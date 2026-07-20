"""Verify session sharing UI elements exist."""
from pathlib import Path


def test_session_sharing_js_exists():
    assert Path("static/session_sharing.js").exists()


def test_session_sharing_js_calls_list_sessions_endpoint():
    src = Path("static/session_sharing.js").read_text(encoding="utf-8")
    assert "/api/sessions" in src


def test_session_sharing_js_calls_share_endpoint():
    src = Path("static/session_sharing.js").read_text(encoding="utf-8")
    # 必须包含用户分享和 token 分享两个 endpoint
    assert "/share" in src
    assert "/share/token" in src


def test_session_sharing_js_renders_own_and_shared_sections():
    src = Path("static/session_sharing.js").read_text(encoding="utf-8")
    # 必须有两个独立的 section
    assert "own-sessions" in src or "own" in src.lower()
    assert "shared-sessions" in src or "shared" in src.lower()


def test_session_sharing_js_has_escape_html_helper():
    """防止 XSS — 用户/会话名插入 DOM 前必须转义。"""
    src = Path("static/session_sharing.js").read_text(encoding="utf-8")
    assert "escapeHtml" in src or "textContent" in src