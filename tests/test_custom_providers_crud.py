"""Custom provider CRUD smoke tests (Task 5/6).

Covers list_custom_providers redaction behavior; reused for the
manual-smoke gate before Task 7 wires the REST endpoint.
"""
import yaml
import pytest
from pathlib import Path
from api.custom_providers import list_custom_providers


def test_list_empty(tmp_path, monkeypatch):
    home = tmp_path
    (home / "config.yaml").write_text("{}\n")
    monkeypatch.setattr("api.custom_providers.list_all_profile_homes", lambda: [home])
    result = list_custom_providers()
    assert result == []


def test_list_returns_entries_without_api_key_value(tmp_path, monkeypatch):
    cfg = {
        "custom_providers": [
            {"name": "A", "slug": "a", "base_url": "https://a", "api_key": "sk-SECRET", "models": ["x"]},
        ]
    }
    home = tmp_path
    (home / "config.yaml").write_text(yaml.safe_dump(cfg))
    monkeypatch.setattr("api.custom_providers.list_all_profile_homes", lambda: [home])
    result = list_custom_providers()
    assert len(result) == 1
    assert result[0]["slug"] == "a"
    assert result[0]["has_key"] is True
    # The literal value MUST NOT appear in any field
    for field in result[0].values():
        assert "sk-SECRET" not in str(field)


def test_list_has_key_false_when_no_key(tmp_path, monkeypatch):
    cfg = {"custom_providers": [{"name": "A", "slug": "a", "base_url": "https://a", "api_key": None, "models": ["x"]}]}
    home = tmp_path
    (home / "config.yaml").write_text(yaml.safe_dump(cfg))
    monkeypatch.setattr("api.custom_providers.list_all_profile_homes", lambda: [home])
    result = list_custom_providers()
    assert result[0]["has_key"] is False


def test_smoke_validate_then_upsert(tmp_path, monkeypatch):
    """Smoke test for Task 6: ensure validate_provider_body + upsert_custom_provider_across_profiles
    integrate correctly when called in sequence as the HTTP handler does."""
    import api.custom_providers as cp
    (tmp_path / "config.yaml").write_text("{}")
    monkeypatch.setattr(cp, "list_all_profile_homes", lambda: [tmp_path])

    provider = {
        "name": "Smoke",
        "slug": "smoke",
        "base_url": "https://x/v1",
        "api_key": "k",
        "models": ["a"],
    }
    cp.validate_provider_body(provider)
    result = cp.upsert_custom_provider_across_profiles(provider=provider)
    assert result["ok"] is True
    assert result["succeeded_count"] == 1
    assert result["total_count"] == 1
    assert result["slug"] == "smoke"  # returned for composer quick-add auto-select
