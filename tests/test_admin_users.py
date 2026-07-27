"""Tests for admin user management API."""
import pytest
from pathlib import Path

from api.admin import list_users, create_user, update_user_role, delete_user


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr("api.admin._state_dir", lambda: tmp_path)
    from api.auth import initialize_first_admin, _state_dir
    # initialize_first_admin uses api.auth._state_dir, not api.admin._state_dir
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    initialize_first_admin("admin", "admin123")
    return tmp_path


def test_list_users_returns_admin(setup):
    users = list_users()
    assert len(users) == 1
    assert users[0]["username"] == "admin"
    assert users[0]["role"] == "admin"
    assert "password_hash" not in users[0]  # 不应泄露 hash


def test_list_users_excludes_password_hash(setup):
    users = list_users()
    for u in users:
        assert "password_hash" not in u


def test_create_user(setup):
    user = create_user("alice", "alice123", "user")
    assert user["username"] == "alice"
    assert user["role"] == "user"
    assert "password_hash" not in user
    assert "id" in user
    # 持久化到磁盘
    from api.user_store import find_user_by_username
    assert find_user_by_username(setup, "alice") is not None


def test_create_user_duplicate_username_raises(setup):
    create_user("alice", "alice123", "user")
    with pytest.raises(ValueError, match="already exists"):
        create_user("alice", "alice456", "user")


def test_create_user_invalid_role_raises(setup):
    with pytest.raises(ValueError, match="Invalid role"):
        create_user("bob", "bob123", "superuser")


def test_update_user_role(setup):
    user = create_user("alice", "alice123", "user")
    updated = update_user_role(user["id"], "admin")
    assert updated is not None
    assert updated["role"] == "admin"


def test_update_user_role_invalid_role_raises(setup):
    user = create_user("alice", "alice123", "user")
    with pytest.raises(ValueError, match="Invalid role"):
        update_user_role(user["id"], "superuser")


def test_update_user_role_unknown_user_returns_none(setup):
    assert update_user_role("nonexistent-id", "admin") is None


def test_delete_user(setup):
    user = create_user("alice", "alice123", "user")
    assert delete_user(user["id"]) is True
    from api.user_store import find_user_by_username
    assert find_user_by_username(setup, "alice") is None


def test_cannot_delete_last_admin(setup):
    """系统中唯一的 admin 不能被删除（防止自锁）。"""
    admin_id = None
    for u in list_users():
        if u["role"] == "admin":
            admin_id = u["id"]
            break
    assert admin_id is not None
    assert delete_user(admin_id) is False
    # 仍在
    from api.user_store import find_user_by_id
    assert find_user_by_id(setup, admin_id) is not None


def test_can_delete_admin_when_multiple_exist(setup):
    """存在多个 admin 时,可以删除其中一个。"""
    a1 = list_users()[0]  # 第一个 admin (initialize_first_admin 创建)
    a2 = create_user("admin2", "admin123", "admin")
    assert delete_user(a1["id"]) is True
    from api.user_store import find_user_by_username
    assert find_user_by_username(setup, "admin2") is not None


def test_delete_nonexistent_user_returns_false(setup):
    assert delete_user("nonexistent-id") is False


def test_create_user_audit_event(setup, monkeypatch):
    """create_user / delete_user / role_change 应记录审计事件。"""
    from api import audit as audit_mod
    captured = []

    def fake_write(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(audit_mod, "write", fake_write)
    # admin 模块的 audit.write 已被 monkeypatch; 重新触发
    user = create_user("alice", "alice123", "user")
    update_user_role(user["id"], "admin")
    delete_user(user["id"])
    actions = [c["action"] for c in captured]
    assert "user.create" in actions
    assert "user.role_change" in actions
    assert "user.delete" in actions