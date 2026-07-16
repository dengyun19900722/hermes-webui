"""Static-check tests for Task 11: Composer quick-add mini modal.

There is no JS test runner in the project, so these tests parse `static/ui.js`
as text and verify the new functions exist and reference the right symbols.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
UI_JS = REPO / "static" / "ui.js"
I18N_JS = REPO / "static" / "i18n.js"


def _load_ui_js() -> str:
    return UI_JS.read_text(encoding="utf-8")


def _extract_function(src: str, name: str) -> str | None:
    pattern = re.compile(rf"(?:async\s+)?function\s+{re.escape(name)}\s*\([^)]*\)\s*\{{", re.MULTILINE)
    m = pattern.search(src)
    if not m:
        return None
    start = m.end()
    depth = 1
    i = start
    while i < len(src) and depth > 0:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1
    return src[start : i - 1]


# ---------------------------------------------------------------------------
# 1. Quick-add entry injection
# ---------------------------------------------------------------------------

def test_composer_quickadd_class_present():
    src = _load_ui_js()
    assert "composer-quickadd" in src, \
        "Composer quick-add class 'composer-quickadd' must exist"


def test_composer_quickadd_uses_i18n_label():
    src = _load_ui_js()
    assert "t('custom_provider_composer_quickadd_label')" in src, \
        "Must reference t('custom_provider_composer_quickadd_label') for the ➕ entry"


def test_render_model_dropdown_calls_quickadd_injection():
    """renderModelDropdown should inject the quick-add entry only for composer."""
    src = _load_ui_js()
    body = _extract_function(src, "renderModelDropdown") or ""
    assert "_injectComposerQuickAdd" in body or "composer-quickadd" in body, \
        "renderModelDropdown must inject the composer quick-add entry"
    # The injection must be conditional (gated) — must reference dropdownId or composerModelDropdown
    assert "dropdownId" in body or "composerModelDropdown" in body, \
        "Quick-add injection must be gated (e.g., check opts.dropdownId) so it only fires for composer"


# ---------------------------------------------------------------------------
# 2. Mini modal functions
# ---------------------------------------------------------------------------

def test_open_composer_quickadd_modal_defined():
    src = _load_ui_js()
    assert "function _openComposerQuickAddModal" in src


def test_open_composer_quickadd_modal_mounts_to_body():
    src = _load_ui_js()
    body = _extract_function(src, "_openComposerQuickAddModal") or ""
    assert "document.body.appendChild" in body
    assert "_composerQuickAddModal" in body, \
        "Must assign overlay to _composerQuickAddModal state variable"


def test_open_composer_quickadd_modal_uses_i18n_title_and_subtitle():
    src = _load_ui_js()
    body = _extract_function(src, "_openComposerQuickAddModal") or ""
    assert "t('custom_provider_quickadd_title')" in body
    assert "t('custom_provider_quickadd_subtitle')" in body


def test_open_composer_quickadd_modal_uses_field_i18n_keys():
    src = _load_ui_js()
    body = _extract_function(src, "_openComposerQuickAddModal") or ""
    for key in ("custom_provider_field_name", "custom_provider_field_base_url", "custom_provider_field_api_key"):
        assert f"t('{key}')" in body, f"mini modal must reference t('{key}')"


def test_open_composer_quickadd_modal_no_hacky_replace():
    """Plan bug: must NOT use .replace('直接保存', '取消') hack."""
    src = _load_ui_js()
    body = _extract_function(src, "_openComposerQuickAddModal") or ""
    assert ".replace(" not in body, \
        "Mini modal must not use .replace() hack for button labels"
    # Cancel button uses the i18n `cancel` key (added to i18n.js line 1382)
    assert "t('cancel')" in body, \
        "Mini modal must reference t('cancel') for cancel button"


def test_close_composer_quickadd_defined():
    src = _load_ui_js()
    assert "function _closeComposerQuickAdd" in src


def test_close_composer_quickadd_removes_overlay():
    src = _load_ui_js()
    body = _extract_function(src, "_closeComposerQuickAdd") or ""
    assert ".remove()" in body or "removeChild" in body


def test_submit_composer_quickadd_defined():
    src = _load_ui_js()
    assert "async function _submitComposerQuickAdd" in src


def test_submit_composer_quickadd_posts_upsert():
    src = _load_ui_js()
    body = _extract_function(src, "_submitComposerQuickAdd") or ""
    assert "/api/custom_providers" in body
    # Accept either spaced or compact JSON form
    has_upsert = bool(re.search(r"action\s*:\s*['\"]upsert['\"]", body))
    assert has_upsert, "Must POST with action='upsert'"


def test_submit_composer_quickadd_probes_models():
    src = _load_ui_js()
    body = _extract_function(src, "_submitComposerQuickAdd") or ""
    assert "/api/custom_providers/probe_models" in body, \
        "Must probe models first to populate the models list"


def test_submit_composer_quickadd_derives_name_from_baseurl():
    src = _load_ui_js()
    body = _extract_function(src, "_submitComposerQuickAdd") or ""
    assert "new URL(baseUrl)" in body or "URL(baseUrl)" in body, \
        "Must derive name from baseUrl host when name is empty"


def test_submit_composer_quickadd_auto_selects_model():
    src = _load_ui_js()
    body = _extract_function(src, "_submitComposerQuickAdd") or ""
    # Either calls selectModelFromDropdown (existing global) or has a clear comment about selection
    has_select = "selectModelFromDropdown" in body or "_applyModelToDropdown" in body
    has_toast = "custom_provider_quickadd_added_toast" in body
    assert has_select or has_toast, \
        "Must either auto-select the new model OR show a toast (we do both)"


def test_show_qa_banner_defined():
    src = _load_ui_js()
    assert "function _showQaBanner" in src


# ---------------------------------------------------------------------------
# 3. i18n keys referenced actually exist
# ---------------------------------------------------------------------------

def test_referenced_i18n_keys_exist():
    src = _load_ui_js()
    i18n = I18N_JS.read_text(encoding="utf-8")
    required = [
        "cancel",
        "add",
        "custom_provider_composer_quickadd_label",
        "custom_provider_quickadd_title",
        "custom_provider_quickadd_subtitle",
        "custom_provider_quickadd_added_toast",
        "custom_provider_field_name",
        "custom_provider_field_base_url",
        "custom_provider_field_api_key",
        "custom_provider_save_failed",
    ]
    missing = []
    for key in required:
        if not re.search(rf"^\s*{re.escape(key)}\s*:", i18n, re.MULTILINE):
            missing.append(key)
    assert not missing, f"Missing i18n keys: {missing}"


# ---------------------------------------------------------------------------
# 4. ESC + overlay-click close behavior
# ---------------------------------------------------------------------------

def test_open_composer_quickadd_modal_closes_on_escape():
    src = _load_ui_js()
    body = _extract_function(src, "_openComposerQuickAddModal") or ""
    assert "Escape" in body, "Mini modal must close on Escape key"


def test_open_composer_quickadd_modal_closes_on_overlay_click():
    src = _load_ui_js()
    body = _extract_function(src, "_openComposerQuickAddModal") or ""
    # Accept either spaced or compact form
    assert re.search(r"ev\.target\s*===\s*overlay", body), \
        "Mini modal must close when clicking outside the card"