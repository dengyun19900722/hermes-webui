"""图库路由层（瘦壳）。

所有业务逻辑在 graph_store / graph_neo4j / graph_mock。本模块只做：
  1. 启动时选 backend（Neo4j 优先，失败降级 Mock）
  2. 解析 HTTP 请求路径 / 参数
  3. 分发到 store 实例
  4. 统一返回 {ok, data} 或 {ok: False, error} 包装层
"""
from __future__ import annotations
import datetime
import json
import logging
import os
from typing import Any

from api.config import DEFAULT_WORKSPACE
from api.graph_dict import get_manager as get_dict_manager

logger = logging.getLogger(__name__)


class _GraphEncoder(json.JSONEncoder):
    """处理 Neo4j 节点里的 datetime / date / time 等非 JSON 原生类型。"""
    def default(self, obj):
        if isinstance(obj, (datetime.datetime, datetime.date, datetime.time)):
            return obj.isoformat()
        try:
            import neo4j.time
            if isinstance(obj, (neo4j.time.DateTime, neo4j.time.Date,
                                neo4j.time.Time, neo4j.time.Duration)):
                return obj.isoformat()
        except ImportError:
            pass
        return super().default(obj)

_store: Any = None
_store_tried = False


def _wrap(payload: Any) -> dict:
    """统一包装层：{ok, data}。若 handler 已返回包装格式则透传。"""
    if (
        isinstance(payload, dict)
        and "ok" in payload
        and ("data" in payload or "error" in payload)
    ):
        return payload
    return {"ok": True, "data": payload}


def _err(msg: str, status: int = 400) -> tuple[int, dict]:
    return status, {"ok": False, "error": msg}


def get_store():
    """单例懒加载。优先 Neo4j，失败降级 Mock。"""
    global _store, _store_tried
    if _store is not None:
        return _store
    if _store_tried and _store is None:
        return None
    _store_tried = True
    try:
        from api.graph_neo4j import Neo4jStore
        s = Neo4jStore()
        h = s.health()
        if h.get("ok"):
            logger.info("Graph store: Neo4j (%s)", h.get("detail"))
            _store = s
            return _store
        else:
            logger.warning("Neo4j not usable (%s), falling back to Mock", h.get("detail"))
    except Exception as e:
        logger.warning("Neo4j import/init failed (%s), falling back to Mock", e)
    from api.graph_mock import MockStore
    db_path = os.environ.get(
        "GRAPH_MOCK_DB", str(DEFAULT_WORKSPACE / ".graph" / "graph.sqlite")
    )
    _store = MockStore(db_path=db_path)
    h = _store.health()
    logger.warning(
        "Graph store: MOCK (%s) — set NEO4J_PASSWORD to enable Neo4j backend",
        h.get("detail"),
    )
    return _store


# ── HTTP handlers ────────────────────────────────────────────────────────────


def _read_body(handler) -> dict:
    """从 BaseHTTPRequestHandler 读 JSON body。无 body 返回 {}。"""
    try:
        length = int(handler.headers.get("Content-Length", 0) or 0)
    except (TypeError, ValueError):
        length = 0
    if length <= 0:
        return {}
    try:
        import json
        raw = handler.rfile.read(length).decode("utf-8") if hasattr(handler, "rfile") else ""
        return json.loads(raw) if raw else {}
    except Exception:
        return {}


def _dispatch_response(handler, status: int, payload: dict) -> bool:
    """统一写响应。返回 True 让 routes.py 继续。"""
    import time as _dt
    _d0 = _dt.time()
    try:
        # 先序列化 body 拿到长度，再设 Content-Length 头。
        # 缺 Content-Length 时 HTTP/1.1 keep-alive 下 curl 不知道
        # 响应已结束，会在 socket 上 等几十秒直到超时。
        body = json.dumps(payload, ensure_ascii=False, cls=_GraphEncoder).encode("utf-8")
        _d1 = _dt.time()
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json; charset=utf-8")
        handler.send_header("Content-Length", str(len(body)))
        handler.end_headers()
        _d2 = _dt.time()
        handler.wfile.write(body)
        _d3 = _dt.time()
        logging.getLogger(__name__).warning(
            "[graph-dispatch] json=%.0fms headers=%.0fms write=%.0fms size=%d",
            (_d1-_d0)*1000, (_d2-_d1)*1000, (_d3-_d2)*1000, len(body))
    except Exception as exc:
        logging.getLogger(__name__).warning(
            "[graph-dispatch] write failed: %s", exc)
        # 能发错误响应的尽量发，不要沉默（否则 curl 空等到超时）
        try:
            err_body = json.dumps(
                {"ok": False, "error": str(exc)}, cls=_GraphEncoder).encode("utf-8")
            handler.send_response(status)
            handler.send_header("Content-Type", "application/json; charset=utf-8")
            handler.send_header("Content-Length", str(len(err_body)))
            handler.end_headers()
            handler.wfile.write(err_body)
        except Exception:
            pass
    return True


def handle_graph_get(method: str, parsed_path: str, query_params: dict) -> tuple[int, dict]:
    path = parsed_path
    store = get_store()
    if store is None:
        return _err("graph store unavailable", 503)
    try:
        if path == "/graph/health":
            return 200, _wrap(store.health())
        if path == "/graph/schema":
            return 200, _wrap(store.schema())
        if path == "/graph/search":
            q = (query_params.get("q") or "").strip()
            if not q:
                return _err("q parameter required", 400)
            label = query_params.get("label") or None
            limit = int(query_params.get("limit", 50))
            return 200, _wrap(store.search(q, label, limit))
        if path == "/graph/nodes":
            label = (query_params.get("label") or "").strip()
            limit = int(query_params.get("limit", 500))
            import time as _nt
            _nt0 = _nt.time()
            if label:
                data = store.list_nodes(label, limit)
            else:
                data = store.list_all_nodes(limit)
            _nt1 = _nt.time()
            payload = _wrap(data)
            _nt2 = _nt.time()
            logging.getLogger(__name__).warning(
                "[graph-nodes] query=%.0fms wrap=%.0fms count=%s",
                (_nt1-_nt0)*1000, (_nt2-_nt1)*1000,
                data.get("count", "?"))
            return 200, payload
        if path.startswith("/graph/node/"):
            eid = path[len("/graph/node/"):]
            n = store.get_node(eid)
            if not n:
                return _err(f"node not found: {eid}", 404)
            return 200, _wrap(n)
        if path.startswith("/graph/relationship/"):
            eid = path[len("/graph/relationship/"):]
            r = store.get_relationship(eid)
            if not r:
                return _err(f"relationship not found: {eid}", 404)
            return 200, _wrap(r)
        if path.startswith("/graph/relationships/"):
            eid = path[len("/graph/relationships/"):]
            direction = query_params.get("direction", "both")
            return 200, _wrap({"results": store.list_relationships(eid, direction)})
        if path == "/graph/relationships":
            limit = int(query_params.get("limit", 500))
            return 200, _wrap({"results": store.list_all_relationships(limit)})
        if path.startswith("/graph/topology/"):
            eid = path[len("/graph/topology/"):]
            # 前端可能用 encodeURIComponent 编码了冒号等字符，需解码
            from urllib.parse import unquote
            eid = unquote(eid)
            try:
                depth = int(query_params.get("depth", 3))
            except (TypeError, ValueError):
                depth = 3
            direction = query_params.get("direction", "both")
            if direction not in ("in", "out", "both"):
                direction = "both"
            return 200, _wrap(store.topology(eid, depth, direction))
        # ── 字典路由 ──
        if path == "/graph/dictionary/apply":
            return 200, _wrap(get_dict_manager().get_apply_mappings())
        if path == "/graph/dictionary/stats":
            return 200, _wrap(get_dict_manager().stats())
        if path == "/graph/dictionary/export":
            fmt = query_params.get("format", "json")
            cat = query_params.get("category") or None
            mgr = get_dict_manager()
            if fmt == "yaml":
                body = mgr.export_yaml(cat)
            else:
                body = mgr.export_json(cat)
            return 200, {"ok": True, "data": body, "format": fmt}
        if path == "/graph/dictionary":
            cat = query_params.get("category") or None
            q = query_params.get("q") or None
            page = int(query_params.get("page", 1))
            size = int(query_params.get("size", 50))
            return 200, _wrap(get_dict_manager().list_items(cat, q, page, size))
        if path.startswith("/graph/dictionary/"):
            item_id = path[len("/graph/dictionary/"):]
            item = get_dict_manager().get_item(item_id)
            if not item:
                return _err(f"字典条目不存在: {item_id}", 404)
            return 200, _wrap(item)
        return _err(f"unknown GET path: {path}", 404)
    except (ValueError, RuntimeError) as e:
        status = 400 if isinstance(e, ValueError) else 503
        return _err(str(e), status)
    except Exception as e:
        logger.exception("GET handler error")
        return _err(f"internal error: {e}", 500)


def handle_graph_post(method: str, parsed_path: str, body: dict) -> tuple[int, dict]:
    path = parsed_path
    store = get_store()
    if store is None:
        return _err("graph store unavailable", 503)
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
        # ── 字典 POST 路由 ──
        if path == "/graph/dictionary":
            return 200, _wrap(get_dict_manager().create_item(body))
        if path == "/graph/dictionary/import":
            fmt = (body.get("format") or "json").lower()
            content = body.get("content", "")
            mgr = get_dict_manager()
            if fmt == "csv":
                result = mgr.import_csv(content)
            else:
                result = mgr.import_json(content)
            status = 200 if result.get("ok") else 400
            return status, result
        return _err(f"unknown POST path: {path}", 404)
    except (ValueError, RuntimeError) as e:
        status = 400 if isinstance(e, ValueError) else 503
        return _err(str(e), status)
    except Exception as e:
        logger.exception("POST handler error")
        return _err(f"internal error: {e}", 500)


def handle_graph_delete(method: str, parsed_path: str) -> tuple[int, dict]:
    path = parsed_path
    store = get_store()
    if store is None:
        return _err("graph store unavailable", 503)
    try:
        if path.startswith("/graph/node/"):
            eid = path[len("/graph/node/"):]
            return 200, _wrap(store.delete_node(eid))
        if path.startswith("/graph/relationship/"):
            eid = path[len("/graph/relationship/"):]
            return 200, _wrap(store.delete_relationship(eid))
        # ── 字典 DELETE 路由 ──
        if path.startswith("/graph/dictionary/"):
            item_id = path[len("/graph/dictionary/"):]
            if get_dict_manager().delete_item(item_id):
                return 200, _wrap({"deleted": True})
            return _err(f"字典条目不存在: {item_id}", 404)
        return _err(f"unknown DELETE path: {path}", 404)
    except (ValueError, RuntimeError) as e:
        status = 400 if isinstance(e, ValueError) else 503
        return _err(str(e), status)
    except Exception as e:
        logger.exception("DELETE handler error")
        return _err(f"internal error: {e}", 500)


def handle_graph_patch(method: str, parsed_path: str, body: dict) -> tuple[int, dict]:
    path = parsed_path
    store = get_store()
    if store is None:
        return _err("graph store unavailable", 503)
    try:
        if path.startswith("/graph/node/"):
            eid = unquote(path[len("/graph/node/"):])
            return 200, _wrap(store.update_node(eid, body.get("properties", {})))
        # ── 字典 PATCH 路由 ──
        if path.startswith("/graph/dictionary/"):
            rest = path[len("/graph/dictionary/"):]
            if rest.endswith("/toggle"):
                item_id = rest[:-7]
                toggled = get_dict_manager().toggle_item(item_id)
                if not toggled:
                    return _err(f"字典条目不存在: {item_id}", 404)
                return 200, _wrap(toggled)
            else:
                item_id = rest
                updated = get_dict_manager().update_item(item_id, body)
                if not updated:
                    return _err(f"字典条目不存在: {item_id}", 404)
                return 200, _wrap(updated)
        return _err(f"unknown PATCH path: {path}", 404)
    except (ValueError, RuntimeError) as e:
        status = 400 if isinstance(e, ValueError) else 503
        return _err(str(e), status)
    except Exception as e:
        logger.exception("PATCH handler error")
        return _err(f"internal error: {e}", 500)


# ── Compatibility shims for routes.py ────────────────────────────────────────
# routes.py 调用 handle_graph_*(handler, parsed) 旧接口。
# 这里把旧调用转发到新的 tuple 返回 API，并直接写响应。

from urllib.parse import parse_qs


def _strip_api_prefix(path: str) -> str:
    """去掉 /api 前缀，返回 /graph/..."""
    if path.startswith("/api"):
        return path[4:]
    return path


def _handle_get_legacy(handler, parsed) -> bool:
    from urllib.parse import urlsplit
    raw = parsed.path if hasattr(parsed, "path") else urlsplit(parsed).path
    parsed_path = _strip_api_prefix(raw)
    qs = parse_qs(getattr(parsed, "query", "") or "")
    query_params = {k: v[0] if len(v) == 1 else v for k, v in qs.items()}
    method = getattr(handler, "command", "GET")
    status, payload = handle_graph_get(method, parsed_path, query_params)
    if status == 404 and payload.get("error", "").startswith("unknown GET path"):
        return False
    _dispatch_response(handler, status, payload)
    return True


def _handle_post_legacy(handler, parsed, body=None) -> bool:
    from urllib.parse import urlsplit
    raw = parsed.path if hasattr(parsed, "path") else urlsplit(parsed).path
    parsed_path = _strip_api_prefix(raw)
    # routes.py 的 handle_post 已经 read_body 并可能传入；否则这里再读一次。
    if body is None:
        body = _read_body(handler)
    method = getattr(handler, "command", "POST")
    status, payload = handle_graph_post(method, parsed_path, body)
    if status == 404 and payload.get("error", "").startswith("unknown POST path"):
        return False
    _dispatch_response(handler, status, payload)
    return True


def _handle_delete_legacy(handler, parsed) -> bool:
    from urllib.parse import urlsplit
    raw = parsed.path if hasattr(parsed, "path") else urlsplit(parsed).path
    parsed_path = _strip_api_prefix(raw)
    method = getattr(handler, "command", "DELETE")
    status, payload = handle_graph_delete(method, parsed_path)
    if status == 404 and payload.get("error", "").startswith("unknown DELETE path"):
        return False
    _dispatch_response(handler, status, payload)
    return True


def _handle_patch_legacy(handler, parsed, body=None) -> bool:
    from urllib.parse import urlsplit
    raw = parsed.path if hasattr(parsed, "path") else urlsplit(parsed).path
    parsed_path = _strip_api_prefix(raw)
    if body is None:
        body = _read_body(handler)
    method = getattr(handler, "command", "PATCH")
    status, payload = handle_graph_patch(method, parsed_path, body)
    if status == 404 and payload.get("error", "").startswith("unknown PATCH path"):
        return False
    _dispatch_response(handler, status, payload)
    return True


# 把旧接口名指向 legacy shim，routes.py 不需要改
# 但单元测试用的新 API 仍可访问（用新名字：handle_graph_get_v2 / post / delete）
handle_graph_get_v2 = handle_graph_get
handle_graph_post_v2 = handle_graph_post
handle_graph_delete_v2 = handle_graph_delete
handle_graph_patch_v2 = handle_graph_patch


# HTTP 入口（routes.py 用这些名字）：接受 (handler, parsed)，写响应，返回 False 让 routes.py 走 404
def handle_graph_http_get(handler, parsed):
    return _handle_get_legacy(handler, parsed)


def handle_graph_http_post(handler, parsed, body=None):
    return _handle_post_legacy(handler, parsed, body)


def handle_graph_http_delete(handler, parsed):
    return _handle_delete_legacy(handler, parsed)


def handle_graph_http_patch(handler, parsed, body=None):
    return _handle_patch_legacy(handler, parsed, body)


# ── 预初始化 ────────────────────────────────────────────────────────────
# 当 routes.py 首次 from api.graph import ... 时，立即初始化 store（而非
# 等到第一个请求才懒加载）。消除首次请求的 2-3s Neo4j 连接握手开销。
get_store()
# 字典管理器同样预初始化（创建 DEFAULT_WORKSPACE/.graph/graph_dict.json 并 seed 内置条目）
get_dict_manager()
