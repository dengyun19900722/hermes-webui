"""Regression coverage: live assistant text should follow the tail while pinned.

Streaming token renders used the generic ``scrollIfPinned()`` path. That path is
correct for broad DOM updates, but a live stream can temporarily lose
``_scrollPinned`` when content grows beneath a stationary followed viewport. The
streaming text frame needs a stricter "follow unless the reader manually
unpinned" policy so the viewport stays on the newest generated text.
"""

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
UI_JS = (ROOT / "static" / "ui.js").read_text(encoding="utf-8")
MESSAGES_JS = (ROOT / "static" / "messages.js").read_text(encoding="utf-8")
NODE = shutil.which("node")


def _function_body(src: str, name: str) -> str:
    marker = f"function {name}"
    start = src.find(marker)
    assert start >= 0, f"{name} not found"
    brace = src.find("{", start)
    assert brace >= 0, f"{name} body not found"
    depth = 0
    for idx in range(brace, len(src)):
        ch = src[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[start : idx + 1]
    raise AssertionError(f"{name} body did not close")


def test_streaming_follow_helper_is_guarded_and_exported():
    helper = _function_body(UI_JS, "followStreamingOutputIfPinned")

    assert "window.followStreamingOutputIfPinned=followStreamingOutputIfPinned" in UI_JS
    assert "_autoScrollFollow" in helper
    assert "_messageUserUnpinned" in helper
    assert "_recentNonMessageScrollIntent()" in helper
    assert "_recentMessageScrollIntent()" in helper
    assert "_recentMessageTouchScrollIntent()" in helper
    assert "_recentMessageWheelIntent()" in helper
    assert "_recentMessageKeyScrollIntent()" in helper
    assert "_setMessageScrollToBottom()" in helper
    assert "_settleMessageScrollToBottom(false)" in helper
    assert "scrollToBottom()" not in helper, (
        "streaming follow must not call explicit scrollToBottom(), because that "
        "clears the sticky manual-unpin state"
    )


def test_live_text_render_uses_streaming_follow_helper_with_scroll_if_pinned_fallback():
    render_section = MESSAGES_JS.split("const _doRender=()=>{", 1)[1].split("_throttledSnapshotLiveTurn();", 1)[0]
    assert "followStreamingOutputIfPinned" in render_section
    assert "else scrollIfPinned();" in render_section
    assert render_section.rfind("followStreamingOutputIfPinned") > render_section.rfind(
        "_upsertAnchorProcessProse(anchorProcessText)"
    )

    drain = _function_body(MESSAGES_JS, "_drainStreamFadeBeforeDone")
    assert "followStreamingOutputIfPinned" in drain
    assert "else scrollIfPinned();" in drain


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_streaming_follow_recovers_false_unpinned_scrollpin_without_user_intent():
    result = _run_helper_scenario(
        {
            "auto": True,
            "unpinned": False,
            "pinned": False,
            "intent": False,
            "scrollTop": 900,
            "scrollHeight": 5000,
            "clientHeight": 600,
        }
    )

    assert result["returned"] is True
    assert result["setCalls"] == 1
    assert result["settleCalls"] == 1
    assert result["scrollPinned"] is True
    assert result["nearBottomCount"] == 2


@pytest.mark.skipif(NODE is None, reason="node not available")
def test_streaming_follow_respects_manual_unpin_and_recent_intent():
    manual = _run_helper_scenario(
        {
            "auto": True,
            "unpinned": True,
            "pinned": False,
            "intent": False,
            "scrollTop": 900,
            "scrollHeight": 5000,
            "clientHeight": 600,
        }
    )
    assert manual["returned"] is False
    assert manual["setCalls"] == 0
    assert manual["scrollPinned"] is False
    assert manual["messageUserUnpinned"] is True

    intent = _run_helper_scenario(
        {
            "auto": True,
            "unpinned": False,
            "pinned": False,
            "intent": True,
            "scrollTop": 900,
            "scrollHeight": 5000,
            "clientHeight": 600,
        }
    )
    assert intent["returned"] is False
    assert intent["setCalls"] == 0
    assert intent["scrollPinned"] is False


def _run_helper_scenario(state: dict) -> dict:
    helper = _function_body(UI_JS, "followStreamingOutputIfPinned")
    script = textwrap.dedent(
        f"""
        let _autoScrollFollow={str(state["auto"]).lower()};
        let _messageUserUnpinned={str(state["unpinned"]).lower()};
        let _scrollPinned={str(state["pinned"]).lower()};
        let _nearBottomCount=0;
        let setCalls=0;
        let settleCalls=0;
        const el={{
          scrollTop:{state["scrollTop"]},
          scrollHeight:{state["scrollHeight"]},
          clientHeight:{state["clientHeight"]},
        }};
        function $(id){{ return id==='messages' ? el : null; }}
        function _recentNonMessageScrollIntent(){{ return {str(state["intent"]).lower()}; }}
        function _recentMessageScrollIntent(){{ return {str(state["intent"]).lower()}; }}
        function _recentMessageTouchScrollIntent(){{ return {str(state["intent"]).lower()}; }}
        function _recentMessageWheelIntent(){{ return {str(state["intent"]).lower()}; }}
        function _recentMessageKeyScrollIntent(){{ return {str(state["intent"]).lower()}; }}
        function _messageBottomDistance(){{ return el.scrollHeight-el.scrollTop-el.clientHeight; }}
        function _setMessageScrollToBottom(){{ setCalls+=1; el.scrollTop=el.scrollHeight; }}
        function _settleMessageScrollToBottom(force){{ settleCalls+=1; _setMessageScrollToBottom(); }}
        function _syncScrollToBottomCue(){{}}
        function _updateSessionStartJumpButton(){{}}
        {helper}
        const returned=followStreamingOutputIfPinned();
        console.log(JSON.stringify({{
          returned,
          setCalls,
          settleCalls,
          scrollPinned:_scrollPinned,
          messageUserUnpinned:_messageUserUnpinned,
          nearBottomCount:_nearBottomCount,
          scrollTop:el.scrollTop,
        }}));
        """
    )
    proc = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout.strip())
