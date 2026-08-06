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


def test_topology_direction_in(store):
    """direction='in' 仅返回指向该节点的关系对应的起点（上游/被依赖）。"""
    a = store.create_node(["Host"], {"name": "a"})
    b = store.create_node(["Host"], {"name": "b"})
    c = store.create_node(["Host"], {"name": "c"})
    # b -> a, c -> a （a 是被依赖的终点）
    store.create_relationship("DEPENDS_ON", b["id"], a["id"])
    store.create_relationship("DEPENDS_ON", c["id"], a["id"])
    # in: 只看入向，所以 a + b + c 都出现（b/c 指向 a）
    topo = store.topology(a["id"], depth=1, direction="in")
    node_ids = {n["id"] for n in topo["nodes"]}
    assert node_ids == {a["id"], b["id"], c["id"]}
    # out: 只有 a 本身
    topo_out = store.topology(a["id"], depth=1, direction="out")
    assert {n["id"] for n in topo_out["nodes"]} == {a["id"]}


def test_topology_direction_out(store):
    """direction='out' 仅返回该节点指向的关系对应的终点（下游/依赖）。"""
    a = store.create_node(["Host"], {"name": "a"})
    b = store.create_node(["Host"], {"name": "b"})
    c = store.create_node(["Host"], {"name": "c"})
    # a -> b, a -> c
    store.create_relationship("DEPENDS_ON", a["id"], b["id"])
    store.create_relationship("DEPENDS_ON", a["id"], c["id"])
    topo = store.topology(a["id"], depth=1, direction="out")
    assert {n["id"] for n in topo["nodes"]} == {a["id"], b["id"], c["id"]}
    topo_in = store.topology(a["id"], depth=1, direction="in")
    assert {n["id"] for n in topo_in["nodes"]} == {a["id"]}


def test_topology_direction_invalid_raises(store):
    a = store.create_node(["Host"], {"name": "a"})
    with pytest.raises(ValueError):
        store.topology(a["id"], depth=1, direction="weird")


def test_topology_depth_zero_means_all(store):
    """depth=0 → BFS 展开到 frontier 空（或 5 跳上限），覆盖整条链。"""
    nodes = [store.create_node(["Host"], {"name": f"n{i}"})["id"]
             for i in range(7)]
    for i in range(6):
        store.create_relationship("DEPENDS_ON", nodes[i], nodes[i+1])
    topo = store.topology(nodes[0], depth=0, direction="out")
    node_ids = {n["id"] for n in topo["nodes"]}
    # 全部 7 个链节点都应被覆盖
    assert node_ids == set(nodes)
    # 中途反向不可达的旁支节点不应出现
    side = store.create_node(["Host"], {"name": "side"})
    store.create_relationship("DEPENDS_ON", side["id"], nodes[3])
    topo_fwd = store.topology(nodes[0], depth=0, direction="out")
    assert side["id"] not in {n["id"] for n in topo_fwd["nodes"]}
    # depth=0 双向：反向旁支可达
    topo_both = store.topology(nodes[0], depth=0, direction="both")
    assert side["id"] in {n["id"] for n in topo_both["nodes"]}


def test_topology_depth_invalid_raises(store):
    a = store.create_node(["Host"], {"name": "a"})
    for bad in (-1, 6, 100):
        with pytest.raises(ValueError):
            store.topology(a["id"], depth=bad)


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
