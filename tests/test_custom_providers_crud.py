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
