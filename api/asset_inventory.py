"""业务实体（资产库存）存储层。

实施助手 1.3_import_entities 导入的 Neo4j 实体关系 CSV 真实落盘到
当前 profile 的 ~/.hermes/asset_inventory.yaml，并提供查询接口，
供 1.3_verify / 3.1 等步骤做"自主验证"。

数据模型 schema v2（Neo4j 5 列格式）：
    schema_version: 2
    imported_at: <epoch>
    imported_by: <username>
    business_lines:                          # 业务线分组（由 Host 实体的 properties.busi_name 提取）
      "<业务线名称>": ["ip1", "ip2", ...]   # 去重后的主机 IP 列表
    entities:                                 # 全部实体（Host/Service/Program/Api/Middleware...）
      - {"label": "Host", "name": "12.7.0.11", "properties": {...}}
    relations:                                # 全部关系
      - {"from_label": "Service", "from_name": "commander",
         "rel_type": "DEPLOY_ON",
         "to_label": "Host", "to_name": "12.7.0.11"}

写入采用原子替换（UUID tmp + os.replace），与 api/guidance_progress.py 一致。
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

import yaml

from api.profiles import get_active_hermes_home

SCHEMA_VERSION = 2

# 与 guidance_progress._REQUIRED_COLUMNS 保持一致
REQUIRED_COLUMNS = ["from_label", "from_name", "properties", "to_label", "to_name"]
_MAX_ROWS = 10000
_IPV4_RE = re.compile(r"^(\d{1,3}\.){3}\d{1,3}$")


def _inventory_path() -> Path:
    """Return the active profile's ~/.hermes/asset_inventory.yaml."""
    return get_active_hermes_home() / "asset_inventory.yaml"


def _atomic_write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Atomically write data to YAML via UUID tmp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        os.replace(tmp, path)
    except (OSError, yaml.YAMLError) as e:
        if tmp.exists():
            tmp.unlink()
        raise RuntimeError(f"asset_inventory.yaml write failed: {e}") from e


def load_inventory() -> dict[str, Any]:
    """Read asset_inventory.yaml; return empty schema if missing/invalid."""
    path = _inventory_path()
    if not path.exists():
        return {
            "schema_version": SCHEMA_VERSION,
            "business_lines": {},
            "entities": [],
            "relations": [],
        }
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError:
        return {
            "schema_version": SCHEMA_VERSION,
            "business_lines": {},
            "entities": [],
            "relations": [],
        }

    if not isinstance(data, dict):
        return {
            "schema_version": SCHEMA_VERSION,
            "business_lines": {},
            "entities": [],
            "relations": [],
        }

    data.setdefault("schema_version", SCHEMA_VERSION)
    data.setdefault("business_lines", {})
    data.setdefault("entities", [])
    data.setdefault("relations", [])
    if not isinstance(data["business_lines"], dict):
        data["business_lines"] = {}
    if not isinstance(data["entities"], list):
        data["entities"] = []
    if not isinstance(data["relations"], list):
        data["relations"] = []
    return data


def save_inventory(data: dict[str, Any]) -> None:
    """Atomically write inventory to disk."""
    _atomic_write_yaml(_inventory_path(), data)


def _is_valid_ipv4(ip: str) -> bool:
    if not _IPV4_RE.match(ip):
        return False
    return all(0 <= int(octet) <= 255 for octet in ip.split("."))


def _parse_props(raw: str) -> dict[str, Any]:
    """Parse properties JSON string; return {} on empty/invalid."""
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def get_business_lines() -> list[str]:
    """Return sorted list of business-line names that have at least one host."""
    data = load_inventory()
    lines = [
        name
        for name, ips in data.get("business_lines", {}).items()
        if isinstance(ips, list) and ips
    ]
    return sorted(lines)


def count_hosts() -> int:
    """Return total unique host count across all business lines."""
    data = load_inventory()
    seen: set[str] = set()
    for ips in data.get("business_lines", {}).values():
        if isinstance(ips, list):
            for ip in ips:
                if isinstance(ip, str):
                    seen.add(ip)
    return len(seen)


def count_entities() -> int:
    """Return total unique entity count."""
    data = load_inventory()
    seen = set()
    for e in data.get("entities", []):
        if isinstance(e, dict):
            seen.add((e.get("label", ""), e.get("name", "")))
    return len(seen)


def count_relations() -> int:
    """Return total unique relation count."""
    data = load_inventory()
    seen = set()
    for r in data.get("relations", []):
        if isinstance(r, dict):
            seen.add((
                r.get("from_label", ""),
                r.get("from_name", ""),
                r.get("rel_type", ""),
                r.get("to_label", ""),
                r.get("to_name", ""),
            ))
    return len(seen)


def business_line_hosts(business_line: str) -> list[str]:
    """Return the host IP list for a given business line (sorted)."""
    data = load_inventory()
    ips = data.get("business_lines", {}).get(business_line, [])
    if not isinstance(ips, list):
        return []
    return sorted(ip for ip in ips if isinstance(ip, str))


def has_data() -> bool:
    """True if at least one entity has been imported."""
    return count_entities() > 0


def upsert_inventory(
    content: str,
    *,
    filename: str,
    by: str,
) -> dict[str, Any]:
    """Validate + upsert Neo4j 5-column CSV into inventory.

    处理实体行（to_label/to_name 留空）和关系行（5 列都填）：
    - 实体行：累加到 entities[]；若 label=Host 且 properties.busi_name 存在，
      累加到 business_lines[busi_name] 作为主机 IP
    - 关系行：累加到 relations[]

    Returns a result dict with entity_count / relation_count / business_lines / total_hosts.
    """
    from api.guidance_progress import validate_business_entity_csv

    validation = validate_business_entity_csv(content, filename=filename)
    if not validation["ok"]:
        return validation

    data = load_inventory()
    business_lines = data.setdefault("business_lines", {})
    entities = data.setdefault("entities", [])
    relations = data.setdefault("relations", [])

    # 已有实体/关系去重
    seen_entities = {(e.get("label", ""), e.get("name", "")) for e in entities if isinstance(e, dict)}
    seen_relations = {(
        r.get("from_label", ""), r.get("from_name", ""),
        r.get("rel_type", ""), r.get("to_label", ""), r.get("to_name", ""),
    ) for r in relations if isinstance(r, dict)}

    reader = csv.DictReader(io.StringIO(content))
    entity_added = 0
    relation_added = 0
    new_host_ips = 0

    for row in reader:
        if not any((v or "").strip() for v in row.values()):
            continue

        from_label = (row.get("from_label") or "").strip()
        from_name = (row.get("from_name") or "").strip()
        properties_raw = (row.get("properties") or "").strip()
        to_label = (row.get("to_label") or "").strip()
        to_name = (row.get("to_name") or "").strip()

        if not from_label or not from_name:
            continue

        props = _parse_props(properties_raw)
        is_relation = bool(to_label and to_name)

        if is_relation:
            rel_type = props.get("rel_type", "RELATED_TO")
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
        else:
            entity_key = (from_label, from_name)
            if entity_key not in seen_entities:
                entities.append({
                    "label": from_label,
                    "name": from_name,
                    "properties": props,
                })
                seen_entities.add(entity_key)
                entity_added += 1
            # 业务线分组：Host 实体 + properties.busi_name → 业务线
            if from_label == "Host" and _is_valid_ipv4(from_name):
                bl = (props.get("busi_name") or props.get("business_line") or "").strip()
                if bl:
                    bucket = business_lines.setdefault(bl, [])
                    if not isinstance(bucket, list):
                        bucket = []
                        business_lines[bl] = bucket
                    if from_name not in bucket:
                        bucket.append(from_name)
                        new_host_ips += 1

    data["schema_version"] = SCHEMA_VERSION
    data["imported_at"] = int(time.time())
    data["imported_by"] = by
    data["last_filename"] = filename
    save_inventory(data)

    return {
        "ok": True,
        "imported_rows": entity_added + relation_added,
        "entity_count": entity_added,
        "relation_count": relation_added,
        "new_hosts": new_host_ips,
        "business_lines": len(business_lines),
        "total_hosts": count_hosts(),
        "total_entities": count_entities(),
        "total_relations": count_relations(),
        "task_updated": "1.3_import_entities",
    }


def clear_inventory() -> None:
    """Clear all business-entity data. Used by Reset Progress."""
    save_inventory({
        "schema_version": SCHEMA_VERSION,
        "business_lines": {},
        "entities": [],
        "relations": [],
    })


# ── 供 guidance_progress 自主验证使用 ────────────────────────────────────────


def check_inventory_loaded() -> dict[str, Any]:
    """Return verification result for task 1.3_verify / 3.1.

    passed = at least one entity imported.
    """
    data = load_inventory()
    entities = count_entities()
    relations = count_relations()
    lines = [
        name for name, ips in data.get("business_lines", {}).items()
        if isinstance(ips, list) and ips
    ]
    passed = entities > 0
    if entities > 0 and lines:
        evidence = (
            f"已写入 {entities} 个实体、{relations} 条关系；"
            f"{len(lines)} 个业务线，共 {count_hosts()} 台主机"
        )
    elif entities > 0:
        evidence = f"已写入 {entities} 个实体、{relations} 条关系"
    else:
        evidence = "尚未导入任何业务实体数据"
    return {
        "passed": passed,
        "evidence": evidence,
        "entities": entities,
        "relations": relations,
        "business_lines": lines,
        "total_hosts": count_hosts(),
    }
