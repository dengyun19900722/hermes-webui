"""Offline deployment guardrails for optional Prism assets."""


def test_index_does_not_load_prism_from_public_cdn():
    src = open("static/index.html", encoding="utf-8").read()
    assert "prism-theme" not in src
    assert "prismjs@1.29.0" not in src
    assert "cdn.jsdelivr.net" not in src


def test_boot_js_does_not_reintroduce_prism_cdn_on_theme_switch():
    src = open("static/boot.js", encoding="utf-8").read()
    assert "_setResolvedTheme" in src
    assert "prism-theme" not in src
    assert "cdn.jsdelivr.net" not in src
    assert "function _syncThemeColorMeta()" in src
    assert "function _setResolvedTheme(isDark)" in src
    assert "_syncThemeColorMeta();" in src
