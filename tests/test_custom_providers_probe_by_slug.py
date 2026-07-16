"""Regression test for probe-by-slug (#WebUI custom-model-config).

The "探测" button on a saved custom provider card used to send
``{base_url, api_key: null}`` to ``/api/custom_providers/probe_models``. The
server then made an unauthenticated request to the upstream, which returned
401/403 for any provider that requires an API key → every probe came back
``auth_failed``.

Fix: server-side ``probe_models(base_url, api_key=None, slug=None)`` now
loads the stored ``api_key`` from config when ``slug`` is provided and the
client didn't send a key. Client now sends ``{base_url, slug}`` instead of
``{base_url, api_key: null}`` so the stored key is reused.
"""

from __future__ import annotations

import io
import json
from pathlib import Path
from urllib.parse import urlparse
from unittest import mock

import pytest


@pytest.fixture
def fake_profile_home(tmp_path, monkeypatch):
    """Create a fake profile home with one custom provider + patch the lookup."""
    profile = tmp_path / "fake_profile"
    profile.mkdir()
    (profile / "config.yaml").write_text(
        """\
custom_providers:
  - slug: minimax-test
    name: minimax-test
    base_url: https://upstream.example.com
    api_key: my-secret-key-123
    models:
      - foo
      - bar
""",
        encoding="utf-8",
    )
    # The module reads list_all_profile_homes() at runtime, so monkeypatching
    # the function in the module's namespace is enough.
    from api import custom_providers as cp_mod

    monkeypatch.setattr(cp_mod, "list_all_profile_homes", lambda: [profile])
    return profile


class _FakeHandler:
    """Minimal BaseHTTPRequestHandler stand-in for routes.handle_post."""

    def __init__(self, body_bytes: bytes = b"") -> None:
        self.status = None
        self.sent_headers: list[tuple[str, str]] = []
        self.body = bytearray()
        self.wfile = self
        self.rfile = io.BytesIO(body_bytes)
        self.headers = {"Content-Length": str(len(body_bytes))}
        self.request = None

    def send_response(self, status: int) -> None:
        self.status = status

    def send_header(self, name: str, value: str) -> None:
        self.sent_headers.append((name, value))

    def end_headers(self) -> None:
        pass

    def write(self, data: bytes) -> None:
        self.body.extend(data)


def _fake_response(payload: dict, status: int = 200):
    r = mock.MagicMock()
    r.status_code = status
    r.json.return_value = payload
    return r


def test_probe_models_slug_loads_stored_key(fake_profile_home):
    """probe_models(slug=...) must use the stored api_key for the upstream."""
    from api.custom_providers import probe_models

    captured: dict = {}

    def fake_get(url, headers=None, timeout=None):
        captured.update(headers or {})
        return _fake_response({"data": [{"id": "foo"}, {"id": "bar"}]})

    with mock.patch("requests.get", side_effect=fake_get):
        result = probe_models(
            "", api_key=None, slug="minimax-test", timeout=4.0
        )

    assert result["ok"] is True
    assert set(result["models"]) == {"foo", "bar"}
    assert captured.get("Authorization") == "Bearer my-secret-key-123", (
        "probe_models must use the stored api_key when slug resolves to a "
        "provider and the client didn't pass one"
    )


def test_probe_models_explicit_api_key_wins(fake_profile_home):
    """If the client passes api_key explicitly, that takes priority over the
    stored key (lets users re-probe with a freshly-rotated key)."""
    from api.custom_providers import probe_models

    captured: dict = {}

    def fake_get(url, headers=None, timeout=None):
        captured.update(headers or {})
        return _fake_response({"data": [{"id": "foo"}]})

    with mock.patch("requests.get", side_effect=fake_get):
        result = probe_models(
            "https://upstream.example.com",
            api_key="explicit-key",
            slug="minimax-test",
            timeout=4.0,
        )

    assert result["ok"] is True
    assert captured.get("Authorization") == "Bearer explicit-key"


def test_probe_models_unknown_slug_returns_error(fake_profile_home):
    """Unknown slug must short-circuit with unknown_slug so we don't burn a
    network round-trip on a typo."""
    from api.custom_providers import probe_models

    result = probe_models("", api_key=None, slug="does-not-exist", timeout=4.0)

    assert result["ok"] is False
    assert result["error"] == "unknown_slug"


def test_http_probe_endpoint_accepts_slug(fake_profile_home):
    """POST /api/custom_providers/probe_models with {slug} must resolve the
    stored key server-side (this is what the saved-card "探测" button sends)."""
    from api.routes import handle_post

    captured: dict = {}

    def fake_get(url, headers=None, timeout=None):
        captured.update(headers or {})
        return _fake_response({"data": [{"id": "foo"}, {"id": "bar"}]})

    body = json.dumps({"slug": "minimax-test"}).encode("utf-8")
    handler = _FakeHandler(body_bytes=body)
    parsed = urlparse("http://example.com/api/custom_providers/probe_models")

    with mock.patch("requests.get", side_effect=fake_get):
        handle_post(handler, parsed)

    assert handler.status == 200, (
        f"expected 200 from probe_models endpoint, got {handler.status}, "
        f"body={bytes(handler.body)!r}"
    )
    payload = json.loads(bytes(handler.body).decode("utf-8"))
    assert payload.get("ok") is True
    assert set(payload.get("models") or []) == {"foo", "bar"}
    assert captured.get("Authorization") == "Bearer my-secret-key-123", (
        "HTTP probe endpoint must load the stored api_key for an authenticated "
        "upstream when only slug is provided"
    )


def test_http_probe_endpoint_still_accepts_api_key():
    """Backwards-compat: existing callers that send api_key explicitly (the
    modal's "探测后保存" flow) must continue to work — api_key wins over any
    stored value."""
    from api.routes import handle_post

    captured: dict = {}

    def fake_get(url, headers=None, timeout=None):
        captured.update(headers or {})
        return _fake_response({"data": [{"id": "x"}]})

    body = json.dumps(
        {
            "base_url": "https://upstream.example.com",
            "api_key": "explicit-key",
        }
    ).encode("utf-8")
    handler = _FakeHandler(body_bytes=body)
    parsed = urlparse("http://example.com/api/custom_providers/probe_models")

    with mock.patch("requests.get", side_effect=fake_get):
        handle_post(handler, parsed)

    assert handler.status == 200
    assert captured.get("Authorization") == "Bearer explicit-key"