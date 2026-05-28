from __future__ import annotations

import io
from pathlib import Path
from urllib.parse import quote, urlparse
from unittest.mock import MagicMock, patch


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


def test_static_wiring_includes_knowledge_panel():
    html = Path("static/index.html").read_text(encoding="utf-8")
    js = Path("static/panels.js").read_text(encoding="utf-8")
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
    assert "showing-knowledge" in css
