"""Concurrency tests for custom_providers: serialized writes across profiles."""
from __future__ import annotations

import threading
import yaml
import pytest
import api.custom_providers as cp


def test_lock_serializes_concurrent_writes(tmp_path, monkeypatch):
    homes = [tmp_path / f"p{i}" for i in range(3)]
    for h in homes:
        h.mkdir()
        (h / "config.yaml").write_text("{}")
    monkeypatch.setattr(cp, "list_all_profile_homes", lambda: homes)

    results = []
    errors = []

    def worker(i):
        try:
            r = cp.upsert_custom_provider_across_profiles(provider={
                "name": f"X{i}", "slug": f"x{i}",
                "base_url": f"https://x{i}", "api_key": "k", "models": ["a"],
            })
            results.append(r)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"workers raised: {errors}"
    assert all(r.get("ok") for r in results), f"not all succeeded: {results}"
    # Each profile should have all 3 entries (lock serializes them correctly)
    for h in homes:
        cfg = yaml.safe_load((h / "config.yaml").read_text())
        assert cfg is not None
        slugs = {p["slug"] for p in cfg.get("custom_providers", [])}
        assert slugs == {"x0", "x1", "x2"}, f"profile {h.name} has {slugs}"


def test_lock_serializes_concurrent_deletes(tmp_path, monkeypatch):
    home = tmp_path / "p"
    home.mkdir()
    cfg = {"custom_providers": [
        {"name": "A", "slug": "a", "base_url": "https://a", "models": ["m"]},
    ]}
    (home / "config.yaml").write_text(yaml.safe_dump(cfg))
    monkeypatch.setattr(cp, "list_all_profile_homes", lambda: [home])

    # Two threads racing to delete 'a': one wins, one gets a 'not found' error but no crash
    results = []

    def worker():
        try:
            r = cp.delete_custom_provider_across_profiles(slug="a")
            results.append(r)
        except Exception as e:
            results.append({"ok": False, "error": str(e)})

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 5
    # At least one succeeded
    assert any(r.get("ok") for r in results), \
        f"at least one delete must succeed: {results}"
    # Final state: no entry remains
    final_cfg = yaml.safe_load((home / "config.yaml").read_text())
    assert not final_cfg.get("custom_providers")