"""Regression test for the "elapsed timer starts from 7m43s" bug.

After deploying to an internal network, starting a new session / new Q&A
in an existing session showed the elapsed timer starting from the previous
turn's age instead of 0s (e.g. "7m43s" on a fresh send).

Root cause: messages.js set ``S.session.pending_started_at`` only when it
was unset (``if(!S.session.pending_started_at) ...``). If the previous
turn left a stale value (server hadn't cleared it yet for offline /
reconnect / stale-local-state reasons), the new turn reused that
timestamp and the timer counted from the OLD turn's start.

Fix: always reset to ``Date.now()/1000`` for a new user turn. The
server's authoritative value (returned by /api/chat/start or attach)
still overrides.

This file pins the new-turn paths so the conditional can't sneak back in,
while still allowing the conditional in reattach paths (where we must
preserve the existing in-flight timestamp).
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MESSAGES_JS = (ROOT / "static" / "messages.js").read_text(encoding="utf-8")


def _has_conditional_set(block: str) -> bool:
    """True if the block contains a conditional set that preserves any
    pre-existing pending_started_at (the OLD buggy form on the new-turn
    path; the desired form on the reattach path).

    Two equivalent shapes appear in the codebase:
    - ``if(S.session && !S.session.pending_started_at) S.session.pending_started_at = Date.now()/1000``
      (sendMessage pre-start + error-recovery, pre-fix)
    - ``if(!S.session.pending_started_at) S.session.pending_started_at = Date.now()/1000``
      (attachLiveStream reattach, current — keep)
    """
    patterns = [
        re.compile(
            r"if\s*\(\s*S\.session\s*(?:&&|&\&)\s*!S\.session\.pending_started_at\s*\)"
            r"\s*S\.session\.pending_started_at\s*=\s*Date\.now\(\)/1000",
            re.MULTILINE,
        ),
        re.compile(
            r"if\s*\(\s*!S\.session\.pending_started_at\s*\)"
            r"\s*S\.session\.pending_started_at\s*=\s*Date\.now\(\)/1000",
            re.MULTILINE,
        ),
    ]
    return any(p.search(block) for p in patterns)


def _has_unconditional_set(block: str) -> bool:
    """True if the block contains the CORRECT unconditional set:
    ``if(S.session) S.session.pending_started_at = Date.now()/1000;``
    """
    pattern = re.compile(
        r"if\s*\(\s*S\.session\s*\)\s*S\.session\.pending_started_at\s*=\s*Date\.now\(\)/1000",
        re.MULTILINE,
    )
    return pattern.search(block) is not None


def _extract_send_message_turn_start(src: str) -> str:
    """Extract the slice around the optimistic pre-start set
    (``S.messages.push(userMsg); ... ensureLiveWorklogShell``) — the path
    executed when the user clicks Send on a fresh turn.
    """
    m = re.search(
        r"S\.messages\.push\(userMsg\);renderMessages\(\);setBusy\(true\);",
        src,
    )
    if not m:
        raise AssertionError("sendMessage pre-start anchor not found")
    start = m.start()
    # Window: 700 chars to comfortably cover the (now multi-line) conditional
    # + comment + the unconditional set.
    return src[start : start + 700]


def _extract_send_message_error_recovery(src: str) -> str:
    """Extract the slice around the error-recovery pre-start set (the catch
    block that re-pushes optimistic messages after a preStartError).
    """
    m = re.search(
        r"INFLIGHT\[activeSid\]=\{messages:optimisticMessages,uploaded:uploadedNames,toolCalls:\[\]\};\s*\n\s*try\{setBusy\(true\);\}catch",
        src,
    )
    if not m:
        raise AssertionError("sendMessage error-recovery anchor not found")
    start = m.start()
    return src[start : start + 700]


def test_new_turn_pre_start_resets_pending_started_at_unconditionally():
    """The optimistic pre-start set in sendMessage must NOT use the old
    conditional pattern. It must reset unconditionally for a new turn."""
    block = _extract_send_message_turn_start(MESSAGES_JS)
    assert not _has_conditional_set(block), (
        "sendMessage pre-start still uses the conditional pattern "
        "`if(!S.session.pending_started_at)` — this leaks the previous "
        "turn's timestamp into the new turn's elapsed timer "
        "(#WebUI internal-network 7m43s repro)"
    )
    assert _has_unconditional_set(block), (
        "sendMessage pre-start must unconditionally reset "
        "S.session.pending_started_at = Date.now()/1000 for a new turn"
    )


def test_new_turn_error_recovery_resets_pending_started_at_unconditionally():
    """The error-recovery pre-start set (after preStartError) must also
    unconditionally reset for a new turn."""
    block = _extract_send_message_error_recovery(MESSAGES_JS)
    assert not _has_conditional_set(block), (
        "sendMessage error-recovery still uses the conditional pattern "
        "`if(!S.session.pending_started_at)` — same 7m43s regression risk "
        "as the happy path"
    )
    assert _has_unconditional_set(block), (
        "sendMessage error-recovery must unconditionally reset "
        "S.session.pending_started_at for a new turn"
    )


def test_attach_live_stream_keeps_conditional():
    """The attachLiveStream reattach path MUST keep the conditional set:
    we only want to set pending_started_at when one isn't already present
    (server-provided or in-flight). This is what keeps an in-flight turn's
    elapsed timer from resetting after an SSE reconnect.

    This guards against an over-eager fix that would also break the
    reattach path.
    """
    # The reattach path anchors on `if (existingLive && existingLive.streamId
    # === streamId) return true;` followed by `S.session.active_stream_id =
    # streamId;` and the conditional pending_started_at set.
    m = re.search(
        r"existingLive\s*&&\s*existingLive\.streamId\s*===\s*streamId\s*\)\s*return\s+true;\s*\n"
        r"\s*S\.busy\s*=\s*true;",
        MESSAGES_JS,
    )
    assert m, "attachLiveStream reattach anchor not found"
    block = MESSAGES_JS[m.start() : m.start() + 800]
    # Either the simple `if(!...pending_started_at) ... = Date.now()` form
    # OR the `typeof d.pending_started_at === 'number' ? ... : else if(...)`
    # form (used in the stream-recover path) preserves an existing
    # startedAt.
    has_conditional = _has_conditional_set(block)
    has_server_preferred = "typeof d.pending_started_at" in block
    assert has_conditional or has_server_preferred, (
        "attachLiveStream reattach path should still preserve the existing "
        "pending_started_at (server-provided or previously set) instead "
        "of unconditionally resetting — otherwise the SSE reconnect would "
        "restart the elapsed timer at 0s on every blip"
    )


def test_no_more_unconditional_conditional_pairs_on_send_paths():
    """Belt-and-braces: search the whole file for any remaining
    `if(S.session && !S.session.pending_started_at) ... = Date.now()/1000`
    pattern (the buggy sendMessage shape) and assert there are zero hits.
    The reattach path uses the simpler `if(!S.session.pending_started_at)`
    shape and is allowed to keep it.
    """
    buggy = re.findall(
        r"if\s*\(\s*S\.session\s*(?:&&|&\&)\s*!S\.session\.pending_started_at\s*\)"
        r"\s*S\.session\.pending_started_at\s*=\s*Date\.now\(\)/1000",
        MESSAGES_JS,
    )
    assert not buggy, (
        f"Found {len(buggy)} leftover buggy conditional set(s) in "
        f"sendMessage paths — these leak the previous turn's timestamp "
        f"into the new turn's elapsed timer (#WebUI internal-network 7m43s "
        f"repro). Only the reattach path's simpler "
        f"`if(!S.session.pending_started_at)` shape may remain."
    )