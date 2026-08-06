"""图库字典管理模块。

提供节点标签、关系类型、属性名、属性值的中英文映射管理。
独立于后端（Neo4j / Mock 通用），持久化到 DEFAULT_WORKSPACE/.graph/graph_dict.json。
"""

from __future__ import annotations
import csv
import io
import json
import logging
import os
import threading
import time
import uuid
from typing import Any

from api.config import DEFAULT_WORKSPACE

logger = logging.getLogger(__name__)

DICT_FILE = os.environ.get(
    "GRAPH_DICT_FILE", str(DEFAULT_WORKSPACE / ".graph" / "graph_dict.json")
)

# 内置字典条目（首次启动时 seed）
_BUILTIN_ENTRIES: list[dict] = [
    # ── 节点标签 ──
    {"category": "node_label", "source": "Host", "target": "主机"},
    {"category": "node_label", "source": "Service", "target": "服务"},
    {"category": "node_label", "source": "Incident", "target": "事件"},
    {"category": "node_label", "source": "Runbook", "target": "预案"},
    {"category": "node_label", "source": "Container", "target": "容器"},
    {"category": "node_label", "source": "Pod", "target": "Pod"},
    {"category": "node_label", "source": "Deployment", "target": "部署"},
    {"category": "node_label", "source": "Namespace", "target": "命名空间"},
    {"category": "node_label", "source": "Application", "target": "应用"},
    {"category": "node_label", "source": "Database", "target": "数据库"},
    {"category": "node_label", "source": "Cluster", "target": "集群"},
    {"category": "node_label", "source": "Room", "target": "机房"},
    {"category": "node_label", "source": "Rack", "target": "机架"},
    # ── 关系类型 ──
    {"category": "rel_type", "source": "DEPENDS_ON", "target": "依赖"},
    {"category": "rel_type", "source": "RUNS_ON", "target": "运行于"},
    {"category": "rel_type", "source": "AFFECTS", "target": "影响"},
    {"category": "rel_type", "source": "APPLIES_TO", "target": "应用于"},
    {"category": "rel_type", "source": "HAS", "target": "包含"},
    {"category": "rel_type", "source": "DEPLOY", "target": "部署于"},
    {"category": "rel_type", "source": "CONNECTS_TO", "target": "连接"},
    {"category": "rel_type", "source": "OWNS", "target": "拥有"},
    {"category": "rel_type", "source": "MANAGES", "target": "管理"},
    {"category": "rel_type", "source": "MONITORS", "target": "监控"},
    # ── 属性名 ──
    {"category": "property_key", "source": "name", "target": "名称"},
    {"category": "property_key", "source": "ip", "target": "IP地址"},
    {"category": "property_key", "source": "host_ip", "target": "主机IP"},
    {"category": "property_key", "source": "version", "target": "版本"},
    {"category": "property_key", "source": "title", "target": "标题"},
    {"category": "property_key", "source": "severity", "target": "严重级别"},
    {"category": "property_key", "source": "status", "target": "状态"},
    {"category": "property_key", "source": "env", "target": "环境"},
    {"category": "property_key", "source": "region", "target": "区域"},
    {"category": "property_key", "source": "owner", "target": "负责人"},
    {"category": "property_key", "source": "description", "target": "描述"},
    {"category": "property_key", "source": "serviceName", "target": "服务名"},
    {"category": "property_key", "source": "namespace", "target": "命名空间"},
    # ── 属性值 ──
    {"category": "property_value", "source": "P0", "target": "严重"},
    {"category": "property_value", "source": "P1", "target": "高"},
    {"category": "property_value", "source": "P2", "target": "中"},
    {"category": "property_value", "source": "P3", "target": "低"},
    {"category": "property_value", "source": "production", "target": "生产"},
    {"category": "property_value", "source": "staging", "target": "预发布"},
    {"category": "property_value", "source": "testing", "target": "测试"},
    {"category": "property_value", "source": "development", "target": "开发"},
    {"category": "property_value", "source": "running", "target": "运行中"},
    {"category": "property_value", "source": "stopped", "target": "已停止"},
    {"category": "property_value", "source": "healthy", "target": "健康"},
    {"category": "property_value", "source": "degraded", "target": "降级"},
    {"category": "property_value", "source": "down", "target": "宕机"},
    {"category": "node_label", "source": "Api", "target": "接口"},
    {"category": "node_label", "source": "Cabinet", "target": "机柜"},
    {"category": "node_label", "source": "HighConfidence", "target": "高置信度"},
    {"category": "node_label", "source": "Middleware", "target": "中间件"},
    {"category": "node_label", "source": "Pattern", "target": "模式"},
    {"category": "node_label", "source": "Port", "target": "端口"},
    {"category": "node_label", "source": "Program", "target": "程序"},
    {"category": "node_label", "source": "RootCause", "target": "根因"},
    {"category": "rel_type", "source": "EXPOSES", "target": "暴露"},
    {"category": "rel_type", "source": "HAS_API", "target": "提供接口"},
    {"category": "rel_type", "source": "HAS_CABINET", "target": "位于机柜"},
    {"category": "rel_type", "source": "HAS_HOST", "target": "属于主机"},
    {"category": "rel_type", "source": "HAS_PATTERN", "target": "匹配模式"},
    {"category": "rel_type", "source": "HAS_ROOT_CAUSE", "target": "根因"},
    {"category": "rel_type", "source": "RUNS", "target": "运行"},
    {"category": "rel_type", "source": "RUNS_CONTAINER", "target": "运行容器"},
    {"category": "rel_type", "source": "RUN_SERVICE", "target": "运行服务"},
    {"category": "rel_type", "source": "SIMILAR_TO", "target": "相似于"},
    {"category": "rel_type", "source": "DEPEND_ON", "target": "依赖"},
    {"category": "property_key", "source": "hostname", "target": "主机名"},
    {"category": "property_key", "source": "image", "target": "镜像"},
    {"category": "property_key", "source": "os", "target": "操作系统"},
    {"category": "property_key", "source": "port", "target": "端口"},
    {"category": "property_key", "source": "protocol", "target": "协议"},
    {"category": "property_key", "source": "method", "target": "方法"},
    {"category": "property_key", "source": "path", "target": "路径"},
    {"category": "property_key", "source": "type", "target": "类型"},
    {"category": "property_key", "source": "code", "target": "编码"},
    {"category": "property_key", "source": "number", "target": "编号"},
    {"category": "property_key", "source": "cpu", "target": "CPU"},
    {"category": "property_key", "source": "memory", "target": "内存"},
    {"category": "property_key", "source": "disk", "target": "磁盘"},
    {"category": "property_key", "source": "cpu_cores", "target": "CPU核数"},
    {"category": "property_key", "source": "cpu_model", "target": "CPU型号"},
    {"category": "property_key", "source": "memory_total", "target": "总内存"},
    {"category": "property_key", "source": "createdAt", "target": "创建时间"},
    {"category": "property_key", "source": "updatedAt", "target": "更新时间"},
    {"category": "property_key", "source": "created_at", "target": "创建时间"},
    {"category": "property_key", "source": "updated_at", "target": "更新时间"},
    {"category": "property_key", "source": "discovered_at", "target": "发现时间"},
    {"category": "property_key", "source": "confidence", "target": "置信度"},
    {"category": "property_key", "source": "evidence", "target": "证据"},
    {"category": "property_key", "source": "fix", "target": "修复建议"},
    {"category": "property_key", "source": "listening_ports", "target": "监听端口"},
    {"category": "property_key", "source": "network_ips", "target": "网卡IP"},
    {"category": "property_key", "source": "log_path", "target": "日志路径"},
    {"category": "property_key", "source": "log_sample", "target": "日志样本"},
    {"category": "property_key", "source": "ssh_user", "target": "SSH用户"},
    {"category": "property_key", "source": "ssh_port", "target": "SSH端口"},
    {"category": "property_key", "source": "ssh_password", "target": "SSH密码"},
    {"category": "property_key", "source": "last_deploy_scan", "target": "最近部署扫描"},
    {"category": "property_key", "source": "cabinetNo", "target": "机柜编号"},
    {"category": "property_key", "source": "root_cause", "target": "根因"},
    {"category": "property_key", "source": "service", "target": "服务"},
    {"category": "property_key", "source": "disks", "target": "磁盘列表"},
    {"category": "property_key", "source": "pattern", "target": "模式"},
    {"category": "property_key", "source": "id", "target": "ID"},
    {"category": "property_value", "source": "active", "target": "活跃"},
    {"category": "property_value", "source": "critical", "target": "严重"},
    {"category": "property_value", "source": "warning", "target": "警告"},
    {"category": "property_value", "source": "info", "target": "信息"},
    {"category": "property_value", "source": "resolved", "target": "已解决"},
    {"category": "property_value", "source": "recovered", "target": "已恢复"},
    {"category": "property_value", "source": "unhealthy", "target": "不健康"},
    {"category": "property_value", "source": "offline", "target": "离线"},
    {"category": "property_value", "source": "online", "target": "在线"},
]


def _gen_id() -> str:
    return f"dict-{uuid.uuid4().hex[:12]}"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _default_data() -> dict:
    now = _now()
    items = []
    for entry in _BUILTIN_ENTRIES:
        items.append({
            "id": _gen_id(),
            "category": entry["category"],
            "source": entry["source"],
            "target": entry["target"],
            "scope": entry.get("scope", ""),
            "description": entry.get("description", ""),
            "enabled": True,
            "created_at": now,
            "updated_at": now,
        })
    return {"version": 1, "items": items}


class DictManager:
    """字典管理器，线程安全，持久化到 JSON 文件。"""

    def __init__(self, file_path: str = DICT_FILE):
        self.file_path = file_path
        self._lock = threading.Lock()
        self._data: dict | None = None
        self._load()

    # ── 文件 I/O ────────────────────────────────────────

    def _load(self):
        """加载或初始化字典文件。"""
        path = self.file_path
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    self._data = json.load(f)
                logger.info("Loaded %d dict entries from %s",
                            len(self._data.get("items", [])), path)
                # 迁移：旧数据没有 version 或 items 结构
                if not isinstance(self._data, dict) or "items" not in self._data:
                    raise ValueError("invalid format")
                return
            except Exception as e:
                logger.warning("Failed to load dict file %s: %s, reinitializing", path, e)
        # 首次启动：写入内置字典
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._data = _default_data()
        self._flush()
        logger.info("Seeded %d built-in dict entries to %s",
                    len(self._data["items"]), path)

    def _flush(self):
        """原子写 JSON 文件。"""
        path = self.file_path
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception:
            try:
                os.remove(tmp)
            except Exception:
                pass
            raise

    def _ensure_loaded(self):
        if self._data is None:
            self._load()

    # ── 条目 CRUD ───────────────────────────────────────

    def list_items(self, category: str | None = None,
                   query: str | None = None,
                   page: int = 1, size: int = 50) -> dict:
        """分页查询字典条目。"""
        self._ensure_loaded()
        items = self._data["items"]
        if category and category != "all":
            items = [i for i in items if i["category"] == category]
        if query:
            q = query.lower()
            items = [i for i in items
                     if q in i["source"].lower()
                     or q in i["target"].lower()
                     or q in i.get("description", "").lower()]
        total = len(items)
        start = (page - 1) * size
        end = start + size
        return {
            "items": items[start:end],
            "total": total,
            "page": page,
            "size": size,
        }

    def get_item(self, item_id: str) -> dict | None:
        self._ensure_loaded()
        for item in self._data["items"]:
            if item["id"] == item_id:
                return dict(item)
        return None

    def create_item(self, entry: dict) -> dict:
        """创建新条目。返回创建的条目。"""
        self._ensure_loaded()
        now = _now()
        item = {
            "id": _gen_id(),
            "category": entry.get("category", "node_label"),
            "source": entry.get("source", "").strip(),
            "target": entry.get("target", "").strip(),
            "scope": entry.get("scope", "").strip(),
            "description": entry.get("description", "").strip(),
            "enabled": entry.get("enabled", True),
            "created_at": now,
            "updated_at": now,
        }
        self._validate_item(item)
        with self._lock:
            self._data["items"].append(item)
            self._flush()
        return item

    def update_item(self, item_id: str, patch: dict) -> dict | None:
        """更新条目。返回更新后的条目，不存在返回 None。"""
        self._ensure_loaded()
        with self._lock:
            for i, item in enumerate(self._data["items"]):
                if item["id"] == item_id:
                    if "category" in patch:
                        item["category"] = patch["category"]
                    if "source" in patch:
                        item["source"] = patch["source"].strip()
                    if "target" in patch:
                        item["target"] = patch["target"].strip()
                    if "scope" in patch:
                        item["scope"] = patch["scope"].strip()
                    if "description" in patch:
                        item["description"] = patch["description"].strip()
                    if "enabled" in patch:
                        item["enabled"] = bool(patch["enabled"])
                    item["updated_at"] = _now()
                    self._validate_item(item)
                    self._data["items"][i] = item
                    self._flush()
                    return dict(item)
        return None

    def delete_item(self, item_id: str) -> bool:
        """删除条目。成功返回 True，不存在返回 False。"""
        self._ensure_loaded()
        with self._lock:
            for i, item in enumerate(self._data["items"]):
                if item["id"] == item_id:
                    self._data["items"].pop(i)
                    self._flush()
                    return True
        return False

    def toggle_item(self, item_id: str) -> dict | None:
        """切换条目启用状态。返回更新后的条目。"""
        self._ensure_loaded()
        with self._lock:
            for i, item in enumerate(self._data["items"]):
                if item["id"] == item_id:
                    item["enabled"] = not item["enabled"]
                    item["updated_at"] = _now()
                    self._data["items"][i] = item
                    self._flush()
                    return dict(item)
        return None

    # ── 批量导入 ────────────────────────────────────────

    def import_json(self, raw: str) -> dict:
        """导入 JSON 格式的字典条目列表。"""
        try:
            entries = json.loads(raw)
        except json.JSONDecodeError as e:
            return {"ok": False, "error": f"JSON 解析失败: {e}", "added": 0, "failed": 0}
        if not isinstance(entries, list):
            entries = [entries]
        return self._import_entries(entries)

    def import_csv(self, raw: str) -> dict:
        """导入 CSV 格式（表头: source,target 或 category,source,target）。"""
        reader = csv.DictReader(io.StringIO(raw))
        entries = []
        for row in reader:
            keys = [k.strip().lower() for k in row.keys()]
            entry = {}
            if "category" in keys:
                entry["category"] = row.get(
                    list(row.keys())[keys.index("category")], "node_label").strip()
            else:
                entry["category"] = "node_label"
            if "source" in keys:
                entry["source"] = row.get(
                    list(row.keys())[keys.index("source")], "").strip()
            if "target" in keys:
                entry["target"] = row.get(
                    list(row.keys())[keys.index("target")], "").strip()
            if entry.get("source") and entry.get("target"):
                entries.append(entry)
        return self._import_entries(entries)

    def _import_entries(self, entries: list[dict]) -> dict:
        """批量导入条目，跳过已存在的（source+category 相同视为重复）。"""
        self._ensure_loaded()
        added = 0
        failed = 0
        errors = []
        with self._lock:
            existing = {(i["category"], i["source"]) for i in self._data["items"]}
            for entry in entries:
                try:
                    cat = entry.get("category", "node_label")
                    src = entry.get("source", "").strip()
                    tgt = entry.get("target", "").strip()
                    if not src or not tgt:
                        failed += 1
                        errors.append(f"source/target 不能为空: {entry}")
                        continue
                    if cat not in ("node_label", "rel_type", "property_key", "property_value"):
                        failed += 1
                        errors.append(f"无效分类 '{cat}': {entry}")
                        continue
                    if (cat, src) in existing:
                        failed += 1
                        errors.append(f"已存在: [{cat}] {src}")
                        continue
                    now = _now()
                    item = {
                        "id": _gen_id(),
                        "category": cat,
                        "source": src,
                        "target": tgt,
                        "scope": entry.get("scope", "").strip(),
                        "description": entry.get("description", "").strip(),
                        "enabled": entry.get("enabled", True),
                        "created_at": now,
                        "updated_at": now,
                    }
                    self._data["items"].append(item)
                    existing.add((cat, src))
                    added += 1
                except Exception as e:
                    failed += 1
                    errors.append(str(e))
            if added > 0:
                self._flush()
        result = {"ok": True, "added": added, "failed": failed}
        if errors:
            result["errors"] = errors[:20]  # 最多返回 20 条错误
        return result

    # ── 导出 ────────────────────────────────────────────

    def export_json(self, category: str | None = None) -> str:
        """导出为 JSON 字符串。"""
        self._ensure_loaded()
        items = self._filtered_items(category)
        return json.dumps(items, ensure_ascii=False, indent=2)

    def export_yaml(self, category: str | None = None) -> str:
        """导出为简易 YAML 字符串（不引入 pyyaml 依赖）。"""
        self._ensure_loaded()
        items = self._filtered_items(category)
        lines = ["# Graph Dictionary Export", f"# Generated: {_now()}", f"# Count: {len(items)}", ""]
        for item in items:
            lines.append(f"- id: {item['id']}")
            lines.append(f"  category: {item['category']}")
            lines.append(f"  source: {item['source']}")
            lines.append(f"  target: {item['target']}")
            if item.get("scope"):
                lines.append(f"  scope: {item['scope']}")
            if item.get("description"):
                lines.append(f"  description: {item.get('description', '')}")
            lines.append(f"  enabled: {str(item['enabled']).lower()}")
            lines.append("")
        return "\n".join(lines)

    def _filtered_items(self, category: str | None) -> list[dict]:
        items = self._data["items"]
        if category and category != "all":
            items = [i for i in items if i["category"] == category]
        return items

    # ── 应用映射（给前端渲染用） ──────────────────────────

    def get_apply_mappings(self) -> dict:
        """返回已解析的映射表。

        {
            "node_labels": {"Host": "主机", ...},
            "rel_types": {"DEPENDS_ON": "依赖", ...},
            "property_keys": {"ip": "IP地址", ...},
            "property_values": {"P0": "严重", ...},
        }
        """
        self._ensure_loaded()
        result: dict[str, dict[str, str]] = {
            "node_labels": {},
            "rel_types": {},
            "property_keys": {},
            "property_values": {},
        }
        cat_map = {
            "node_label": "node_labels",
            "rel_type": "rel_types",
            "property_key": "property_keys",
            "property_value": "property_values",
        }
        for item in self._data["items"]:
            if not item.get("enabled", True):
                continue
            key = cat_map.get(item["category"])
            if key:
                result[key][item["source"]] = item["target"]
        return result

    # ── 校验 ────────────────────────────────────────────

    CATEGORIES = ("node_label", "rel_type", "property_key", "property_value")

    def _validate_item(self, item: dict):
        if item["category"] not in self.CATEGORIES:
            raise ValueError(f"无效分类: {item['category']}")
        if not item["source"] or len(item["source"]) > 200:
            raise ValueError("source 长度需在 1-200 字符之间")
        if not item["target"] or len(item["target"]) > 200:
            raise ValueError("target 长度需在 1-200 字符之间")

    # ── 统计 ────────────────────────────────────────────

    def stats(self) -> dict:
        self._ensure_loaded()
        items = self._data["items"]
        counts: dict[str, int] = {"total": len(items)}
        for cat in self.CATEGORIES:
            counts[cat] = sum(1 for i in items if i["category"] == cat)
        counts["enabled"] = sum(1 for i in items if i.get("enabled"))
        return counts


# ── 全局单例 ──────────────────────────────────────────
_manager: DictManager | None = None
_manager_lock = threading.Lock()


def get_manager() -> DictManager:
    global _manager
    if _manager is None:
        with _manager_lock:
            if _manager is None:
                _manager = DictManager()
    return _manager
