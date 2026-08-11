"""实施助手引导页（2.1）后端模块。

读写 ~/.hermes/guidance_progress.yaml，提供 5 个 endpoint 的业务逻辑。
YAML 写采用原子替换（UUID tmp + os.replace）避免半写损坏 + 并发写冲突。
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import time
import uuid
import datetime
import yaml
from pathlib import Path
from typing import Any, Optional

from api.profiles import get_active_hermes_home

# v2: 任务状态增加验证字段（verified/verified_by/verified_at/
#     verification_type/evidence/last_check）。旧 v1 数据读取时自动迁移补齐。
SCHEMA_VERSION = 2

# 哪些任务可由后端"自主验证"（调用真实后端能力判定是否真的完成）。
# 不在白名单里的任务只能手动标记（且手动标记必须填备注）。
AUTO_VERIFIABLE_TASKS = frozenset({
    # 有真实后端可判定完成的任务 → 可"自主验证"
    "1.3_import_entities",  # CSV 校验 + 真实落盘到资产库存（一次完成）
    "2.2_batch_import",     # 真实批量导入知识库
    "2.3_verify_search",    # 调用知识库搜索接口 results>0
    "3.1_select_business_line",  # 资产库存里存在可选业务线
})

# "查看/下载/执行"类任务：无可靠后端数据可判定，必须手动标记（且必填备注）
# 这些任务提供就地操作入口（跳转/触发），但完成与否由用户确认并备注原因。
MANUAL_ONLY_TASKS = frozenset({
    "1.1_fill_entity_table",  # 查看文档 + 下载模板 + 填写说明（手动确认）
    "2.1_view_template",
    "3.2_run_inspection", "3.3_run_diagnosis", "3.4_record_result",
})

# 9 项任务白名单（Group 1 合并为 2 步）
ALLOWED_TASKS = frozenset({
    "1.1_fill_entity_table", "1.3_import_entities",
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
    # Group 1: 业务线实体关系表整理 (2 步)
    {"id": "1.1_fill_entity_table", "group": 1, "title": "填写实体关系表"},
    {"id": "1.3_import_entities",   "group": 1, "title": "上传导入实体表"},
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
    """Merge progress state into static metadata; defaults applied for missing tasks.

    兼容 v1 旧数据：缺验证字段时按默认值补齐（不强制改写磁盘文件）。
    """
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
            # v2 验证字段
            "verified": bool(state.get("verified", False)),
            "verified_by": state.get("verified_by"),
            "verified_at": state.get("verified_at"),
            "verification_type": state.get("verification_type"),  # auto / manual / null
            "evidence": state.get("evidence", ""),
            "last_check": state.get("last_check"),  # {"passed": bool, "evidence": str} | null
            "verifiable": meta["id"] in AUTO_VERIFIABLE_TASKS,
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


def mark_task(
    task_id: str,
    *,
    done: bool,
    by: str,
    note: Optional[str] = None,
) -> dict[str, Any]:
    """Manually mark task done/undone (checklist behaviour).

    - done=True：视为"手动标记"。若任务当前未自动验证通过，则必须提供 note
      （备注原因），否则抛 ValueError("manual_note_required")。
    - done=False：取消完成，同时清除验证标记。

    Returns updated task dict.
    """
    validate_task_id(task_id)
    data = load_progress()
    existing = data["implementation"].get(task_id, {})

    # 保留 note（除非显式传入）
    note_value = note if note is not None else existing.get("note", "")

    if done:
        # 手动标记：若未被自动验证覆盖，强制要求备注，杜绝"打勾就完事"
        already_verified = bool(existing.get("verified", False))
        if not already_verified and not (note_value or "").strip():
            raise ValueError("manual_note_required")
        data["implementation"][task_id] = {
            "done": True,
            "by": by,
            "ts": int(time.time()),
            "note": note_value,
            # 手动标记但未自动验证时，verification_type 标记为 manual
            "verified": already_verified,
            "verified_by": existing.get("verified_by") if already_verified else by,
            "verified_at": existing.get("verified_at") if already_verified else int(time.time()),
            "verification_type": existing.get("verification_type", "manual") if already_verified else "manual",
            "evidence": existing.get("evidence", note_value),
            "last_check": existing.get("last_check"),
        }
    else:
        # 取消：清空完成与验证状态，保留 note
        data["implementation"][task_id] = {
            "done": False,
            "by": None,
            "ts": None,
            "note": note_value,
            "verified": False,
            "verified_by": None,
            "verified_at": None,
            "verification_type": None,
            "evidence": existing.get("evidence", ""),
            "last_check": existing.get("last_check"),
        }

    save_progress(data)

    all_tasks = merge_with_metadata(data)
    return next(t for t in all_tasks if t["id"] == task_id)


def mark_verified(
    task_id: str,
    *,
    by: str,
    evidence: str,
    last_check: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Auto-mark a task as done after verification passed.

    Sets verified=True with verification_type='auto'. Also marks done=True
    (auto-verify passing means the task is genuinely complete).
    """
    validate_task_id(task_id)
    data = load_progress()
    existing = data["implementation"].get(task_id, {})
    data["implementation"][task_id] = {
        "done": True,
        "by": by,
        "ts": int(time.time()),
        "note": existing.get("note", ""),
        "verified": True,
        "verified_by": by,
        "verified_at": int(time.time()),
        "verification_type": "auto",
        "evidence": evidence,
        "last_check": last_check,
    }
    save_progress(data)

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
    """Clear all progress. Used by 'Reset Progress' button.

    Also clears the business-entity inventory so a re-run starts clean.
    """
    save_progress({"schema_version": SCHEMA_VERSION, "implementation": {}})
    try:
        from api.asset_inventory import clear_inventory
        clear_inventory()
    except Exception:
        # 清库存失败不应阻塞进度重置
        pass


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


def get_full_state(current_user: Optional[str] = None) -> dict[str, Any]:
    """Return full state for GET endpoint: schema, tasks, summary.

    `current_user` (optional, str) is the username of the caller; when provided
    it is included as ``current_user`` in the response so the UI can render the
    "当前用户" label even when no task has been completed yet (previously the
    frontend derived this from ``tasks[].by``, which is ``None`` for every task
    on a fresh state and therefore rendered ``unknown``).
    """
    data = _ensure_first_seen(load_progress())
    tasks = merge_with_metadata(data)
    payload = {
        "schema_version": data["schema_version"],
        "deployment_id": data["deployment_id"],
        "first_seen_at": data["first_seen_at"],
        "tasks": tasks,
        "summary": compute_summary(tasks),
    }
    if current_user is not None:
        payload["current_user"] = current_user
    return payload


# ── Task 7: CSV validation ──────────────────────────────────────────────────


_REQUIRED_COLUMNS = ["from_label", "from_name", "properties", "to_label", "to_name"]
_MAX_ROWS = 10000
_IPV4_RE = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")


def _is_valid_ipv4(ip: str) -> bool:
    if not _IPV4_RE.match(ip):
        return False
    return all(0 <= int(octet) <= 255 for octet in ip.split("."))


def _is_valid_label(label: str) -> bool:
    """允许 label 由字母/数字/下划线/连字符/中文组成，避免恶意字符。"""
    if not label or len(label) > 64:
        return False
    return bool(re.match(r"^[A-Za-z0-9_\-一-龥]+$", label))


def _is_valid_name(name: str) -> bool:
    """name 是节点唯一标识，长度上限 128。"""
    return bool(name) and len(name) <= 128


def _is_valid_properties(props: str) -> bool:
    """properties 必须是合法 JSON 字符串（可空）。

    宽容处理：允许空。对于包含未转义双引号的 CSV 字段值，
    csv 解析会自动截断（变成不完整 JSON），这种情况也宽容通过：只要以 { 开头，
    即使 { 比 } 多也认为可能是 JSON object 起点。
    """
    if not props or not props.strip():
        return True
    try:
        parsed = json.loads(props)
        return isinstance(parsed, (dict, list))
    except (ValueError, TypeError):
        stripped = props.strip()
        # 启发式：看起来像 JSON object 起点则宽容通过
        if stripped.startswith("{") and stripped.count("{") >= stripped.count("}"):
            return True
        return False


def validate_business_entity_csv(content: str, filename: str = "test.csv") -> dict[str, Any]:
    """Validate Neo4j 5-column CSV content.

    Returns ok=True on success or detailed errors.
    5 列：from_label, from_name, properties, to_label, to_name
    - 实体行：to_label/to_name 留空
    - 关系行：5 列都填，rel_type 写在 properties 里
    """
    if not filename.lower().endswith(".csv"):
        return {"ok": False, "error": "unsupported_format", "format": filename.split(".")[-1]}

    reader = csv.DictReader(io.StringIO(content))
    headers = reader.fieldnames or []
    missing = [c for c in _REQUIRED_COLUMNS if c not in headers]
    if missing:
        return {"ok": False, "error": "missing_columns", "missing": missing}

    failed_rows = []
    total = 0
    entity_count = 0
    relation_count = 0
    seen_entities = set()  # (label, name) 唯一性

    for line_no, row in enumerate(reader, start=2):
        if not any((v or "").strip() for v in row.values()):
            continue  # 空行
        total += 1
        if total > _MAX_ROWS:
            return {
                "ok": False,
                "error": "size_limit",
                "detail": f"超过 {_MAX_ROWS} 行上限",
                "rows_seen": total,
            }

        from_label = (row.get("from_label") or "").strip()
        from_name = (row.get("from_name") or "").strip()
        properties = (row.get("properties") or "").strip()
        to_label = (row.get("to_label") or "").strip()
        to_name = (row.get("to_name") or "").strip()

        # 起点必填
        if not _is_valid_label(from_label):
            failed_rows.append({"line": line_no, "field": "from_label", "reason": f"标签不合法（{from_label}）"})
        if not _is_valid_name(from_name):
            failed_rows.append({"line": line_no, "field": "from_name", "reason": f"必填且长度≤128（{from_name}）"})

        # properties 必须是合法 JSON（宽容，详见 _is_valid_properties）
        if not _is_valid_properties(properties):
            failed_rows.append({"line": line_no, "field": "properties", "reason": f"JSON 解析失败（{properties[:50]}）"})

        # 区分实体行 / 关系行
        is_relation = bool(to_label and to_name)
        if is_relation:
            relation_count += 1
            if not _is_valid_label(to_label):
                failed_rows.append({"line": line_no, "field": "to_label", "reason": f"标签不合法（{to_label}）"})
            if not _is_valid_name(to_name):
                failed_rows.append({"line": line_no, "field": "to_name", "reason": f"必填且长度≤128（{to_name}）"})
            # 关系必须有 rel_type
            if properties and "\"rel_type\"" not in properties:
                failed_rows.append({"line": line_no, "field": "properties", "reason": "关系行 properties 必须包含 rel_type"})
        else:
            entity_count += 1
            # 实体行：to_label/to_name 必须留空
            if to_label or to_name:
                failed_rows.append({"line": line_no, "field": "to_label/to_name", "reason": "实体行 4-5 列必须留空"})
            # 实体唯一性（(label, name) 必须唯一）
            key = (from_label, from_name)
            if key in seen_entities:
                failed_rows.append({"line": line_no, "field": "from_label+from_name", "reason": f"实体重复：{from_label} {from_name}"})
            else:
                seen_entities.add(key)

    if failed_rows:
        return {
            "ok": False,
            "error": "validation",
            "failed_rows": failed_rows[:100],
            "total_failed": len(failed_rows),
            "total_rows": total,
        }

    return {"ok": True, "total_rows": total, "entity_count": entity_count, "relation_count": relation_count, "failed_rows": []}


# ── Task 8: import_business_entities ────────────────────────────────────────


def import_business_entities(content: str, *, filename: str, by: str) -> dict[str, Any]:
    """Validate + import business entities CSV. Real-persists to inventory.

    On success, writes rows to api/asset_inventory and auto-verifies
    1.3_import_entities (verified_by=auto, evidence records row/host counts).
    """
    from api.asset_inventory import upsert_inventory

    result = upsert_inventory(content, filename=filename, by=by)
    if not result["ok"]:
        return result

    # 落盘成功后：1.3_import_entities 标记 done + 自动验证通过
    evidence = (
        f"已写入 {result['business_lines']} 个业务线，共 "
        f"{result['total_hosts']} 台主机（本次 {result['imported_rows']} 行）"
    )
    mark_verified(
        "1.3_import_entities",
        by=by,
        evidence=evidence,
        last_check={"passed": True, "evidence": evidence},
    )
    result["task_updated"] = "1.3_import_entities"
    result["evidence"] = evidence
    return result


def import_business_entities_xlsx(raw: bytes, *, filename: str, by: str) -> dict[str, Any]:
    """Import a 3-sheet xlsx (entity/relation/help) and persist to inventory.

    解析实体页与关系页，写入 api/asset_inventory，并自动验证
    1.3_import_entities。
    """
    try:
        from api.guidance_xlsx import parse_template_xlsx, parse_properties, extract_busi_name
    except Exception as e:
        return {"ok": False, "error": "xlsx_module_unavailable", "detail": str(e)}

    parsed = parse_template_xlsx(raw)
    entity_rows = parsed.get("entity_rows", [])
    relation_rows = parsed.get("relation_rows", [])

    if not entity_rows and not relation_rows:
        return {"ok": False, "error": "empty", "detail": "实体页/关系页都没有有效数据，请按模板填写后重试"}

    from api import asset_inventory as _ai

    data = _ai.load_inventory()
    entities = data.setdefault("entities", [])
    relations = data.setdefault("relations", [])
    business_lines = data.setdefault("business_lines", {})

    seen_entities = {(e.get("label", ""), e.get("name", "")) for e in entities if isinstance(e, dict)}
    seen_relations = {
        (r.get("from_label", ""), r.get("from_name", ""), r.get("rel_type", ""),
         r.get("to_label", ""), r.get("to_name", ""))
        for r in relations if isinstance(r, dict)
    }

    entity_added = 0
    relation_added = 0
    new_host_ips = 0

    # 实体页
    for row in entity_rows:
        label = row.get("label", "").strip()
        name = row.get("name", "").strip()
        if not label or not name:
            continue
        props = parse_properties(row.get("properties", ""))
        # 业务线：busi_name 列优先，其次 properties.busi_name/business_line
        busi_name = extract_busi_name(props, explicit=row.get("busi_name", ""))
        if busi_name:
            props["busi_name"] = busi_name
        key = (label, name)
        if key not in seen_entities:
            entities.append({"label": label, "name": name, "properties": props})
            seen_entities.add(key)
            entity_added += 1
        if label == "Host" and _is_valid_ipv4(name):
            if busi_name:
                bucket = business_lines.setdefault(busi_name, [])
                if not isinstance(bucket, list):
                    bucket = []
                    business_lines[busi_name] = bucket
                if name not in bucket:
                    bucket.append(name)
                    new_host_ips += 1

    # 关系页
    for row in relation_rows:
        from_label = row.get("from_label", "").strip()
        from_name = row.get("from_name", "").strip()
        rel_type = row.get("rel_type", "").strip() or "RELATED_TO"
        to_label = row.get("to_label", "").strip()
        to_name = row.get("to_name", "").strip()
        if not (from_label and from_name and to_label and to_name):
            continue
        rel_key = (from_label, from_name, rel_type, to_label, to_name)
        if rel_key not in seen_relations:
            relations.append({
                "from_label": from_label,
                "from_name": from_name,
                "rel_type": rel_type,
                "to_label": to_label,
                "to_name": to_name,
            })
            seen_relations.add(rel_key)
            relation_added += 1

    data["schema_version"] = _ai.SCHEMA_VERSION
    data["imported_at"] = int(time.time())
    data["imported_by"] = by
    data["last_filename"] = filename
    _ai.save_inventory(data)

    result = {
        "ok": True,
        "entity_count": entity_added,
        "relation_count": relation_added,
        "imported_rows": entity_added + relation_added,
        "business_lines": len(business_lines),
        "total_hosts": _ai.count_hosts(),
        "total_entities": _ai.count_entities(),
        "total_relations": _ai.count_relations(),
        "task_updated": "1.3_import_entities",
    }
    evidence = (
        f"已写入 {entity_added} 个实体、{relation_added} 条关系；"
        f"{len(business_lines)} 个业务线，共 {_ai.count_hosts()} 台主机"
    )
    mark_verified(
        "1.3_import_entities",
        by=by,
        evidence=evidence,
        last_check={"passed": True, "evidence": evidence},
    )
    result["evidence"] = evidence
    return result


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
                src = "自动验证" if t.get("verification_type") == "auto" else "手动标记"
                base += f" ({src} by {t['by']}, {_format_ts(t['ts'])})"
            if t.get("evidence"):
                base += f" — 证据：{t['evidence']}"
            elif t.get("note"):
                base += f" — 备注：{t['note']}"
            lines.append(base)
        lines.append("")

    return "\n".join(lines)


# ── Task 10: 自主验证（verifier） ────────────────────────────────────────────


def _check_1_3_import_entities() -> dict[str, Any]:
    """1.3_import_entities：资产库存已写入业务线数据即通过。

    该步骤在 HTTP 层通过上传导入完成（校验 + 落盘一次完成），导入成功后
    自动 mark_verified；本函数用于刷新时的轻量复核。
    """
    from api.asset_inventory import check_inventory_loaded
    return check_inventory_loaded()


def _check_2_2_batch_import() -> dict[str, Any]:
    """2.2 批量导入知识库：导入动作在 HTTP 层就地完成并落盘 last_check。

    此处返回未检查，避免误报。
    """
    return {"passed": False, "evidence": "尚未执行批量导入", "available": False}


def _check_2_3_verify_search(query: Optional[str] = None) -> dict[str, Any]:
    """2.3 验证可搜索：调用知识库搜索接口，results>0 即通过。

    优先使用调用方传入的查询词；否则用高频业务词探测。
    """
    try:
        from api.obsidian_notes import search_notes
    except Exception as e:  # pragma: no cover - import guard
        return {"passed": False, "evidence": f"知识库模块不可用：{e}"}

    probes = [query, "故障", "FAQ", "排查", "巡检"] if (query or "").strip() else ["故障", "FAQ", "排查", "巡检"]
    for q in probes:
        q = (q or "").strip()
        if not q:
            continue
        try:
            res = search_notes(q)
            results = (res or {}).get("results", [])
            if results:
                return {
                    "passed": True,
                    "evidence": f"知识库可检索：查询“{q}”命中 {len(results)} 条",
                    "matched": q,
                    "count": len(results),
                }
        except Exception as e:
            return {"passed": False, "evidence": f"知识库搜索失败：{e}"}
    return {"passed": False, "evidence": "知识库中未检索到 FAQ 相关内容"}


def _check_3_1_select_business_line() -> dict[str, Any]:
    from api.asset_inventory import check_inventory_loaded
    return check_inventory_loaded()


# 任务 id → 校验函数映射（仅在 AUTO_VERIFIABLE_TASKS 内注册）
_VERIFIERS: dict[str, Any] = {
    "1.3_import_entities": _check_1_3_import_entities,
    "2.3_verify_search": _check_2_3_verify_search,
    "3.1_select_business_line": _check_3_1_select_business_line,
    # 2.2_batch_import 依赖就地操作动作，不在映射内
    # （由 HTTP 层在动作完成后直接落盘 last_check + mark_verified）
}


def check_task(task_id: str, **params) -> dict[str, Any]:
    """Run the verifier for a task (no state mutation).

    `params` are passed to the verifier (e.g. query for 2.3_verify_search).
    """
    validate_task_id(task_id)
    verifier = _VERIFIERS.get(task_id)
    if not verifier:
        return {
            "passed": False,
            "evidence": "该步骤无自动验证能力，请通过就地操作或手动标记完成",
            "available": False,
        }
    try:
        result = verifier(**params)
    except Exception as e:
        logger = __import__("logging").getLogger("webui.guidance")
        logger.warning("verifier %s failed: %s", task_id, e)
        result = {"passed": False, "evidence": f"验证失败：{e}"}
    result.setdefault("available", True)
    return result


def run_verification(task_id: str, *, by: str, **params) -> dict[str, Any]:
    """Run the verifier; if passed, auto-mark the task done (verified=auto).

    Returns a result dict:
        {ok: True, passed: bool, evidence: str, task: <merged task dict>}
    If not passed, the task is NOT marked; the check result is returned so the
    frontend can show why.
    """
    validate_task_id(task_id)
    result = check_task(task_id, **params)
    if result["passed"]:
        task = mark_verified(
            task_id,
            by=by,
            evidence=result["evidence"],
            last_check={"passed": True, "evidence": result["evidence"]},
        )
        return {"ok": True, "passed": True, "evidence": result["evidence"], "task": task}
    return {"ok": True, "passed": False, "evidence": result["evidence"], "task": None}


def record_verification(
    task_id: str,
    *,
    by: str,
    passed: bool,
    evidence: str,
) -> dict[str, Any]:
    """Record a verification check result into last_check.

    If passed=True, also auto-marks the task done (verified=auto). This is used
    by HTTP handlers that perform an in-place action (CSV validate, batch import)
    and want to both record the evidence and, when successful, mark the task.
    """
    validate_task_id(task_id)
    data = load_progress()
    existing = data["implementation"].get(task_id, {})
    existing["last_check"] = {"passed": passed, "evidence": evidence}
    data["implementation"][task_id] = existing
    save_progress(data)

    if passed:
        task = mark_verified(
            task_id,
            by=by,
            evidence=evidence,
            last_check={"passed": True, "evidence": evidence},
        )
        return {"ok": True, "passed": True, "evidence": evidence, "task": task}
    return {"ok": True, "passed": False, "evidence": evidence, "task": None}