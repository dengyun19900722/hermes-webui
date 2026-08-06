"""Tests for PUT /api/admin/users/{user_id}/password (Task 3 of the RBAC refactor).

This endpoint lets an admin reset *another* user's password. We verify:

  * Happy path: admin resets target user → 200, password_hash rewritten,
    ALL sessions for the target user kicked, audit event written.
  * Non-admin caller → 403 ``admin_required``.
  * Unauthenticated request → 401 ``auth_required``.
  * Unknown user_id → 404 ``user_not_found``.
  * Missing ``new_password`` in body → 400 ``missing_field``.
  * Complexity is BYPASSED — admin may set a short password (5 chars).
  * Dispatcher routes ``PUT /api/admin/users/{id}/password`` correctly.

The handler signature is ``handle_admin_reset_password(handler, parsed, user_id)``,
so tests pass the user_id explicitly. We mock ``_read_json_body`` /
``_current_user`` / ``_send_json`` so the test does not need a real HTTP
round-trip; ``user_store`` + ``auth`` are left intact so we can verify
on-disk side effects (hash rewritten, sessions removed, audit written).
"""
import json
from unittest.mock import patch

import pytest

from api import rbac_routes as rmod
from api.auth import (
    _hash_password,
    create_user_session,
    invalidate_all_user_sessions,
)
from api.user_store import find_user_by_id, save_users


# ─────────────────────────────────────────────────────────────────────────────
# Test scaffolding
# ─────────────────────────────────────────────────────────────────────────────


def _patch_state_dir(monkeypatch, tmp_path):
    """Point every state_dir helper at tmp_path.

    RBAC helpers use ``STATE_DIR`` imported from ``api.config``; we patch
    the rmod-local reference so disk writes (user_store, sessions,
    audit) land in a throwaway directory.
    """
    from api import auth as auth_mod
    from api import admin as admin_mod

    monkeypatch.setattr(auth_mod, "_state_dir", lambda: tmp_path)
    monkeypatch.setattr(admin_mod, "_state_dir", lambda: tmp_path)
    monkeypatch.setattr(rmod, "STATE_DIR", tmp_path)


def _seed_users(tmp_path):
    """Write a deterministic users.json with one admin + one victim."""
    save_users(tmp_path, [
        {
            "id": "u-admin",
            "username": "admin",
            "password_hash": _hash_password("AdminPass1"),
            "role": "admin",
            "created_at": "2026-08-01T00:00:00Z",
            "last_login": None,
        },
        {
            "id": "u-victim",
            "username": "victim",
            "password_hash": _hash_password("VictimPass1"),
            "role": "user",
            "created_at": "2026-08-01T00:00:00Z",
            "last_login": None,
        },
    ])


class _CapturedResponse:
    """Track the last (status, body) written via rmod._send_json."""

    def __init__(self):
        self.code = None
        self.body = None

    def __call__(self, _handler, code, body):
        self.code = code
        self.body = body


def _call_reset(user_id, *, caller, body, captured):
    """Invoke the handler with the four external seams mocked.

    Returns the handler's return value (always True — the handler
    short-circuits and reports handled to the dispatcher).
    """
    with patch.object(rmod, "_read_json_body", return_value=body), \
         patch.object(rmod, "_current_user", return_value=caller), \
         patch.object(rmod, "_send_json", side_effect=captured):
        return rmod.handle_admin_reset_password(None, None, user_id)


# ─────────────────────────────────────────────────────────────────────────────
# handle_admin_reset_password — direct handler tests
# ─────────────────────────────────────────────────────────────────────────────


def test_admin_reset_password_happy_path(tmp_path, monkeypatch):
    """Admin resets another user's password → 200, hash updated, all
    sessions for the target user are invalidated, audit event written."""
    _patch_state_dir(monkeypatch, tmp_path)
    _seed_users(tmp_path)
    admin = {"id": "u-admin", "username": "admin", "role": "admin"}
    victim_before = find_user_by_id(tmp_path, "u-victim")
    assert victim_before is not None
    old_hash = victim_before["password_hash"]

    # Two sessions for the victim → both must be kicked.
    tok_a = create_user_session("u-victim")
    tok_b = create_user_session("u-victim")
    assert tok_a != tok_b
    # And one for the admin — must SURVIVE (different user).
    tok_admin = create_user_session("u-admin")

    captured = _CapturedResponse()
    result = _call_reset(
        "u-victim",
        caller=admin,
        body={"new_password": "ResetPass99"},
        captured=captured,
    )
    assert result is True

    # Response
    assert captured.code == 200
    assert captured.body == {"ok": True}

    # Password hash on disk has been replaced.
    after = find_user_by_id(tmp_path, "u-victim")
    assert after is not None
    assert after["password_hash"] != old_hash
    assert after["password_hash"] == _hash_password("ResetPass99")
    # Old password no longer verifies; new password does.
    assert _hash_password("VictimPass1") != after["password_hash"]
    assert _hash_password("ResetPass99") == after["password_hash"]

    # Both victim sessions are gone; admin session untouched.
    from api.auth import _load_user_sessions
    sessions = _load_user_sessions()
    assert tok_a not in sessions, "victim session A must be invalidated"
    assert tok_b not in sessions, "victim session B must be invalidated"
    assert tok_admin in sessions, "admin session must NOT be invalidated"


def test_admin_reset_password_writes_audit_event(tmp_path, monkeypatch):
    """Audit log records category='rbac', action='password.reset', with
    actor_id (admin) and target_id (victim)."""
    _patch_state_dir(monkeypatch, tmp_path)
    _seed_users(tmp_path)
    admin = {"id": "u-admin", "username": "admin", "role": "admin"}

    captured_calls = []
    real_write = rmod._audit.write

    def spy_write(*args, **kwargs):
        captured_calls.append((args, kwargs))

    monkeypatch.setattr(rmod._audit, "write", spy_write)

    resp = _CapturedResponse()
    _call_reset("u-victim", caller=admin,
                body={"new_password": "ResetPass99"}, captured=resp)

    assert resp.code == 200
    assert captured_calls, "expected at least one audit write"
    last_kwargs = captured_calls[-1][1]
    assert last_kwargs.get("category") == "rbac"
    assert last_kwargs.get("action") == "password.reset"
    assert last_kwargs.get("actor_id") == "u-admin"
    assert last_kwargs.get("actor_name") == "admin"
    assert last_kwargs.get("target_id") == "u-victim"
    assert last_kwargs.get("target_name") == "victim"
    assert last_kwargs.get("target_type") == "user"


def test_admin_reset_password_non_admin_forbidden(tmp_path, monkeypatch):
    """Non-admin caller → 403 ``admin_required``; no disk side-effects."""
    _patch_state_dir(monkeypatch, tmp_path)
    _seed_users(tmp_path)
    regular = {"id": "u-victim", "username": "victim", "role": "user"}
    victim_before = find_user_by_id(tmp_path, "u-victim")
    old_hash = victim_before["password_hash"]

    resp = _CapturedResponse()
    _call_reset("u-victim", caller=regular,
                body={"new_password": "Whatever1"}, captured=resp)

    assert resp.code == 403
    assert resp.body == {"error": "admin_required"}

    # Disk state untouched.
    after = find_user_by_id(tmp_path, "u-victim")
    assert after["password_hash"] == old_hash


def test_admin_reset_password_unauthenticated_returns_401(tmp_path, monkeypatch):
    """No caller (no cookie) → 401 ``auth_required``."""
    _patch_state_dir(monkeypatch, tmp_path)
    _seed_users(tmp_path)

    resp = _CapturedResponse()
    _call_reset("u-victim", caller=None,
                body={"new_password": "Whatever1"}, captured=resp)

    assert resp.code == 401
    assert resp.body == {"error": "auth_required"}


def test_admin_reset_password_unknown_user_404(tmp_path, monkeypatch):
    """Admin tries to reset a user_id that doesn't exist → 404."""
    _patch_state_dir(monkeypatch, tmp_path)
    _seed_users(tmp_path)
    admin = {"id": "u-admin", "username": "admin", "role": "admin"}

    resp = _CapturedResponse()
    _call_reset("u-ghost", caller=admin,
                body={"new_password": "Whatever1"}, captured=resp)

    assert resp.code == 404
    assert resp.body == {"error": "user_not_found"}


def test_admin_reset_password_bypasses_complexity(tmp_path, monkeypatch):
    """Admin may set a short (5-char) password — complexity is intentionally
    skipped for the admin-reset path."""
    _patch_state_dir(monkeypatch, tmp_path)
    _seed_users(tmp_path)
    admin = {"id": "u-admin", "username": "admin", "role": "admin"}

    resp = _CapturedResponse()
    _call_reset("u-victim", caller=admin,
                body={"new_password": "abcde"},  # 5 chars, no digit
                captured=resp)

    assert resp.code == 200
    assert resp.body == {"ok": True}
    after = find_user_by_id(tmp_path, "u-victim")
    assert after["password_hash"] == _hash_password("abcde")


def test_admin_reset_password_missing_new_password(tmp_path, monkeypatch):
    """Empty / missing ``new_password`` field → 400 ``missing_field``."""
    _patch_state_dir(monkeypatch, tmp_path)
    _seed_users(tmp_path)
    admin = {"id": "u-admin", "username": "admin", "role": "admin"}

    for bad_body in [
        {},
        {"new_password": ""},
        {"new_password": None},
    ]:
        resp = _CapturedResponse()
        _call_reset("u-victim", caller=admin, body=bad_body, captured=resp)
        assert resp.code == 400
        assert resp.body == {"error": "missing_field"}


# ─────────────────────────────────────────────────────────────────────────────
# Dispatcher test
# ─────────────────────────────────────────────────────────────────────────────


def test_dispatcher_routes_admin_reset_password(tmp_path, monkeypatch):
    """``try_handle_rbac`` must dispatch ``PUT /api/admin/users/{id}/password``
    to ``handle_admin_reset_password`` and return True."""
    _patch_state_dir(monkeypatch, tmp_path)
    _seed_users(tmp_path)
    admin = {"id": "u-admin", "username": "admin", "role": "admin"}

    captured = _CapturedResponse()
    with patch.object(rmod, "_current_user", return_value=admin), \
         patch.object(rmod, "_read_json_body", return_value={"new_password": "ResetPass99"}), \
         patch.object(rmod, "_send_json", side_effect=captured):
        from unittest.mock import MagicMock
        parsed = MagicMock()
        parsed.path = "/api/admin/users/u-victim/password"
        parsed.query = ""
        handled = rmod.try_handle_rbac("PUT", parsed, None)

    assert handled is True
    assert captured.code == 200
    assert captured.body == {"ok": True}

    # And the password actually changed on disk.
    after = find_user_by_id(tmp_path, "u-victim")
    assert after["password_hash"] == _hash_password("ResetPass99")