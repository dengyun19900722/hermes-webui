from __future__ import annotations

import io
import base64
import zipfile
import sys
import types
from pathlib import Path
from urllib.parse import quote, urlparse
from unittest.mock import MagicMock, patch

import pytest


class _DownloadHandler:
    def __init__(self):
        self.status = None
        self.headers = {}
        self.wfile = io.BytesIO()

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.headers[key] = value

    def end_headers(self):
        return None


def _zip_bytes(entries: dict[str, bytes | str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data.encode("utf-8") if isinstance(data, str) else data)
    return buf.getvalue()


def test_filesystem_crud_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_OBSIDIAN_VAULT_DIR", str(tmp_path / "vault"))
    from api import obsidian_notes as notes

    created = notes.create_note("登录失败排查", "01-故障知识库", "# 登录失败\n\n检查 cookie")
    assert created["path"].startswith("01-故障知识库/")
    assert created["content"].startswith("# 登录失败")

    tree = notes.notes_tree()
    assert any(node["path"] == "01-故障知识库" for node in tree["tree"])

    read = notes.read_note(created["path"])
    assert "检查 cookie" in read["content"]

    updated = notes.update_note(created["path"], "# 更新后的内容")
    assert updated["content"] == "# 更新后的内容"

    search = notes.search_notes("更新后的")
    assert any(item["path"] == created["path"] for item in search["results"])

    uploaded = notes.upload_markdown("导入.md", "# 导入\n\n内容".encode("utf-8"), "02-运维手册")
    assert uploaded["path"].startswith("02-运维手册/")

    listed = notes.list_notes("02-运维手册")
    assert any(item["path"] == uploaded["path"] for item in listed["notes"])

    deleted = notes.delete_note(created["path"])
    assert deleted["ok"] is True
    assert not (tmp_path / "vault" / created["path"]).exists()


def test_directory_crud_and_assets_are_sandboxed(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_OBSIDIAN_VAULT_DIR", str(tmp_path / "vault"))
    from api import obsidian_notes as notes

    root_dir = notes.create_directory("", "一级目录")
    assert root_dir["path"] == "一级目录"
    assert (tmp_path / "vault" / "一级目录").is_dir()

    child_dir = notes.create_directory(root_dir["path"], "子目录")
    assert child_dir["path"] == "一级目录/子目录"
    assert (tmp_path / "vault" / "一级目录" / "子目录").is_dir()

    created_dir = notes.create_directory("01-故障知识库", "数据库")
    assert created_dir["path"] == "01-故障知识库/数据库"

    renamed = notes.rename_directory(created_dir["path"], "MySQL")
    assert renamed["path"] == "01-故障知识库/MySQL"

    created = notes.create_note("慢查询", renamed["path"], "# 慢查询")
    with pytest.raises(FileExistsError):
        notes.delete_directory(renamed["path"], recursive=False)

    asset = notes.upload_asset("截图.png", b"\x89PNG\r\n\x1a\n", note_path=created["path"])
    assert "_attachments/" in asset["path"]
    assert asset["markdown"].startswith("![")

    tree = notes.notes_tree()
    assert "_attachments" not in repr(tree["tree"])

    handler = _DownloadHandler()
    assert notes.send_note_media(handler, asset["path"]) is True
    assert handler.status == 200
    assert handler.headers["Content-Type"] == "image/png"
    assert handler.wfile.getvalue().startswith(b"\x89PNG")

    deleted = notes.delete_directory(renamed["path"], recursive=True)
    assert deleted["ok"] is True
    assert not (tmp_path / "vault" / renamed["path"]).exists()


def test_office_import_uses_optional_converter(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_OBSIDIAN_VAULT_DIR", str(tmp_path / "vault"))
    from api import obsidian_notes as notes

    class FakeMarkItDown:
        def convert(self, path):
            assert path.endswith(".docx")
            return types.SimpleNamespace(text_content="## 导入内容\n\n正文")

    monkeypatch.setitem(sys.modules, "markitdown", types.SimpleNamespace(MarkItDown=FakeMarkItDown))

    imported = notes.import_office_document("巡检报告.docx", b"fake", target_dir="02-运维手册")
    assert imported["path"].startswith("02-运维手册/")
    assert imported["imported_from"] == "巡检报告.docx"
    assert imported["content"].startswith("# 巡检报告")
    assert "## 导入内容" in imported["content"]


def test_office_import_rewrites_data_uri_images_to_attachments(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_OBSIDIAN_VAULT_DIR", str(tmp_path / "vault"))
    from api import obsidian_notes as notes

    image_bytes = b"\x89PNG\r\n\x1a\n"
    encoded = base64.b64encode(image_bytes).decode("ascii")

    class FakeMarkItDown:
        def convert(self, path):
            assert path.endswith(".docx")
            return types.SimpleNamespace(
                text_content=f"## 导入内容\n\n![登录截图](data:image/png;base64,{encoded})\n"
            )

    monkeypatch.setitem(sys.modules, "markitdown", types.SimpleNamespace(MarkItDown=FakeMarkItDown))

    imported = notes.import_office_document("巡检报告.docx", b"fake", target_dir="02-运维手册")

    assert "data:image/png;base64" not in imported["content"]
    assert "![登录截图](_attachments/" in imported["content"]
    assert imported["asset_count"] == 1
    asset_path = tmp_path / "vault" / imported["assets"][0]["path"]
    assert asset_path.read_bytes() == image_bytes


def test_markdown_upload_rewrites_data_uri_images_to_attachments(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_OBSIDIAN_VAULT_DIR", str(tmp_path / "vault"))
    from api import obsidian_notes as notes

    image_bytes = b"\x89PNG\r\n\x1a\n"
    encoded = base64.b64encode(image_bytes).decode("ascii")

    uploaded = notes.upload_markdown(
        "导入.md",
        f"# 导入\n\n![](data:image/png; charset=utf-8; base64, {encoded})\n".encode("utf-8"),
        "02-运维手册",
    )

    assert "data:image/png" not in uploaded["content"]
    assert "![](_attachments/导入/image-1.png)" in uploaded["content"]
    assert uploaded["asset_count"] == 1
    asset_path = tmp_path / "vault" / uploaded["assets"][0]["path"]
    assert asset_path.read_bytes() == image_bytes


def test_office_import_rewrites_wrapped_data_uri_with_parameters(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_OBSIDIAN_VAULT_DIR", str(tmp_path / "vault"))
    from api import obsidian_notes as notes

    image_bytes = b"\x89PNG\r\n\x1a\n"
    encoded = base64.b64encode(image_bytes).decode("ascii").rstrip("=")
    folded = encoded[:8] + "\n" + encoded[8:]

    class FakeMarkItDown:
        def convert(self, path):
            assert path.endswith(".docx")
            return types.SimpleNamespace(
                text_content=(
                    "## 导入内容\n\n"
                    f"![登录截图](<data:image/png; charset=utf-8; base64, {folded}> \"截图\")\n"
                )
            )

    monkeypatch.setitem(sys.modules, "markitdown", types.SimpleNamespace(MarkItDown=FakeMarkItDown))

    imported = notes.import_office_document("巡检报告.docx", b"fake", target_dir="02-运维手册")

    assert "data:image/png" not in imported["content"]
    assert "![登录截图](_attachments/" in imported["content"]
    assert '"截图"' in imported["content"]
    assert imported["asset_count"] == 1
    asset_path = tmp_path / "vault" / imported["assets"][0]["path"]
    assert asset_path.read_bytes() == image_bytes


def test_office_import_rewrites_unparseable_data_uri_with_embedded_image_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_OBSIDIAN_VAULT_DIR", str(tmp_path / "vault"))
    from api import obsidian_notes as notes

    image_bytes = b"\x89PNG\r\n\x1a\n"

    class FakeMarkItDown:
        def convert(self, path):
            assert path.endswith(".docx")
            return types.SimpleNamespace(text_content="## 导入内容\n\n![](data:image/png;base64,not-valid-base64!!)\n")

    monkeypatch.setitem(sys.modules, "markitdown", types.SimpleNamespace(MarkItDown=FakeMarkItDown))

    docx = _zip_bytes(
        {
            "[Content_Types].xml": b"",
            "word/document.xml": b"",
            "word/media/image1.png": image_bytes,
        }
    )

    imported = notes.import_office_document("巡检报告.docx", docx, target_dir="02-运维手册")

    assert "data:image/png" not in imported["content"]
    assert "![](_attachments/" in imported["content"]
    assert "## 附件图片" not in imported["content"]
    assert imported["asset_count"] == 1
    asset_path = tmp_path / "vault" / imported["assets"][0]["path"]
    assert asset_path.read_bytes() == image_bytes


def test_default_vault_root_uses_global_workspace_obsidian(tmp_path, monkeypatch):
    monkeypatch.delenv("HERMES_OBSIDIAN_VAULT_DIR", raising=False)
    from api import config
    from api import obsidian_notes as notes

    monkeypatch.setattr(config, "DEFAULT_WORKSPACE", tmp_path / "workspace")

    root = notes.vault_root()
    assert root == (tmp_path / "workspace" / "obsidian").resolve()

    created = notes.create_note("全局工作区", "03-FAQ", "# 全局工作区")
    assert (tmp_path / "workspace" / "obsidian" / created["path"]).exists()


def test_download_response_uses_attachment_headers(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_OBSIDIAN_VAULT_DIR", str(tmp_path / "vault"))
    from api import obsidian_notes as notes

    created = notes.create_note("下载测试", "03-FAQ", "# 下载\n\n内容")
    handler = _DownloadHandler()

    assert notes.send_note_download(handler, created["path"]) is True
    assert handler.status == 200
    assert handler.headers["Content-Type"].startswith("text/markdown")
    assert "attachment;" in handler.headers["Content-Disposition"]
    assert handler.wfile.getvalue().decode("utf-8").startswith("# 下载")


def test_route_get_post_put_delete_cover_notes_endpoints(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_OBSIDIAN_VAULT_DIR", str(tmp_path / "vault"))
    from api import obsidian_notes as notes
    import api.routes as routes

    created = notes.create_note("路由测试", "01-故障知识库", "# 路由\n\n内容")

    captured = {}

    def fake_j(handler, payload, status=200, extra_headers=None):
        captured["payload"] = payload
        captured["status"] = status
        return True

    handler = MagicMock()

    with patch("api.obsidian_notes.j", side_effect=fake_j):
        assert routes.handle_get(handler, urlparse("/api/notes/tree")) is True
        assert captured["status"] == 200
        assert any(node["path"] == "01-故障知识库" for node in captured["payload"]["tree"])

    handler_download = _DownloadHandler()
    assert routes.handle_get(handler_download, urlparse("/api/notes/download/" + quote(created["path"]))) is True
    assert handler_download.status == 200

    with patch("api.routes._check_csrf", return_value=True), \
         patch("api.routes.read_body", side_effect=AssertionError("read_body should not run for upload")), \
         patch("api.obsidian_notes.handle_notes_upload", return_value=True) as upload_mock:
        assert routes.handle_post(handler, urlparse("/api/notes/upload")) is True
        upload_mock.assert_called_once()

    with patch("api.routes._check_csrf", return_value=True), \
         patch("api.routes.read_body", side_effect=AssertionError("read_body should not run for asset upload")), \
         patch("api.obsidian_notes.handle_notes_asset_upload", return_value=True) as asset_mock:
        assert routes.handle_post(handler, urlparse("/api/notes/assets")) is True
        asset_mock.assert_called_once()

    with patch("api.routes._check_csrf", return_value=True), \
         patch("api.routes.read_body", side_effect=AssertionError("read_body should not run for office import")), \
         patch("api.obsidian_notes.handle_notes_import", return_value=True) as import_mock:
        assert routes.handle_post(handler, urlparse("/api/notes/import")) is True
        import_mock.assert_called_once()

    with patch("api.routes._check_csrf", return_value=True), \
         patch("api.routes.read_body", side_effect=AssertionError("read_body should not run for batch import")), \
         patch("api.obsidian_notes.handle_notes_batch_import", return_value=True) as batch_import_mock:
        assert routes.handle_post(handler, urlparse("/api/notes/import/batch")) is True
        batch_import_mock.assert_called_once()

    captured.clear()
    body = {"path": created["path"], "content": "# 修改后的内容"}
    with patch("api.obsidian_notes.j", side_effect=fake_j), \
         patch("api.routes._check_csrf", return_value=True):
        with patch("api.routes.read_body", return_value=body):
            assert routes.handle_put(handler, urlparse("/api/notes/content")) is True
            assert captured["payload"]["content"] == "# 修改后的内容"

    captured.clear()
    with patch("api.obsidian_notes.j", side_effect=fake_j), \
         patch("api.routes._check_csrf", return_value=True), \
         patch("api.routes.read_body", return_value={"path": created["path"]}):
        assert routes.handle_delete(handler, urlparse("/api/notes/content")) is True
    assert captured["payload"]["ok"] is True


def test_notes_office_import_allows_knowledge_limit_above_default_upload_limit(monkeypatch):
    from api import obsidian_notes as notes

    captured = {}

    def fake_j(handler, payload, status=200, extra_headers=None):
        captured["payload"] = payload
        captured["status"] = status
        return True

    handler = MagicMock()
    handler.headers = {
        "Content-Type": "multipart/form-data; boundary=test",
        "Content-Length": str(notes.MAX_UPLOAD_BYTES + 1),
    }
    handler.rfile = io.BytesIO()

    with patch("api.obsidian_notes.j", side_effect=fake_j), \
         patch("api.obsidian_notes.parse_multipart", return_value=({"target_dir": "导入"}, {"file": ("big.docx", b"fake")})) as parse_mock, \
         patch("api.obsidian_notes.import_office_document", return_value={"path": "导入/big.md"}) as import_mock:
        assert notes.handle_notes_import(handler) is True

    assert captured["status"] == 200
    parse_mock.assert_called_once()
    import_mock.assert_called_once()


def test_notes_batch_import_rejects_files_over_knowledge_limit(monkeypatch):
    from api import obsidian_notes as notes

    captured = {}

    def fake_j(handler, payload, status=200, extra_headers=None):
        captured["payload"] = payload
        captured["status"] = status
        return True

    handler = MagicMock()
    handler.headers = {
        "Content-Type": "multipart/form-data; boundary=test",
        "Content-Length": str(notes.KNOWLEDGE_IMPORT_MAX_BYTES + 1),
    }
    handler.rfile = io.BytesIO()

    with patch("api.obsidian_notes.j", side_effect=fake_j), \
         patch("api.obsidian_notes.parse_multipart", side_effect=AssertionError("oversized upload should stop before parsing")):
        assert notes.handle_notes_batch_import(handler) is True

    assert captured["status"] == 413
    assert "500 MB" in captured["payload"]["error"]


def test_static_wiring_includes_knowledge_panel():
    html = Path("static/index.html").read_text(encoding="utf-8")
    js = Path("static/panels.js").read_text(encoding="utf-8")
    notes_js = Path("static/obsidian_notes.js").read_text(encoding="utf-8")
    icons_js = Path("static/icons.js").read_text(encoding="utf-8")
    css = Path("static/style.css").read_text(encoding="utf-8")

    assert 'data-panel="knowledge"' in html
    assert 'id="panelKnowledge"' in html
    assert 'id="mainKnowledge"' in html
    assert 'id="knowledgeList"' in html
    assert 'id="knowledgeSearch"' in html
    assert 'id="knowledgeDetailTitle"' in html
    assert 'id="knowledgeDetailBody"' in html
    assert "static/obsidian_notes.js" in html
    assert "loadKnowledgeNotes" in js
    assert 'onclick="createRootKnowledgeDirectory()"' in html
    assert 'data-tooltip="新建一级目录"' in html
    assert 'data-tooltip="新建笔记"' in html
    assert 'data-tooltip="上传 Markdown"' in html
    assert 'data-tooltip="导入 Office 文档"' in html
    assert 'data-tooltip="批量导入 ZIP"' in html
    assert 'placeholder="搜索笔记..."' in html
    assert "function createRootKnowledgeDirectory" in notes_js
    assert "createKnowledgeDirectory" in notes_js
    assert "createKnowledgeDirectory(nodePath)" in notes_js
    assert "'folder-plus'" in icons_js
    assert "openKnowledgeOfficeImport" in notes_js
    assert "openKnowledgeBatchImport" in notes_js
    assert "function _knowledgeChooseFiles" in notes_js
    assert "id='knowledgeFilePicker'" in notes_js
    assert "file-input-visually-hidden" in notes_js
    assert "document.body.appendChild(input)" in notes_js
    assert "_knowledgeChooseFiles({accept:'.md,.markdown,text/markdown'})" in notes_js
    assert "openKnowledgeImageUpload" in notes_js
    assert "_knowledgeBatchGuideText" in notes_js
    assert "推荐结构" in notes_js
    assert "Markdown 本地图片必须放在 ZIP 内" in notes_js
    assert "![[附件/login.png]]" in notes_js
    assert "hideCancel:true" in notes_js
    assert "wide:true" in notes_js
    assert "/api/notes/import/batch" in notes_js
    assert "/api/notes/assets" in notes_js
    assert "knowledge-toc" in css
    assert ".knowledge-row-actions{margin-left:auto;display:inline-flex" in css
    assert 'button[data-action="mkdir"]' in css
    assert ".knowledge-note-content img" in css
    assert "width:100%" in css
    assert "showing-knowledge" in css
    assert ".app-dialog--wide" in css
