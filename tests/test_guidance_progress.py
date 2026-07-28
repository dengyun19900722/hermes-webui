"""Tests for api/guidance_progress.py — 实施助手进度持久化与 API."""
import pytest
import yaml
from pathlib import Path
from unittest.mock import patch

from api import guidance_progress as gp


# 解析 fixtures 路径，避免 cwd 依赖（peer review: cwd-independent fixture access）
FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    """Redirect ~/.hermes to tmp_path for isolation.

    Monkeypatches api.guidance_progress.get_active_hermes_home so the module
    resolves to a temp directory regardless of the real profile context.
    """
    fake_home = tmp_path / "hermes"
    fake_home.mkdir()
    monkeypatch.setattr(
        gp, "get_active_hermes_home", lambda: fake_home
    )
    return fake_home


def test_atomic_write_creates_file(tmp_home):
    """_atomic_write_yaml should create a new file with valid YAML."""
    target = tmp_home / "guidance_progress.yaml"
    data = {"implementation": {"1.1_view_doc": {"done": True, "by": "alice", "ts": 1, "note": ""}}}

    gp._atomic_write_yaml(target, data)

    assert target.exists()
    loaded = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert loaded == data


def test_atomic_write_creates_parent_dir(tmp_path):
    """首次写入应自动创建父目录（项目惯例：passkeys/config/onboarding/user_store）."""
    target = tmp_path / "new_subdir" / "deeper" / "guidance_progress.yaml"
    data = {"implementation": {}}

    gp._atomic_write_yaml(target, data)

    assert target.exists()
    assert target.parent.is_dir()


def test_atomic_write_uses_uuid_tmp(tmp_home):
    """两次并发写不应使用固定 tmp 名（避免 race condition）。"""
    target = tmp_home / "guidance_progress.yaml"

    gp._atomic_write_yaml(target, {"implementation": {"a": {"done": True}}})
    gp._atomic_write_yaml(target, {"implementation": {"b": {"done": True}}})

    # 验证无残留的 .tmp 文件
    leftovers = list(tmp_home.glob("*.tmp"))
    assert leftovers == [], f"tmp 文件未清理: {leftovers}"
    # 验证两次写都成功（第二次覆盖第一次）
    loaded = yaml.safe_load(target.read_text(encoding="utf-8"))
    assert "b" in loaded["implementation"]


def test_atomic_write_no_partial_on_os_error(tmp_home):
    """If yaml.safe_dump raises OSError, target file must not be corrupted."""
    target = tmp_home / "guidance_progress.yaml"
    target.write_text("existing: valid\n", encoding="utf-8")

    with patch("yaml.safe_dump", side_effect=OSError("disk full")):
        with pytest.raises(RuntimeError, match="guidance_progress.yaml write failed"):
            gp._atomic_write_yaml(target, {"implementation": {}})

    assert target.read_text(encoding="utf-8") == "existing: valid\n"
    # 验证无残留 tmp
    assert list(tmp_home.glob("*.tmp")) == []


def test_atomic_write_catches_yaml_representer_error(tmp_home):
    """非 OSError 异常（如 YAML RepresenterError）也应被捕获并清理 tmp。"""
    target = tmp_home / "guidance_progress.yaml"
    target.write_text("existing: valid\n", encoding="utf-8")

    # yaml.YAMLError 是 yaml 序列化所有异常的基类
    with patch("yaml.safe_dump", side_effect=yaml.YAMLError("can't represent object")):
        with pytest.raises(RuntimeError, match="guidance_progress.yaml write failed"):
            gp._atomic_write_yaml(target, {"implementation": {}})

    assert target.read_text(encoding="utf-8") == "existing: valid\n"
    assert list(tmp_home.glob("*.tmp")) == []


def test_load_progress_returns_empty_when_missing(tmp_home):
    """First call when YAML doesn't exist should return empty schema, not raise."""
    result = gp.load_progress()

    assert result == {"implementation": {}, "schema_version": 1}


def test_load_progress_reads_existing(tmp_home):
    """Should read pre-existing YAML unchanged."""
    src = FIXTURES_DIR / "guidance_progress_initial.yaml"
    target = tmp_home / "guidance_progress.yaml"
    target.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    result = gp.load_progress()

    assert result["schema_version"] == 1
    assert "1.1_view_doc" in result["implementation"]
    assert result["implementation"]["1.1_view_doc"]["done"] is True


def test_load_progress_handles_non_mapping_yaml(tmp_home):
    """User-edited YAML with scalar/list content should return empty schema, not crash."""
    target = tmp_home / "guidance_progress.yaml"
    target.write_text("- this\n- is\n- a\n- list\n", encoding="utf-8")

    result = gp.load_progress()

    assert result == {"implementation": {}, "schema_version": 1}


def test_load_progress_handles_corrupted_yaml(tmp_home):
    """YAML parse error should not crash; return empty schema."""
    target = tmp_home / "guidance_progress.yaml"
    target.write_text("invalid: : yaml: : :\n  - broken\n", encoding="utf-8")

    result = gp.load_progress()

    assert result == {"implementation": {}, "schema_version": 1}


def test_load_progress_applies_defaults_to_partial_yaml(tmp_home):
    """YAML missing schema_version/implementation keys should get defaults."""
    target = tmp_home / "guidance_progress.yaml"
    target.write_text("other_key: 42\n", encoding="utf-8")

    result = gp.load_progress()

    assert result["schema_version"] == 1
    assert result["implementation"] == {}
    assert result["other_key"] == 42  # 未触及的数据保留