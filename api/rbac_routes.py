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
    invalidate_all_user_sessions,
    invalidate_user_session,
    is_admin,
    needs_initialization,
    initialize_first_admin,
    verify_password_against_hash,
    _hash_password,
)
from api.user_store import find_user_by_username, find_user_by_id, update_password
from api.config import STATE_DIR
from api.helpers import j


# Password complexity rules for self-service change.
# Mirrored from api.admin.create_user so that admins and users have the same
# surface (8+ chars AND must contain both letters and digits). When you tune
# these, also update the i18n keys in static/i18n.js
#   password_too_short, password_needs_classes
_MIN_PASSWORD_LEN = 8


def _validate_password_complexity(password: str) -> str | None:
    """Return i18n error key when password fails complexity, else None.

    Rules (deliberately simple — see _MIN_PASSWORD_LEN):
      - length < _MIN_PASSWORD_LEN → "password_too_short"
      - missing letter OR missing digit → "password_needs_classes"
    """
    if not isinstance(password, str) or len(password) < _MIN_PASSWORD_LEN:
        return "password_too_short"
    has_letter = any(c.isalpha() for c in password)
    has_digit = any(c.isdigit() for c in password)
    if not (has_letter and has_digit):
        return "password_needs_classes"
    return None


def _read_json_body(handler) -> dict:
    """Read and parse JSON body from handler.rfile."""
    content_length = int(handler.headers.get("Content-Length", 0))
    raw = handler.rfile.read(content_length) if content_length else b"{}"
    decoded = raw.decode("utf-8", errors="replace").strip() or "{}"
    try:
        return json.loads(decoded)
    except json.JSONDecodeError as e:
        import logging
        logging.getLogger(__name__).error(
            "[rbac] Failed to parse JSON body: len=%d content=%r headers[Content-Type]=%r",
            len(raw), raw[:200], handler.headers.get("Content-Type"),
        )
        raise


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
    cookie = (
        f"hermes_session={token}; HttpOnly; Path=/; SameSite=Lax; Max-Age=2592000"
    )
    payload = {
        "user": {
            "id": user["id"],
            "username": user["username"],
            "role": user.get("role", "user"),
        }
    }
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Set-Cookie", cookie)
    handler.end_headers()
    handler.wfile.write(body)
    return True


def handle_auth_logout(handler, parsed) -> bool:
    """POST /api/auth/logout — invalidate current session."""
    content_length = int(handler.headers.get("Content-Length", 0) or 0)
    if content_length:
        handler.rfile.read(content_length)
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
    from api.auth import clear_auth_cookie

    body = json.dumps({"ok": True}).encode("utf-8")
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    clear_auth_cookie(handler)
    handler.end_headers()
    handler.wfile.write(body)
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


def handle_auth_change_password(handler, parsed) -> bool:
    """POST /api/auth/change-password — authenticated user updates own password.

    Body: ``{"old_password": "...", "new_password": "..."}``.

    Order of checks (each short-circuits with a 4xx + i18n-friendly error key):
      1. Must be logged in                  → 401 "auth_required"
      2. Body must include both fields      → 400 "missing_field"
      3. old_password must verify           → 400 "password_old_wrong"
      4. new_password must pass complexity  → 400 "password_too_short" | "password_needs_classes"

    Side effects on success:
      - user.password_hash replaced on disk via api.user_store.update_password
      - all OTHER sessions for this user are invalidated; current keep_token preserved
      - audit.write(category='rbac', action='password.change') fired

    Returns ``{ok: true}`` on success. Errors use the same i18n-key
    ``error`` field that the frontend already maps to a translated string.
    """
    user = _current_user(handler)
    if not user:
        _send_json(handler, 401, {"error": "auth_required"})
        return True

    try:
        body = _read_json_body(handler)
    except json.JSONDecodeError:
        _send_json(handler, 400, {"error": "invalid_json"})
        return True

    old_password = body.get("old_password") or ""
    new_password = body.get("new_password") or ""
    if not old_password or not new_password:
        _send_json(handler, 400, {"error": "missing_field"})
        return True

    # Verify current password against the user's stored hash. We re-load
    # the user record (instead of trusting the caller-supplied user dict)
    # so a stale cookie pointing at a deleted user is rejected.
    record = find_user_by_id(Path(STATE_DIR), str(user.get("id") or ""))
    if not record:
        _send_json(handler, 401, {"error": "auth_required"})
        return True
    stored_hash = record.get("password_hash") or ""
    if not stored_hash or not verify_password_against_hash(old_password, stored_hash):
        _send_json(handler, 400, {"error": "password_old_wrong"})
        return True

    # Complexity check (length + classes)
    complexity_err = _validate_password_complexity(new_password)
    if complexity_err:
        _send_json(handler, 400, {"error": complexity_err})
        return True

    # All checks passed — persist new hash + kick other sessions.
    try:
        new_hash = _hash_password(new_password)
        update_password(Path(STATE_DIR), str(user["id"]), new_hash)
    except Exception:
        _send_json(handler, 500, {"error": "internal_error"})
        return True

    keep_token = _get_session_token(handler)
    try:
        invalidate_all_user_sessions(str(user["id"]), keep_token=keep_token)
    except Exception:
        # Don't fail the request — password is already updated.
        pass

    _audit.write(
        category="rbac",
        action="password.change",
        actor_id=user["id"], actor_name=user.get("username"),
        target_type="user", target_id=user["id"], target_name=user.get("username"),
        details={"via": "self"},
    )
    _send_json(handler, 200, {"ok": True})
    return True


# ── /api/sessions/* (sharing — backed by api/share_store.py + real Sessions) ──

def _load_owned_session(handler, session_id: str):
    """Load the real Session and verify the requester may share it.

    Returns (session, None) when allowed (owner or admin), else (None, error_json).
    """
    from api.models import get_session
    try:
        session = get_session(session_id, metadata_only=True)
    except KeyError:
        return None, (404, {"error": "Session not found"})
    user = _current_user(handler)
    owner = str(getattr(session, "rbac_user_id", None) or "").strip()
    if is_admin(user) or (owner and owner == str(user.get("id") or "")):
        return session, None
    if not owner:
        return None, (403, {"error": "Only an admin can share ownerless legacy sessions"})
    return None, (403, {"error": "Only the session owner can share this session"})


def _session_summary(session) -> dict:
    try:
        return session.compact()
    except Exception:
        return {
            "session_id": getattr(session, "session_id", None),
            "title": getattr(session, "title", "Untitled"),
            "message_count": len(getattr(session, "messages", None) or []),
        }


def handle_sessions_list(handler, parsed) -> bool:
    """GET /api/rbac/sessions — own + shared sessions for current user."""
    user = _current_user(handler)
    if not user:
        _send_json(handler, 401, {"error": "Authentication required"})
        return True
    from api import share_store
    shared = share_store.list_shares_for_user(STATE_DIR, user["id"])
    _send_json(handler, 200, {"shared": shared})
    return True


def handle_users_list(handler, parsed) -> bool:
    """GET /api/users — list users available for sharing (any authenticated user).

    Returns minimal public info (id, username, role) so non-admin users can
    pick recipients in the share dialog.  Excludes the caller themselves
    (no point sharing with yourself).  Legacy-auth callers get an empty
    list so the dropdown still renders without breaking the UI.
    """
    from api.admin import list_users
    caller = _current_user(handler)
    if not caller:
        _send_json(handler, 200, {"users": []})
        return True
    caller_id = str(caller.get("id") or "")
    public = [
        {"id": u.get("id"), "username": u.get("username"), "role": u.get("role", "user")}
        for u in list_users()
        if u.get("id") and str(u.get("id")) != caller_id
    ]
    _send_json(handler, 200, {"users": public})
    return True


def handle_sessions_shared(handler, parsed) -> bool:
    """GET /api/sessions/shared — incoming shares enriched with session summary.

    Unauthenticated / legacy-auth callers get an empty list (not 401) so the
    "收到的分享" sidebar section still renders for them and they can see
    that the feature exists.
    """
    user = _current_user(handler)
    if not user:
        _send_json(handler, 200, {"shared": []})
        return True
    from api import share_store
    from api.models import get_session
    result = []
    for share in share_store.list_shares_for_user(STATE_DIR, user["id"]):
        sid = str(share.get("session_id") or "")
        try:
            session = get_session(sid, metadata_only=True)
        except KeyError:
            continue  # session was deleted; skip
        result.append({
            "share_id": share.get("id"),
            "from_user_id": share.get("owner_id"),
            "from_username": share.get("owner_name"),
            "shared_at": share.get("created_at"),
            "session": _session_summary(session),
        })
    _send_json(handler, 200, {"shared": result})
    return True


def handle_session_share(handler, parsed) -> bool:
    """POST /api/sessions/{id}/share — share with one or more users.

    Accepts either ``{"username": "alice"}`` (single) or
    ``{"usernames": ["alice", "bob"]}`` / ``{"user_ids": ["..."]}`` (batch).
    Returns ``{"shares": [...], "failed": [{"username": "x", "error": "..."}]}``.
    """
    user = _current_user(handler)
    if not user:
        _send_json(handler, 401, {"error": "Authentication required"})
        return True
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 4:
        _send_json(handler, 400, {"error": "Bad request"})
        return True
    session_id = parts[2]
    body = _read_json_body(handler)

    # Collect requested recipients (deduped, preserves order).
    raw_names = body.get("usernames") or []
    raw_ids = body.get("user_ids") or []
    single = body.get("username")
    if isinstance(single, str) and single.strip():
        raw_names = [single] + (raw_names if isinstance(raw_names, list) else [])
    if not isinstance(raw_names, list):
        raw_names = []
    if not isinstance(raw_ids, list):
        raw_ids = []
    seen: set[str] = set()
    targets: list[tuple[str, dict]] = []  # (lookup_key, target_dict)
    for name in raw_names:
        n = str(name or "").strip()
        if not n or n in seen:
            continue
        seen.add(n)
        t = find_user_by_username(STATE_DIR, n)
        if t:
            targets.append((n, t))
    for uid in raw_ids:
        u = str(uid or "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        t = find_user_by_id(STATE_DIR, u)
        if t:
            targets.append((u, t))
    if not targets:
        _send_json(handler, 400, {"error": "username or user_ids required"})
        return True
    session, err = _load_owned_session(handler, session_id)
    if err:
        _send_json(handler, err[0], err[1])
        return True
    from api import share_store
    created_shares: list[dict] = []
    failed: list[dict] = []
    for key, target in targets:
        if str(target.get("id") or "") == str(user.get("id") or ""):
            failed.append({"key": key, "error": "Cannot share to yourself"})
            continue
        share = share_store.add_user_share(
            STATE_DIR,
            session_id=session_id,
            owner_id=str(user["id"]),
            owner_name=str(user.get("username") or ""),
            to_user_id=str(target.get("id")),
            to_username=str(target.get("username") or ""),
        )
        created_shares.append(share)
        _audit.write(
            category="rbac",
            action="session.share",
            actor_id=user["id"], actor_name=user["username"],
            target_type="session", target_id=session_id,
            target_name=str(target.get("username") or key),
            details={"method": "user", "to_user_id": target.get("id"), "share_id": share["id"]},
        )
    try:
        from api.routes import _publish_session_list_changed
        _publish_session_list_changed("session_share", session_id=session_id)
    except Exception:
        pass
    # Back-compat: also expose "share" (single) when only one recipient.
    resp: dict = {"shares": created_shares, "failed": failed}
    if len(created_shares) == 1 and not failed:
        resp["share"] = created_shares[0]
    _send_json(handler, 200, resp)
    return True


def handle_session_shares_list(handler, parsed) -> bool:
    """GET /api/sessions/{id}/shares — list share records for a session (owner/admin)."""
    user = _current_user(handler)
    if not user:
        _send_json(handler, 401, {"error": "Authentication required"})
        return True
    parts = [p for p in parsed.path.split("/") if p]
    # [api, sessions, {id}, shares]
    if len(parts) < 4:
        _send_json(handler, 400, {"error": "Bad request"})
        return True
    session_id = parts[2]
    session, err = _load_owned_session(handler, session_id)
    if err:
        _send_json(handler, err[0], err[1])
        return True
    from api import share_store
    shares = share_store.list_shares_for_session(STATE_DIR, session_id)
    for share in shares:
        if share.get("type") == "token" and share.get("token"):
            share["url"] = f"/api/shared/session?token={share['token']}"
    _send_json(handler, 200, {"shares": shares})
    return True


def handle_session_share_token(handler, parsed) -> bool:
    """POST /api/sessions/{id}/share/token — generate/reuse a share token link."""
    user = _current_user(handler)
    if not user:
        _send_json(handler, 401, {"error": "Authentication required"})
        return True
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 4:
        _send_json(handler, 400, {"error": "Bad request"})
        return True
    session_id = parts[2]
    session, err = _load_owned_session(handler, session_id)
    if err:
        _send_json(handler, err[0], err[1])
        return True
    from api import share_store
    share = share_store.add_token_share(
        STATE_DIR,
        session_id=session_id,
        owner_id=str(user["id"]),
        owner_name=str(user.get("username") or ""),
    )
    _audit.write(
        category="rbac",
        action="session.share",
        actor_id=user["id"], actor_name=user["username"],
        target_type="session", target_id=session_id, target_name="(token link)",
        details={"method": "token", "share_id": share["id"]},
    )
    payload = dict(share)
    payload["url"] = f"/api/shared/session?token={share['token']}"
    _send_json(handler, 200, {"share": payload})
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
    from api import share_store
    record = next(
        (s for s in share_store.list_shares_for_session(STATE_DIR, session_id)
         if str(s.get("id") or "") == share_id),
        None,
    )
    if record is None:
        _send_json(handler, 404, {"error": "Share not found"})
        return True
    # Only the share creator (owner) or admin may revoke.
    if not is_admin(user) and str(record.get("owner_id") or "") != str(user.get("id") or ""):
        _send_json(handler, 403, {"error": "Only the session owner can revoke this share"})
        return True
    ok = share_store.remove_share(STATE_DIR, share_id)
    if not ok:
        _send_json(handler, 404, {"error": "Share not found"})
        return True
    _audit.write(
        category="rbac",
        action="session.revoke",
        actor_id=user["id"], actor_name=user["username"],
        target_type="share", target_id=share_id, target_name=session_id,
    )
    try:
        from api.routes import _publish_session_list_changed
        _publish_session_list_changed("session_share", session_id=session_id)
    except Exception:
        pass
    _send_json(handler, 200, {"ok": True})
    return True


def handle_shared_session_token(handler, parsed) -> bool:
    """GET /api/shared/session?token=xxx — public read-only session payload."""
    qs = parse_qs(parsed.query or "")
    token = (qs.get("token", [""])[0] or "").strip()
    if not token:
        _send_json(handler, 400, {"error": "token required"})
        return True
    from api import share_store
    share = share_store.find_share_by_token(STATE_DIR, token)
    if not share:
        _send_json(handler, 403, {"error": "Invalid or expired share link"})
        return True
    sid = str(share.get("session_id") or "")
    from api.models import get_session
    try:
        session = get_session(sid, metadata_only=False)
    except KeyError:
        _send_json(handler, 404, {"error": "Session not found"})
        return True
    payload = _session_summary(session)
    payload["messages"] = getattr(session, "messages", None) or []
    payload["viewer"] = "shared"
    payload["shared_by"] = share.get("owner_name")
    _send_json(handler, 200, {"session": payload})
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
        new_user = create_user(username, password, role, panels=body.get("panels"))
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


def handle_admin_reset_password(handler, parsed, user_id: str) -> bool:
    """PUT /api/admin/users/{user_id}/password — admin resets another user's password.

    Body: ``{"new_password": "..."}``.

    Differences from POST /api/auth/change-password:
      - No old_password required (admin acts on behalf of user).
      - **Bypasses complexity** — admin reset is intentional: the admin may
        choose a short or otherwise "weak" password when restoring access
        to a locked-out account. Frontend should still warn but not block.
      - **All sessions kicked** (no ``keep_token``) — the user must log in
        again with whatever credential the admin hands them out-of-band.

    Order of checks:
      1. Caller logged in               → 401 "auth_required"
      2. Caller is admin                → 403 "admin_required"
      3. Body parses + new_password set → 400 "missing_field"
      4. Target user exists             → 404 "user_not_found"
      5. Hash + invalidate on success   → 200 ``{ok: true}``

    Audit: ``category='rbac', action='password.reset'`` with
    ``actor_id`` (admin) and ``target_id`` (reset victim).
    """
    caller = _current_user(handler)
    if not caller:
        _send_json(handler, 401, {"error": "auth_required"})
        return True
    if not is_admin(caller):
        _send_json(handler, 403, {"error": "admin_required"})
        return True

    try:
        body = _read_json_body(handler)
    except json.JSONDecodeError:
        _send_json(handler, 400, {"error": "invalid_json"})
        return True

    new_password = body.get("new_password") or ""
    if not new_password:
        _send_json(handler, 400, {"error": "missing_field"})
        return True

    # Reload target from disk — never trust caller-supplied fields.
    target = find_user_by_id(Path(STATE_DIR), str(user_id))
    if not target:
        _send_json(handler, 404, {"error": "user_not_found"})
        return True

    try:
        new_hash = _hash_password(new_password)
        update_password(Path(STATE_DIR), str(user_id), new_hash)
    except Exception:
        _send_json(handler, 500, {"error": "internal_error"})
        return True

    # Force a re-login: no keep_token — the victim is being kicked everywhere.
    try:
        invalidate_all_user_sessions(str(user_id))
    except Exception:
        # Don't fail the request — password is already updated.
        pass

    _audit.write(
        category="rbac",
        action="password.reset",
        actor_id=caller["id"], actor_name=caller.get("username"),
        target_type="user", target_id=str(user_id),
        target_name=target.get("username"),
        details={"via": "admin_api"},
    )
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


def handle_admin_users_update_panels(handler, parsed) -> bool:
    """PUT /api/admin/users/{id}/panels — admin updates a user's panel permissions."""
    user = _current_user(handler)
    if not user:
        _send_json(handler, 401, {"error": "Authentication required"})
        return True
    if not is_admin(user):
        _send_json(handler, 403, {"error": "Admin required"})
        return True
    parts = [p for p in parsed.path.split("/") if p]
    # [api, admin, users, {id}, panels]
    if len(parts) < 5:
        _send_json(handler, 400, {"error": "Bad request"})
        return True
    target_id = parts[3]
    body = _read_json_body(handler)
    panels = body.get("panels")
    if not isinstance(panels, list):
        _send_json(handler, 400, {"error": "panels must be a list of panel names"})
        return True
    try:
        from api.admin import update_user_panels
        updated = update_user_panels(
            target_id, panels,
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


# ── Knowledge base meta routes ───────────────────────────────────────────────

def _meta_dir() -> Path:
    """Return the .meta sidecar directory inside the Obsidian vault."""
    from api.obsidian_notes import vault_root
    return vault_root() / ".meta"


def handle_notes_meta_get(handler, parsed) -> bool:
    """GET /api/notes/meta/{path:.*} — fetch meta for a doc."""
    user = _current_user(handler)
    if not user:
        _send_json(handler, 401, {"error": "Authentication required"})
        return True
    from urllib.parse import unquote
    # /api/notes/meta/{path...}
    prefix = "/api/notes/meta/"
    doc_path = unquote(parsed.path[len(prefix):]) if parsed.path.startswith(prefix) else ""
    if not doc_path:
        _send_json(handler, 400, {"error": "path required"})
        return True
    from api.obsidian_meta import (
        load_meta, compute_rating_summary, get_creator, get_ratings,
    )
    meta_dir = _meta_dir()
    meta = load_meta(meta_dir, doc_path)
    creator = get_creator(meta_dir, doc_path)
    summary = compute_rating_summary(meta_dir, doc_path)
    # Find current user's rating
    my_rating = None
    uid = str(user.get("id") or "").strip()
    if uid:
        for r in get_ratings(meta_dir, doc_path):
            if str(r.get("user_id") or "").strip() == uid:
                my_rating = r.get("rating")
                break
    _send_json(handler, 200, {
        "creator_id": creator["creator_id"] if creator else None,
        "creator_name": creator["creator_name"] if creator else None,
        "rating_count": summary["count"],
        "rating_average": summary["average"],
        "my_rating": my_rating,
    })
    return True


def handle_notes_rate(handler, parsed) -> bool:
    """POST /api/notes/meta/{path:.*}/rate — submit/update rating 1-5."""
    user = _current_user(handler)
    if not user:
        _send_json(handler, 401, {"error": "Authentication required"})
        return True
    from urllib.parse import unquote
    # /api/notes/meta/{path}/rate
    prefix = "/api/notes/meta/"
    suffix = "/rate"
    if not (parsed.path.startswith(prefix) and parsed.path.endswith(suffix)):
        _send_json(handler, 400, {"error": "Bad request"})
        return True
    doc_path = unquote(parsed.path[len(prefix):-len(suffix)])
    if not doc_path:
        _send_json(handler, 400, {"error": "path required"})
        return True
    body = _read_json_body(handler)
    rating = body.get("rating")
    if not isinstance(rating, int) or not (1 <= rating <= 5):
        _send_json(handler, 400, {"error": "rating must be 1-5"})
        return True
    from api.obsidian_meta import add_or_update_rating
    record = add_or_update_rating(
        _meta_dir(), doc_path,
        user["id"], user["username"], rating,
    )
    _audit.write(
        category="rbac",
        action="doc.rate",
        actor_id=user["id"], actor_name=user["username"],
        target_type="doc", target_id=doc_path, target_name=doc_path,
        details={"rating": rating},
    )
    _send_json(handler, 200, {"record": record})
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

    # Authenticated self-service password change (RBAC)
    if method == "POST" and path == "/api/auth/change-password":
        return handle_auth_change_password(handler, parsed)

    # Public token view (no auth)
    if method == "GET" and path == "/api/shared/session":
        return handle_shared_session_token(handler, parsed)

    # Authenticated routes
    if method == "GET" and path == "/api/rbac/sessions":
        return handle_sessions_list(handler, parsed)
    if method == "GET" and path == "/api/users":
        return handle_users_list(handler, parsed)
    if method == "GET" and path == "/api/sessions/shared":
        return handle_sessions_shared(handler, parsed)
    if method == "POST" and path.startswith("/api/sessions/") and path.endswith("/share/token"):
        return handle_session_share_token(handler, parsed)
    if method == "POST" and path.startswith("/api/sessions/") and path.endswith("/share"):
        return handle_session_share(handler, parsed)
    if method == "GET" and path.startswith("/api/sessions/") and path.endswith("/shares"):
        return handle_session_shares_list(handler, parsed)
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
    if method == "PUT" and path.startswith("/api/admin/users/") and path.endswith("/panels"):
        return handle_admin_users_update_panels(handler, parsed)
    if method == "PUT" and path.startswith("/api/admin/users/") and path.endswith("/password"):
        # parts = ["api", "admin", "users", "{id}", "password"]
        parts = [p for p in path.split("/") if p]
        if len(parts) < 5:
            return False
        return handle_admin_reset_password(handler, parsed, parts[3])
    if method == "GET" and path == "/api/admin/audit":
        return handle_admin_audit(handler, parsed)
    if method == "GET" and path == "/api/admin/sessions":
        return handle_admin_sessions(handler, parsed)

    # Knowledge base meta (auth required)
    if method == "GET" and path.startswith("/api/notes/meta/") and not path.endswith("/rate"):
        return handle_notes_meta_get(handler, parsed)
    if method == "POST" and path.startswith("/api/notes/meta/") and path.endswith("/rate"):
        return handle_notes_rate(handler, parsed)

    return False
