"""Per-user session storage backed by JSON files.

Each user has their own directory under sessions_dir:
    sessions/{user_id}/sessions.json
    sessions/{user_id}/shares.json

Sesssions are isolated by directory: alice cannot read bob's sessions
even by guessing IDs, since get_session() walks only the caller's
sessions file.
"""
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


def _user_sessions_file(sessions_dir: Path, user_id: str) -> Path:
    user_dir = sessions_dir / user_id
    user_dir.mkdir(parents=True, exist_ok=True)
    return user_dir / "sessions.json"


def _atomic_write(path: Path, data: dict) -> None:
    """Atomic write: temp file + replace."""
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def load_user_sessions(sessions_dir: Path, user_id: str) -> list[dict[str, Any]]:
    """Load all sessions for a user. Returns empty list if file missing or corrupt."""
    path = _user_sessions_file(sessions_dir, user_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            sessions = data.get("sessions", [])
            return sessions if isinstance(sessions, list) else []
        return []
    except Exception:
        return []


def save_user_sessions(sessions_dir: Path, user_id: str, sessions: list[dict]) -> None:
    """Atomically persist user's sessions."""
    path = _user_sessions_file(sessions_dir, user_id)
    _atomic_write(path, {"sessions": sessions})


def list_user_sessions(sessions_dir: Path, user_id: str) -> list[dict[str, Any]]:
    """Return all sessions owned by user_id."""
    return load_user_sessions(sessions_dir, user_id)


def add_session(sessions_dir: Path, user_id: str, session: dict) -> dict:
    """Add a new session for user_id. Auto-generates id, owner_id, timestamps."""
    now = datetime.utcnow().isoformat() + "Z"
    session.setdefault("id", str(uuid.uuid4()))
    session.setdefault("owner_id", user_id)
    session.setdefault("created_at", now)
    session.setdefault("updated_at", now)
    sessions = load_user_sessions(sessions_dir, user_id)
    sessions.append(session)
    save_user_sessions(sessions_dir, user_id, sessions)
    return session


def get_session(sessions_dir: Path, user_id: str, session_id: str) -> dict | None:
    """Get a specific session by id for a user. Returns None if not found."""
    for s in load_user_sessions(sessions_dir, user_id):
        if s.get("id") == session_id:
            return s
    return None


def delete_session(sessions_dir: Path, user_id: str, session_id: str) -> bool:
    """Delete a session. Returns True if deleted, False if not found."""
    sessions = load_user_sessions(sessions_dir, user_id)
    new_sessions = [s for s in sessions if s.get("id") != session_id]
    if len(new_sessions) == len(sessions):
        return False
    save_user_sessions(sessions_dir, user_id, new_sessions)
    return True


def update_session(
    sessions_dir: Path, user_id: str, session_id: str, updates: dict
) -> dict | None:
    """Merge updates into an existing session. Returns updated session or None."""
    sessions = load_user_sessions(sessions_dir, user_id)
    for i, s in enumerate(sessions):
        if s.get("id") == session_id:
            s.update(updates)
            s["updated_at"] = datetime.utcnow().isoformat() + "Z"
            sessions[i] = s
            save_user_sessions(sessions_dir, user_id, sessions)
            return s
    return None


def list_all_sessions_for_admin(sessions_dir: Path) -> list[dict[str, Any]]:
    """Admin-only: list all sessions across all users."""
    if not sessions_dir.exists():
        return []
    all_sessions = []
    for user_dir in sessions_dir.iterdir():
        if not user_dir.is_dir():
            continue
        user_id = user_dir.name
        all_sessions.extend(load_user_sessions(sessions_dir, user_id))
    return all_sessions