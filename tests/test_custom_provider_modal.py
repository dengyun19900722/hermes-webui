"""Static-check tests for Task 10: Add/Edit custom provider modal + action handlers.

There is no JS test runner in the project, so these tests parse `static/panels.js`
as text and verify the new functions exist and reference the right symbols.

Each test corresponds to one or more requirements in the implementation plan
(`docs/superpowers/plans/2026-07-15-custom-model-config-implementation.md`
lines 1294-1574).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PANELS_JS = REPO / "static" / "panels.js"
I18N_JS = REPO / "static" / "i18n.js"


def _load_panels_js() -> str:
    return PANELS_JS.read_text(encoding="utf-8")


def _extract_function(src: str, name: str) -> str | None:
    """Extract the body of a top-level function declaration `name(...)`."""
    pattern = re.compile(rf"function\s+{re.escape(name)}\s*\([^)]*\)\s*\{{", re.MULTILINE)
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
# 1. _openCustomProviderModal — main entry point
# ---------------------------------------------------------------------------

def test_open_custom_provider_modal_defined():
    src = _load_panels_js()
    assert "function _openCustomProviderModal" in src, \
        "_openCustomProviderModal must be defined in static/panels.js"


def test_open_custom_provider_modal_mounts_to_body():
    src = _load_panels_js()
    body = _extract_function(src, "_openCustomProviderModal") or ""
    assert "document.body.appendChild" in body, \
        "_openCustomProviderModal must append overlay to document.body"
    assert "_customProviderModal" in body, \
        "_openCustomProviderModal must assign the overlay to _customProviderModal"


def test_open_custom_provider_modal_uses_i18n_cancel_not_hack():
    """Plan bug #2: must NOT use .replace('直接保存', '取消') hack."""
    src = _load_panels_js()
    body = _extract_function(src, "_openCustomProviderModal") or ""
    assert ".replace(" not in body, \
        "_openCustomProviderModal must not use .replace() hack for cancel button label"
    # Cancel button must use the i18n `cancel` key (added to i18n.js line 1260)
    assert "t('cancel')" in body, \
        "_openCustomProviderModal must reference t('cancel') for cancel button"


def test_open_custom_provider_modal_uses_field_i18n_keys():
    src = _load_panels_js()
    body = _extract_function(src, "_openCustomProviderModal") or ""
    for key in (
        "custom_provider_field_name",
        "custom_provider_field_slug",
        "custom_provider_field_base_url",
        "custom_provider_field_api_key",
        "custom_provider_field_models",
    ):
        assert f"t('{key}')" in body, f"_openCustomProviderModal must reference t('{key}')"


def test_open_custom_provider_modal_uses_btn_i18n_keys():
    src = _load_panels_js()
    body = _extract_function(src, "_openCustomProviderModal") or ""
    for key in (
        "custom_provider_btn_save_direct",
        "custom_provider_btn_probe_save",
    ):
        assert f"t('{key}')" in body, f"_openCustomProviderModal must reference t('{key}')"


def test_open_custom_provider_modal_wires_live_probe():
    """base_url input must trigger a debounced re-probe via _autoProbeModels."""
    src = _load_panels_js()
    body = _extract_function(src, "_openCustomProviderModal") or ""
    assert "setTimeout" in body, "_openCustomProviderModal must debounce probe"
    assert "_autoProbeModels" in body, \
        "_openCustomProviderModal must call _autoProbeModels on base_url input"


# ---------------------------------------------------------------------------
# 2. _closeCustomProviderModal
# ---------------------------------------------------------------------------

def test_close_custom_provider_modal_defined():
    src = _load_panels_js()
    assert "function _closeCustomProviderModal" in src


def test_close_custom_provider_modal_removes_overlay():
    src = _load_panels_js()
    body = _extract_function(src, "_closeCustomProviderModal") or ""
    assert ".remove()" in body or "removeChild" in body, \
        "_closeCustomProviderModal must remove the overlay from DOM"


# ---------------------------------------------------------------------------
# 3. _addModelChip + _addModelAddButton
# ---------------------------------------------------------------------------

def test_add_model_chip_defined():
    src = _load_panels_js()
    assert "function _addModelChip" in src


def test_add_model_chip_creates_input_and_remove_button():
    src = _load_panels_js()
    body = _extract_function(src, "_addModelChip") or ""
    assert "<input" in body, "_addModelChip must create an input"
    assert "data-remove" in body, "_addModelChip must create a remove button"


def test_add_model_add_button_defined():
    src = _load_panels_js()
    assert "function _addModelAddButton" in src


def test_add_model_add_button_uses_btn_i18n_keys():
    src = _load_panels_js()
    body = _extract_function(src, "_addModelAddButton") or ""
    for key in ("custom_provider_btn_add_model", "custom_provider_btn_fetch_models"):
        assert f"t('{key}')" in body, f"_addModelAddButton must reference t('{key}')"


# ---------------------------------------------------------------------------
# 4. _autoProbeModels
# ---------------------------------------------------------------------------

def test_auto_probe_models_defined():
    src = _load_panels_js()
    assert "async function _autoProbeModels" in src


def test_auto_probe_models_posts_to_probe_endpoint():
    src = _load_panels_js()
    body = _extract_function(src, "_autoProbeModels") or ""
    assert "/api/custom_providers/probe_models" in body, \
        "_autoProbeModels must POST to /api/custom_providers/probe_models"
    assert "method: 'POST'" in body or 'method:"POST"' in body, \
        "_autoProbeModels must use POST"


def test_auto_probe_models_populates_chips_on_success():
    """Regression: probe results must populate the chip list so the submit
    payload isn't empty. Previously the probe cached models but never added
    them as chips, so users who didn't manually type model ids hit a 400
    "models_empty" on save even though the banner said "Found N models"."""
    src = _load_panels_js()
    body = _extract_function(src, "_autoProbeModels") or ""
    assert "_addModelChip" in body, \
        "_autoProbeModels must call _addModelChip to populate the chip list"
    assert "probedModelsCache" in body, \
        "_autoProbeModels must keep probedModelsCache in sync with chips"
    assert "probedKey" in body, \
        "_autoProbeModels must record probedKey so submit can validate the cache"


# ---------------------------------------------------------------------------
# 5. _submitCustomProvider
# ---------------------------------------------------------------------------

def test_submit_custom_provider_defined():
    src = _load_panels_js()
    assert "async function _submitCustomProvider" in src


def test_submit_custom_provider_posts_upsert():
    src = _load_panels_js()
    body = _extract_function(src, "_submitCustomProvider") or ""
    assert "/api/custom_providers" in body
    assert "action: 'upsert'" in body or 'action:"upsert"' in body, \
        "_submitCustomProvider must POST with action='upsert'"
    assert "provider" in body, \
        "_submitCustomProvider must send the provider body"


def test_submit_custom_provider_handles_partial_failure():
    src = _load_panels_js()
    body = _extract_function(src, "_submitCustomProvider") or ""
    assert "failed_profiles" in body or "succeeded_count" in body, \
        "_submitCustomProvider must handle partial-failure response"


def test_submit_custom_provider_falls_back_to_probed_cache():
    """Regression: if user clicks 保存 without manually typing any model ids,
    submit must fall back to the probed cache (when key still matches) so we
    don't 400 with "models_empty" right after a successful "Found N models"
    probe. Key check prevents using a stale cache from a previous base_url."""
    src = _load_panels_js()
    body = _extract_function(src, "_submitCustomProvider") or ""
    assert "probedModelsCache" in body, \
        "_submitCustomProvider must consult probedModelsCache as a fallback"
    assert "probedKey" in body, \
        "_submitCustomProvider must validate probedKey matches the current " \
        "base_url+api_key before using the cache"


# ---------------------------------------------------------------------------
# 6. _showModalError
# ---------------------------------------------------------------------------

def test_show_modal_error_defined():
    src = _load_panels_js()
    assert "function _showModalError" in src


# ---------------------------------------------------------------------------
# 7. Action handlers: probe / delete / set-default
# ---------------------------------------------------------------------------

def test_probe_custom_provider_defined():
    src = _load_panels_js()
    assert "async function _probeCustomProvider" in src


def test_probe_custom_provider_posts_to_probe_endpoint():
    src = _load_panels_js()
    body = _extract_function(src, "_probeCustomProvider") or ""
    assert "/api/custom_providers/probe_models" in body


def test_delete_custom_provider_defined():
    src = _load_panels_js()
    assert "async function _deleteCustomProvider" in src


def test_delete_custom_provider_uses_confirm_dialog():
    """Plan bug #4: must use showConfirmDialog, NOT bare native confirm() as primary."""
    src = _load_panels_js()
    body = _extract_function(src, "_deleteCustomProvider") or ""
    assert "showConfirmDialog" in body, \
        "_deleteCustomProvider must use showConfirmDialog (not native confirm)"
    # `confirm(` may appear only inside an `else` fallback branch — primary path must be showConfirmDialog
    confirm_calls = re.findall(r"\bconfirm\s*\(", body)
    show_calls = body.count("showConfirmDialog")
    assert show_calls >= 1, "_deleteCustomProvider must call showConfirmDialog"
    assert len(confirm_calls) <= 1, \
        f"_deleteCustomProvider should not call native confirm() more than once (fallback). Got {len(confirm_calls)}."


def test_delete_custom_provider_uses_i18n_confirm_key():
    src = _load_panels_js()
    body = _extract_function(src, "_deleteCustomProvider") or ""
    assert "t('custom_provider_delete_confirm')" in body, \
        "_deleteCustomProvider must reference t('custom_provider_delete_confirm')"


def test_delete_custom_provider_posts_action_delete():
    src = _load_panels_js()
    body = _extract_function(src, "_deleteCustomProvider") or ""
    assert "action: 'delete'" in body or 'action:"delete"' in body
    assert "/api/custom_providers" in body


def test_set_default_custom_provider_defined():
    src = _load_panels_js()
    assert "async function _setDefaultCustomProvider" in src


def test_set_default_custom_provider_posts_to_set_default():
    src = _load_panels_js()
    body = _extract_function(src, "_setDefaultCustomProvider") or ""
    assert "/api/custom_providers/set_default" in body, \
        "_setDefaultCustomProvider must POST to /api/custom_providers/set_default"


def test_set_default_custom_provider_uses_models_empty_i18n():
    src = _load_panels_js()
    body = _extract_function(src, "_setDefaultCustomProvider") or ""
    assert "t('custom_provider_models_empty')" in body, \
        "_setDefaultCustomProvider must reference t('custom_provider_models_empty')"


# ---------------------------------------------------------------------------
# 8. i18n keys referenced actually exist
# ---------------------------------------------------------------------------

def test_referenced_i18n_keys_exist():
    """Grep panels.js for `t('xxx')` calls and verify each key exists in i18n.js."""
    src = _load_panels_js()
    i18n = I18N_JS.read_text(encoding="utf-8")

    # Required keys used by Task 10
    required = [
        "cancel",
        "custom_provider_field_name",
        "custom_provider_field_slug",
        "custom_provider_field_base_url",
        "custom_provider_field_api_key",
        "custom_provider_field_models",
        "custom_provider_field_api_key_hint",
        "custom_provider_btn_save_direct",
        "custom_provider_btn_probe_save",
        "custom_provider_btn_add_model",
        "custom_provider_btn_fetch_models",
        "custom_provider_save_partial",
        "custom_provider_save_failed",
        "custom_provider_models_empty",
        "custom_provider_delete_confirm",
    ]
    missing = []
    for key in required:
        # key may appear as `key: '...'` or `key: (...) => ...` in i18n.js
        if not re.search(rf"^\s*{re.escape(key)}\s*:", i18n, re.MULTILINE):
            missing.append(key)
    assert not missing, f"Missing i18n keys: {missing}"


# ---------------------------------------------------------------------------
# 9. Regression — Task 8 + Task 9 tests still pass (caller verifies via pytest)
# ---------------------------------------------------------------------------

def test_no_orphan_placeholder_card():
    """Task 9 removed _renderPlaceholderCard; verify it's gone."""
    src = _load_panels_js()
    assert "_renderPlaceholderCard" not in src, \
        "_renderPlaceholderCard was removed in Task 9 and must not return"


def test_build_custom_provider_card_unconditional():
    """Task 9 made the card call unconditional."""
    src = _load_panels_js()
    # The `typeof _buildCustomProviderCard === 'function'` ternary must be gone
    assert "typeof _buildCustomProviderCard === 'function'" not in src, \
        "_renderCustomProvidersSection should call _buildCustomProviderCard unconditionally now"