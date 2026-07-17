"""Regression test for the cold-boot session-list timeout (#ZKREQ-138).

User reported the sidebar session list timed out on internal network with
a very large session history, showing "Session list is taking longer
than expected. The backend may still be scanning a very large session
history." The previous 90s budget was too tight — cold disk reads of
hundreds of sessions pushed past it.

Fix:
- Bump default cold-boot timeout from 90s to 180s.
- Allow override via window.HERMES_WEBUI_SESSION_LIST_BOOT_TIMEOUT_MS
  so deployments can tune without code changes.

This file pins both behaviours so they don't silently regress.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SESSIONS_JS = (ROOT / "static" / "sessions.js").read_text(encoding="utf-8")


def test_default_boot_timeout_at_least_three_minutes():
    """The cold-boot /api/sessions timeout must be at least 3 minutes so
    slow internal networks have a fair chance to finish scanning large
    session history before the user sees a timeout error."""
    # Find the const declaration with the default value. The IIFE body
    # contains nested braces (the catch block), so match a balanced block
    # via a simple bracket counter rather than [^}]*.
    start = SESSIONS_JS.find("const _SESSION_LIST_BOOT_TIMEOUT_MS")
    assert start >= 0, "_SESSION_LIST_BOOT_TIMEOUT_MS declaration not found"
    # Find the matching closing paren for the IIFE: '})()'
    i = SESSIONS_JS.find("})()", start)
    assert i >= 0, "IIFE closing not found"
    block = SESSIONS_JS[start : i + 4]
    m = re.search(r"return\s+(\d+)\s*;", block)
    assert m, "default return value not found in IIFE"
    default_ms = int(m.group(1))
    assert default_ms >= 180000, (
        f"default cold-boot timeout {default_ms}ms is below the 3-minute "
        f"floor required for slow / internal networks "
        f"(was 90s, raised to 180s after #ZKREQ-138)"
    )


def test_boot_timeout_overridable_via_window_global():
    """Deployments must be able to override the cold-boot timeout without
    a code change, by setting window.HERMES_WEBUI_SESSION_LIST_BOOT_TIMEOUT_MS
    before the script runs."""
    assert "HERMES_WEBUI_SESSION_LIST_BOOT_TIMEOUT_MS" in SESSIONS_JS, (
        "expected an override hook window.HERMES_WEBUI_SESSION_LIST_BOOT_TIMEOUT_MS"
    )
    # The override must actually be honoured: the IIFE must read window.*,
    # parse it as a finite number, and use it when > 0.
    block = re.search(
        r"const\s+_SESSION_LIST_BOOT_TIMEOUT_MS\s*=\s*\(\(\)\s*=>\s*\{(.+?)\}\)\(\s*\)\s*;",
        SESSIONS_JS,
        re.DOTALL,
    )
    assert block, "_SESSION_LIST_BOOT_TIMEOUT_MS IIFE not found"
    body = block.group(1)
    assert "window" in body, "IIFE must consult window for the override"
    assert "Number.isFinite" in body and "> 0" in body, (
        "IIFE must validate the override (finite + > 0) before using it"
    )


def test_session_list_request_uses_boot_timeout():
    """The renderSessionList boot path must apply the timeoutMs override."""
    # Anchor on the requestOpts construction that wires the boot timeout.
    m = re.search(
        r"if\s*\(\s*!_sessionListHasLoadedOnce\s*\)\s*\{\s*"
        r"sessionRequestOpts\.timeoutMs\s*=\s*_SESSION_LIST_BOOT_TIMEOUT_MS\s*;",
        SESSIONS_JS,
    )
    assert m, (
        "renderSessionList boot path must wire "
        "sessionRequestOpts.timeoutMs = _SESSION_LIST_BOOT_TIMEOUT_MS"
    )