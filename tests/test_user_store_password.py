"""Tests for update_password (api.user_store) and invalidate_all_user_sessions (api.auth).

These are the two backend helpers introduced in Task 1 of the RBAC refactor:
- update_password: replace a user's password_hash on disk
- invalidate_all_user_sessions: kick all sessions for a user_id (with optional keep_token)

Both helpers are pure file/state operations and require no running server.
"""
import json
import tempfile
from pathlib import Path

import pytest

from api.user_store import (
    load_users,
    save_users,
    find_user_by_id,
    update_password,
    _hash_password_for_test,
)


# ─────────────────────────────────────────────────────────────────────────────
# update_password tests
# ─────────────────────────────────────────────────────────────────────────────


def _make_user(state_dir: Path, username: str = "alice") -> dict:
    """Helper: insert a user with a known password hash."""
    save_users(state_dir, [{
        "id": "u-1",
        "username": username,
        "password_hash": _hash_password_for_test("oldpass123"),
        "role": "user",
        "created_at": "2026-08-01T00:00:00Z",
        "last_login": None,
    }])
    return load_users(state_dir)[0]


def test_update_password_changes_hash():
    with tempfile.TemporaryDirectory() as tmp:
        sd = Path(tmp)
        _make_user(sd)
        update_password(sd, "u-1", _hash_password_for_test("newpass123"))
        u = find_user_by_id(sd, "u-1")
        assert u["password_hash"] != _hash_password_for_test("oldpass123")
        assert u["password_hash"] == _hash_password_for_test("newpass123")


def test_update_password_unknown_user_raises():
    with tempfile.TemporaryDirectory() as tmp:
        sd = Path(tmp)
        with pytest.raises(KeyError):
            update_password(sd, "u-nonexistent", _hash_password_for_test("x"))


# ─────────────────────────────────────────────────────────────────────────────
# invalidate_all_user_sessions tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.fixture
def isolated_user_sessions(tmp_path, monkeypatch):
    """Redirect .rbac-sessions.json to tmp_path and clear in-memory cache.

    Tests use the RBAC session helpers (_load_user_sessions / _save_user_sessions)
    — NOT the legacy single-user helpers at lines 126-198 of api/auth.py, which
    expect token->float values. The RBAC sessions store token->{user_id, expires_at}
    dictionaries on disk in STATE_DIR/.rbac-sessions.json.
    """
    from api import auth as auth_mod

    target = tmp_path / ".rbac-sessions.json"
    monkeypatch.setattr(auth_mod, "_USER_SESSIONS_FILE", target)
    monkeypatch.setattr(auth_mod, "_user_sessions", {})
    return target


def test_invalidate_all_sessions_for_user(isolated_user_sessions):
    """Set up .rbac-sessions.json with mixed users, run, verify only u-1's tokens removed."""
    from api.auth import (
        _load_user_sessions,
        _save_user_sessions,
        invalidate_all_user_sessions,
    )
    from api import auth as auth_mod

    auth_mod._user_sessions.update({
        "tok-a": {"user_id": "u-1", "expires_at": 9999999999.0},
        "tok-b": {"user_id": "u-2", "expires_at": 9999999999.0},
        "tok-c": {"user_id": "u-1", "expires_at": 9999999999.0},
    })
    _save_user_sessions()
    removed = invalidate_all_user_sessions("u-1")
    assert removed == 2
    s = _load_user_sessions()
    assert "tok-a" not in s and "tok-c" not in s
    assert "tok-b" in s


def test_invalidate_all_sessions_keeps_current(isolated_user_sessions):
    """keep_token preserves the caller's own session during a self-password-change."""
    from api.auth import (
        _load_user_sessions,
        _save_user_sessions,
        invalidate_all_user_sessions,
    )
    from api import auth as auth_mod

    auth_mod._user_sessions.update({
        "tok-current": {"user_id": "u-1", "expires_at": 9999999999.0},
        "tok-other": {"user_id": "u-1", "expires_at": 9999999999.0},
    })
    _save_user_sessions()
    removed = invalidate_all_user_sessions("u-1", keep_token="tok-current")
    assert removed == 1
    s = _load_user_sessions()
    assert "tok-current" in s
    assert "tok-other" not in s