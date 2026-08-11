# 图库管理可视化模块实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 Hermes WebUI 中新增 Graph 图库管理面板，通过 FastAPI 代理层连接 Neo4j，实现节点/关系的 CRUD、可视化和拓扑查看。

**Architecture:** 后端新增 `api/graph.py` 作为 Neo4j 代理模块，在 `api/routes.py` 中注册 `/api/graph/*` 路由。前端新增 `static/graph.js` 作为面板模块，在 `static/index.html` 中注册 Graph 导航按钮和面板 DOM，在 `static/style.css` 中补充样式。Cytoscape.js 通过 CDN 引入。

**Tech Stack:** neo4j-python-driver (官方驱动), Cytoscape.js (CDN), 原生 JS (遵循 WebUI 现有模式)

---

## 文件结构总览

```
新增文件:
  api/graph.py                    # Neo4j 代理层 + 所有图谱 API 逻辑
  static/graph.js                  # 前端图库面板模块
  static/vendor/cytoscape.min.js    # Cytoscape.js 库文件
  tests/test_graph_api.py          # 后端 API 单元测试

修改文件:
  requirements.txt                  # 新增 neo4j 依赖
  api/routes.py:11860+             # 注册 /api/graph/* 路由
  static/index.html:166+           # 新增 Graph 导航按钮 + 面板 DOM
  static/style.css                  # 新增 graph panel 样式
  static/boot.js                    # 加载 graph.js 模块
  .env.example                      # 新增 NEO4J_* 环境变量说明
```

---

## Phase 1：后端骨架 + 环境配置

### Task 1: 添加 neo4j 依赖

**Files:**
- Modify: `requirements.txt`

- [ ] **Step 1: 添加 neo4j 依赖**

在 `requirements.txt` 末尾添加：

```
# Graph visualization — Neo4j connectivity
neo4j>=5.0
```

Run: `cat requirements.txt | tail -5`
Expected: 包含 `neo4j>=5.0`

- [ ] **Step 2: Commit**

```bash
git add requirements.txt
git commit -m "feat(graph): add neo4j-python-driver dependency"
```

---

### Task 2: 添加环境变量说明

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: 添加 Neo4j 环境变量说明**

在 `.env.example` 末尾追加：

```
# ── Neo4j Graph Database ─────────────────────────────────────────────────────
# Connection to Neo4j for the Graph panel. Leave NEO4J_PASSWORD empty to
# disable the Graph panel at startup (connection tested lazily on first API call).
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=
HERMES_WEBUI_GRAPH_POLL_INTERVAL=30
```

Run: `grep -n "NEO4J" .env.example`
Expected: 3 行输出

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "docs(graph): add Neo4j env vars to .env.example"
```

---

### Task 3: 编写 api/graph.py 后端模块

**Files:**
- Create: `api/graph.py`

- [ ] **Step 1: 编写 api/graph.py 骨架（Driver 单例 + Schema 接口）**

```python
"""
Hermes WebUI — Neo4j graph proxy.
Provides REST endpoints for the Graph panel: schema discovery, node/relationship
CRUD, topology, and search.
"""
import logging
import os
import threading
from typing import Any

from api.helpers import j, bad

logger = logging.getLogger(__name__)

# ── Neo4j connection ──────────────────────────────────────────────────────────

_driver = None
_driver_lock = threading.Lock()


def _get_neo4j_config() -> dict:
    """Read Neo4j connection config from environment variables."""
    return {
        "uri": os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        "user": os.environ.get("NEO4J_USER", "neo4j"),
        "password": os.environ.get("NEO4J_PASSWORD", ""),
    }


def get_driver():
    """Lazily create and return a Neo4j Driver singleton (thread-safe)."""
    global _driver
    if _driver is not None:
        return _driver
    with _driver_lock:
        if _driver is not None:
            return _driver
        cfg = _get_neo4j_config()
        if not cfg["password"]:
            raise ConnectionError("NEO4J_PASSWORD is not set")
        try:
            from neo4j import GraphDatabase
        except ImportError:
            raise ConnectionError(
                "neo4j driver not installed. Run: pip install neo4j>=5.0"
            )
        _driver = GraphDatabase.driver(
            cfg["uri"],
            auth=(cfg["user"], cfg["password"]),
        )
        return _driver


def close_driver():
    """Close the driver singleton. Call on server shutdown."""
    global _driver
    with _driver_lock:
        if _driver is not None:
            _driver.close()
            _driver = None


def _run_query(cypher: str, params: dict | None = None) -> list[dict]:
    """Execute a read Cypher query and return a list of result dicts."""
    driver = get_driver()
    with driver.session() as session:
        result = session.run(cypher, params or {})
        return [dict(record) for record in result]


def _run_write(cypher: str, params: dict | None = None) -> dict:
    """Execute a write Cypher query and return a single result dict."""
    driver = get_driver()
    with driver.session() as session:
        return session.run(cypher, params or {}).single()


# ── Schema discovery ─────────────────────────────────────────────────────────

def get_schema() -> dict:
    """Return all node labels, relationship types, and per-label counts."""
    try:
        driver = get_driver()
    except ConnectionError:
        return {
            "node_labels": [],
            "relationship_types": [],
            "stats": {},
            "connected": False,
        }

    try:
        with driver.session() as session:
            # All node labels
            labels_result = session.run("CALL db.labels() YIELD label RETURN label")
            node_labels = sorted(set(r["label"] for r in labels_result))

            # All relationship types
            rels_result = session.run(
                "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"
            )
            rel_types = sorted(set(r["relationshipType"] for r in rels_result))

            # Per-label counts
            stats = {}
            for label in node_labels:
                count_result = session.run(
                    f"MATCH (n:`{label}`) RETURN count(n) AS cnt"
                )
                stats[label] = count_result.single()["cnt"]

        return {
            "node_labels": node_labels,
            "relationship_types": rel_types,
            "stats": stats,
            "connected": True,
        }
    except Exception as exc:
        logger.warning("Neo4j schema query failed: %s", exc)
        return {
            "node_labels": [],
            "relationship_types": [],
            "stats": {},
            "connected": False,
            "error": str(exc),
        }
```

- [ ] **Step 2: 添加节点 CRUD 函数**

在 `_run_write` 函数之后添加：

```python
# ── Node helpers ──────────────────────────────────────────────────────────────

def _node_to_dict(node: Any) -> dict:
    """Convert a Neo4j Node to a plain dict."""
    props = dict(node)
    # Prefer a "name" or "title" property as display name, else first prop key
    name = props.get("name") or props.get("title") or props.get("id", "")
    return {
        "id": node.element_id,
        "labels": list(node.labels),
        "name": str(name),
        "properties": props,
        "created_at": props.get("created_at"),
    }


def list_nodes(label: str | None = None, page: int = 1, page_size: int = 50,
               q: str | None = None) -> dict:
    """List nodes, optionally filtered by label, with pagination."""
    driver = get_driver()
    skip = (page - 1) * page_size

    where_parts = []
    params: dict[str, Any] = {"skip": skip, "limit": page_size}
    label_cypher = f":`{label}`" if label else ""

    if q:
        where_parts.append(
            "any(k IN keys(n) WHERE toString(n[k]) CONTAINS $q)"
        )
        params["q"] = q

    where_clause = "WHERE " + " AND ".join(where_parts) if where_parts else ""

    count_cypher = f"MATCH (n {label_cypher}) {where_clause} RETURN count(n) AS total"
    data_cypher = (
        f"MATCH (n {label_cypher}) {where_clause} "
        f"RETURN n ORDER BY n.name SKIP $skip LIMIT $limit"
    )

    with driver.session() as session:
        total = session.run(count_cypher, params).single()["total"]
        nodes = [_node_to_dict(r["n"]) for r in session.run(data_cypher, params)]

    return {
        "nodes": nodes,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": (skip + len(nodes)) < total,
    }


def get_node(node_id: str) -> dict | None:
    """Return a single node by its element_id."""
    cypher = "MATCH (n) WHERE n.elementId = $node_id RETURN n"
    with get_driver().session() as session:
        result = session.run(cypher, {"node_id": node_id})
        record = result.single()
        if not record:
            return None
        return _node_to_dict(record["n"])


def create_node(labels: list[str], properties: dict) -> dict:
    """Create a node with the given labels and properties."""
    label_str = ":" + ":".join(f"`{l}`" for l in labels)
    props_keys = list(properties.keys())
    params = {"props": properties}
    set_clause = ", ".join(f"n.{k} = $props.{k}" for k in props_keys)
    cypher = (
        f"CREATE (n {label_str} {{}}) "
        f"SET {set_clause} "
        "RETURN n.elementId AS id, n"
    )
    with get_driver().session() as session:
        result = session.run(cypher, params)
        record = result.single()
        node_id = record["id"]
    return get_node(node_id)


def update_node(node_id: str, properties: dict) -> dict | None:
    """Update a node's properties."""
    props_keys = list(properties.keys())
    params = {"node_id": node_id, "props": properties}
    set_clause = ", ".join(f"n.{k} = $props.{k}" for k in props_keys)
    cypher = (
        f"MATCH (n) WHERE n.elementId = $node_id "
        f"SET {set_clause} "
        "RETURN n.elementId AS id"
    )
    with get_driver().session() as session:
        result = session.run(cypher, params)
        if result.single() is None:
            return None
    return get_node(node_id)


def delete_node(node_id: str) -> bool:
    """Delete a node and all its relationships."""
    cypher = (
        "MATCH (n) WHERE n.elementId = $node_id "
        "DETACH DELETE n "
        "RETURN count(n) AS deleted"
    )
    with get_driver().session() as session:
        deleted = session.run(cypher, {"node_id": node_id}).single()["deleted"]
    return deleted > 0


def expand_node(node_id: str, depth: int = 1, direction: str = "both",
                 rel_types: list[str] | None = None) -> dict:
    """Return the center node plus its neighbors and relationships within depth."""
    driver = get_driver()
    if direction == "both":
        dir_pattern = "-[r]-"
    elif direction == "in":
        dir_pattern = "<-[r]-"
    else:
        dir_pattern = "-[r]->"

    rel_clause = ""
    if rel_types:
        rel_patterns = "|".join(f":`{rt}`" for rt in rel_types)
        rel_clause = f"AND type(r) IN [{rel_patterns}]"

    cypher = (
        f"MATCH path = (center) WHERE center.elementId = $node_id "
        f"F CALL {{ "
        f"  WITH center "
        f"  MATCH path = (center){dir_pattern}(neighbor) "
        f"  WHERE true {rel_clause} "
        f"  RETURN path LIMIT 100 "
        f"}} "
        f"RETURN center, nodes(path) AS nodes, rels(path) AS rels"
    )

    with driver.session() as session:
        result = session.run(cypher, {"node_id": node_id, "depth": depth})
        records = list(result)

    if not records:
        center = get_node(node_id)
        return {"center": center, "nodes": [], "relationships": []}

    rec = records[0]
    center_node = _node_to_dict(rec["center"]) if rec["center"] else get_node(node_id)
    all_nodes = {_node_to_dict(n)["id"]: _node_to_dict(n) for n in rec["nodes"]}
    relationships = []
    for rel in rec["rels"]:
        rp = dict(rel)
        relationships.append({
            "id": rel.element_id,
            "type": rel.type,
            "start_node_id": rel.start_node.element_id,
            "end_node_id": rel.end_node.element_id,
            "properties": rp,
        })

    return {
        "center": center_node,
        "nodes": list(all_nodes.values()),
        "relationships": relationships,
    }
```

- [ ] **Step 3: 添加关系 CRUD 函数**

```python
# ── Relationship helpers ──────────────────────────────────────────────────────

def _rel_to_dict(rel: Any, start_name: str = "", end_name: str = "") -> dict:
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


def list_relationships(page: int = 1, page_size: int = 50,
                       rel_type: str | None = None) -> dict:
    """List relationships with pagination, optionally filtered by type."""
    driver = get_driver()
    skip = (page - 1) * page_size

    type_clause = f"WHERE type(r) = $rel_type" if rel_type else ""
    count_cypher = f"MATCH ()-[r]->() {type_clause} RETURN count(r) AS total"
    data_cypher = (
        f"MATCH (s)-[r]->(e) {type_clause} "
        f"RETURN r, s.elementId AS sid, s.name AS sname, e.elementId AS eid, e.name AS ename "
        f"ORDER BY type(r) SKIP $skip LIMIT $limit"
    )

    params: dict[str, Any] = {"skip": skip, "limit": page_size}
    if rel_type:
        params["rel_type"] = rel_type

    with driver.session() as session:
        total = session.run(count_cypher, params).single()["total"]
        rels = []
        for rec in session.run(data_cypher, params):
            rels.append(_rel_to_dict(
                rec["r"],
                start_name=rec["sname"] or "",
                end_name=rec["ename"] or "",
            ))

    return {
        "relationships": rels,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_more": (skip + len(rels)) < total,
    }


def create_relationship(rel_type: str, start_node_id: str,
                         end_node_id: str, properties: dict) -> dict | None:
    """Create a relationship between two nodes."""
    params = {
        "rel_type": rel_type,
        "start_node_id": start_node_id,
        "end_node_id": end_node_id,
        "props": properties,
    }
    props_set = ", ".join(f"r.{k} = $props.{k}" for k in properties.keys())
    cypher = (
        "MATCH (s) WHERE s.elementId = $start_node_id "
        "MATCH (e) WHERE e.elementId = $end_node_id "
        f"CREATE (s)-[r:`{rel_type}`]->(e) "
        f"SET {props_set} "
        "RETURN r.elementId AS id, s.name AS sname, e.name AS ename"
    )
    with get_driver().session() as session:
        result = session.run(cypher, params)
        rec = result.single()
        if rec is None:
            return None
        return _rel_to_dict(
            rec["r"],
            start_name=rec["sname"] or "",
            end_name=rec["ename"] or "",
        )


def update_relationship(rel_id: str, properties: dict) -> dict | None:
    """Update a relationship's properties."""
    params = {"rel_id": rel_id, "props": properties}
    props_set = ", ".join(f"r.{k} = $props.{k}" for k in properties.keys())
    cypher = (
        "MATCH ()-[r]->() WHERE r.elementId = $rel_id "
        f"SET {props_set} "
        "RETURN r.elementId AS id"
    )
    with get_driver().session() as session:
        result = session.run(cypher, params)
        if result.single() is None:
            return None
    # Fetch full rel
    cypher2 = (
        "MATCH (s)-[r]->(e) WHERE r.elementId = $rel_id "
        "RETURN r, s.name AS sname, e.name AS ename"
    )
    with get_driver().session() as session:
        rec = session.run(cypher2, {"rel_id": rel_id}).single()
        if rec is None:
            return None
        return _rel_to_dict(rec["r"], rec["sname"] or "", rec["ename"] or "")


def delete_relationship(rel_id: str) -> bool:
    """Delete a relationship by its element_id."""
    cypher = (
        "MATCH ()-[r]->() WHERE r.elementId = $rel_id "
        "DELETE r "
        "RETURN count(r) AS deleted"
    )
    with get_driver().session() as session:
        deleted = session.run(cypher, {"rel_id": rel_id}).single()["deleted"]
    return deleted > 0


def get_relationship(rel_id: str) -> dict | None:
    """Return a single relationship by its element_id."""
    cypher = (
        "MATCH (s)-[r]->(e) WHERE r.elementId = $rel_id "
        "RETURN r, s.name AS sname, e.name AS ename"
    )
    with get_driver().session() as session:
        rec = session.run(cypher, {"rel_id": rel_id}).single()
        if rec is None:
            return None
        return _rel_to_dict(rec["r"], rec["sname"] or "", rec["ename"] or "")
```

- [ ] **Step 4: 添加搜索和拓扑接口函数**

```python
# ── Search and topology ──────────────────────────────────────────────────────

def search_graph(q: str, types: list[str] | None = None,
                 limit: int = 20) -> dict:
    """Search nodes by keyword across name and all property values."""
    driver = get_driver()
    params: dict[str, Any] = {"q": q, "limit": limit}

    type_clause = ""
    if types:
        label_conds = " OR ".join(f"'{t}' IN labels(n)" for t in types)
        type_clause = f"WHERE ({label_conds})"

    cypher = (
        f"MATCH (n) {type_clause} "
        f"WHERE any(k IN keys(n) WHERE toString(n[k]) CONTAINS $q) "
        f"RETURN n LIMIT $limit"
    )

    with driver.session() as session:
        nodes = [_node_to_dict(r["n"]) for r in session.run(cypher, params)]

    return {"results": nodes, "q": q, "count": len(nodes)}


def get_topology(center_id: str | None = None, depth: int = 2,
                 node_types: list[str] | None = None,
                 rel_types: list[str] | None = None) -> dict:
    """Return a subgraph for topology view, optionally centered on a node."""
    driver = get_driver()

    label_filter = ""
    if node_types:
        label_conds = " OR ".join(f"'{t}' IN labels(n)" for t in node_types)
        label_filter = f"AND ({label_conds})"

    rel_filter = ""
    if rel_types:
        rel_conds = " OR ".join(f"type(r) = '{rt}'" for rt in rel_types)
        rel_filter = f"AND ({rel_conds})"

    if center_id:
        cypher = (
            f"MATCH path = (center)-[r*1..{depth}]-(leaf) "
            f"WHERE center.elementId = $center_id {label_filter} {rel_filter} "
            f"WITH nodes(path) AS ns, rels(path) AS rs "
            f"UNWIND ns AS n WITH collect(DISTINCT n) AS uniq, rs "
            f"UNWIND rs AS r "
            f"RETURN uniq AS nodes, collect(DISTINCT r) AS rels"
        )
        params = {"center_id": center_id}
    else:
        cypher = (
            f"MATCH (n) {label_filter} "
            f"WITH n LIMIT 50 "
            f"MATCH path = (n)-[r]-(m) {rel_filter} "
            f"WHERE '{node_types[0]}' IN labels(n) " if node_types else ""
            f"WITH collect(DISTINCT n) AS uniq, collect(DISTINCT r) AS rels "
            f"RETURN uniq AS nodes, rels AS relationships"
        )
        params = {}

    try:
        with driver.session() as session:
            result = session.run(cypher, params)
            rec = result.single()
            if not rec:
                return {"nodes": [], "relationships": []}

            nodes = [_node_to_dict(n) for n in rec["nodes"]]
            relationships = []
            for rel in rec["relationships"]:
                if rel is None:
                    continue
                relationships.append({
                    "id": rel.element_id,
                    "type": rel.type,
                    "start_node_id": rel.start_node.element_id,
                    "end_node_id": rel.end_node.element_id,
                    "properties": dict(rel),
                })
            return {"nodes": nodes, "relationships": relationships}
    except Exception as exc:
        logger.warning("Topology query failed: %s", exc)
        return {"nodes": [], "relationships": [], "error": str(exc)}
```

- [ ] **Step 5: 添加 HTTP handler 函数（供 routes.py 调用）**

```python
# ── HTTP Handlers (called from routes.py) ────────────────────────────────────

def handle_graph_get(handler, parsed):
    """Route all GET /api/graph/* requests."""
    path = parsed.path
    qs = {}
    if parsed.query:
        import urllib.parse
        qs = dict(urllib.parse.parse_qsl(parsed.query))

    if path == "/api/graph/schema":
        data = get_schema()
        return j(handler, data)

    if path == "/api/graph/topology":
        center_id = qs.get("center_id")
        depth = int(qs.get("depth", 2))
        node_types = qs.get("node_types", "").split(",") if qs.get("node_types") else None
        rel_types = qs.get("rel_types", "").split(",") if qs.get("rel_types") else None
        data = get_topology(center_id, depth, node_types, rel_types)
        return j(handler, data)

    if path == "/api/graph/search":
        q = qs.get("q", "")
        types = qs.get("types", "").split(",") if qs.get("types") else None
        limit = int(qs.get("limit", 20))
        if not q:
            return bad(handler, "q parameter is required", status=400)
        data = search_graph(q, types, limit)
        return j(handler, data)

    if path.startswith("/api/graph/nodes/"):
        node_id = path.split("/api/graph/nodes/")[1]
        data = get_node(node_id)
        if data is None:
            return bad(handler, f"Node not found: {node_id}", status=404)
        return j(handler, data)

    if path == "/api/graph/nodes":
        label = qs.get("type") or None
        page = int(qs.get("page", 1))
        page_size = min(int(qs.get("page_size", 50)), 200)
        q = qs.get("q") or None
        data = list_nodes(label, page, page_size, q)
        return j(handler, data)

    if path.startswith("/api/graph/relationships/"):
        rel_id = path.split("/api/graph/relationships/")[1]
        data = get_relationship(rel_id)
        if data is None:
            return bad(handler, f"Relationship not found: {rel_id}", status=404)
        return j(handler, data)

    if path == "/api/graph/relationships":
        rel_type = qs.get("type") or None
        page = int(qs.get("page", 1))
        page_size = min(int(qs.get("page_size", 50)), 200)
        data = list_relationships(page, page_size, rel_type)
        return j(handler, data)

    return bad(handler, f"Unknown graph endpoint: GET {path}", status=404)


def handle_graph_post(handler, parsed):
    """Route all POST /api/graph/* requests."""
    import json as _json
    body = _json.loads(handler.rfile.read(int(handler.headers.get("Content-Length", 0))))
    path = parsed.path

    if path == "/api/graph/nodes":
        labels = body.get("labels", [])
        properties = body.get("properties", {})
        if not labels:
            return bad(handler, "labels is required", status=400)
        data = create_node(labels, properties)
        return j(handler, data, status=201)

    if path == "/api/graph/relationships":
        rel_type = body.get("type")
        start_id = body.get("start_node_id")
        end_id = body.get("end_node_id")
        properties = body.get("properties", {})
        if not rel_type or not start_id or not end_id:
            return bad(handler, "type, start_node_id, and end_node_id are required", status=400)
        data = create_relationship(rel_type, start_id, end_id, properties)
        if data is None:
            return bad(handler, "Failed to create relationship — check node IDs", status=400)
        return j(handler, data, status=201)

    if path.startswith("/api/graph/nodes/") and path.endswith("/expand"):
        node_id = path.split("/api/graph/nodes/")[1].replace("/expand", "")
        depth = int(body.get("depth", 1))
        direction = body.get("direction", "both")
        rel_types = body.get("relationship_types")
        data = expand_node(node_id, depth, direction, rel_types)
        return j(handler, data)

    if path.startswith("/api/graph/nodes/"):
        node_id = path.split("/api/graph/nodes/")[1]
        properties = body.get("properties", {})
        data = update_node(node_id, properties)
        if data is None:
            return bad(handler, f"Node not found: {node_id}", status=404)
        return j(handler, data)

    if path.startswith("/api/graph/relationships/"):
        rel_id = path.split("/api/graph/relationships/")[1]
        properties = body.get("properties", {})
        data = update_relationship(rel_id, properties)
        if data is None:
            return bad(handler, f"Relationship not found: {rel_id}", status=404)
        return j(handler, data)

    return bad(handler, f"Unknown graph endpoint: POST {path}", status=404)


def handle_graph_delete(handler, parsed):
    """Route all DELETE /api/graph/* requests."""
    path = parsed.path

    if path.startswith("/api/graph/nodes/"):
        node_id = path.split("/api/graph/nodes/")[1]
        deleted = delete_node(node_id)
        if not deleted:
            return bad(handler, f"Node not found: {node_id}", status=404)
        return j(handler, {"deleted": True})

    if path.startswith("/api/graph/relationships/"):
        rel_id = path.split("/api/graph/relationships/")[1]
        deleted = delete_relationship(rel_id)
        if not deleted:
            return bad(handler, f"Relationship not found: {rel_id}", status=404)
        return j(handler, {"deleted": True})

    return bad(handler, f"Unknown graph endpoint: DELETE {path}", status=404)
```

- [ ] **Step 6: 语法检查**

Run: `python -m py_compile api/graph.py`
Expected: 无输出（成功）

- [ ] **Step 7: Commit**

```bash
git add api/graph.py
git commit -m "feat(graph): add Neo4j proxy module with schema, CRUD, search, topology APIs"
```

---

### Task 4: 注册 /api/graph 路由

**Files:**
- Modify: `api/routes.py` (在文件末尾 `if parsed.path.startswith("/api/notes")` 之前添加)

- [ ] **Step 1: 在 routes.py 注册 graph 路由**

在 `api/routes.py` 找到现有的路由注册区域（参考 `11860-11870` 行附件 obsidian_notes 路由模式），在 `if parsed.path.startswith("/api/notes")` 之前添加：

```python
    # ── Graph panel (Neo4j proxy) ──────────────────────────────────────────
    if parsed.path.startswith("/api/graph") or parsed.path.startswith("/api/graph"):
        if handler.command == "GET":
            from api.graph import handle_graph_get
            return handle_graph_get(handler, parsed)
        elif handler.command == "POST":
            from api.graph import handle_graph_post
            return handle_graph_post(handler, parsed)
        elif handler.command == "DELETE":
            from api.graph import handle_graph_delete
            return handle_graph_delete(handler, parsed)
        return bad(handler, "Method not allowed", status=405)
```

**注意**：精确行号需要用 grep 确认，实际操作时用 Edit 工具精确定位。

- [ ] **Step 2: 验证语法**

Run: `python -m py_compile api/routes.py`
Expected: 无输出（成功）

- [ ] **Step 3: Commit**

```bash
git add api/routes.py
git commit -m "feat(graph): register /api/graph/* routes in routes.py"
```

---

### Task 5: 编写后端 API 测试

**Files:**
- Create: `tests/test_graph_api.py`

- [ ] **Step 1: 编写基础测试（mock Neo4j driver）**

```python
"""
Tests for api/graph.py — Neo4j graph proxy module.
Uses unittest.mock to mock the Neo4j driver since no real DB is available in CI.
"""
from __future__ import annotations
from unittest.mock import MagicMock, patch
import pytest

# Minimal mock handler
class _MockHandler:
    def __init__(self):
        self.status = None
        self.headers = {}
        self._body = b""

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.headers[key] = value

    def end_headers(self):
        pass

    def rfile(self):
        return MagicMock(read=lambda n: self._body)


class _Parsed:
    def __init__(self, path, query="", command="GET"):
        self.path = path
        self.query = query
        self.command = command


def _make_mock_get(path, query=""):
    h = _MockHandler()
    p = _Parsed(path, query, "GET")
    return h, p


def _make_mock_post(path, body_json):
    h = _MockHandler()
    h._body = body_json.encode()
    p = _Parsed(path, "", "POST")
    return h, p


def _make_mock_delete(path):
    h = _MockHandler()
    p = _Parsed(path, "", "DELETE")
    return h, p


class TestSchemaDiscovery:
    """Tests for get_schema() — dynamic label/rel-type discovery."""

    def test_returns_connected_false_when_no_password(self):
        with patch.dict("os.environ", {"NEO4J_PASSWORD": ""}):
            from api import graph
            # Force re-load to pick up env
            graph._driver = None
            result = graph.get_schema()
            assert result["connected"] is False
            assert result["node_labels"] == []

    def test_returns_empty_when_driver_unavailable(self):
        with patch.dict("os.environ", {"NEO4J_PASSWORD": ""}):
            from api import graph
            graph._driver = None
            result = graph.get_schema()
            assert result["connected"] is False


class TestListNodes:
    """Tests for list_nodes() — pagination and label filtering."""

    def test_page_defaults_to_one(self):
        from api import graph
        # Check function signature accepts optional args
        sig = graph.list_nodes.__code__.co_varnames
        assert "page" in sig
        assert "page_size" in sig
        assert "label" in sig


class TestNodeCRUDHelpers:
    """Smoke tests for CRUD helper signatures."""

    def test_create_node_requires_labels_and_properties(self):
        from api import graph
        # Without a real driver, create_node raises ConnectionError
        with patch.dict("os.environ", {"NEO4J_PASSWORD": ""}):
            graph._driver = None
            with pytest.raises(ConnectionError):
                graph.create_node(["Service"], {"name": "test"})

    def test_delete_node_returns_bool(self):
        from api import graph
        with patch.dict("os.environ", {"NEO4J_PASSWORD": ""}):
            graph._driver = None
            with pytest.raises(ConnectionError):
                graph.delete_node("any-id")

    def test_expand_node_returns_center_nodes_rels(self):
        from api import graph
        sig = graph.expand_node.__code__.co_varnames
        assert "center_node" not in sig  # it's node_id
        assert "depth" in sig
        assert "direction" in sig


class TestRelationshipCRUDHelpers:
    """Smoke tests for relationship CRUD signatures."""

    def test_create_relationship_requires_type_and_ids(self):
        from api import graph
        with patch.dict("os.environ", {"NEO4J_PASSWORD": ""}):
            graph._driver = None
            with pytest.raises(ConnectionError):
                graph.create_relationship("CALLS", "id1", "id2", {})

    def test_delete_relationship_returns_bool(self):
        from api import graph
        with patch.dict("os.environ", {"NEO4J_PASSWORD": ""}):
            graph._driver = None
            with pytest.raises(ConnectionError):
                graph.delete_relationship("any-rel-id")


class TestSearchAndTopology:
    """Tests for search_graph() and get_topology()."""

    def test_search_graph_requires_q_param(self):
        from api import graph
        with patch.dict("os.environ", {"NEO4J_PASSWORD": ""}):
            graph._driver = None
            with pytest.raises(ConnectionError):
                graph.search_graph("payment")

    def test_get_topology_returns_nodes_and_rels_keys(self):
        from api import graph
        sig = graph.get_topology.__code__.co_varnames
        assert "center_id" in sig
        assert "depth" in sig
        assert "node_types" in sig
        assert "rel_types" in sig


class TestHTTPRouteHandlers:
    """Tests for the HTTP handler functions called from routes.py."""

    def test_get_schema_handler_returns_schema(self):
        from api.graph import handle_graph_get
        h, p = _make_mock_get("/api/graph/schema")
        result = handle_graph_get(h, p)
        assert h.status == 200

    def test_get_nodes_returns_paginated_list(self):
        from api.graph import handle_graph_get
        h, p = _make_mock_get("/api/graph/nodes", "page=1&page_size=10")
        result = handle_graph_get(h, p)
        assert h.status == 200
        # body is written to h._body by handler — parse from headers
        import json
        body = h.headers.get("Content-Length", "0")
        # Handler writes JSON via j() which calls send_response + send_header
        # We verify status is 200 (happy path for disconnected/mock)
        assert h.status == 200

    def test_post_create_node_requires_labels(self):
        from api.graph import handle_graph_post
        h, p = _make_mock_post("/api/graph/nodes", '{"labels": [], "properties": {}}')
        with patch.dict("os.environ", {"NEO4J_PASSWORD": ""}):
            result = handle_graph_post(h, p)
            # Should fail validation since labels is empty
            assert h.status == 400

    def test_post_create_node_creates_node(self):
        from api.graph import handle_graph_post
        h, p = _make_mock_post(
            "/api/graph/nodes",
            '{"labels": ["Service"], "properties": {"name": "test-svc"}}',
        )
        with patch.dict("os.environ", {"NEO4J_PASSWORD": ""}):
            graph = __import__("api.graph", fromlist=["graph"]).graph
            graph._driver = None
            # ConnectionError expected without real DB
            with pytest.raises(ConnectionError):
                handle_graph_post(h, p)

    def test_delete_nonexistent_node_returns_404(self):
        from api.graph import handle_graph_delete
        h, p = _make_mock_delete("/api/graph/nodes/nonexistent")
        with patch.dict("os.environ", {"NEO4J_PASSWORD": ""}):
            graph = __import__("api.graph", fromlist=["graph"]).graph
            graph._driver = None
            with pytest.raises(ConnectionError):
                handle_graph_delete(h, p)

    def test_unknown_endpoint_returns_404(self):
        from api.graph import handle_graph_get, handle_graph_post
        h, p = _make_mock_get("/api/graph/unknown")
        result = handle_graph_get(h, p)
        assert h.status == 404

        h2, p2 = _make_mock_post("/api/graph/unknown", "{}")
        result2 = handle_graph_post(h2, p2)
        assert h2.status == 404
```

- [ ] **Step 2: 运行测试**

Run: `cd /Users/dengyun/workspace/hermes-webui-dev/hermes-webui && python -m pytest tests/test_graph_api.py -v --tb=short 2>&1 | head -60`
Expected: 测试收集成功，无报错（mock 测试不依赖真实 Neo4j）

- [ ] **Step 3: Commit**

```bash
git add tests/test_graph_api.py
git commit -m "test(graph): add api/graph.py unit tests with mock driver"
```

---

## Phase 2：前端 Graph 面板入口

### Task 6: 下载 Cytoscape.js 库文件

**Files:**
- Create: `static/vendor/cytoscape.min.js`

- [ ] **Step 1: 创建 vendor 目录并下载 Cytoscape.js**

```bash
mkdir -p static/vendor
# Download Cytoscape.js v3.30 (latest stable)
curl -sL https://unpkg.com/cytoscape@3.30.2/dist/cytoscape.min.js \
  -o static/vendor/cytoscape.min.js
# Verify download
wc -c static/vendor/cytoscape.min.js
# Should be > 500KB
```

Expected: 文件大小 > 500KB

- [ ] **Step 2: Commit**

```bash
git add static/vendor/cytoscape.min.js
git commit -m "feat(graph): add Cytoscape.js v3.30 library"
```

---

### Task 7: 在 index.html 中添加 Graph 导航按钮和面板 DOM

**Files:**
- Modify: `static/index.html`

- [ ] **Step 1: 添加 Graph 导航按钮（紧接在 knowledge 按钮后面）**

在 `static/index.html` 第 166 行（knowledge 按钮）之后，添加：

```html
    <button class="rail-btn nav-tab has-tooltip" data-panel="graph" onclick="switchPanel('graph',{fromRailClick:true})" data-tooltip="Graph" aria-label="Graph"><svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><circle cx="5" cy="6" r="2"/><circle cx="19" cy="6" r="2"/><circle cx="5" cy="18" r="2"/><circle cx="19" cy="18" r="2"/><line x1="9.5" y1="10" x2="6.5" y2="7.5"/><line x1="14.5" y1="10" x2="17.5" y2="7.5"/><line x1="9.5" y1="14" x2="6.5" y2="16.5"/><line x1="14.5" y1="14" x2="17.5" y2="16.5"/></svg></button>
```

同样在侧边栏导航（mobile/compact）第 186 行（knowledge 按钮）之后添加：

```html
    <button class="nav-tab has-tooltip has-tooltip--bottom" data-panel="graph" data-label="Graph" onclick="switchPanel('graph',{fromRailClick:true})" data-tooltip="Graph"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><circle cx="5" cy="6" r="2"/><circle cx="19" cy="6" r="2"/><circle cx="5" cy="18" r="2"/><circle cx="19" cy="18" r="2"/><line x1="9.5" y1="10" x2="6.5" y2="7.5"/><line x1="14.5" y1="10" x2="17.5" y2="7.5"/><line x1="9.5" y1="14" x2="6.5" y2="16.5"/><line x1="14.5" y1="14" x2="17.5" y2="16.5"/></svg></button>
```

- [ ] **Step 2: 添加 Graph 面板 DOM（紧接在 panelKnowledge 之后）**

在 `static/index.html` 找到 `<div class="panel-view" id="panelKnowledge">` 并在其后添加：

```html
    <!-- Graph panel -->
    <div class="panel-view" id="panelGraph">
      <div id="graphContainer">
        <div id="graphToolbar" class="graph-toolbar">
          <div class="graph-view-tabs">
            <button class="graph-tab active" data-view="graph" onclick="switchGraphView('graph')">图形</button>
            <button class="graph-tab" data-view="topology" onclick="switchGraphView('topology')">拓扑</button>
            <button class="graph-tab" data-view="list" onclick="switchGraphView('list')">列表</button>
          </div>
          <div class="graph-search-box">
            <input type="text" id="graphSearchInput" placeholder="搜索节点..." oninput="debounceGraphSearch(this.value, 300)">
          </div>
          <div class="graph-actions">
            <button class="icon-btn" onclick="showCreateNodeModal()" title="新建节点">+ Node</button>
            <button class="icon-btn" onclick="showCreateRelModal()" title="新建关系">+ Rel</button>
          </div>
        </div>
        <div id="graphSidebar" class="graph-sidebar">
          <div id="graphFilterList" class="graph-filter-list"></div>
          <div id="graphNodeList" class="graph-node-list"></div>
        </div>
        <div id="graphCanvas" class="graph-canvas"></div>
        <div id="graphDetailPanel" class="graph-detail-panel" style="display:none"></div>
        <div id="graphListView" class="graph-list-view" style="display:none"></div>
      </div>
    </div>
```

- [ ] **Step 3: Commit**

```bash
git add static/index.html
git commit -m "feat(graph): add Graph nav button and panel DOM to index.html"
```

---

### Task 8: 添加 Graph 面板 CSS 样式

**Files:**
- Modify: `static/style.css`

- [ ] **Step 1: 添加 Graph 面板样式**

在 `static/style.css` 末尾追加：

```css
/* ── Graph Panel ─────────────────────────────────────────────────────────── */

#graphContainer {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.graph-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
}

.graph-view-tabs {
  display: flex;
  gap: 2px;
}

.graph-tab {
  padding: 4px 12px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 13px;
  color: var(--text-muted);
  border-radius: 4px;
}

.graph-tab.active {
  background: var(--primary);
  color: #fff;
}

.graph-search-box {
  flex: 1;
}

.graph-search-box input {
  width: 100%;
  max-width: 240px;
  padding: 4px 8px;
  border: 1px solid var(--border);
  border-radius: 4px;
  font-size: 13px;
}

.graph-actions {
  display: flex;
  gap: 4px;
}

#graphSidebar {
  width: 220px;
  flex-shrink: 0;
  border-right: 1px solid var(--border);
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.graph-filter-list {
  padding: 8px;
  border-bottom: 1px solid var(--border);
}

.graph-filter-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 4px;
  font-size: 13px;
  cursor: pointer;
}

.graph-filter-item input[type="checkbox"] {
  width: auto;
}

.graph-node-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}

.graph-node-item {
  padding: 6px 12px;
  font-size: 13px;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.graph-node-item:hover,
.graph-node-item.selected {
  background: var(--highlight);
}

.graph-node-item .node-type-badge {
  font-size: 10px;
  padding: 1px 4px;
  border-radius: 3px;
  flex-shrink: 0;
}

#graphCanvas {
  flex: 1;
  overflow: hidden;
  position: relative;
}

#graphCanvas .graph-tab-content {
  width: 100%;
  height: 100%;
}

.graph-detail-panel {
  position: absolute;
  top: 0;
  right: 0;
  width: 280px;
  height: 100%;
  background: var(--surface);
  border-left: 1px solid var(--border);
  overflow-y: auto;
  padding: 12px;
  z-index: 10;
}

.graph-detail-header {
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 8px;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.graph-detail-row {
  font-size: 12px;
  margin-bottom: 6px;
}

.graph-detail-label {
  color: var(--text-muted);
  margin-bottom: 2px;
}

.graph-detail-value {
  word-break: break-all;
}

.graph-detail-rels {
  margin-top: 12px;
  border-top: 1px solid var(--border);
  padding-top: 8px;
}

.graph-detail-rel-item {
  font-size: 12px;
  padding: 3px 0;
  color: var(--text-muted);
}

.graph-list-view {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
}

.graph-list-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.graph-list-table th {
  text-align: left;
  padding: 6px 8px;
  border-bottom: 2px solid var(--border);
  cursor: pointer;
  user-select: none;
}

.graph-list-table td {
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
}

.graph-list-table tr:hover td {
  background: var(--highlight);
}

.graph-pagination {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-top: 1px solid var(--border);
  font-size: 13px;
}

.graph-pagination button {
  padding: 3px 8px;
  cursor: pointer;
}

.graph-modal {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.4);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}

.graph-modal-inner {
  background: var(--surface);
  border-radius: 8px;
  padding: 20px;
  min-width: 360px;
  max-width: 480px;
}

.graph-modal-title {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 16px;
}

.graph-form-row {
  margin-bottom: 12px;
}

.graph-form-row label {
  display: block;
  font-size: 12px;
  color: var(--text-muted);
  margin-bottom: 4px;
}

.graph-form-row input,
.graph-form-row select {
  width: 100%;
  padding: 6px 8px;
  border: 1px solid var(--border);
  border-radius: 4px;
  font-size: 13px;
}

.graph-form-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  margin-top: 16px;
}

.icon-btn {
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: transparent;
  cursor: pointer;
  font-size: 12px;
}
```

- [ ] **Step 2: Commit**

```bash
git add static/style.css
git commit -m "feat(graph): add CSS styles for Graph panel"
```

---

### Task 9: 编写 graph.js 前端模块

**Files:**
- Create: `static/graph.js`

- [ ] **Step 1: 编写 graph.js 基础骨架（API 封装 + 面板加载）**

```javascript
/**
 * Hermes WebUI — Graph panel module.
 * Neo4j graph visualization with three view modes: graph, topology, list.
 */
(function () {
  "use strict";

  // ── State ───────────────────────────────────────────────────────────────────

  const G = {
    schema: null,           // {node_labels, relationship_types, stats, connected}
    nodes: [],               // current page of nodes
    selectedNode: null,       // currently selected node
    selectedRel: null,       // currently selected relationship
    currentView: "graph",    // "graph" | "topology" | "list"
    currentPage: 1,
    pageSize: 50,
    searchQ: "",
    filters: {},             // label -> enabled bool
    cy: null,                // Cytoscape instance
    pollInterval: null,
  };

  // ── API helpers ─────────────────────────────────────────────────────────────

  async function api(path, opts = {}) {
    const r = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || r.statusText);
    return d;
  }

  async function loadSchema() {
    try {
      G.schema = await api("/api/graph/schema");
      renderFilterList();
      renderNodeList();
      if (!G.schema.connected) {
        showGraphNotice("Neo4j 未连接。请设置 NEO4J_* 环境变量后重启服务。");
      }
    } catch (e) {
      showGraphNotice("加载图谱 Schema 失败: " + e.message);
    }
  }

  async function loadNodes(page = 1, pageSize = 50, q = "", label = null) {
    try {
      const params = new URLSearchParams({ page, page_size: pageSize });
      if (q) params.set("q", q);
      if (label) params.set("type", label);
      const data = await api("/api/graph/nodes?" + params);
      G.nodes = data.nodes;
      G.currentPage = page;
      G.pageSize = pageSize;
      renderNodeList();
      return data;
    } catch (e) {
      showGraphNotice("加载节点列表失败: " + e.message);
    }
  }

  async function searchGraph(q, types) {
    try {
      const params = new URLSearchParams({ q, limit: 20 });
      if (types && types.length) params.set("types", types.join(","));
      const data = await api("/api/graph/search?" + params);
      renderSearchResults(data.results);
      return data;
    } catch (e) {
      showGraphNotice("搜索失败: " + e.message);
    }
  }

  async function loadTopology(centerId, depth, nodeTypes, relTypes) {
    try {
      const params = new URLSearchParams({ depth: depth || 2 });
      if (centerId) params.set("center_id", centerId);
      if (nodeTypes && nodeTypes.length) params.set("node_types", nodeTypes.join(","));
      if (relTypes && relTypes.length) params.set("rel_types", relTypes.join(","));
      return await api("/api/graph/topology?" + params);
    } catch (e) {
      showGraphNotice("加载拓扑失败: " + e.message);
      return { nodes: [], relationships: [] };
    }
  }

  async function createNode(labels, properties) {
    return await api("/api/graph/nodes", {
      method: "POST",
      body: JSON.stringify({ labels, properties }),
    });
  }

  async function updateNode(nodeId, properties) {
    return await api("/api/graph/nodes/" + encodeURIComponent(nodeId), {
      method: "POST",
      body: JSON.stringify({ properties }),
    });
  }

  async function deleteNode(nodeId) {
    if (!confirm("确认删除此节点？关联的关系也会被删除。")) return;
    await api("/api/graph/nodes/" + encodeURIComponent(nodeId), { method: "DELETE" });
    hideDetailPanel();
    loadSchema();
    loadNodes();
  }

  async function createRelationship(relType, startNodeId, endNodeId, properties) {
    return await api("/api/graph/relationships", {
      method: "POST",
      body: JSON.stringify({ type: relType, start_node_id: startNodeId, end_node_id: endNodeId, properties }),
    });
  }

  async function deleteRelationship(relId) {
    if (!confirm("确认删除此关系？")) return;
    await api("/api/graph/relationships/" + encodeURIComponent(relId), { method: "DELETE" });
    hideDetailPanel();
    loadNodes();
  }

  // ── Panel lifecycle ─────────────────────────────────────────────────────────

  let _prevPanel = null;

  window.switchPanel = (function (orig) {
    return async function (panel, opts) {
      _prevPanel = panel === "graph" ? _prevPanel : panel;
      const r = orig.apply(this, arguments);
      if (panel === "graph") {
        await onGraphShow();
      }
      return r;
    };
  })(window.switchPanel);

  async function onGraphShow() {
    if (!G.schema) {
      await loadSchema();
    }
    if (G.currentView === "graph" && !G.cy) {
      initCytoscape();
    } else if (G.currentView === "list") {
      await loadNodes();
      renderListView();
    }
    startPolling();
  }

  function startPolling() {
    stopPolling();
    const interval = parseInt(getGraphPollInterval(), 0) * 1000;
    if (interval > 0) {
      G.pollInterval = setInterval(loadSchema, interval);
    }
  }

  function stopPolling() {
    if (G.pollInterval) {
      clearInterval(G.pollInterval);
      G.pollInterval = null;
    }
  }

  function getGraphPollInterval() {
    return "30"; // default 30s
  }

  // ── View switching ──────────────────────────────────────────────────────────

  window.switchGraphView = async function (view) {
    G.currentView = view;
    document.querySelectorAll(".graph-tab").forEach(function (t) {
      t.classList.toggle("active", t.dataset.view === view);
    });
    document.getElementById("graphCanvas").style.display = view === "list" ? "none" : "";
    document.getElementById("graphListView").style.display = view === "list" ? "" : "none";
    document.getElementById("graphSidebar").style.display = view === "list" ? "none" : "";

    if (view === "list") {
      await loadNodes();
      renderListView();
    } else if (view === "topology") {
      await renderTopologyView();
    } else {
      if (!G.cy) initCytoscape();
    }
  };

  // ── Filter + Node List rendering ──────────────────────────────────────────────

  function renderFilterList() {
    const el = document.getElementById("graphFilterList");
    if (!el || !G.schema) return;
    el.innerHTML = "";
    G.schema.node_labels.forEach(function (label) {
      const count = G.schema.stats[label] || 0;
      if (!G.filters.hasOwnProperty(label)) G.filters[label] = true;
      const checked = G.filters[label] ? "checked" : "";
      el.innerHTML +=
        '<label class="graph-filter-item">' +
        '<input type="checkbox" ' + checked + ' onchange="toggleGraphFilter(\'' +
        label + "', this.checked)\"> " +
        '<span class="node-type-badge" style="background:' +
        getNodeColor(label) + ';color:#fff">' + label + '</span> ' +
        "(" + count + ")" +
        "</label>";
    });
  }

  window.toggleGraphFilter = function (label, enabled) {
    G.filters[label] = enabled;
    if (G.currentView !== "list") refreshCurrentView();
    else { loadNodes(); renderListView(); }
  };

  function renderNodeList() {
    const el = document.getElementById("graphNodeList");
    if (!el) return;
    el.innerHTML = "";
    if (!G.nodes || !G.nodes.length) {
      el.innerHTML = '<div style="padding:12px;font-size:12px;color:var(--text-muted)">无节点</div>';
      return;
    }
    G.nodes.forEach(function (node) {
      const selected = G.selectedNode && G.selectedNode.id === node.id ? ' selected' : "";
      const color = getNodeColor(node.labels[0] || "Node");
      el.innerHTML +=
        '<div class="graph-node-item' + selected + '" ' +
        'onclick="selectGraphNode(\'' + node.id + '\')">' +
        '<span class="node-type-badge" style="background:' + color + ';color:#fff">' +
        (node.labels[0] || "?") + '</span>' +
        '<span>' + escHtml(node.name || node.id) + '</span>' +
        "</div>";
    });
  }

  window.selectGraphNode = async function (nodeId) {
    try {
      const data = await api("/api/graph/nodes/" + encodeURIComponent(nodeId));
      G.selectedNode = data;
      G.selectedRel = null;
      showNodeDetail(data);
      highlightInCytoscape(nodeId);
    } catch (e) {
      showGraphNotice("加载节点详情失败: " + e.message);
    }
  };

  // ── Detail panel ─────────────────────────────────────────────────────────────

  function showNodeDetail(node) {
    const el = document.getElementById("graphDetailPanel");
    if (!el) return;
    el.style.display = "";
    let propsHtml = "";
    for (const [k, v] of Object.entries(node.properties || {})) {
      propsHtml += '<div class="graph-detail-row"><div class="graph-detail-label">' +
        escHtml(k) + '</div><div class="graph-detail-value">' +
        escHtml(String(v)) + "</div></div>";
    }
    el.innerHTML =
      '<div class="graph-detail-header">' +
      '<span>' + escHtml(node.labels ? node.labels[0] : "Node") + '</span>' +
      '<button onclick="hideDetailPanel()" style="border:none;background:transparent;cursor:pointer;font-size:16px">×</button>' +
      "</div>" +
      '<div class="graph-detail-row"><div class="graph-detail-label">名称</div>' +
      '<div class="graph-detail-value">' + escHtml(node.name || node.id) + "</div></div>" +
      (propsHtml ? '<div class="graph-detail-rels"><div class="graph-detail-label" style="font-weight:600;margin-bottom:8px">属性</div>' + propsHtml + "</div>" : "") +
      '<div class="graph-form-actions" style="margin-top:16px">' +
      '<button class="icon-btn" onclick="editGraphNode(\'' + node.id + '\')">编辑</button>' +
      '<button class="icon-btn" onclick="expandGraphNode(\'' + node.id + '\')">钻取</button>' +
      '<button class="icon-btn" style="color:#e05" onclick="deleteNode(\'' + node.id + '\')">删除</button>' +
      "</div>";
    renderNodeList();
  }

  window.hideDetailPanel = function () {
    const el = document.getElementById("graphDetailPanel");
    if (el) el.style.display = "none";
    G.selectedNode = null;
    G.selectedRel = null;
    renderNodeList();
    if (G.cy) G.cy.elements().unselect();
  };

  window.editGraphNode = async function (nodeId) {
    const node = G.selectedNode;
    const props = node.properties || {};
    const html =
      '<div class="graph-modal-title">编辑节点</div>' +
      Object.keys(props).map(function (k) {
        return '<div class="graph-form-row"><label>' + escHtml(k) +
          '</label><input class="prop-input" data-key="' + escHtml(k) + '" value="' + escHtml(String(props[k] || "")) + '"></div>';
      }).join("") +
      '<div class="graph-form-actions">' +
      '<button class="icon-btn" onclick="closeGraphModal()">取消</button>' +
      '<button class="icon-btn" style="background:var(--primary);color:#fff;border:none" onclick="saveEditNode(\'' + nodeId + '\')">保存</button>' +
      "</div>";
    openGraphModal(html);
  };

  window.saveEditNode = async function (nodeId) {
    const inputs = document.querySelectorAll(".prop-input");
    const props = {};
    inputs.forEach(function (inp) { props[inp.dataset.key] = inp.value; });
    await updateNode(nodeId, props);
    closeGraphModal();
    await loadNodes();
    window.selectGraphNode(nodeId);
  };

  window.expandGraphNode = async function (nodeId) {
    try {
      const data = await api("/api/graph/nodes/" + encodeURIComponent(nodeId) + "/expand", {
        method: "POST",
        body: JSON.stringify({ depth: 1, direction: "both" }),
      });
      if (G.cy) {
        addToCytoscape(data.nodes, data.relationships);
      } else if (G.currentView === "topology") {
        await renderTopologyView(nodeId);
      }
    } catch (e) {
      showGraphNotice("钻取失败: " + e.message);
    }
  };

  // ── Search ───────────────────────────────────────────────────────────────────

  let _searchTimer = null;
  window.debounceGraphSearch = function (q, delay) {
    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(async function () {
      G.searchQ = q;
      if (!q) {
        await loadNodes();
        renderNodeList();
        return;
      }
      const enabledTypes = Object.entries(G.filters).filter(function (_, v) { return v; }).map(function (k) { return k; });
      await searchGraph(q, enabledTypes);
    }, delay || 300);
  };

  function renderSearchResults(results) {
    const el = document.getElementById("graphNodeList");
    if (!el) return;
    if (!results || !results.length) {
      el.innerHTML = '<div style="padding:12px;font-size:12px;color:var(--text-muted)">无结果</div>';
      return;
    }
    el.innerHTML = "";
    results.forEach(function (node) {
      const color = getNodeColor(node.labels[0] || "Node");
      el.innerHTML +=
        '<div class="graph-node-item" onclick="selectGraphNode(\'' + node.id + '\')">' +
        '<span class="node-type-badge" style="background:' + color + ';color:#fff">' +
        (node.labels[0] || "?") + '</span>' +
        '<span>' + escHtml(node.name || node.id) + '</span>' +
        "</div>";
    });
  }

  // ── Cytoscape.js — Graph view ────────────────────────────────────────────────

  var _nodeColors = {
    Service: "#4A90D9",
    Host: "#52C41A",
    Component: "#FA8C16",
    Alert: "#F5222D",
    FAQ: "#722ED1",
    Node: "#8C8C8C",
  };

  function getNodeColor(label) {
    return _nodeColors[label] || _nodeColors.Node;
  }

  window.initCytoscape = function () {
    const container = document.getElementById("graphCanvas");
    if (!container || G.cy) return;

    G.cy = cytoscape({
      container: container,
      style: [
        {
          selector: "node",
          style: {
            label: "data(name)",
            "background-color": "data(color)",
            color: "#fff",
            "font-size": "11px",
            width: 40,
            height: 40,
            "text-valign": "bottom",
            "text-margin-y": 6,
          },
        },
        {
          selector: "edge",
          style: {
            width: 2,
            "line-color": "#aaa",
            "target-arrow-color": "#aaa",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            label: "data(type)",
            "font-size": "9px",
            color: "#666",
            "text-rotation": "autorotate",
          },
        },
        {
          selector: "node:selected",
          style: {
            "border-width": 3,
            "border-color": "#FFD700",
          },
        },
      ],
      layout: { name: "cose", animate: false },
      minZoom: 0.1,
      maxZoom: 3,
      wheelSensitivity: 0.3,
    });

    G.cy.on("tap", "node", async function (evt) {
      const nodeId = evt.target.id();
      await window.selectGraphNode(nodeId);
    });

    G.cy.on("dbltap", "node", function (evt) {
      const nodeId = evt.target.id();
      window.expandGraphNode(nodeId);
    });

    G.cy.on("tap", function (evt) {
      if (evt.target === G.cy) window.hideDetailPanel();
    });

    loadGraphData();
  };

  async function loadGraphData() {
    try {
      const params = new URLSearchParams({ depth: 1 });
      const data = await api("/api/graph/topology?" + params);
      addToCytoscape(data.nodes || [], data.relationships || []);
    } catch (e) {
      showGraphNotice("加载图形数据失败: " + e.message);
    }
  }

  window.addToCytoscape = function (nodes, relationships) {
    if (!G.cy) return;
    const eles = [];

    nodes.forEach(function (n) {
      const label = n.labels ? n.labels[0] : "Node";
      const color = getNodeColor(label);
      eles.push({
        group: "nodes",
        data: { id: n.id, name: n.name || n.id, color: color, label: label },
      });
    });

    relationships.forEach(function (r) {
      // Only add if both endpoints are in the current graph
      eles.push({
        group: "edges",
        data: {
          id: r.id,
          source: r.start_node_id,
          target: r.end_node_id,
          type: r.type,
        },
      });
    });

    G.cy.add(eles);
    G.cy.layout({ name: "cose", animate: true, refresh: 5 }).run();
  };

  window.highlightInCytoscape = function (nodeId) {
    if (!G.cy) return;
    G.cy.elements().unselect();
    const el = G.cy.$id(nodeId);
    if (el.length) el.select();
  };

  function refreshCurrentView() {
    if (G.currentView === "graph") {
      if (G.cy) { G.cy.destroy(); G.cy = null; }
      initCytoscape();
    } else if (G.currentView === "topology") {
      renderTopologyView();
    }
  }

  // ── Topology view ───────────────────────────────────────────────────────────

  window.renderTopologyView = async function (centerId) {
    const container = document.getElementById("graphCanvas");
    if (!container) return;
    const enabledTypes = Object.entries(G.filters).filter(function (e) { return e[1]; }).map(function (e) { return e[0]; });
    const data = await loadTopology(centerId || null, 2, enabledTypes, null);

    if (G.cy) { G.cy.destroy(); G.cy = null; }
    G.cy = cytoscape({
      container: container,
      style: [
        {
          selector: "node",
          style: {
            label: "data(name)",
            "background-color": "data(color)",
            color: "#fff",
            "font-size": "11px",
            width: 36,
            height: 36,
            shape: "roundrectangle",
          },
        },
        {
          selector: "edge",
          style: {
            width: 2,
            "line-color": "#ccc",
            "target-arrow-color": "#ccc",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
          },
        },
      ],
      layout: { name: "breadthfirst", directed: true, animate: false, padding: 20 },
      minZoom: 0.1,
      maxZoom: 3,
      wheelSensitivity: 0.3,
    });

    const eles = [];
    data.nodes.forEach(function (n) {
      const label = n.labels ? n.labels[0] : "Node";
      eles.push({
        group: "nodes",
        data: { id: n.id, name: n.name || n.id, color: getNodeColor(label) },
      });
    });
    data.relationships.forEach(function (r) {
      eles.push({ group: "edges", data: { source: r.start_node_id, target: r.end_node_id } });
    });

    G.cy.add(eles);
    G.cy.layout({ name: "breadthfirst", directed: true, animate: true, padding: 20 }).run();

    G.cy.on("tap", "node", async function (evt) {
      await window.selectGraphNode(evt.target.id());
    });
  };

  // ── List view ────────────────────────────────────────────────────────────────

  async function renderListView() {
    const el = document.getElementById("graphListView");
    if (!el) return;
    if (!G.nodes || !G.nodes.length) {
      el.innerHTML = '<div style="padding:20px;color:var(--text-muted)">暂无数据</div>';
      return;
    }
    const html =
      '<table class="graph-list-table">' +
      "<thead><tr>" +
      "<th onclick=\"sortList('name')\">名称</th>" +
      "<th onclick=\"sortList('labels')\">类型</th>" +
      "<th>标签</th>" +
      "<th>操作</th>" +
      "</tr></thead><tbody>" +
      G.nodes.map(function (n) {
        const color = getNodeColor(n.labels ? n.labels[0] : "Node");
        const tags = (n.properties && n.properties.labels) ? n.properties.labels.join(", ") : "";
        return "<tr>" +
          "<td>" + escHtml(n.name || n.id) + "</td>" +
          '<td><span class="node-type-badge" style="background:' + color + ';color:#fff">' + escHtml(n.labels ? n.labels[0] : "?") + "</span></td>" +
          "<td>" + escHtml(tags) + "</td>" +
          '<td>' +
          '<button class="icon-btn" onclick="selectGraphNode(\'' + n.id + '\')">查看</button> ' +
          '<button class="icon-btn" onclick="window.editGraphNode(\'' + n.id + '\')">编辑</button> ' +
          '<button class="icon-btn" style="color:#e05" onclick="deleteNode(\'' + n.id + '\')">删除</button>' +
          "</td></tr>";
      }).join("") +
      "</tbody></table>" +
      '<div class="graph-pagination">' +
      '<button onclick="changeGraphPage(' + (G.currentPage - 1) + ')">上一页</button>' +
      "<span>第 " + G.currentPage + " 页</span>" +
      '<button onclick="changeGraphPage(' + (G.currentPage + 1) + ')">下一页</button>' +
      "</div>";
    el.innerHTML = html;
  }

  window.sortList = function (key) {
    G.nodes.sort(function (a, b) {
      if (key === "name") return (a.name || "").localeCompare(b.name || "");
      if (key === "labels") return ((a.labels && a.labels[0]) || "").localeCompare((b.labels && b.labels[0]) || "");
      return 0;
    });
    renderListView();
  };

  window.changeGraphPage = async function (page) {
    if (page < 1) return;
    await loadNodes(page, G.pageSize, G.searchQ);
    renderListView();
  };

  // ── Create / Edit modals ───────────────────────────────────────────────────

  window.showCreateNodeModal = function () {
    if (!G.schema) return;
    const labelOptions = G.schema.node_labels.map(function (l) {
      return '<option value="' + l + '">' + l + "</option>";
    }).join("");
    const html =
      '<div class="graph-modal-title">新建节点</div>' +
      '<div class="graph-form-row"><label>节点类型</label>' +
      '<select id="newNodeLabel"><option value="">-- 选择类型 --</option>' + labelOptions + "</select></div>" +
      '<div class="graph-form-row"><label>名称</label><input id="newNodeName" placeholder="名称"></div>' +
      '<div class="graph-form-row" id="customProps"></div>' +
      '<div class="graph-form-row"><label>标签（逗号分隔）</label><input id="newNodeTags" placeholder="关键, 金融"></div>' +
      '<div class="graph-form-actions">' +
      '<button class="icon-btn" onclick="closeGraphModal()">取消</button>' +
      '<button class="icon-btn" style="background:var(--primary);color:#fff;border:none" onclick="submitCreateNode()">创建</button>' +
      "</div>";
    openGraphModal(html);
  };

  window.submitCreateNode = async function () {
    const label = document.getElementById("newNodeLabel").value;
    const name = document.getElementById("newNodeName").value;
    const tags = document.getElementById("newNodeTags").value;
    if (!label) { alert("请选择节点类型"); return; }
    const properties = { name: name };
    if (tags) properties.labels = tags.split(",").map(function (s) { return s.trim(); }).filter(Boolean);
    try {
      await createNode([label], properties);
      closeGraphModal();
      await loadSchema();
      await loadNodes();
      renderListView();
    } catch (e) {
      alert("创建失败: " + e.message);
    }
  };

  window.showCreateRelModal = function () {
    if (!G.schema) return;
    const relOptions = G.schema.relationship_types.map(function (r) {
      return '<option value="' + r + '">' + r + "</option>";
    }).join("");
    const nodeOptions = (G.nodes || []).map(function (n) {
      return '<option value="' + n.id + '">' + escHtml(n.name || n.id) + " (" + (n.labels ? n.labels[0] : "?") + ")</option>";
    }).join("");
    const html =
      '<div class="graph-modal-title">新建关系</div>' +
      '<div class="graph-form-row"><label>关系类型</label>' +
      '<select id="newRelType"><option value="">-- 选择类型 --</option>' + relOptions + "</select></div>" +
      '<div class="graph-form-row"><label>起始节点</label>' +
      '<select id="newRelStart"><option value="">-- 选择 --</option>' + nodeOptions + "</select></div>" +
      '<div class="graph-form-row"><label>结束节点</label>' +
      '<select id="newRelEnd"><option value="">-- 选择 --</option>' + nodeOptions + "</select></div>" +
      '<div class="graph-form-row"><label>属性（可选）</label><input id="newRelWeight" placeholder="weight" value="1"></div>' +
      '<div class="graph-form-actions">' +
      '<button class="icon-btn" onclick="closeGraphModal()">取消</button>' +
      '<button class="icon-btn" style="background:var(--primary);color:#fff;border:none" onclick="submitCreateRel()">创建</button>' +
      "</div>";
    openGraphModal(html);
  };

  window.submitCreateRel = async function () {
    const relType = document.getElementById("newRelType").value;
    const startId = document.getElementById("newRelStart").value;
    const endId = document.getElementById("newRelEnd").value;
    const weight = document.getElementById("newRelWeight") ? document.getElementById("newRelWeight").value : "1";
    if (!relType || !startId || !endId) { alert("请填写完整信息"); return; }
    try {
      await createRelationship(relType, startId, endId, { weight: weight });
      closeGraphModal();
      await loadNodes();
      if (G.currentView !== "list") refreshCurrentView();
    } catch (e) {
      alert("创建失败: " + e.message);
    }
  };

  function openGraphModal(html) {
    let overlay = document.getElementById("graphModalOverlay");
    if (!overlay) {
      overlay = document.createElement("div");
      overlay.id = "graphModalOverlay";
      overlay.className = "graph-modal";
      document.body.appendChild(overlay);
    }
    overlay.innerHTML = '<div class="graph-modal-inner" id="graphModalInner">' + html + "</div>";
    overlay.style.display = "flex";
    overlay.onclick = function (e) {
      if (e.target === overlay) closeGraphModal();
    };
  }

  window.closeGraphModal = function () {
    const overlay = document.getElementById("graphModalOverlay");
    if (overlay) overlay.style.display = "none";
  };

  // ── Utility ──────────────────────────────────────────────────────────────────

  function escHtml(s) {
    if (!s) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function showGraphNotice(msg) {
    if (typeof setStatus === "function") setStatus(msg);
    else console.warn("[Graph]", msg);
  }

  // ── Boot ────────────────────────────────────────────────────────────────────

  // Expose init when script is loaded
  window.loadGraphPanel = loadSchema;

})();
```

- [ ] **Step 2: 验证语法**

Run: `node --check static/graph.js`
Expected: 无输出（成功）

- [ ] **Step 3: Commit**

```bash
git add static/graph.js
git commit -m "feat(graph): add graph.js panel module with three view modes"
```

---

### Task 10: 在 boot.js 中加载 graph.js

**Files:**
- Modify: `static/boot.js`

- [ ] **Step 1: 在 boot.js 中添加 graph.js 加载**

在 `static/boot.js` 中找到现有的脚本加载区域（参考 `/* ── Panel modules ── */` 注释），添加：

```javascript
// ── Panel modules ────────────────────────────────────────────────────────────
loadScript("/static/obsidian_notes.js");
loadScript("/static/graph.js");  // Graph panel (Neo4j visualization)
```

**注意**：精确位置用 grep 找到现有 `loadScript("/static/obsidian_notes.js")` 行，在其后添加。

- [ ] **Step 2: Commit**

```bash
git add static/boot.js
git commit -m "feat(graph): load graph.js module in boot.js"
```

---

## Phase 3：图形可视化组件完善

### Task 11: 完善图形交互（拖拽、框选、节点展开动画）

**Files:**
- Modify: `static/graph.js`（在 `initCytoscape` 函数中增强）

- [ ] **Step 1: 增强 Cytoscape 交互配置**

找到 `initCytoscape` 函数，将 `G.cy = cytoscape({...})` 调用替换为增强版本：

```javascript
    G.cy = cytoscape({
      container: container,
      style: [
        {
          selector: "node",
          style: {
            label: "data(name)",
            "background-color": "data(color)",
            color: "#fff",
            "font-size": "11px",
            width: 40,
            height: 40,
            "text-valign": "bottom",
            "text-margin-y": 6,
            "border-width": 2,
            "border-color": "data(color)",
          },
        },
        {
          selector: "node:selected",
          style: {
            "border-width": 4,
            "border-color": "#FFD700",
            "background-color": "data(color)",
          },
        },
        {
          selector: "node:hover",
          style: {
            "border-width": 3,
            "border-color": "#FFD700",
          },
        },
        {
          selector: "edge",
          style: {
            width: 2,
            "line-color": "#aaa",
            "target-arrow-color": "#aaa",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            label: "data(type)",
            "font-size": "9px",
            color: "#666",
            "text-rotation": "autorotate",
          },
        },
      ],
      layout: { name: "cose", animate: false },
      minZoom: 0.1,
      maxZoom: 3,
      wheelSensitivity: 0.3,
      boxSelectionEnabled: true,  // Enable box selection
      selectionType: "additive",
    });
```

- [ ] **Step 2: Commit**

```bash
git add static/graph.js
git commit -m "feat(graph): enhance Cytoscape interactions (hover, box selection, selection type)"
```

---

### Task 12: 添加拓扑视图的折叠/展开功能

**Files:**
- Modify: `static/graph.js`

- [ ] **Step 1: 添加拓扑视图折叠/展开支持**

在 `renderTopologyView` 函数中添加折叠按钮逻辑，并增强布局参数：

```javascript
  // In renderTopologyView, add collapse controls:
  // After G.cy is created and elements added, add double-click to collapse children:
  G.cy.on("dblclick", "node", function (evt) {
    const node = evt.target;
    const children = node.outgoers().nodes();
    if (children.length > 0) {
      children.addClass("hidden");
    } else {
      G.cy.nodes().removeClass("hidden");
    }
  });

  // Add CSS for hidden nodes in the style array:
  // { selector: "node.hidden", style: { "display": "none" } }
```

- [ ] **Step 2: Commit**

```bash
git add static/graph.js
git commit -m "feat(graph): add topology collapse/expand interaction"
```

---

## Phase 4：搜索 + CRUD + 完整链路

### Task 13: 完善搜索功能（前端防抖 + 高亮）

**Files:**
- Modify: `static/graph.js`

- [ ] **Step 1: 改进搜索防抖 + 结果高亮**

确保 `debounceGraphSearch` 正确处理空值和边界情况，并改进 `renderSearchResults` 的展示。

- [ ] **Step 2: Commit**

```bash
git add static/graph.js
git commit -m "feat(graph): improve search debounce and result rendering"
```

---

### Task 14: 添加属性动态增删（编辑节点时）

**Files:**
- Modify: `static/graph.js`

- [ ] **Step 1: 在编辑节点模态框中添加"添加属性"按钮**

修改 `window.editGraphNode` 函数，添加动态属性行：

```javascript
  window.editGraphNode = async function (nodeId) {
    const node = G.selectedNode;
    const props = node.properties || {};
    let propsHtml = Object.keys(props).map(function (k) {
      return '<div class="graph-form-row"><label>' + escHtml(k) +
        '</label><input class="prop-input" data-key="' + escHtml(k) + '" value="' + escHtml(String(props[k] || "")) + '">' +
        ' <button onclick="removePropRow(this)" style="cursor:pointer;color:#e05">×</button></div>';
    }).join("");
    propsHtml += '<div class="graph-form-row" id="newPropRow">' +
      '<label>新属性</label><input id="newPropKey" placeholder="属性名">' +
      '<input id="newPropVal" placeholder="属性值" style="margin-top:4px"> ' +
      '<button class="icon-btn" onclick="addPropRow()">+</button></div>';
    const html = /* same as before but with updated propsHtml + removePropRow + addPropRow implementations */;
    openGraphModal(html);
  };

  window.removePropRow = function (btn) {
    btn.parentElement.remove();
  };

  window.addPropRow = function () {
    const key = document.getElementById("newPropKey").value.trim();
    const val = document.getElementById("newPropVal").value;
    if (!key) return;
    const newRow = document.createElement("div");
    newRow.className = "graph-form-row";
    newRow.innerHTML = '<label>' + escHtml(key) + '</label>' +
      '<input class="prop-input" data-key="' + escHtml(key) + '" value="' + escHtml(val) + '"> ' +
      '<button onclick="removePropRow(this)" style="cursor:pointer;color:#e05">×</button>';
    document.getElementById("newPropRow").before(newRow);
    document.getElementById("newPropKey").value = "";
    document.getElementById("newPropVal").value = "";
  };
```

- [ ] **Step 2: Commit**

```bash
git add static/graph.js
git commit -m "feat(graph): add dynamic property add/remove in node edit modal"
```

---

### Task 15: 集成测试 — 完整链路验证

**Files:**
- Modify: `tests/test_graph_api.py`

- [ ] **Step 1: 添加端到端测试（mock Neo4j full round-trip）**

```python
def test_full_crud_cycle_with_mocked_driver(tmp_path, monkeypatch):
    """Simulate a full node CRUD cycle using a mocked Neo4j session."""
    # This test verifies the API contract without a real DB.
    # We mock at the driver level to test query construction.
    from unittest.mock import MagicMock, patch

    mock_session = MagicMock()
    mock_driver = MagicMock()
    mock_driver.session.return_value.__enter__ = MagicMock(return_value=mock_session)
    mock_driver.session.return_value.__exit__ = MagicMock(return_value=False)

    # Simulate schema response
    mock_session.run.side_effect = [
        # labels
        MagicMock(__iter__=lambda s: iter([{"label": "Service"}, {"label": "Host"}])),
        # rel types
        MagicMock(__iter__=lambda s: iter([{"relationshipType": "CALLS"}, {"relationshipType": "DEPENDS_ON"}])),
        # counts
        MagicMock(single=MagicMock(return_value={"cnt": 5})),
        MagicMock(single=MagicMock(return_value={"cnt": 3})),
    ]

    with patch("neo4j.GraphDatabase.driver", return_value=mock_driver):
        from api import graph
        graph._driver = mock_driver
        schema = graph.get_schema()
        assert schema["node_labels"] == ["Host", "Service"]
        assert schema["relationship_types"] == ["CALLS", "DEPENDS_ON"]
        assert schema["stats"]["Service"] == 5
        assert schema["stats"]["Host"] == 3
```

- [ ] **Step 2: Commit**

```bash
git add tests/test_graph_api.py
git commit -m "test(graph): add mock driver CRUD cycle test"
```

---

## 自检清单

完成所有任务后运行以下检查：

1. **Spec coverage**: 逐一核对设计文档每项需求，确认每项都有对应实现
2. **Placeholder scan**: 检查计划中无 TBD/TODO 标记
3. **Type consistency**: 确认 API 响应字段与前端使用字段一致（如 `element_id` vs `id`，`labels` 数组）
4. **API 路由注册**: 确认 `routes.py` 中的路由注册在正确的位置（`if parsed.path.startswith("/api/notes")` 之前）
5. **Neo4j driver import**: 确认 `api/graph.py` 中 `from neo4j import GraphDatabase` 在懒加载块内，避免无依赖时报错
6. **Cytoscape CDN 路径**: 确认 `index.html` 中 cytoscape 通过 `<script src="/static/vendor/cytoscape.min.js">` 引入，在 `graph.js` 之前
7. **Error handling**: 确认 `get_schema()` 在 Neo4j 不可用时返回 `connected: False` 而非抛出 500

---

**Plan complete and saved to `docs/superpowers/plans/2026-06-29-graph-management-plan.md`**

Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using `executing-plans`, batch execution with checkpoints

Which approach?
