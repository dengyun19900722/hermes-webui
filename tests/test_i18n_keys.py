"""Guard the RBAC i18n keys added for password change + workspace empty state.

`static/i18n.js` declares one object literal per locale inside a single
`const LOCALES = { ... }`. `t()` resolves `_locale[key] ?? LOCALES.en[key]`,
so a key only needs to exist in `en` (universal fallback) and `zh` (the
default locale for this deployment) to render correctly everywhere.

Note on style: keys in this file are written as bare JS identifiers with
single-quoted values (`some_key: 'value',`) -- there is not a single
double-quoted key in the whole file. The regex below matches the bare form
on purpose; requiring `"key":` would enforce a style the file does not use.
"""

import re
from pathlib import Path

I18N_PATH = Path(__file__).resolve().parents[1] / "static" / "i18n.js"

REQUIRED_KEYS = [
    "menu_change_password", "change_password_title",
    "change_password_old", "change_password_new", "change_password_confirm",
    "change_password_submit", "change_password_cancel",
    "password_old_wrong", "password_too_short", "password_needs_classes",
    "password_mismatch", "password_changed_ok",
    "admin_reset_password", "admin_reset_password_title",
    "admin_reset_password_hint", "admin_reset_password_ok",
    "workspace_empty_title", "workspace_empty_hint", "workspace_empty_create_btn",
    "workspace_role_owner", "workspace_owner_label",
]

# Locales that must carry every key: `en` is the hard fallback in t(),
# `zh` is the default locale chosen by loadLocale().
REQUIRED_LOCALES = ("en", "zh")

# `  en: {` / `  'zh-Hant': {` at exactly two-space indent opens a locale block;
# `  },` at the same indent closes it.
_LOCALE_OPEN = re.compile(r"^ {2}'?([A-Za-z][\w-]*)'?\s*:\s*\{\s*$")
_LOCALE_CLOSE = re.compile(r"^ {2}\},?\s*$")


def _locale_blocks(src: str) -> dict[str, str]:
    """Split i18n.js into {locale_name: block_source}."""
    blocks: dict[str, list[str]] = {}
    current: str | None = None
    for line in src.splitlines():
        if current is None:
            match = _LOCALE_OPEN.match(line)
            if match:
                current = match.group(1)
                blocks[current] = []
            continue
        if _LOCALE_CLOSE.match(line):
            current = None
            continue
        blocks[current].append(line)
    return {name: "\n".join(lines) for name, lines in blocks.items()}


def _key_occurrences(block: str, key: str) -> int:
    """Count `key: value` definitions, ignoring substring/comment matches."""
    return len(re.findall(rf"^\s*'?{re.escape(key)}'?\s*:", block, re.MULTILINE))


def test_locale_blocks_are_parseable():
    blocks = _locale_blocks(I18N_PATH.read_text(encoding="utf-8"))
    for locale in REQUIRED_LOCALES:
        assert locale in blocks, (
            f"Locale {locale!r} not found; parsed locales: {sorted(blocks)}"
        )


def test_all_keys_in_each_required_locale():
    blocks = _locale_blocks(I18N_PATH.read_text(encoding="utf-8"))
    missing = []
    for locale in REQUIRED_LOCALES:
        for key in REQUIRED_KEYS:
            count = _key_occurrences(blocks[locale], key)
            if count != 1:
                missing.append(f"{locale}.{key} defined {count} times (want exactly 1)")
    assert not missing, "i18n key problems:\n  " + "\n  ".join(missing)


def test_no_key_defined_twice_anywhere():
    """A duplicate key in one locale silently shadows the earlier value."""
    blocks = _locale_blocks(I18N_PATH.read_text(encoding="utf-8"))
    dupes = [
        f"{locale}.{key} x{count}"
        for locale, block in blocks.items()
        for key in REQUIRED_KEYS
        if (count := _key_occurrences(block, key)) > 1
    ]
    assert not dupes, "Duplicate i18n definitions: " + ", ".join(dupes)


def test_username_placeholder_present_where_expected():
    """These four strings are interpolated with a username by the UI layer."""
    blocks = _locale_blocks(I18N_PATH.read_text(encoding="utf-8"))
    for locale in REQUIRED_LOCALES:
        for key in ("admin_reset_password_title", "admin_reset_password_ok",
                    "workspace_owner_label"):
            line = re.search(
                rf"^\s*'?{re.escape(key)}'?\s*:.*$", blocks[locale], re.MULTILINE
            )
            assert line and "{username}" in line.group(0), (
                f"{locale}.{key} must contain the {{username}} placeholder"
            )
