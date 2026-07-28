"""实施助手引导页（2.1）后端模块。

读写 ~/.hermes/guidance_progress.yaml，提供 5 个 endpoint 的业务逻辑。
YAML 写采用原子替换（UUID tmp + os.replace）避免半写损坏 + 并发写冲突。
"""
from __future__ import annotations

import os
import uuid
import yaml
from pathlib import Path
from typing import Any

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