"""Regression test for custom-provider form translations + help text.

Three things pinned here so the i18n + UX don't silently regress:

1. ``custom_provider_field_slug`` must NOT be the literal English word in the
   zh locale (the original complaint: "slug 是什么意思、翻译成中文").
2. All five form fields must have a corresponding ``*_help`` translation key
   in BOTH en and zh, so the modal can show a descriptive helper under each
   input.
3. The modal HTML in panels.js must render the help text under every field
   via ``<p class="form-row-help">…</p>``.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
I18N_JS = (ROOT / "static" / "i18n.js").read_text(encoding="utf-8")
PANELS_JS = (ROOT / "static" / "panels.js").read_text(encoding="utf-8")
STYLE_CSS = (ROOT / "static" / "style.css").read_text(encoding="utf-8")


def _extract_locale_block(src: str, locale: str) -> str:
    """Return the substring for ``locale: { … }`` (top-level locale block).

    Locale blocks in this file end with a ``},`` line at 2-space indent (the
    next locale starts at the same indent). We use that as the terminator
    instead of counting braces, because the values contain template-literal
    ``${...}`` placeholders and ``=> {...}`` arrow bodies whose braces would
    throw off a naive depth counter.
    """
    pat = re.compile(rf"^\s{{2}}{re.escape(locale)}:\s*\{{", re.MULTILINE)
    m = pat.search(src)
    if not m:
        raise AssertionError(f"locale block {locale!r} not found")
    start = m.end()
    # Find the next line that is exactly ``  },`` (closing brace + comma at
    # the same indent as the opening key).
    end_pat = re.compile(rf"^\s{{2}}\}},\s*$", re.MULTILINE)
    end_m = end_pat.search(src, start)
    if not end_m:
        raise AssertionError(f"could not find closing `}},` for locale {locale!r}")
    return src[start : end_m.start()]


def _has_key(block: str, key: str) -> bool:
    return re.search(rf"^\s+{re.escape(key)}\s*:", block, re.MULTILINE) is not None


# ---------------------------------------------------------------------------
# 1. Slug is translated in zh (the user's explicit request).
# ---------------------------------------------------------------------------

def test_slug_field_translated_to_chinese():
    """``custom_provider_field_slug`` must be Chinese in the zh locale, not
    the literal English word."""
    zh = _extract_locale_block(I18N_JS, "zh")
    m = re.search(
        r"^\s+custom_provider_field_slug\s*:\s*['\"]([^'\"]+)['\"]",
        zh,
        re.MULTILINE,
    )
    assert m, "custom_provider_field_slug missing in zh locale"
    value = m.group(1)
    assert value != "Slug", (
        f"custom_provider_field_slug in zh is still the literal English "
        f"'{value}' — must be translated (e.g. '标识符'). User explicitly "
        f"asked for slug to be translated to Chinese."
    )


def test_slug_field_present_in_english():
    """English keeps the dev term 'Slug' but it must still be defined."""
    en = _extract_locale_block(I18N_JS, "en")
    assert _has_key(en, "custom_provider_field_slug"), (
        "custom_provider_field_slug missing in en locale"
    )


# ---------------------------------------------------------------------------
# 2. Every form field has a corresponding _help key in both en and zh.
# ---------------------------------------------------------------------------

FIELDS = ("name", "slug", "base_url", "api_key", "models")


def test_all_help_keys_exist_in_english():
    en = _extract_locale_block(I18N_JS, "en")
    missing = [
        f"custom_provider_field_{f}_help"
        for f in FIELDS
        if not _has_key(en, f"custom_provider_field_{f}_help")
    ]
    assert not missing, f"missing en help keys: {missing}"


def test_all_help_keys_exist_in_chinese():
    zh = _extract_locale_block(I18N_JS, "zh")
    missing = [
        f"custom_provider_field_{f}_help"
        for f in FIELDS
        if not _has_key(zh, f"custom_provider_field_{f}_help")
    ]
    assert not missing, f"missing zh help keys: {missing}"


def test_help_text_is_substantive_in_chinese():
    """Help text shouldn't be empty/placeholder. Sanity check: each zh help
    string is at least 10 characters of real content (not just punctuation)."""
    zh = _extract_locale_block(I18N_JS, "zh")
    for f in FIELDS:
        m = re.search(
            rf"^\s+custom_provider_field_{f}_help\s*:\s*['\"]([^'\"]+)['\"]",
            zh,
            re.MULTILINE,
        )
        assert m, f"custom_provider_field_{f}_help missing in zh"
        value = m.group(1).strip()
        assert len(value) >= 10, (
            f"custom_provider_field_{f}_help is suspiciously short: {value!r}"
        )


# ---------------------------------------------------------------------------
# 3. Modal HTML renders the help text under each field.
# ---------------------------------------------------------------------------

def test_modal_renders_help_for_every_field():
    """The modal HTML must include ``<p class="form-row-help">`` with the
    corresponding help key for every field."""
    for f in FIELDS:
        key = f"custom_provider_field_{f}_help"
        # Look for the key embedded in a form-row-help paragraph near the
        # corresponding input id. Tolerate surrounding whitespace.
        pattern = re.compile(
            rf'<p\s+class="form-row-help">[^<]*{re.escape(key)}[^<]*</p>',
            re.DOTALL,
        )
        assert pattern.search(PANELS_JS), (
            f"modal HTML in panels.js must render <p class=\"form-row-help\"> "
            f"with t('{key}') for the {f} field"
        )


def test_modal_label_for_slug_uses_translated_text():
    """The slug field's label should use t('custom_provider_field_slug') so it
    picks up the zh translation automatically."""
    # Find the slug form-row
    m = re.search(
        r'<label>\s*\$\{esc\(t\(\'custom_provider_field_slug\'\)\)\}\s*</label>',
        PANELS_JS,
    )
    assert m, (
        "slug <label> in modal must be wired through t('custom_provider_field_slug')"
    )


# ---------------------------------------------------------------------------
# 4. CSS has a .form-row-help rule.
# ---------------------------------------------------------------------------

def test_css_form_row_help_defined():
    assert re.search(r"\.custom-provider-modal\s+\.form-row-help\s*\{", STYLE_CSS), (
        "style.css must define .custom-provider-modal .form-row-help"
    )


def test_css_form_row_help_quickadd_defined():
    assert re.search(
        r"\.composer-quickadd-modal\s+\.form-row-help\s*\{", STYLE_CSS
    ), "style.css must define .composer-quickadd-modal .form-row-help"