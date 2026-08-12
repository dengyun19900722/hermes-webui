"""
Hermes Web UI -- 引导中心（实施助手 2.1）http.server 风格路由。

项目主服务基于 http.server(BaseHTTPRequestHandler)，非 Flask。
原 api/routes.py:register_guidance_routes() 是 Flask 风格实现，无法接入
handle_get/handle_post 等分发函数。本模块提供等价功能的 http.server 实现：

    GET    /api/guidance/implementation                          → 全量状态
    GET    /api/guidance/implementation/report                   → Markdown 报告下载
    PATCH  /api/guidance/implementation/<task_id>                → 标记任务完成
    POST   /api/guidance/implementation/<task_id>/note           → 更新备注
    POST   /api/guidance/implementation/import-business-entities → CSV 导入
    DELETE /api/guidance/implementation                          → 重置进度

所有端点要求 role ∈ {admin, ops}，否则 403。

注意：handle_post / handle_patch 已统一调用 read_body() 读取请求体，
因此 PATCH / POST(note) handler 必须复用传入的 body，不能再次
handler.rfile.read()（第二次读取会阻塞到 keep-alive 超时）。CSV 导入
走 multipart，必须在 handle_post 的 read_body() 之前拦截，由本模块
自行解析 multipart（否则 rfile 已被消费）。
"""

import logging
from datetime import datetime

from api import guidance_progress as _gp
from api.helpers import bad, j

logger = logging.getLogger("webui.guidance")

# 路由前缀
_GUIDANCE_BASE = "/api/guidance/implementation"
_REPORT_PATH = _GUIDANCE_BASE + "/report"
_TEMPLATE_PATH = _GUIDANCE_BASE + "/template"
_ENTITY_DOC_PATH = _GUIDANCE_BASE + "/entity-doc"
_IMPORT_PATH = _GUIDANCE_BASE + "/import-business-entities"
_IMPORT_KB_PATH = _GUIDANCE_BASE + "/import-knowledge"
_VERIFY_PATH = _GUIDANCE_BASE + "/verify"
_CHECK_PATH = _GUIDANCE_BASE + "/check"

# vault 中固定文档：实施助手 1.1 填表说明。用户可在知识库面板里编辑它。
_ENTITY_DOC_REL_PATH = "01-故障知识库/实施指南/实体关系表填写说明.md"

# 文档初始内容（仅在 vault 中不存在时创建）。
_ENTITY_DOC_INITIAL = """# Neo4j 实体关系表填写说明

面向实施助手 1.1 步骤。本文档基于 Neo4j 导入模板（neo4j_import_template-202606.xlsx），
定义了统一的 5 列 CSV 格式：实体与关系放在同一张表，通过字段填充区分。

## 列定义（必填 5 列）

| from_label | from_name | properties | to_label | to_name |
| ---------- | --------- | ---------- | -------- | ------ |
| 起点标签 | 起点唯一标识 | JSON 属性（见下） | 终点标签（实体行留空） | 终点唯一标识 |

- 实体行：to_label 和 to_name 留空，1-3 列有值
- 关系行：5 列都填，rel_type 写在 properties 字段里

## 实体（Entity）

实体类型通过 `from_label` 字段定义，每个实体必须全局唯一（`from_label + from_name` 联合唯一）。

### 常用实体标签

| label | 用途 | name 字段约定 |
| ----- | ---- | -------------- |
| `Host` | 主机/服务器 | IP 地址，如 `12.7.0.12` |
| `Service` | 服务/组件 | 服务名，如 `commander`、`wxsshd` |
| `Program` | 程序/进程 | 程序名，如 `PKTCMD`、`bckproc` |
| `Api` | 接口端点 | API 路径，如 `/v1/pay` |
| `Middleware` | 中间件（MySQL/Redis 等） | 类型名，如 `MySQL`、`Redis` |
| `Room` | 机房 | 机房编号 |
| `Cabinet` | 机柜 | 机柜编号 |

> Middleware 是独立实体类型，用于描述服务依赖的中间件实例；服务通过
> `DEPENDS_ON` 关系指向它（见下文关系类型）。

### 实体 properties（JSON 字符串）

```json
{
  "busi_name": "支付线",
  "log_type": "host",
  "log_path": "/usr/log/commander/let.log",
  "let_type": "防火墙",
  "let_typename": "dd"
}
```

`busi_name`（业务线）是 Host 实体 properties 里的属性，用于资产按业务线分组。
Host 实体的 properties 建议包含 `busi_name`，否则资产无法归入业务线。

### 实体示例

```
Host,12.7.0.11,{"ssh_port":22,"ssh_user":"root","busi_name":"支付线"},,
Host,12.7.0.12,{"ssh_port":22,"ssh_user":"root","busi_name":"支付线"},,
Service,commander,{"rel_type":"host","log_path":"/usr/log/commander/"},,
Program,wxsshd,{"rel_type":"host","log_path":"/usr/log/wxsshd/"},,
Program,bckproc,{"rel_type":"host","log_path":"/usr/log/bckproc/"},,
```

## 关系（Relationship）

关系通过 5 列都填来表达：`rel_type` 写在 `properties` 字段里。

### 常用关系类型

| rel_type | 含义 | 起点 → 终点 |
| -------- | ---- | ------------- |
| `HAS_CABINET` | 机房拥有 | Room → Cabinet |
| `HAS_HOST` | 机柜拥有主机 | Cabinet → Host |
| `RUN_SERVICE` | 主机运行服务 | Host → Service |
| `DEPLOY` | 部署 | Service → Host |
| `DEPEND_ON` | 依赖 | Service/Program → Service/Program |
| `HAS_API` | 服务暴露 API | Service → Api |
| `CALLS` | API 调用 | Api → Api |
| `DEPENDS_ON` | 服务依赖中间件 | Service → Middleware |

### 关系示例

```
Service,commander,{"rel_type":"DEPLOY_ON"},Host,12.7.0.11
Service,commander,{"rel_type":"DEPLOY_ON"},Host,12.7.0.12
Service,commander,{"rel_type":"DEPLOY_ON"},Host,12.7.0.13
Service,bckproc,{"rel_type":"DPEND_ON"},Program,cws
Service,commander,{"rel_type":"DEPENDS_ON"},Middleware,Mysql
```

## 填写规则

1. **`from_label + from_name` 必须全局唯一**，唯一标识一个实体
2. 实体行 4-5 列（to_label/to_name）必须留空
3. 关系行 1-5 列都填，`rel_type` 写在 properties 里
4. `properties` 必须是合法 JSON 字符串（双引号、逗号）
5. JSON 中的特殊字符（双引号、换行）需用 `\\"` 转义
6. 空行或 `#` 开头的行会被忽略（用于注释）
7. 上传前可点击"⬇ 下载模板"获取标准模板

## 注意事项

- 该文档可直接编辑；前端填写说明与本文件保持一致
- 实际导入由前端 1.3 步骤的上传按钮触发
- 导入后会自动验证库存中的数据（verify 步骤）
"""


def _current_user(handler) -> dict | None:
    """返回当前 RBAC 用户 dict；无登录返回 None。"""
    try:
        from api.auth import get_user_from_session, parse_cookie
        token = parse_cookie(handler)
        return get_user_from_session(token) if token else None
    except Exception:
        return None


def _current_username(handler) -> str:
    user = _current_user(handler)
    if not user:
        return "unknown"
    return str(user.get("username") or user.get("id") or "unknown")


def _require_admin_or_ops(handler):
    """检查当前用户角色 ∈ {admin, ops}，失败返回错误响应。"""
    user = _current_user(handler)
    if not user:
        return bad(handler, "Authentication required", status=401)
    if user.get("role") not in ("admin", "ops"):
        return bad(handler, "Requires admin or ops role", status=403)
    return None


def _serve_template(handler) -> bool:
    """GET /api/guidance/implementation/template → 下载 3-sheet xlsx 模板。

    基于 Neo4j 导入模板（neo4j_import_template-202606.xlsx）：
    - 实体页（label, name, properties, busi_name）
    - 关系页（from_label, from_name, rel_type, to_label, to_name, properties）
    - 填写说明（说明文档）
    """
    try:
        from api.guidance_xlsx import generate_template_xlsx
        encoded = generate_template_xlsx()
    except Exception as e:
        logger.warning("generate xlsx template failed: %s", e)
        return bad(handler, "template_generation_failed", status=500)

    filename = "neo4j_import_template.xlsx"
    handler.send_response(200)
    handler.send_header(
        "Content-Type",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    handler.send_header("Content-Length", str(len(encoded)))
    handler.send_header(
        "Content-Disposition",
        f"attachment; filename*=UTF-8''{filename}",
    )
    handler.send_header("Cache-Control", "no-cache")
    handler.end_headers()
    handler.wfile.write(encoded)
    return True


def _get_or_create_entity_doc() -> dict:
    """Get or create the fixed entity-doc in vault."""
    from api.obsidian_notes import vault_root, read_note

    vault = vault_root(create=True)
    doc_path = vault / _ENTITY_DOC_REL_PATH
    if not doc_path.exists():
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        doc_path.write_text(_ENTITY_DOC_INITIAL, encoding="utf-8")

    payload = read_note(_ENTITY_DOC_REL_PATH)
    return {
        "ok": True,
        "path": _ENTITY_DOC_REL_PATH,
        "title": payload.get("title", "doc"),
        "content": payload.get("content", ""),
        "rendered_html": payload.get("rendered_html", ""),
    }


def handle_guidance_get(handler, parsed) -> bool:
    """GET /api/guidance/implementation, /report, /template, /entity-doc."""
    path = parsed.path
    if path not in (_GUIDANCE_BASE, _REPORT_PATH, _TEMPLATE_PATH, _ENTITY_DOC_PATH):
        return False

    denied = _require_admin_or_ops(handler)
    if denied is not None:
        return True

    if path == _TEMPLATE_PATH:
        return _serve_template(handler)

    if path == _ENTITY_DOC_PATH:
        try:
            return j(handler, _get_or_create_entity_doc())
        except Exception as e:
            logger.warning("entity-doc read failed: %s", e)
            return j(handler, {"ok": False, "error": "read_failed", "detail": str(e)}, status=500)

    if path == _REPORT_PATH:
        md = _gp.render_report()
        encoded = md.encode("utf-8")
        filename = f"implementation-report-{datetime.now().strftime('%Y%m%d')}.md"
        handler.send_response(200)
        handler.send_header("Content-Type", "text/markdown; charset=utf-8")
        handler.send_header("Content-Length", str(len(encoded)))
        handler.send_header(
            "Content-Disposition",
            f"attachment; filename*=UTF-8''{filename}",
        )
        handler.send_header("Cache-Control", "no-cache")
        handler.end_headers()
        handler.wfile.write(encoded)
        return True

    return j(handler, _gp.get_full_state(current_user=_current_username(handler)))


def handle_guidance_patch(handler, parsed, body) -> bool:
    """PATCH /api/guidance/implementation/<task_id> → mark_task(done)。

    body 由 handle_patch 的 read_body() 统一解析后传入，此处不得再读 rfile。
    """
    path = parsed.path
    if not path.startswith(_GUIDANCE_BASE + "/"):
        return False
    if path.startswith(_GUIDANCE_BASE + "/") and path.endswith("/note"):
        return False  # note 走 POST，不在 PATCH 处理
    task_id = path[len(_GUIDANCE_BASE + "/"):].strip("/")
    if not task_id:
        return False

    denied = _require_admin_or_ops(handler)
    if denied is not None:
        return True

    body = body or {}
    try:
        task = _gp.mark_task(
            task_id,
            done=bool(body.get("done", False)),
            by=_current_username(handler),
            note=body.get("note"),
        )
    except ValueError as e:
        msg = str(e)
        if msg == "manual_note_required":
            return j(
                handler,
                {
                    "error": "manual_note_required",
                    "task_id": task_id,
                    "detail": "该步骤需手动标记，请填写备注原因（自动验证未通过）。",
                },
                status=400,
            )
        return j(
            handler,
            {"error": "unknown_task", "task_id": task_id, "detail": msg},
            status=400,
        )
    return j(handler, {"ok": True, "task": task})


def handle_guidance_post(handler, parsed, body=None) -> bool:
    """POST /api/guidance/implementation/<task_id>/note 及 CSV 导入。

    必须在 handle_post 的 read_body() 之前调用本函数：
      - <task_id>/note 由本函数自己 read_body（rfile 未被消费）
      - import-business-entities 由本函数自己解析 multipart
    """
    path = parsed.path

    # 以下 multipart 路由必须在任何 read_body 之前处理（需要原始 rfile）
    if path == _IMPORT_PATH:
        denied = _require_admin_or_ops(handler)
        if denied is not None:
            return True
        return _handle_import_csv(handler)

    if path == _IMPORT_KB_PATH:
        denied = _require_admin_or_ops(handler)
        if denied is not None:
            return True
        return _handle_import_knowledge(handler)

    # JSON body 路由：verify / check / note
    if path == _VERIFY_PATH:
        denied = _require_admin_or_ops(handler)
        if denied is not None:
            return True
        if body is None:
            from api.helpers import read_body
            body = read_body(handler)
        body = body or {}
        task_id = str(body.get("task_id", "")).strip()
        query = body.get("query")
        try:
            if query is not None:
                result = _gp.run_verification(task_id, by=_current_username(handler), query=query)
            else:
                result = _gp.run_verification(task_id, by=_current_username(handler))
        except ValueError as e:
            return j(
                handler,
                {"error": "unknown_task", "task_id": task_id, "detail": str(e)},
                status=400,
            )
        return j(handler, result)

    if path == _CHECK_PATH:
        denied = _require_admin_or_ops(handler)
        if denied is not None:
            return True
        if body is None:
            from api.helpers import read_body
            body = read_body(handler)
        body = body or {}
        task_id = str(body.get("task_id", "")).strip()
        try:
            result = _gp.check_task(task_id)
        except ValueError as e:
            return j(
                handler,
                {"error": "unknown_task", "task_id": task_id, "detail": str(e)},
                status=400,
            )
        return j(handler, result)

    if not path.startswith(_GUIDANCE_BASE + "/") or not path.endswith("/note"):
        return False
    task_id = path[len(_GUIDANCE_BASE + "/"):-len("/note")].strip("/")
    if not task_id:
        return False

    denied = _require_admin_or_ops(handler)
    if denied is not None:
        return True

    if body is None:
        from api.helpers import read_body
        body = read_body(handler)
    body = body or {}
    note = body.get("note", "")
    try:
        task = _gp.update_note(task_id, note=note)
    except ValueError as e:
        return j(
            handler,
            {"error": "unknown_task", "task_id": task_id, "detail": str(e)},
            status=400,
        )
    return j(handler, {"ok": True, "task": task})


def _handle_import_csv(handler) -> bool:
    """解析 multipart 中的 file 字段并导入业务实体。

    支持两种格式：
    - .xlsx（推荐）：3-sheet 模板（实体页/关系页/填写说明）
    - .csv：5 列格式（from_label,from_name,properties,to_label,to_name）
    """
    content_type = handler.headers.get("Content-Type", "")
    content_length = handler.headers.get("Content-Length", "0")
    try:
        length = int(content_length)
    except (TypeError, ValueError):
        return bad(handler, "Invalid Content-Length", status=400)
    if length <= 0:
        return bad(handler, "no_file", status=400)

    try:
        from api.upload import parse_multipart
        fields, files = parse_multipart(handler.rfile, content_type, content_length)
    except ValueError as e:
        return bad(handler, str(e), status=400)
    except Exception as e:
        logger.debug("guidance import multipart parse failed: %s", e)
        return bad(handler, "invalid_upload", status=400)

    if "file" not in files:
        return bad(handler, "no_file", status=400)
    filename, file_bytes = files["file"]
    name = (filename or "upload.csv").lower()

    try:
        if name.endswith(".xlsx"):
            result = _gp.import_business_entities_xlsx(
                file_bytes,
                filename=filename or "upload.xlsx",
                by=_current_username(handler),
            )
        else:
            try:
                content = file_bytes.decode("utf-8")
            except UnicodeDecodeError:
                return bad(handler, "invalid_utf8", status=400)
            result = _gp.import_business_entities(
                content,
                filename=name or "upload.csv",
                by=_current_username(handler),
            )
    except Exception as e:
        logger.warning("guidance import failed: %s", e)
        return j(handler, {"ok": False, "error": "import_failed", "detail": str(e)}, status=400)

    if not result.get("ok"):
        return j(handler, result, status=400)
    return j(handler, result)


def _handle_import_knowledge(handler) -> bool:
    """POST /api/guidance/implementation/import-knowledge (multipart archive).

    就地批量导入知识库（复用 /api/notes/import/batch 的导入管线）。导入成功后
    自动验证 2.2_batch_import（记录 last_check + mark_verified）。
    """
    content_type = handler.headers.get("Content-Type", "")
    content_length = handler.headers.get("Content-Length", "0")
    try:
        length = int(content_length)
    except (TypeError, ValueError):
        return bad(handler, "Invalid Content-Length", status=400)
    if length <= 0:
        return bad(handler, "no_file", status=400)

    try:
        from api.upload import parse_multipart
        fields, files = parse_multipart(handler.rfile, content_type, content_length)
    except ValueError as e:
        return bad(handler, str(e), status=400)
    except Exception as e:
        logger.debug("guidance knowledge import multipart parse failed: %s", e)
        return bad(handler, "invalid_upload", status=400)

    archive = files.get("archive") or files.get("file")
    if not archive:
        return bad(handler, "no_file", status=400)
    filename, file_bytes = archive

    try:
        from api.obsidian_notes import import_batch_archive, search_notes
        result = import_batch_archive(filename or "upload.zip", file_bytes)
    except Exception as e:
        logger.warning("guidance knowledge import failed: %s", e)
        return j(handler, {"ok": False, "error": "import_failed", "detail": str(e)}, status=400)

    # 防御性提取导入数量
    imported_count = 0
    if isinstance(result, dict):
        imported_count = (
            result.get("success_count")
            or result.get("imported_count")
            or len(result.get("imported", []))
            or 0
        )

    # 导入后做一次检索探测，确认知识库可检索（证据更可信）
    probe_evidence = ""
    try:
        probe = search_notes("故障")
        probe_count = len((probe or {}).get("results", []))
        probe_evidence = f"；检索“故障”命中 {probe_count} 条"
    except Exception:
        probe_evidence = ""

    evidence = f"批量导入完成（{imported_count} 篇）{probe_evidence}".strip()
    result = _gp.record_verification(
        "2.2_batch_import",
        by=_current_username(handler),
        passed=True,
        evidence=evidence,
    )
    result["import_result"] = imported_count
    return j(handler, result)


def handle_guidance_delete(handler, parsed) -> bool:
    """DELETE /api/guidance/implementation → reset_progress()。"""
    if parsed.path != _GUIDANCE_BASE:
        return False

    denied = _require_admin_or_ops(handler)
    if denied is not None:
        return True

    _gp.reset_progress()
    return j(handler, {"ok": True})
