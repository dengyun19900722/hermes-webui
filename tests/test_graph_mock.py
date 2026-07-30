"""Mock (SQLite) 存储实现测试。Cypher-free，CI 友好。"""
import os
import tempfile
import pytest
from api.graph_mock import MockStore


@pytest.fixture(scope="session")
def test_server():
    """纯单元测试无需启动 HTTP 测试服务器。"""


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


def test_list_all_relationships(store):
    a = store.create_node(["Host"], {"name": "a"})
    b = store.create_node(["Host"], {"name": "b"})
    store.create_relationship("DEPENDS_ON", a["id"], b["id"])
    rels = store.list_all_relationships()
    assert len(rels) == 1
    assert rels[0]["type"] == "DEPENDS_ON"
