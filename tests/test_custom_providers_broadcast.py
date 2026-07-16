# tests/test_custom_providers_broadcast.py
import os
import yaml
import pytest
from pathlib import Path
from api.custom_providers import (
    upsert_custom_provider_across_profiles,
    delete_custom_provider_across_profiles,
    set_default_across_profiles,
)


@pytest.fixture
def multi_profile_homes(tmp_path: Path, monkeypatch) -> list[Path]:
    homes = []
    for name in ("default", "work", "test"):
        home = tmp_path / name
        home.mkdir()
        (home / "config.yaml").write_text(
            yaml.safe_dump(
                {"model": {"provider": "anthropic", "default": "claude"}},
                allow_unicode=True,
            )
        )
        homes.append(home)
    monkeypatch.setattr(
        "api.custom_providers.list_all_profile_homes", lambda: homes
    )
    return homes


def test_upsert_writes_to_all_profiles(multi_profile_homes):
    result = upsert_custom_provider_across_profiles(
        provider={
            "name": "My Relay",
            "slug": "my-relay",
            "base_url": "https://r.example.com/v1",
            "api_key": "sk-x",
            "models": ["gpt-4o"],
        }
    )
    assert result["ok"] is True
    assert result["succeeded_count"] == 3
    assert result["total_count"] == 3
    for home in multi_profile_homes:
        cfg = yaml.safe_load((home / "config.yaml").read_text())
        assert "custom_providers" in cfg
        assert cfg["custom_providers"][0]["slug"] == "my-relay"


def test_upsert_overwrites_same_slug(multi_profile_homes):
    upsert_custom_provider_across_profiles(
        provider={
            "name": "My Relay",
            "slug": "my-relay",
            "base_url": "https://a",
            "api_key": "k1",
            "models": ["a"],
        }
    )
    upsert_custom_provider_across_profiles(
        provider={
            "name": "My Relay v2",
            "slug": "my-relay",
            "base_url": "https://b",
            "api_key": "k2",
            "models": ["b"],
        }
    )
    for home in multi_profile_homes:
        cfg = yaml.safe_load((home / "config.yaml").read_text())
        assert len(cfg["custom_providers"]) == 1
        assert cfg["custom_providers"][0]["base_url"] == "https://b"
        assert cfg["custom_providers"][0]["models"] == ["b"]


def test_upsert_partial_failure_collects_failed_profiles(
    multi_profile_homes, monkeypatch
):
    # Make one profile read-only. Skip when running as root because UID 0
    # bypasses DAC permission checks on POSIX, which makes the fixture a
    # no-op (the test would then incorrectly report full success).
    if os.geteuid() == 0:
        pytest.skip("chmod 0o000 is a no-op for root; cannot simulate denial")
    target = multi_profile_homes[1] / "config.yaml"
    original_mode = target.stat().st_mode & 0o777
    os.chmod(target, 0o000)
    try:
        result = upsert_custom_provider_across_profiles(
            provider={
                "name": "X",
                "slug": "x",
                "base_url": "https://x",
                "api_key": None,
                "models": ["a"],
            }
        )
    finally:
        os.chmod(target, original_mode)
    assert result["ok"] is False
    assert result["succeeded_count"] == 2
    assert result["total_count"] == 3
    assert any(f["profile"] == "work" for f in result["failed_profiles"])


def test_delete_removes_from_all_profiles(multi_profile_homes):
    upsert_custom_provider_across_profiles(
        provider={
            "name": "X",
            "slug": "x",
            "base_url": "https://x",
            "api_key": "k",
            "models": ["a"],
        }
    )
    result = delete_custom_provider_across_profiles(slug="x")
    assert result["ok"] is True
    for home in multi_profile_homes:
        cfg = yaml.safe_load((home / "config.yaml").read_text())
        assert "custom_providers" not in cfg or cfg["custom_providers"] == []


def test_set_default_writes_model_section(multi_profile_homes):
    upsert_custom_provider_across_profiles(
        provider={
            "name": "X",
            "slug": "x",
            "base_url": "https://x",
            "api_key": "k",
            "models": ["a", "b"],
        }
    )
    result = set_default_across_profiles(slug="x", model="a")
    assert result["ok"] is True
    for home in multi_profile_homes:
        cfg = yaml.safe_load((home / "config.yaml").read_text())
        assert cfg["model"] == {"provider": "custom:x", "default": "a"}


def test_upsert_partial_failure_mock_based(multi_profile_homes, monkeypatch):
    """Same scenario as test_upsert_partial_failure_collects_failed_profiles but
    environment-independent (no chmod, no UID-0 concerns)."""
    import api.custom_providers as cp
    target = multi_profile_homes[1]
    original = cp._save_yaml_atomic

    def selective_save(path, data):
        if str(path).endswith(str(target / "config.yaml")):
            raise PermissionError("simulated")
        return original(path, data)

    monkeypatch.setattr(cp, "_save_yaml_atomic", selective_save)
    result = cp.upsert_custom_provider_across_profiles(provider={
        "name": "X", "slug": "x", "base_url": "https://x", "api_key": None, "models": ["a"],
    })
    assert result["ok"] is False
    assert result["succeeded_count"] == 2
    assert result["total_count"] == 3
    assert any(f["profile"] == "work" and f["error"] == "permission_denied" for f in result["failed_profiles"])


def test_set_default_rejects_unknown_slug(multi_profile_homes):
    result = set_default_across_profiles(slug="nope", model="x")
    assert result["ok"] is False
    assert "unknown slug" in result["error"]
    assert result["succeeded_count"] == 0
    # Verify no profile was mutated
    for home in multi_profile_homes:
        cfg = yaml.safe_load((home / "config.yaml").read_text())
        assert "model" not in cfg or cfg["model"].get("provider") != "custom:nope"


def test_set_default_rejects_unknown_model(multi_profile_homes):
    upsert_custom_provider_across_profiles(provider={
        "name": "X", "slug": "x", "base_url": "https://x", "api_key": "k", "models": ["a", "b"],
    })
    result = set_default_across_profiles(slug="x", model="nonexistent")
    assert result["ok"] is False
    assert "model not in provider" in result["error"]


# === M1: Orphan .tmp cleanup ============================================
def test_save_yaml_atomic_cleans_tmp_on_replace_failure(
    multi_profile_homes, monkeypatch
):
    """When ``os.replace`` fails the stray ``.tmp`` must be unlinked.

    ``_save_yaml_atomic`` uses uuid-based tmp filenames
    (``config.yaml.<uuid>.tmp``) so concurrent writers don't clobber each
    other's tmp files (#5692); the cleanup test therefore fails on any
    replace targeting the target's path rather than a fixed tmp name.
    """
    import api.custom_providers as cp
    target = multi_profile_homes[0] / "config.yaml"

    # Make sure no leftover .tmp from a previous run
    for stray in target.parent.glob(f"{target.name}.*.tmp"):
        stray.unlink()

    real_replace = cp.os.replace

    def failing_replace(src, dst):
        if str(dst) == str(target):
            raise OSError("simulated cross-device move")
        return real_replace(src, dst)

    monkeypatch.setattr(cp.os, "replace", failing_replace)
    with pytest.raises(OSError):
        cp._save_yaml_atomic(target, {"x": 1})
    strays = list(target.parent.glob(f"{target.name}.*.tmp"))
    assert not strays, f"orphan .tmp files were not cleaned up: {strays}"
