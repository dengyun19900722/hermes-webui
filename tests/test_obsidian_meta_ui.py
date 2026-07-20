"""Verify knowledge base meta UI elements (creator + ratings) exist."""
from pathlib import Path


def test_notes_meta_js_exists():
    assert Path("static/notes_meta.js").exists()


def test_notes_meta_js_has_rating_helper():
    src = Path("static/notes_meta.js").read_text(encoding="utf-8")
    assert "rating" in src.lower()


def test_notes_meta_js_has_creator_rendering():
    src = Path("static/notes_meta.js").read_text(encoding="utf-8")
    assert "creator" in src.lower() or "creator_name" in src


def test_notes_meta_js_uses_meta_endpoint():
    """应通过 /api/notes/meta/{path}/rate 等端点提交评分。"""
    src = Path("static/notes_meta.js").read_text(encoding="utf-8")
    # 不强制要求完整路径，但应该使用 api/notes 路径
    assert "/api/notes" in src or "api/notes" in src


def test_notes_meta_js_has_escape_html_helper():
    src = Path("static/notes_meta.js").read_text(encoding="utf-8")
    # XSS 防护
    assert "escapeHtml" in src or "textContent" in src