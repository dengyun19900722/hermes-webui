"""Session sharing between users (user-to-user and token-link).

Storage: each user's directory contains a shares.json:
    sessions/{user_id}/shares.json
        {
          "outgoing": [<shares created by this user>],
          "incoming": [<shares sent TO this user>]
        }

When alice shares to bob, alice's outgoing gets the canonical record and
bob's incoming gets a mirror copy with from_user_id set. Revoke walks
both sides to keep them in sync.

Token shares don't propagate to any incoming list — anyone with the token
URL can resolve via ``resolve_share_token()``.
"""
import json
import secrets
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from api.session_store import _atomic_write, load_user_sessions


def _shares_file(sessions_dir: Path, user_id: str) -> Path:
    user_dir = sessions_dir / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir / "shares.json"


def _load_shares(sessions_dir: Path, user_id: str) -> dict:
    """Load shares file for user. Returns {outgoing: [...], incoming: [...]}."""
    path = _shares_file(sessions_dir, user_id)
    if not path.exists():
        return {"outgoing": [], "incoming": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {
                "outgoing": data.get("outgoing", []) if isinstance(data.get("outgoing"), list) else [],
                "incoming": data.get("incoming", []) if isinstance(data.get("incoming"), list) else [],
            }
    except Exception:
        pass
    return {"outgoing": [], "incoming": []}


def _save_shares(sessions_dir: Path, user_id: str, shares: dict) -> None:
    _atomic_write(_shares_file(sessions_dir, user_id), shares)


def share_session_to_user(
    sessions_dir: Path, from_user_id: str, to_user_id: str, session_id: str
) -> dict:
    """Share a session from one user to another user. Mirrors to both sides."""
    now = datetime.utcnow().isoformat() + "Z"
    share = {
        "id": str(uuid.uuid4()),
        "to_user_id": to_user_id,
        "session_id": session_id,
        "type": "user",
        "created_at": now,
    }
    # 写入 from_user 的 outgoing
    shares = _load_shares(sessions_dir, from_user_id)
    shares["outgoing"].append(share)
    _save_shares(sessions_dir, from_user_id, shares)
    # 写入 to_user 的 incoming（镜像 + from_user_id）
    incoming_shares = _load_shares(sessions_dir, to_user_id)
    incoming_shares["incoming"].append({
        **share,
        "from_user_id": from_user_id,
    })
    _save_shares(sessions_dir, to_user_id, incoming_shares)
    # 审计 (失败不应阻塞业务)
    try:
        from api import audit as _audit
        _audit.write(
            category="rbac",
            action="session.share",
            actor_id=from_user_id,
            actor_name=from_user_id,  # 业务层不持有 username
            target_type="session", target_id=session_id, target_name=to_user_id,
            details={"method": "user", "to_user_id": to_user_id, "share_id": share["id"]},
        )
    except Exception:
        pass
    return share


def share_session_with_token(
    sessions_dir: Path, from_user_id: str, session_id: str
) -> dict:
    """Generate a token link for a session. Stores in outgoing only."""
    now = datetime.utcnow().isoformat() + "Z"
    token = secrets.token_urlsafe(32)
    share = {
        "id": str(uuid.uuid4()),
        "session_id": session_id,
        "type": "token",
        "token": token,
        "created_at": now,
    }
    shares = _load_shares(sessions_dir, from_user_id)
    shares["outgoing"].append(share)
    _save_shares(sessions_dir, from_user_id, shares)
    return share


def list_outgoing_shares(sessions_dir: Path, user_id: str) -> list[dict]:
    """List shares created by this user (both user-to-user and token)."""
    return _load_shares(sessions_dir, user_id)["outgoing"]


def list_incoming_shares(sessions_dir: Path, user_id: str) -> list[dict]:
    """List shares received by this user (user-to-user only)."""
    return _load_shares(sessions_dir, user_id)["incoming"]


def list_shared_sessions(sessions_dir: Path, user_id: str) -> list[dict]:
    """List sessions shared to this user, enriched with session details.

    Returns a list of:
        {
          "share_id": ...,
          "from_user_id": ...,
          "session": <full session dict from owner's file>,
          "shared_at": "ISO8601"
        }
    """
    incoming = list_incoming_shares(sessions_dir, user_id)
    result = []
    for share in incoming:
        from_user_id = share.get("from_user_id")
        session_id = share.get("session_id")
        if not from_user_id or not session_id:
            continue
        # 从分享者的会话列表中读取会话详情
        from_sessions = load_user_sessions(sessions_dir, from_user_id)
        session = next((s for s in from_sessions if s.get("id") == session_id), None)
        if session:
            result.append({
                "share_id": share["id"],
                "from_user_id": from_user_id,
                "session": session,
                "shared_at": share.get("created_at"),
            })
    return result


def revoke_share(sessions_dir: Path, user_id: str, share_id: str) -> bool:
    """Revoke an outgoing share. For user-to-user, also clears recipient's incoming.

    Returns True if a share was removed, False if not found.
    """
    shares = _load_shares(sessions_dir, user_id)
    target = next((s for s in shares["outgoing"] if s.get("id") == share_id), None)
    if not target:
        return False

    # 移除 outgoing
    shares["outgoing"] = [s for s in shares["outgoing"] if s.get("id") != share_id]
    _save_shares(sessions_dir, user_id, shares)

    # 如果是 user 类型，同步移除对方的 incoming
    if target.get("type") == "user":
        to_user_id = target.get("to_user_id")
        if to_user_id:
            to_shares = _load_shares(sessions_dir, to_user_id)
            to_shares["incoming"] = [
                s for s in to_shares["incoming"] if s.get("id") != share_id
            ]
            _save_shares(sessions_dir, to_user_id, to_shares)
    return True


def resolve_share_token(sessions_dir: Path, token: str) -> dict | None:
    """Resolve a share token to the underlying session info.

    Walks every user's outgoing shares to find a token match. Returns:
        {
          "from_user_id": ...,
          "session_id": ...,
          "session": <full session dict>,
          "shared_at": "ISO8601"
        }
    or None if the token is not found / revoked.
    """
    if not token or not sessions_dir.exists():
        return None
    for user_dir in sessions_dir.iterdir():
        if not user_dir.is_dir():
            continue
        from_user_id = user_dir.name
        shares = _load_shares(sessions_dir, from_user_id)
        for share in shares["outgoing"]:
            if share.get("type") == "token" and share.get("token") == token:
                sessions = load_user_sessions(sessions_dir, from_user_id)
                session = next(
                    (s for s in sessions if s.get("id") == share.get("session_id")),
                    None,
                )
                if session:
                    return {
                        "from_user_id": from_user_id,
                        "session_id": share.get("session_id"),
                        "session": session,
                        "shared_at": share.get("created_at"),
                    }
    return None