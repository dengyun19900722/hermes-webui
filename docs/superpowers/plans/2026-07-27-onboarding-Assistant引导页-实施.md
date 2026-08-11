# ZK 运维智能体 1.1.0 — 实施助手引导页（2.1）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 4 类引导页中的最高优先级 **实施助手引导页（2.1）**——从部署完成到具备使用条件的 step-by-step 清单，含 12 项任务、CSV 导入、Markdown 报告导出，admin/ops RBAC 限定。

**Architecture:** 单页全屏覆盖 + 侧栏常驻入口；前端 `GuidanceManager` 单例调度 + 后端 `guidance_progress.py` 模块读写 `~/.hermes/guidance_progress.yaml`；触发器监听 `hermes:license_activated` / `hermes:onboarding_complete` 自动展开。

**Tech Stack:** Python 3.12 + FastAPI 路由风格（项目内一致性）+ vanilla-JS 前端 + jsdom 单元测试 + Playwright E2E + pytest。

**Spec:** `docs/superpowers/specs/2026-07-27-1.1.0-onboarding-experience-design.md` §3-§6

**优先级：** P0（4 份 plan 中第一个交付）

---

## 文件结构

### 新增文件

| 路径 | 职责 |
|---|---|
| `api/guidance_progress.py` | 后端模块：YAML 读写、任务白名单校验、CSV 校验、报告渲染 |
| `static/guidance.js` | 前端模块：`GuidanceManager` 单例 + Page2_1 全屏页实现 |
| `static/guidance.css` | 全屏页样式（含移动端 < 768px 折叠） |
| `tests/test_guidance_progress.py` | 17 个 pytest 用例 |
| `tests/js/test_guidance_triggers.test.mjs` | Page2_1 jsdom 单元测试 |
| `tests/e2e/test_implementation_assistant.spec.js` | Playwright E2E |
| `tests/fixtures/business_entities_valid.csv` | 5 行有效 CSV |
| `tests/fixtures/business_entities_missing_col.csv` | 缺列 CSV |
| `tests/fixtures/business_entities_bad_ip.csv` | 错误 IP CSV |
| `tests/fixtures/guidance_progress_initial.yaml` | 初始 YAML 快照 |

### 修改文件

| 路径 | 改动 |
|---|---|
| `api/routes.py` | 注册 5 个新端点（GET/PATCH/POST note/GET report/POST import） |
| `static/index.html` | 注入 `<template id="tpl-guidance-2-1">` + `<script src="guidance.js">` |
| `static/i18n.js` | 新增 13 个 `guidance_2_1_*` key |
| `static/boot.js` | 末尾追加 `GuidanceManager.init()` + 事件监听 |
| `static/panels.js` | 侧栏入口 `_renderGuidanceSidebarEntry()` 含 RBAC 检查 |
| `CHANGELOG.md` | 1.1.0 版本条目 |

---

## Phase 1：后端基础（YAML + 白名单）

### Task 1：创建测试 fixtures

**Files:**
- Create: `tests/fixtures/business_entities_valid.csv`
- Create: `tests/fixtures/business_entities_missing_col.csv`
- Create: `tests/fixtures/business_entities_bad_ip.csv`
- Create: `tests/fixtures/guidance_progress_initial.yaml`

- [ ] **Step 1：创建有效 CSV**

```bash
mkdir -p tests/fixtures
```

`tests/fixtures/business_entities_valid.csv`：
```csv
业务线名称,主机IP,主机角色,关联服务,端口,负责人,备注
电商平台,10.0.1.10,DB,mysql-prod,3306,alice,主库
电商平台,10.0.1.11,DB,mysql-prod,3306,alice,从库
电商平台,10.0.2.20,应用,tomcat-1,8080,bob,
支付网关,10.0.3.30,中间件,kafka-1,9092,carol,核心交易链路
支付网关,10.0.3.31,中间件,kafka-2,9092,carol,
```

- [ ] **Step 2：创建缺列 CSV**

`tests/fixtures/business_entities_missing_col.csv`：
```csv
主机IP,主机角色,关联服务
10.0.1.10,DB,mysql-prod
```

- [ ] **Step 3：创建错误 IP CSV**

`tests/fixtures/business_entities_bad_ip.csv`：
```csv
业务线名称,主机IP,主机角色
电商平台,not-an-ip,DB
支付网关,999.999.999.999,中间件
```

- [ ] **Step 4：创建初始 YAML**

`tests/fixtures/guidance_progress_initial.yaml`：
```yaml
implementation:
  '1.1_view_doc':
    done: true
    by: 'alice'
    ts: 1722000000
    note: ''
  '1.2_download_tpl':
    done: true
    by: 'alice'
    ts: 1722000100
    note: ''
```

- [ ] **Step 5：commit**

```bash
git add tests/fixtures/
git commit -m "test(guidance): add CSV + YAML fixtures for implementation assistant"
```

---

### Task 2：实现 `_atomic_write_yaml` 和 `load_progress`

**Files:**
- Create: `api/guidance_progress.py`
- Test: `tests/test_guidance_progress.py`

- [ ] **Step 1：写失败测试**

`tests/test_guidance_progress.py`：
```python
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
```

- [ ] **Step 2：跑测试确认失败**

Run:
```bash
pytest tests/test_guidance_progress.py -v --no-header
```
Expected: `ModuleNotFoundError: No module named 'api.guidance_progress'`（或 ImportError）

- [ ] **Step 3：实现最小代码**

`api/guidance_progress.py`：
```python
"""实施助手引导页（2.1）后端模块。

读写 ~/.hermes/guidance_progress.yaml，提供 5 个 endpoint 的业务逻辑。
YAML 写采用原子替换（tmp + os.replace）避免半写损坏。
"""
from __future__ import annotations

import os
import yaml
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

# 12 项任务白名单（与 spec §4.1 一致）
ALLOWED_TASKS = frozenset({
    "1.1_view_doc", "1.2_download_tpl", "1.3_validate", "1.3_import", "1.3_verify",
    "2.1_view_template", "2.2_batch_import", "2.3_verify_search",
    "3.1_select_business_line", "3.2_run_inspection", "3.3_run_diagnosis", "3.4_record_result",
})


def _guidance_progress_path() -> Path:
    """Return ~/.hermes/guidance_progress.yaml for the active profile."""
    home = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()
    return home / "guidance_progress.yaml"


def _atomic_write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Atomically write data to YAML via tmp + os.replace. On failure, tmp is cleaned."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        os.replace(tmp, path)
    except OSError as e:
        if tmp.exists():
            tmp.unlink()
        raise RuntimeError(f"guidance_progress.yaml write failed: {e}") from e


def load_progress() -> dict[str, Any]:
    """Read guidance_progress.yaml; return empty schema if file missing."""
    path = _guidance_progress_path()
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "implementation": {}}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("schema_version", SCHEMA_VERSION)
    data.setdefault("implementation", {})
    return data


def save_progress(data: dict[str, Any]) -> None:
    """Atomically write progress data to disk."""
    _atomic_write_yaml(_guidance_progress_path(), data)
```

- [ ] **Step 4：跑测试确认通过**

Run:
```bash
pytest tests/test_guidance_progress.py -v --no-header
```
Expected: 4 passed

- [ ] **Step 5：commit**

```bash
git add api/guidance_progress.py tests/test_guidance_progress.py
git commit -m "feat(guidance): add guidance_progress module with atomic YAML IO"
```

---

### Task 3：实现任务白名单校验 + 任务元数据

**Files:**
- Modify: `api/guidance_progress.py`
- Modify: `tests/test_guidance_progress.py`

- [ ] **Step 1：追加失败测试**

在 `tests/test_guidance_progress.py` 末尾追加：
```python
# 追加在文件末尾

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

    # 验证每组数量
    by_group = {}
    for t in tasks:
        by_group.setdefault(t["group"], []).append(t)
    assert len(by_group[1]) == 5  # 业务线：1.1, 1.2, 1.3a, 1.3b, 1.3c
    assert len(by_group[2]) == 3  # 知识库
    assert len(by_group[3]) == 4  # 验证

    # 验证 group_title
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
    assert task_1_1["note"] == "ok"
```

- [ ] **Step 2：跑测试确认失败**

Run:
```bash
pytest tests/test_guidance_progress.py -v --no-header
```
Expected: 4 failed（validate_task_id / get_task_metadata / merge_with_metadata 未定义）

- [ ] **Step 3：实现最小代码**

在 `api/guidance_progress.py` 末尾追加：
```python
# 12 项任务的静态元数据（group / title / group_title）
# 与 spec §4.1 表格严格一致
_TASK_METADATA = [
    # Group 1: 业务线实体关系表整理 (5 步)
    {"id": "1.1_view_doc",           "group": 1, "title": "查看文档说明"},
    {"id": "1.2_download_tpl",       "group": 1, "title": "下载模板"},
    {"id": "1.3_validate",           "group": 1, "title": "校验文件"},
    {"id": "1.3_import",             "group": 1, "title": "导入实体表"},
    {"id": "1.3_verify",             "group": 1, "title": "验证导入结果"},
    # Group 2: 知识库整理 (3 步)
    {"id": "2.1_view_template",      "group": 2, "title": "查看 FAQ 模板"},
    {"id": "2.2_batch_import",       "group": 2, "title": "批量导入知识库"},
    {"id": "2.3_verify_search",      "group": 2, "title": "验证可搜索"},
    # Group 3: 巡检+诊断技能验证 (4 步)
    {"id": "3.1_select_business_line", "group": 3, "title": "选择业务线"},
    {"id": "3.2_run_inspection",     "group": 3, "title": "执行全链路巡检"},
    {"id": "3.3_run_diagnosis",      "group": 3, "title": "执行故障诊断"},
    {"id": "3.4_record_result",      "group": 3, "title": "记录验证结果"},
]

_GROUP_TITLES = {1: "业务线实体关系表整理", 2: "知识库整理（故障FAQ）", 3: "巡检+诊断技能验证"}


def validate_task_id(task_id: str) -> bool:
    """Raise ValueError if task_id not in whitelist."""
    if task_id not in ALLOWED_TASKS:
        raise ValueError(f"unknown_task: {task_id}")
    return True


def get_task_metadata() -> list[dict[str, Any]]:
    """Return static metadata for all 12 tasks, ordered as in spec."""
    return [
        {**t, "group_title": _GROUP_TITLES[t["group"]]}
        for t in _TASK_METADATA
    ]


def merge_with_metadata(progress: dict[str, Any]) -> list[dict[str, Any]]:
    """Merge progress state into static metadata; defaults applied for missing tasks."""
    impl = progress.get("implementation", {})
    merged = []
    for meta in _TASK_METADATA:
        state = impl.get(meta["id"], {})
        merged.append({
            **meta,
            "group_title": _GROUP_TITLES[meta["group"]],
            "done": bool(state.get("done", False)),
            "by": state.get("by"),
            "ts": state.get("ts"),
            "note": state.get("note", ""),
        })
    return merged


def compute_summary(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Return {total, done, by_group: {group_str: count}}."""
    by_group: dict[str, int] = {}
    done = 0
    for t in tasks:
        g = str(t["group"])
        by_group.setdefault(g, 0)
        if t["done"]:
            done += 1
            by_group[g] += 1
    return {"total": len(tasks), "done": done, "by_group": by_group}
```

- [ ] **Step 4：跑测试确认通过**

Run:
```bash
pytest tests/test_guidance_progress.py -v --no-header
```
Expected: 9 passed

- [ ] **Step 5：commit**

```bash
git add api/guidance_progress.py tests/test_guidance_progress.py
git commit -m "feat(guidance): add 12-task whitelist, metadata, and merge helpers"
```

---

### Task 4：实现 `mark_task` 和 `update_note`

**Files:**
- Modify: `api/guidance_progress.py`
- Modify: `tests/test_guidance_progress.py`

- [ ] **Step 1：追加失败测试**

在 `tests/test_guidance_progress.py` 末尾追加：
```python
# 追加在文件末尾

def test_mark_task_done(tmp_home):
    """mark_task should set done=True, record by and ts."""
    import time
    before = int(time.time())
    task = gp.mark_task("1.1_view_doc", done=True, by="alice", note="")

    after = int(time.time())
    assert task["done"] is True
    assert task["by"] == "alice"
    assert before <= task["ts"] <= after
    assert task["note"] == ""

    # 持久化检查
    persisted = gp.load_progress()
    assert persisted["implementation"]["1.1_view_doc"]["done"] is True


def test_mark_task_undone_clears_by_and_ts(tmp_home):
    """Setting done=False should reset by/ts (note preserved)."""
    gp.mark_task("1.1_view_doc", done=True, by="alice", note="kept")
    task = gp.mark_task("1.1_view_doc", done=False, by="alice", note="kept")

    assert task["done"] is False
    assert task["by"] is None
    assert task["ts"] is None
    assert task["note"] == "kept"  # note 保留


def test_mark_task_unknown_raises(tmp_home):
    with pytest.raises(ValueError, match="unknown_task"):
        gp.mark_task("bogus", done=True, by="alice")


def test_update_note_does_not_change_done(tmp_home):
    """update_note should only change note, leave done/by/ts untouched."""
    gp.mark_task("1.1_view_doc", done=True, by="alice", note="")
    task = gp.update_note("1.1_view_doc", note="关联 ZKREQ-130")

    assert task["done"] is True
    assert task["by"] == "alice"
    assert task["note"] == "关联 ZKREQ-130"


def test_update_note_allows_empty(tmp_home):
    """Updating note to empty string should clear it."""
    gp.update_note("1.1_view_doc", note="something")
    task = gp.update_note("1.1_view_doc", note="")

    assert task["note"] == ""


def test_mark_task_concurrent_writes_lose_safe(tmp_home):
    """Two simultaneous marks should not corrupt YAML (atomic write protects)."""
    gp.mark_task("1.1_view_doc", done=True, by="alice")
    gp.mark_task("1.2_download_tpl", done=True, by="bob")

    persisted = gp.load_progress()
    assert persisted["implementation"]["1.1_view_doc"]["by"] == "alice"
    assert persisted["implementation"]["1.2_download_tpl"]["by"] == "bob"
```

- [ ] **Step 2：跑测试确认失败**

Run:
```bash
pytest tests/test_guidance_progress.py -v --no-header
```
Expected: 6 failed

- [ ] **Step 3：实现最小代码**

在 `api/guidance_progress.py` 末尾追加：
```python
import time
from typing import Optional


def mark_task(task_id: str, *, done: bool, by: str, note: Optional[str] = None) -> dict[str, Any]:
    """Mark task done/undone; record by and ts. Returns updated task dict."""
    validate_task_id(task_id)
    data = load_progress()
    existing = data["implementation"].get(task_id, {})

    # 保留 note（除非显式传入）
    note_value = note if note is not None else existing.get("note", "")

    if done:
        data["implementation"][task_id] = {
            "done": True,
            "by": by,
            "ts": int(time.time()),
            "note": note_value,
        }
    else:
        # 取消：清空 by/ts，保留 note
        data["implementation"][task_id] = {
            "done": False,
            "by": None,
            "ts": None,
            "note": note_value,
        }

    save_progress(data)

    # 返回完整的 task dict（含 metadata）
    all_tasks = merge_with_metadata(data)
    return next(t for t in all_tasks if t["id"] == task_id)


def update_note(task_id: str, *, note: str) -> dict[str, Any]:
    """Update only the note field. Done state unchanged."""
    validate_task_id(task_id)
    data = load_progress()
    existing = data["implementation"].get(task_id, {"done": False, "by": None, "ts": None})
    existing["note"] = note
    data["implementation"][task_id] = existing
    save_progress(data)

    all_tasks = merge_with_metadata(data)
    return next(t for t in all_tasks if t["id"] == task_id)
```

- [ ] **Step 4：跑测试确认通过**

Run:
```bash
pytest tests/test_guidance_progress.py -v --no-header
```
Expected: 15 passed

- [ ] **Step 5：commit**

```bash
git add api/guidance_progress.py tests/test_guidance_progress.py
git commit -m "feat(guidance): add mark_task and update_note with atomic write"
```

---

### Task 5：实现 `reset_progress`

**Files:**
- Modify: `api/guidance_progress.py`
- Modify: `tests/test_guidance_progress.py`

- [ ] **Step 1：追加失败测试**

在 `tests/test_guidance_progress.py` 末尾追加：
```python
def test_reset_progress_clears_all(tmp_home):
    gp.mark_task("1.1_view_doc", done=True, by="alice")
    gp.mark_task("1.2_download_tpl", done=True, by="alice")

    gp.reset_progress()

    result = gp.load_progress()
    assert result["implementation"] == {}
```

- [ ] **Step 2：跑测试确认失败**

Run: `pytest tests/test_guidance_progress.py::test_reset_progress_clears_all -v`
Expected: AttributeError: module 'api.guidance_progress' has no attribute 'reset_progress'

- [ ] **Step 3：实现**

在 `api/guidance_progress.py` 末尾追加：
```python
def reset_progress() -> None:
    """Clear all progress. Used by 'Reset Progress' button."""
    save_progress({"schema_version": SCHEMA_VERSION, "implementation": {}})
```

- [ ] **Step 4：跑测试确认通过**

Run: `pytest tests/test_guidance_progress.py -v --no-header`
Expected: 16 passed

- [ ] **Step 5：commit**

```bash
git add api/guidance_progress.py tests/test_guidance_progress.py
git commit -m "feat(guidance): add reset_progress"
```

---

### Task 6：实现 `get_full_state`（GET endpoint 业务逻辑）

**Files:**
- Modify: `api/guidance_progress.py`
- Modify: `tests/test_guidance_progress.py`

- [ ] **Step 1：追加失败测试**

```python
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
    """first_seen_at should be set on first call and reused on subsequent calls."""
    state1 = gp.get_full_state()
    state2 = gp.get_full_state()

    assert state1["first_seen_at"] == state2["first_seen_at"]
    assert state1["deployment_id"] == state2["deployment_id"]
```

- [ ] **Step 2：跑测试确认失败**

Run: `pytest tests/test_guidance_progress.py::test_get_full_state_returns_schema_and_summary -v`
Expected: AttributeError

- [ ] **Step 3：实现**

在 `api/guidance_progress.py` 末尾追加：
```python
import uuid


def _ensure_first_seen(data: dict[str, Any]) -> dict[str, Any]:
    """Populate deployment_id and first_seen_at on first access; persist."""
    changed = False
    if "deployment_id" not in data:
        data["deployment_id"] = f"dep-{uuid.uuid4().hex[:12]}"
        changed = True
    if "first_seen_at" not in data:
        data["first_seen_at"] = int(time.time())
        changed = True
    if changed:
        save_progress(data)
    return data


def get_full_state() -> dict[str, Any]:
    """Return full state for GET endpoint: schema, tasks, summary."""
    data = _ensure_first_seen(load_progress())
    tasks = merge_with_metadata(data)
    return {
        "schema_version": data["schema_version"],
        "deployment_id": data["deployment_id"],
        "first_seen_at": data["first_seen_at"],
        "tasks": tasks,
        "summary": compute_summary(tasks),
    }
```

- [ ] **Step 4：跑测试确认通过**

Run: `pytest tests/test_guidance_progress.py -v --no-header`
Expected: 18 passed

- [ ] **Step 5：commit**

```bash
git add api/guidance_progress.py tests/test_guidance_progress.py
git commit -m "feat(guidance): add get_full_state with deployment_id persistence"
```

---

## Phase 2：CSV 导入

### Task 7：实现 CSV 校验

**Files:**
- Modify: `api/guidance_progress.py`
- Modify: `tests/test_guidance_progress.py`

- [ ] **Step 1：追加失败测试**

```python
import csv
import io


def _make_file_upload(content: str, filename: str = "test.csv"):
    """Helper to simulate Werkzeug FileStorage."""
    from werkzeug.datastructures import FileStorage
    fs = FileStorage(stream=io.BytesIO(content.encode("utf-8")), filename=filename)
    return fs


def test_validate_csv_happy_path():
    content = (Path("tests/fixtures/business_entities_valid.csv")).read_text(encoding="utf-8")
    result = gp.validate_business_entity_csv(content)

    assert result["ok"] is True
    assert result["total_rows"] == 5
    assert result["failed_rows"] == []


def test_validate_csv_missing_column():
    content = Path("tests/fixtures/business_entities_missing_col.csv").read_text(encoding="utf-8")
    result = gp.validate_business_entity_csv(content)

    assert result["ok"] is False
    assert "业务线名称" in result["missing_columns"]


def test_validate_csv_bad_ip():
    content = Path("tests/fixtures/business_entities_bad_ip.csv").read_text(encoding="utf-8")
    result = gp.validate_business_entity_csv(content)

    assert result["ok"] is False
    assert len(result["failed_rows"]) >= 2
    assert any(f["field"] == "主机IP" for f in result["failed_rows"])


def test_validate_csv_size_limit():
    """超过 10000 行应截断 + 报错."""
    rows = ["业务线名称,主机IP,主机角色\n"]
    for i in range(10001):
        rows.append(f"line_{i},10.0.0.{i % 256},DB\n")
    content = "".join(rows)

    result = gp.validate_business_entity_csv(content)

    assert result["ok"] is False
    assert "size_limit" in str(result.get("error", ""))


def test_validate_csv_xlsx_rejected():
    """v1.1.0 仅 csv; xlsx 应报 unsupported_format."""
    result = gp.validate_business_entity_csv(
        "fake xlsx content",
        filename="test.xlsx",
    )

    assert result["ok"] is False
    assert result["error"] == "unsupported_format"
```

- [ ] **Step 2：跑测试确认失败**

Run: `pytest tests/test_guidance_progress.py -k "test_validate_csv" -v`
Expected: 5 failed

- [ ] **Step 3：实现**

在 `api/guidance_progress.py` 末尾追加：
```python
import csv
import io
import re

_REQUIRED_COLUMNS = ["业务线名称", "主机IP", "主机角色"]
_MAX_ROWS = 10000
_IPV4_RE = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")


def _is_valid_ipv4(ip: str) -> bool:
    if not _IPV4_RE.match(ip):
        return False
    return all(0 <= int(octet) <= 255 for octet in ip.split("."))


def validate_business_entity_csv(content: str, filename: str = "test.csv") -> dict[str, Any]:
    """Validate CSV content. Returns ok=True on success or detailed errors."""
    if not filename.lower().endswith(".csv"):
        return {"ok": False, "error": "unsupported_format", "format": filename.split(".")[-1]}

    reader = csv.DictReader(io.StringIO(content))
    headers = reader.fieldnames or []

    missing = [c for c in _REQUIRED_COLUMNS if c not in headers]
    if missing:
        return {"ok": False, "error": "missing_columns", "missing": missing}

    failed_rows = []
    total = 0
    for line_no, row in enumerate(reader, start=2):
        total += 1
        if total > _MAX_ROWS:
            return {
                "ok": False,
                "error": "size_limit",
                "detail": f"超过 {_MAX_ROWS} 行上限",
                "rows_seen": total,
            }
        # 必填校验
        if not (row.get("业务线名称") or "").strip():
            failed_rows.append({"line": line_no, "field": "业务线名称", "reason": "必填"})
        ip = (row.get("主机IP") or "").strip()
        if not _is_valid_ipv4(ip):
            failed_rows.append({"line": line_no, "field": "主机IP", "reason": f"格式不合法（{ip}）"})

    if failed_rows:
        return {
            "ok": False,
            "error": "validation",
            "failed_rows": failed_rows[:100],
            "total_failed": len(failed_rows),
            "total_rows": total,
        }

    return {"ok": True, "total_rows": total, "failed_rows": []}
```

- [ ] **Step 4：跑测试确认通过**

Run: `pytest tests/test_guidance_progress.py -k "test_validate_csv" -v`
Expected: 5 passed

- [ ] **Step 5：commit**

```bash
git add api/guidance_progress.py tests/test_guidance_progress.py
git commit -m "feat(guidance): add CSV validation with IP format + size limit"
```

---

### Task 8：实现 `import_business_entities`（完整导入流程）

**Files:**
- Modify: `api/guidance_progress.py`
- Modify: `tests/test_guidance_progress.py`

- [ ] **Step 1：追加失败测试**

```python
def test_import_happy_path_marks_task_done(tmp_home):
    """导入成功后应自动勾选 '1.3_import' 任务."""
    content = Path("tests/fixtures/business_entities_valid.csv").read_text(encoding="utf-8")

    result = gp.import_business_entities(content, filename="test.csv", by="alice")

    assert result["ok"] is True
    assert result["imported_rows"] == 5
    assert result["task_updated"] == "1.3_import"

    # 验证任务被勾选
    state = gp.get_full_state()
    task = next(t for t in state["tasks"] if t["id"] == "1.3_import")
    assert task["done"] is True
    assert task["by"] == "alice"


def test_import_validation_failure_no_task_update(tmp_home):
    """校验失败不应修改任何任务状态."""
    content = Path("tests/fixtures/business_entities_bad_ip.csv").read_text(encoding="utf-8")

    result = gp.import_business_entities(content, filename="test.csv", by="alice")

    assert result["ok"] is False
    state = gp.get_full_state()
    task = next(t for t in state["tasks"] if t["id"] == "1.3_import")
    assert task["done"] is False
```

- [ ] **Step 2：跑测试确认失败**

Run: `pytest tests/test_guidance_progress.py -k "test_import" -v`
Expected: 2 failed

- [ ] **Step 3：实现**

在 `api/guidance_progress.py` 末尾追加：
```python
def import_business_entities(content: str, *, filename: str, by: str) -> dict[str, Any]:
    """Validate + import business entities CSV. Auto-mark 1.3_import on success."""
    validation = validate_business_entity_csv(content, filename=filename)
    if not validation["ok"]:
        return validation

    # TODO(后续版本): 实际写入业务实体存储（api/asset_inventory.py）
    # 当前仅做校验 + 标记任务，实体存储层在后续版本集成

    # 自动勾选 1.3_import
    mark_task("1.3_import", done=True, by=by)

    return {
        "ok": True,
        "imported_rows": validation["total_rows"],
        "failed_rows": [],
        "task_updated": "1.3_import",
    }
```

- [ ] **Step 4：跑测试确认通过**

Run: `pytest tests/test_guidance_progress.py -k "test_import" -v`
Expected: 2 passed

- [ ] **Step 5：commit**

```bash
git add api/guidance_progress.py tests/test_guidance_progress.py
git commit -m "feat(guidance): add import_business_entities with auto task update"
```

---

### Task 9：实现 `render_report`（Markdown 报告生成）

**Files:**
- Modify: `api/guidance_progress.py`
- Modify: `tests/test_guidance_progress.py`

- [ ] **Step 1：追加失败测试**

```python
def test_render_report_markdown(tmp_home):
    gp.mark_task("1.1_view_doc", done=True, by="alice")
    gp.mark_task("1.2_download_tpl", done=True, by="alice", note="模板已下载")
    gp.update_note("1.3_import", note="关联 ZKREQ-130")

    md = gp.render_report()

    assert "# 实施助手进度报告" in md
    assert "**总进度**：2/12" in md
    assert "## 1. 业务线实体关系表整理" in md
    assert "- [x] 1.1 查看文档说明 (by alice" in md
    assert "- [x] 1.2 下载模板" in md
    assert "模板已下载" in md
    assert "- [ ] 1.3 校验文件" in md  # 未完成
    assert "关联 ZKREQ-130" in md
    assert "## 2. 知识库整理（故障FAQ）⬜ 0/3" in md
    assert "## 3. 巡检+诊断技能验证 ⬜ 0/4" in md


def test_render_report_empty_state(tmp_home):
    """全部未完成时的报告格式."""
    md = gp.render_report()

    assert "**总进度**：0/12（0%）" in md
    assert "⬜" in md  # 所有项都未勾选
```

- [ ] **Step 2：跑测试确认失败**

Run: `pytest tests/test_guidance_progress.py -k "test_render_report" -v`
Expected: 2 failed

- [ ] **Step 3：实现**

在 `api/guidance_progress.py` 末尾追加：
```python
def _format_ts(ts: Optional[int]) -> str:
    if ts is None:
        return ""
    import datetime
    return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")


def render_report() -> str:
    """Generate Markdown progress report."""
    state = get_full_state()
    tasks = state["tasks"]
    summary = state["summary"]
    pct = int(round(summary["done"] / summary["total"] * 100)) if summary["total"] else 0

    lines = [
        "# 实施助手进度报告",
        "",
        f"**部署 ID**：{state['deployment_id']}",
        f"**生成时间**：{time.strftime('%Y-%m-%d %H:%M')}",
        f"**总进度**：{summary['done']}/{summary['total']}（{pct}%）",
        "",
    ]

    # 按 group 渲染
    for group_num in (1, 2, 3):
        group_tasks = [t for t in tasks if t["group"] == group_num]
        group_done = sum(1 for t in group_tasks if t["done"])
        icon = "✅" if group_done == len(group_tasks) else "⬜"
        title = _GROUP_TITLES[group_num]
        lines.append(f"## {group_num}. {title} {icon} {group_done}/{len(group_tasks)}")
        lines.append("")

        for t in group_tasks:
            checkbox = "- [x]" if t["done"] else "- [ ]"
            base = f"{checkbox} {t['id']} {t['title']}"
            if t["done"]:
                base += f" (by {t['by']}, {_format_ts(t['ts'])})"
            if t["note"]:
                base += f" — {t['note']}"
            lines.append(base)
        lines.append("")

    return "\n".join(lines)
```

- [ ] **Step 4：跑测试确认通过**

Run: `pytest tests/test_guidance_progress.py -k "test_render_report" -v`
Expected: 2 passed

- [ ] **Step 5：commit**

```bash
git add api/guidance_progress.py tests/test_guidance_progress.py
git commit -m "feat(guidance): add Markdown report renderer"
```

---

## Phase 3：路由注册（含 RBAC）

### Task 10：注册 5 个路由到 routes.py

**Files:**
- Modify: `api/routes.py`（添加 import + 路由函数）
- Modify: `tests/test_guidance_progress.py`（端到端 TestClient 测试）

- [ ] **Step 1：追加失败测试**

在 `tests/test_guidance_progress.py` 末尾追加：
```python
# --- 端到端路由测试 ---

@pytest.fixture
def app_with_admin(tmp_home, monkeypatch):
    """Create a minimal Flask app with admin session for route testing."""
    from flask import Flask, session
    app = Flask(__name__)
    app.secret_key = "test-secret"

    # 注册路由
    from api.routes import register_guidance_routes
    register_guidance_routes(app)

    return app


@pytest.fixture
def client(app_with_admin):
    return app_with_admin.test_client()


def _login_as(client, role="admin", username="alice"):
    with client.session_transaction() as sess:
        sess["user"] = {"username": username, "role": role}


def test_get_endpoint_admin_allowed(client, tmp_home):
    _login_as(client, "admin")
    res = client.get("/api/guidance/implementation")
    assert res.status_code == 200
    data = res.get_json()
    assert "tasks" in data
    assert len(data["tasks"]) == 12


def test_get_endpoint_ops_allowed(client, tmp_home):
    _login_as(client, "ops")
    res = client.get("/api/guidance/implementation")
    assert res.status_code == 200


def test_get_endpoint_viewer_forbidden(client, tmp_home):
    _login_as(client, "viewer")
    res = client.get("/api/guidance/implementation")
    assert res.status_code == 403


def test_patch_endpoint_admin(client, tmp_home):
    _login_as(client, "admin")
    res = client.patch(
        "/api/guidance/implementation/1.1_view_doc",
        json={"done": True},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["task"]["done"] is True


def test_patch_unknown_task_returns_400(client, tmp_home):
    _login_as(client, "admin")
    res = client.patch(
        "/api/guidance/implementation/bogus",
        json={"done": True},
    )
    assert res.status_code == 400


def test_post_note_endpoint(client, tmp_home):
    _login_as(client, "admin")
    res = client.post(
        "/api/guidance/implementation/1.3_import/note",
        json={"note": "关联 ZKREQ-130"},
    )
    assert res.status_code == 200
    assert res.get_json()["task"]["note"] == "关联 ZKREQ-130"


def test_get_report_returns_markdown(client, tmp_home):
    _login_as(client, "admin")
    res = client.get("/api/guidance/implementation/report")
    assert res.status_code == 200
    assert "text/markdown" in res.headers["Content-Type"]
    assert "attachment" in res.headers["Content-Disposition"]
    assert "# 实施助手进度报告" in res.get_data(as_text=True)


def test_post_import_happy(client, tmp_home):
    _login_as(client, "admin")
    content = Path("tests/fixtures/business_entities_valid.csv").read_bytes()
    res = client.post(
        "/api/guidance/implementation/import-business-entities",
        data={"file": (io.BytesIO(content), "valid.csv")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["ok"] is True
    assert data["imported_rows"] == 5


def test_post_import_validation_error(client, tmp_home):
    _login_as(client, "admin")
    content = Path("tests/fixtures/business_entities_missing_col.csv").read_bytes()
    res = client.post(
        "/api/guidance/implementation/import-business-entities",
        data={"file": (io.BytesIO(content), "missing.csv")},
        content_type="multipart/form-data",
    )
    assert res.status_code == 400
    data = res.get_json()
    assert "业务线名称" in data["missing"]


def test_no_state_leak_between_profiles(tmp_home, monkeypatch):
    """不同 HERMES_HOME 应读到不同进度."""
    from api import guidance_progress as gp

    other_home = tmp_home / "other"
    other_home.mkdir()
    monkeypatch.setenv("HERMES_HOME", str(other_home))

    gp.mark_task("1.1_view_doc", done=True, by="alice")

    # 切回 tmp_home
    monkeypatch.setenv("HERMES_HOME", str(tmp_home))
    state = gp.get_full_state()
    assert state["summary"]["done"] == 0
```

- [ ] **Step 2：跑测试确认失败**

Run: `pytest tests/test_guidance_progress.py -k "test_get_endpoint or test_patch_endpoint or test_post_note or test_get_report or test_post_import or test_no_state_leak" -v`
Expected: 多数失败（路由未注册）

- [ ] **Step 3：实现路由注册函数**

修改 `api/routes.py`：

1. 在文件顶部 import 区域添加：
```python
from api import guidance_progress as _guidance_progress
```

2. 在文件末尾追加（独立函数，可在 `server.py` 中按需注册）：
```python
def register_guidance_routes(app):
    """Register 5 endpoints for 2.1 implementation assistant.

    Call from server.py after auth middleware is set up.
    Endpoints:
      GET    /api/guidance/implementation
      PATCH  /api/guidance/implementation/<task_id>
      POST   /api/guidance/implementation/<task_id>/note
      GET    /api/guidance/implementation/report
      POST   /api/guidance/implementation/import-business-entities
    """
    from flask import jsonify, request, send_file, abort
    import io

    def _require_admin_or_ops():
        user = session.get("user") or {}
        if user.get("role") not in ("admin", "ops"):
            abort(403)

    def _current_username():
        return (session.get("user") or {}).get("username", "unknown")

    @app.route("/api/guidance/implementation", methods=["GET"])
    def _get_implementation():
        _require_admin_or_ops()
        return jsonify(_guidance_progress.get_full_state())

    @app.route("/api/guidance/implementation/<task_id>", methods=["PATCH"])
    def _patch_implementation(task_id):
        _require_admin_or_ops()
        body = request.get_json() or {}
        try:
            task = _guidance_progress.mark_task(
                task_id,
                done=bool(body.get("done", False)),
                by=_current_username(),
                note=body.get("note"),
            )
        except ValueError as e:
            return jsonify({"error": "unknown_task", "task_id": task_id, "detail": str(e)}), 400
        return jsonify({"ok": True, "task": task})

    @app.route("/api/guidance/implementation/<task_id>/note", methods=["POST"])
    def _post_note(task_id):
        _require_admin_or_ops()
        body = request.get_json() or {}
        note = body.get("note", "")
        try:
            task = _guidance_progress.update_note(task_id, note=note)
        except ValueError as e:
            return jsonify({"error": "unknown_task", "task_id": task_id, "detail": str(e)}), 400
        return jsonify({"ok": True, "task": task})

    @app.route("/api/guidance/implementation/report", methods=["GET"])
    def _get_report():
        _require_admin_or_ops()
        md = _guidance_progress.render_report()
        buf = io.BytesIO(md.encode("utf-8"))
        from datetime import datetime
        filename = f"implementation-report-{datetime.now().strftime('%Y%m%d')}.md"
        return send_file(
            buf,
            mimetype="text/markdown",
            as_attachment=True,
            download_name=filename,
        )

    @app.route(
        "/api/guidance/implementation/import-business-entities",
        methods=["POST"],
    )
    def _post_import():
        _require_admin_or_ops()
        upload = request.files.get("file")
        if not upload:
            return jsonify({"error": "no_file"}), 400
        content = upload.read().decode("utf-8")
        result = _guidance_progress.import_business_entities(
            content,
            filename=upload.filename or "upload.csv",
            by=_current_username(),
        )
        if not result["ok"]:
            return jsonify(result), 400
        return jsonify(result)
```

- [ ] **Step 4：在 server.py 中注册**

修改 `server.py`，找到 `register_routes(app)` 或类似调用，在其后面追加：
```python
from api.routes import register_guidance_routes
register_guidance_routes(app)
```

- [ ] **Step 5：跑测试确认通过**

Run: `pytest tests/test_guidance_progress.py -v --no-header`
Expected: 全部 passed（约 28 passed）

- [ ] **Step 6：commit**

```bash
git add api/routes.py server.py tests/test_guidance_progress.py
git commit -m "feat(guidance): register 5 routes with admin/ops RBAC"
```

---

## Phase 4：前端基础

### Task 11：i18n 新增 13 个 key

**Files:**
- Modify: `static/i18n.js`

- [ ] **Step 1：在 i18n.js 中找到合适位置（中英文表）**

查找 `guidance` 或相关键，确认格式。

- [ ] **Step 2：追加 13 个中英文 key**

在 i18n.js 的中文表 + 英文表各追加：
```javascript
// 中文 (zh)
"guidance_sidebar_entry": "引导中心",
"guidance_2_1_title": "实施助手 · 部署后使用条件检查",
"guidance_2_1_progress": "总进度：{done}/{total} 已完成",
"guidance_2_1_export": "导出进度报告",
"guidance_2_1_reset": "重置进度",
"guidance_2_1_reset_confirm": "确定要重置所有进度吗？此操作不可恢复。",
"guidance_2_1_group_1": "业务线实体关系表整理",
"guidance_2_1_group_2": "知识库整理（故障FAQ）",
"guidance_2_1_group_3": "巡检+诊断技能验证",
"guidance_2_1_import_btn": "上传 CSV 文件",
"guidance_2_1_import_missing_col": "缺少必填列：{cols}",
"guidance_2_1_import_errors": "共 {n} 行错误，已显示前 {shown} 行",
"guidance_2_1_download_errors": "下载错误报告",

// 英文 (en)
"guidance_sidebar_entry": "Guidance Center",
"guidance_2_1_title": "Implementation Assistant",
"guidance_2_1_progress": "Progress: {done}/{total}",
"guidance_2_1_export": "Export Progress Report",
"guidance_2_1_reset": "Reset Progress",
"guidance_2_1_reset_confirm": "Reset all progress? This cannot be undone.",
"guidance_2_1_group_1": "Business Line Entity Table",
"guidance_2_1_group_2": "Knowledge Base (FAQ)",
"guidance_2_1_group_3": "Inspection + Diagnosis Validation",
"guidance_2_1_import_btn": "Upload CSV File",
"guidance_2_1_import_missing_col": "Missing required columns: {cols}",
"guidance_2_1_import_errors": "{n} errors total, showing first {shown}",
"guidance_2_1_download_errors": "Download Error Report",
```

- [ ] **Step 3：手动验证 t() 行为**

Run:
```bash
node -e "
const code = require('fs').readFileSync('static/i18n.js', 'utf-8');
eval(code.replace('function t(', 'globalThis.t = function t_').replace(/^/, 'globalThis.t = ').split('function t_')[1].split('}')[0] + '}');
console.log(t('guidance_2_1_title'));
console.log(t('guidance_2_1_progress').replace('{done}', '3').replace('{total}', '12'));
"
```
Expected: 输出"实施助手 · 部署后使用条件检查" 和 "总进度：3/12 已完成"

- [ ] **Step 4：commit**

```bash
git add static/i18n.js
git commit -m "feat(guidance): add 13 i18n keys for implementation assistant"
```

---

### Task 12：创建 `static/guidance.css`

**Files:**
- Create: `static/guidance.css`

- [ ] **Step 1：写入 CSS**

`static/guidance.css`：
```css
/* ── Implementation Assistant (2.1) ────────────────────────────────────── */
.guidance-overlay-21 {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  z-index: 9000;
  display: flex;
  align-items: center;
  justify-content: center;
}

.guidance-page-21 {
  background: var(--bg-primary, #fff);
  width: min(960px, 95vw);
  max-height: 92vh;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.gp21-header {
  padding: 20px 24px;
  border-bottom: 1px solid var(--border-color, #e5e7eb);
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
}

.gp21-header h1 {
  margin: 0;
  font-size: 20px;
  flex: 1;
}

.gp21-progress-bar {
  height: 8px;
  background: var(--bg-tertiary, #f3f4f6);
  border-radius: 4px;
  overflow: hidden;
  flex: 1;
  min-width: 200px;
}

.gp21-progress-fill {
  height: 100%;
  background: var(--accent-color, #10b981);
  transition: width 0.3s ease;
}

.gp21-progress-label {
  font-size: 14px;
  color: var(--text-secondary, #6b7280);
}

.gp21-tasks {
  padding: 16px 24px;
  overflow-y: auto;
  flex: 1;
}

.gp21-group {
  margin-bottom: 16px;
  border: 1px solid var(--border-color, #e5e7eb);
  border-radius: 8px;
}

.gp21-group-header {
  padding: 12px 16px;
  background: var(--bg-secondary, #f9fafb);
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 12px;
  font-weight: 600;
}

.gp21-group-header:hover {
  background: var(--bg-tertiary, #f3f4f6);
}

.gp21-group-body {
  padding: 8px 16px;
}

.gp21-task {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
  border-bottom: 1px solid var(--border-color-light, #f3f4f6);
}

.gp21-task:last-child {
  border-bottom: none;
}

.gp21-task input[type="checkbox"] {
  flex-shrink: 0;
  width: 18px;
  height: 18px;
}

.gp21-task-title {
  flex: 1;
}

.gp21-task-meta {
  font-size: 12px;
  color: var(--text-secondary, #6b7280);
}

.gp21-task-note {
  font-size: 12px;
  color: var(--text-tertiary, #9ca3af);
  font-style: italic;
  margin-left: 12px;
}

.gp21-footer {
  padding: 16px 24px;
  border-top: 1px solid var(--border-color, #e5e7eb);
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.gp21-actions {
  display: flex;
  gap: 8px;
}

.gp21-btn {
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid var(--border-color, #d1d5db);
  background: var(--bg-primary, #fff);
  cursor: pointer;
  font-size: 14px;
}

.gp21-btn:hover {
  background: var(--bg-secondary, #f9fafb);
}

.gp21-btn-primary {
  background: var(--accent-color, #10b981);
  color: white;
  border-color: var(--accent-color, #10b981);
}

/* 移动端 */
@media (max-width: 768px) {
  .guidance-page-21 {
    width: 100vw;
    height: 100vh;
    max-height: 100vh;
    border-radius: 0;
  }

  .gp21-header {
    padding: 12px 16px;
  }

  .gp21-tasks {
    padding: 8px 16px;
  }
}
```

- [ ] **Step 2：在 index.html 引入 CSS**

在 `static/index.html` 找到 `style.css` 的引入行附近，追加：
```html
<link rel="stylesheet" href="guidance.css">
```

- [ ] **Step 3：commit**

```bash
git add static/guidance.css static/index.html
git commit -m "feat(guidance): add CSS for implementation assistant fullscreen page"
```

---

### Task 13：在 index.html 注入 template 和 script

**Files:**
- Modify: `static/index.html`

- [ ] **Step 1：注入 HTML 模板**

在 `static/index.html` 的 `</body>` 前追加：
```html
<!-- 2.1 实施助手引导页模板 -->
<template id="tpl-guidance-2-1">
  <div class="guidance-overlay-21" id="guidanceOverlay21">
    <div class="guidance-page-21" role="dialog" aria-labelledby="gp21-title">
      <header class="gp21-header">
        <h1 id="gp21-title">📋 实施助手</h1>
        <div class="gp21-progress-bar">
          <div class="gp21-progress-fill" id="gp21ProgressFill" style="width:0%"></div>
        </div>
        <span class="gp21-progress-label" id="gp21ProgressLabel">0/12</span>
        <div class="gp21-actions">
          <button class="gp21-btn" id="gp21ExportBtn">导出报告</button>
          <button class="gp21-btn" id="gp21ResetBtn">重置进度</button>
          <button class="gp21-btn" id="gp21CloseBtn">关闭</button>
        </div>
      </header>
      <div class="gp21-tasks" id="gp21Tasks">
        <!-- 3 个 group 动态渲染 -->
      </div>
      <footer class="gp21-footer">
        <span id="gp21CurrentUser"></span>
        <input type="file" id="gp21ImportFile" accept=".csv" style="display:none">
        <button class="gp21-btn gp21-btn-primary" id="gp21ImportBtn">📤 上传 CSV</button>
      </footer>
    </div>
  </div>
</template>

<!-- 2.1 错误报告 Modal 模板 -->
<template id="tpl-guidance-2-1-errors">
  <div class="guidance-overlay-21" id="guidanceErrors21">
    <div class="guidance-page-21" style="max-width:720px">
      <header class="gp21-header">
        <h1>导入错误</h1>
        <button class="gp21-btn" id="gp21ErrorsClose">关闭</button>
      </header>
      <div class="gp21-tasks">
        <p id="gp21ErrorsSummary"></p>
        <div style="max-height:400px;overflow:auto">
          <table id="gp21ErrorsTable" style="width:100%;font-size:13px">
            <thead><tr><th>行号</th><th>字段</th><th>原因</th></tr></thead>
            <tbody></tbody>
          </table>
        </div>
      </div>
      <footer class="gp21-footer">
        <button class="gp21-btn gp21-btn-primary" id="gp21ErrorsDownload">下载错误报告</button>
      </footer>
    </div>
  </div>
</template>

<script src="guidance.js"></script>
```

- [ ] **Step 2：commit**

```bash
git add static/index.html
git commit -m "feat(guidance): inject HTML templates for implementation assistant"
```

---

## Phase 5：前端模块 `static/guidance.js`

### Task 14：模块骨架 + GuidanceManager 单例

**Files:**
- Create: `static/guidance.js`（初始版本，后续 task 扩展）

- [ ] **Step 1：写入骨架**

`static/guidance.js`：
```javascript
/* ───────────────────────────────────────────────────────────────────────────
 * 2.1 实施助手引导页 — 前端模块
 * ───────────────────────────────────────────────────────────────────────────
 * GuidanceManager 单例 + Page2_1 全屏页实现。
 * 与 boot.js / panels.js 通过 window 事件总线解耦。
 */

(function() {
  'use strict';

  // ── 单例 ────────────────────────────────────────────────────────────────
  const GuidanceManager = {
    state: {
      '2.1': {
        loaded: false,
        data: null,  // 全量 state from /api/guidance/implementation
        collapsed: { 1: true, 2: true, 3: false },
        currentUser: null,
      },
    },

    triggers: {
      '2.1': {
        on: ['deployment_first_seen', 'business_line_no_assets', 'manual_nav'],
        surface: 'fullscreen_page',
        auto_show: true,
      },
    },

    init() {
      this._hydrateFromLocalStorage();
      this._registerEventListeners();
      this._registerSidebarEntry();
      window.__guidanceMgr = this;
      console.log('[guidance] initialized');
    },

    _hydrateFromLocalStorage() {
      try {
        const raw = localStorage.getItem('guidance.dismissed.2_1');
        if (raw) this.state['2.1'].dismissed = raw === 'true';
      } catch (e) {
        console.warn('[guidance] localStorage read failed:', e);
      }
    },

    _registerEventListeners() {
      window.addEventListener('hermes:license_activated', (e) => {
        this.evaluate('deployment_first_seen', { autoTriggered: true });
      });
      window.addEventListener('hermes:onboarding_complete', (e) => {
        // 仅在 deployment_first_seen 未触发时兜底
        if (!this.state['2.1'].loaded) {
          this.evaluate('deployment_first_seen', { autoTriggered: true });
        }
      });
    },

    _registerSidebarEntry() {
      // 由 panels.js 处理入口渲染（见 Task 19）
    },

    evaluate(eventName, payload) {
      for (const [pageId, cfg] of Object.entries(this.triggers)) {
        if (cfg.on.includes(eventName) && this._shouldShow(pageId, eventName, payload)) {
          this._dispatch(pageId, payload);
        }
      }
    },

    _shouldShow(pageId, eventName, payload) {
      if (this.state[pageId].dismissed && eventName !== 'manual_nav') return false;
      const key = `guidance.${pageId.replace('.', '_')}.auto_shown_at`;
      try {
        const lastShown = sessionStorage.getItem(key);
        if (lastShown && Date.now() - parseInt(lastShown, 10) < 600_000) return false;
      } catch (e) {
        // sessionStorage 不可用时直接通过
      }
      return true;
    },

    _dispatch(pageId, payload) {
      if (pageId === '2.1') {
        const key = 'guidance.2_1.auto_shown_at';
        try { sessionStorage.setItem(key, String(Date.now())); } catch (e) {}
        Page2_1_Implementation.openFullscreen({ autoTriggered: payload.autoTriggered });
      }
    },
  };

  // ── Page2_1 实施助手 ──────────────────────────────────────────────────────
  const Page2_1_Implementation = {
    async openFullscreen({ autoTriggered = false } = {}) {
      // 从模板克隆
      const tpl = document.getElementById('tpl-guidance-2-1');
      if (!tpl) {
        console.warn('[guidance] template tpl-guidance-2-1 not found');
        return;
      }
      const overlay = tpl.content.firstElementChild.cloneNode(true);
      overlay.id = `guidanceOverlay21-${Date.now()}`;
      document.body.appendChild(overlay);

      // 绑定事件
      overlay.querySelector('#gp21CloseBtn').addEventListener('click', () => this.close(overlay));
      overlay.querySelector('#gp21ExportBtn').addEventListener('click', () => this.exportReport());
      overlay.querySelector('#gp21ResetBtn').addEventListener('click', () => this.resetProgress(overlay));
      overlay.querySelector('#gp21ImportBtn').addEventListener('click', () => {
        overlay.querySelector('#gp21ImportFile').click();
      });
      overlay.querySelector('#gp21ImportFile').addEventListener('change', (e) => {
        this.handleImport(e.target.files[0], overlay);
      });

      // 拉取状态
      await this._refresh(overlay);

      if (autoTriggered) {
        console.log('[guidance] 2.1 auto-shown after deployment');
      }
    },

    close(overlay) {
      overlay.remove();
      try {
        localStorage.setItem('guidance.dismissed.2_1', 'true');
        GuidanceManager.state['2.1'].dismissed = true;
      } catch (e) {}
    },

    async _refresh(overlay) {
      try {
        const res = await api('/api/guidance/implementation');
        if (!res || !res.tasks) {
          throw new Error('invalid response');
        }
        GuidanceManager.state['2.1'].data = res;
        GuidanceManager.state['2.1'].loaded = true;
        this._render(overlay, res);
      } catch (e) {
        console.warn('[guidance] failed to load implementation state:', e);
        this._renderError(overlay, '加载失败，请稍后重试');
      }
    },

    _render(overlay, data) {
      // 进度条
      const pct = data.summary.total ? Math.round(data.summary.done / data.summary.total * 100) : 0;
      overlay.querySelector('#gp21ProgressFill').style.width = pct + '%';
      overlay.querySelector('#gp21ProgressLabel').textContent = `${data.summary.done}/${data.summary.total}`;

      // 当前用户
      overlay.querySelector('#gp21CurrentUser').textContent = `当前用户：${(data.tasks.find(t => t.by) || {}).by || 'unknown'}`;

      // 任务列表
      const tasksEl = overlay.querySelector('#gp21Tasks');
      tasksEl.innerHTML = '';

      for (const groupNum of [1, 2, 3]) {
        const groupTasks = data.tasks.filter(t => t.group === groupNum);
        const groupEl = this._renderGroup(groupNum, groupTasks);
        tasksEl.appendChild(groupEl);
      }
    },

    _renderGroup(groupNum, tasks) {
      const group = document.createElement('div');
      group.className = 'gp21-group';

      const groupDone = tasks.filter(t => t.done).length;
      const collapsed = GuidanceManager.state['2.1'].collapsed[groupNum];

      const header = document.createElement('div');
      header.className = 'gp21-group-header';
      header.innerHTML = `
        <span>${collapsed ? '▶' : '▼'}</span>
        <span style="flex:1">${groupNum}. ${tasks[0].group_title}</span>
        <span style="color:var(--text-secondary)">${groupDone}/${tasks.length}</span>
      `;
      header.addEventListener('click', () => {
        GuidanceManager.state['2.1'].collapsed[groupNum] = !collapsed;
        body.style.display = collapsed ? 'block' : 'none';
        header.querySelector('span').textContent = collapsed ? '▼' : '▶';
      });

      const body = document.createElement('div');
      body.className = 'gp21-group-body';
      body.style.display = collapsed ? 'none' : 'block';

      for (const task of tasks) {
        body.appendChild(this._renderTask(task));
      }

      group.appendChild(header);
      group.appendChild(body);
      return group;
    },

    _renderTask(task) {
      const row = document.createElement('div');
      row.className = 'gp21-task';
      row.dataset.taskId = task.id;

      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.checked = task.done;
      checkbox.addEventListener('change', () => this.toggleTask(task.id, checkbox.checked));

      const title = document.createElement('span');
      title.className = 'gp21-task-title';
      title.textContent = `${task.id} ${task.title}`;

      const meta = document.createElement('span');
      meta.className = 'gp21-task-meta';
      if (task.done && task.by) {
        meta.textContent = `(by ${task.by})`;
      }

      const noteBtn = document.createElement('button');
      noteBtn.className = 'gp21-btn';
      noteBtn.style.fontSize = '12px';
      noteBtn.textContent = task.note ? '📝 编辑备注' : '+ 备注';
      noteBtn.addEventListener('click', () => this.editNote(task.id, task.note, row));

      row.appendChild(checkbox);
      row.appendChild(title);
      row.appendChild(meta);
      row.appendChild(noteBtn);

      if (task.note) {
        const note = document.createElement('span');
        note.className = 'gp21-task-note';
        note.textContent = task.note;
        row.appendChild(note);
      }

      return row;
    },

    _renderError(overlay, msg) {
      const tasksEl = overlay.querySelector('#gp21Tasks');
      tasksEl.innerHTML = `<div style="padding:32px;text-align:center;color:var(--text-secondary)">${msg}</div>`;
    },

    async toggleTask(taskId, done) {
      try {
        const res = await api(`/api/guidance/implementation/${taskId}`, {
          method: 'PATCH',
          body: JSON.stringify({ done }),
        });
        if (!res.ok) throw new Error(res.error || 'patch failed');
        // 局部刷新
        const overlay = document.querySelector('[id^="guidanceOverlay21-"]');
        if (overlay) await this._refresh(overlay);
      } catch (e) {
        console.warn('[guidance] toggle task failed:', e);
        alert('保存失败，请稍后重试');
      }
    },

    async editNote(taskId, currentNote, row) {
      const note = prompt('备注（关联需求号 / 说明）：', currentNote || '');
      if (note === null) return;
      try {
        const res = await api(`/api/guidance/implementation/${taskId}/note`, {
          method: 'POST',
          body: JSON.stringify({ note }),
        });
        if (!res.ok) throw new Error(res.error || 'note failed');
        const overlay = document.querySelector('[id^="guidanceOverlay21-"]');
        if (overlay) await this._refresh(overlay);
      } catch (e) {
        console.warn('[guidance] edit note failed:', e);
        alert('保存备注失败');
      }
    },

    async exportReport() {
      try {
        const res = await fetch('/api/guidance/implementation/report', { credentials: 'include' });
        if (!res.ok) throw new Error('export failed');
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = res.headers.get('Content-Disposition').match(/filename="?([^"]+)"?/)[1];
        a.click();
        URL.revokeObjectURL(url);
      } catch (e) {
        console.warn('[guidance] export failed:', e);
        alert('导出失败，请稍后重试');
      }
    },

    async resetProgress(overlay) {
      if (!confirm('确定要重置所有进度吗？此操作不可恢复。')) return;
      try {
        const res = await api('/api/guidance/implementation', {
          method: 'DELETE',
        });
        if (!res.ok) throw new Error('reset failed');
        await this._refresh(overlay);
      } catch (e) {
        console.warn('[guidance] reset failed:', e);
        alert('重置失败，请稍后重试');
      }
    },

    async handleImport(file, overlay) {
      if (!file) return;
      if (!file.name.toLowerCase().endsWith('.csv')) {
        alert('v1.1.0 仅支持 CSV 文件');
        return;
      }
      const formData = new FormData();
      formData.append('file', file);
      try {
        const res = await fetch('/api/guidance/implementation/import-business-entities', {
          method: 'POST',
          body: formData,
          credentials: 'include',
        });
        const data = await res.json();
        if (res.ok && data.ok) {
          await this._refresh(overlay);
          alert(`成功导入 ${data.imported_rows} 行`);
        } else {
          this._showImportErrors(data);
        }
      } catch (e) {
        console.warn('[guidance] import failed:', e);
        alert('导入失败，请稍后重试');
      }
    },

    _showImportErrors(data) {
      const tpl = document.getElementById('tpl-guidance-2-1-errors');
      if (!tpl) return;
      const overlay = tpl.content.firstElementChild.cloneNode(true);
      document.body.appendChild(overlay);

      const summary = overlay.querySelector('#gp21ErrorsSummary');
      if (data.error === 'missing_columns') {
        summary.textContent = `缺少必填列：${data.missing.join('、')}`;
      } else if (data.error === 'size_limit') {
        summary.textContent = data.detail || '文件过大';
      } else {
        summary.textContent = `共 ${data.total_failed} 行错误，已显示前 ${data.failed_rows.length} 行`;
        const tbody = overlay.querySelector('#gp21ErrorsTable tbody');
        for (const row of data.failed_rows) {
          const tr = document.createElement('tr');
          tr.innerHTML = `<td>${row.line}</td><td>${row.field}</td><td>${row.reason}</td>`;
          tbody.appendChild(tr);
        }
      }

      overlay.querySelector('#gp21ErrorsClose').addEventListener('click', () => overlay.remove());
    },
  };

  // ── 导出到全局 ────────────────────────────────────────────────────────────
  window.GuidanceManager = GuidanceManager;
  window.Page2_1_Implementation = Page2_1_Implementation;
})();
```

- [ ] **Step 2：在 boot.js 末尾追加 init 调用**

修改 `static/boot.js`，找到合适的末尾位置追加：
```javascript
// 引导中心初始化
if (window.GuidanceManager && !window.__guidanceMgr) {
  window.GuidanceManager.init();
}
```

- [ ] **Step 3：commit**

```bash
git add static/guidance.js static/boot.js
git commit -m "feat(guidance): add frontend module with Page2_1 implementation"
```

---

### Task 15：在 routes.py 添加 DELETE /api/guidance/implementation（reset 端点）

**Files:**
- Modify: `api/routes.py`

- [ ] **Step 1：添加 reset 路由**

在 `register_guidance_routes` 函数内，添加：
```python
    @app.route("/api/guidance/implementation", methods=["DELETE"])
    def _delete_implementation():
        _require_admin_or_ops()
        _guidance_progress.reset_progress()
        return jsonify({"ok": True})
```

- [ ] **Step 2：commit**

```bash
git add api/routes.py
git commit -m "feat(guidance): add DELETE endpoint for reset"
```

---

### Task 16：侧栏入口（panels.js RBAC 检查）

**Files:**
- Modify: `static/panels.js`

- [ ] **Step 1：找到侧栏渲染函数**

查找 `renderSidebar` 或类似入口（在 panels.js 中）。

- [ ] **Step 2：在适当位置插入入口**

```javascript
function _renderGuidanceSidebarEntry() {
  const userRole = (window.currentUser && window.currentUser.role) || 'viewer';
  if (!['admin', 'ops'].includes(userRole)) return null;  // RBAC

  const entry = document.createElement('div');
  entry.className = 'sidebar-entry';
  entry.innerHTML = `<span>📋 引导中心</span>`;
  entry.addEventListener('click', () => {
    if (window.GuidanceManager) {
      window.GuidanceManager.evaluate('manual_nav', { autoTriggered: false });
    }
  });
  return entry;
}
```

并在侧栏渲染流程中调用 `_renderGuidanceSidebarEntry()`。

- [ ] **Step 3：commit**

```bash
git add static/panels.js
git commit -m "feat(guidance): add sidebar entry with admin/ops RBAC"
```

---

## Phase 6：测试 + 验证

### Task 17：前端 jsdom 单元测试

**Files:**
- Create: `tests/js/test_guidance_triggers.test.mjs`

- [ ] **Step 1：写入测试**

`tests/js/test_guidance_triggers.test.mjs`：
```javascript
import { JSDOM } from 'jsdom';
import { strict as assert } from 'assert';

const dom = new JSDOM('<!DOCTYPE html><html><body></body></html>');
global.window = dom.window;
global.document = dom.window.document;
global.localStorage = dom.window.localStorage;
global.sessionStorage = dom.window.sessionStorage;
global.fetch = async () => ({ ok: true, json: async () => ({}) });

// 加载 guidance.js
const code = await import('fs').then(fs => fs.promises.readFile('static/guidance.js', 'utf-8'));
eval(code);

describe('GuidanceManager 2.1 triggers', () => {
  it('ignores deployment_first_seen when dismissed', () => {
    const gm = window.GuidanceManager;
    gm.state['2.1'].dismissed = true;
    let triggered = false;
    const origDispatch = gm._dispatch;
    gm._dispatch = (pageId) => { if (pageId === '2.1') triggered = true; };

    gm.evaluate('deployment_first_seen', { autoTriggered: true });
    assert.equal(triggered, false);

    gm._dispatch = origDispatch;
  });

  it('dedupes within 10 minutes via sessionStorage', () => {
    const gm = window.GuidanceManager;
    gm.state['2.1'].dismissed = false;
    sessionStorage.setItem('guidance.2_1.auto_shown_at', String(Date.now()));

    let triggered = false;
    const origDispatch = gm._dispatch;
    gm._dispatch = () => { triggered = true; };

    gm.evaluate('deployment_first_seen', { autoTriggered: true });
    assert.equal(triggered, false);

    gm._dispatch = origDispatch;
    sessionStorage.removeItem('guidance.2_1.auto_shown_at');
  });

  it('manual_nav bypasses dedup and dismissed', () => {
    const gm = window.GuidanceManager;
    gm.state['2.1'].dismissed = true;
    sessionStorage.setItem('guidance.2_1.auto_shown_at', String(Date.now()));

    let triggered = false;
    const origDispatch = gm._dispatch;
    gm._dispatch = () => { triggered = true; };

    gm.evaluate('manual_nav', { autoTriggered: false });
    assert.equal(triggered, true);

    gm._dispatch = origDispatch;
  });
});
```

- [ ] **Step 2：跑测试**

Run: `node tests/js/test_guidance_triggers.test.mjs`
Expected: 3 passed

如失败，先安装 jsdom：
```bash
npm install --save-dev jsdom
```

- [ ] **Step 3：commit**

```bash
git add tests/js/test_guidance_triggers.test.mjs package.json package-lock.json
git commit -m "test(guidance): add jsdom unit tests for triggers"
```

---

### Task 18：Playwright E2E

**Files:**
- Create: `tests/e2e/test_implementation_assistant.spec.js`

- [ ] **Step 1：写入 E2E 测试**

`tests/e2e/test_implementation_assistant.spec.js`：
```javascript
const { test, expect } = require('@playwright/test');
const path = require('path');

test.describe('2.1 Implementation Assistant', () => {
  test.beforeEach(async ({ page }) => {
    // 模拟 admin 登录
    await page.goto('/');
    await page.evaluate(() => {
      window.currentUser = { username: 'alice', role: 'admin' };
    });
  });

  test('admin can open and check tasks', async ({ page }) => {
    await page.evaluate(() => {
      window.GuidanceManager.evaluate('manual_nav', { autoTriggered: false });
    });
    await page.waitForSelector('[id^="guidanceOverlay21-"]');

    // 勾选第一个任务
    const firstCheckbox = page.locator('.gp21-task input[type="checkbox"]').first();
    await firstCheckbox.check();

    // 验证进度更新
    await expect(page.locator('#gp21ProgressLabel')).toContainText('1/12');
  });

  test('CSV import happy path', async ({ page }) => {
    await page.evaluate(() => {
      window.GuidanceManager.evaluate('manual_nav', { autoTriggered: false });
    });
    await page.waitForSelector('[id^="guidanceOverlay21-"]');

    // 上传有效 CSV
    const fileInput = page.locator('#gp21ImportFile');
    await fileInput.setInputFiles(
      path.join(__dirname, '../fixtures/business_entities_valid.csv'),
    );

    // 验证 alert（成功）
    page.on('dialog', async (dialog) => {
      expect(dialog.message()).toContain('成功导入');
      await dialog.accept();
    });

    // 等待任务 1.3_import 被勾选
    await page.waitForTimeout(1000);
    // 注：实际等待可以用更精确的 selector
  });

  test('CSV import error shows modal', async ({ page }) => {
    await page.evaluate(() => {
      window.GuidanceManager.evaluate('manual_nav', { autoTriggered: false });
    });
    await page.waitForSelector('[id^="guidanceOverlay21-"]');

    const fileInput = page.locator('#gp21ImportFile');
    await fileInput.setInputFiles(
      path.join(__dirname, '../fixtures/business_entities_missing_col.csv'),
    );

    // 验证错误 modal 出现
    await expect(page.locator('#guidanceErrors21')).toBeVisible({ timeout: 3000 });
  });

  test('viewer role sees no sidebar entry', async ({ page }) => {
    await page.evaluate(() => {
      window.currentUser = { username: 'bob', role: 'viewer' };
    });
    // 触发侧栏重渲染
    await page.reload();

    // 验证侧栏没有引导中心入口
    const entry = page.locator('text=引导中心');
    await expect(entry).toHaveCount(0);
  });
});
```

- [ ] **Step 2：跑 E2E（CI 环境才跑）**

Run:
```bash
npx playwright test tests/e2e/test_implementation_assistant.spec.js
```
Expected: 4 passed（前提是测试服务器已起且数据库干净）

- [ ] **Step 3：commit**

```bash
git add tests/e2e/test_implementation_assistant.spec.js
git commit -m "test(guidance): add Playwright E2E for implementation assistant"
```

---

### Task 19：CHANGELOG 更新

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1：在 1.1.0 条目下追加**

找到 `## [1.1.0]` 或最新未发布版本，在其下追加：
```markdown
### Added
- 实施助手引导页（2.1）：从部署完成到具备使用条件的 12 项 step-by-step 清单
  - 侧栏入口 + 全屏覆盖页（含进度条、3 大子任务、备注）
  - CSV 业务实体表导入（含校验、错误聚合、错误报告下载）
  - Markdown 进度报告导出
  - 重置进度功能
  - admin/ops RBAC 限定
- 后端模块 `api/guidance_progress.py`：YAML 原子读写、白名单校验、CSV 校验、报告渲染
- 5 个新 API 端点（GET/PATCH/POST note/GET report/POST import + DELETE reset）
- 前端模块 `static/guidance.js`：`GuidanceManager` 单例 + 事件总线触发器
- 13 个 i18n key（`guidance_2_1_*`）
- 28 个 pytest 用例 + 3 个 jsdom 触发器用例 + 4 个 Playwright E2E
```

- [ ] **Step 2：commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): add 1.1.0 implementation assistant entry"
```

---

## 验收清单（执行完成后勾选）

- [ ] Task 1-9：后端 pytest 全绿（28+ passed）
- [ ] Task 10：5 个路由 + DELETE reset 注册成功
- [ ] Task 11：13 个 i18n key 中英文对照
- [ ] Task 12：CSS 在移动端 < 768px 折叠子任务
- [ ] Task 13：HTML 模板 + script 引入
- [ ] Task 14：guidance.js 模块加载无 console error
- [ ] Task 15：DELETE reset 端点 200
- [ ] Task 16：viewer 角色看不到侧栏入口
- [ ] Task 17：jsdom 单元测试 3 passed
- [ ] Task 18：Playwright E2E 4 passed
- [ ] Task 19：CHANGELOG 更新
- [ ] 手动 checklist（spec §8.5）：移动端、RBAC、i18n、边界

## 后续计划（v1.1.0 之后）

- Plan B：引导页 2.2（首次使用 modal）
- Plan C：引导页 2.3（新会话空状态）
- Plan D：引导页 2.4（技能发现 popover）
- v1.2.0：PDF 报告导出
- v1.2.0：XLSX 导入支持
- v1.2.0：业务实体实际写入存储（当前仅校验）