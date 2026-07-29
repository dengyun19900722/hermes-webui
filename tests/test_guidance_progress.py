"""Tests for api/guidance_progress.py — 实施助手进度持久化与 API."""
import pytest
import time
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


def test_validate_task_id_accepts_whitelisted():
    assert gp.validate_task_id("1.1_view_doc") is True
    assert gp.validate_task_id("3.4_record_result") is True


def test_validate_task_id_rejects_unknown():
    with pytest.raises(ValueError, match="unknown_task"):
        gp.validate_task_id("99.99_invalid")
    with pytest.raises(ValueError, match="unknown_task"):
        gp.validate_task_id("DROP TABLE")


def test_get_task_metadata_returns_12_tasks():
    """Static metadata for the 12-step checklist, grouped by 3 subtasks."""
    tasks = gp.get_task_metadata()

    assert len(tasks) == 12
    groups = {t["group"] for t in tasks}
    assert groups == {1, 2, 3}

    by_group = {}
    for t in tasks:
        by_group.setdefault(t["group"], []).append(t)
    assert len(by_group[1]) == 5  # 业务线：1.1, 1.2, 1.3a, 1.3b, 1.3c
    assert len(by_group[2]) == 3  # 知识库
    assert len(by_group[3]) == 4  # 验证

    assert by_group[1][0]["group_title"] == "业务线实体关系表整理"
    assert by_group[2][0]["group_title"] == "知识库整理（故障FAQ）"
    assert by_group[3][0]["group_title"] == "巡检+诊断技能验证"


def test_merge_with_metadata_includes_default_done_false():
    """Tasks never marked should default to done=False, by=None, ts=None, note=''."""
    progress = {"schema_version": 1, "implementation": {}}
    merged = gp.merge_with_metadata(progress)

    assert len(merged) == 12
    for task in merged:
        assert task["done"] is False
        assert task["by"] is None
        assert task["ts"] is None
        assert task["note"] == ""


def test_merge_with_metadata_preserves_done_state():
    """Already-done tasks keep their by/ts/note."""
    progress = {
        "schema_version": 1,
        "implementation": {
            "1.1_view_doc": {"done": True, "by": "alice", "ts": 100, "note": "ok"},
        },
    }
    merged = gp.merge_with_metadata(progress)

    task_1_1 = next(t for t in merged if t["id"] == "1.1_view_doc")
    assert task_1_1["done"] is True
    assert task_1_1["by"] == "alice"
    assert task_1_1["ts"] == 100


# ── Task 4: mark_task + update_note ──────────────────────────────────────────


def test_mark_task_done(tmp_home):
    """mark_task should set done=True, record by and ts."""
    before = int(time.time())
    task = gp.mark_task("1.1_view_doc", done=True, by="alice", note="")
    after = int(time.time())
    assert task["done"] is True
    assert task["by"] == "alice"
    assert before <= task["ts"] <= after
    assert task["note"] == ""

    persisted = gp.load_progress()
    assert persisted["implementation"]["1.1_view_doc"]["done"] is True


def test_mark_task_undone_clears_by_and_ts(tmp_home):
    gp.mark_task("1.1_view_doc", done=True, by="alice", note="kept")
    task = gp.mark_task("1.1_view_doc", done=False, by="alice", note="kept")
    assert task["done"] is False
    assert task["by"] is None
    assert task["ts"] is None
    assert task["note"] == "kept"


def test_mark_task_unknown_raises(tmp_home):
    with pytest.raises(ValueError, match="unknown_task"):
        gp.mark_task("bogus", done=True, by="alice")


def test_update_note_does_not_change_done(tmp_home):
    gp.mark_task("1.1_view_doc", done=True, by="alice", note="")
    task = gp.update_note("1.1_view_doc", note="关联 ZKREQ-130")
    assert task["done"] is True
    assert task["by"] == "alice"
    assert task["note"] == "关联 ZKREQ-130"


def test_update_note_allows_empty(tmp_home):
    gp.update_note("1.1_view_doc", note="something")
    task = gp.update_note("1.1_view_doc", note="")
    assert task["note"] == ""


def test_mark_task_concurrent_writes_safe(tmp_home):
    gp.mark_task("1.1_view_doc", done=True, by="alice")
    gp.mark_task("1.2_download_tpl", done=True, by="bob")
    persisted = gp.load_progress()
    assert persisted["implementation"]["1.1_view_doc"]["by"] == "alice"
    assert persisted["implementation"]["1.2_download_tpl"]["by"] == "bob"


# ── Task 5: reset_progress ──────────────────────────────────────────────────


def test_reset_progress_clears_all(tmp_home):
    gp.mark_task("1.1_view_doc", done=True, by="alice")
    gp.mark_task("1.2_download_tpl", done=True, by="alice")
    gp.reset_progress()
    result = gp.load_progress()
    assert result["implementation"] == {}


# ── Task 6: get_full_state ──────────────────────────────────────────────────


def test_get_full_state_returns_schema_and_summary(tmp_home):
    gp.mark_task("1.1_view_doc", done=True, by="alice")
    state = gp.get_full_state()
    assert state["schema_version"] == 1
    assert "deployment_id" in state
    assert "first_seen_at" in state
    assert len(state["tasks"]) == 12
    assert state["summary"]["total"] == 12
    assert state["summary"]["done"] == 1
    assert state["summary"]["by_group"] == {"1": 1, "2": 0, "3": 0}


def test_get_full_state_first_seen_persists(tmp_home):
    state1 = gp.get_full_state()
    state2 = gp.get_full_state()
    assert state1["first_seen_at"] == state2["first_seen_at"]
    assert state1["deployment_id"] == state2["deployment_id"]


# ── Task 7: CSV validation ──────────────────────────────────────────────────


def test_validate_csv_happy_path():
    content = (FIXTURES_DIR / "business_entities_valid.csv").read_text(encoding="utf-8")
    result = gp.validate_business_entity_csv(content)
    assert result["ok"] is True
    assert result["total_rows"] == 5
    assert result["failed_rows"] == []


def test_validate_csv_missing_column():
    content = (FIXTURES_DIR / "business_entities_missing_col.csv").read_text(encoding="utf-8")
    result = gp.validate_business_entity_csv(content)
    assert result["ok"] is False
    assert "业务线名称" in result["missing"]


def test_validate_csv_bad_ip():
    content = (FIXTURES_DIR / "business_entities_bad_ip.csv").read_text(encoding="utf-8")
    result = gp.validate_business_entity_csv(content)
    assert result["ok"] is False
    assert len(result["failed_rows"]) >= 2
    assert any(f["field"] == "主机IP" for f in result["failed_rows"])


def test_validate_csv_size_limit():
    rows = ["业务线名称,主机IP,主机角色\n"]
    for i in range(10001):
        rows.append(f"line_{i},10.0.0.{i % 256},DB\n")
    content = "".join(rows)
    result = gp.validate_business_entity_csv(content)
    assert result["ok"] is False
    assert "size_limit" in str(result.get("error", ""))


def test_validate_csv_xlsx_rejected():
    result = gp.validate_business_entity_csv(
        "fake xlsx content",
        filename="test.xlsx",
    )
    assert result["ok"] is False
    assert result["error"] == "unsupported_format"


# ── Task 8: import_business_entities ────────────────────────────────────────


def test_import_happy_path_marks_task_done(tmp_home):
    content = (FIXTURES_DIR / "business_entities_valid.csv").read_text(encoding="utf-8")
    result = gp.import_business_entities(content, filename="test.csv", by="alice")
    assert result["ok"] is True
    assert result["imported_rows"] == 5
    assert result["task_updated"] == "1.3_import"
    state = gp.get_full_state()
    task = next(t for t in state["tasks"] if t["id"] == "1.3_import")
    assert task["done"] is True
    assert task["by"] == "alice"


def test_import_validation_failure_no_task_update(tmp_home):
    content = (FIXTURES_DIR / "business_entities_bad_ip.csv").read_text(encoding="utf-8")
    result = gp.import_business_entities(content, filename="test.csv", by="alice")
    assert result["ok"] is False
    state = gp.get_full_state()
    task = next(t for t in state["tasks"] if t["id"] == "1.3_import")
    assert task["done"] is False


# ── Task 9: render_report ───────────────────────────────────────────────────


def test_render_report_markdown(tmp_home):
    gp.mark_task("1.1_view_doc", done=True, by="alice")
    gp.mark_task("1.2_download_tpl", done=True, by="alice", note="模板已下载")
    gp.update_note("1.3_import", note="关联 ZKREQ-130")

    md = gp.render_report()
    assert "# 实施助手进度报告" in md
    assert "**总进度**：2/12" in md
    assert "## 1. 业务线实体关系表整理" in md
    assert "- [x] 1.1_view_doc 查看文档说明 (by alice" in md
    assert "- [x] 1.2_download_tpl 下载模板" in md
    assert "模板已下载" in md
    assert "- [ ] 1.3_validate 校验文件" in md
    assert "关联 ZKREQ-130" in md
    assert "## 2. 知识库整理（故障FAQ） ⬜ 0/3" in md
    assert "## 3. 巡检+诊断技能验证 ⬜ 0/4" in md


def test_render_report_empty_state(tmp_home):
    md = gp.render_report()
    assert "**总进度**：0/12（0%）" in md
