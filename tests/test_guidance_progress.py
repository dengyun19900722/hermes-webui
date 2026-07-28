"""Tests for api/guidance_progress.py — 实施助手进度持久化与 API."""
import pytest
import yaml
from pathlib import Path
from unittest.mock import patch

from api import guidance_progress as gp


@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    """Redirect ~/.hermes to tmp_path for isolation."""
    fake_home = tmp_path / "hermes"
    fake_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(fake_home))
    return fake_home


def test_atomic_write_creates_file(tmp_home):
    """_atomic_write_yaml should create a new file with valid YAML."""
    target = tmp_home / "guidance_progress.yaml"
    data = {"implementation": {"1.1_view_doc": {"done": True, "by": "alice", "ts": 1, "note": ""}}}

    gp._atomic_write_yaml(target, data)

    assert target.exists()
    loaded = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert loaded == data


def test_atomic_write_no_partial_on_failure(tmp_home):
    """If YAML dump fails midway, target file must not be corrupted."""
    target = tmp_home / "guidance_progress.yaml"
    target.write_text("existing: valid\n", encoding="utf-8")

    with patch("yaml.safe_dump", side_effect=OSError("disk full")):
        with pytest.raises(RuntimeError, match="guidance_progress.yaml write failed"):
            gp._atomic_write_yaml(target, {"implementation": {}})

    assert target.read_text(encoding="utf-8") == "existing: valid\n"
    assert not (target.parent / "guidance_progress.yaml.tmp").exists()


def test_load_progress_returns_empty_when_missing(tmp_home):
    """First call when YAML doesn't exist should return empty schema, not raise."""
    result = gp.load_progress()

    assert result == {"implementation": {}, "schema_version": 1}


def test_load_progress_reads_existing(tmp_home, tmp_path):
    """Should read pre-existing YAML unchanged."""
    src = Path("tests/fixtures/guidance_progress_initial.yaml")
    target = tmp_home / "guidance_progress.yaml"
    target.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    result = gp.load_progress()

    assert result["schema_version"] == 1
    assert "1.1_view_doc" in result["implementation"]
    assert result["implementation"]["1.1_view_doc"]["done"] is True
