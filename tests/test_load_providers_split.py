"""Task 8: verify loadProvidersPanel is split into Custom (top) + Built-in (below).

We have no JS test runner, so this is a static structural check of
static/panels.js: it asserts the new helper functions exist, that
loadProvidersPanel wires them up in the right order, that the built-in list
excludes is_custom providers, and that the new section class names are present.

Run with: pytest --noconftest tests/test_load_providers_split.py -v
"""

import os
import re

from tests.js_source_extract import extract_function

PANELS = os.path.join(os.path.dirname(__file__), "..", "static", "panels.js")


def _read():
    with open(PANELS, encoding="utf-8") as f:
        return f.read()


def test_render_custom_providers_section_defined():
    js = _read()
    assert "function _renderCustomProvidersSection(" in js


def test_render_builtin_providers_section_defined():
    js = _read()
    assert "function _renderBuiltInProvidersSection(" in js


def test_load_custom_providers_defined():
    js = _read()
    assert "function _loadCustomProviders(" in js


def test_load_providers_panel_calls_new_renderers():
    body = extract_function(_read(), "loadProvidersPanel", prefix="async function")
    assert "_loadCustomProviders(" in body
    assert "_renderCustomProvidersSection(" in body
    assert "_renderBuiltInProvidersSection(" in body


def test_load_providers_panel_ordering():
    body = extract_function(_read(), "loadProvidersPanel", prefix="async function")
    load_pos = body.find("_loadCustomProviders(")
    custom_pos = body.find("_renderCustomProvidersSection(")
    builtin_pos = body.find("_renderBuiltInProvidersSection(")
    assert load_pos >= 0 and custom_pos >= 0 and builtin_pos >= 0
    assert load_pos < custom_pos < builtin_pos, (
        f"expected order load({load_pos}) < custom({custom_pos}) < builtin({builtin_pos})"
    )


def test_builtin_list_excludes_custom():
    body = extract_function(_read(), "loadProvidersPanel", prefix="async function")
    assert re.search(r"filter\(\s*p\s*=>\s*!p\.is_custom", body), (
        "built-in provider filter must exclude is_custom"
    )


def test_new_section_class_names_present():
    js = _read()
    assert "custom-providers-section" in js
    assert "builtin-providers-section" in js


def test_builtin_cards_still_use_build_provider_card():
    body = extract_function(_read(), "loadProvidersPanel", prefix="async function")
    assert "_buildProviderCard(p)" in body


def test_builtin_section_uses_details_element():
    """Plan §2.2: Built-in section should be wrapped in a <details> element
    so it collapses by default. Verify the helper creates a <details> tag."""
    body = extract_function(_read(), "_renderBuiltInProvidersSection", prefix="function")
    assert "details" in body, "Built-in section helper must use a <details> element"
    # Also verify .open=false (collapsed by default)
    assert ".open = false" in body or "open=false" in body, (
        "Built-in <details> should default to collapsed"
    )
