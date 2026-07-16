"""Tests for provider body validation in api.custom_providers.

Task 2: validate_provider_body + ValidationError.

Run via direct invocation (conftest test_server is blocked by license check):
    python -c "
    import tests.test_custom_providers_validation as t
    for name in dir(t):
        if name.startswith('test_'):
            try:
                getattr(t, name)()
                print('PASS', name)
            except Exception as e:
                print('FAIL', name, type(e).__name__, e)
    "
"""

import pytest

from api.custom_providers import validate_provider_body, ValidationError


def _base_body() -> dict:
    return {
        "name": "My Relay",
        "slug": "my-relay",
        "base_url": "https://relay.example.com/v1",
        "api_key": "sk-xxx",
        "models": ["gpt-4o", "gpt-4o-mini"],
    }


def test_validate_ok():
    validate_provider_body(_base_body())  # no raise


def test_validate_missing_name():
    body = _base_body()
    body["name"] = ""
    with pytest.raises(ValidationError, match="name_required"):
        validate_provider_body(body)


def test_validate_missing_base_url():
    body = _base_body()
    body["base_url"] = ""
    with pytest.raises(ValidationError, match="base_url_required"):
        validate_provider_body(body)


def test_validate_base_url_non_http():
    body = _base_body()
    body["base_url"] = "ftp://x"
    with pytest.raises(ValidationError, match="base_url_invalid"):
        validate_provider_body(body)


def test_validate_base_url_strips_trailing_slash():
    body = _base_body()
    body["base_url"] = "https://x/v1/"
    validate_provider_body(body)
    assert body["base_url"] == "https://x/v1"


def test_validate_models_empty():
    body = _base_body()
    body["models"] = []
    with pytest.raises(ValidationError, match="models_empty"):
        validate_provider_body(body)


def test_validate_models_dedupes():
    body = _base_body()
    body["models"] = ["a", "a", "b"]
    validate_provider_body(body)
    assert body["models"] == ["a", "b"]


def test_validate_models_strips_whitespace():
    body = _base_body()
    body["models"] = ["  a  ", " b"]
    validate_provider_body(body)
    assert body["models"] == ["a", "b"]


def test_validate_slug_invalid_chars():
    body = _base_body()
    body["slug"] = "my relay!"
    with pytest.raises(ValidationError, match="slug_invalid"):
        validate_provider_body(body)


def test_validate_slug_collides_builtin():
    body = _base_body()
    body["slug"] = "anthropic"
    with pytest.raises(ValidationError, match="slug_collides_builtin"):
        validate_provider_body(body)
