"""
Hermes WebUI — Neo4j graph proxy.
Provides REST endpoints for the Graph panel: schema discovery, node/relationship
CRUD, topology, and search.
"""
import logging
import os
import re
import threading
from typing import Any

from api.helpers import j, bad

logger = logging.getLogger(__name__)

# ── Neo4j connection ──────────────────────────────────────────────────────────

_driver = None
_driver_lock = threading.Lock()

# Cypher identifier pattern: must start with letter/underscore, then word chars
_CYPHER_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_identifier(value: str, kind: str) -> str:
    """Validate that a string is a safe Cypher identifier (label or rel type).

    Returns the value unchanged on success. Raises ``ValueError`` on invalid input.
    """
    if not value or not _CYPHER_IDENT_RE.match(value):
        raise ValueError(f"Invalid {kind}: {value!r}")
    return value


def _get_neo4j_config() -> dict:
    """Read Neo4j connection config from environment variables."""
    return {
        "uri": os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        "user": os.environ.get("NEO4J_USER", "neo4j"),
        "password": os.environ.get("NEO4J_PASSWORD") or "",
    }


def get_driver():
    """Lazily create and return a Neo4j Driver singleton (thread-safe).

    On first creation, runs ``RETURN 1`` to verify connectivity.
    Raises ``RuntimeError`` if the verification query fails.
    """
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
        # Verify connectivity on first creation
        try:
            with _driver.session() as session:
                session.run("RETURN 1").single()
        except Exception as exc:
            _driver.close()
            _driver = None
            raise RuntimeError(f"Neo4j connectivity check failed: {exc}")
        return _driver


def close_driver():
    """Close the driver singleton. Call on server shutdown."""
    global _driver
    with _driver_lock:
        if _driver is not None:
            _driver.close()
            _driver = None


def _run_query(cypher: str, params: dict | None = None) -> list[dict]:
    """Execute a read Cypher query and return a list of result dicts.

    Raises ``RuntimeError`` with a structured message on Neo4j errors.
    """
    try:
        driver = get_driver()
    except Exception as exc:
        raise RuntimeError(f"Neo4j driver unavailable: {exc}") from exc
    try:
        with driver.session() as session:
            result = session.run(cypher, params or {})
            return [dict(record) for record in result]
    except Exception as exc:
        logger.warning("Cypher query failed: %s | query=%s", exc, cypher)
        raise RuntimeError(f"Neo4j query failed: {exc}") from exc


def _run_write(cypher: str, params: dict | None = None) -> Any:
    """Execute a write Cypher query and return the first record, or ``None``.

    Raises ``RuntimeError`` with a structured message on Neo4j errors.
    """
    try:
        driver = get_driver()
    except Exception as exc:
        raise RuntimeError(f"Neo4j driver unavailable: {exc}") from exc
    try:
        with driver.session() as session:
            return session.run(cypher, params or {}).single()
    except Exception as exc:
        logger.warning("Cypher write failed: %s | query=%s", exc, cypher)
        raise RuntimeError(f"Neo4j write failed: {exc}") from exc


# ── Schema discovery ─────────────────────────────────────────────────────────

def get_schema() -> dict:
    """Return all node labels, relationship types, and property keys.

    Raises ``ConnectionError`` if the driver cannot be initialized.
    """
    driver = get_driver()
    with driver.session() as session:
        # All node labels
        labels_result = session.run("CALL db.labels() YIELD label RETURN label")
        node_labels = sorted(set(r["label"] for r in labels_result))

        # All relationship types
        rels_result = session.run(
            "CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType"
        )
        rel_types = sorted(set(r["relationshipType"] for r in rels_result))

        # All property keys
        props_result = session.run(
            "CALL db.propertyKeys() YIELD propertyKey RETURN propertyKey"
        )
        property_keys = sorted(set(r["propertyKey"] for r in props_result))

    return {
        "node_labels": node_labels,
        "relationship_types": rel_types,
        "property_keys": property_keys,
    }


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


def list_nodes(label: str, limit: int = 100) -> list[dict]:
    """List nodes of a given label, returning a list of ``{'id', 'properties'}``."""
    if label:
        _validate_identifier(label, "label")
    driver = get_driver()
    label_cypher = f":`{label}`" if label else ""
    cypher = (
        f"MATCH (n {label_cypher}) "
        f"RETURN n LIMIT $limit"
    )
    with driver.session() as session:
        nodes = [_node_to_dict(r["n"]) for r in session.run(cypher, {"limit": limit})]
    # Normalize to {"id": ..., "properties": ...} per spec
    return [{"id": n["id"], "properties": n["properties"]} for n in nodes]


def get_node(element_id: str) -> dict | None:
    """Return a single node by its element_id, including its labels list."""
    cypher = "MATCH (n) WHERE elementId(n) = $element_id RETURN n"
    with get_driver().session() as session:
        result = session.run(cypher, {"element_id": element_id})
        record = result.single()
        if not record:
            return None
        node = record["n"]
        return {
            "id": node.element_id,
            "labels": list(node.labels),
            "properties": dict(node),
        }


def create_node(label: str, properties: dict) -> dict:
    """Create a node with a single label and the given properties."""
    if label:
        _validate_identifier(label, "label")
    label_str = f":`{label}`" if label else ""
    props_keys = list(properties.keys())
    params = {"props": properties}
    set_clause = ", ".join(f"n.`{k}` = $props.`{k}`" for k in props_keys)
    cypher = (
        f"CREATE (n {label_str} {{}}) "
        f"SET {set_clause} "
        "RETURN elementId(n) AS id, n"
    )
    with get_driver().session() as session:
        result = session.run(cypher, params)
        record = result.single()
        node_id = record["id"]
    return get_node(node_id)


def update_node(element_id: str, properties: dict) -> dict | None:
    """Update a node's properties."""
    props_keys = list(properties.keys())
    params = {"element_id": element_id, "props": properties}
    set_clause = ", ".join(f"n.`{k}` = $props.`{k}`" for k in props_keys)
    cypher = (
        f"MATCH (n) WHERE elementId(n) = $element_id "
        f"SET {set_clause} "
        "RETURN elementId(n) AS id"
    )
    with get_driver().session() as session:
        result = session.run(cypher, params)
        if result.single() is None:
            return None
    return get_node(element_id)


def delete_node(element_id: str) -> bool:
    """Delete a node and all its relationships."""
    cypher = (
        "MATCH (n) WHERE elementId(n) = $element_id "
        "DETACH DELETE n "
        "RETURN count(n) AS deleted"
    )
    with get_driver().session() as session:
        deleted = session.run(cypher, {"element_id": element_id}).single()["deleted"]
    return deleted > 0


def expand_node(element_id: str, depth: int = 1, direction: str = "both",
               rel_types: list[str] | None = None, limit: int = 100) -> dict:
    """Return the center node plus its neighbors and relationships within depth."""
    if rel_types:
        for rt in rel_types:
            _validate_identifier(rt, "relationship_type")
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
        f"MATCH path = (center) WHERE elementId(center) = $element_id "
        f"CALL {{ "
        f"  WITH center "
        f"  MATCH path = (center){dir_pattern}*1..$depth(neighbor) "
        f"  WHERE true {rel_clause} "
        f"  RETURN path LIMIT $limit "
        f"}} "
        f"RETURN center, nodes(path) AS nodes, rels(path) AS rels"
    )

    with driver.session() as session:
        result = session.run(
            cypher,
            {"element_id": element_id, "depth": depth, "limit": limit},
        )
        records = list(result)

    if not records:
        center = get_node(element_id)
        return {"center": center, "nodes": [], "relationships": []}

    rec = records[0]
    center_node = _node_to_dict(rec["center"]) if rec["center"] else get_node(element_id)
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


def list_relationships(element_id: str, direction: str = "both") -> list[dict]:
    """List relationships for a given node element_id, paginated by the node.

    ``direction`` is one of ``'both'``, ``'in'``, ``'out'``.
    """
    driver = get_driver()
    if direction == "out":
        dir_pattern = "-[r]->"
    elif direction == "in":
        dir_pattern = "<-[r]-"
    else:
        dir_pattern = "-[r]-"

    cypher = (
        f"MATCH (n) WHERE elementId(n) = $element_id "
        f"MATCH (n){dir_pattern}(m) "
        f"RETURN r, elementId(n) AS sid, n.name AS sname, "
        f"elementId(m) AS eid, m.name AS ename, "
        f"elementId(startNode(r)) AS start_id, "
        f"elementId(endNode(r)) AS end_id"
    )

    with driver.session() as session:
        rels = []
        for rec in session.run(cypher, {"element_id": element_id}):
            rels.append(_rel_to_dict(
                rec["r"],
                start_name=rec["sname"] or "",
                end_name=rec["ename"] or "",
            ))

    return rels


def create_relationship(start_node_id: str, end_node_id: str, rel_type: str,
                        properties: dict) -> dict | None:
    """Create a relationship between two nodes."""
    _validate_identifier(rel_type, "relationship_type")
    params = {
        "rel_type": rel_type,
        "start_node_id": start_node_id,
        "end_node_id": end_node_id,
        "props": properties,
    }
    props_set = ", ".join(f"r.`{k}` = $props.`{k}`" for k in properties.keys())
    cypher = (
        "MATCH (s) WHERE elementId(s) = $start_node_id "
        "MATCH (e) WHERE elementId(e) = $end_node_id "
        f"CREATE (s)-[r:`{rel_type}`]->(e) "
        f"SET {props_set} "
        "RETURN elementId(r) AS id, s.name AS sname, e.name AS ename, r"
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


def update_relationship(element_id: str, properties: dict) -> dict | None:
    """Update a relationship's properties."""
    params = {"element_id": element_id, "props": properties}
    props_set = ", ".join(f"r.`{k}` = $props.`{k}`" for k in properties.keys())
    cypher = (
        "MATCH ()-[r]->() WHERE elementId(r) = $element_id "
        f"SET {props_set} "
        "RETURN elementId(r) AS id"
    )
    with get_driver().session() as session:
        result = session.run(cypher, params)
        if result.single() is None:
            return None
    # Fetch full rel
    cypher2 = (
        "MATCH (s)-[r]->(e) WHERE elementId(r) = $element_id "
        "RETURN r, s.name AS sname, e.name AS ename"
    )
    with get_driver().session() as session:
        rec = session.run(cypher2, {"element_id": element_id}).single()
        if rec is None:
            return None
        return _rel_to_dict(rec["r"], rec["sname"] or "", rec["ename"] or "")


def delete_relationship(element_id: str) -> bool:
    """Delete a relationship by its element_id."""
    cypher = (
        "MATCH ()-[r]->() WHERE elementId(r) = $element_id "
        "DELETE r "
        "RETURN count(r) AS deleted"
    )
    with get_driver().session() as session:
        deleted = session.run(cypher, {"element_id": element_id}).single()["deleted"]
    return deleted > 0


def get_relationship(element_id: str) -> dict | None:
    """Return a single relationship by its element_id."""
    cypher = (
        "MATCH (s)-[r]->(e) WHERE elementId(r) = $element_id "
        "RETURN r, s.name AS sname, e.name AS ename"
    )
    with get_driver().session() as session:
        rec = session.run(cypher, {"element_id": element_id}).single()
        if rec is None:
            return None
        return _rel_to_dict(rec["r"], rec["sname"] or "", rec["ename"] or "")


# ── Search and topology ──────────────────────────────────────────────────────

def search_graph(query: str, label: str | None = None, limit: int = 50) -> dict:
    """Search nodes by keyword across name and all property values."""
    driver = get_driver()
    params: dict[str, Any] = {"query": query, "limit": limit}

    if label:
        _validate_identifier(label, "label")
        params["label"] = label
        cypher = (
            "MATCH (n) "
            "WHERE any(k IN keys(n) WHERE toString(n[k]) CONTAINS $query) "
            "AND $label IN labels(n) "
            "RETURN n LIMIT $limit"
        )
    else:
        cypher = (
            "MATCH (n) "
            "WHERE any(k IN keys(n) WHERE toString(n[k]) CONTAINS $query) "
            "RETURN n LIMIT $limit"
        )

    with driver.session() as session:
        nodes = [_node_to_dict(r["n"]) for r in session.run(cypher, params)]

    return {"results": nodes, "query": query, "count": len(nodes)}


def get_topology(element_id: str, depth: int = 1) -> dict:
    """Return a subgraph centered on the given node element_id, within depth."""
    driver = get_driver()
    cypher = (
        "MATCH path = (center)-[r*1..$depth]-(leaf) "
        "WHERE elementId(center) = $element_id "
        "WITH nodes(path) AS ns, rels(path) AS rs "
        "UNWIND ns AS n WITH collect(DISTINCT n) AS uniq, rs "
        "UNWIND rs AS r "
        "RETURN uniq AS nodes, collect(DISTINCT r) AS rels"
    )
    params = {"element_id": element_id, "depth": depth}

    try:
        with driver.session() as session:
            result = session.run(cypher, params)
            rec = result.single()
            if not rec:
                return {"nodes": [], "relationships": []}

            nodes = [_node_to_dict(n) for n in rec["nodes"]]
            relationships = []
            for rel in rec["rels"]:
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


# ── HTTP Handlers (called from routes.py) ───────────────────────────────────

def _err(exc: Exception):
    """Map an internal exception to an (status, payload) tuple."""
    if isinstance(exc, ValueError):
        return 400, {"error": str(exc)}
    if isinstance(exc, (ConnectionError, RuntimeError)):
        return 503, {"error": str(exc)}
    return 500, {"error": f"Internal error: {exc}"}


def handle_graph_get(method: str, parsed_path: str, query_params: dict) -> tuple:
    """Route all GET /graph/* requests.

    Returns a ``(status, data)`` tuple.
    """
    path = parsed_path
    try:
        if path == "/graph/schema":
            return 200, get_schema()

        if path == "/graph/search":
            query = query_params.get("q", "")
            label = query_params.get("label") or None
            limit = int(query_params.get("limit", 50))
            if not query:
                return 400, {"error": "q parameter is required"}
            return 200, search_graph(query, label, limit)

        if path == "/graph/nodes":
            label = query_params.get("label", "")
            if not label:
                return 400, {"error": "label parameter is required"}
            limit = int(query_params.get("limit", 100))
            return 200, list_nodes(label, limit)

        if path.startswith("/graph/node/"):
            element_id = path.split("/graph/node/")[1]
            data = get_node(element_id)
            if data is None:
                return 404, {"error": f"Node not found: {element_id}"}
            return 200, data

        if path.startswith("/graph/relationship/"):
            element_id = path.split("/graph/relationship/")[1]
            data = get_relationship(element_id)
            if data is None:
                return 404, {"error": f"Relationship not found: {element_id}"}
            return 200, data

        if path.startswith("/graph/relationships/"):
            element_id = path.split("/graph/relationships/")[1]
            direction = query_params.get("direction", "both")
            return 200, list_relationships(element_id, direction)

        if path.startswith("/graph/topology/"):
            element_id = path.split("/graph/topology/")[1]
            depth = int(query_params.get("depth", 1))
            return 200, get_topology(element_id, depth)

        return 404, {"error": f"Unknown graph endpoint: GET {path}"}
    except (ValueError, ConnectionError, RuntimeError) as exc:
        return _err(exc)


def handle_graph_post(parsed_path: str, body: dict) -> tuple:
    """Route all POST /graph/* requests.

    Returns a ``(status, data)`` tuple.
    """
    path = parsed_path
    try:
        if path == "/graph/nodes":
            label = body.get("label", "")
            properties = body.get("properties", {})
            if not label:
                return 400, {"error": "label is required"}
            return 201, create_node(label, properties)

        if path == "/graph/relationships":
            start_id = body.get("start_node_id")
            end_id = body.get("end_node_id")
            rel_type = body.get("type")
            properties = body.get("properties", {})
            if not rel_type or not start_id or not end_id:
                return 400, {"error": "type, start_node_id, and end_node_id are required"}
            data = create_relationship(start_id, end_id, rel_type, properties)
            if data is None:
                return 400, {"error": "Failed to create relationship — check node IDs"}
            return 201, data

        if path.startswith("/graph/node/") and path.endswith("/expand"):
            element_id = path.split("/graph/node/")[1].replace("/expand", "")
            depth = int(body.get("depth", 1))
            direction = body.get("direction", "both")
            rel_types = body.get("relationship_types")
            limit = int(body.get("limit", 100))
            return 200, expand_node(element_id, depth, direction, rel_types, limit)

        if path.startswith("/graph/node/"):
            element_id = path.split("/graph/node/")[1]
            properties = body.get("properties", {})
            data = update_node(element_id, properties)
            if data is None:
                return 404, {"error": f"Node not found: {element_id}"}
            return 200, data

        if path.startswith("/graph/relationship/"):
            element_id = path.split("/graph/relationship/")[1]
            properties = body.get("properties", {})
            data = update_relationship(element_id, properties)
            if data is None:
                return 404, {"error": f"Relationship not found: {element_id}"}
            return 200, data

        return 404, {"error": f"Unknown graph endpoint: POST {path}"}
    except (ValueError, ConnectionError, RuntimeError) as exc:
        return _err(exc)


def handle_graph_delete(parsed_path: str) -> tuple:
    """Route all DELETE /graph/* requests.

    Returns a ``(status, data)`` tuple.
    """
    path = parsed_path
    try:
        if path.startswith("/graph/node/"):
            element_id = path.split("/graph/node/")[1]
            deleted = delete_node(element_id)
            if not deleted:
                return 404, {"error": f"Node not found: {element_id}"}
            return 200, {"deleted": True}

        if path.startswith("/graph/relationship/"):
            element_id = path.split("/graph/relationship/")[1]
            deleted = delete_relationship(element_id)
            if not deleted:
                return 404, {"error": f"Relationship not found: {element_id}"}
            return 200, {"deleted": True}

        return 404, {"error": f"Unknown graph endpoint: DELETE {path}"}
    except (ValueError, ConnectionError, RuntimeError) as exc:
        return _err(exc)
