"""Integration tests for RBAC HTTP routes.

These verify route handlers parse JSON bodies, return correct HTTP codes,
and call into the underlying business-logic modules. Uses MagicMock
to simulate handler state.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock


def _make_handler():
    """Create a mock handler with .wfile captured."""
    handler = MagicMock()
    handler.wfile.write = MagicMock()
    handler.rfile = MagicMock()
    return handler


def _read_json_response(handler) -> dict:
    """Extract the last JSON dict written to handler.wfile."""
    body = handler.wfile.write.call_args_list[-1][0][0].decode("utf-8")
    return json.loads(body)


def test_login_route_handler_exists():
    from api.rbac_routes import handle_auth_login
    assert callable(handle_auth_login)


def test_register_route_handler_exists():
    from api.rbac_routes import handle_auth_register
    assert callable(handle_auth_register)


def test_logout_route_handler_exists():
    from api.rbac_routes import handle_auth_logout
    assert callable(handle_auth_logout)


def test_init_status_route_handler_exists():
    from api.rbac_routes import handle_auth_init_status
    assert callable(handle_auth_init_status)


def test_list_sessions_route_handler_exists():
    from api.rbac_routes import handle_sessions_list
    assert callable(handle_sessions_list)


def test_share_session_route_handler_exists():
    from api.rbac_routes import handle_session_share
    assert callable(handle_session_share)


def test_token_share_route_handler_exists():
    from api.rbac_routes import handle_session_share_token
    assert callable(handle_session_share_token)


def test_admin_list_users_route_handler_exists():
    from api.rbac_routes import handle_admin_users_list
    assert callable(handle_admin_users_list)


def test_admin_audit_route_handler_exists():
    from api.rbac_routes import handle_admin_audit
    assert callable(handle_admin_audit)


def test_login_with_correct_credentials(tmp_path, monkeypatch):
    """POST /api/auth/login with valid creds → 200 + session cookie."""
    from api.rbac_routes import handle_auth_login
    from api.auth import _hash_password
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    from api.user_store import add_user
    add_user(tmp_path, {
        "id": "u-alice", "username": "alice",
        "password_hash": _hash_password("secret123"), "role": "user",
    })
    handler = _make_handler()
    handler.rfile.read = MagicMock(return_value=b'{"username":"alice","password":"secret123"}')
    parsed = MagicMock()
    parsed.path = "/api/auth/login"
    handle_auth_login(handler, parsed)
    handler.send_response.assert_called_with(200)
    body = _read_json_response(handler)
    assert body["user"]["username"] == "alice"


def test_login_with_wrong_credentials_returns_401(tmp_path, monkeypatch):
    from api.rbac_routes import handle_auth_login
    from api.auth import _hash_password
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    from api.user_store import add_user
    add_user(tmp_path, {
        "id": "u-alice", "username": "alice",
        "password_hash": _hash_password("secret123"), "role": "user",
    })
    handler = _make_handler()
    handler.rfile.read = MagicMock(return_value=b'{"username":"alice","password":"WRONG"}')
    parsed = MagicMock()
    parsed.path = "/api/auth/login"
    handle_auth_login(handler, parsed)
    handler.send_response.assert_called_with(401)


def test_init_status_when_empty(tmp_path, monkeypatch):
    """未初始化时 /api/auth/init_status 返回 {initialized: false}."""
    from api.rbac_routes import handle_auth_init_status
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    handler = _make_handler()
    parsed = MagicMock()
    parsed.path = "/api/auth/init_status"
    handle_auth_init_status(handler, parsed)
    handler.send_response.assert_called_with(200)
    body = _read_json_response(handler)
    assert body["initialized"] is False


def test_init_status_when_initialized(tmp_path, monkeypatch):
    from api.rbac_routes import handle_auth_init_status
    from api.auth import _hash_password
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    from api.user_store import add_user
    add_user(tmp_path, {
        "id": "u1", "username": "alice",
        "password_hash": _hash_password("x"), "role": "user",
    })
    handler = _make_handler()
    parsed = MagicMock()
    parsed.path = "/api/auth/init_status"
    handle_auth_init_status(handler, parsed)
    body = _read_json_response(handler)
    assert body["initialized"] is True


def test_register_when_already_initialized_returns_403(tmp_path, monkeypatch):
    """已初始化时 /api/auth/register 拒绝。"""
    from api.rbac_routes import handle_auth_register
    from api.auth import _hash_password
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    from api.user_store import add_user
    add_user(tmp_path, {
        "id": "u1", "username": "alice",
        "password_hash": _hash_password("x"), "role": "user",
    })
    handler = _make_handler()
    handler.rfile.read = MagicMock(return_value=b'{"username":"bob","password":"bob123"}')
    parsed = MagicMock()
    parsed.path = "/api/auth/register"
    handle_auth_register(handler, parsed)
    handler.send_response.assert_called_with(403)


def test_register_first_admin(tmp_path, monkeypatch):
    """未初始化时 /api/auth/register 创建 admin 并返回 200。"""
    from api.rbac_routes import handle_auth_register
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    handler = _make_handler()
    handler.rfile.read = MagicMock(return_value=b'{"username":"admin","password":"admin123"}')
    parsed = MagicMock()
    parsed.path = "/api/auth/register"
    handle_auth_register(handler, parsed)
    handler.send_response.assert_called_with(200)
    body = _read_json_response(handler)
    assert body["user"]["username"] == "admin"
    assert body["user"]["role"] == "admin"


def test_admin_users_list_requires_admin(tmp_path, monkeypatch):
    """非 admin 调用 /api/admin/users → 403。"""
    from api.rbac_routes import handle_admin_users_list
    from api.auth import create_user_session, _hash_password
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    monkeypatch.setattr("api.admin._state_dir", lambda: tmp_path)
    from api.user_store import add_user
    add_user(tmp_path, {
        "id": "u-alice", "username": "alice",
        "password_hash": _hash_password("x"), "role": "user",
    })
    token = create_user_session("u-alice")
    handler = _make_handler()
    handler.headers = {"Cookie": f"hermes_session={token}"}
    parsed = MagicMock()
    parsed.path = "/api/admin/users"
    handle_admin_users_list(handler, parsed)
    handler.send_response.assert_called_with(403)


def test_admin_users_list_as_admin(tmp_path, monkeypatch):
    """admin 调用 /api/admin/users → 200 + 用户列表。"""
    from api.rbac_routes import handle_admin_users_list
    from api.auth import create_user_session, _hash_password
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    monkeypatch.setattr("api.admin._state_dir", lambda: tmp_path)
    from api.user_store import add_user
    add_user(tmp_path, {
        "id": "u-admin", "username": "admin",
        "password_hash": _hash_password("x"), "role": "admin",
    })
    token = create_user_session("u-admin")
    handler = _make_handler()
    handler.headers = {"Cookie": f"hermes_session={token}"}
    parsed = MagicMock()
    parsed.path = "/api/admin/users"
    handle_admin_users_list(handler, parsed)
    handler.send_response.assert_called_with(200)
    body = _read_json_response(handler)
    assert len(body["users"]) >= 1


def test_admin_users_list_unauthenticated_returns_401():
    """无 cookie 时 → 401。"""
    from api.rbac_routes import handle_admin_users_list
    handler = _make_handler()
    handler.headers = {}
    parsed = MagicMock()
    parsed.path = "/api/admin/users"
    handle_admin_users_list(handler, parsed)
    handler.send_response.assert_called_with(401)