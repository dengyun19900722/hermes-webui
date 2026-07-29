"""实施助手引导页（2.1）后端模块。

读写 ~/.hermes/guidance_progress.yaml，提供 5 个 endpoint 的业务逻辑。
YAML 写采用原子替换（UUID tmp + os.replace）避免半写损坏 + 并发写冲突。
"""
from __future__ import annotations

import csv
import io
import os
import re
import time
import uuid
import datetime
import yaml
from pathlib import Path
from typing import Any, Optional

from api.profiles import get_active_hermes_home

SCHEMA_VERSION = 1

# 12 项任务白名单（与 spec §4.1 一致）
ALLOWED_TASKS = frozenset({
    "1.1_view_doc", "1.2_download_tpl", "1.3_validate", "1.3_import", "1.3_verify",
    "2.1_view_template", "2.2_batch_import", "2.3_verify_search",
    "3.1_select_business_line", "3.2_run_inspection", "3.3_run_diagnosis", "3.4_record_result",
})


def _guidance_progress_path() -> Path:
    """Return the active profile's ~/.hermes/guidance_progress.yaml.

    Uses get_active_hermes_home() so per-request TLS profile context (#798)
    is respected, not just the process-level HERMES_HOME env var. This ensures
    progress state follows the logged-in user's profile, not the server's
    startup profile.
    """
    return get_active_hermes_home() / "guidance_progress.yaml"


def _atomic_write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Atomically write data to YAML via UUID tmp + os.replace.

    - UUID tmp suffix prevents concurrent writers from clobbering each other.
    - Creates parent directory if missing (matches project convention in
      api/passkeys.py:70, api/config.py:791, api/onboarding.py:253).
    - Catches both OSError (file system) and yaml.YAMLError (serialization).
    - On any failure, tmp is cleaned and RuntimeError raised with context.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        os.replace(tmp, path)
    except (OSError, yaml.YAMLError) as e:
        if tmp.exists():
            tmp.unlink()
        raise RuntimeError(f"guidance_progress.yaml write failed: {e}") from e


def load_progress() -> dict[str, Any]:
    """Read guidance_progress.yaml; return empty schema if file missing or invalid.

    Robust against:
    - Missing file → empty schema
    - Empty file → empty schema
    - Non-mapping YAML (e.g., scalar/list from user edit) → empty schema
    - Missing required keys → defaults applied
    """
    path = _guidance_progress_path()
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "implementation": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError:
        # Corrupted YAML — return empty rather than crash
        return {"schema_version": SCHEMA_VERSION, "implementation": {}}

    if not isinstance(data, dict):
        # User-edited file with non-mapping (scalar/list) — fall back to empty
        return {"schema_version": SCHEMA_VERSION, "implementation": {}}

    data.setdefault("schema_version", SCHEMA_VERSION)
    data.setdefault("implementation", {})
    return data


def save_progress(data: dict[str, Any]) -> None:
    """Atomically write progress data to disk."""
    _atomic_write_yaml(_guidance_progress_path(), data)


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


# ── Task 4: mark_task + update_note ─────────────────────────────────────────


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


# ── Task 5: reset_progress ──────────────────────────────────────────────────


def reset_progress() -> None:
    """Clear all progress. Used by 'Reset Progress' button."""
    save_progress({"schema_version": SCHEMA_VERSION, "implementation": {}})


# ── Task 6: get_full_state ──────────────────────────────────────────────────


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


# ── Task 7: CSV validation ──────────────────────────────────────────────────


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


# ── Task 8: import_business_entities ────────────────────────────────────────


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


# ── Task 9: render_report ───────────────────────────────────────────────────


def _format_ts(ts: Optional[int]) -> str:
    if ts is None:
        return ""
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