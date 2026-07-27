"""Regression test for the "Failed to load session — page frozen" UX.

On slow / internal networks the 30s default api() timeout can trip before
the Phase-1 session-metadata call completes (cold disk reads + active-
profile env resolution), surfacing a generic "Request timed out" toast
plus a static "Failed to load session. Try refreshing or switching
sessions." inline message. The user had no way to recover without a
full page refresh, so the page felt permanently stuck.

Two changes pinned here:

1. The loadSession Phase-1 metadata fetch uses an explicit 60s
   ``timeoutMs`` so a slow-but-eventually-successful disk read doesn't
   trip the generic toast.

2. The "Failed to load session" empty-state message now contains a
   ``<button data-load-retry="1">Retry</button>`` wired to
   ``loadSession(sid, { force: true })`` so the user can recover in-place.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SESSIONS_JS = (ROOT / "static" / "sessions.js").read_text(encoding="utf-8")


def _extract_load_session_phase1(src: str) -> str:
    """Extract the slice around the loadSession Phase-1 metadata fetch
    (the ``data = await api(`/api/session?...messages=0...`` block)."""
    m = re.search(
        r"let data;\s*\n\s*try\s*\{\s*\n\s*data\s*=\s*await api\(`/api/session\?"
        r"session_id=\$\{encodeURIComponent\(sid\)\}&messages=0&resolve_model=0`",
        src,
    )
    if not m:
        raise AssertionError("loadSession Phase-1 fetch anchor not found")
    return src[m.start() : m.start() + 700]


def _extract_failed_to_load_message(src: str) -> str:
    """Extract the slice around the inline 'Failed to load session' error
    message in loadSession's catch block."""
    m = re.search(
        r"_clearStuckSessionOnBoot\(sid,\s*currentSid\);",
        src,
    )
    if not m:
        raise AssertionError("Failed-to-load inline message anchor not found")
    return src[m.start() : m.start() + 1500]


# ---------------------------------------------------------------------------
# 1. Phase-1 metadata fetch uses an extended timeout (60s).
# ---------------------------------------------------------------------------

def test_load_session_phase1_uses_extended_timeout():
    """The Phase-1 metadata fetch must NOT use api()'s 30s default. Cold
    disk reads on internal networks can push past it; without an explicit
    timeoutMs the user sees a generic "Request timed out" toast on every
    first load."""
    block = _extract_load_session_phase1(SESSIONS_JS)
    assert "timeoutMs" in block, (
        "loadSession Phase-1 metadata fetch must pass an explicit "
        "timeoutMs option so a slow-but-eventually-successful disk read "
        "doesn't trip the generic 30s timeout"
    )
    # Match a numeric timeoutMs in the same block.
    m = re.search(r"timeoutMs\s*:\s*(\d+)", block)
    assert m, "expected a numeric timeoutMs value"
    timeout_s = int(m.group(1)) // 1000
    assert timeout_s >= 45, (
        f"timeoutMs {timeout_s}s is too tight for cold disk reads on slow "
        f"networks — must be >= 45s"
    )


# ---------------------------------------------------------------------------
# 2. Inline error message includes a Retry button wired to loadSession.
# ---------------------------------------------------------------------------

def test_failed_to_load_message_has_retry_button():
    """The inline 'Failed to load session' empty state must include a
    Retry button so users can recover in-place on slow networks."""
    block = _extract_failed_to_load_message(SESSIONS_JS)
    assert "data-load-retry" in block, (
        "Failed-to-load inline message must include a "
        "<button data-load-retry=\"1\">Retry</button> so users can "
        "recover without a full page refresh"
    )
    assert "loadSession" in block and "force: true" in block, (
        "Retry button click handler must call "
        "loadSession(sid, { force: true }) to re-attempt the metadata "
        "fetch"
    )


def test_failed_to_load_message_still_describes_problem():
    """Defensive: keep the original 'Failed to load session. Try refreshing
    or switching sessions.' text in the inline message so the user still
    knows what happened (not just a bare Retry button)."""
    block = _extract_failed_to_load_message(SESSIONS_JS)
    assert "Failed to load session" in block, (
        "inline message must keep the 'Failed to load session' description"
    )