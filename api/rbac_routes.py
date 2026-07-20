"""RBAC HTTP route handlers.

Each function is a thin handler that:
  1. Parses request body / cookies
  2. Calls into business-logic modules (api.auth, api.admin, api.session_*, etc.)
  3. Writes a JSON response (or error code)

Wire these into api/routes.py by adding to the dispatcher near the top of
handle_get / handle_post / handle_delete — return True to short-circuit
out of the existing routes table.

Note: the helpers below use ``_audit.write`` (not from-import) so tests
can monkeypatch the underlying module without re-binding names.
"""
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs

from api import audit as _audit
from api.auth import (
    authenticate,
    create_user_session,
    get_user_from_session,
    invalidate_user_session,
    is_admin,
    needs_initialization,
    initialize_first_admin,
)
from api.user_store import find_user_by_username
from api.config import STATE_DIR
from api.helpers import j


def _read_json_body(handler) -> dict:
    """Read and parse JSON body from handler.rfile."""
    content_length = int(handler.headers.get("Content-Length", 0))
    raw = handler.rfile.read(content_length) if content_length else b"{}"
    return json.loads(raw.decode("utf-8") or "{}")


def _get_session_token(handler) -> str | None:
    """Extract session token from hermes_session cookie."""
    cookie_header = handler.headers.get("Cookie", "")
    if not cookie_header:
        return None
    for part in cookie_header.split(";"):
        part = part.strip()
        if part.startswith("hermes_session="):
            return part[len("hermes_session="):]
    return None


def _send_json(handler, status: int, payload: dict) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _send_text(handler, status: int, text: str, content_type: str = "text/plain; charset=utf-8") -> None:
    body = text.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _current_user(handler) -> dict | None:
    """Resolve the currently authenticated user from the session cookie."""
    token = _get_session_token(handler)
    if not token:
        return None
    return get_user_from_session(token)


# ── /api/auth/* ──────────────────────────────────────────────────────────────

def handle_auth_login(handler, parsed) -> bool:
    """POST /api/auth/login — username + password → session cookie."""
    body = _read_json_body(handler)
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        _send_json(handler, 400, {"error": "username and password required"})
        return True
    user = authenticate(username, password)
    if not user:
        _send_json(handler, 401, {"error": "Invalid credentials"})
        return True
    token = create_user_session(user["id"])
    _audit.write(
        category="rbac",
        action="auth.login",
        actor_id=user["id"], actor_name=user["username"],
    )
    _send_json(handler, 200, {
        "user": {
            "id": user["id"],
            "username": user["username"],
            "role": user.get("role", "user"),
        }
    })
    # 设置 cookie（追加 Set-Cookie header）
    cookie = (
        f"hermes_session={token}; HttpOnly; Path=/; SameSite=Lax; Max-Age=2592000"
    )
    handler.send_header("Set-Cookie", cookie)
    return True


def handle_auth_logout(handler, parsed) -> bool:
    """POST /api/auth/logout — invalidate current session."""
    token = _get_session_token(handler)
    if token:
        user = get_user_from_session(token)
        invalidate_user_session(token)
        if user:
            _audit.write(
                category="rbac",
                action="auth.logout",
                actor_id=user["id"], actor_name=user["username"],
            )
    _send_json(handler, 200, {"ok": True})
    return True


def handle_auth_register(handler, parsed) -> bool:
    """POST /api/auth/register — first-time admin creation. Blocked after init."""
    if not needs_initialization():
        _send_json(handler, 403, {"error": "Already initialized"})
        return True
    body = _read_json_body(handler)
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        _send_json(handler, 400, {"error": "username and password required"})
        return True
    user = initialize_first_admin(username, password)
    # 自动登录
    token = create_user_session(user["id"])
    _audit.write(
        category="rbac",
        action="auth.register",
        actor_id=user["id"], actor_name=user["username"],
    )
    _send_json(handler, 200, {
        "user": {
            "id": user["id"],
            "username": user["username"],
            "role": user["role"],
        }
    })
    cookie = f"hermes_session={token}; HttpOnly; Path=/; SameSite=Lax; Max-Age=2592000"
    handler.send_header("Set-Cookie", cookie)
    return True


def handle_auth_init_status(handler, parsed) -> bool:
    """GET /api/auth/init_status — public; used by login page to decide route."""
    initialized = not needs_initialization()
    license_status = "valid"
    try:
        from api.license import check_license_status
        license_status = check_license_status(Path(STATE_DIR).parent).get("status", "valid")
    except Exception:
        pass
    _send_json(handler, 200, {"initialized": initialized, "license_status": license_status})
    return True


# ── /api/sessions/* ──────────────────────────────────────────────────────────

def handle_sessions_list(handler, parsed) -> bool:
    """GET /api/sessions — own + shared sessions for current user."""
    user = _current_user(handler)
    if not user:
        _send_json(handler, 401, {"error": "Authentication required"})
        return True
    from api.session_store import list_user_sessions
    from api.session_sharing import list_shared_sessions
    sessions_dir = STATE_DIR / "sessions"
    own = list_user_sessions(sessions_dir, user["id"])
    shared = list_shared_sessions(sessions_dir, user["id"])
    _send_json(handler, 200, {"own": own, "shared": shared})
    return True


def handle_session_share(handler, parsed) -> bool:
    """POST /api/sessions/{id}/share — share with another user by username."""
    user = _current_user(handler)
    if not user:
        _send_json(handler, 401, {"error": "Authentication required"})
        return True
    # 提取 session_id: /api/sessions/{id}/share
    parts = [p for p in parsed.path.split("/") if p]
    # [api, sessions, {id}, share]
    if len(parts) < 4:
        _send_json(handler, 400, {"error": "Bad request"})
        return True
    session_id = parts[2]
    body = _read_json_body(handler)
    to_username = (body.get("username") or "").strip()
    if not to_username:
        _send_json(handler, 400, {"error": "username required"})
        return True
    target = find_user_by_username(STATE_DIR, to_username)
    if not target:
        _send_json(handler, 404, {"error": "User not found"})
        return True
    from api.session_sharing import share_session_to_user
    sessions_dir = STATE_DIR / "sessions"
    share = share_session_to_user(sessions_dir, user["id"], target["id"], session_id)
    _audit.write(
        category="rbac",
        action="session.share",
        actor_id=user["id"], actor_name=user["username"],
        target_type="session", target_id=session_id, target_name=to_username,
        details={"method": "user", "to_user_id": target["id"]},
    )
    _send_json(handler, 200, {"share": share})
    return True


def handle_session_share_token(handler, parsed) -> bool:
    """POST /api/sessions/{id}/share/token — generate a share token link."""
    user = _current_user(handler)
    if not user:
        _send_json(handler, 401, {"error": "Authentication required"})
        return True
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 4:
        _send_json(handler, 400, {"error": "Bad request"})
        return True
    session_id = parts[2]
    from api.session_sharing import share_session_with_token
    sessions_dir = STATE_DIR / "sessions"
    share = share_session_with_token(sessions_dir, user["id"], session_id)
    _audit.write(
        category="rbac",
        action="session.share",
        actor_id=user["id"], actor_name=user["username"],
        target_type="session", target_id=session_id, target_name="(token link)",
        details={"method": "token"},
    )
    _send_json(handler, 200, {"share": share})
    return True


def handle_session_share_revoke(handler, parsed) -> bool:
    """DELETE /api/sessions/{id}/share/{share_id} — revoke an outgoing share."""
    user = _current_user(handler)
    if not user:
        _send_json(handler, 401, {"error": "Authentication required"})
        return True
    parts = [p for p in parsed.path.split("/") if p]
    # [api, sessions, {id}, share, {share_id}]
    if len(parts) < 5:
        _send_json(handler, 400, {"error": "Bad request"})
        return True
    session_id = parts[2]
    share_id = parts[4]
    from api.session_sharing import revoke_share
    sessions_dir = STATE_DIR / "sessions"
    ok = revoke_share(sessions_dir, user["id"], share_id)
    if not ok:
        _send_json(handler, 404, {"error": "Share not found"})
        return True
    _audit.write(
        category="rbac",
        action="session.revoke",
        actor_id=user["id"], actor_name=user["username"],
        target_type="share", target_id=share_id, target_name=session_id,
    )
    _send_json(handler, 200, {"ok": True})
    return True


# ── /api/admin/* ─────────────────────────────────────────────────────────────

def handle_admin_users_list(handler, parsed) -> bool:
    """GET /api/admin/users — admin-only."""
    user = _current_user(handler)
    if not user:
        _send_json(handler, 401, {"error": "Authentication required"})
        return True
    if not is_admin(user):
        _send_json(handler, 403, {"error": "Admin required"})
        return True
    from api.admin import list_users
    _send_json(handler, 200, {"users": list_users()})
    return True


def handle_admin_users_create(handler, parsed) -> bool:
    """POST /api/admin/users — admin creates a new user."""
    user = _current_user(handler)
    if not user:
        _send_json(handler, 401, {"error": "Authentication required"})
        return True
    if not is_admin(user):
        _send_json(handler, 403, {"error": "Admin required"})
        return True
    body = _read_json_body(handler)
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    role = body.get("role", "user")
    if not username or not password:
        _send_json(handler, 400, {"error": "username and password required"})
        return True
    try:
        from api.admin import create_user
        new_user = create_user(username, password, role)
    except ValueError as e:
        _send_json(handler, 400, {"error": str(e)})
        return True
    _audit.write(
        category="rbac",
        action="user.create",
        actor_id=user["id"], actor_name=user["username"],
        target_type="user", target_id=new_user["id"], target_name=username,
        details={"role": role, "via": "admin_api"},
    )
    _send_json(handler, 201, {"user": new_user})
    return True


def handle_admin_users_update_role(handler, parsed) -> bool:
    """PUT /api/admin/users/{id}/role — admin updates a user's role."""
    user = _current_user(handler)
    if not user:
        _send_json(handler, 401, {"error": "Authentication required"})
        return True
    if not is_admin(user):
        _send_json(handler, 403, {"error": "Admin required"})
        return True
    parts = [p for p in parsed.path.split("/") if p]
    # [api, admin, users, {id}, role]
    if len(parts) < 5:
        _send_json(handler, 400, {"error": "Bad request"})
        return True
    target_id = parts[3]
    body = _read_json_body(handler)
    new_role = body.get("role", "")
    try:
        from api.admin import update_user_role
        updated = update_user_role(
            target_id, new_role,
            actor_id=user["id"], actor_name=user["username"],
        )
    except ValueError as e:
        _send_json(handler, 400, {"error": str(e)})
        return True
    if updated is None:
        _send_json(handler, 404, {"error": "User not found"})
        return True
    _send_json(handler, 200, {"user": updated})
    return True


def handle_admin_users_delete(handler, parsed) -> bool:
    """DELETE /api/admin/users/{id} — admin deletes a user."""
    user = _current_user(handler)
    if not user:
        _send_json(handler, 401, {"error": "Authentication required"})
        return True
    if not is_admin(user):
        _send_json(handler, 403, {"error": "Admin required"})
        return True
    parts = [p for p in parsed.path.split("/") if p]
    # [api, admin, users, {id}]
    if len(parts) < 4:
        _send_json(handler, 400, {"error": "Bad request"})
        return True
    target_id = parts[3]
    if target_id == user["id"]:
        _send_json(handler, 400, {"error": "Cannot delete self"})
        return True
    from api.admin import delete_user
    ok = delete_user(
        target_id,
        actor_id=user["id"], actor_name=user["username"],
    )
    if not ok:
        _send_json(handler, 400, {"error": "Cannot delete (last admin or unknown)"})
        return True
    _send_json(handler, 200, {"ok": True})
    return True


def handle_admin_audit(handler, parsed) -> bool:
    """GET /api/admin/audit — admin-only; search RBAC events."""
    user = _current_user(handler)
    if not user:
        _send_json(handler, 401, {"error": "Authentication required"})
        return True
    if not is_admin(user):
        _send_json(handler, 403, {"error": "Admin required"})
        return True
    # Parse ?limit= and ?action= from query
    qs = parse_qs(parsed.query or "")
    limit = int(qs.get("limit", ["100"])[0])
    action = qs.get("action", [None])[0]
    from api.audit import search
    events = search(
        category="rbac",
        limit=limit,
        keyword=action,  # keyword substring on action name
    )
    _send_json(handler, 200, {"events": events})
    return True


def handle_admin_sessions(handler, parsed) -> bool:
    """GET /api/admin/sessions — admin-only; all users' sessions."""
    user = _current_user(handler)
    if not user:
        _send_json(handler, 401, {"error": "Authentication required"})
        return True
    if not is_admin(user):
        _send_json(handler, 403, {"error": "Admin required"})
        return True
    from api.session_store import list_all_sessions_for_admin
    sessions_dir = STATE_DIR / "sessions"
    all_s = list_all_sessions_for_admin(sessions_dir)
    _audit.write(
        category="rbac",
        action="admin.sessions_view",
        actor_id=user["id"], actor_name=user["username"],
    )
    _send_json(handler, 200, {"sessions": all_s})
    return True


# ── Static page routes ──────────────────────────────────────────────────────

def handle_setup_page(handler, parsed) -> bool:
    """GET /setup — first-time admin creation page."""
    try:
        html_path = Path(__file__).parent.parent / "static" / "setup.html"
        html = html_path.read_text(encoding="utf-8")
        body = html.encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "text/html; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        handler.wfile.write(body)
    except Exception:
        _send_text(handler, 500, "Internal server error")
    return True


# ── Dispatcher entry-point ───────────────────────────────────────────────────

def try_handle_rbac(method: str, parsed, handler) -> bool:
    """Top-level dispatch: return True if request was an RBAC route.

    Wire into api/routes.py handle_get / handle_post / handle_delete / handle_put
    by inserting at the top, e.g.:
        if try_handle_rbac('GET', parsed, handler):
            return True
    """
    path = parsed.path

    # Static page routes (public, no auth)
    if method == "GET" and path == "/setup":
        return handle_setup_page(handler, parsed)

    # Public (no auth) API routes
    if method == "POST" and path == "/api/auth/login":
        return handle_auth_login(handler, parsed)
    if method == "POST" and path == "/api/auth/register":
        return handle_auth_register(handler, parsed)
    if method == "POST" and path == "/api/auth/logout":
        return handle_auth_logout(handler, parsed)
    if method == "GET" and path == "/api/auth/init_status":
        return handle_auth_init_status(handler, parsed)

    # Authenticated routes
    if method == "GET" and path == "/api/sessions":
        return handle_sessions_list(handler, parsed)
    if method == "POST" and path.startswith("/api/sessions/") and path.endswith("/share"):
        return handle_session_share(handler, parsed)
    if method == "POST" and path.startswith("/api/sessions/") and path.endswith("/share/token"):
        return handle_session_share_token(handler, parsed)
    if method == "DELETE" and path.startswith("/api/sessions/") and "/share/" in path:
        return handle_session_share_revoke(handler, parsed)

    # Admin routes
    if method == "GET" and path == "/api/admin/users":
        return handle_admin_users_list(handler, parsed)
    if method == "POST" and path == "/api/admin/users":
        return handle_admin_users_create(handler, parsed)
    if method == "PUT" and path.startswith("/api/admin/users/") and path.endswith("/role"):
        return handle_admin_users_update_role(handler, parsed)
    if method == "DELETE" and path.startswith("/api/admin/users/"):
        return handle_admin_users_delete(handler, parsed)
    if method == "GET" and path == "/api/admin/audit":
        return handle_admin_audit(handler, parsed)
    if method == "GET" and path == "/api/admin/sessions":
        return handle_admin_sessions(handler, parsed)

    return False