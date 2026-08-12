"""实施助手多 sheet xlsx 模板生成与解析。

基于 Neo4j 导入模板（neo4j_import_template-202606.xlsx）约定 3 个 sheet：

- 实体页（entity / 实体）：label, name, properties
- 关系页（relation / 关系）：from_label, from_name, rel_type, to_label, to_name, properties
- 填写说明（help / 填写说明）：说明文档（可选）

实体/关系 sheet 兼容中英文表头，sheet 名兼容中英文。
"""
from __future__ import annotations

import io
import json
from typing import Any

# ── Sheet 名称（兼容中英文） ──────────────────────────────────────────────────
SHEET_ENTITY = "实体"      # 备用英文 "entity"
SHEET_RELATION = "关系"    # 备用英文 "relation"
SHEET_HELP = "填写说明"    # 备用英文 "help"


def _match_sheet(actual: str, names: tuple[str, ...]) -> bool:
    a = (actual or "").strip().lower()
    return any(a == n.lower() for n in names)


def generate_template_xlsx() -> bytes:
    """生成 3-sheet 的 xlsx 模板字节流。"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()

    # ── Sheet 1：实体页 ──
    ws = wb.active
    ws.title = SHEET_ENTITY
    header_fill = PatternFill("solid", fgColor="4472C4")
    header_font = Font(bold=True, color="FFFFFF")
    title_font = Font(bold=True, size=13)

    ws.append(["实体表（Entity）", "", "", ""])
    ws.merge_cells("A1:D1")
    ws["A1"].font = title_font
    ws.append([])
    cols = ["label", "name", "properties", "busi_name"]
    ws.append(cols)
    for cell in ws[3]:
        if cell.value:
            cell.fill = header_fill
            cell.font = header_font
    # 列宽
    ws.column_dimensions["A"].width = 14
    ws.column_dimensions["B"].width = 24
    ws.column_dimensions["C"].width = 46
    ws.column_dimensions["D"].width = 18
    # 示例数据（含 busi_name 示例）
    examples = [
        ["Host", "12.7.0.11", '{"ssh_port":22,"ssh_user":"root","busi_name":"支付线"}', ""],
        ["Host", "12.7.0.12", '{"ssh_port":22,"ssh_user":"root","busi_name":"支付线"}', ""],
        ["Service", "commander", '{"rel_type":"host","log_path":"/usr/log/commander/"}', ""],
        ["Program", "wxsshd", '{"rel_type":"host","log_path":"/usr/log/wxsshd/"}', ""],
    ]
    for row in examples:
        ws.append(row)
    ws.append([])
    ws.append(["说明", "label 必填，常用 Host/Service/Program/Api/Middleware/Room/Cabinet；"
               "name 为唯一标识；properties 为 JSON；busi_name 标注业务线（建议放 properties 内）", "", ""])
    ws.merge_cells("A12:D12")
    ws["A12"].font = Font(italic=True, color="808080")

    # ── Sheet 2：关系页 ──
    ws2 = wb.create_sheet(SHEET_RELATION)
    ws2.append(["关系表（Relationship）", "", "", "", "", ""])
    ws2.merge_cells("A1:F1")
    ws2["A1"].font = title_font
    ws2.append([])
    rel_cols = ["from_label", "from_name", "rel_type", "to_label", "to_name", "properties"]
    ws2.append(rel_cols)
    for cell in ws2[3]:
        if cell.value:
            cell.fill = header_fill
            cell.font = header_font
    for col, w in zip("ABCDEF", [14, 24, 14, 14, 24, 46]):
        ws2.column_dimensions[col].width = w
    rel_examples = [
        ["Service", "commander", "DEPLOY_ON", "Host", "12.7.0.11", '{"log_path":"/usr/log/commander/"}'],
        ["Service", "commander", "DEPLOY_ON", "Host", "12.7.0.12", ""],
        ["Service", "bckproc", "DEPEND_ON", "Program", "cws", ""],
        ["Service", "commander", "DEPENDS_ON", "Middleware", "Mysql", ""],
        ["Host", "12.7.0.11", "RUN_SERVICE", "Service", "commander", ""],
    ]
    for row in rel_examples:
        ws2.append(row)
    ws2.append([])
    ws2.append(["说明", "rel_type 常用 DEPLOY_ON / DEPEND_ON / DEPENDS_ON / RUN_SERVICE / HAS_CABINET / HAS_HOST / HAS_API / CALLS；"
               "服务依赖中间件用 DEPENDS_ON（Service → Middleware）", "", "", "", ""])
    ws2.merge_cells("A13:F13")
    ws2["A13"].font = Font(italic=True, color="808080")

    # ── Sheet 3：填写说明 ──
    ws3 = wb.create_sheet(SHEET_HELP)
    ws3.append(["填写说明", "", ""])
    ws3.merge_cells("A1:C1")
    ws3["A1"].font = title_font
    help_lines = [
        ["1. 实体页：", "每行一个实体，label 表示类型，name 为唯一标识（label+name 联合唯一）。"],
        ["", "properties 为 JSON 字符串；Host 用 busi_name 标注业务线。"],
        ["2. 关系页：", "每行一个关系，from_* 为起点，rel_type 为关系类型，to_* 为终点。"],
        ["", "properties 可含关系属性。"],
        ["3. 常用 label：", "Host, Service, Program, Api, Middleware, Room, Cabinet"],
        ["", "Middleware 为中间件（MySQL/Redis 等），name 用类型名，如 Mysql"],
        ["4. 常用 rel_type：", "DEPLOY_ON, DEPEND_ON, DEPENDS_ON, RUN_SERVICE, HAS_CABINET, HAS_HOST, HAS_API, CALLS"],
        ["", "服务依赖中间件：Service → Middleware，rel_type 用 DEPENDS_ON"],
        ["5. 上传：", "选择本文件，系统校验并导入，成功后自动验证。"],
    ]
    for row in help_lines:
        ws3.append(row)
    for col, w in zip("ABC", [16, 60, 10]):
        ws3.column_dimensions[col].width = w
    for row_idx in range(3, 3 + len(help_lines)):
        ws3[f"A{row_idx}"].font = Font(bold=True)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def parse_template_xlsx(raw: bytes) -> dict[str, Any]:
    """解析 3-sheet xlsx，返回 {entity_rows, relation_rows, help_text}。

    entity_rows: list of {label, name, properties(dict), busi_name}
    relation_rows: list of {from_label, from_name, rel_type, to_label, to_name, properties(dict)}
    help_text: str
    """
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(raw), data_only=True, read_only=True)

    entity_rows: list[dict[str, Any]] = []
    relation_rows: list[dict[str, Any]] = []
    help_text = ""

    for sheet in wb.worksheets:
        title = sheet.title or ""
        if _match_sheet(title, (SHEET_ENTITY, "entity", "实体", "entities")):
            entity_rows = _parse_entity_sheet(sheet)
        elif _match_sheet(title, (SHEET_RELATION, "relation", "关系", "relations")):
            relation_rows = _parse_relation_sheet(sheet)
        elif _match_sheet(title, (SHEET_HELP, "help", "填写说明", "说明")):
            help_text = _parse_help_sheet(sheet)

    wb.close()
    return {
        "entity_rows": entity_rows,
        "relation_rows": relation_rows,
        "help_text": help_text,
    }


def _normalize_headers(headers: list[str]) -> list[str]:
    """把中英文表头归一化为小写英文键名。"""
    mapping = {
        "label": "label", "实体": "label", "实体类型": "label",
        "name": "name", "名称": "name", "实体名": "name",
        "properties": "properties", "属性": "properties", "props": "properties",
        "from_label": "from_label", "起点标签": "from_label",
        "from_name": "from_name", "起点名称": "from_name",
        "rel_type": "rel_type", "关系类型": "rel_type",
        "to_label": "to_label", "终点标签": "to_label",
        "to_name": "to_name", "终点名称": "to_name",
        "busi_name": "busi_name", "业务线": "busi_name", "业务线名称": "busi_name",
    }
    result = []
    for h in headers:
        key = mapping.get(str(h or "").strip(), str(h or "").strip().lower())
        result.append(key)
    return result


def _cell_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _parse_entity_sheet(sheet) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    header_idx: list[tuple[int, str]] = []
    seen_headers = False
    for r_idx, row in enumerate(sheet.iter_rows(values_only=True), start=1):
        vals = [v for v in row]
        # 找到表头行（含 label 或 实体）
        if not seen_headers:
            headers = [_cell_str(v) for v in vals]
            if any(h in ("label", "实体", "实体类型") for h in headers):
                normalized = _normalize_headers(headers)
                header_idx = [(i, n) for i, n in enumerate(normalized) if n in ("label", "name", "properties", "busi_name")]
                seen_headers = True
            continue
        if seen_headers and not any(_cell_str(v) for v in vals):
            continue  # 跳过空行
        # 跳过说明/示例尾行（以"说明"或"#"开头，或缺 label）
        if not vals or not _cell_str(vals[0]):
            continue
        if _cell_str(vals[0]).startswith(("#", "说明", "示例")):
            continue
        record = {}
        for i, key in header_idx:
            record[key] = _cell_str(vals[i]) if i < len(vals) else ""
        if record.get("label") and record.get("name"):
            rows.append(record)
    return rows


def _parse_relation_sheet(sheet) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    header_idx: list[tuple[int, str]] = []
    seen_headers = False
    for r_idx, row in enumerate(sheet.iter_rows(values_only=True), start=1):
        vals = [v for v in row]
        if not seen_headers:
            headers = [_cell_str(v) for v in vals]
            if any(h in ("from_label", "起点标签", "from_name") for h in headers):
                normalized = _normalize_headers(headers)
                header_idx = [(i, n) for i, n in enumerate(normalized) if n in (
                    "from_label", "from_name", "rel_type", "to_label", "to_name", "properties",
                )]
                seen_headers = True
            continue
        if not vals or not _cell_str(vals[0]):
            continue
        if _cell_str(vals[0]).startswith(("#", "说明", "示例")):
            continue
        record = {}
        for i, key in header_idx:
            record[key] = _cell_str(vals[i]) if i < len(vals) else ""
        if record.get("from_label") and record.get("from_name"):
            rows.append(record)
    return rows


def _parse_help_sheet(sheet) -> str:
    lines = []
    for row in sheet.iter_rows(values_only=True):
        vals = [_cell_str(v) for v in row if v is not None]
        if vals:
            lines.append("\t".join(vals))
    return "\n".join(lines).strip()


def parse_properties(raw: str) -> dict[str, Any]:
    """把 properties 字符串解析为 dict（宽容，空/非法返回空 dict）。"""
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def extract_busi_name(props: dict[str, Any], explicit: str = "") -> str:
    """业务线提取：优先显式列，其次 properties.busi_name/business_line。"""
    if explicit and explicit.strip():
        return explicit.strip()
    return str(props.get("busi_name") or props.get("business_line") or "").strip()
