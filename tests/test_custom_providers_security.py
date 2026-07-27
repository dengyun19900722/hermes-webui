"""Security tests for custom_providers: API key redaction + atomic yaml write."""
from __future__ import annotations

import json
import yaml
import pytest
import api.custom_providers as cp


def test_list_response_never_includes_api_key_value(tmp_path, monkeypatch):
    cfg = {"custom_providers": [
        {"name": "A", "slug": "a", "base_url": "https://a",
         "api_key": "sk-SECRET-TOKEN-1234", "models": ["x"]},
    ]}
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg))
    monkeypatch.setattr(cp, "list_all_profile_homes", lambda: [tmp_path])
    serialized = json.dumps(cp.list_custom_providers())
    assert "sk-SECRET-TOKEN-1234" not in serialized, \
        "API key value must NEVER appear in serialized list response"


def test_list_response_includes_has_key_true(tmp_path, monkeypatch):
    cfg = {"custom_providers": [
        {"name": "A", "slug": "a", "base_url": "https://a",
         "api_key": "sk-secret", "models": ["x"]},
    ]}
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg))
    monkeypatch.setattr(cp, "list_all_profile_homes", lambda: [tmp_path])
    result = cp.list_custom_providers()
    assert result[0]["has_key"] is True
    assert "api_key" not in result[0], \
        "api_key field must NOT appear in dict form either (only has_key)"


def test_list_response_includes_has_key_false_when_missing(tmp_path, monkeypatch):
    cfg = {"custom_providers": [
        {"name": "A", "slug": "a", "base_url": "https://a",
         "models": ["x"]},  # no api_key
    ]}
    (tmp_path / "config.yaml").write_text(yaml.safe_dump(cfg))
    monkeypatch.setattr(cp, "list_all_profile_homes", lambda: [tmp_path])
    result = cp.list_custom_providers()
    assert result[0]["has_key"] is False


def test_yaml_write_atomic_no_tmp_leftover(tmp_path):
    target = tmp_path / "config.yaml"
    cp._save_yaml_atomic(target, {"x": 1, "y": [1, 2, 3]})
    assert target.exists()
    assert yaml.safe_load(target.read_text()) == {"x": 1, "y": [1, 2, 3]}
    # No leftover .tmp file
    assert not (tmp_path / (target.name + ".tmp")).exists()


def test_yaml_write_atomic_overwrites_existing(tmp_path):
    target = tmp_path / "config.yaml"
    target.write_text(yaml.safe_dump({"old": True}))
    cp._save_yaml_atomic(target, {"new": True})
    assert yaml.safe_load(target.read_text()) == {"new": True}


def test_yaml_write_atomic_handles_nested_data(tmp_path):
    target = tmp_path / "config.yaml"
    data = {
        "custom_providers": [
            {"name": "A", "slug": "a", "base_url": "https://a",
             "api_key": "k1", "models": ["m1", "m2"]},
        ],
        "model": {"provider": "custom:a", "default": "m1"},
    }
    cp._save_yaml_atomic(target, data)
    loaded = yaml.safe_load(target.read_text())
    assert loaded == data
    assert "api_key" not in str(loaded) or loaded["custom_providers"][0]["api_key"] == "k1"