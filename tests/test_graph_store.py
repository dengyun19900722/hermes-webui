"""GraphStore 接口契约测试。"""
from typing import Protocol

import pytest

from api.graph_store import GraphStore


@pytest.fixture(scope="session")
def test_server():
    """纯单元测试无需启动 HTTP 测试服务器。"""


def test_graphstore_is_a_protocol():
    """GraphStore 必须是 Protocol，不能是具体类。"""
    assert GraphStore._is_protocol is True
    assert Protocol in GraphStore.__mro__


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
