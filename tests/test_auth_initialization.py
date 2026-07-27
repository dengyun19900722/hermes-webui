"""Tests for first-time RBAC initialization."""
import pytest
from pathlib import Path

from api.auth import needs_initialization, is_initialized, initialize_first_admin


def test_needs_initialization_empty(tmp_path, monkeypatch):
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    assert needs_initialization() is True
    assert is_initialized() is False


def test_needs_initialization_with_users(tmp_path, monkeypatch):
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    from api.user_store import add_user
    add_user(tmp_path, {"username": "alice", "password_hash": "x", "role": "user"})
    assert needs_initialization() is False
    assert is_initialized() is True


def test_initialize_first_admin(tmp_path, monkeypatch):
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    admin = initialize_first_admin("admin", "secret123")
    assert admin["role"] == "admin"
    assert admin["username"] == "admin"
    assert "id" in admin
    assert "password_hash" in admin
    assert admin["password_hash"] != "secret123"  # 必须 hash
    assert needs_initialization() is False


def test_initialize_first_admin_twice_raises(tmp_path, monkeypatch):
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    initialize_first_admin("admin", "secret123")
    with pytest.raises(ValueError, match="already initialized"):
        initialize_first_admin("admin2", "secret456")


def test_initialize_first_admin_password_is_hashed(tmp_path, monkeypatch):
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    admin = initialize_first_admin("admin", "secret123")
    # Hash 应符合 PBKDF2-SHA256-600k 的格式（64 hex chars）
    import re as _re
    assert _re.match(r"^[0-9a-f]{64}$", admin["password_hash"]), (
        f"expected PBKDF2 hex hash, got {admin['password_hash'][:20]}..."
    )
    # 原始密码不应出现在 hash 中
    assert "secret123" not in admin["password_hash"]
    # 同样的密码调用 _hash_password 应得到相同的 hash（确定性）
    from api.auth import _hash_password
    assert admin["password_hash"] == _hash_password("secret123")