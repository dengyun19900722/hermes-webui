"""Mock-based tests for api/graph.py — Neo4j graph proxy module.

These tests patch ``api.graph.get_driver`` to return a MagicMock that
simulates the small subset of the neo4j driver surface that
``api.graph`` uses (``driver.session()`` as a context manager whose
``session.run()`` returns a Result-like object with ``single()`` and
iteration support).

No real Neo4j connection is required.
"""
from __future__ import annotations

import sys
import pathlib
from unittest.mock import MagicMock, patch

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import api.graph as graph  # noqa: E402


# ── Override conftest's session-scoped autouse server fixture ────────────────
#
# These tests are pure unit tests with all Neo4j access mocked out, so they
# have no need for the live test server that conftest.py spins up. Defining a
# no-op fixture with the same name in this module shadows the conftest one.
@pytest.fixture(scope="session")
def test_server():
    """No-op — graph API unit tests do not require a live HTTP server."""


# ── Helpers ──────────────────────────────────────────────────────────────────


class _FakeRecord(dict):
    """A dict subclass that supports both ``record["key"]`` and attribute
    access via ``record.key`` (mimicking neo4j Record)."""


class _FakeResult:
    """Minimal stand-in for a neo4j Result.

    - Iteration yields ``_FakeRecord`` instances from ``records``.
    - ``.single()`` returns the first record or ``None``.
    """

    def __init__(self, records):
        self._records = [self._coerce(r) for r in records]

    @staticmethod
    def _coerce(item):
        if isinstance(item, _FakeRecord):
            return item
        if isinstance(item, dict):
            return _FakeRecord(item)
        return item

    def __iter__(self):
        return iter(self._records)

    def single(self):
        return self._records[0] if self._records else None

    def consume(self):
        return None


def _make_node_mock(element_id: str = "elem-1",
                    labels: tuple = ("Person",),
                    properties: dict | None = None):
    """Build a duck-typed object that mimics a neo4j Node.

    Supports:
      - ``node.element_id``
      - ``node.labels`` (iterable)
      - ``dict(node)`` and ``node["key"]`` to extract properties
      - ``node.get("key", default)``
    """
    props = dict(properties or {"name": "Alice", "age": 30})

    class _Node:
        def __init__(self):
            self.element_id = element_id
            self.labels = tuple(labels)
            self._props = props

        def __iter__(self):
            return iter(self._props.items())

        def __getitem__(self, key):
            return self._props[key]

        def get(self, key, default=None):
            return self._props.get(key, default)

        def __contains__(self, key):
            return key in self._props

        def keys(self):
            return self._props.keys()

        def values(self):
            return self._props.values()

        def items(self):
            return self._props.items()

    # ``dict(node)`` calls ``node.keys()``; ensure MagicMock side_effects
    # don't intercept our dunder methods.
    return _Node()


def _make_rel_mock(element_id: str = "rel-1",
                   rel_type: str = "KNOWS",
                   start: object | None = None,
                   end: object | None = None,
                   properties: dict | None = None):
    """Build a duck-typed object that mimics a neo4j Relationship."""
    props = dict(properties or {"since": 2020})
    start_node = start if start is not None else _make_node_mock("start-1", ("Person",), {"name": "Alice"})
    end_node = end if end is not None else _make_node_mock("end-1", ("Person",), {"name": "Bob"})

    class _Rel:
        def __init__(self):
            self.element_id = element_id
            self.type = rel_type
            self.start_node = start_node
            self.end_node = end_node
            self._props = props

        def __iter__(self):
            return iter(self._props.items())

        def __getitem__(self, key):
            return self._props[key]

        def get(self, key, default=None):
            return self._props.get(key, default)

        def keys(self):
            return self._props.keys()

    return _Rel()


def _patched_driver():
    """Context manager that patches ``api.graph.get_driver`` with a fresh mock.

    Returns the patched driver mock so tests can configure session.run()
    return values per-call.
    """
    driver = MagicMock()
    session = MagicMock()
    driver.session.return_value.__enter__.return_value = session
    driver.session.return_value.__exit__.return_value = False
    return driver, session


@pytest.fixture(autouse=True)
def _reset_driver_singleton():
    """Reset the cached driver singleton and env var between tests."""
    graph._driver = None
    yield
    graph._driver = None


# ── 1. list_nodes ─────────────────────────────────────────────────────────────


def test_list_nodes():
    """list_nodes returns normalized ``{"id", "properties"}`` dicts."""
    node_a = _make_node_mock("elem-A", ("Person",), {"name": "Alice"})
    node_b = _make_node_mock("elem-B", ("Person",), {"name": "Bob"})
    result = _FakeResult([{"n": node_a}, {"n": node_b}])

    driver, session = _patched_driver()
    session.run.return_value = result

    with patch.object(graph, "get_driver", return_value=driver):
        nodes = graph.list_nodes(label="Person", limit=10)

    assert isinstance(nodes, list)
    assert len(nodes) == 2
    for n in nodes:
        assert "id" in n
        assert "properties" in n
    assert nodes[0]["id"] == "elem-A"
    assert nodes[0]["properties"]["name"] == "Alice"


# ── 2. get_node ──────────────────────────────────────────────────────────────


def test_get_node():
    """get_node returns ``{id, labels, properties}`` for a matching element_id."""
    node = _make_node_mock("elem-42", ("Person",), {"name": "Alice"})
    record = _FakeRecord({"n": node})
    result = _FakeResult([record])

    driver, session = _patched_driver()
    session.run.return_value = result

    with patch.object(graph, "get_driver", return_value=driver):
        data = graph.get_node("elem-42")

    assert data is not None
    assert data["id"] == "elem-42"
    assert data["labels"] == ["Person"]
    assert data["properties"]["name"] == "Alice"


# ── 3. create_node ───────────────────────────────────────────────────────────


def test_create_node():
    """create_node returns the newly-created node dict."""
    node = _make_node_mock("new-id", ("Person",), {"name": "Alice"})
    record = _FakeRecord({"id": "new-id", "n": node})
    result = _FakeResult([record])

    driver, session = _patched_driver()
    session.run.return_value = result

    with patch.object(graph, "get_driver", return_value=driver):
        created = graph.create_node(label="Person", properties={"name": "Alice"})

    # create_node returns the dict from get_node; ensure an id was assigned
    assert created is not None
    assert created["id"] == "new-id"
    assert "Person" in created["labels"]


# ── 4. update_node ───────────────────────────────────────────────────────────


def test_update_node():
    """update_node returns the updated node dict."""
    node = _make_node_mock("elem-7", ("Person",), {"name": "Bob"})
    update_record = _FakeRecord({"id": "elem-7"})
    update_result = _FakeResult([update_record])
    fetch_record = _FakeRecord({"n": node})
    fetch_result = _FakeResult([fetch_record])

    driver, session = _patched_driver()
    # update_node runs two queries: SET (returns {"id"}) then get_node (returns {"n"})
    session.run.side_effect = [update_result, fetch_result]

    with patch.object(graph, "get_driver", return_value=driver):
        updated = graph.update_node("elem-7", {"name": "Bob"})

    assert updated is not None
    assert updated["id"] == "elem-7"
    assert updated["properties"]["name"] == "Bob"


# ── 5. delete_node ───────────────────────────────────────────────────────────


def test_delete_node():
    """delete_node returns True when the MATCH found a row."""
    record = _FakeRecord({"deleted": 1})
    result = _FakeResult([record])

    driver, session = _patched_driver()
    session.run.return_value = result

    with patch.object(graph, "get_driver", return_value=driver):
        assert graph.delete_node("elem-9") is True


# ── 6. list_relationships ────────────────────────────────────────────────────


def test_list_relationships():
    """list_relationships yields dicts with id/type/start/end."""
    rel = _make_rel_mock("rel-1", "KNOWS")
    record = _FakeRecord({
        "r": rel,
        "sid": "start-1", "sname": "Alice",
        "eid": "end-1", "ename": "Bob",
        "start_id": "start-1", "end_id": "end-1",
    })
    result = _FakeResult([record])

    driver, session = _patched_driver()
    session.run.return_value = result

    with patch.object(graph, "get_driver", return_value=driver):
        rels = graph.list_relationships("start-1")

    assert isinstance(rels, list)
    assert len(rels) == 1
    r = rels[0]
    assert r["id"] == "rel-1"
    assert r["type"] == "KNOWS"
    assert r["start_node_id"] == "start-1"
    assert r["end_node_id"] == "end-1"


# ── 7. create_relationship ──────────────────────────────────────────────────


def test_create_relationship():
    """create_relationship returns the new relationship dict."""
    rel = _make_rel_mock("new-rel", "KNOWS")
    record = _FakeRecord({"id": "new-rel", "r": rel, "sname": "Alice", "ename": "Bob"})
    result = _FakeResult([record])

    driver, session = _patched_driver()
    session.run.return_value = result

    with patch.object(graph, "get_driver", return_value=driver):
        created = graph.create_relationship(
            start_node_id="start-1",
            end_node_id="end-1",
            rel_type="KNOWS",
            properties={},
        )

    assert created is not None
    assert created["id"] == "new-rel"
    assert created["type"] == "KNOWS"


# ── 8. delete_relationship ───────────────────────────────────────────────────


def test_delete_relationship():
    """delete_relationship returns True when the MATCH found a row."""
    record = _FakeRecord({"deleted": 1})
    result = _FakeResult([record])

    driver, session = _patched_driver()
    session.run.return_value = result

    with patch.object(graph, "get_driver", return_value=driver):
        assert graph.delete_relationship("rel-1") is True


# ── 9. search_graph ──────────────────────────────────────────────────────────


def test_search_graph():
    """search_graph with a label returns the ``results`` list."""
    node = _make_node_mock("elem-S", ("Person",), {"name": "Alice"})
    record = _FakeRecord({"n": node})
    result = _FakeResult([record])

    driver, session = _patched_driver()
    session.run.return_value = result

    with patch.object(graph, "get_driver", return_value=driver):
        data = graph.search_graph("Alice", label="Person")

    assert data["query"] == "Alice"
    assert data["count"] == 1
    assert isinstance(data["results"], list)
    assert data["results"][0]["properties"]["name"] == "Alice"


# ── 10. get_topology ────────────────────────────────────────────────────────


def test_get_topology():
    """get_topology returns ``{nodes, relationships}`` for a center node."""
    center = _make_node_mock("center-1", ("Person",), {"name": "Alice"})
    leaf = _make_node_mock("leaf-1", ("Person",), {"name": "Bob"})
    rel = _make_rel_mock("rel-T", "KNOWS")

    record = _FakeRecord({"nodes": [center, leaf], "rels": [rel]})
    result = _FakeResult([record])

    driver, session = _patched_driver()
    session.run.return_value = result

    with patch.object(graph, "get_driver", return_value=driver):
        topo = graph.get_topology("center-1", depth=2)

    assert "nodes" in topo
    assert "relationships" in topo
    assert isinstance(topo["nodes"], list)
    assert isinstance(topo["relationships"], list)


# ── 11. handle_graph_get: schema ────────────────────────────────────────────


def test_handle_graph_get_schema():
    """GET /graph/schema returns the schema payload."""
    driver, session = _patched_driver()
    # Three separate run() calls — labels, relationshipTypes, propertyKeys
    labels_result = _FakeResult([{"label": "Person"}, {"label": "Project"}])
    rels_result = _FakeResult([{"relationshipType": "KNOWS"}])
    props_result = _FakeResult([{"propertyKey": "name"}, {"propertyKey": "age"}])
    session.run.side_effect = [labels_result, rels_result, props_result]

    with patch.object(graph, "get_driver", return_value=driver):
        status, payload = graph.handle_graph_get("GET", "/graph/schema", {})

    assert status == 200
    assert "Person" in payload["node_labels"]
    assert "KNOWS" in payload["relationship_types"]
    assert "name" in payload["property_keys"]


# ── 12. handle_graph_get: nodes ─────────────────────────────────────────────


def test_handle_graph_get_nodes():
    """GET /graph/nodes with label param calls list_nodes."""
    node = _make_node_mock("elem-N", ("Person",), {"name": "Alice"})
    result = _FakeResult([{"n": node}])

    driver, session = _patched_driver()
    session.run.return_value = result

    with patch.object(graph, "get_driver", return_value=driver):
        status, payload = graph.handle_graph_get(
            "GET", "/graph/nodes", {"label": "Person", "limit": "5"},
        )

    assert status == 200
    assert isinstance(payload, list)
    assert payload[0]["id"] == "elem-N"
    assert payload[0]["properties"]["name"] == "Alice"


# ── 13. handle_graph_post: node ────────────────────────────────────────────


def test_handle_graph_post_node():
    """POST /graph/nodes returns 201 with the new node id."""
    node = _make_node_mock("created-1", ("Person",), {"name": "Bob"})
    record = _FakeRecord({"id": "created-1", "n": node})
    result = _FakeResult([record])

    driver, session = _patched_driver()
    session.run.return_value = result

    with patch.object(graph, "get_driver", return_value=driver):
        status, payload = graph.handle_graph_post(
            "/graph/nodes",
            {"label": "Person", "properties": {"name": "Bob"}},
        )

    assert status == 201
    assert payload["id"] == "created-1"


# ── 14. handle_graph_delete: node ──────────────────────────────────────────


def test_handle_graph_delete_node():
    """DELETE /graph/node/<id> returns 200 ``{deleted: True}``."""
    record = _FakeRecord({"deleted": 1})
    result = _FakeResult([record])

    driver, session = _patched_driver()
    session.run.return_value = result

    with patch.object(graph, "get_driver", return_value=driver):
        status, payload = graph.handle_graph_delete("/graph/node/elem-123")

    assert status == 200
    assert payload == {"deleted": True}


# ── 15. handle_graph_* not found ───────────────────────────────────────────


def test_handle_graph_not_found():
    """Unknown graph paths return 404."""
    status, payload = graph.handle_graph_get("GET", "/graph/unknown", {})
    assert status == 404
    assert "error" in payload

    status, payload = graph.handle_graph_post("/graph/unknown", {})
    assert status == 404
    assert "error" in payload

    status, payload = graph.handle_graph_delete("/graph/unknown")
    assert status == 404
    assert "error" in payload