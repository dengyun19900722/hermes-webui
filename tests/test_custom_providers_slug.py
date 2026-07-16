# tests/test_custom_providers_slug.py
import pytest
from api import custom_providers
from api.custom_providers import slug_from_name, _BUILTIN_SLUGS, register_plugin_slugs


def test_slug_from_name_basic():
    assert slug_from_name("My OpenAI 中转") == "my-openai"


def test_slug_from_name_strips_invalid_chars():
    assert slug_from_name("relay/@host!") == "relay-host"


def test_slug_from_name_preserves_dot_underscore_dash():
    assert slug_from_name("my.gateway_thing-1") == "my.gateway_thing-1"


def test_slug_from_name_unicode_pinyin_safe():
    # 中文 → 保留（仅过滤非 ASCII 字母数字/._-）
    assert slug_from_name("OpenAI 中转") == "openai"


def test_slug_from_name_empty_after_strip_raises():
    with pytest.raises(ValueError, match="slug required"):
        slug_from_name("///")


def test_slug_from_name_trims_to_64():
    long = "a" * 100
    out = slug_from_name(long)
    assert len(out) <= 64


def test_builtin_slugs_includes_known():
    for s in ("anthropic", "openai", "openrouter", "ollama", "lmstudio"):
        assert s in _BUILTIN_SLUGS


def test_register_plugin_slugs_lowercases_and_skips_falsy():
    # Read via module attribute (not ``from … import _PLUGIN_SLUGS``) so we
    # see the live rebound global after ``register_plugin_slugs`` runs.
    register_plugin_slugs(["Plugin-A", "", "Plugin-B"])
    try:
        assert {"plugin-a", "plugin-b"} <= custom_providers._PLUGIN_SLUGS
    finally:
        # Reset to avoid leaking state across tests in the same process.
        register_plugin_slugs([])
