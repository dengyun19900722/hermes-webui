"""Admin user management API.

All operations log an audit event via api.audit.write() so the admin
panel can show a chronological record of who did what. The audit calls
use category='rbac' so they're easy to filter out from HTTP request logs.

Safety: cannot delete the last remaining admin (prevents self-lock).
"""
from datetime import datetime
from pathlib import Path
from typing import Any

from api import audit as _audit
from api.auth import _hash_password, _state_dir
from api.user_store import (
    add_user as _add_user,
    find_user_by_id,
    find_user_by_username,
    load_users,
    save_users,
)


def _strip_sensitive(user: dict) -> dict:
    """Remove password_hash and other sensitive fields before returning to caller."""
    return {k: v for k, v in user.items() if k != "password_hash"}


def list_users() -> list[dict[str, Any]]:
    """List all users (without password hashes)."""
    users = load_users(_state_dir())
    return [_strip_sensitive(u) for u in users]


def create_user(username: str, password: str, role: str = "user") -> dict:
    """Create a new user. Raises ValueError on duplicate username or invalid role."""
    if role not in ("user", "admin"):
        raise ValueError(f"Invalid role: {role}")
    if find_user_by_username(_state_dir(), username):
        raise ValueError(f"User already exists: {username}")
    user = _add_user(_state_dir(), {
        "username": username,
        "password_hash": _hash_password(password),
        "role": role,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "last_login": None,
    })
    _audit.write(
        category="rbac",
        action="user.create",
        actor_id="system", actor_name="system",
        target_type="user", target_id=user["id"], target_name=username,
        details={"role": role},
    )
    return _strip_sensitive(user)


def update_user_role(
    user_id: str, new_role: str,
    *, actor_id: str = "system", actor_name: str = "system",
) -> dict | None:
    """Update a user's role. Returns updated user (no hash) or None if not found."""
    if new_role not in ("user", "admin"):
        raise ValueError(f"Invalid role: {new_role}")
    users = load_users(_state_dir())
    for user in users:
        if user.get("id") == user_id:
            old_role = user.get("role")
            user["role"] = new_role
            save_users(_state_dir(), users)
            _audit.write(
                category="rbac",
                action="user.role_change",
                actor_id=actor_id, actor_name=actor_name,
                target_type="user", target_id=user_id, target_name=user.get("username"),
                details={"old_role": old_role, "new_role": new_role},
            )
            return _strip_sensitive(user)
    return None


def delete_user(
    user_id: str,
    *, actor_id: str = "system", actor_name: str = "system",
) -> bool:
    """Delete a user. Cannot delete the last remaining admin."""
    users = load_users(_state_dir())
    target = next((u for u in users if u.get("id") == user_id), None)
    if not target:
        return False
    # 防止删除最后一个 admin（自锁保护）
    if target.get("role") == "admin":
        admin_count = sum(1 for u in users if u.get("role") == "admin")
        if admin_count <= 1:
            return False
    users = [u for u in users if u.get("id") != user_id]
    save_users(_state_dir(), users)
    _audit.write(
        category="rbac",
        action="user.delete",
        actor_id=actor_id, actor_name=actor_name,
        target_type="user", target_id=user_id, target_name=target.get("username"),
    )
    return True