"""Tests for POST /api/auth/change-password (Task 2 of the RBAC refactor).

This endpoint lets an authenticated user rotate their own password. We
verify:

  * Happy path: old_password correct + new_password compliant → 200,
    password_hash rewritten on disk, all OTHER sessions kicked (current
    keep_token survives), and a `password.change` audit entry is written.
  * Old password wrong → 400 with i18n key ``password_old_wrong``.
  * Weak new password (too short, or missing letter/digit classes) → 400
    with the right i18n key.
  * Unauthenticated request → 401 ``auth_required``.
  * Missing fields → 400 ``missing_field``.
  * ``_validate_password_complexity`` itself.

All handlers here use the project's existing MagicMock + ``rfile.read``
pattern (see ``test_routes_rbac.py``) — no real socket is opened.
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from api import rbac_routes as rmod
from api.auth import (
    _hash_password,
    create_user_session,
    invalidate_all_user_sessions,
)
from api.user_store import find_user_by_id, load_users, update_password


# ─────────────────────────────────────────────────────────────────────────────
# Test scaffolding
# ─────────────────────────────────────────────────────────────────────────────


def _make_handler(body: bytes | None = None):
    """Return a MagicMock handler with ``rfile.read`` primed for JSON body.

    ``body`` defaults to empty bytes so handlers that don't read a body
    (e.g. auth_required short-circuit) still work.

    When a body is supplied, we also set ``Content-Length`` on the real
    dict headers so ``_read_json_body`` actually consumes it — otherwise
    ``headers.get("Content-Length", 0)`` would default to 0 and the read
    would be skipped. Cookie is added by the caller via ``handler.headers``.
    """
    handler = MagicMock()
    handler.wfile.write = MagicMock()
    handler.rfile = MagicMock()
    handler.headers = {"Content-Length": str(len(body))} if body else {"Content-Length": "0"}
    handler.rfile.read = MagicMock(return_value=body if body is not None else b"")
    return handler


def _read_json_response(handler) -> dict:
    """Pull the last JSON dict written to handler.wfile."""
    body = handler.wfile.write.call_args_list[-1][0][0].decode("utf-8")
    return json.loads(body)


def _patch_state_dir(monkeypatch, tmp_path):
    """Point every state_dir helper at tmp_path.

    RBAC helpers (``api.rbac_routes``, ``api.auth``, ``api.admin``) all
    expose their own ``_state_dir`` (or import ``STATE_DIR``); we patch
    them all so disk writes go to a throwaway dir.
    """
    from api import auth as auth_mod
    from api import admin as admin_mod

    monkeypatch.setattr(auth_mod, "_state_dir", lambda: tmp_path)
    monkeypatch.setattr(admin_mod, "_state_dir", lambda: tmp_path)
    monkeypatch.setattr(rmod, "STATE_DIR", tmp_path)


def _seed_user(tmp_path, *, user_id="u-alice", username="alice", password="OldPass123"):
    """Insert a user with a real PBKDF2 hash and return the record."""
    from api.user_store import add_user

    add_user(tmp_path, {
        "id": user_id,
        "username": username,
        "password_hash": _hash_password(password),
        "role": "user",
        "created_at": "2026-08-01T00:00:00Z",
        "last_login": None,
    })
    return find_user_by_id(tmp_path, user_id)


# ─────────────────────────────────────────────────────────────────────────────
# _validate_password_complexity — direct unit tests
# ─────────────────────────────────────────────────────────────────────────────


def test_complexity_too_short():
    assert rmod._validate_password_complexity("") == "password_too_short"
    assert rmod._validate_password_complexity("a1") == "password_too_short"
    assert rmod._validate_password_complexity("abcdefg") == "password_too_short"  # 7 chars, no digit
    assert rmod._validate_password_complexity("1234567") == "password_too_short"  # 7 chars, no letter


def test_complexity_missing_classes():
    assert rmod._validate_password_complexity("longpasswordwithletters") == "password_needs_classes"
    assert rmod._validate_password_complexity("12345678") == "password_needs_classes"
    assert rmod._validate_password_complexity("LongWithLetters") == "password_needs_classes"


def test_complexity_accepts_valid_passwords():
    assert rmod._validate_password_complexity("abcd1234") is None
    assert rmod._validate_password_complexity("MySecret99") is None
    assert rmod._validate_password_complexity("Zz9xxxxx") is None


def test_complexity_non_string_returns_too_short():
    # Defensive: a None or non-string value should not crash the handler.
    assert rmod._validate_password_complexity(None) == "password_too_short"  # type: ignore[arg-type]
    assert rmod._validate_password_complexity(12345678) == "password_too_short"  # type: ignore[arg-type]


# ─────────────────────────────────────────────────────────────────────────────
# handle_auth_change_password — end-to-end with mocked handler
# ─────────────────────────────────────────────────────────────────────────────


def test_change_password_happy_path(tmp_path, monkeypatch):
    """Old password correct + new password compliant → 200, hash updated,
    other session invalidated, current session kept, audit written."""
    _patch_state_dir(monkeypatch, tmp_path)
    user = _seed_user(tmp_path, password="OldPass123")

    # Two sessions exist for this user; ``tok-current`` is the caller's.
    tok_current = create_user_session(user["id"])
    tok_other = create_user_session(user["id"])
    assert tok_current != tok_other

    handler = _make_handler(body=json.dumps({
        "old_password": "OldPass123",
        "new_password": "NewPass456",
    }).encode("utf-8"))
    handler.headers["Cookie"] = f"hermes_session={tok_current}"

    parsed = MagicMock()
    parsed.path = "/api/auth/change-password"
    result = rmod.handle_auth_change_password(handler, parsed)
    assert result is True

    # 200 + {ok: true}
    handler.send_response.assert_called_with(200)
    body = _read_json_response(handler)
    assert body == {"ok": True}

    # Password hash on disk has been replaced.
    updated = find_user_by_id(tmp_path, user["id"])
    assert updated["password_hash"] != user["password_hash"]
    assert updated["password_hash"] == _hash_password("NewPass456")

    # Old password no longer verifies; new password does.
    assert _hash_password("OldPass123") != updated["password_hash"]
    assert _hash_password("NewPass456") == updated["password_hash"]

    # Other session invalidated, current preserved.
    from api.auth import _load_user_sessions
    sessions = _load_user_sessions()
    assert tok_current in sessions, "current session must be preserved (keep_token)"
    assert tok_other not in sessions, "other session must be invalidated"


def test_change_password_wrong_old_password(tmp_path, monkeypatch):
    """Wrong old_password → 400 with i18n key ``password_old_wrong``."""
    _patch_state_dir(monkeypatch, tmp_path)
    user = _seed_user(tmp_path, password="OldPass123")
    tok = create_user_session(user["id"])

    handler = _make_handler(body=json.dumps({
        "old_password": "WrongGuess999",
        "new_password": "NewPass456",
    }).encode("utf-8"))
    handler.headers["Cookie"] = f"hermes_session={tok}"

    parsed = MagicMock()
    parsed.path = "/api/auth/change-password"
    rmod.handle_auth_change_password(handler, parsed)

    handler.send_response.assert_called_with(400)
    assert _read_json_response(handler) == {"error": "password_old_wrong"}

    # Disk state unchanged.
    after = find_user_by_id(tmp_path, user["id"])
    assert after["password_hash"] == user["password_hash"]


def test_change_password_weak_new_password_too_short(tmp_path, monkeypatch):
    """New password < 8 chars → 400 ``password_too_short``."""
    _patch_state_dir(monkeypatch, tmp_path)
    user = _seed_user(tmp_path, password="OldPass123")
    tok = create_user_session(user["id"])

    handler = _make_handler(body=json.dumps({
        "old_password": "OldPass123",
        "new_password": "abc1",  # 4 chars
    }).encode("utf-8"))
    handler.headers["Cookie"] = f"hermes_session={tok}"

    parsed = MagicMock()
    parsed.path = "/api/auth/change-password"
    rmod.handle_auth_change_password(handler, parsed)

    handler.send_response.assert_called_with(400)
    assert _read_json_response(handler) == {"error": "password_too_short"}


def test_change_password_weak_new_password_missing_classes(tmp_path, monkeypatch):
    """New password passes length but lacks letters OR digits → ``password_needs_classes``."""
    _patch_state_dir(monkeypatch, tmp_path)
    user = _seed_user(tmp_path, password="OldPass123")
    tok = create_user_session(user["id"])

    handler = _make_handler(body=json.dumps({
        "old_password": "OldPass123",
        # 8+ chars but only letters
        "new_password": "longpassword",
    }).encode("utf-8"))
    handler.headers["Cookie"] = f"hermes_session={tok}"

    parsed = MagicMock()
    parsed.path = "/api/auth/change-password"
    rmod.handle_auth_change_password(handler, parsed)

    handler.send_response.assert_called_with(400)
    assert _read_json_response(handler) == {"error": "password_needs_classes"}


def test_change_password_unauthenticated_returns_401(tmp_path, monkeypatch):
    """No cookie / no valid session → 401 ``auth_required``."""
    _patch_state_dir(monkeypatch, tmp_path)
    _seed_user(tmp_path, password="OldPass123")

    handler = _make_handler(body=json.dumps({
        "old_password": "OldPass123",
        "new_password": "NewPass456",
    }).encode("utf-8"))
    # No Cookie header at all
    parsed = MagicMock()
    parsed.path = "/api/auth/change-password"
    rmod.handle_auth_change_password(handler, parsed)

    handler.send_response.assert_called_with(401)
    assert _read_json_response(handler) == {"error": "auth_required"}


def test_change_password_missing_fields_returns_400(tmp_path, monkeypatch):
    """Empty old_password or new_password → 400 ``missing_field``."""
    _patch_state_dir(monkeypatch, tmp_path)
    user = _seed_user(tmp_path, password="OldPass123")
    tok = create_user_session(user["id"])

    for bad_body in [
        b'{"old_password": "", "new_password": "NewPass456"}',
        b'{"old_password": "OldPass123", "new_password": ""}',
        b'{}',
    ]:
        handler = _make_handler(body=bad_body)
        handler.headers["Cookie"] = f"hermes_session={tok}"
        parsed = MagicMock()
        parsed.path = "/api/auth/change-password"
        rmod.handle_auth_change_password(handler, parsed)
        handler.send_response.assert_called_with(400)
        assert _read_json_response(handler) == {"error": "missing_field"}


def test_change_password_writes_audit_event(tmp_path, monkeypatch):
    """Audit log is written with category='rbac' and action='password.change'."""
    _patch_state_dir(monkeypatch, tmp_path)
    user = _seed_user(tmp_path, password="OldPass123")
    tok = create_user_session(user["id"])

    # Spy on rmod._audit.write so we can inspect the call args without
    # actually touching the .jsonl files on disk.
    captured = {}
    real_write = rmod._audit.write

    def spy_write(*args, **kwargs):
        # The handler calls audit.write with kwargs (category=..., action=..., ...).
        captured.setdefault("calls", []).append((args, kwargs))

    monkeypatch.setattr(rmod._audit, "write", spy_write)

    handler = _make_handler(body=json.dumps({
        "old_password": "OldPass123",
        "new_password": "NewPass456",
    }).encode("utf-8"))
    handler.headers["Cookie"] = f"hermes_session={tok}"

    parsed = MagicMock()
    parsed.path = "/api/auth/change-password"
    rmod.handle_auth_change_password(handler, parsed)

    handler.send_response.assert_called_with(200)
    assert captured["calls"], "expected at least one audit write"
    last_kwargs = captured["calls"][-1][1]
    assert last_kwargs.get("category") == "rbac"
    assert last_kwargs.get("action") == "password.change"
    assert last_kwargs.get("actor_id") == user["id"]


def test_change_password_dispatcher_routes_correctly(tmp_path, monkeypatch):
    """try_handle_rbac must dispatch POST /api/auth/change-password to our handler."""
    _patch_state_dir(monkeypatch, tmp_path)
    user = _seed_user(tmp_path, password="OldPass123")
    tok = create_user_session(user["id"])

    handler = _make_handler(body=json.dumps({
        "old_password": "OldPass123",
        "new_password": "NewPass456",
    }).encode("utf-8"))
    handler.headers["Cookie"] = f"hermes_session={tok}"

    parsed = MagicMock()
    parsed.path = "/api/auth/change-password"
    parsed.query = ""
    handled = rmod.try_handle_rbac("POST", parsed, handler)
    assert handled is True
    handler.send_response.assert_called_with(200)
    assert _read_json_response(handler) == {"ok": True}