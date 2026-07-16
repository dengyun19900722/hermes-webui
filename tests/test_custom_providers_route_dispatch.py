"""Regression test for /api/custom_providers NameError (#custom-model-config).

The original implementation tried to dispatch by HTTP method inside
``handle_post`` using a bare ``if method == "GET":`` check. Because ``method``
isn't a local variable in that function (and isn't even an attribute of the
``parsed`` namespace-arg), every POST request raised ``NameError: name
'method' is not defined`` and returned HTTP 500. The fix routes GET to
``handle_get`` and lets ``handle_post`` handle only POST.

This file pins both halves so the bug can't silently come back.
"""

import io
import json


class _FakeHandler:
    """Minimal handler that supports GET + POST body reading.

    Mirrors the fixture used in tests/test_1560_password_env_var_no_op.py so
    the route handlers (which call ``read_body``/``_check_csrf``/etc.) can run
    in isolation.
    """

    def __init__(self, body_bytes: bytes = b"", cookie: str = ""):
        self.status = None
        self.sent_headers = []
        self.body = bytearray()
        self.wfile = self
        self.rfile = io.BytesIO(body_bytes)
        self.headers = {"Content-Length": str(len(body_bytes))}
        if cookie:
            self.headers["Cookie"] = cookie
        # _check_csrf / set_auth_cookie probe handler.request; safe to None.
        self.request = None

    def send_response(self, status):
        self.status = status

    def send_header(self, name, value):
        self.sent_headers.append((name, value))

    def end_headers(self):
        pass

    def write(self, data):
        self.body.extend(data)


def _payload(handler) -> dict:
    return json.loads(bytes(handler.body).decode("utf-8"))


def test_post_custom_providers_does_not_raise_name_error(tmp_path, monkeypatch):
    """POST /api/custom_providers (upsert) must NOT raise NameError on `method`.

    Regression: previously the dispatch used a bare ``if method == "GET":``
    inside ``handle_post`` which raised NameError because ``method`` was never
    defined. This caused every save attempt to 500.
    """
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HERMES_WEBUI_PASSWORD", "")  # keep CSRF happy
    monkeypatch.setenv("HERMES_AUTH_DISABLED", "1")  # bypass auth/license gate

    body = json.dumps(
        {
            "action": "upsert",
            "skip_probe": True,  # skip network probe to keep the test offline
            "provider": {
                "slug": "demo-route",
                "name": "Demo Route",
                "base_url": "https://example.com/v1",
                "api_key": "sk-route-test",
                "models": ["demo-1"],  # list of model-id strings, per validate_provider_body
            },
        }
    ).encode("utf-8")

    from urllib.parse import urlparse

    from api.routes import handle_post

    handler = _FakeHandler(body_bytes=body)
    parsed = urlparse("http://example.com/api/custom_providers")

    # Should NOT raise NameError; result should be a valid HTTP response.
    handle_post(handler, parsed)

    assert handler.status == 200, (
        f"POST /api/custom_providers must succeed; got status={handler.status}, "
        f"body={_payload(handler)!r}"
    )
    payload = _payload(handler)
    # Upsert returns {"ok": True, "succeeded_count": N, ...}
    assert payload.get("ok") is True


def test_get_custom_providers_returns_list(monkeypatch, tmp_path):
    """GET /api/custom_providers must return {"providers": [...]} via handle_get."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HERMES_AUTH_DISABLED", "1")

    from urllib.parse import urlparse

    from api.routes import handle_get

    handler = _FakeHandler()
    parsed = urlparse("http://example.com/api/custom_providers")

    handle_get(handler, parsed)

    assert handler.status == 200, (
        f"GET /api/custom_providers must succeed; got status={handler.status}"
    )
    payload = _payload(handler)
    assert "providers" in payload, (
        f"GET /api/custom_providers must include `providers` key; got {payload!r}"
    )
    assert isinstance(payload["providers"], list)