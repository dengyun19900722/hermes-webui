"""Set-default tests for custom_providers."""
from __future__ import annotations

import yaml
import pytest
import api.custom_providers as cp


def test_set_default_writes_model_section(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text(yaml.safe_dump({
        "custom_providers": [
            {"name": "X", "slug": "x", "base_url": "https://x",
             "api_key": "k", "models": ["a", "b"]},
        ],
    }))
    monkeypatch.setattr(cp, "list_all_profile_homes", lambda: [tmp_path])
    result = cp.set_default_across_profiles(slug="x", model="a")
    assert result["ok"] is True
    cfg = yaml.safe_load((tmp_path / "config.yaml").read_text())
    assert cfg["model"] == {"provider": "custom:x", "default": "a"}


def test_set_default_unknown_slug_fails(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("{}")
    monkeypatch.setattr(cp, "list_all_profile_homes", lambda: [tmp_path])
    result = cp.set_default_across_profiles(slug="missing", model="a")
    assert result["ok"] is False
    assert "unknown slug" in result["error"].lower() or "not found" in result["error"].lower()


def test_set_default_unknown_model_fails(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text(yaml.safe_dump({
        "custom_providers": [
            {"name": "X", "slug": "x", "base_url": "https://x",
             "api_key": "k", "models": ["a"]},
        ],
    }))
    monkeypatch.setattr(cp, "list_all_profile_homes", lambda: [tmp_path])
    result = cp.set_default_across_profiles(slug="x", model="not-in-list")
    assert result["ok"] is False
    assert "model" in result["error"].lower()


def test_set_default_broadcasts_across_profiles(tmp_path, monkeypatch):
    homes = [tmp_path / f"p{i}" for i in range(3)]
    for h in homes:
        h.mkdir()
        (h / "config.yaml").write_text(yaml.safe_dump({
            "custom_providers": [
                {"name": "X", "slug": "x", "base_url": "https://x",
                 "api_key": "k", "models": ["m1", "m2"]},
            ],
        }))
    monkeypatch.setattr(cp, "list_all_profile_homes", lambda: homes)

    result = cp.set_default_across_profiles(slug="x", model="m2")
    assert result["ok"] is True

    for h in homes:
        cfg = yaml.safe_load((h / "config.yaml").read_text())
        assert cfg["model"] == {"provider": "custom:x", "default": "m2"}