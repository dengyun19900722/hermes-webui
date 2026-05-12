"""
Tests for app-titlebar logo, brand text, and version badge.

Covers:
  1. Logo SVG exists and has correct dimensions in index.html
  2. #appTitlebarBrand element exists and contains 'Hermes'
  3. panels.js: syncAppTitlebar() prepends 'Hermes · ' to session titles
  4. panels.js: brand element is shown on non-chat panels, hidden on chat with session
  5. Version badge (#versionBadge) has onclick="showChangelogDialog()"
  6. showChangelogDialog() function is defined in ui.js
  7. Changelog dialog (#changelogDialog) exists and is closeable
  8. style.css: .app-titlebar-brand styles are defined
"""
from pathlib import Path

REPO = Path(__file__).parent.parent
INDEX_HTML = (REPO / "static" / "index.html").read_text(encoding="utf-8")
PANELS_JS = (REPO / "static" / "panels.js").read_text(encoding="utf-8")
UI_JS     = (REPO / "static" / "ui.js").read_text(encoding="utf-8")
STYLE_CSS = (REPO / "static" / "style.css").read_text(encoding="utf-8")


# ── 1. Logo SVG ─────────────────────────────────────────────────────────────────

def test_logo_svg_exists_in_index_html():
    """Logo SVG must exist inside .app-titlebar-icon in index.html."""
    assert 'class="app-titlebar-icon"' in INDEX_HTML
    assert '<svg' in INDEX_HTML, "No SVG found in index.html"
    # The icon span should contain an SVG with viewBox="0 0 64 64"
    assert 'viewBox="0 0 64 64"' in INDEX_HTML, (
        "Logo SVG must use the caduceus-style viewBox"
    )

def test_logo_svg_has_minimum_dimensions():
    """Logo SVG width/height must be at least 16px for visibility."""
    import re
    # Find width="NN" or height="NN" on the app-titlebar SVG
    matches = re.findall(r'app-titlebar-icon.*?width="(\d+)"', INDEX_HTML, re.DOTALL)
    assert matches, "No width= found on the app-titlebar-icon SVG"
    width = int(matches[0])
    assert width >= 16, f"Logo SVG width={width} is too small (minimum 16px)"


# ── 2. Brand element ─────────────────────────────────────────────────────────────

def test_brand_element_exists():
    """#appTitlebarBrand element must exist in the DOM."""
    assert 'id="appTitlebarBrand"' in INDEX_HTML, (
        "#appTitlebarBrand element is missing from index.html"
    )

def test_brand_text_is_hermes():
    """Brand element must contain the text 'Hermes'."""
    import re
    m = re.search(r'id="appTitlebarBrand"[^>]*>([^<]+)<', INDEX_HTML)
    assert m, "Could not find text content of #appTitlebarBrand"
    assert 'Hermes' in m.group(1), f"Brand element text should be 'Hermes', got: {m.group(1)!r}"


# ── 3. syncAppTitlebar — Hermes ·  prefix ──────────────────────────────────────

def test_sync_app_titlebar_prepends_hermes_prefix():
    """panels.js syncAppTitlebar() must prepend 'Hermes · ' to session titles."""
    assert "'Hermes · '" in PANELS_JS or '"Hermes · "' in PANELS_JS, (
        "syncAppTitlebar() must prepend 'Hermes · ' to session title"
    )
    # The raw title assignment must use the Hermes prefix
    assert "mainText = 'Hermes · '" in PANELS_JS or 'mainText = "Hermes · "' in PANELS_JS, (
        "panels.js must set mainText to 'Hermes · ' + rawTitle for chat sessions"
    )

def test_sync_app_titlebar_shows_brand_on_non_chat_panels():
    """On non-chat panels, brand element must be shown (not hidden)."""
    # showBrand = true for non-chat panels
    assert "showBrand = true" in PANELS_JS, (
        "syncAppTitlebar() must set showBrand=true for non-chat panels"
    )
    # showBrand = false when Hermes is embedded in mainText (chat with session)
    assert "showBrand = false" in PANELS_JS, (
        "syncAppTitlebar() must set showBrand=false when Hermes is in title prefix"
    )

def test_sync_app_titlebar_manages_brand_hidden():
    """panels.js must toggle brandEl.hidden based on showBrand."""
    # Must reference brandEl
    assert "brandEl" in PANELS_JS, (
        "syncAppTitlebar() must getElementById('appTitlebarBrand')"
    )
    # Must set hidden property
    assert "brandEl.hidden" in PANELS_JS or "hidden = " in PANELS_JS, (
        "syncAppTitlebar() must set brandEl.hidden to toggle brand visibility"
    )


# ── 4. Version badge ─────────────────────────────────────────────────────────────

def test_version_badge_exists_in_index_html():
    """#versionBadge element must exist in index.html."""
    assert 'id="versionBadge"' in INDEX_HTML, (
        "#versionBadge element is missing from index.html"
    )

def test_version_badge_has_changelog_onclick():
    """Version badge onclick must call showChangelogDialog()."""
    import re
    m = re.search(r'id="versionBadge"[^>]*onclick="([^"]+)"', INDEX_HTML)
    assert m, "Could not find onclick attribute on #versionBadge"
    assert 'showChangelogDialog()' in m.group(1), (
        f"versionBadge onclick should be 'showChangelogDialog()', got: {m.group(1)!r}"
    )

def test_show_changelog_dialog_function_defined():
    """showChangelogDialog() must be defined in ui.js."""
    assert 'function showChangelogDialog()' in UI_JS, (
        "showChangelogDialog() function is missing from ui.js"
    )

def test_show_changelog_dialog_sets_display_flex():
    """showChangelogDialog() must set the dialog display to 'flex'."""
    # The dialog overlay must be shown
    assert "style.display = 'flex'" in UI_JS or 'style.display = "flex"' in UI_JS, (
        "showChangelogDialog() must set style.display = 'flex' on the dialog overlay"
    )
    assert "aria-hidden" in UI_JS and 'false' in UI_JS, (
        "showChangelogDialog() must set aria-hidden='false' when opening"
    )

def test_close_changelog_dialog_function_defined():
    """closeChangelogDialog() must be defined in ui.js."""
    assert 'function closeChangelogDialog()' in UI_JS, (
        "closeChangelogDialog() function is missing from ui.js"
    )

def test_changelog_dialog_exists_in_index_html():
    """#changelogDialog element must exist in index.html."""
    assert 'id="changelogDialog"' in INDEX_HTML, (
        "#changelogDialog element is missing from index.html"
    )

def test_changelog_dialog_title_exists():
    """#changelogDialogTitle element must exist inside the dialog."""
    assert 'id="changelogDialogTitle"' in INDEX_HTML, (
        "#changelogDialogTitle element is missing from index.html"
    )


# ── 5. CSS styles ────────────────────────────────────────────────────────────────

def test_app_titlebar_brand_css_defined():
    """.app-titlebar-brand CSS class must be defined in style.css."""
    assert '.app-titlebar-brand' in STYLE_CSS, (
        ".app-titlebar-brand CSS class is missing from style.css"
    )

def test_app_titlebar_brand_hidden_css_defined():
    """.app-titlebar-brand[hidden] CSS rule must be defined."""
    assert '.app-titlebar-brand[hidden]' in STYLE_CSS, (
        ".app-titlebar-brand[hidden] CSS rule is missing (needed to hide brand)"
    )

def test_app_titlebar_is_centered_desktop():
    """.app-titlebar must be centered on desktop (justify-content:center)."""
    assert ".app-titlebar{display:flex;align-items:center;justify-content:center;" in STYLE_CSS, (
        ".app-titlebar must be centered with justify-content:center on desktop"
    )

def test_version_badge_css_exists():
    """.version-badge CSS must be defined."""
    assert '.version-badge' in STYLE_CSS, (
        ".version-badge CSS class is missing from style.css"
    )


# ── 6. i18n keys for panel tabs ─────────────────────────────────────────────────

def test_panel_tab_keys_exist_in_i18n():
    """APP_TITLEBAR_KEYS in panels.js must reference i18n keys for all panels."""
    import re
    m = re.search(r'const APP_TITLEBAR_KEYS\s*=\s*\{([^}]+)\}', PANELS_JS, re.DOTALL)
    assert m, "APP_TITLEBAR_KEYS not found in panels.js"
    keys_text = m.group(1)
    required = ['chat', 'tasks', 'skills', 'logs', 'insights', 'settings']
    for panel in required:
        assert panel in keys_text, f"Panel '{panel}' missing from APP_TITLEBAR_KEYS"
