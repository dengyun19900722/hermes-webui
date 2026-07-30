"""Neo4j Cypher 字符串生成测试。不连真实数据库，只断言生成的 Cypher 正确。"""
import pytest
from api.graph_neo4j import _build_topology_cypher, _validate_identifier, Neo4jStore


@pytest.fixture(scope="session")
def test_server():
    """纯单元测试无需启动 HTTP 测试服务器。"""


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
    cypher, params = _build_topology_cypher(direction="both",
                                            depth=2, rel_types=None, limit=100)
    assert "*1..2" in cypher
    assert "$depth" not in cypher
    assert params["limit"] == 100
    assert "elementId(center) = $element_id" in cypher


def test_topology_cypher_clamps_depth():
    """depth 必须在 [1, 5] 内。"""
    for bad in (0, -1, 6, 100):
        with pytest.raises(ValueError):
            _build_topology_cypher(direction="both", depth=bad,
                                   rel_types=None, limit=50)


def test_topology_cypher_filters_rel_types():
    cypher, params = _build_topology_cypher(direction="out",
                                            depth=1, rel_types=["DEPENDS_ON"], limit=50)
    assert "DEPENDS_ON" in cypher
    assert "$depth" not in cypher


def test_topology_cypher_direction_in():
    cypher, _ = _build_topology_cypher(direction="in",
                                       depth=1, rel_types=None, limit=50)
    assert "<-[r]-" in cypher


def test_search_cypher_contains_query():
    """Ensure search Cypher uses parameterized query string."""
    ns = Neo4jStore.__new__(Neo4jStore)
    cypher = ns._build_search_cypher("nginx", label=None, limit=10)
    assert "$query" in cypher
    assert "toString(n[k])" in cypher


def test_search_cypher_with_label():
    ns = Neo4jStore.__new__(Neo4jStore)
    cypher = ns._build_search_cypher("nginx", label="Host", limit=10)
    assert "$label IN labels(n)" in cypher
