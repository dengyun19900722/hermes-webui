"""Regression coverage for bounded Provider settings lookups."""

import threading
import time


def test_provider_lookup_timeout_uses_static_fallback(monkeypatch):
    """A stalled optional provider probe must not block the Settings request."""
    from api import providers

    started = threading.Event()
    release = threading.Event()

    def slow_lookup():
        started.set()
        release.wait(1)
        return {"logged_in": True}

    monkeypatch.setattr(providers, "_PROVIDER_LIVE_LOOKUP_TIMEOUT_SECONDS", 0.01)
    started_at = time.monotonic()
    try:
        result = providers._run_bounded_provider_lookup("test", "auth", slow_lookup)
    finally:
        release.set()

    assert started.wait(0.1)
    assert result is None
    assert time.monotonic() - started_at < 0.2
