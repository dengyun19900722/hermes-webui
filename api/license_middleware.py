"""License state middleware — gates requests before RBAC auth.

Reuses api.license.py without modification. License status acts as a
platform-level prerequisite that precedes any RBAC checks.
"""
from pathlib import Path

from api.license import init_license_config, check_license_status


WHITELIST_PREFIXES = (
    "/static/",
    "/session/static/",
    "/license",
    "/api/license/",
)


def _is_whitelisted_path(path: str) -> bool:
    """Return True for paths that bypass license gate."""
    if path == "/health":
        return True
    if path.startswith("/static/") or path.startswith("/session/static/"):
        return True
    if path == "/license" or path.startswith("/license/"):
        return True
    if path.startswith("/api/license/"):
        return True
    return False


def _send_json(handler, status_code: int, payload: dict) -> None:
    """Send a JSON error response."""
    import json
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status_code)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _send_403(handler, message: str) -> None:
    """Send a plain-text 403 response."""
    body = message.encode("utf-8")
    handler.send_response(403)
    handler.send_header("Content-Type", "text/plain; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _send_redirect(handler, location: str) -> None:
    """Send a 302 redirect."""
    handler.send_response(302)
    handler.send_header("Location", location)
    handler.send_header("Content-Length", "0")
    handler.end_headers()


def check_license_gate(handler, parsed, workspace: Path) -> bool:
    """Gate request by license state. Returns True if request may proceed.

    Behavior:
      - Whitelisted paths always pass.
      - license module errors: pass through (back-compat).
      - not_activated: 302 → /license/activate (HTML) / 503 JSON (API).
      - expired: 403 plain text.
      - copied:   403 plain text.
      - valid:    pass through to RBAC.
    """
    if _is_whitelisted_path(parsed.path):
        return True

    try:
        init_license_config(workspace)
        status = check_license_status(workspace)
    except Exception:
        # License 模块异常时放行，保持向后兼容
        return True

    license_state = status.get("status")

    if license_state == "expired":
        _send_403(handler, "License 已过期，请联系管理员续期")
        return False

    if license_state == "copied":
        _send_403(handler, "License 检测到 MAC 变更，请重新激活")
        return False

    if license_state == "not_activated":
        if parsed.path.startswith("/api/"):
            _send_json(handler, 503, {"error": "License not activated"})
        else:
            _send_redirect(handler, "/license/activate")
        return False

    # valid (or unknown status) → 放行
    return True