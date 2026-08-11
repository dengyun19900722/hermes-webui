"""Tests for api/guidance_progress.py — 实施助手进度持久化与 API."""
import pytest
import time
import yaml
from pathlib import Path
from unittest.mock import patch

from api import asset_inventory as ai
from api import guidance_progress as gp


# 解析 fixtures 路径，避免 cwd 依赖（peer review: cwd-independent fixture access）
FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    """Redirect ~/.hermes to tmp_path for isolation.

    Patches both api.guidance_progress.get_active_hermes_home and
    api.asset_inventory.get_active_hermes_home so every module resolves to the
    same temp dir regardless of the real profile context.
    """
    fake_home = tmp_path / "hermes"
    fake_home.mkdir()
    monkeypatch.setattr(gp, "get_active_hermes_home", lambda: fake_home)
    monkeypatch.setattr(ai, "get_active_hermes_home", lambda: fake_home)
    return fake_home


# ── 原子写 ────────────────────────────────────────────────────────────────────


def test_atomic_write_creates_file(tmp_home):
    """_atomic_write_yaml should create a new file with valid YAML."""
    target = tmp_home / "guidance_progress.yaml"
    data = {"implementation": {"1.1_fill_entity_table": {"done": True, "by": "alice", "ts": 1, "note": ""}}}

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

    leftovers = list(tmp_home.glob("*.tmp"))
    assert leftovers == [], f"tmp 文件未清理: {leftovers}"
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
    assert list(tmp_home.glob("*.tmp")) == []


def test_atomic_write_catches_yaml_representer_error(tmp_home):
    """非 OSError 异常（如 YAML RepresenterError）也应被捕获并清理 tmp。"""
    target = tmp_home / "guidance_progress.yaml"
    target.write_text("existing: valid\n", encoding="utf-8")

    with patch("yaml.safe_dump", side_effect=yaml.YAMLError("can't represent object")):
        with pytest.raises(RuntimeError, match="guidance_progress.yaml write failed"):
            gp._atomic_write_yaml(target, {"implementation": {}})

    assert target.read_text(encoding="utf-8") == "existing: valid\n"
    assert list(tmp_home.glob("*.tmp")) == []


# ── load_progress / schema ────────────────────────────────────────────────────


def test_load_progress_returns_empty_when_missing(tmp_home):
    """First call when YAML doesn't exist should return empty schema, not raise."""
    result = gp.load_progress()

    assert result == {"implementation": {}, "schema_version": gp.SCHEMA_VERSION}


def test_load_progress_reads_existing(tmp_home):
    """Should read pre-existing YAML unchanged."""
    src = FIXTURES_DIR / "guidance_progress_initial.yaml"
    target = tmp_home / "guidance_progress.yaml"
    target.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    result = gp.load_progress()

    assert result["schema_version"] == gp.SCHEMA_VERSION
    assert "1.1_fill_entity_table" in result["implementation"]
    assert result["implementation"]["1.1_fill_entity_table"]["done"] is True


def test_load_progress_handles_non_mapping_yaml(tmp_home):
    """User-edited YAML with scalar/list content should return empty schema, not crash."""
    target = tmp_home / "guidance_progress.yaml"
    target.write_text("- this\n- is\n- a\n- list\n", encoding="utf-8")

    result = gp.load_progress()

    assert result == {"implementation": {}, "schema_version": gp.SCHEMA_VERSION}


def test_load_progress_handles_corrupted_yaml(tmp_home):
    """YAML parse error should not crash; return empty schema."""
    target = tmp_home / "guidance_progress.yaml"
    target.write_text("invalid: : yaml: : :\n  - broken\n", encoding="utf-8")

    result = gp.load_progress()

    assert result == {"implementation": {}, "schema_version": gp.SCHEMA_VERSION}


def test_load_progress_applies_defaults_to_partial_yaml(tmp_home):
    """YAML missing schema_version/implementation keys should get defaults."""
    target = tmp_home / "guidance_progress.yaml"
    target.write_text("other_key: 42\n", encoding="utf-8")

    result = gp.load_progress()

    assert result["schema_version"] == gp.SCHEMA_VERSION
    assert result["implementation"] == {}
    assert result["other_key"] == 42  # 未触及的数据保留


# ── task_id / metadata ────────────────────────────────────────────────────────


def test_validate_task_id_accepts_whitelisted():
    assert gp.validate_task_id("1.1_fill_entity_table") is True
    assert gp.validate_task_id("1.3_import_entities") is True
    assert gp.validate_task_id("3.4_record_result") is True


def test_validate_task_id_rejects_unknown():
    with pytest.raises(ValueError, match="unknown_task"):
        gp.validate_task_id("99.99_invalid")
    with pytest.raises(ValueError, match="unknown_task"):
        gp.validate_task_id("DROP TABLE")
    # 旧 id 已并入新步骤，应被拒绝
    with pytest.raises(ValueError, match="unknown_task"):
        gp.validate_task_id("1.1_view_doc")
    with pytest.raises(ValueError, match="unknown_task"):
        gp.validate_task_id("1.3_verify")


def test_get_task_metadata_returns_9_tasks():
    """Static metadata for the 9-step checklist, grouped by 3 subtasks."""
    tasks = gp.get_task_metadata()

    assert len(tasks) == 9
    groups = {t["group"] for t in tasks}
    assert groups == {1, 2, 3}

    by_group = {}
    for t in tasks:
        by_group.setdefault(t["group"], []).append(t)
    assert len(by_group[1]) == 2  # 业务线：填写实体关系表 + 上传导入实体表
    assert len(by_group[2]) == 3  # 知识库
    assert len(by_group[3]) == 4  # 验证

    assert by_group[1][0]["group_title"] == "业务线实体关系表整理"
    assert by_group[2][0]["group_title"] == "知识库整理（故障FAQ）"
    assert by_group[3][0]["group_title"] == "巡检+诊断技能验证"


def test_merge_with_metadata_includes_default_done_false():
    """Tasks never marked should default to done=False, by=None, ts=None, note=''."""
    progress = {"schema_version": gp.SCHEMA_VERSION, "implementation": {}}
    merged = gp.merge_with_metadata(progress)

    assert len(merged) == 9
    for task in merged:
        assert task["done"] is False
        assert task["by"] is None
        assert task["ts"] is None
        assert task["note"] == ""
        assert task["verified"] is False
        assert task["verification_type"] is None


def test_merge_with_metadata_preserves_done_state():
    """Already-done tasks keep their by/ts/note."""
    progress = {
        "schema_version": gp.SCHEMA_VERSION,
        "implementation": {
            "1.1_fill_entity_table": {"done": True, "by": "alice", "ts": 100, "note": "ok"},
        },
    }
    merged = gp.merge_with_metadata(progress)

    task_1_1 = next(t for t in merged if t["id"] == "1.1_fill_entity_table")
    assert task_1_1["done"] is True
    assert task_1_1["by"] == "alice"
    assert task_1_1["ts"] == 100


def test_merge_with_metadata_migrates_v1_no_verification_fields():
    """v1 数据缺验证字段应被补齐为默认值（不 crash）。"""
    progress = {
        "schema_version": 1,
        "implementation": {
            "1.3_import_entities": {"done": True, "by": "alice", "ts": 100, "note": ""},
        },
    }
    merged = gp.merge_with_metadata(progress)
    task = next(t for t in merged if t["id"] == "1.3_import_entities")
    assert task["done"] is True
    assert task["verified"] is False
    assert task["verification_type"] is None
    assert task["evidence"] == ""


# ── Task 4: mark_task + update_note ──────────────────────────────────────────


def test_mark_task_done_requires_note_for_manual(tmp_home):
    """手动勾选未自动验证的任务，必须填写备注，否则拒绝。"""
    with pytest.raises(ValueError, match="manual_note_required"):
        gp.mark_task("1.1_fill_entity_table", done=True, by="alice", note="")


def test_mark_task_done_with_note(tmp_home):
    """带备注的手动标记应成功，verification_type 为 manual。"""
    before = int(time.time())
    task = gp.mark_task("1.1_fill_entity_table", done=True, by="alice", note="已填写实体关系表")
    after = int(time.time())
    assert task["done"] is True
    assert task["by"] == "alice"
    assert before <= task["ts"] <= after
    assert task["note"] == "已填写实体关系表"
    assert task["verification_type"] == "manual"

    persisted = gp.load_progress()
    assert persisted["implementation"]["1.1_fill_entity_table"]["done"] is True
    assert persisted["implementation"]["1.1_fill_entity_table"]["verification_type"] == "manual"


def test_mark_task_undone_clears_by_and_ts(tmp_home):
    gp.mark_task("1.1_fill_entity_table", done=True, by="alice", note="kept")
    task = gp.mark_task("1.1_fill_entity_table", done=False, by="alice", note="kept")
    assert task["done"] is False
    assert task["by"] is None
    assert task["ts"] is None
    assert task["note"] == "kept"
    assert task["verified"] is False


def test_mark_task_unknown_raises(tmp_home):
    with pytest.raises(ValueError, match="unknown_task"):
        gp.mark_task("bogus", done=True, by="alice")


def test_update_note_does_not_change_done(tmp_home):
    gp.mark_task("1.1_fill_entity_table", done=True, by="alice", note="init")
    task = gp.update_note("1.1_fill_entity_table", note="关联 ZKREQ-130")
    assert task["done"] is True
    assert task["by"] == "alice"
    assert task["note"] == "关联 ZKREQ-130"


def test_update_note_allows_empty(tmp_home):
    gp.update_note("1.1_fill_entity_table", note="something")
    task = gp.update_note("1.1_fill_entity_table", note="")
    assert task["note"] == ""


def test_mark_task_concurrent_writes_safe(tmp_home):
    gp.mark_task("1.1_fill_entity_table", done=True, by="alice", note="n1")
    gp.mark_task("2.1_view_template", done=True, by="bob", note="n2")
    persisted = gp.load_progress()
    assert persisted["implementation"]["1.1_fill_entity_table"]["by"] == "alice"
    assert persisted["implementation"]["2.1_view_template"]["by"] == "bob"


# ── Task 5: reset_progress ──────────────────────────────────────────────────


def test_reset_progress_clears_all(tmp_home):
    gp.mark_task("1.1_fill_entity_table", done=True, by="alice", note="n1")
    gp.mark_task("2.1_view_template", done=True, by="alice", note="n2")
    gp.reset_progress()
    result = gp.load_progress()
    assert result["implementation"] == {}


def test_reset_progress_clears_inventory(tmp_home):
    """重置进度应同时清空资产库存（1.3 相关的业务实体落盘数据）。"""
    content = (FIXTURES_DIR / "business_entities_valid.csv").read_text(encoding="utf-8")
    gp.import_business_entities(content, filename="test.csv", by="alice")
    assert ai.count_hosts() > 0
    gp.reset_progress()
    assert ai.count_hosts() == 0


# ── Task 6: get_full_state ──────────────────────────────────────────────────


def test_get_full_state_returns_schema_and_summary(tmp_home):
    gp.mark_task("1.1_fill_entity_table", done=True, by="alice", note="n1")
    state = gp.get_full_state()
    assert state["schema_version"] == gp.SCHEMA_VERSION
    assert "deployment_id" in state
    assert "first_seen_at" in state
    assert len(state["tasks"]) == 9
    assert state["summary"]["total"] == 9
    assert state["summary"]["done"] == 1
    assert state["summary"]["by_group"] == {"1": 1, "2": 0, "3": 0}


def test_get_full_state_first_seen_persists(tmp_home):
    state1 = gp.get_full_state()
    state2 = gp.get_full_state()
    assert state1["first_seen_at"] == state2["first_seen_at"]
    assert state1["deployment_id"] == state2["deployment_id"]


def test_get_full_state_omits_current_user_by_default(tmp_home):
    """未传入 current_user 时，响应里不应出现 current_user 字段（兼容旧前端）。"""
    state = gp.get_full_state()
    assert "current_user" not in state


def test_get_full_state_includes_current_user(tmp_home):
    """修复 bug：GET 响应必须带当前用户名，否则前端永远显示 'unknown' 直到有任务完成。

    回归：在未标记任何 task 时，前端用 data.tasks[].by 取不到用户名，会显示 'unknown'。
    现在后端直接通过 current_user 字段返回用户名，前端优先读它。
    """
    state = gp.get_full_state(current_user="alice")
    assert state["current_user"] == "alice"

    # 即便后续 mark_task 触发了 by 改变，前端仍以响应里的 current_user 为准
    gp.mark_task("1.1_fill_entity_table", done=True, by="bob", note="n1")
    state2 = gp.get_full_state(current_user="alice")
    assert state2["current_user"] == "alice"
    # 但任务本身的 by 是真实完成者
    t11 = next(t for t in state2["tasks"] if t["id"] == "1.1_fill_entity_table")
    assert t11["by"] == "bob"


def test_get_full_state_current_user_empty_string(tmp_home):
    """current_user 传空串时应被保留为 ''（由前端兜底显示 'unknown'）。"""
    state = gp.get_full_state(current_user="")
    assert state["current_user"] == ""


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


# ── Task 8: import_business_entities（真实落盘）─────────────────────────────


def test_import_happy_path_marks_task_done(tmp_home):
    content = (FIXTURES_DIR / "business_entities_valid.csv").read_text(encoding="utf-8")
    result = gp.import_business_entities(content, filename="test.csv", by="alice")
    assert result["ok"] is True
    assert result["imported_rows"] == 5
    assert result["task_updated"] == "1.3_import_entities"
    # 真实落盘
    assert ai.count_hosts() > 0
    state = gp.get_full_state()
    task = next(t for t in state["tasks"] if t["id"] == "1.3_import_entities")
    assert task["done"] is True
    assert task["by"] == "alice"
    assert task["verification_type"] == "auto"
    assert task["verified"] is True


def test_import_validation_failure_no_task_update(tmp_home):
    content = (FIXTURES_DIR / "business_entities_bad_ip.csv").read_text(encoding="utf-8")
    result = gp.import_business_entities(content, filename="test.csv", by="alice")
    assert result["ok"] is False
    state = gp.get_full_state()
    task = next(t for t in state["tasks"] if t["id"] == "1.3_import_entities")
    assert task["done"] is False


# ── Task 10: 验证器（自主验证）───────────────────────────────────────────────


def test_check_task_not_verifiable_returns_available_false(tmp_home):
    """无验证能力的任务（如填写实体关系表）应返回 available=False。"""
    result = gp.check_task("1.1_fill_entity_table")
    assert result["passed"] is False
    assert result["available"] is False


def test_check_task_1_3_import_before_data(tmp_home):
    """未导入任何实体时，1.3_import_entities 验证应未通过。"""
    result = gp.check_task("1.3_import_entities")
    assert result["passed"] is False


def test_check_task_1_3_import_after_data(tmp_home):
    """导入实体后，1.3_import_entities 验证应通过。"""
    content = (FIXTURES_DIR / "business_entities_valid.csv").read_text(encoding="utf-8")
    gp.import_business_entities(content, filename="test.csv", by="alice")
    result = gp.check_task("1.3_import_entities")
    assert result["passed"] is True


def test_run_verification_passes_and_marks(tmp_home):
    """验证通过后应自动标记任务 done=True，verification_type=auto。"""
    content = (FIXTURES_DIR / "business_entities_valid.csv").read_text(encoding="utf-8")
    gp.import_business_entities(content, filename="test.csv", by="alice")
    result = gp.run_verification("1.3_import_entities", by="alice")
    assert result["passed"] is True
    assert result["task"]["done"] is True
    assert result["task"]["verification_type"] == "auto"


def test_run_verification_not_passed_does_not_mark(tmp_home):
    """验证未通过时不应标记任务。"""
    result = gp.run_verification("1.3_import_entities", by="alice")
    assert result["passed"] is False
    assert result["task"] is None
    state = gp.get_full_state()
    task = next(t for t in state["tasks"] if t["id"] == "1.3_import_entities")
    assert task["done"] is False


def test_manual_mark_on_verifiable_task_requires_note(tmp_home):
    """有自动验证能力的任务，若未验证而手动勾选也必须填备注。"""
    with pytest.raises(ValueError, match="manual_note_required"):
        gp.mark_task("1.3_import_entities", done=True, by="alice", note="")


# ── Task 9: render_report ───────────────────────────────────────────────────


def test_render_report_markdown(tmp_home):
    gp.mark_task("1.1_fill_entity_table", done=True, by="alice", note="已填写")
    gp.mark_task("2.1_view_template", done=True, by="alice", note="已查看模板")

    md = gp.render_report()
    assert "# 实施助手进度报告" in md
    assert "**总进度**：2/9" in md
    assert "## 1. 业务线实体关系表整理" in md
    assert "- [x] 1.1_fill_entity_table 填写实体关系表 (手动标记 by alice" in md
    assert "已填写" in md
    assert "- [ ] 1.3_import_entities 上传导入实体表" in md
    assert "## 2. 知识库整理（故障FAQ） ⬜ 1/3" in md
    assert "## 3. 巡检+诊断技能验证 ⬜ 0/4" in md


def test_render_report_auto_verified(tmp_home):
    """自动验证通过的任务，报告中应标记为自动验证并含证据。"""
    content = (FIXTURES_DIR / "business_entities_valid.csv").read_text(encoding="utf-8")
    gp.import_business_entities(content, filename="test.csv", by="alice")
    md = gp.render_report()
    assert "自动验证 by alice" in md


def test_render_report_empty_state(tmp_home):
    md = gp.render_report()
    assert "**总进度**：0/9（0%）" in md
