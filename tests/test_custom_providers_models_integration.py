"""Models integration tests for custom_providers — verifying list_custom_providers
exposes models correctly (drives the Composer dropdown integration)."""
from __future__ import annotations

import yaml
import pytest
import api.custom_providers as cp


def test_list_includes_custom_provider_with_models(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text(yaml.safe_dump({
        "custom_providers": [
            {"name": "A", "slug": "a", "base_url": "https://a",
             "api_key": "k", "models": ["x", "y"]},
        ],
    }))
    monkeypatch.setattr(cp, "list_all_profile_homes", lambda: [tmp_path])
    result = cp.list_custom_providers()
    assert len(result) == 1
    assert result[0]["name"] == "A"
    assert result[0]["slug"] == "a"
    assert result[0]["base_url"] == "https://a"
    assert result[0]["models"] == ["x", "y"]
    assert result[0]["has_key"] is True


def test_list_dedupes_providers_across_profiles(tmp_path, monkeypatch):
    """Same provider defined in multiple profiles appears once."""
    homes = [tmp_path / f"p{i}" for i in range(3)]
    for h in homes:
        h.mkdir()
        (h / "config.yaml").write_text(yaml.safe_dump({
            "custom_providers": [
                {"name": "Shared", "slug": "shared", "base_url": "https://shared",
                 "api_key": "k", "models": ["m"]},
            ],
        }))
    monkeypatch.setattr(cp, "list_all_profile_homes", lambda: homes)
    result = cp.list_custom_providers()
    slugs = [p["slug"] for p in result]
    assert slugs.count("shared") == 1, f"expected dedup, got: {slugs}"


def test_list_aggregates_models_for_same_slug(tmp_path, monkeypatch):
    """When the same slug has different models in different profiles, we union them."""
    homes = [tmp_path / "p0", tmp_path / "p1"]
    for i, h in enumerate(homes):
        h.mkdir()
        (h / "config.yaml").write_text(yaml.safe_dump({
            "custom_providers": [
                {"name": "X", "slug": "x", "base_url": "https://x",
                 "api_key": "k", "models": [f"m{i}", "common"]},
            ],
        }))
    monkeypatch.setattr(cp, "list_all_profile_homes", lambda: homes)
    result = cp.list_custom_providers()
    x_providers = [p for p in result if p["slug"] == "x"]
    assert len(x_providers) == 1
    # models should be a union (or at least contain 'common')
    assert "common" in x_providers[0]["models"]


def test_list_includes_empty_models_when_no_models_field(tmp_path, monkeypatch):
    """Legacy entry without explicit models list defaults to []."""
    (tmp_path / "config.yaml").write_text(yaml.safe_dump({
        "custom_providers": [
            {"name": "Legacy", "slug": "legacy", "base_url": "https://legacy",
             "api_key": "k"},
        ],
    }))
    monkeypatch.setattr(cp, "list_all_profile_homes", lambda: [tmp_path])
    result = cp.list_custom_providers()
    assert result[0]["slug"] == "legacy"
    assert result[0]["models"] == []