"""Task 9: verify _buildCustomProviderCard renders a Custom provider card.

We have no JS test runner, so this is a static structural check of
static/panels.js. It asserts that the function exists, that it uses the
i18n keys added in Task 7 (no hardcoded UI strings), and that the click
dispatcher guards each action handler with a typeof check (the handlers
arrive in Tasks 10/11).

It also verifies that the Task 8 _renderPlaceholderCard shim has been
removed and that _renderCustomProvidersSection now calls
_buildCustomProviderCard unconditionally.

Run with: pytest --noconftest tests/test_custom_provider_card.py -v
"""

import os

from tests.js_source_extract import extract_function

PANELS = os.path.join(os.path.dirname(__file__), "..", "static", "panels.js")


def _read():
    with open(PANELS, encoding="utf-8") as f:
        return f.read()


def test_build_custom_provider_card_defined():
    js = _read()
    assert "function _buildCustomProviderCard(" in js, (
        "_buildCustomProviderCard must be defined in static/panels.js"
    )


def test_build_custom_provider_card_uses_i18n_probe_key():
    """The Probe action label must come from i18n, not a hardcoded string."""
    body = extract_function(_read(), "_buildCustomProviderCard", prefix="function")
    assert "t('custom_provider_card_probe')" in body, (
        "Probe action must use t('custom_provider_card_probe')"
    )
    assert ">Probe<" not in body, "Probe label must not be hardcoded"


def test_build_custom_provider_card_uses_i18n_edit_key():
    body = extract_function(_read(), "_buildCustomProviderCard", prefix="function")
    assert "t('custom_provider_card_edit')" in body, (
        "Edit action must use t('custom_provider_card_edit')"
    )


def test_build_custom_provider_card_uses_i18n_delete_key():
    body = extract_function(_read(), "_buildCustomProviderCard", prefix="function")
    assert "t('custom_provider_card_delete')" in body, (
        "Delete action must use t('custom_provider_card_delete')"
    )


def test_build_custom_provider_card_uses_i18n_set_default_key():
    body = extract_function(_read(), "_buildCustomProviderCard", prefix="function")
    assert "t('custom_provider_card_set_default')" in body, (
        "Set-default action must use t('custom_provider_card_set_default')"
    )


def test_build_custom_provider_card_no_hardcoded_chinese():
    """The plan's snippet had hardcoded '已配置'/'未配置' — must be i18n keys."""
    js = _read()
    assert "已配置" not in js, "Hardcoded '已配置' should not appear in panels.js"
    assert "未配置" not in js, "Hardcoded '未配置' should not appear in panels.js"


def test_build_custom_provider_card_uses_i18n_for_key_status():
    """The key-configured / not-configured status should use i18n keys."""
    body = extract_function(_read(), "_buildCustomProviderCard", prefix="function")
    # Either the new Task 7 keys (preferred) or the existing providers_status_* labels
    has_new_key = (
        "t('custom_provider_key_configured')" in body
        and "t('custom_provider_key_not_configured')" in body
    )
    has_existing_key = (
        "t('providers_status_configured')" in body
        and "t('providers_status_not_configured_label')" in body
    )
    assert has_new_key or has_existing_key, (
        "key status text must use i18n keys "
        "(custom_provider_key_configured/_not_configured or "
        "providers_status_configured/_not_configured_label)"
    )


def test_build_custom_provider_card_guards_action_handlers():
    """Each action handler is added in Tasks 10/11; guard with typeof checks."""
    body = extract_function(_read(), "_buildCustomProviderCard", prefix="function")
    assert "typeof _openCustomProviderModal === 'function'" in body, (
        "edit action must guard _openCustomProviderModal with typeof check"
    )
    assert "typeof _deleteCustomProvider === 'function'" in body, (
        "delete action must guard _deleteCustomProvider with typeof check"
    )
    assert "typeof _probeCustomProvider === 'function'" in body, (
        "probe action must guard _probeCustomProvider with typeof check"
    )
    assert "typeof _setDefaultCustomProvider === 'function'" in body, (
        "set-default action must guard _setDefaultCustomProvider with typeof check"
    )


def test_build_custom_provider_card_has_custom_provider_card_class():
    """Card uses 'custom-provider-card' so existing CSS keeps applying."""
    body = extract_function(_read(), "_buildCustomProviderCard", prefix="function")
    assert "'custom-provider-card'" in body or '"custom-provider-card"' in body, (
        "Card element must have className 'custom-provider-card'"
    )


def test_build_custom_provider_card_sets_data_slug():
    """Card carries a data-slug attribute so test/E2E hooks can find it."""
    body = extract_function(_read(), "_buildCustomProviderCard", prefix="function")
    assert "data-slug" in body or "setAttribute('data-slug'" in body, (
        "Card must expose data-slug attribute for hookability"
    )


def test_render_placeholder_card_removed():
    """Task 8's _renderPlaceholderCard shim should be gone now that the real
    card builder exists."""
    js = _read()
    assert "function _renderPlaceholderCard(" not in js, (
        "_renderPlaceholderCard should be removed in Task 9"
    )
    # And no leftover references in _renderCustomProvidersSection
    body = extract_function(_read(), "_renderCustomProvidersSection", prefix="function")
    assert "_renderPlaceholderCard" not in body, (
        "_renderCustomProvidersSection must not reference _renderPlaceholderCard"
    )


def test_render_custom_providers_section_calls_builder_unconditionally():
    """The typeof guard fallback is no longer needed — call is direct."""
    body = extract_function(_read(), "_renderCustomProvidersSection", prefix="function")
    assert "section.appendChild(_buildCustomProviderCard(p));" in body, (
        "_renderCustomProvidersSection must call _buildCustomProviderCard(p) "
        "unconditionally"
    )
    assert "typeof _buildCustomProviderCard === 'function'" not in body, (
        "typeof guard for _buildCustomProviderCard must be removed"
    )