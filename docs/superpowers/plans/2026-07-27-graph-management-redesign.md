# 图库管理面板重做 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `feat/graph-management` 分支上"半成品"的 Graph 面板重做成完整可用的图库管理工具（搜索能用、Table/JSON/Graph 三视图、Mock 降级、CRUD、一键加载示例）。

**Architecture:** 分层重构 + Mock 降级。后端把 `api/graph.py` 拆成 `graph_store.py` 接口 + `graph_neo4j.py` / `graph_mock.py` 两个实现；前端把 `static/graph.js`（1076+ 行单文件）拆成 `graph_main.js` 主控 + 4 个视图 / 模块文件。

**Tech Stack:** Python 3.11 / sqlite3（标准库）/ Neo4j Python Driver / Cytoscape.js v3.30（已 vendor）/ vitest + jsdom（前端单测）。

**⚠️ 重要：用户偏好**
- 设计文档 / 计划文档正常 commit
- **所有源代码改动（.py / .js / .css / .html / 等）stage 后暂停，等用户确认再 commit**
- 不要执行 `git commit` 对源码改动，除非用户明确说"提交" / "commit"

---

## 文件结构

### 新建

| 文件 | 职责 |
|---|---|
| `api/graph_store.py` | `GraphStore` Protocol，所有方法以 dict / list[dict] 进出 |
| `api/graph_neo4j.py` | Neo4j 实现，把现 `api/graph.py` 的 Cypher 搬过来并修复 `*1..$depth` |
| `api/graph_mock.py` | SQLite 实现（标准库），持久化到 `data/graph.sqlite` |
| `static/graph_main.js` | 主控：面板初始化、健康探测、tab 切换、状态管理 |
| `static/graph_view_graph.js` | Cytoscape 视图（修 API 解析 bug、tab 切换 resize） |
| `static/graph_view_table.js` | 表格视图（Nodes / Relationships 双表） |
| `static/graph_view_json.js` | JSON 视图（树 + 详情面板） |
| `static/graph_crud.js` | CRUD 模态框 |
| `tests/test_graph_mock.py` | SQLite 实现测试（Cypher-free，CI 友好） |
| `tests/test_graph_neo4j.py` | Cypher 字符串生成测试（不连真实 Neo4j） |
| `tests/test_graph_main.spec.js` | vitest + jsdom 前端单测 |

### 修改

| 文件 | 修改内容 |
|---|---|
| `api/graph.py` | 瘦壳化：保留 `handle_graph_get/post/delete`，分发到 `get_store()` |
| `static/index.html` | 重写 `panelGraph` DOM 为 tab 结构 + 加载新 JS 模块 |
| `static/style.css` | 删除 2659-2698 死代码；新增 tabs/table/json/crud/empty-state 样式 |
| `static/boot.js` | （可能）无需改动，模块自加载 |
| `tests/test_graph_api.py` | 加包装层断言（{ok, data, error}） |
| `.gitignore` | 加 `data/graph.sqlite` 忽略 mock 数据库文件 |

### 删除 / 替换

| 文件 | 处理 |
|---|---|
| `static/graph.js` | 删除（被 `graph_main.js` 取代）；`index.html` 改引用 |

---

## Task 1: GraphStore 接口 + 健康探测契约

**Files:**
- Create: `api/graph_store.py`
- Test: `tests/test_graph_store.py`

- [ ] **Step 1: 写失败的测试**

`tests/test_graph_store.py`：

```python
"""GraphStore 接口契约测试。"""
import pytest
from api.graph_store import GraphStore


def test_graphstore_is_a_protocol():
    """GraphStore 必须是 Protocol，不能是具体类。"""
    assert hasattr(GraphStore, "_is_protocol")
    # 验证是 Protocol 而非 ABC
    assert not hasattr(GraphStore, "register")


def test_protocol_has_required_methods():
    """接口必须声明所有规范要求的方法。"""
    required = {
        "health", "schema", "search", "list_nodes",
        "get_node", "get_relationship", "list_relationships",
        "topology", "create_node", "create_relationship",
        "update_node", "delete_node", "delete_relationship",
        "seed_sample",
    }
    for name in required:
        assert hasattr(GraphStore, name), f"missing method: {name}"


def test_health_returns_required_keys():
    """health() 必须返回包含 backend/ok/detail 的字典。"""
    class FakeStore:
        def health(self): return {"backend": "mock", "ok": True, "detail": "ok"}
        def schema(self): return {}
        def search(self, q, label=None, limit=50): return {"results": [], "query": q, "count": 0}
        def list_nodes(self, label, limit=200): return {"results": [], "count": 0}
        def get_node(self, eid): return None
        def get_relationship(self, eid): return None
        def list_relationships(self, eid, direction="both"): return []
        def topology(self, eid, depth=1): return {"nodes": [], "relationships": []}
        def create_node(self, labels, properties): return {}
        def create_relationship(self, t, s, e, properties=None): return {}
        def update_node(self, eid, properties): return {}
        def delete_node(self, eid): return {}
        def delete_relationship(self, eid): return {}
        def seed_sample(self): return {}

    fs = FakeStore()
    h = fs.health()
    assert "backend" in h
    assert "ok" in h
    assert "detail" in h
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `pytest tests/test_graph_store.py -v`
Expected: `ModuleNotFoundError: No module named 'api.graph_store'`

- [ ] **Step 3: 实现 GraphStore Protocol**

`api/graph_store.py`：

```python
"""GraphStore 接口定义。

所有存储实现（Neo4j / Mock）必须遵循此协议，方法以 dict / list[dict]
进出，不暴露后端特定类型。
"""
from __future__ import annotations
from typing import Protocol, runtime_checkable


@runtime_checkable
class GraphStore(Protocol):
    """图存储抽象接口。"""

    def health(self) -> dict:
        """健康探测。返回 {"backend": "neo4j"|"mock", "ok": bool, "detail": str, ...}"""
        ...

    def schema(self) -> dict:
        """Schema 概览。返回 {"node_labels": [...], "relationship_types": [...], "stats": {...}}"""
        ...

    def search(self, query: str, label: str | None = None, limit: int = 50) -> dict:
        """按关键字搜索节点。返回 {"results": [...], "query": str, "count": int}"""
        ...

    def list_nodes(self, label: str, limit: int = 200) -> dict:
        """按 label 列出节点。返回 {"results": [...], "count": int}"""
        ...

    def get_node(self, element_id: str) -> dict | None:
        """按 element_id 拿节点。不存在返回 None。"""
        ...

    def get_relationship(self, element_id: str) -> dict | None:
        """按 element_id 拿关系。不存在返回 None。"""
        ...

    def list_relationships(self, element_id: str, direction: str = "both") -> list[dict]:
        """列出节点的所有关系。direction in {"in","out","both"}"""
        ...

    def topology(self, element_id: str, depth: int = 1) -> dict:
        """返回以节点为中心、depth 跳内的子图。{"nodes": [...], "relationships": [...]}"""
        ...

    def create_node(self, labels: list[str], properties: dict) -> dict:
        """创建节点，返回创建的节点 dict（含新 id）。"""
        ...

    def create_relationship(self, type_: str, start_id: str, end_id: str,
                            properties: dict | None = None) -> dict:
        """创建关系，返回创建的关系 dict（含新 id）。"""
        ...

    def update_node(self, element_id: str, properties: dict) -> dict:
        """更新节点 properties（merge / replace）。返回更新后的节点。"""
        ...

    def delete_node(self, element_id: str) -> dict:
        """删除节点（级联删除关系）。返回 {"deleted": True}。"""
        ...

    def delete_relationship(self, element_id: str) -> dict:
        """删除关系。返回 {"deleted": True}。"""
        ...

    def seed_sample(self) -> dict:
        """加载示例图谱。返回 {"nodes_added": int, "relationships_added": int}。"""
        ...
```

- [ ] **Step 4: 跑测试，确认通过**

Run: `pytest tests/test_graph_store.py -v`
Expected: 3 passed

- [ ] **Step 5: ⚠️ 不 commit — 等用户确认**

---

## Task 2: SQLite Mock 实现

**Files:**
- Create: `api/graph_mock.py`
- Test: `tests/test_graph_mock.py`
- Modify: `.gitignore`

- [ ] **Step 1: 写失败的测试**

`tests/test_graph_mock.py`：

```python
"""Mock (SQLite) 存储实现测试。Cypher-free，CI 友好。"""
import os
import tempfile
import pytest
from api.graph_mock import MockStore


@pytest.fixture
def store(tmp_path):
    db_path = str(tmp_path / "graph.sqlite")
    s = MockStore(db_path=db_path)
    yield s
    s.close()


def test_health_ok(store):
    h = store.health()
    assert h["backend"] == "mock"
    assert h["ok"] is True
    assert "detail" in h


def test_schema_empty(store):
    s = store.schema()
    assert s["node_labels"] == []
    assert s["relationship_types"] == []
    assert s["stats"]["node_count"] == 0
    assert s["stats"]["relationship_count"] == 0


def test_create_and_get_node(store):
    n = store.create_node(["Host"], {"name": "web-01", "ip": "10.0.0.1"})
    assert "id" in n
    assert "Host" in n["labels"]
    assert n["properties"]["name"] == "web-01"

    fetched = store.get_node(n["id"])
    assert fetched["id"] == n["id"]
    assert fetched["properties"]["name"] == "web-01"


def test_get_node_missing(store):
    assert store.get_node("does-not-exist") is None


def test_list_nodes_by_label(store):
    store.create_node(["Host"], {"name": "web-01"})
    store.create_node(["Host"], {"name": "db-01"})
    store.create_node(["Service"], {"name": "nginx"})
    res = store.list_nodes("Host")
    assert res["count"] == 2
    assert all(n["labels"] == ["Host"] for n in res["results"])


def test_search_by_keyword(store):
    store.create_node(["Host"], {"name": "web-01"})
    store.create_node(["Service"], {"name": "nginx", "version": "1.24"})
    res = store.search("nginx")
    assert res["count"] == 1
    assert res["results"][0]["properties"]["name"] == "nginx"
    # 验证 response shape（修前端 bug 关键）
    assert "results" in res
    assert "query" in res
    assert "count" in res


def test_create_relationship(store):
    a = store.create_node(["Host"], {"name": "web-01"})
    b = store.create_node(["Host"], {"name": "db-01"})
    r = store.create_relationship("DEPENDS_ON", a["id"], b["id"], {"since": "2024"})
    assert r["type"] == "DEPENDS_ON"
    assert r["start_node_id"] == a["id"]
    assert r["end_node_id"] == b["id"]


def test_topology_depth_1(store):
    a = store.create_node(["Host"], {"name": "a"})
    b = store.create_node(["Host"], {"name": "b"})
    c = store.create_node(["Host"], {"name": "c"})
    store.create_relationship("DEPENDS_ON", a["id"], b["id"])
    store.create_relationship("DEPENDS_ON", b["id"], c["id"])
    topo = store.topology(a["id"], depth=1)
    node_ids = {n["id"] for n in topo["nodes"]}
    assert a["id"] in node_ids
    assert b["id"] in node_ids
    assert c["id"] not in node_ids  # depth=1 只看一层


def test_topology_depth_2(store):
    a = store.create_node(["Host"], {"name": "a"})
    b = store.create_node(["Host"], {"name": "b"})
    c = store.create_node(["Host"], {"name": "c"})
    store.create_relationship("DEPENDS_ON", a["id"], b["id"])
    store.create_relationship("DEPENDS_ON", b["id"], c["id"])
    topo = store.topology(a["id"], depth=2)
    node_ids = {n["id"] for n in topo["nodes"]}
    assert c["id"] in node_ids  # depth=2 看到两层


def test_update_node(store):
    n = store.create_node(["Host"], {"name": "web-01", "ip": "10.0.0.1"})
    updated = store.update_node(n["id"], {"ip": "10.0.0.2"})
    assert updated["properties"]["ip"] == "10.0.0.2"
    assert updated["properties"]["name"] == "web-01"  # 保留


def test_delete_node_cascades_relationships(store):
    a = store.create_node(["Host"], {"name": "a"})
    b = store.create_node(["Host"], {"name": "b"})
    r = store.create_relationship("DEPENDS_ON", a["id"], b["id"])
    store.delete_node(a["id"])
    assert store.get_node(a["id"]) is None
    assert store.get_relationship(r["id"]) is None


def test_seed_sample_idempotent(store):
    res1 = store.seed_sample()
    assert res1["nodes_added"] > 0
    res2 = store.seed_sample()
    # 已存在的 name 不重复插入
    schema = store.schema()
    assert schema["stats"]["node_count"] == res1["nodes_added"]
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `pytest tests/test_graph_mock.py -v`
Expected: `ModuleNotFoundError: No module named 'api.graph_mock'`

- [ ] **Step 3: 实现 MockStore**

`api/graph_mock.py`：

```python
"""SQLite 后端 Mock 实现，无需 Neo4j。

持久化到 data/graph.sqlite（gitignored）。
"""
from __future__ import annotations
import json
import os
import sqlite3
import uuid
from typing import Any


def _gen_id() -> str:
    return f"mock-{uuid.uuid4().hex[:16]}"


class MockStore:
    def __init__(self, db_path: str = "data/graph.sqlite"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def close(self):
        self.conn.close()

    def _ensure_schema(self):
        cur = self.conn.cursor()
        cur.executescript("""
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
                name TEXT PRIMARY KEY  -- seed_sample 幂等性
            );
        """)
        self.conn.commit()

    def health(self) -> dict:
        try:
            self.conn.execute("SELECT 1").fetchone()
            return {"backend": "mock", "ok": True, "detail": f"sqlite at {self.db_path}"}
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
        results = []
        for row in cur.execute("SELECT id, labels, properties FROM nodes"):
            labels = json.loads(row["labels"])
            if label not in labels:
                continue
            results.append({
                "id": row["id"],
                "labels": labels,
                "properties": json.loads(row["properties"]),
            })
            if len(results) >= limit:
                break
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

    def topology(self, element_id: str, depth: int = 1) -> dict:
        # Python 端 BFS，避免 Cypher 兼容问题
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
        # 幂等：通过 sample_names 表去重
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
        for label, name, props in sample_nodes:
            existing = self.conn.execute(
                "SELECT 1 FROM sample_names WHERE name = ?", (name,)
            ).fetchone()
            if existing:
                continue
            n = self.create_node([label], {"name": name, **props})
            name_to_id[name] = n["id"]
            self.conn.execute("INSERT INTO sample_names (name) VALUES (?)", (name,))
            added += 1
        self.conn.commit()

        # 关系（仅在节点都存在时插入）
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
                self.create_relationship(type_, sid, eid)
                rel_added += 1
        return {"nodes_added": added, "relationships_added": rel_added}
```

- [ ] **Step 4: 更新 .gitignore**

`.gitignore` 末尾添加：

```
data/graph.sqlite
data/
!data/.gitkeep
```

- [ ] **Step 5: 跑测试，确认通过**

Run: `pytest tests/test_graph_mock.py -v`
Expected: 11 passed

- [ ] **Step 6: ⚠️ 不 commit — 等用户确认**

---

## Task 3: Neo4j 实现（迁移 + 修 Cypher）

**Files:**
- Create: `api/graph_neo4j.py`
- Test: `tests/test_graph_neo4j.py`

- [ ] **Step 1: 写失败的 Cypher 生成测试**

`tests/test_graph_neo4j.py`：

```python
"""Neo4j Cypher 字符串生成测试。不连真实数据库，只断言生成的 Cypher 正确。"""
import pytest
from api.graph_neo4j import _build_topology_cypher, _validate_identifier


def test_validate_identifier_accepts():
    _validate_identifier("Host", "label")
    _validate_identifier("DEPENDS_ON", "type")


def test_validate_identifier_rejects_injection():
    with pytest.raises(ValueError):
        _validate_identifier("Host` MATCH (n) DETACH DELETE n --", "label")
    with pytest.raises(ValueError):
        _validate_identifier("1; DROP TABLE nodes;--", "label")


def test_topology_cypher_uses_literal_depth():
    """关键修复：*1..$depth 不能用参数化上限，改字符串拼接 N。"""
    cypher, params = _build_topology_cypher("DEPENDS_ON", direction="both",
                                            depth=2, rel_types=None, limit=100)
    assert "*1..2" in cypher
    assert "$depth" not in cypher  # 不能参数化上限
    assert params["limit"] == 100
    assert "elementId(center) = $element_id" in cypher


def test_topology_cypher_clamps_depth():
    """depth 必须在 [1, 5] 内。"""
    for bad in (0, -1, 6, 100):
        with pytest.raises(ValueError):
            _build_topology_cypher("DEPENDS_ON", direction="both", depth=bad,
                                   rel_types=None, limit=50)


def test_topology_cypher_filters_rel_types():
    cypher, params = _build_topology_cypher("DEPENDS_ON", direction="out",
                                            depth=1, rel_types=["DEPENDS_ON"], limit=50)
    assert "DEPENDS_ON" in cypher
    assert "$depth" not in cypher


def test_topology_cypher_direction_in():
    cypher, _ = _build_topology_cypher("DEPENDS_ON", direction="in",
                                       depth=1, rel_types=None, limit=50)
    assert "<-[r]-" in cypher
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `pytest tests/test_graph_neo4j.py -v`
Expected: `ModuleNotFoundError: No module named 'api.graph_neo4j'`

- [ ] **Step 3: 实现 Neo4jStore + helper**

`api/graph_neo4j.py`：

```python
"""Neo4j 后端实现。

环境变量：
  NEO4J_URI      (默认 bolt://localhost:7687)
  NEO4J_USER     (默认 neo4j)
  NEO4J_PASSWORD (必需，否则 health() 报 not_configured)
"""
from __future__ import annotations
import os
import logging
from typing import Any

logger = logging.getLogger(__name__)

_VALID_ID = __import__("re").compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_identifier(value: str, kind: str) -> None:
    if not isinstance(value, str) or not _VALID_ID.match(value):
        raise ValueError(f"Invalid {kind}: {value!r}")


def _build_topology_cypher(direction: str, depth: int, rel_types: list[str] | None,
                           limit: int) -> tuple[str, dict]:
    """构建 topology 查询 Cypher。关键：N 字符串拼接而非参数化。"""
    if not isinstance(depth, int) or depth < 1 or depth > 5:
        raise ValueError(f"depth must be int in [1,5], got {depth}")

    dir_pattern = {
        "both": "-[r]-",
        "in": "<-[r]-",
        "out": "-[r]->",
    }[direction]

    rel_clause = ""
    if rel_types:
        for rt in rel_types:
            _validate_identifier(rt, "relationship type")
        types_str = "|".join(f":`{rt}`" for rt in rel_types)
        rel_clause = f"AND type(r) IN [{types_str}]"

    # 关键修复：N 直接拼字符串，避免 *1..$depth 参数化上限不支持
    cypher = (
        f"MATCH path = (center){dir_pattern}*1..{depth}(neighbor) "
        f"WHERE elementId(center) = $element_id {rel_clause} "
        f"RETURN center, nodes(path) AS ns, relationships(path) AS rs "
        f"LIMIT $limit"
    )
    return cypher, {"element_id": "", "limit": limit}


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
            self._driver = GraphDatabase.driver(self._uri, auth=(self._user, self._password))
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

    # ---- CRUD 方法：调用 _connect() 后做 Cypher，转换为 dict ----
    # （完整的 CRUD 方法实现在 Task 3.5 一次性补全 ——
    #  此处仅声明以满足 Protocol 测试）

    def schema(self) -> dict:
        ...

    def search(self, query: str, label: str | None = None, limit: int = 50) -> dict:
        ...

    def list_nodes(self, label: str, limit: int = 200) -> dict:
        ...

    def get_node(self, element_id: str) -> dict | None:
        ...

    def get_relationship(self, element_id: str) -> dict | None:
        ...

    def list_relationships(self, element_id: str, direction: str = "both") -> list[dict]:
        ...

    def topology(self, element_id: str, depth: int = 1) -> dict:
        ...

    def create_node(self, labels: list[str], properties: dict) -> dict:
        ...

    def create_relationship(self, type_: str, start_id: str, end_id: str,
                            properties: dict | None = None) -> dict:
        ...

    def update_node(self, element_id: str, properties: dict) -> dict:
        ...

    def delete_node(self, element_id: str) -> dict:
        ...

    def delete_relationship(self, element_id: str) -> dict:
        ...

    def seed_sample(self) -> dict:
        ...
```

- [ ] **Step 4: 跑测试，确认通过（至少 helper 部分）**

Run: `pytest tests/test_graph_neo4j.py -v`
Expected: 6 passed（CRUD 方法暂未实现，但 Protocol 测试不查它们）

- [ ] **Step 5: ⚠️ 不 commit — 等用户确认**

---

## Task 4: 把 Neo4jStore CRUD 方法补全

**Files:**
- Modify: `api/graph_neo4j.py`

- [ ] **Step 1: 复制并迁移现 api/graph.py 的 Cypher**

把 `api/graph.py` 中 `get_schema` / `search_graph` / `list_nodes_by_label` / `get_node` / `get_relationship` / `list_relationships` / `get_topology` / `expand_node` / `create_node` / `create_relationship` / `update_node` / `delete_node` / `delete_relationship` / `_node_to_dict` / `_rel_to_dict` / `_validate_identifier` 全部内容迁移到 `api/graph_neo4j.py` 作为 `Neo4jStore` 的实例方法。

要点：
- 删除迁移过来的 `_*` 工具函数的 `api.graph._err`，改用 `logger.warning` + 抛 `RuntimeError`
- 把所有 Cypher 中的 `$depth` 替换为字符串拼接（参考 `_build_topology_cypher`）
- `_node_to_dict` / `_rel_to_dict` 改名为 `_node_to_dict` / `_rel_to_dict` 但放在类内私有方法

- [ ] **Step 2: 实现 seed_sample**

```python
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
```

其中 `SAMPLE_NODES` 和 `SAMPLE_RELS` 与 `graph_mock.py` 中保持一致。

- [ ] **Step 3: 用 Cypher 字符串测试覆盖所有 Neo4j 方法**

`tests/test_graph_neo4j.py` 追加：

```python
def test_search_cypher_contains_query():
    ns = Neo4jStore.__new__(Neo4jStore)  # 不连 DB，只用类方法
    cypher = ns._build_search_cypher("nginx", label=None, limit=10)
    assert "$query" in cypher
    assert "toString(n[k])" in cypher


def test_search_cypher_with_label():
    ns = Neo4jStore.__new__(Neo4jStore)
    cypher = ns._build_search_cypher("nginx", label="Host", limit=10)
    assert "$label IN labels(n)" in cypher
```

并在 `Neo4jStore` 上加 `_build_search_cypher(query, label, limit) -> str` 静态方法。

- [ ] **Step 4: 跑全部 Neo4j 测试**

Run: `pytest tests/test_graph_neo4j.py -v`
Expected: 8 passed

- [ ] **Step 5: ⚠️ 不 commit — 等用户确认**

---

## Task 5: api/graph.py 瘦壳化 + 路由分发

**Files:**
- Modify: `api/graph.py`
- Test: `tests/test_graph_api.py`（更新断言）

- [ ] **Step 1: 写瘦壳的测试**

`tests/test_graph_api.py` 顶部加：

```python
import pytest
from api.graph import get_store, handle_graph_get, handle_graph_post, handle_graph_delete


def test_get_store_returns_instance():
    s = get_store()
    assert s is not None
    assert hasattr(s, "health")


def test_handle_graph_get_health():
    status, payload = handle_graph_get("GET", "/graph/health", {})
    assert status == 200
    assert payload["ok"] is True
    assert "backend" in payload["data"]


def test_handle_graph_get_schema():
    status, payload = handle_graph_get("GET", "/graph/schema", {})
    assert status == 200
    assert "node_labels" in payload["data"]
    assert "stats" in payload["data"]


def test_handle_graph_get_search_keeps_dict_format():
    """关键：search 返回必须是 {ok, data:{results,query,count}}。"""
    status, payload = handle_graph_get(
        "GET", "/graph/search", {"q": "anything"}
    )
    assert status == 200
    assert "results" in payload["data"]
    assert "query" in payload["data"]
    assert "count" in payload["data"]


def test_handle_graph_post_seed():
    status, payload = handle_graph_post("POST", "/graph/seed", {})
    assert status == 200
    assert "nodes_added" in payload["data"]
    assert "relationships_added" in payload["data"]
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `pytest tests/test_graph_api.py -v`
Expected: 大量失败（旧的 graph.py 没有这些方法）

- [ ] **Step 3: 重写 api/graph.py**

`api/graph.py`：

```python
"""图库路由层（瘦壳）。所有业务逻辑在 graph_store / graph_neo4j / graph_mock。"""
from __future__ import annotations
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

_store: Any = None
_store_tried = False


def _wrap(payload: Any) -> dict:
    """统一包装层：{ok, data}。旧 handler 返回 dict 时也兼容。"""
    if isinstance(payload, dict) and ("ok" in payload or "error" in payload):
        return payload
    return {"ok": True, "data": payload}


def _err(msg: str, status: int = 400) -> tuple[int, dict]:
    return status, {"ok": False, "error": msg}


def get_store():
    """单例懒加载。优先 Neo4j，失败降级 Mock。"""
    global _store, _store_tried
    if _store is not None:
        return _store
    if _store_tried:
        return _store  # 已尝试过且失败，保持 None
    _store_tried = True
    # 优先尝试 Neo4j
    try:
        from api.graph_neo4j import Neo4jStore
        s = Neo4jStore()
        h = s.health()
        if h["ok"]:
            logger.info("Graph store: Neo4j (%s)", h.get("detail"))
            _store = s
            return _store
        else:
            logger.warning("Neo4j not usable (%s), falling back to Mock", h.get("detail"))
    except Exception as e:
        logger.warning("Neo4j import failed (%s), falling back to Mock", e)
    # 降级 Mock
    from api.graph_mock import MockStore
    db_path = os.environ.get("GRAPH_MOCK_DB", "data/graph.sqlite")
    _store = MockStore(db_path=db_path)
    h = _store.health()
    logger.warning("Graph store: MOCK (%s) — set NEO4J_PASSWORD for Neo4j", h["detail"])
    return _store


# ---- HTTP handlers ----

def handle_graph_get(method: str, parsed_path: str, query_params: dict) -> tuple[int, dict]:
    path = parsed_path
    store = get_store()
    try:
        if path == "/graph/health":
            return 200, _wrap(store.health())
        if path == "/graph/schema":
            return 200, _wrap(store.schema())
        if path == "/graph/search":
            q = query_params.get("q", "").strip()
            if not q:
                return *_err("q parameter required", 400),  # noqa
            label = query_params.get("label") or None
            limit = int(query_params.get("limit", 50))
            return 200, _wrap(store.search(q, label, limit))
        if path == "/graph/nodes":
            label = query_params.get("label", "").strip()
            if not label:
                return *_err("label parameter required (use /graph/schema to discover)", 400),
            limit = int(query_params.get("limit", 200))
            return 200, _wrap(store.list_nodes(label, limit))
        if path.startswith("/graph/node/"):
            eid = path[len("/graph/node/"):]
            n = store.get_node(eid)
            if not n:
                return *_err("node not found", 404),
            return 200, _wrap(n)
        if path.startswith("/graph/relationship/"):
            eid = path[len("/graph/relationship/"):]
            r = store.get_relationship(eid)
            if not r:
                return *_err("relationship not found", 404),
            return 200, _wrap(r)
        if path.startswith("/graph/relationships/"):
            eid = path[len("/graph/relationships/"):]
            direction = query_params.get("direction", "both")
            return 200, _wrap({"results": store.list_relationships(eid, direction)})
        if path.startswith("/graph/topology/"):
            eid = path[len("/graph/topology/"):]
            depth = int(query_params.get("depth", 1))
            return 200, _wrap(store.topology(eid, depth))
        return *_err(f"unknown GET path: {path}", 404),
    except (ValueError, RuntimeError) as e:
        return _err(str(e), 400 if isinstance(e, ValueError) else 503)


def handle_graph_post(method: str, parsed_path: str, body: dict) -> tuple[int, dict]:
    path = parsed_path
    store = get_store()
    try:
        if path == "/graph/nodes":
            labels = body.get("labels") or []
            properties = body.get("properties") or {}
            return 200, _wrap(store.create_node(labels, properties))
        if path == "/graph/relationships":
            return 200, _wrap(store.create_relationship(
                body.get("type", ""),
                body.get("start_node_id", ""),
                body.get("end_node_id", ""),
                body.get("properties"),
            ))
        if path == "/graph/seed":
            return 200, _wrap(store.seed_sample())
        return *_err(f"unknown POST path: {path}", 404),
    except (ValueError, RuntimeError) as e:
        return _err(str(e), 400 if isinstance(e, ValueError) else 503)


def handle_graph_delete(method: str, parsed_path: str) -> tuple[int, dict]:
    path = parsed_path
    store = get_store()
    try:
        if path.startswith("/graph/node/"):
            eid = path[len("/graph/node/"):]
            return 200, _wrap(store.delete_node(eid))
        if path.startswith("/graph/relationship/"):
            eid = path[len("/graph/relationship/"):]
            return 200, _wrap(store.delete_relationship(eid))
        return *_err(f"unknown DELETE path: {path}", 404),
    except (ValueError, RuntimeError) as e:
        return _err(str(e), 400 if isinstance(e, ValueError) else 503)
```

注意：上面 `return *_err(...),` 是 tuple splat 写法，等价于 `return (400, {"ok": False, ...})`。如果 Python 解释器不认（3.11 应支持），改为：

```python
status, payload = _err(...)
return status, payload
```

- [ ] **Step 4: 更新现有 tests/test_graph_api.py**

旧 `tests/test_graph_api.py` 中所有断言需要：
- 把 `payload["..."]` 直接访问改成 `payload["data"]["..."]`
- 加 `assert payload["ok"] is True`

具体修改清单（读取现有测试，按上述规则批量调整）。

- [ ] **Step 5: 跑全部图库相关测试**

Run: `pytest tests/test_graph_api.py tests/test_graph_mock.py tests/test_graph_neo4j.py tests/test_graph_store.py -v`
Expected: 全部通过

- [ ] **Step 6: ⚠️ 不 commit — 等用户确认**

---

## Task 6: 删除旧 graph.js，加载新模块

**Files:**
- Delete: `static/graph.js`
- Modify: `static/index.html`

- [ ] **Step 1: 从 index.html 删除旧脚本引用**

`static/index.html:1897` 行附近：

```html
<script src="static/graph.js?v=__WEBUI_VERSION__" defer></script>
```

删除该行。

- [ ] **Step 2: ⚠️ 暂不动 index.html script 标签，先在 §Task 7 重写 panel DOM 时一起加**

（避免重复 edit index.html）

- [ ] **Step 3: ⚠️ 不 commit — 等用户确认**

---

## Task 7: 重写 panelGraph DOM 结构

**Files:**
- Modify: `static/index.html`

- [ ] **Step 1: 替换 panelGraph 整个 div**

`static/index.html:327-359` 区域，把现有：

```html
<!-- Graph panel -->
<div class="panel-view" id="panelGraph" hidden>
  ...
</div>
```

整段替换为：

```html
<!-- Graph panel -->
<div class="panel-view" id="panelGraph" hidden>
  <div class="panel-head">
    <span data-i18n="tab_graph">Graph</span>
    <div class="panel-head-actions">
      <span class="graph-backend-badge" id="graphBackendBadge" hidden></span>
      <button class="panel-head-btn has-tooltip" id="graphSeedBtn" data-tooltip="Load sample data" aria-label="Load sample data" type="button">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
      </button>
      <button class="panel-head-btn has-tooltip" id="graphRefreshBtn" data-tooltip="Refresh" aria-label="Refresh" type="button">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
      </button>
      <button class="panel-head-btn has-tooltip" id="graphCloseBtn" data-tooltip="Close" aria-label="Close" type="button">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
      </button>
    </div>
  </div>

  <div class="graph-tabs" role="tablist">
    <button class="graph-tab active" data-view="graph" role="tab" aria-selected="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="6" cy="6" r="3"/><circle cx="18" cy="6" r="3"/><circle cx="12" cy="18" r="3"/><line x1="8.5" y1="7.5" x2="11" y2="15"/><line x1="15.5" y1="7.5" x2="13" y2="15"/><line x1="9" y1="6" x2="15" y2="6"/></svg>
      <span data-i18n="graph_view_graph">Graph</span>
    </button>
    <button class="graph-tab" data-view="table" role="tab" aria-selected="false">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="3" y1="15" x2="21" y2="15"/><line x1="9" y1="3" x2="9" y2="21"/><line x1="15" y1="3" x2="15" y2="21"/></svg>
      <span data-i18n="graph_view_table">Table</span>
    </button>
    <button class="graph-tab" data-view="json" role="tab" aria-selected="false">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>
      <span data-i18n="graph_view_json">JSON</span>
    </button>
    <div class="graph-search-wrap">
      <svg class="sidebar-search-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
      <input id="graphSearchInput" placeholder="Search nodes..." data-i18n-placeholder="graph_search_placeholder" autocomplete="off">
      <div class="graph-search-dropdown" id="graphSearchDropdown" hidden></div>
    </div>
  </div>

  <div class="graph-body">
    <!-- Graph view (Cytoscape) -->
    <div class="graph-view graph-view-graph active" data-view="graph">
      <div class="graph-canvas" id="graphCanvas"></div>
      <div class="graph-empty-state" id="graphEmptyState" hidden>
        <div class="graph-empty-icon">📊</div>
        <h3 data-i18n="graph_empty_title">Graph is empty</h3>
        <p data-i18n="graph_empty_desc">Backend is Mock mode with no data. Load a sample operations graph (Host / Service / Incident / Runbook) to get started.</p>
        <div class="graph-empty-actions">
          <button class="btn btn-primary" id="graphEmptySeedBtn" data-i18n="graph_load_sample">Load sample data</button>
          <button class="btn btn-secondary" id="graphEmptyCreateBtn" data-i18n="graph_create_first">Create first node</button>
        </div>
      </div>
      <div class="graph-floating-toolbar">
        <button class="graph-fab" data-action="fit" data-tooltip="Fit">⤢</button>
        <button class="graph-fab" data-action="zoom-in" data-tooltip="Zoom in">+</button>
        <button class="graph-fab" data-action="zoom-out" data-tooltip="Zoom out">−</button>
        <button class="graph-fab" data-action="layout" data-tooltip="Layout: COSE">⊕</button>
      </div>
    </div>

    <!-- Table view -->
    <div class="graph-view graph-view-table" data-view="table" hidden>
      <div class="graph-subtabs">
        <button class="graph-subtab active" data-table="nodes" data-i18n="graph_table_nodes">Nodes</button>
        <button class="graph-subtab" data-table="relationships" data-i18n="graph_table_rels">Relationships</button>
      </div>
      <div class="graph-table-wrap">
        <table class="graph-table" id="graphTableNodes">
          <thead><tr><th>ID</th><th>Labels</th><th>Name</th><th>Actions</th></tr></thead>
          <tbody></tbody>
        </table>
        <table class="graph-table" id="graphTableRels" hidden>
          <thead><tr><th>ID</th><th>Type</th><th>Start</th><th>End</th><th>Actions</th></tr></thead>
          <tbody></tbody>
        </table>
      </div>
    </div>

    <!-- JSON view -->
    <div class="graph-view graph-view-json" data-view="json" hidden>
      <div class="graph-json-tree" id="graphJsonTree"></div>
      <div class="graph-json-detail" id="graphJsonDetail">
        <div class="graph-json-empty">Select a node or relationship</div>
      </div>
    </div>
  </div>

  <div class="graph-status">
    <span class="graph-status-counts">
      <span data-i18n="graph_status_nodes">Nodes</span>: <strong id="graphStatusNodes">0</strong>
      <span data-i18n="graph_status_rels">Relationships</span>: <strong id="graphStatusEdges">0</strong>
    </span>
    <span class="graph-status-msg" id="graphStatusMsg"></span>
  </div>

  <!-- CRUD modal mount point -->
  <div class="graph-crud-mount" id="graphCrudMount"></div>
</div>
```

- [ ] **Step 2: 加新模块 script 标签（紧跟 cytoscape vendor）**

`static/index.html` 在 `static/vendor/cytoscape.min.js` 之后、之前 `static/graph.js` 位置替换为：

```html
<script src="static/vendor/cytoscape.min.js?v=__WEBUI_VERSION__" defer></script>
<script src="static/graph_view_graph.js?v=__WEBUI_VERSION__" defer></script>
<script src="static/graph_view_table.js?v=__WEBUI_VERSION__" defer></script>
<script src="static/graph_view_json.js?v=__WEBUI_VERSION__" defer></script>
<script src="static/graph_crud.js?v=__WEBUI_VERSION__" defer></script>
<script src="static/graph_main.js?v=__WEBUI_VERSION__" defer></script>
```

- [ ] **Step 3: 删除 static/graph.js**

```bash
rm static/graph.js
```

- [ ] **Step 4: ⚠️ 不 commit — 等用户确认**

---

## Task 8: 写 graph_main.js（主控）

**Files:**
- Create: `static/graph_main.js`
- Test: `tests/test_graph_main.spec.js`

- [ ] **Step 1: 写 vitest 测试**

`tests/test_graph_main.spec.js`：

```javascript
import { describe, it, expect, beforeEach, vi } from "vitest";

describe("graph_main state management", () => {
  it("init resolves panel elements", async () => {
    document.body.innerHTML = `
      <div id="panelGraph" class="active">
        <button class="graph-tab active" data-view="graph">Graph</button>
        <button class="graph-tab" data-view="table">Table</button>
        <button class="graph-tab" data-view="json">JSON</button>
        <div class="graph-view graph-view-graph active" data-view="graph"></div>
        <div class="graph-view graph-view-table" data-view="table" hidden></div>
        <div class="graph-view graph-view-json" data-view="json" hidden></div>
        <span id="graphBackendBadge"></span>
        <span id="graphStatusNodes">0</span>
        <span id="graphStatusEdges">0</span>
        <span id="graphStatusMsg"></span>
      </div>
    `;
    // 调用 graph_main 的 init
    const mod = await import("../static/graph_main.js");
    // 触发 DOMContentLoaded
    document.dispatchEvent(new Event("DOMContentLoaded"));
    expect(mod.state).toBeDefined();
    expect(mod.state.currentView).toBe("graph");
  });

  it("switchView toggles tab active state", async () => {
    const mod = await import("../static/graph_main.js");
    mod.switchView("table");
    expect(mod.state.currentView).toBe("table");
    expect(document.querySelector('[data-view="table"].graph-tab').classList.contains("active")).toBe(true);
  });
});
```

- [ ] **Step 2: 跑测试，确认失败**

Run: `npx vitest run tests/test_graph_main.spec.js`
Expected: 失败（graph_main.js 不存在）

- [ ] **Step 3: 实现 graph_main.js**

`static/graph_main.js`：

```javascript
/* ==========================================
   GRAPH PANEL — Main controller
   ========================================== */
(function() {
  "use strict";

  const state = {
    backend: "unknown",  // "neo4j" | "mock"
    healthOk: false,
    schema: null,
    currentView: "graph",  // "graph" | "table" | "json"
    selectedNodeId: null,
    selectedRelId: null,
  };

  let panel, tabs, views, searchInput, searchDropdown, statusNodes, statusEdges, statusMsg, backendBadge;

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    const json = await res.json();
    if (!json.ok) throw new Error(json.error || "API error");
    return json.data;
  }

  function $(id) { return document.getElementById(id); }
  function $$(sel, root = document) { return Array.from(root.querySelectorAll(sel)); }

  async function init() {
    panel = $("panelGraph");
    if (!panel) return;

    tabs = $$(".graph-tab", panel);
    views = $$(".graph-view", panel);
    searchInput = $("graphSearchInput");
    searchDropdown = $("graphSearchDropdown");
    statusNodes = $("graphStatusNodes");
    statusEdges = $("graphStatusEdges");
    statusMsg = $("graphStatusMsg");
    backendBadge = $("graphBackendBadge");

    tabs.forEach(tab => tab.addEventListener("click", () => switchView(tab.dataset.view)));
    if (searchInput) {
      let timer = null;
      searchInput.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(doSearch, 250);
      });
    }

    // 加载示例 / 刷新 / 关闭 按钮
    const seedBtn = $("graphSeedBtn");
    if (seedBtn) seedBtn.addEventListener("click", loadSample);
    const refreshBtn = $("graphRefreshBtn");
    if (refreshBtn) refreshBtn.addEventListener("click", loadSchema);
    const closeBtn = $("graphCloseBtn");
    if (closeBtn) closeBtn.addEventListener("click", () => switchPanel && switchPanel("graph"));
    const emptySeedBtn = $("graphEmptySeedBtn");
    if (emptySeedBtn) emptySeedBtn.addEventListener("click", loadSample);
    const emptyCreateBtn = $("graphEmptyCreateBtn");
    if (emptyCreateBtn) emptyCreateBtn.addEventListener("click", () => {
      if (window.GraphCRUD) window.GraphCRUD.openCreateNode();
    });

    // 监听面板显示
    panel.addEventListener("panel:show", onPanelShow);
  }

  async function onPanelShow() {
    if (!panel.classList.contains("active")) return;
    await checkHealth();
    await loadSchema();
  }

  async function checkHealth() {
    try {
      const h = await api("/api/graph/health");
      state.backend = h.backend;
      state.healthOk = h.ok;
      renderBackendBadge();
    } catch (e) {
      setStatus("Health check failed: " + e.message, "error");
    }
  }

  function renderBackendBadge() {
    if (!backendBadge) return;
    backendBadge.hidden = false;
    backendBadge.textContent = state.backend === "neo4j" ? "✓ Neo4j" : "⚠ Mock";
    backendBadge.className = "graph-backend-badge " + (state.backend === "neo4j" ? "ok" : "warn");
  }

  async function loadSchema() {
    try {
      state.schema = await api("/api/graph/schema");
      renderSchema();
      checkEmptyState();
      notifyViews("schema");
    } catch (e) {
      setStatus("Schema load failed: " + e.message, "error");
    }
  }

  function renderSchema() {
    const s = state.schema;
    if (!s) return;
    if (statusNodes) statusNodes.textContent = s.stats?.node_count ?? 0;
    if (statusEdges) statusEdges.textContent = s.stats?.relationship_count ?? 0;
    setStatus("Ready — " + (s.node_labels?.length || 0) + " labels, " +
              (s.relationship_types?.length || 0) + " relationship types");
  }

  function checkEmptyState() {
    const emptyEl = $("graphEmptyState");
    if (!emptyEl) return;
    const isEmpty = state.backend === "mock" &&
                    state.schema?.stats?.node_count === 0;
    emptyEl.hidden = !isEmpty;
  }

  async function loadSample() {
    if (!confirm("Load sample data into the graph? This may add new nodes if not already present.")) return;
    try {
      const res = await api("/api/graph/seed", { method: "POST", body: "{}" });
      setStatus(`Loaded ${res.nodes_added} nodes, ${res.relationships_added} relationships`);
      await loadSchema();
    } catch (e) {
      setStatus("Seed failed: " + e.message, "error");
    }
  }

  async function doSearch() {
    const q = searchInput.value.trim();
    if (!q) {
      if (searchDropdown) searchDropdown.hidden = true;
      return;
    }
    try {
      const res = await api("/api/graph/search?q=" + encodeURIComponent(q) + "&limit=5");
      showSearchDropdown(res.results || []);
    } catch (e) {
      // 静默：搜索是渐进体验
    }
  }

  function showSearchDropdown(nodes) {
    if (!searchDropdown) return;
    if (!nodes || nodes.length === 0) {
      searchDropdown.hidden = true;
      return;
    }
    searchDropdown.innerHTML = nodes.map(n => {
      const label = (n.labels && n.labels[0]) || "?";
      const name = (n.properties && (n.properties.name || n.properties.title)) || n.id;
      return `<div class="graph-search-result" data-id="${escAttr(n.id)}">
        <span class="graph-node-label">${escHtml(label)}</span>
        <span class="graph-node-name">${escHtml(String(name))}</span>
      </div>`;
    }).join("");
    searchDropdown.querySelectorAll(".graph-search-result").forEach(el => {
      el.addEventListener("click", () => {
        const id = el.dataset.id;
        searchInput.value = "";
        searchDropdown.hidden = true;
        if (window.GraphViewGraph) window.GraphViewGraph.expandNode(id);
      });
    });
    searchDropdown.hidden = false;
  }

  function setStatus(msg, kind = "info") {
    if (!statusMsg) return;
    statusMsg.textContent = msg;
    statusMsg.dataset.kind = kind;
  }

  function switchView(view) {
    if (!["graph", "table", "json"].includes(view)) return;
    state.currentView = view;
    tabs.forEach(t => {
      const active = t.dataset.view === view;
      t.classList.toggle("active", active);
      t.setAttribute("aria-selected", active ? "true" : "false");
    });
    views.forEach(v => v.hidden = v.dataset.view !== view);
    // 通知视图：tab 切换时触发 resize / 重渲染
    notifyViews("view-changed", view);
  }

  function notifyViews(event, payload) {
    if (event === "view-changed" && payload === "graph" && window.GraphViewGraph) {
      window.GraphViewGraph.onShow();
    }
    if (event === "view-changed" && payload === "table" && window.GraphViewTable) {
      window.GraphViewTable.onShow(state.schema);
    }
    if (event === "view-changed" && payload === "json" && window.GraphViewJson) {
      window.GraphViewJson.onShow(state.schema);
    }
    if (event === "schema" && window.GraphViewTable) {
      window.GraphViewTable.onShow(state.schema);
    }
  }

  function escHtml(s) {
    return String(s).replace(/[&<>"']/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function escAttr(s) { return escHtml(s); }

  document.addEventListener("DOMContentLoaded", init);

  window.GraphMain = { state, switchView, getState: () => state, setStatus };
})();
```

- [ ] **Step 4: 跑测试，确认通过**

Run: `npx vitest run tests/test_graph_main.spec.js`
Expected: 2 passed

- [ ] **Step 5: ⚠️ 不 commit — 等用户确认**

---

## Task 9: 写 graph_view_graph.js（Cytoscape 视图）

**Files:**
- Create: `static/graph_view_graph.js`

- [ ] **Step 1: 实现 Cytoscape 视图（修 API 解析 bug + tab 切换 resize）**

`static/graph_view_graph.js`：

```javascript
/* ==========================================
   GRAPH — Cytoscape view
   ========================================== */
(function() {
  "use strict";

  let cy = null;
  let canvas = null;
  let nodeMap = {};
  let relMap = {};
  const LABEL_COLORS = {
    Host: "#4A90E2", Service: "#7ED321", Incident: "#D0021B", Runbook: "#F5A623",
  };

  function $(id) { return document.getElementById(id); }

  function init() {
    canvas = $("graphCanvas");
    if (!canvas || typeof cytoscape === "undefined") return;

    cy = cytoscape({
      container: canvas,
      style: [
        { selector: "node", style: {
            label: "data(label)",
            "background-color": "data(color)",
            "border-width": 2,
            "border-color": "data(borderColor)",
            width: 40, height: 40,
            "font-size": 12, "text-valign": "bottom", color: "#555",
        }},
        { selector: "edge", style: {
            label: "data(label)",
            width: 2, "line-color": "#aaa", "target-arrow-color": "#aaa",
            "target-arrow-shape": "triangle", "curve-style": "bezier", "font-size": 10,
        }},
        { selector: "node:selected", style: { "border-width": 4, "border-color": "#FF6B35" }},
        { selector: "node.highlighted", style: { "border-width": 3, "border-color": "#FF6B35" }},
      ],
      layout: { name: "preset" },
      wheelSensitivity: 0.3,
    });

    cy.on("tap", "node", e => onSelectNode(e.target.id()));
    cy.on("dbltap", "node", e => expandNode(e.target.id()));
    cy.on("tap", e => {
      if (e.target === cy) clearSelection();
    });

    // 浮动工具条
    document.querySelectorAll(".graph-fab").forEach(btn => {
      btn.addEventListener("click", () => {
        const a = btn.dataset.action;
        if (a === "fit") cy.fit(null, 50);
        else if (a === "zoom-in") cy.zoom({ level: cy.zoom() * 1.2, renderedPosition: { x: cy.width()/2, y: cy.height()/2 }});
        else if (a === "zoom-out") cy.zoom({ level: cy.zoom() / 1.2, renderedPosition: { x: cy.width()/2, y: cy.height()/2 }});
        else if (a === "layout") cy.layout({ name: "cose", animate: true, padding: 50 }).run();
      });
    });
  }

  function onShow() {
    if (cy) {
      // 关键：tab 切换后必须 resize，否则 Cytoscape 不渲染
      setTimeout(() => { if (cy) cy.resize(); }, 50);
    }
  }

  async function expandNode(elementId, depth = 1) {
    try {
      const res = await fetch("/api/graph/topology/" + encodeURIComponent(elementId) + "?depth=" + depth);
      const json = await res.json();
      if (!json.ok) throw new Error(json.error);
      renderTopology(json.data, depth);
      if (window.GraphMain) window.GraphMain.setStatus(
        `Loaded ${json.data.nodes.length} nodes, ${json.data.relationships.length} relationships`);
    } catch (e) {
      if (window.GraphMain) window.GraphMain.setStatus("Expand failed: " + e.message, "error");
    }
  }

  function renderTopology(topo) {
    if (!cy) return;
    topo.nodes.forEach(n => {
      const id = n.id;
      if (!nodeMap[id]) {
        const label = (n.labels && n.labels[0]) || "Node";
        const name = (n.properties && (n.properties.name || n.properties.title)) || id;
        nodeMap[id] = cy.add({
          group: "nodes",
          data: {
            id,
            label: name,
            color: LABEL_COLORS[label] || "#999",
            borderColor: LABEL_COLORS[label] || "#999",
          },
        });
      }
    });
    topo.relationships.forEach(r => {
      const id = r.id;
      if (!relMap[id] && nodeMap[r.start_node_id] && nodeMap[r.end_node_id]) {
        relMap[id] = cy.add({
          group: "edges",
          data: { id, source: r.start_node_id, target: r.end_node_id, label: r.type },
        });
      }
    });
    cy.layout({ name: "cose", animate: true, padding: 50 }).run();
  }

  function onSelectNode(id) {
    if (window.GraphMain) {
      window.GraphMain.state.selectedNodeId = id;
    }
    if (window.GraphCRUD) window.GraphCRUD.showNodeActions(id);
  }

  function clearSelection() {
    if (cy) cy.elements().unselect();
    if (window.GraphMain) {
      window.GraphMain.state.selectedNodeId = null;
      window.GraphMain.state.selectedRelId = null;
    }
  }

  document.addEventListener("DOMContentLoaded", init);
  window.GraphViewGraph = { expandNode, onShow };
})();
```

- [ ] **Step 2: ⚠️ 不 commit — 等用户确认**

---

## Task 10: 写 graph_view_table.js

**Files:**
- Create: `static/graph_view_table.js`

- [ ] **Step 1: 实现表格视图**

`static/graph_view_table.js`：

```javascript
/* ==========================================
   GRAPH — Table view
   ========================================== */
(function() {
  "use strict";

  let currentSubtab = "nodes";
  let allNodes = [];
  let allRels = [];

  async function onShow(schema) {
    if (!schema) return;
    await Promise.all([loadNodes(schema), loadRels()]);
  }

  async function loadNodes(schema) {
    // Mock 模式下没有 "label required" 限制；Neo4j 模式按 label 循环
    try {
      let collected = [];
      if (schema && schema.node_labels && schema.node_labels.length > 0) {
        for (const label of schema.node_labels) {
          const res = await fetch("/api/graph/nodes?label=" + encodeURIComponent(label) + "&limit=200");
          const json = await res.json();
          if (json.ok && json.data) collected = collected.concat(json.data.results || []);
        }
      }
      allNodes = collected;
      renderNodesTable();
    } catch (e) {
      console.error("loadNodes failed", e);
    }
  }

  async function loadRels() {
    try {
      const res = await fetch("/api/graph/schema");
      const json = await res.json();
      // relationships 列表需要 schema 的 relationship_types，按 type 全列
      // 此处简化：从每个节点拉一次 list_relationships 会爆 N+1，改为全部遍历
      // 实际：调用 /api/graph/schema 拿到 relationship_types 后批量 fetch
      // 简化为：先展示 schema 数据
      const r = await fetch("/api/graph/search?q=&limit=1");  // 触发不到；改用 seed sample 后才有数据
      allRels = [];
      renderRelsTable();
    } catch (e) { /* silent */ }
  }

  function renderNodesTable() {
    const tbody = document.querySelector("#graphTableNodes tbody");
    if (!tbody) return;
    tbody.innerHTML = allNodes.map(n => `
      <tr data-id="${escAttr(n.id)}">
        <td class="graph-td-id">${escHtml(n.id.slice(0, 12))}…</td>
        <td>${escHtml((n.labels || []).join(", "))}</td>
        <td>${escHtml((n.properties && (n.properties.name || n.properties.title)) || "")}</td>
        <td class="graph-td-actions">
          <button class="graph-row-btn" data-action="locate">Locate</button>
          <button class="graph-row-btn" data-action="edit">Edit</button>
          <button class="graph-row-btn danger" data-action="delete">Delete</button>
        </td>
      </tr>
    `).join("");
    tbody.querySelectorAll("button").forEach(btn => {
      btn.addEventListener("click", e => {
        const tr = e.target.closest("tr");
        const id = tr.dataset.id;
        const a = btn.dataset.action;
        if (a === "locate") switchToGraph(id);
        else if (a === "edit") window.GraphCRUD && window.GraphCRUD.openEditNode(id);
        else if (a === "delete") window.GraphCRUD && window.GraphCRUD.deleteNode(id);
      });
    });
  }

  function renderRelsTable() {
    const tbody = document.querySelector("#graphTableRels tbody");
    if (!tbody) return;
    tbody.innerHTML = allRels.map(r => `
      <tr data-id="${escAttr(r.id)}">
        <td class="graph-td-id">${escHtml(r.id.slice(0, 12))}…</td>
        <td>${escHtml(r.type)}</td>
        <td>${escHtml((r.start_node_id || "").slice(0, 12))}…</td>
        <td>${escHtml((r.end_node_id || "").slice(0, 12))}…</td>
        <td class="graph-td-actions">
          <button class="graph-row-btn danger" data-action="delete">Delete</button>
        </td>
      </tr>
    `).join("");
  }

  function switchToGraph(nodeId) {
    if (window.GraphMain) window.GraphMain.switchView("graph");
    if (window.GraphViewGraph) window.GraphViewGraph.expandNode(nodeId);
  }

  // 监听 subtab
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".graph-subtab").forEach(btn => {
      btn.addEventListener("click", () => {
        currentSubtab = btn.dataset.table;
        document.querySelectorAll(".graph-subtab").forEach(b => b.classList.toggle("active", b === btn));
        document.getElementById("graphTableNodes").hidden = currentSubtab !== "nodes";
        document.getElementById("graphTableRels").hidden = currentSubtab !== "relationships";
      });
    });
  });

  function escHtml(s) { return String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
  function escAttr(s) { return escHtml(s); }

  window.GraphViewTable = { onShow };
})();
```

> **说明**：上面的 `loadRels` 用了 placeholder 实现——因为现有 API 没有"列全部关系"的端点。完整实现需要新增 `GET /api/graph/relationships` 返回所有关系（可在 Task 11 加），或在 graph_view_graph.js 已有数据时复用。**实现阶段决策**：先实现节点表，关系表留 TODO 等补端点。

- [ ] **Step 2: ⚠️ 不 commit — 等用户确认**

---

## Task 11: 加 GET /api/graph/relationships 端点

**Files:**
- Modify: `api/graph.py`
- Modify: `api/graph_store.py`
- Modify: `api/graph_mock.py`
- Modify: `api/graph_neo4j.py`

- [ ] **Step 1: 给 Protocol 加 list_all_relationships**

`api/graph_store.py` 加方法签名：

```python
def list_all_relationships(self, limit: int = 500) -> list[dict]:
    """列出所有关系（不分页节点）。用于 Table 视图。"""
    ...
```

- [ ] **Step 2: MockStore 实现**

`api/graph_mock.py` 加：

```python
def list_all_relationships(self, limit: int = 500) -> list[dict]:
    rows = self.conn.execute(
        "SELECT id, type, start_id, end_id, properties FROM relationships LIMIT ?",
        (limit,)
    ).fetchall()
    return [{"id": r["id"], "type": r["type"],
             "start_node_id": r["start_id"], "end_node_id": r["end_id"],
             "properties": json.loads(r["properties"])} for r in rows]
```

- [ ] **Step 3: Neo4jStore 实现**

`api/graph_neo4j.py` 加：

```python
def list_all_relationships(self, limit: int = 500) -> list[dict]:
    driver = self._connect()
    with driver.session() as s:
        res = s.run("MATCH ()-[r]->() RETURN r LIMIT $limit", limit=limit)
        return [{"id": r["r"].element_id, "type": r["r"].type,
                 "start_node_id": r["r"].start_node.element_id,
                 "end_node_id": r["r"].end_node.element_id,
                 "properties": dict(r["r"])} for r in res]
```

- [ ] **Step 4: handle_graph_get 加分支**

`api/graph.py`：

```python
if path == "/graph/relationships":
    limit = int(query_params.get("limit", 500))
    return 200, _wrap({"results": store.list_all_relationships(limit)})
```

- [ ] **Step 5: 加测试**

`tests/test_graph_mock.py` 追加：

```python
def test_list_all_relationships(store):
    a = store.create_node(["Host"], {"name": "a"})
    b = store.create_node(["Host"], {"name": "b"})
    store.create_relationship("DEPENDS_ON", a["id"], b["id"])
    rels = store.list_all_relationships()
    assert len(rels) == 1
    assert rels[0]["type"] == "DEPENDS_ON"
```

- [ ] **Step 6: 跑测试**

Run: `pytest tests/test_graph_mock.py -v`
Expected: 12 passed

- [ ] **Step 7: 更新 graph_view_table.js 的 loadRels**

把 placeholder 替换为：

```javascript
async function loadRels() {
  try {
    const res = await fetch("/api/graph/relationships?limit=500");
    const json = await res.json();
    allRels = (json.ok && json.data) ? (json.data.results || []) : [];
    renderRelsTable();
  } catch (e) { /* silent */ }
}
```

- [ ] **Step 8: ⚠️ 不 commit — 等用户确认**

---

## Task 12: 写 graph_view_json.js

**Files:**
- Create: `static/graph_view_json.js`

- [ ] **Step 1: 实现 JSON 视图**

`static/graph_view_json.js`：

```javascript
/* ==========================================
   GRAPH — JSON view
   ========================================== */
(function() {
  "use strict";

  let selected = null;
  let selectedKind = null;  // "node" | "rel"

  async function onShow(schema) {
    if (!schema) return;
    await renderTree(schema);
  }

  async function renderTree(schema) {
    const treeEl = document.getElementById("graphJsonTree");
    if (!treeEl) return;
    let html = '<div class="graph-json-section"><h4>Nodes</h4><ul>';
    for (const label of schema.node_labels || []) {
      html += `<li class="graph-json-label" data-label="${escAttr(label)}">${escHtml(label)}</li>`;
    }
    html += '</ul></div><div class="graph-json-section"><h4>Relationships</h4><ul>';
    for (const t of schema.relationship_types || []) {
      html += `<li class="graph-json-type">${escHtml(t)}</li>`;
    }
    html += "</ul></div>";
    treeEl.innerHTML = html;

    // 点击 label → 拉该 label 下所有节点
    treeEl.querySelectorAll(".graph-json-label").forEach(el => {
      el.addEventListener("click", async () => {
        const res = await fetch("/api/graph/nodes?label=" + encodeURIComponent(el.dataset.label));
        const json = await res.json();
        if (json.ok) showList(el.dataset.label, json.data.results || []);
      });
    });
  }

  function showList(label, nodes) {
    const treeEl = document.getElementById("graphJsonTree");
    const detailEl = document.getElementById("graphJsonDetail");
    if (!treeEl || !detailEl) return;
    treeEl.innerHTML = `<button class="btn-link" id="graphJsonBack">← Back</button>
      <h4>${escHtml(label)} (${nodes.length})</h4>
      <ul class="graph-json-list">${nodes.map(n => `
        <li data-id="${escAttr(n.id)}" class="graph-json-item">${escHtml((n.properties && n.properties.name) || n.id)}</li>
      `).join("")}</ul>`;
    treeEl.querySelectorAll(".graph-json-item").forEach(el => {
      el.addEventListener("click", async () => {
        const res = await fetch("/api/graph/node/" + encodeURIComponent(el.dataset.id));
        const json = await res.json();
        if (json.ok) showDetail("node", json.data);
      });
    });
    const back = document.getElementById("graphJsonBack");
    if (back) back.addEventListener("click", () => onShow(window.GraphMain.state.schema));
  }

  function showDetail(kind, data) {
    const detailEl = document.getElementById("graphJsonDetail");
    if (!detailEl) return;
    selected = data;
    selectedKind = kind;
    detailEl.innerHTML = `
      <div class="graph-json-toolbar">
        <button class="btn btn-secondary" id="graphJsonCopy">Copy</button>
        <button class="btn btn-secondary" id="graphJsonDownload">Download</button>
      </div>
      <pre class="graph-json-pre">${escHtml(JSON.stringify(data, null, 2))}</pre>
    `;
    document.getElementById("graphJsonCopy").addEventListener("click", () => {
      navigator.clipboard.writeText(JSON.stringify(data, null, 2));
      if (window.GraphMain) window.GraphMain.setStatus("Copied to clipboard");
    });
    document.getElementById("graphJsonDownload").addEventListener("click", () => {
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = (data.properties && data.properties.name) || data.id;
      a.click();
      URL.revokeObjectURL(url);
    });
  }

  function escHtml(s) { return String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
  function escAttr(s) { return escHtml(s); }

  window.GraphViewJson = { onShow };
})();
```

- [ ] **Step 2: ⚠️ 不 commit — 等用户确认**

---

## Task 13: 写 graph_crud.js（CRUD 模态）

**Files:**
- Create: `static/graph_crud.js`

- [ ] **Step 1: 实现 CRUD 模态**

`static/graph_crud.js`：

```javascript
/* ==========================================
   GRAPH — CRUD modal
   ========================================== */
(function() {
  "use strict";

  let mount = null;

  document.addEventListener("DOMContentLoaded", () => {
    mount = document.getElementById("graphCrudMount");
  });

  function openModal(title, body) {
    if (!mount) mount = document.getElementById("graphCrudMount");
    if (!mount) return;
    mount.innerHTML = `
      <div class="graph-crud-backdrop"></div>
      <div class="graph-crud-modal">
        <div class="graph-crud-head">
          <h3>${title}</h3>
          <button class="panel-head-btn" id="graphCrudClose">✕</button>
        </div>
        <div class="graph-crud-body">${body}</div>
      </div>`;
    mount.querySelector(".graph-crud-backdrop").addEventListener("click", close);
    mount.querySelector("#graphCrudClose").addEventListener("click", close);
  }

  function close() { if (mount) mount.innerHTML = ""; }

  async function openCreateNode() {
    const schema = window.GraphMain ? window.GraphMain.state.schema : null;
    const labels = (schema && schema.node_labels) || ["Host", "Service", "Incident", "Runbook"];
    const body = `
      <label>Labels
        <div class="graph-crud-labels">${labels.map(l =>
          `<label class="graph-crud-chip"><input type="checkbox" value="${escAttr(l)}">${escHtml(l)}</label>`
        ).join("")}</div>
      </label>
      <label>Properties (key=value, one per line)
        <textarea id="graphCrudProps" rows="5" placeholder="name=web-01&#10;ip=10.0.0.1"></textarea>
      </label>
      <div class="graph-crud-actions">
        <button class="btn btn-secondary" id="graphCrudCancel">Cancel</button>
        <button class="btn btn-primary" id="graphCrudSave">Create</button>
      </div>`;
    openModal("Create Node", body);
    document.getElementById("graphCrudCancel").addEventListener("click", close);
    document.getElementById("graphCrudSave").addEventListener("click", saveCreate);
  }

  async function saveCreate() {
    const labels = Array.from(document.querySelectorAll(".graph-crud-labels input:checked")).map(i => i.value);
    const propsText = document.getElementById("graphCrudProps").value.trim();
    const properties = {};
    propsText.split(/\n+/).forEach(line => {
      const [k, ...rest] = line.split("=");
      if (k && rest.length) properties[k.trim()] = rest.join("=").trim();
    });
    if (labels.length === 0) { alert("Select at least one label"); return; }
    try {
      const res = await fetch("/api/graph/nodes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ labels, properties }),
      });
      const json = await res.json();
      if (!json.ok) throw new Error(json.error);
      close();
      // 触发 schema 重载，让其他视图看到新数据
      const panel = document.getElementById("panelGraph");
      if (panel) panel.dispatchEvent(new CustomEvent("panel:show"));
    } catch (e) {
      alert("Create failed: " + e.message);
    }
  }

  async function openEditNode(nodeId) {
    const res = await fetch("/api/graph/node/" + encodeURIComponent(nodeId));
    const json = await res.json();
    if (!json.ok) { alert("Load failed"); return; }
    const n = json.data;
    const propsText = Object.entries(n.properties || {})
      .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`).join("\n");
    const body = `
      <p><strong>ID:</strong> <code>${escHtml(n.id)}</code></p>
      <p><strong>Labels:</strong> ${(n.labels || []).map(escHtml).join(", ")}</p>
      <label>Properties
        <textarea id="graphCrudProps" rows="8">${escHtml(propsText)}</textarea>
      </label>
      <div class="graph-crud-actions">
        <button class="btn btn-secondary" id="graphCrudCancel">Cancel</button>
        <button class="btn btn-primary" id="graphCrudSave">Save</button>
      </div>`;
    openModal("Edit Node", body);
    document.getElementById("graphCrudCancel").addEventListener("click", close);
    document.getElementById("graphCrudSave").addEventListener("click", () => saveEdit(nodeId));
  }

  async function saveEdit(nodeId) {
    const propsText = document.getElementById("graphCrudProps").value.trim();
    const properties = {};
    propsText.split(/\n+/).forEach(line => {
      const [k, ...rest] = line.split("=");
      if (k && rest.length) properties[k.trim()] = rest.join("=").trim();
    });
    try {
      const res = await fetch("/api/graph/node/" + encodeURIComponent(nodeId), {
        method: "PATCH",  // PATCH 用于部分更新
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ properties }),
      });
      const json = await res.json();
      if (!json.ok) throw new Error(json.error);
      if (window.GraphMain) window.GraphMain.setStatus("Node updated");
      close();
    } catch (e) {
      alert("Update failed: " + e.message);
    }
  }

  async function deleteNode(nodeId) {
    if (!confirm(`Delete node ${nodeId.slice(0, 12)}…? This will cascade delete relationships.`)) return;
    try {
      const res = await fetch("/api/graph/node/" + encodeURIComponent(nodeId), { method: "DELETE" });
      const json = await res.json();
      if (!json.ok) throw new Error(json.error);
      if (window.GraphMain) window.GraphMain.setStatus("Node deleted");
    } catch (e) {
      alert("Delete failed: " + e.message);
    }
  }

  function escHtml(s) { return String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
  function escAttr(s) { return escHtml(s); }

  window.GraphCRUD = { openCreateNode, openEditNode, deleteNode };
})();
```

> **注意**：上面 `saveCreate` 用了 PATCH 方法，但我们的 handle_graph_delete 只支持 DELETE。需要给 `api/graph.py` 加 PATCH 分支——见 Task 14。

- [ ] **Step 2: ⚠️ 不 commit — 等用户确认**

---

## Task 14: 加 PATCH /api/graph/node/{id} 端点

**Files:**
- Modify: `api/graph.py`

- [ ] **Step 1: handle_graph_post 加 PATCH 分支**

实际更干净的做法是给 `api/graph.py` 加一个 `handle_graph_patch`：

```python
def handle_graph_patch(method: str, parsed_path: str, body: dict) -> tuple[int, dict]:
    path = parsed_path
    store = get_store()
    try:
        if path.startswith("/graph/node/"):
            eid = path[len("/graph/node/"):]
            return 200, _wrap(store.update_node(eid, body.get("properties", {})))
        return *_err(f"unknown PATCH path: {path}", 404),
    except (ValueError, RuntimeError) as e:
        return _err(str(e), 400 if isinstance(e, ValueError) else 503)
```

并在 routes.py 注册 PATCH 路由分发到 `handle_graph_patch`。

- [ ] **Step 2: 跑全部测试**

Run: `pytest tests/ -k graph -v`
Expected: 全部通过

- [ ] **Step 3: ⚠️ 不 commit — 等用户确认**

---

## Task 15: 更新 style.css

**Files:**
- Modify: `static/style.css`

- [ ] **Step 1: 删除 2659-2698 死代码**

删除 `style.css:2659-2698` 整段（旧的 `#graph-panel` / `.graph-header` / 等 kebab-case 选择器）。

- [ ] **Step 2: 追加新样式**

`style.css` 末尾追加：

```css
/* === Graph panel v2 === */
.graph-backend-badge {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  margin-right: 8px;
}
.graph-backend-badge.ok { background: rgba(46, 204, 113, 0.15); color: #2ecc71; }
.graph-backend-badge.warn { background: rgba(241, 196, 15, 0.15); color: #f39c12; }

.graph-tabs {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 10px;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}
.graph-tab {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  font-size: 12px;
  font-weight: 600;
  background: transparent;
  border: 0;
  color: var(--muted);
  cursor: pointer;
  border-radius: 6px;
}
.graph-tab svg { width: 14px; height: 14px; }
.graph-tab:hover { background: var(--hover-bg); color: var(--text); }
.graph-tab.active { background: var(--accent-bg); color: var(--accent-text); }
.graph-search-wrap {
  position: relative;
  margin-left: auto;
  display: flex;
  align-items: center;
  flex: 0 1 280px;
}
.graph-search-wrap .sidebar-search-icon { width: 14px; height: 14px; margin-right: 4px; color: var(--muted); }
.graph-search-wrap input {
  flex: 1;
  padding: 4px 8px;
  font-size: 12px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--input-bg);
  color: var(--text);
}
.graph-search-dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  margin-top: 4px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.2);
  max-height: 240px;
  overflow-y: auto;
  z-index: 100;
}
.graph-search-result {
  padding: 6px 10px;
  cursor: pointer;
  font-size: 12px;
  border-bottom: 1px solid var(--border-subtle);
}
.graph-search-result:hover { background: var(--hover-bg); }
.graph-node-label { font-weight: 600; margin-right: 6px; color: var(--accent); }
.graph-node-name { color: var(--muted); font-size: 11px; }

.graph-body {
  flex: 1;
  min-height: 0;
  position: relative;
  display: flex;
  overflow: hidden;
}
.graph-view { flex: 1; display: flex; min-height: 0; min-width: 0; }
.graph-view-graph { position: relative; }
.graph-canvas { flex: 1; background: var(--bg); }

.graph-empty-state {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  text-align: center;
  padding: 40px;
  background: var(--surface);
  z-index: 5;
}
.graph-empty-icon { font-size: 48px; margin-bottom: 12px; }
.graph-empty-state h3 { margin: 0 0 8px; font-size: 16px; color: var(--text); }
.graph-empty-state p { margin: 0 0 20px; font-size: 13px; color: var(--muted); max-width: 400px; }
.graph-empty-actions { display: flex; gap: 8px; }

.graph-floating-toolbar {
  position: absolute;
  top: 12px;
  right: 12px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  z-index: 4;
}
.graph-fab {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
}
.graph-fab:hover { background: var(--accent-bg); color: var(--accent-text); }

.graph-subtabs {
  display: flex;
  border-bottom: 1px solid var(--border);
  background: var(--surface);
}
.graph-subtab {
  padding: 8px 16px;
  font-size: 12px;
  background: transparent;
  border: 0;
  color: var(--muted);
  cursor: pointer;
  border-bottom: 2px solid transparent;
}
.graph-subtab.active { color: var(--accent); border-bottom-color: var(--accent); }

.graph-table-wrap { flex: 1; overflow: auto; padding: 8px; }
.graph-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
}
.graph-table th, .graph-table td {
  text-align: left;
  padding: 6px 10px;
  border-bottom: 1px solid var(--border-subtle);
}
.graph-table th { background: var(--surface); color: var(--muted); font-weight: 600; }
.graph-td-id { font-family: monospace; color: var(--muted); }
.graph-td-actions { display: flex; gap: 4px; }
.graph-row-btn {
  padding: 2px 8px;
  font-size: 11px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--text);
  border-radius: 4px;
  cursor: pointer;
}
.graph-row-btn.danger { color: #e53; }
.graph-row-btn:hover { background: var(--hover-bg); }

.graph-view-json { display: flex; }
.graph-json-tree {
  flex: 0 0 30%;
  border-right: 1px solid var(--border);
  padding: 12px;
  overflow: auto;
  font-size: 12px;
}
.graph-json-section h4 {
  margin: 12px 0 6px;
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  color: var(--muted);
}
.graph-json-label, .graph-json-type, .graph-json-item {
  padding: 4px 8px;
  cursor: pointer;
  border-radius: 4px;
}
.graph-json-label:hover, .graph-json-item:hover { background: var(--hover-bg); }
.graph-json-detail {
  flex: 1;
  padding: 12px;
  overflow: auto;
}
.graph-json-pre {
  background: var(--surface);
  padding: 12px;
  border-radius: 6px;
  font-size: 11px;
  overflow: auto;
  margin: 8px 0 0;
}
.graph-json-toolbar { display: flex; gap: 6px; margin-bottom: 8px; }

.graph-status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 10px;
  font-size: 11px;
  color: var(--muted);
  border-top: 1px solid var(--border);
  background: var(--surface);
}
.graph-status-msg { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 60%; }
.graph-status-msg[data-kind="error"] { color: #e53; }

.graph-crud-mount { position: fixed; inset: 0; pointer-events: none; z-index: 1000; }
.graph-crud-backdrop {
  position: absolute;
  inset: 0;
  background: rgba(0,0,0,0.4);
  pointer-events: auto;
}
.graph-crud-modal {
  position: absolute;
  top: 50%; left: 50%;
  transform: translate(-50%, -50%);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.3);
  width: min(480px, 90vw);
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  pointer-events: auto;
}
.graph-crud-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}
.graph-crud-head h3 { margin: 0; font-size: 14px; }
.graph-crud-body { padding: 16px; overflow: auto; }
.graph-crud-body label { display: block; font-size: 12px; margin-bottom: 12px; color: var(--muted); }
.graph-crud-body textarea {
  width: 100%;
  font-family: monospace;
  font-size: 12px;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--input-bg);
  color: var(--text);
  margin-top: 4px;
}
.graph-crud-labels { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 4px; }
.graph-crud-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 12px;
  font-size: 11px;
  cursor: pointer;
}
.graph-crud-actions { display: flex; justify-content: flex-end; gap: 8px; }
.btn {
  padding: 6px 14px;
  font-size: 12px;
  font-weight: 600;
  border-radius: 6px;
  cursor: pointer;
  border: 1px solid var(--border);
}
.btn-primary { background: var(--accent); color: var(--accent-text); border-color: var(--accent); }
.btn-secondary { background: var(--surface); color: var(--text); }
.btn-link { background: none; border: 0; color: var(--accent); cursor: pointer; }
```

- [ ] **Step 2: ⚠️ 不 commit — 等用户确认**

---

## Task 16: 启动 + 手动验证

- [ ] **Step 1: 启动 server（Mock 模式）**

Run:
```bash
./start.sh
```
Expected: 看到日志 `Graph store: MOCK (sqlite at data/graph.sqlite) — set NEO4J_PASSWORD for Neo4j`

- [ ] **Step 2: 浏览器打开 http://127.0.0.1:18787**

- [ ] **Step 3: 打开 Graph 面板**

Expected: 看到 GRAPH 头部、`[Graph] [Table] [JSON]` tab strip、`⚠ Mock` 徽章、空白 canvas、底部"图库为空"引导卡片（如果 data/graph.sqlite 不存在）。

- [ ] **Step 4: 点击「一键加载示例」**

Expected: 看到 toast "Loaded 8 nodes, 7 relationships"，canvas 渲染 Cytoscape 图谱。

- [ ] **Step 5: 切换到 Table tab**

Expected: 看到 8 行节点表格，每行有 Locate / Edit / Delete 按钮。

- [ ] **Step 6: 切换到 JSON tab，点击 Host**

Expected: 左侧出现 web-01 / db-01 / cache-01 列表，点击某节点右侧出现 pretty JSON。

- [ ] **Step 7: 搜索 "nginx"**

Expected: 下拉出现 Service:nginx 候选，点击后跳到 Graph 视图并展开 nginx 节点。

- [ ] **Step 8: 创建一个新节点**

点击 [+]，Labels 勾选 Host，Properties 写 `name=test-01`，点 Create。
Expected: 状态栏提示 `Created node mock-xxx…`，Table 视图刷新。

- [ ] **Step 9: 删除刚创建的节点**

Expected: confirm 后节点消失，相关关系级联删除。

- [ ] **Step 10: pytest 全跑**

Run: `pytest tests/ -k graph -v`
Expected: 全部通过

- [ ] **Step 11: ⚠️ 不 commit — 等用户确认**

---

## 收尾

完成所有任务后，把以下内容 stage 但**不 commit**，等用户确认：

```bash
git add api/graph.py api/graph_store.py api/graph_neo4j.py api/graph_mock.py
git add static/index.html static/graph_main.js static/graph_view_graph.js
git add static/graph_view_table.js static/graph_view_json.js static/graph_crud.js
git add static/style.css
git rm static/graph.js
git add tests/test_graph_api.py tests/test_graph_mock.py tests/test_graph_neo4j.py
git add tests/test_graph_store.py tests/test_graph_main.spec.js
git add .gitignore
git status  # 给用户看 staged 内容
```

然后告诉用户："代码已 stage，请确认后告诉我提交。"

---

## 自审检查（write plan 后）

✓ Spec 覆盖：每个 spec 章节都在某 task 中实现（接口 / Mock / Neo4j / 瘦壳 / 三视图 / CRUD / CSS / 测试 / 验证）
✓ Placeholder：无 TBD / TODO；Task 10 留了 TODO 标记需补端点（已在 Task 11 解决）
✓ 类型一致：`get_store()` / `MockStore` / `Neo4jStore` 方法签名在所有 task 中保持一致；`apiGET` → `fetch` 在前端 Task 8 用 `api` helper 统一
✓ 频率 commit：每个 task 都标 ⚠️ 不 commit（用户偏好）