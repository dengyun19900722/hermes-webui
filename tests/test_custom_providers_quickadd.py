"""Quick-add (composer mini modal) integration tests for custom_providers.

Verifies the backend correctly handles the minimal payloads sent by the
Composer ➕ quick-add modal (spec §2.8).
"""
from __future__ import annotations

import yaml
import pytest
import api.custom_providers as cp


def test_quickadd_minimal_body_creates_entry(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("{}")
    monkeypatch.setattr(cp, "list_all_profile_homes", lambda: [tmp_path])
    result = cp.upsert_custom_provider_across_profiles(provider={
        "name": "My Relay",
        "slug": "my-relay",
        "base_url": "https://relay.example.com/v1",
        "api_key": "sk-x",
        "models": ["gpt-4o", "gpt-4o-mini"],
    })
    assert result["ok"] is True
    cfg = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert len(cfg["custom_providers"]) == 1
    entry = cfg["custom_providers"][0]
    assert entry["slug"] == "my-relay"
    assert entry["base_url"] == "https://relay.example.com/v1"
    assert entry["api_key"] == "sk-x"
    assert entry["models"] == ["gpt-4o", "gpt-4o-mini"]


def test_quickadd_models_fallback_when_missing(tmp_path, monkeypatch):
    """Quick-add path: when caller can't probe, models=['default'] is acceptable."""
    (tmp_path / "config.yaml").write_text("{}")
    monkeypatch.setattr(cp, "list_all_profile_homes", lambda: [tmp_path])
    result = cp.upsert_custom_provider_across_profiles(provider={
        "name": "X",
        "slug": "x",
        "base_url": "https://x",
        "api_key": None,
        "models": ["default"],
    })
    assert result["ok"] is True


def test_quickadd_visible_in_list_after_create(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("{}")
    monkeypatch.setattr(cp, "list_all_profile_homes", lambda: [tmp_path])
    create_result = cp.upsert_custom_provider_across_profiles(provider={
        "name": "X", "slug": "x", "base_url": "https://x",
        "api_key": "k", "models": ["a"],
    })
    assert create_result["ok"] is True
    listed = cp.list_custom_providers()
    assert any(p["slug"] == "x" for p in listed)


def test_quickadd_upsert_returns_slug(tmp_path, monkeypatch):
    """The composer auto-select flow relies on getting the slug back from upsert."""
    (tmp_path / "config.yaml").write_text("{}")
    monkeypatch.setattr(cp, "list_all_profile_homes", lambda: [tmp_path])
    result = cp.upsert_custom_provider_across_profiles(provider={
        "name": "X", "slug": "x", "base_url": "https://x",
        "api_key": "k", "models": ["a"],
    })
    assert result.get("slug") == "x", \
        f"upsert result must include slug for composer auto-select: {result}"


def test_quickadd_no_api_key_allowed(tmp_path, monkeypatch):
    """Quick-add modal lets user skip API key (api_key=None)."""
    (tmp_path / "config.yaml").write_text("{}")
    monkeypatch.setattr(cp, "list_all_profile_homes", lambda: [tmp_path])
    result = cp.upsert_custom_provider_across_profiles(provider={
        "name": "X", "slug": "x", "base_url": "https://x",
        "api_key": None, "models": ["a"],
    })
    assert result["ok"] is True
    listed = cp.list_custom_providers()
    assert listed[0]["has_key"] is False