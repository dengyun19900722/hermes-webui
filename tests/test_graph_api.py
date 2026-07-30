"""Graph API thin shell tests."""
import pytest
from api.graph import get_store, handle_graph_get, handle_graph_post, handle_graph_delete


@pytest.fixture(scope="session")
def test_server():
    """纯单元测试无需启动 HTTP 测试服务器。"""


def test_get_store_returns_instance():
    s = get_store()
    assert s is not None
    assert hasattr(s, "health")


def test_handle_graph_get_health():
    status, payload = handle_graph_get("GET", "/graph/health", {})
    assert status == 200
    assert payload["ok"] is True
    assert "backend" in payload["data"]
    assert payload["data"]["backend"] in ("neo4j", "mock")


def test_handle_graph_get_schema():
    status, payload = handle_graph_get("GET", "/graph/schema", {})
    assert status == 200
    assert payload["ok"] is True
    assert "node_labels" in payload["data"]
    assert "relationship_types" in payload["data"]
    assert "stats" in payload["data"]


def test_handle_graph_get_search_keeps_dict_format():
    """关键：search 返回必须是 {ok, data:{results,query,count}}。"""
    status, payload = handle_graph_get(
        "GET", "/graph/search", {"q": "anything"}
    )
    assert status == 200
    assert payload["ok"] is True
    assert "results" in payload["data"]
    assert "query" in payload["data"]
    assert "count" in payload["data"]


def test_handle_graph_get_search_requires_q():
    """无 q 参数时返回 400。"""
    status, payload = handle_graph_get("GET", "/graph/search", {})
    assert status == 400
    assert payload["ok"] is False
    assert "q" in payload["error"].lower() or "required" in payload["error"].lower()


def test_handle_graph_get_nodes_no_label():
    """无 label 参数时返回全量节点（不再报 400）。"""
    status, payload = handle_graph_get("GET", "/graph/nodes", {})
    assert status == 200
    assert payload["ok"] is True
    assert isinstance(payload["data"].get("results"), list)
    assert isinstance(payload["data"].get("count"), int)


def test_handle_graph_post_seed():
    status, payload = handle_graph_post("POST", "/graph/seed", {})
    assert status == 200
    assert payload["ok"] is True
    assert "nodes_added" in payload["data"]
    assert "relationships_added" in payload["data"]


def test_handle_graph_post_create_node():
    status, payload = handle_graph_post("POST", "/graph/nodes",
                                          {"labels": ["Host"], "properties": {"name": "test"}})
    assert status == 200
    assert payload["ok"] is True
    assert "id" in payload["data"]
