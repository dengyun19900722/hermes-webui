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
            f"RETURN collect(DISTINCT n) AS nodes, collect(DISTINCT r) AS rels"
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
