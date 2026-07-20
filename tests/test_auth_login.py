"""Tests for multi-user login flow."""
import time
import pytest
from pathlib import Path

from api.auth import (
    authenticate, create_user_session, get_user_from_session,
    invalidate_user_session, verify_password_against_hash, _state_dir, _hash_password,
)
from api.user_store import add_user


def _create_test_user(state_dir: Path, **overrides) -> dict:
    """Helper: create a test user with PBKDF2-hashed password."""
    password = overrides.pop("password", "secret123")
    defaults = {
        "username": "alice",
        "password_hash": _hash_password(password),
        "role": "user",
    }
    defaults.update(overrides)
    return add_user(state_dir, defaults)


def test_authenticate_success(tmp_path, monkeypatch):
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    _create_test_user(tmp_path, password="secret123")
    user = authenticate("alice", "secret123")
    assert user["username"] == "alice"
    assert user["role"] == "user"


def test_authenticate_wrong_password(tmp_path, monkeypatch):
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    _create_test_user(tmp_path, password="secret123")
    assert authenticate("alice", "wrong") is None


def test_authenticate_unknown_user(tmp_path, monkeypatch):
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    assert authenticate("nobody", "anything") is None


def test_session_lifecycle(tmp_path, monkeypatch):
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    user = _create_test_user(tmp_path)
    token = create_user_session(user["id"])
    assert token and len(token) > 32  # hex token should be 64 chars
    fetched = get_user_from_session(token)
    assert fetched is not None
    assert fetched["id"] == user["id"]


def test_session_invalid_token_returns_none():
    assert get_user_from_session("nonexistent-token") is None


def test_invalidate_session(tmp_path, monkeypatch):
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    user = _create_test_user(tmp_path)
    token = create_user_session(user["id"])
    assert get_user_from_session(token) is not None
    invalidate_user_session(token)
    assert get_user_from_session(token) is None


def test_verify_password_against_hash():
    h = _hash_password("secret")
    assert verify_password_against_hash("secret", h) is True
    assert verify_password_against_hash("wrong", h) is False


def test_session_expires(tmp_path, monkeypatch):
    """Expired sessions are invalidated lazily on lookup."""
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    user = _create_test_user(tmp_path)
    token = create_user_session(user["id"])

    # 直接修改内部 session 表为已过期
    from api import auth as auth_mod
    auth_mod._user_sessions[token]["expires_at"] = time.time() - 1
    assert get_user_from_session(token) is None


def test_authenticate_updates_last_login(tmp_path, monkeypatch):
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    user = _create_test_user(tmp_path)
    assert user.get("last_login") is None
    authenticated = authenticate("alice", "secret123")
    assert authenticated is not None
    assert authenticated.get("last_login") is not None