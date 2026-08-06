"""Neo4j 后端实现。

环境变量：
  NEO4J_URI      (默认 bolt://localhost:7687)
  NEO4J_USER     (默认 neo4j)
  NEO4J_PASSWORD (必需，否则 health() 报 not_configured)
"""
from __future__ import annotations
import os
import re
import logging
from typing import Any

logger = logging.getLogger(__name__)

_VALID_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_identifier(value: str, kind: str) -> None:
    if not isinstance(value, str) or not _VALID_ID.match(value):
        raise ValueError(f"Invalid {kind}: {value!r}")


def _build_topology_cypher(direction: str, depth: int, rel_types: list[str] | None,
                           limit: int) -> tuple[str, dict]:
    """构建 topology 查询 Cypher。关键：N 字符串拼接而非参数化。"""
    if not isinstance(depth, int) or depth < 0 or depth > 5:
        raise ValueError(f"depth must be int in [0,5], got {depth}")
    # depth=0 表示"全部"——内部映射为最大跳数 5（*1..5 已是 Cypher 表达上限）
    if depth == 0:
        depth = 5

    dir_pattern = {
        "both": ("-", "-"),
        "in": ("<-", "-"),
        "out": ("-", "->"),
    }[direction]

    rel_clause = ""
    if rel_types:
        for rt in rel_types:
            _validate_identifier(rt, "relationship type")
        types_str = "|".join(f":`{rt}`" for rt in rel_types)
        rel_clause = f" AND type(r) IN [{types_str}]"

    cypher = (
        f"MATCH path = (center){dir_pattern[0]}[r*1..{depth}]{dir_pattern[1]}(neighbor) "
        f"WHERE elementId(center) = $element_id{rel_clause} "
        f"RETURN center, nodes(path) AS ns, relationships(path) AS rs "
        f"LIMIT $limit"
    )
    return cypher, {"element_id": "", "limit": limit}


# ── Sample data for seed_sample ──────────────────────────────────────────────

SAMPLE_NODES = [
    ("Host", "web-01", {"ip": "10.0.0.1"}),
    ("Host", "db-01", {"ip": "10.0.0.2"}),
    ("Host", "cache-01", {"ip": "10.0.0.3"}),
    ("Service", "nginx", {"version": "1.24"}),
    ("Service", "postgres", {"version": "15"}),
    ("Service", "redis", {"version": "7"}),
    ("Incident", "INC-001", {"title": "nginx 502 突发", "severity": "P2"}),
    ("Runbook", "RB-001", {"title": "重启 nginx 步骤"}),
]

SAMPLE_RELS = [
    ("DEPENDS_ON", "web-01", "db-01"),
    ("DEPENDS_ON", "web-01", "cache-01"),
    ("RUNS_ON", "nginx", "web-01"),
    ("RUNS_ON", "postgres", "db-01"),
    ("RUNS_ON", "redis", "cache-01"),
    ("AFFECTS", "INC-001", "nginx"),
    ("APPLIES_TO", "RB-001", "nginx"),
]


class Neo4jStore:
    """通过 neo4j Python Driver 连接。"""

    def __init__(self):
        self._driver = None
        self._uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
        self._user = os.environ.get("NEO4J_USER", "neo4j")
        self._password = os.environ.get("NEO4J_PASSWORD")

    def _connect(self):
        if self._driver is not None:
            return self._driver
        if not self._password:
            raise RuntimeError("neo4j not configured (NEO4J_PASSWORD missing)")
        try:
            from neo4j import GraphDatabase
        except ImportError:
            raise RuntimeError("neo4j package not installed")
        try:
            # 显式超时：避免 Bolt 握手卡 30s 默认值
            self._driver = GraphDatabase.driver(
                self._uri,
                auth=(self._user, self._password),
                connection_timeout=5.0,    # 初始连接最多等 5s
                max_connection_lifetime=300,  # 连接 5min 回收，防 stale
                max_connection_pool_size=50,  # 足够并发
            )
            self._driver.verify_connectivity()
            return self._driver
        except Exception as e:
            self._driver = None
            raise RuntimeError(f"neo4j unreachable: {e}")

    def health(self) -> dict:
        if not self._password:
            return {"backend": "neo4j", "ok": False, "detail": "not_configured"}
        try:
            self._connect()
            return {"backend": "neo4j", "ok": True, "detail": "connected"}
        except Exception as e:
            return {"backend": "neo4j", "ok": False, "detail": str(e)}

    # ── Internal helpers ────────────────────────────────────────────────────

    @staticmethod
    def _build_search_cypher(query: str, label: str | None, limit: int) -> str:
        """构建 search Cypher。"""
        if label:
            _validate_identifier(label, "label")
            return (
                "MATCH (n) "
                "WHERE any(k IN keys(n) WHERE toLower(toString(n[k])) CONTAINS toLower($query)) "
                "AND $label IN labels(n) "
                "RETURN n LIMIT $limit"
            )
        return (
            "MATCH (n) "
            "WHERE any(k IN keys(n) WHERE toLower(toString(n[k])) CONTAINS toLower($query)) "
            "RETURN n LIMIT $limit"
        )

    def _node_to_dict(self, node: Any) -> dict:
        """Convert a Neo4j Node to a plain dict."""
        if node is None:
            return {}
        props = dict(node)
        name = props.get("name") or props.get("title") or props.get("id", "")
        return {
            "id": node.element_id,
            "labels": list(node.labels),
            "name": str(name),
            "properties": props,
        }

    def _rel_to_dict(self, rel: Any, start_name: str = "", end_name: str = "") -> dict:
        """Convert a Neo4j Relationship to a plain dict."""
        return {
            "id": rel.element_id,
            "type": rel.type,
            "start_node_id": rel.start_node.element_id,
            "end_node_id": rel.end_node.element_id,
            "start_node_name": start_name,
            "end_node_name": end_name,
            "properties": dict(rel),
        }

    def _run_read(self, cypher: str, params: dict | None = None) -> list[Any]:
        try:
            driver = self._connect()
        except Exception as exc:
            raise RuntimeError(f"Neo4j driver unavailable: {exc}") from exc
        try:
            with driver.session() as session:
                result = session.run(cypher, params or {})
                return list(result)
        except Exception as exc:
            logger.warning("Cypher query failed: %s | query=%s", exc, cypher)
            raise RuntimeError(f"Neo4j query failed: {exc}") from exc

    def _run_write_single(self, cypher: str, params: dict | None = None) -> Any:
        try:
            driver = self._connect()
        except Exception as exc:
            raise RuntimeError(f"Neo4j driver unavailable: {exc}") from exc
        try:
            with driver.session() as session:
                return session.run(cypher, params or {}).single()
        except Exception as exc:
            logger.warning("Cypher write failed: %s | query=%s", exc, cypher)
            raise RuntimeError(f"Neo4j write failed: {exc}") from exc

    # ── CRUD methods (Protocol contract) ────────────────────────────────────

    def schema(self) -> dict:
        """Return all node labels, relationship types, and property keys."""
        import time as _t
        t0 = _t.time()
        driver = self._connect()
        t1 = _t.time()
        with driver.session() as session:
            t2 = _t.time()
            labels = sorted(set(
                r["label"] for r in session.run("CALL db.labels() YIELD label RETURN label")
            ))
            t3 = _t.time()
            rel_types = sorted(set(
                r["relationshipType"] for r in session.run(
                    "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"
                )
            ))
            t4 = _t.time()
            property_keys = sorted(set(
                r["propertyKey"] for r in session.run(
                    "CALL db.propertyKeys() YIELD propertyKey RETURN propertyKey"
                )
            ))
            t5 = _t.time()
            node_count = session.run("MATCH (n) RETURN count(n) AS c").single()["c"]
            t6 = _t.time()
            rel_count = session.run(
                "MATCH ()-[r]->() RETURN count(r) AS c"
            ).single()["c"]
            t7 = _t.time()
        logger.warning(
            "[graph] schema _connect=%.0fms session=%.0fms labels=%.0fms rels=%.0fms "
            "props=%.0fms count_n=%.0fms count_r=%.0fms total=%.0fms",
            (t1-t0)*1000, (t2-t1)*1000, (t3-t2)*1000, (t4-t3)*1000,
            (t5-t4)*1000, (t6-t5)*1000, (t7-t6)*1000, (t7-t0)*1000,
        )
        return {
            "node_labels": labels,
            "relationship_types": rel_types,
            "property_keys": property_keys,
            "stats": {"node_count": node_count, "relationship_count": rel_count},
        }

    def search(self, query: str, label: str | None = None, limit: int = 50) -> dict:
        """Search nodes by keyword across name and all property values."""
        cypher = self._build_search_cypher(query, label, limit)
        params: dict[str, Any] = {"query": query, "limit": limit}
        if label:
            params["label"] = label
        records = self._run_read(cypher, params)
        nodes = [self._node_to_dict(r["n"]) for r in records]
        # Normalize to {id, labels, properties} per Protocol contract
        results = [
            {"id": n["id"], "labels": n["labels"], "properties": n["properties"]}
            for n in nodes
        ]
        return {"results": results, "query": query, "count": len(results)}

    def list_nodes(self, label: str, limit: int = 200) -> dict:
        """List nodes of a given label."""
        if label:
            _validate_identifier(label, "label")
        label_cypher = f":`{label}`" if label else ""
        cypher = f"MATCH (n {label_cypher}) RETURN n LIMIT $limit"
        records = self._run_read(cypher, {"limit": limit})
        results = []
        for r in records:
            nd = self._node_to_dict(r["n"])
            results.append({
                "id": nd["id"],
                "labels": nd["labels"],
                "properties": nd["properties"],
            })
        return {"results": results, "count": len(results)}

    def list_all_nodes(self, limit: int = 500) -> dict:
        """一次查询返回所有节点，不分 label。"""
        cypher = "MATCH (n) RETURN n LIMIT $limit"
        records = self._run_read(cypher, {"limit": limit})
        results = []
        for r in records:
            nd = self._node_to_dict(r["n"])
            results.append({
                "id": nd["id"],
                "labels": nd["labels"],
                "properties": nd["properties"],
            })
        return {"results": results, "count": len(results)}

    def get_node(self, element_id: str) -> dict | None:
        """Return a single node by its element_id, including its labels list."""
        cypher = "MATCH (n) WHERE elementId(n) = $element_id RETURN n"
        try:
            record = self._run_write_single(cypher, {"element_id": element_id})
        except RuntimeError:
            return None
        if not record:
            return None
        node = record["n"]
        return {
            "id": node.element_id,
            "labels": list(node.labels),
            "properties": dict(node),
        }

    def get_relationship(self, element_id: str) -> dict | None:
        """Return a single relationship by its element_id."""
        cypher = (
            "MATCH (s)-[r]->(e) WHERE elementId(r) = $element_id "
            "RETURN r, s.name AS sname, e.name AS ename"
        )
        try:
            rec = self._run_write_single(cypher, {"element_id": element_id})
        except RuntimeError:
            return None
        if rec is None:
            return None
        return self._rel_to_dict(rec["r"], rec["sname"] or "", rec["ename"] or "")

    def list_relationships(self, element_id: str, direction: str = "both") -> list[dict]:
        """List relationships for a given node element_id."""
        if direction == "out":
            dir_pattern = "-[r]->"
        elif direction == "in":
            dir_pattern = "<-[r]-"
        else:
            dir_pattern = "-[r]-"

        cypher = (
            f"MATCH (n) WHERE elementId(n) = $element_id "
            f"MATCH (n){dir_pattern}(m) "
            f"RETURN r, n.name AS sname, m.name AS ename"
        )
        try:
            records = self._run_read(cypher, {"element_id": element_id})
        except RuntimeError:
            return []
        rels = []
        for rec in records:
            rels.append(self._rel_to_dict(
                rec["r"],
                start_name=rec["sname"] or "",
                end_name=rec["ename"] or "",
            ))
        return rels

    def list_all_relationships(self, limit: int = 500) -> list[dict]:
        driver = self._connect()
        with driver.session() as s:
            res = s.run("MATCH ()-[r]->() RETURN r LIMIT $limit", limit=limit)
            return [{"id": r["r"].element_id, "type": r["r"].type,
                     "start_node_id": r["r"].start_node.element_id,
                     "end_node_id": r["r"].end_node.element_id,
                     "properties": dict(r["r"])} for r in res]

    def topology(self, element_id: str, depth: int = 1, direction: str = "both") -> dict:
        """Return a subgraph centered on the given node element_id, within depth.

        direction:
          - "both" 双向（默认）
          - "in"   上游（被依赖 / 指向该节点）
          - "out"  下游（依赖 / 该节点指向）

        depth:
          - 1..5   固定层数
          - 0      全部展开（内部映射为 5，避免 Cypher 无限遍历）
        """
        if not isinstance(depth, int) or depth < 0 or depth > 5:
            raise ValueError(f"depth must be int in [0,5], got {depth}")
        if direction not in ("in", "out", "both"):
            raise ValueError(f"direction must be in/out/both, got {direction}")

        cypher, params = _build_topology_cypher(direction, depth, None, 200)
        params["element_id"] = element_id
        try:
            records = self._run_read(cypher, params)
        except RuntimeError as exc:
            logger.warning("Topology query failed: %s", exc)
            return {"nodes": [], "relationships": [], "error": str(exc)}

        if not records:
            return {"nodes": [], "relationships": []}

        # Deduplicate nodes and rels across all paths
        nodes_map: dict[str, dict] = {}
        rels_map: dict[str, dict] = {}
        for rec in records:
            if rec["center"] is not None:
                cn = self._node_to_dict(rec["center"])
                if cn.get("id") and cn["id"] not in nodes_map:
                    nodes_map[cn["id"]] = cn
            for n in rec["ns"]:
                nd = self._node_to_dict(n)
                if nd.get("id") and nd["id"] not in nodes_map:
                    nodes_map[nd["id"]] = nd
            for r in rec["rs"]:
                if r is None:
                    continue
                rd = {
                    "id": r.element_id,
                    "type": r.type,
                    "start_node_id": r.start_node.element_id,
                    "end_node_id": r.end_node.element_id,
                    "properties": dict(r),
                }
                if rd["id"] not in rels_map:
                    rels_map[rd["id"]] = rd

        return {
            "nodes": list(nodes_map.values()),
            "relationships": list(rels_map.values()),
        }

    def create_node(self, labels: list[str], properties: dict) -> dict:
        """Create a node with the given labels and properties."""
        if not labels:
            raise ValueError("labels is required (at least one)")
        for lbl in labels:
            _validate_identifier(lbl, "label")
        label_str = "".join(f":`{lbl}`" for lbl in labels)
        props_keys = list(properties.keys())
        params = {"props": properties}
        set_clause = ", ".join(f"n.`{k}` = $props.`{k}`" for k in props_keys)
        cypher = (
            f"CREATE (n {label_str} {{}}) "
            f"SET {set_clause} "
            "RETURN elementId(n) AS id"
        )
        rec = self._run_write_single(cypher, params)
        if rec is None:
            raise RuntimeError("create_node returned no record")
        new_id = rec["id"]
        created = self.get_node(new_id)
        if created is None:
            raise RuntimeError("create_node: node not found after create")
        return created

    def create_relationship(self, type_: str, start_id: str, end_id: str,
                            properties: dict | None = None) -> dict:
        """Create a relationship between two nodes."""
        _validate_identifier(type_, "relationship type")
        properties = properties or {}
        params = {
            "rel_type": type_,
            "start_node_id": start_id,
            "end_node_id": end_id,
            "props": properties,
        }
        props_set = ", ".join(f"r.`{k}` = $props.`{k}`" for k in properties.keys())
        cypher = (
            "MATCH (s) WHERE elementId(s) = $start_node_id "
            "MATCH (e) WHERE elementId(e) = $end_node_id "
            f"CREATE (s)-[r:`{type_}`]->(e) "
            f"SET {props_set} "
            "RETURN elementId(r) AS id, s.name AS sname, e.name AS ename, r"
        )
        rec = self._run_write_single(cypher, params)
        if rec is None:
            raise RuntimeError("Failed to create relationship — check node IDs")
        return self._rel_to_dict(
            rec["r"],
            start_name=rec["sname"] or "",
            end_name=rec["ename"] or "",
        )

    def update_node(self, element_id: str, properties: dict) -> dict:
        """Update a node's properties (merge)."""
        if not properties:
            # No-op: just return current state
            existing = self.get_node(element_id)
            if existing is None:
                raise ValueError(f"Node not found: {element_id}")
            return existing
        props_keys = list(properties.keys())
        params = {"element_id": element_id, "props": properties}
        set_clause = ", ".join(f"n.`{k}` = $props.`{k}`" for k in props_keys)
        cypher = (
            f"MATCH (n) WHERE elementId(n) = $element_id "
            f"SET {set_clause} "
            "RETURN elementId(n) AS id"
        )
        rec = self._run_write_single(cypher, params)
        if rec is None:
            raise ValueError(f"Node not found: {element_id}")
        updated = self.get_node(element_id)
        if updated is None:
            raise RuntimeError("update_node: node not found after update")
        return updated

    def delete_node(self, element_id: str) -> dict:
        """Delete a node and all its relationships."""
        cypher = (
            "MATCH (n) WHERE elementId(n) = $element_id "
            "DETACH DELETE n "
            "RETURN count(n) AS deleted"
        )
        rec = self._run_write_single(cypher, {"element_id": element_id})
        if rec is None or rec["deleted"] == 0:
            raise ValueError(f"Node not found: {element_id}")
        return {"deleted": True}

    def delete_relationship(self, element_id: str) -> dict:
        """Delete a relationship by its element_id."""
        cypher = (
            "MATCH ()-[r]->() WHERE elementId(r) = $element_id "
            "DELETE r "
            "RETURN count(r) AS deleted"
        )
        rec = self._run_write_single(cypher, {"element_id": element_id})
        if rec is None or rec["deleted"] == 0:
            raise ValueError(f"Relationship not found: {element_id}")
        return {"deleted": True}

    def seed_sample(self) -> dict:
        """幂等：按 name 唯一约束防重复。"""
        nodes_added = 0
        rels_added = 0
        driver = self._connect()
        with driver.session() as session:
            for label, name, props in SAMPLE_NODES:
                res = session.run(
                    "MERGE (n:`" + label + "` {name: $name}) "
                    "ON CREATE SET n += $props "
                    "RETURN n",
                    name=name, props=props,
                )
                if res.single():
                    nodes_added += 1
            for type_, s, e in SAMPLE_RELS:
                session.run(
                    "MATCH (a {name: $s}), (b {name: $e}) "
                    "MERGE (a)-[r:`" + type_ + "`]->(b)",
                    s=s, e=e,
                )
                rels_added += 1
        return {"nodes_added": nodes_added, "relationships_added": rels_added}
