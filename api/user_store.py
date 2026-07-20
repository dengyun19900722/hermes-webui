"""Local-file user store backed by users.json.

Stores multi-user accounts for the RBAC permission system. Each user record:
    {
        "id": "uuid",
        "username": "...",
        "password_hash": "pbkdf2_sha256_xxx",
        "role": "user|admin",
        "created_at": "ISO8601",
        "last_login": "ISO8601" | null
    }

Persistence uses atomic write (temp file + replace) so a crash mid-write
never leaves a truncated users.json on disk.
"""
import json
import uuid
from pathlib import Path
from typing import Any


USERS_FILE = "users.json"


def _users_file(state_dir: Path) -> Path:
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / USERS_FILE


def load_users(state_dir: Path) -> list[dict[str, Any]]:
    """Load users from users.json. Returns empty list if file missing or corrupt."""
    path = _users_file(state_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            users = data.get("users", [])
            return users if isinstance(users, list) else []
        return []
    except Exception:
        return []


def save_users(state_dir: Path, users: list[dict[str, Any]]) -> None:
    """Atomically persist users to users.json."""
    path = _users_file(state_dir)
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(
            json.dumps({"users": users}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def find_user_by_username(state_dir: Path, username: str) -> dict[str, Any] | None:
    """Find a user by username (case-sensitive). Returns None if not found."""
    for user in load_users(state_dir):
        if user.get("username") == username:
            return user
    return None


def find_user_by_id(state_dir: Path, user_id: str) -> dict[str, Any] | None:
    """Find a user by id. Returns None if not found."""
    for user in load_users(state_dir):
        if user.get("id") == user_id:
            return user
    return None


def add_user(state_dir: Path, user: dict[str, Any]) -> dict[str, Any]:
    """Add a new user with a generated UUID. Persists to disk and returns the user."""
    if "id" not in user:
        user["id"] = str(uuid.uuid4())
    users = load_users(state_dir)
    users.append(user)
    save_users(state_dir, users)
    return user