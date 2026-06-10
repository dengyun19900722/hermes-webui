from __future__ import annotations

import io
import base64
import struct
import sys
import types
import zlib
import zipfile
from pathlib import Path


PNG = b"\x89PNG\r\n\x1a\n"


def _zip_bytes(entries: dict[str, bytes | str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, data.encode("utf-8") if isinstance(data, str) else data)
    return buf.getvalue()


def _legacy_gbk_zip_bytes(entries: dict[str, bytes | str]) -> bytes:
    out = io.BytesIO()
    central: list[bytes] = []
    for name, data in entries.items():
        payload = data.encode("utf-8") if isinstance(data, str) else data
        raw_name = name.encode("gbk")
        crc = zlib.crc32(payload) & 0xFFFFFFFF
        offset = out.tell()
        out.write(
            struct.pack(
                "<IHHHHHIIIHH",
                0x04034B50,
                20,
                0,
                0,
                0,
                0,
                crc,
                len(payload),
                len(payload),
                len(raw_name),
                0,
            )
        )
        out.write(raw_name)
        out.write(payload)
        central.append(
            struct.pack(
                "<IHHHHHHIIIHHHHHII",
                0x02014B50,
                20,
                20,
                0,
                0,
                0,
                0,
                crc,
                len(payload),
                len(payload),
                len(raw_name),
                0,
                0,
                0,
                0,
                0,
                offset,
            )
            + raw_name
        )
    cd_offset = out.tell()
    for item in central:
        out.write(item)
    cd_size = out.tell() - cd_offset
    out.write(
        struct.pack(
            "<IHHHHIIH",
            0x06054B50,
            0,
            0,
            len(central),
            len(central),
            cd_size,
            cd_offset,
            0,
        )
    )
    return out.getvalue()


def test_zip_markdown_import_copies_and_rewrites_local_images(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_OBSIDIAN_VAULT_DIR", str(tmp_path / "vault"))
    from api import obsidian_notes as notes

    archive = _zip_bytes(
        {
            "guide/readme.md": (
                "# Runbook\n\n"
                "![one](./img/pic.png)\n"
                "![two](./img2/pic.png)\n"
                "![remote](https://example.com/remote.png)\n"
            ),
            "guide/img/pic.png": PNG,
            "guide/img2/pic.png": PNG + b"2",
        }
    )

    result = notes.import_batch_archive("knowledge.zip", archive, target_dir="导入")

    assert result["ok"] is True
    assert result["success_count"] == 1
    assert result["failure_count"] == 0
    assert result["imported"][0]["assets"] == 2
    note_path = tmp_path / "vault" / "导入" / "guide" / "readme.md"
    content = note_path.read_text(encoding="utf-8")
    assert "_attachments/readme/pic.png" in content
    assert "_attachments/readme/pic-1.png" in content
    assert "https://example.com/remote.png" in content
    assert (note_path.parent / "_attachments" / "readme" / "pic.png").read_bytes() == PNG
    assert (note_path.parent / "_attachments" / "readme" / "pic-1.png").read_bytes() == PNG + b"2"


def test_zip_markdown_import_recovers_gbk_names_and_obsidian_attachment_links(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_OBSIDIAN_VAULT_DIR", str(tmp_path / "vault"))
    from api import obsidian_notes as notes

    archive = _legacy_gbk_zip_bytes(
        {
            "文档/笔记.md": "# 标题\n\n![[附件/截图.png]]\n",
            "文档/附件/截图.png": PNG,
        }
    )

    result = notes.import_batch_archive("知识库.zip", archive, target_dir="导入")

    assert result["ok"] is True
    assert result["success_count"] == 1
    assert result["failure_count"] == 0
    assert result["imported"][0]["source"] == "文档/笔记.md"
    assert result["imported"][0]["path"] == "导入/文档/笔记.md"
    note_path = tmp_path / "vault" / "导入" / "文档" / "笔记.md"
    content = note_path.read_text(encoding="utf-8")
    assert "![[附件/截图.png]]" not in content
    assert "![截图](_attachments/笔记/截图.png)" in content
    assert (note_path.parent / "_attachments" / "笔记" / "截图.png").read_bytes() == PNG
    assert not (note_path.parent / "附件" / "截图.png").exists()


def test_zip_markdown_import_rewrites_data_uri_images(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_OBSIDIAN_VAULT_DIR", str(tmp_path / "vault"))
    from api import obsidian_notes as notes

    encoded = base64.b64encode(PNG).decode("ascii")
    archive = _zip_bytes(
        {
            "guide/readme.md": f"# Runbook\n\n![截图](data:image/png; charset=utf-8; base64, {encoded})\n",
        }
    )

    result = notes.import_batch_archive("knowledge.zip", archive, target_dir="导入")

    assert result["ok"] is True
    assert result["success_count"] == 1
    assert result["failure_count"] == 0
    assert result["imported"][0]["assets"] == 1
    note_path = tmp_path / "vault" / "导入" / "guide" / "readme.md"
    content = note_path.read_text(encoding="utf-8")
    assert "data:image/png" not in content
    assert "![截图](_attachments/readme/截图-1.png)" in content
    assert (note_path.parent / "_attachments" / "readme" / "截图-1.png").read_bytes() == PNG


def test_zip_office_import_extracts_embedded_images(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_OBSIDIAN_VAULT_DIR", str(tmp_path / "vault"))
    from api import obsidian_notes as notes

    class FakeMarkItDown:
        def convert(self, path):
            assert path.endswith(".docx")
            return types.SimpleNamespace(text_content="## 正文\n\n巡检内容")

    monkeypatch.setitem(sys.modules, "markitdown", types.SimpleNamespace(MarkItDown=FakeMarkItDown))

    docx = _zip_bytes(
        {
            "[Content_Types].xml": b"",
            "word/document.xml": b"",
            "word/media/image1.png": PNG,
        }
    )
    archive = _zip_bytes({"reports/report.docx": docx})

    result = notes.import_batch_archive("office.zip", archive, target_dir="导入")

    assert result["ok"] is True
    assert result["success_count"] == 1
    assert result["imported"][0]["assets"] == 1
    imported_dir = tmp_path / "vault" / "导入" / "reports"
    note_files = list(imported_dir.glob("*.md"))
    assert len(note_files) == 1
    content = note_files[0].read_text(encoding="utf-8")
    assert content.startswith("# report")
    assert "## 附件图片" in content
    assert "_attachments/" in content
    assert "image1.png" in content
    assert list((imported_dir / "_attachments").rglob("image1.png"))[0].read_bytes() == PNG


def test_zip_office_import_rewrites_converter_data_uri_images(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_OBSIDIAN_VAULT_DIR", str(tmp_path / "vault"))
    from api import obsidian_notes as notes

    encoded = base64.b64encode(PNG).decode("ascii")

    class FakeMarkItDown:
        def convert(self, path):
            assert path.endswith(".docx")
            return types.SimpleNamespace(
                text_content=f"## 正文\n\n![内嵌图](data:image/png;base64,{encoded})\n"
            )

    monkeypatch.setitem(sys.modules, "markitdown", types.SimpleNamespace(MarkItDown=FakeMarkItDown))

    docx = _zip_bytes(
        {
            "[Content_Types].xml": b"",
            "word/document.xml": b"",
            "word/media/image1.png": PNG,
        }
    )
    archive = _zip_bytes({"reports/report.docx": docx})

    result = notes.import_batch_archive("office.zip", archive, target_dir="导入")

    assert result["ok"] is True
    assert result["success_count"] == 1
    assert result["imported"][0]["assets"] == 1
    imported_dir = tmp_path / "vault" / "导入" / "reports"
    note_files = list(imported_dir.glob("*.md"))
    assert len(note_files) == 1
    content = note_files[0].read_text(encoding="utf-8")
    assert "data:image/png;base64" not in content
    assert "![内嵌图](_attachments/" in content
    assert "## 附件图片" not in content
    assert list((imported_dir / "_attachments").rglob("*.png"))[0].read_bytes() == PNG


def test_zip_batch_import_reports_per_file_failures_and_blocks_traversal(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_OBSIDIAN_VAULT_DIR", str(tmp_path / "vault"))
    from api import obsidian_notes as notes

    archive = _zip_bytes(
        {
            "good.md": "# Good\n",
            "bad.md": "# Bad\n\n![missing](missing.png)\n",
            "../evil.md": "# Evil\n",
        }
    )

    result = notes.import_batch_archive("mixed.zip", archive)

    assert result["ok"] is False
    assert result["success_count"] == 1
    assert result["failure_count"] == 2
    failures = {(item["source"], item["stage"]) for item in result["failed"]}
    assert ("../evil.md", "validate") in failures
    assert ("bad.md", "copy_assets") in failures
    assert any(item["error"] == "ZIP 内文件路径不能包含 .." for item in result["failed"])
    assert any(item["error"] == "本地图片未找到：missing.png" for item in result["failed"])
    assert (tmp_path / "vault" / "good.md").exists()
    assert not (tmp_path / "vault" / "bad.md").exists()
    assert not (tmp_path / "evil.md").exists()
