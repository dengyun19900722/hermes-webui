"""SQLite 后端 Mock 实现，无需 Neo4j。

持久化到 data/graph.sqlite（gitignored）。

多线程安全：每个请求线程用独立的 sqlite3 连接（threading.local）。
"""
from __future__ import annotations
import json
import os
import sqlite3
import threading
import uuid
from typing import Any


def _gen_id() -> str:
    return f"mock-{uuid.uuid4().hex[:16]}"


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS nodes (
    id TEXT PRIMARY KEY,
    labels TEXT NOT NULL,
    properties TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS relationships (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    start_id TEXT NOT NULL,
    end_id TEXT NOT NULL,
    properties TEXT NOT NULL,
    FOREIGN KEY (start_id) REFERENCES nodes(id) ON DELETE CASCADE,
    FOREIGN KEY (end_id) REFERENCES nodes(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS sample_names (
    name TEXT PRIMARY KEY
);
"""


class MockStore:
    """每个线程独立连接。"""

    def __init__(self, db_path: str = "data/graph.sqlite"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._local = threading.local()
        conn = self._get_conn()
        # WAL + busy_timeout 需要早于任何写操作生效
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(_SCHEMA_SQL)
        conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        """按线程懒创建连接。"""
        c = getattr(self._local, "conn", None)
        if c is None:
            c = sqlite3.connect(self.db_path, check_same_thread=False)
            c.row_factory = sqlite3.Row
            c.execute("PRAGMA foreign_keys = ON")
            c.execute("PRAGMA busy_timeout = 5000")  # 5s 锁等待，避免多线程僵死
            self._local.conn = c
        return c

    @property
    def conn(self) -> sqlite3.Connection:
        return self._get_conn()

    def close(self):
        c = getattr(self._local, "conn", None)
        if c is not None:
            try:
                c.close()
            except Exception:
                pass
            self._local.conn = None

    def _ensure_schema(self):
        # 兼容旧版调用
        with self.conn.cursor() as cur:
            cur.executescript(_SCHEMA_SQL)
            self.conn.commit()

    def health(self) -> dict:
        try:
            self.conn.execute("SELECT 1").fetchone()
            return {"backend": "mock", "ok": True, "detail": f"sqlite at {self.db_path} (thread-local)"}
        except Exception as e:
            return {"backend": "mock", "ok": False, "detail": str(e)}

    def schema(self) -> dict:
        cur = self.conn.cursor()
        labels = set()
        for row in cur.execute("SELECT labels FROM nodes"):
            labels.update(json.loads(row["labels"]))
        types = {r["type"] for r in cur.execute("SELECT DISTINCT type FROM relationships")}
        node_count = cur.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
        rel_count = cur.execute("SELECT COUNT(*) FROM relationships").fetchone()[0]
        return {
            "node_labels": sorted(labels),
            "relationship_types": sorted(types),
            "stats": {"node_count": node_count, "relationship_count": rel_count},
        }

    def search(self, query: str, label: str | None = None, limit: int = 50) -> dict:
        cur = self.conn.cursor()
        results = []
        for row in cur.execute("SELECT id, labels, properties FROM nodes"):
            props = json.loads(row["properties"])
            labels = json.loads(row["labels"])
            if label and label not in labels:
                continue
            blob = json.dumps(props, ensure_ascii=False)
            if query.lower() in blob.lower():
                results.append({
                    "id": row["id"],
                    "labels": labels,
                    "properties": props,
                })
                if len(results) >= limit:
                    break
        return {"results": results, "query": query, "count": len(results)}

    def list_nodes(self, label: str, limit: int = 200) -> dict:
        cur = self.conn.cursor()
        # SQL 层过滤：labels 是 JSON 数组字符串，用 LIKE 匹配。
        # 比 Python 端 for-loop 快几个数量级（特别是节点多时）。
        # 模式：要么 ["Label"，要么 "Label"]，避免前缀冲突（如 "Host" 误匹配 "Ghost"）。
        pattern = f'%"{label}"%'
        results = []
        try:
            for row in cur.execute(
                "SELECT id, labels, properties FROM nodes "
                "WHERE labels LIKE ? LIMIT ?",
                (pattern, limit)
            ):
                labels = json.loads(row["labels"])
                # 防御性：LIKE 可能误匹配（如 "Host" 匹配 '["Ghost"]' 不存在但保险起见）
                if label not in labels:
                    continue
                results.append({
                    "id": row["id"],
                    "labels": labels,
                    "properties": json.loads(row["properties"]),
                })
        finally:
            try:
                cur.close()
            except Exception:
                pass
        return {"results": results, "count": len(results)}

    def list_all_nodes(self, limit: int = 500) -> dict:
        """一次查询返回所有节点，不分 label。"""
        cur = self.conn.cursor()
        try:
            rows = cur.execute(
                "SELECT id, labels, properties FROM nodes LIMIT ?", (limit,)
            ).fetchall()
        except Exception:
            return {"results": [], "count": 0}
        finally:
            try:
                cur.close()
            except Exception:
                pass
        results = []
        for row in rows:
            results.append({
                "id": row["id"],
                "labels": json.loads(row["labels"]),
                "properties": json.loads(row["properties"]),
            })
        return {"results": results, "count": len(results)}

    def get_node(self, element_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT id, labels, properties FROM nodes WHERE id = ?",
            (element_id,)
        ).fetchone()
        if not row:
            return None
        return {"id": row["id"], "labels": json.loads(row["labels"]),
                "properties": json.loads(row["properties"])}

    def get_relationship(self, element_id: str) -> dict | None:
        row = self.conn.execute(
            "SELECT id, type, start_id, end_id, properties FROM relationships WHERE id = ?",
            (element_id,)
        ).fetchone()
        if not row:
            return None
        return {"id": row["id"], "type": row["type"],
                "start_node_id": row["start_id"], "end_node_id": row["end_id"],
                "properties": json.loads(row["properties"])}

    def list_relationships(self, element_id: str, direction: str = "both") -> list[dict]:
        if direction == "out":
            sql = "WHERE start_id = ?"
        elif direction == "in":
            sql = "WHERE end_id = ?"
        else:
            sql = "WHERE start_id = ? OR end_id = ?"
        params = (element_id, element_id) if direction == "both" else (element_id,)
        rows = self.conn.execute(
            f"SELECT id, type, start_id, end_id, properties FROM relationships {sql}",
            params
        ).fetchall()
        return [{"id": r["id"], "type": r["type"],
                 "start_node_id": r["start_id"], "end_node_id": r["end_id"],
                 "properties": json.loads(r["properties"])} for r in rows]

    def list_all_relationships(self, limit: int = 500) -> list[dict]:
        rows = self.conn.execute(
            "SELECT id, type, start_id, end_id, properties FROM relationships LIMIT ?",
            (limit,)
        ).fetchall()
        return [{"id": r["id"], "type": r["type"],
                 "start_node_id": r["start_id"], "end_node_id": r["end_id"],
                 "properties": json.loads(r["properties"])} for r in rows]

    def topology(self, element_id: str, depth: int = 1) -> dict:
        visited_nodes = {element_id}
        visited_rels = set()
        frontier = {element_id}
        for _ in range(max(1, min(depth, 5))):
            next_frontier = set()
            for nid in frontier:
                rels = self.list_relationships(nid, direction="both")
                for r in rels:
                    visited_rels.add(r["id"])
                    if r["start_node_id"] not in visited_nodes:
                        next_frontier.add(r["start_node_id"])
                        visited_nodes.add(r["start_node_id"])
                    if r["end_node_id"] not in visited_nodes:
                        next_frontier.add(r["end_node_id"])
                        visited_nodes.add(r["end_node_id"])
            frontier = next_frontier
        nodes = [self.get_node(nid) for nid in visited_nodes]
        rels = [self.get_relationship(rid) for rid in visited_rels]
        return {"nodes": [n for n in nodes if n], "relationships": [r for r in rels if r]}

    def create_node(self, labels: list[str], properties: dict) -> dict:
        nid = _gen_id()
        self.conn.execute(
            "INSERT INTO nodes (id, labels, properties) VALUES (?, ?, ?)",
            (nid, json.dumps(labels), json.dumps(properties, ensure_ascii=False))
        )
        self.conn.commit()
        return {"id": nid, "labels": labels, "properties": properties}

    def create_relationship(self, type_: str, start_id: str, end_id: str,
                            properties: dict | None = None) -> dict:
        rid = _gen_id()
        self.conn.execute(
            "INSERT INTO relationships (id, type, start_id, end_id, properties) VALUES (?, ?, ?, ?, ?)",
            (rid, type_, start_id, end_id, json.dumps(properties or {}, ensure_ascii=False))
        )
        self.conn.commit()
        return {"id": rid, "type": type_,
                "start_node_id": start_id, "end_node_id": end_id,
                "properties": properties or {}}

    def update_node(self, element_id: str, properties: dict) -> dict:
        existing = self.get_node(element_id)
        if not existing:
            raise ValueError(f"Node not found: {element_id}")
        merged = {**existing["properties"], **properties}
        self.conn.execute(
            "UPDATE nodes SET properties = ? WHERE id = ?",
            (json.dumps(merged, ensure_ascii=False), element_id)
        )
        self.conn.commit()
        return {**existing, "properties": merged}

    def delete_node(self, element_id: str) -> dict:
        self.conn.execute("DELETE FROM nodes WHERE id = ?", (element_id,))
        self.conn.commit()
        return {"deleted": True}

    def delete_relationship(self, element_id: str) -> dict:
        self.conn.execute("DELETE FROM relationships WHERE id = ?", (element_id,))
        self.conn.commit()
        return {"deleted": True}

    def seed_sample(self) -> dict:
        sample_nodes = [
            ("Host", "web-01", {"ip": "10.0.0.1"}),
            ("Host", "db-01", {"ip": "10.0.0.2"}),
            ("Host", "cache-01", {"ip": "10.0.0.3"}),
            ("Service", "nginx", {"version": "1.24"}),
            ("Service", "postgres", {"version": "15"}),
            ("Service", "redis", {"version": "7"}),
            ("Incident", "INC-001", {"title": "nginx 502 突发", "severity": "P2"}),
            ("Runbook", "RB-001", {"title": "重启 nginx 步骤"}),
        ]
        name_to_id = {}
        added = 0
        cur = self.conn.cursor()
        # 批量事务：避免逐行 commit 的开销和多线程锁竞争
        for label, name, props in sample_nodes:
            existing = cur.execute(
                "SELECT 1 FROM sample_names WHERE name = ?", (name,)
            ).fetchone()
            if existing:
                continue
            nid = _gen_id()
            cur.execute(
                "INSERT INTO nodes (id, labels, properties) VALUES (?, ?, ?)",
                (nid, json.dumps([label]),
                 json.dumps({"name": name, **props}, ensure_ascii=False))
            )
            cur.execute("INSERT INTO sample_names (name) VALUES (?)", (name,))
            name_to_id[name] = nid
            added += 1
        self.conn.commit()

        sample_rels = [
            ("DEPENDS_ON", "web-01", "db-01"),
            ("DEPENDS_ON", "web-01", "cache-01"),
            ("RUNS_ON", "nginx", "web-01"),
            ("RUNS_ON", "postgres", "db-01"),
            ("RUNS_ON", "redis", "cache-01"),
            ("AFFECTS", "INC-001", "nginx"),
            ("APPLIES_TO", "RB-001", "nginx"),
        ]
        rel_added = 0
        for type_, s, e in sample_rels:
            sid = name_to_id.get(s)
            eid = name_to_id.get(e)
            if sid and eid:
                rid = _gen_id()
                cur.execute(
                    "INSERT INTO relationships (id, type, start_id, end_id, properties) VALUES (?, ?, ?, ?, ?)",
                    (rid, type_, sid, eid, "{}")
                )
                rel_added += 1
        self.conn.commit()
        return {"nodes_added": added, "relationships_added": rel_added}