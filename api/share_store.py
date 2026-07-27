"""Session share store backed by shares.json.

Stores session share records for the RBAC permission system. Each record:

    {
        "id": "uuid",
        "session_id": "session_uuid",
        "owner_id": "user_uuid",
        "owner_name": "username",
        "to_user_id": "user_uuid" | null,
        "to_username": "username" | null,
        "type": "user" | "token",
        "token": "hex" | null,
        "created_at": "ISO8601",
        "expires_at": "ISO8601" | null
    }

- ``type == "user"`` shares a session with a specific user (to_user_id set).
- ``type == "token"`` exposes a session via a public read-only link (token set).

Persistence uses atomic write (temp file + replace), mirroring
``api/user_store.py``. An in-memory cache keyed on file mtime avoids a disk
read on every sidebar / visibility check; write operations invalidate it.

Read failures degrade to an empty share set so the session list never breaks
because of a corrupt shares file.
"""
import json
import os
import secrets
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

SHARES_FILE = "shares.json"

_LOCK = threading.RLock()
_cache: dict[str, Any] = {"mtime": None, "shares": None}


def _shares_file(state_dir: Path) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / SHARES_FILE


def _now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


def load_shares(state_dir: Path) -> list[dict[str, Any]]:
    """Load share records. Returns [] if file missing or corrupt.

    Cached on file mtime so repeated calls within the same second do not
    re-read the file. Callers must not mutate the returned list.
    """
    path = _shares_file(state_dir)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    with _LOCK:
        if _cache["shares"] is not None and _cache["mtime"] == mtime:
            return list(_cache["shares"])
    shares: list[dict[str, Any]] = []
    if mtime is not None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                raw = data.get("shares", [])
                if isinstance(raw, list):
                    shares = [s for s in raw if isinstance(s, dict)]
        except Exception:
            shares = []
    with _LOCK:
        _cache["mtime"] = mtime
        _cache["shares"] = list(shares)
    return shares


def save_shares(state_dir: Path, shares: list[dict[str, Any]]) -> None:
    """Atomically persist share records and refresh the cache."""
    path = _shares_file(state_dir)
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(
            json.dumps({"shares": shares}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise
    with _LOCK:
        try:
            _cache["mtime"] = path.stat().st_mtime
        except OSError:
            _cache["mtime"] = None
        _cache["shares"] = list(shares)


def invalidate_cache() -> None:
    with _LOCK:
        _cache["mtime"] = None
        _cache["shares"] = None


def _expires(share: dict[str, Any]) -> bool:
    raw = str(share.get("expires_at") or "").strip()
    if not raw:
        return False
    try:
        exp = datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except Exception:
        return False
    return exp <= datetime.utcnow().timestamp()


def _live(shares: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [s for s in shares if not _expires(s)]


def list_shares_for_session(state_dir: Path, session_id: str) -> list[dict[str, Any]]:
    sid = str(session_id or "").strip()
    if not sid:
        return []
    return [s for s in _live(load_shares(state_dir)) if str(s.get("session_id") or "") == sid]


def list_shares_for_user(state_dir: Path, user_id: str) -> list[dict[str, Any]]:
    """Return user-type shares addressed to ``user_id`` (incoming shares)."""
    uid = str(user_id or "").strip()
    if not uid:
        return []
    return [
        s for s in _live(load_shares(state_dir))
        if s.get("type") == "user" and str(s.get("to_user_id") or "") == uid
    ]


def shared_session_ids_for_user(state_dir: Path, user_id: str) -> set[str]:
    """Set of session ids shared to ``user_id`` — used by sidebar filtering."""
    return {str(s.get("session_id") or "") for s in list_shares_for_user(state_dir, user_id)}


def find_share_by_token(state_dir: Path, token: str) -> dict[str, Any] | None:
    tok = str(token or "").strip()
    if not tok:
        return None
    for share in _live(load_shares(state_dir)):
        if share.get("type") == "token" and secrets.compare_digest(
            str(share.get("token") or ""), tok
        ):
            return share
    return None


def _existing_user_share(
    shares: list[dict[str, Any]], session_id: str, to_user_id: str
) -> dict[str, Any] | None:
    for share in shares:
        if (
            share.get("type") == "user"
            and str(share.get("session_id") or "") == session_id
            and str(share.get("to_user_id") or "") == to_user_id
            and not _expires(share)
        ):
            return share
    return None


def add_user_share(
    state_dir: Path,
    *,
    session_id: str,
    owner_id: str,
    owner_name: str,
    to_user_id: str,
    to_username: str,
) -> dict[str, Any]:
    """Share a session with a user. Idempotent: returns the existing record."""
    with _LOCK:
        shares = load_shares(state_dir)
        existing = _existing_user_share(shares, session_id, to_user_id)
        if existing is not None:
            return existing
        record = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "owner_id": owner_id,
            "owner_name": owner_name,
            "to_user_id": to_user_id,
            "to_username": to_username,
            "type": "user",
            "token": None,
            "created_at": _now_iso(),
            "expires_at": None,
        }
        shares.append(record)
        save_shares(state_dir, shares)
        return record


def add_token_share(
    state_dir: Path,
    *,
    session_id: str,
    owner_id: str,
    owner_name: str,
    expires_at: str | None = None,
) -> dict[str, Any]:
    """Create (or reuse) a public token link for a session."""
    with _LOCK:
        shares = load_shares(state_dir)
        for share in shares:
            if (
                share.get("type") == "token"
                and str(share.get("session_id") or "") == session_id
                and not _expires(share)
            ):
                return share
        record = {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "owner_id": owner_id,
            "owner_name": owner_name,
            "to_user_id": None,
            "to_username": None,
            "type": "token",
            "token": secrets.token_hex(24),
            "created_at": _now_iso(),
            "expires_at": expires_at,
        }
        shares.append(record)
        save_shares(state_dir, shares)
        return record


def remove_share(state_dir: Path, share_id: str) -> bool:
    """Remove a share record by id. Returns True when something was removed."""
    rid = str(share_id or "").strip()
    if not rid:
        return False
    with _LOCK:
        shares = load_shares(state_dir)
        remaining = [s for s in shares if str(s.get("id") or "") != rid]
        if len(remaining) == len(shares):
            return False
        save_shares(state_dir, remaining)
        return True


def remove_shares_for_session(state_dir: Path, session_id: str) -> int:
    """Remove all shares for a session (called on session delete)."""
    sid = str(session_id or "").strip()
    if not sid:
        return 0
    with _LOCK:
        shares = load_shares(state_dir)
        remaining = [s for s in shares if str(s.get("session_id") or "") != sid]
        removed = len(shares) - len(remaining)
        if removed:
            save_shares(state_dir, remaining)
        return removed
