"""Integration tests for RBAC HTTP routes.

These verify route handlers parse JSON bodies, return correct HTTP codes,
and call into the underlying business-logic modules. Uses MagicMock
to simulate handler state.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock
from types import SimpleNamespace
from collections import OrderedDict


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


def test_rbac_owned_empty_session_not_pruned_as_zero_message_orphan(monkeypatch):
    import api.routes as routes

    row = {
        "session_id": "sess-rbac-empty",
        "title": "test2-会话2",
        "message_count": 0,
        "source_tag": "webui",
        "profile": "default",
        "rbac_user_id": "u-test2",
    }
    pruned = []
    monkeypatch.setattr(
        routes,
        "agent_session_zero_message_sids",
        lambda ids, profile=None: set(ids),
    )
    monkeypatch.setattr(routes, "prune_session_from_index", lambda sid: pruned.append(sid))
    monkeypatch.setattr(routes, "_record_webui_zero_message_orphan_tombstone", lambda sid: None)

    rows = routes._prune_orphaned_webui_zero_message_sessions([row])

    assert rows == [row]
    assert pruned == []


def test_current_rbac_user_cache_is_bound_to_request_cookie(monkeypatch):
    """A keep-alive handler reused after login must not retain the prior user."""
    import api.routes as routes

    users = {
        "token-a": {"id": "u-a", "username": "alice", "role": "user"},
        "token-b": {"id": "u-b", "username": "bob", "role": "user"},
    }
    monkeypatch.setattr("api.auth.parse_cookie", lambda handler: handler.headers["Token"])
    monkeypatch.setattr("api.auth.get_user_from_session", lambda token: users.get(token))

    handler = SimpleNamespace(headers={"Token": "token-a"})
    assert routes._current_rbac_user(handler)["id"] == "u-a"
    assert routes._current_rbac_user_id(handler) == "u-a"

    handler.headers = {"Token": "token-b"}
    assert routes._current_rbac_user(handler)["id"] == "u-b"
    assert routes._current_rbac_user_id(handler) == "u-b"


def test_current_rbac_user_cache_reuses_same_token(monkeypatch):
    import api.routes as routes

    lookups = []
    monkeypatch.setattr("api.auth.parse_cookie", lambda handler: handler.headers["Token"])
    monkeypatch.setattr(
        "api.auth.get_user_from_session",
        lambda token: lookups.append(token) or {"id": "u-a", "role": "user"},
    )

    handler = SimpleNamespace(headers={"Token": "token-a"})
    assert routes._current_rbac_user(handler)["id"] == "u-a"
    assert routes._current_rbac_user(handler)["id"] == "u-a"
    assert lookups == ["token-a"]

    handler._req_t0 = 2
    assert routes._current_rbac_user(handler)["id"] == "u-a"
    assert lookups == ["token-a", "token-a"]


def test_logout_clears_auth_cookie(monkeypatch):
    """RBAC logout must clear the browser cookie so users can switch accounts."""
    import io
    from api.rbac_routes import handle_auth_logout

    monkeypatch.setattr(
        "api.rbac_routes.get_user_from_session",
        lambda token: {"id": "u-admin", "username": "admin", "role": "admin"},
    )
    invalidated = []
    monkeypatch.setattr(
        "api.rbac_routes.invalidate_user_session",
        lambda token: invalidated.append(token),
    )

    handler = _make_handler()
    handler.headers = {"Cookie": "hermes_session=token-123", "Content-Length": "2"}
    handler.rfile = io.BytesIO(b"{}")
    parsed = MagicMock()
    parsed.path = "/api/auth/logout"
    handle_auth_logout(handler, parsed)

    handler.send_response.assert_called_with(200)
    assert invalidated == ["token-123"]
    assert handler.rfile.read() == b""
    set_cookie_headers = [
        call.args[1]
        for call in handler.send_header.call_args_list
        if call.args and call.args[0] == "Set-Cookie"
    ]
    assert any("hermes_session=" in value and "Max-Age=0" in value for value in set_cookie_headers)


def test_webui_session_model_persists_rbac_owner(tmp_path, monkeypatch):
    """WebUI session sidecars and the sidebar index must carry RBAC ownership."""
    import api.models as models

    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    monkeypatch.setattr(models, "SESSION_DIR", session_dir)
    monkeypatch.setattr(models, "SESSION_INDEX_FILE", session_dir / "_index.json")
    monkeypatch.setattr(models, "SESSIONS", OrderedDict(), raising=False)

    session = models.Session(
        session_id="rbac_owner_session",
        title="Owned",
        messages=[{"role": "user", "content": "hello"}],
        rbac_user_id="u-alice",
    )
    session.save()

    sidecar = json.loads((session_dir / "rbac_owner_session.json").read_text(encoding="utf-8"))
    index = json.loads((session_dir / "_index.json").read_text(encoding="utf-8"))
    assert sidecar["rbac_user_id"] == "u-alice"
    assert index[0]["rbac_user_id"] == "u-alice"
    assert session.compact()["rbac_user_id"] == "u-alice"


def test_new_session_accepts_rbac_owner(tmp_path, monkeypatch):
    import api.models as models

    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    monkeypatch.setattr(models, "SESSION_DIR", session_dir)
    monkeypatch.setattr(models, "SESSION_INDEX_FILE", session_dir / "_index.json")
    monkeypatch.setattr(models, "SESSIONS", OrderedDict(), raising=False)
    monkeypatch.setattr(models, "get_last_workspace", lambda: str(tmp_path))

    session = models.new_session(rbac_user_id="u-alice")
    assert session.rbac_user_id == "u-alice"
    assert session.compact()["rbac_user_id"] == "u-alice"


def test_session_list_cache_key_includes_rbac_user():
    import api.routes as routes

    base = dict(
        active_profile="default",
        all_profiles=False,
        show_cli_sessions=False,
        show_previous_messaging_sessions=False,
        show_cron_sessions=False,
    )
    assert routes._session_list_cache_key(**base, rbac_user_id="u-alice") != routes._session_list_cache_key(**base, rbac_user_id="u-bob")


def test_session_visibility_checks_rbac_owner(monkeypatch):
    import api.routes as routes

    monkeypatch.setattr(routes, "_current_rbac_user_id", lambda handler: "u-alice")
    monkeypatch.setattr(routes, "_rbac_users_configured", lambda: True)
    assert routes._session_visible_to_request(SimpleNamespace(profile="default", rbac_user_id="u-alice"), object())
    assert not routes._session_visible_to_request(SimpleNamespace(profile="default", rbac_user_id="u-bob"), object())
    assert not routes._session_visible_to_request(SimpleNamespace(profile="default", rbac_user_id=None), object())


def test_owned_session_hidden_when_rbac_configured_without_user(monkeypatch):
    import api.routes as routes

    monkeypatch.setattr(routes, "_current_rbac_user_id", lambda handler: None)
    monkeypatch.setattr(routes, "_rbac_users_configured", lambda: True)
    assert not routes._session_visible_to_request(SimpleNamespace(profile="default", rbac_user_id="u-alice"), object())
    assert not routes._session_visible_to_request(SimpleNamespace(profile="default", rbac_user_id=None), object())


def test_session_list_payload_filters_by_rbac_owner(monkeypatch):
    import api.routes as routes

    rows = [
        {"session_id": "alice", "title": "Alice", "profile": "default", "rbac_user_id": "u-alice", "message_count": 1, "updated_at": 3},
        {"session_id": "bob", "title": "Bob", "profile": "default", "rbac_user_id": "u-bob", "message_count": 1, "updated_at": 2},
        {"session_id": "legacy", "title": "Legacy", "profile": "default", "message_count": 1, "updated_at": 1},
    ]
    monkeypatch.setattr(routes, "all_sessions", lambda **_kwargs: [dict(row) for row in rows])
    monkeypatch.setattr(routes, "_prune_orphaned_webui_zero_message_sessions", lambda rows, **_kwargs: list(rows))
    monkeypatch.setattr(routes, "_enrich_sidebar_lineage_metadata", lambda rows: None)

    payload = routes._build_session_list_cache_payload(
        active_profile="default",
        all_profiles=False,
        show_cli_sessions=False,
        show_previous_messaging_sessions=True,
        show_cron_sessions=False,
        rbac_user_id="u-alice",
        rbac_scope_enabled=True,
    )

    ids = {row["session_id"] for row in payload["sessions"]}
    assert ids == {"alice"}


def test_session_list_payload_hides_rows_when_rbac_configured_without_user(monkeypatch):
    import api.routes as routes

    rows = [
        {"session_id": "alice", "title": "Alice", "profile": "default", "rbac_user_id": "u-alice", "message_count": 1, "updated_at": 3},
        {"session_id": "legacy", "title": "Legacy", "profile": "default", "message_count": 1, "updated_at": 1},
    ]
    monkeypatch.setattr(routes, "_rbac_users_configured", lambda: True)
    monkeypatch.setattr(routes, "all_sessions", lambda **_kwargs: [dict(row) for row in rows])
    monkeypatch.setattr(routes, "_prune_orphaned_webui_zero_message_sessions", lambda rows, **_kwargs: list(rows))
    monkeypatch.setattr(routes, "_enrich_sidebar_lineage_metadata", lambda rows: None)

    payload = routes._build_session_list_cache_payload(
        active_profile="default",
        all_profiles=False,
        show_cli_sessions=False,
        show_previous_messaging_sessions=True,
        show_cron_sessions=False,
        rbac_user_id=None,
        rbac_scope_enabled=False,
    )

    assert payload["sessions"] == []


def test_session_list_payload_includes_shared_sessions_for_recipient(monkeypatch, tmp_path):
    import api.routes as routes
    from api import share_store

    rows = [
        {"session_id": "alice", "title": "Alice", "profile": "default", "rbac_user_id": "u-alice", "message_count": 1, "updated_at": 3},
        {"session_id": "bob", "title": "Bob", "profile": "default", "rbac_user_id": "u-bob", "message_count": 1, "updated_at": 2},
    ]
    share_store.add_user_share(
        tmp_path,
        session_id="alice",
        owner_id="u-alice",
        owner_name="alice",
        to_user_id="u-bob",
        to_username="bob",
    )
    monkeypatch.setattr(routes, "STATE_DIR", tmp_path)
    monkeypatch.setattr(routes, "all_sessions", lambda **_kwargs: [dict(row) for row in rows])
    monkeypatch.setattr(routes, "_prune_orphaned_webui_zero_message_sessions", lambda rows, **_kwargs: list(rows))
    monkeypatch.setattr(routes, "_enrich_sidebar_lineage_metadata", lambda rows: None)

    payload = routes._build_session_list_cache_payload(
        active_profile="default",
        all_profiles=False,
        show_cli_sessions=False,
        show_previous_messaging_sessions=True,
        show_cron_sessions=False,
        rbac_user_id="u-bob",
        rbac_scope_enabled=True,
    )

    ids = {row["session_id"] for row in payload["sessions"]}
    assert ids == {"alice", "bob"}
    shared_row = next(row for row in payload["sessions"] if row["session_id"] == "alice")
    assert shared_row["read_only"] is True
    assert shared_row["viewer"] == "shared"
    assert shared_row["shared_by"] == "alice"


def test_session_list_payload_keeps_empty_shared_session_for_recipient(monkeypatch, tmp_path):
    import api.routes as routes
    from api import share_store

    rows = [
        {"session_id": "alice-empty", "title": "Alice Empty", "profile": "default", "rbac_user_id": "u-alice", "message_count": 0, "updated_at": 3},
        {"session_id": "bob", "title": "Bob", "profile": "default", "rbac_user_id": "u-bob", "message_count": 1, "updated_at": 2},
    ]
    share_store.add_user_share(
        tmp_path,
        session_id="alice-empty",
        owner_id="u-alice",
        owner_name="alice",
        to_user_id="u-bob",
        to_username="bob",
    )
    monkeypatch.setattr(routes, "STATE_DIR", tmp_path)
    monkeypatch.setattr(routes, "all_sessions", lambda **_kwargs: [dict(row) for row in rows])
    monkeypatch.setattr(routes, "_prune_orphaned_webui_zero_message_sessions", lambda rows, **_kwargs: list(rows))
    monkeypatch.setattr(routes, "_enrich_sidebar_lineage_metadata", lambda rows: None)

    payload = routes._build_session_list_cache_payload(
        active_profile="default",
        all_profiles=False,
        show_cli_sessions=False,
        show_previous_messaging_sessions=True,
        show_cron_sessions=False,
        rbac_user_id="u-bob",
        rbac_scope_enabled=True,
        visible_only=True,
    )

    ids = {row["session_id"] for row in payload["sessions"]}
    assert ids == {"alice-empty", "bob"}
    shared_row = next(row for row in payload["sessions"] if row["session_id"] == "alice-empty")
    assert shared_row["read_only"] is True
    assert shared_row["viewer"] == "shared"


def test_session_list_payload_admin_sees_all_rbac_rows(monkeypatch):
    import api.routes as routes

    rows = [
        {"session_id": "alice", "title": "Alice", "profile": "default", "rbac_user_id": "u-alice", "message_count": 1, "updated_at": 3},
        {"session_id": "bob", "title": "Bob", "profile": "default", "rbac_user_id": "u-bob", "message_count": 1, "updated_at": 2},
        {"session_id": "legacy", "title": "Legacy", "profile": "default", "message_count": 1, "updated_at": 1},
    ]
    monkeypatch.setattr(routes, "all_sessions", lambda **_kwargs: [dict(row) for row in rows])
    monkeypatch.setattr(routes, "_prune_orphaned_webui_zero_message_sessions", lambda rows, **_kwargs: list(rows))
    monkeypatch.setattr(routes, "_enrich_sidebar_lineage_metadata", lambda rows: None)

    payload = routes._build_session_list_cache_payload(
        active_profile="default",
        all_profiles=False,
        show_cli_sessions=False,
        show_previous_messaging_sessions=True,
        show_cron_sessions=False,
        rbac_user_id="u-admin",
        rbac_scope_enabled=True,
        rbac_is_admin=True,
    )

    ids = {row["session_id"] for row in payload["sessions"]}
    assert ids == {"alice", "bob", "legacy"}


def test_rbac_routes_do_not_intercept_primary_sessions_sidebar_contract():
    from urllib.parse import urlparse
    from api.rbac_routes import try_handle_rbac

    handler = _make_handler()

    assert try_handle_rbac("GET", urlparse("http://example.com/api/sessions"), handler) is False
    assert not handler.wfile.write.called
