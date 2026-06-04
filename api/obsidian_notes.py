"""
Filesystem-backed Obsidian vault notes API.

The WebUI owns a small CRUD surface over a mounted Markdown vault.  The module
keeps filesystem policy here so routes.py only needs thin dispatch hooks.
"""

from __future__ import annotations

import os
import re
import mimetypes
import shutil
import tempfile
from datetime import date
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, quote, unquote

from api.config import MAX_UPLOAD_BYTES
from api.helpers import _sanitize_error, _security_headers, bad, j
from api.upload import parse_multipart


VAULT_DIR_NAME = "obsidian"
DEFAULT_CATEGORIES = ("01-故障知识库", "02-运维手册", "03-FAQ")
MARKDOWN_SUFFIXES = {".md", ".markdown"}
OFFICE_SUFFIXES = {".docx", ".xlsx", ".pptx"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
ASSET_DIR_NAME = "_attachments"
EXCLUDED_DIR_NAMES = {".obsidian"}
EXCLUDED_TREE_DIR_NAMES = EXCLUDED_DIR_NAMES | {ASSET_DIR_NAME}
RESERVED_ENDPOINTS = {
    "/api/notes",
    "/api/notes/tree",
    "/api/notes/search",
    "/api/notes/content",
    "/api/notes/download",
    "/api/notes/upload",
    "/api/notes/delete",
    "/api/notes/directories",
    "/api/notes/assets",
    "/api/notes/media",
    "/api/notes/import",
}
MAX_SEARCH_FILE_BYTES = 512 * 1024
MAX_SEARCH_RESULTS = 100


class NotesError(ValueError):
    """Client-visible validation error."""


class NotesDependencyError(RuntimeError):
    """Optional feature dependency is not installed or unavailable."""


def vault_root(*, create: bool = False) -> Path:
    raw = os.getenv("HERMES_OBSIDIAN_VAULT_DIR", "").strip()
    if raw:
        root = Path(raw).expanduser().resolve()
    else:
        from api.config import DEFAULT_WORKSPACE

        root = (Path(DEFAULT_WORKSPACE).expanduser().resolve() / VAULT_DIR_NAME)
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root


def _clean_rel_path(raw_path: str | None, *, allow_root: bool = False) -> PurePosixPath:
    raw = str(raw_path or "").replace("\\", "/").strip()
    if raw in {"", "."}:
        if allow_root:
            return PurePosixPath(".")
        raise NotesError("path is required")
    if raw.startswith("/") or "\x00" in raw:
        raise NotesError("invalid path")
    parts = [part for part in raw.split("/") if part and part != "."]
    if not parts and allow_root:
        return PurePosixPath(".")
    if not parts:
        raise NotesError("path is required")
    if any(part == ".." for part in parts):
        raise NotesError("path traversal is not allowed")
    if any(part in EXCLUDED_DIR_NAMES or part.startswith(".") for part in parts):
        raise NotesError("hidden vault paths are not accessible")
    return PurePosixPath(*parts)


def _resolve_vault_path(
    raw_path: str | None,
    *,
    allow_root: bool = False,
    require_markdown: bool = False,
    create_root: bool = False,
) -> Path:
    rel = _clean_rel_path(raw_path, allow_root=allow_root)
    if require_markdown and rel.suffix.lower() not in MARKDOWN_SUFFIXES:
        raise NotesError("only Markdown notes are supported")
    root = vault_root(create=create_root)
    if rel == PurePosixPath("."):
        return root
    target = (root / Path(*rel.parts)).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise NotesError("path traversal is not allowed") from exc
    return target


def _relative(path: Path) -> str:
    return path.resolve().relative_to(vault_root()).as_posix()


def _is_excluded_path(path: Path, *, include_assets: bool = True) -> bool:
    excluded = EXCLUDED_TREE_DIR_NAMES if include_assets else EXCLUDED_DIR_NAMES
    return any(part in excluded or part.startswith(".") for part in path.parts)


def _is_markdown(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in MARKDOWN_SUFFIXES


def _safe_filename_stem(value: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", str(value or "").strip())
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    cleaned = cleaned.replace("..", "_")
    if not cleaned:
        raise NotesError("title is required")
    return cleaned[:120]


def _safe_upload_name(filename: str) -> str:
    name = Path(str(filename or "")).name
    stem = _safe_filename_stem(Path(name).stem)
    suffix = Path(name).suffix.lower()
    if suffix not in MARKDOWN_SUFFIXES:
        raise NotesError("only .md files can be uploaded")
    return f"{stem}{suffix}"


def _safe_dir_name(value: str) -> str:
    name = _safe_filename_stem(Path(str(value or "")).name)
    if name in {".", "..", ASSET_DIR_NAME} or name.startswith("."):
        raise NotesError("invalid directory name")
    return name


def _safe_asset_name(filename: str) -> str:
    name = Path(str(filename or "")).name
    stem = _safe_filename_stem(Path(name).stem or "image")
    suffix = Path(name).suffix.lower() or ".png"
    if suffix not in IMAGE_SUFFIXES:
        raise NotesError("only image assets are supported")
    return f"{stem}{suffix}"


def _safe_office_name(filename: str) -> str:
    name = Path(str(filename or "")).name
    suffix = Path(name).suffix.lower()
    if suffix not in OFFICE_SUFFIXES:
        raise NotesError("only docx, xlsx, and pptx imports are supported")
    return name


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    for idx in range(1, 1000):
        candidate = parent / f"{stem}-{idx}{suffix}"
        if not candidate.exists():
            return candidate
    raise FileExistsError("too many files with the same name")


def _ensure_manageable_directory(path: Path) -> None:
    root = vault_root()
    if path.resolve() == root:
        raise NotesError("vault root cannot be modified")
    rel = path.resolve().relative_to(root)
    if any(part == ASSET_DIR_NAME for part in rel.parts):
        raise NotesError("attachment directories are managed automatically")


def _note_payload(path: Path) -> dict:
    stat = path.stat()
    rel = _relative(path)
    parts = PurePosixPath(rel).parts
    return {
        "type": "note",
        "name": path.name,
        "title": path.stem,
        "path": rel,
        "category": parts[0] if len(parts) > 1 else "",
        "mtime": stat.st_mtime,
        "size": stat.st_size,
    }


def _dir_payload(path: Path) -> dict:
    rel = "." if path.resolve() == vault_root() else _relative(path)
    return {
        "type": "dir",
        "name": "Knowledge Base" if rel == "." else path.name,
        "path": rel,
        "children": _tree_children(path),
    }


def _tree_children(path: Path) -> list[dict]:
    if not path.exists():
        return []
    children: list[dict] = []
    for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold())):
        if _is_excluded_path(child.relative_to(vault_root())):
            continue
        if child.is_dir():
            children.append(_dir_payload(child))
        elif _is_markdown(child):
            children.append(_note_payload(child))
    return children


def _all_notes(root: Path | None = None) -> list[dict]:
    base = root or vault_root()
    if not base.exists():
        return []
    notes = []
    for path in sorted(base.rglob("*"), key=lambda p: p.relative_to(base).as_posix().casefold()):
        rel = path.relative_to(base)
        if _is_excluded_path(rel) or not _is_markdown(path):
            continue
        notes.append(_note_payload(path))
    return notes


def notes_tree() -> dict:
    root = vault_root()
    return {
        "root": str(root),
        "exists": root.exists(),
        "tree": _tree_children(root),
        "notes": _all_notes(root),
        "default_categories": list(DEFAULT_CATEGORIES),
    }


def list_notes(raw_dir: str | None = None) -> dict:
    directory = _resolve_vault_path(raw_dir or ".", allow_root=True)
    if not directory.exists():
        return {"dir": "." if not raw_dir else raw_dir, "notes": []}
    if not directory.is_dir():
        raise NotesError("dir must be a directory")
    notes = [
        _note_payload(path)
        for path in sorted(directory.iterdir(), key=lambda p: p.name.casefold())
        if not _is_excluded_path(path.relative_to(vault_root())) and _is_markdown(path)
    ]
    return {"dir": "." if directory == vault_root() else _relative(directory), "notes": notes}


def read_note(raw_path: str) -> dict:
    target = _resolve_vault_path(raw_path, require_markdown=True)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError("note not found")
    payload = _note_payload(target)
    payload["content"] = target.read_text(encoding="utf-8")
    return payload


def create_note(title: str, category: str | None = None, content: str | None = None) -> dict:
    safe_title = _safe_filename_stem(title)
    category_path = _clean_rel_path(category or ".", allow_root=True)
    if category_path.suffix:
        raise NotesError("category must be a directory")
    filename = f"{date.today().isoformat()}_{safe_title}.md"
    parent = _resolve_vault_path(category_path.as_posix(), allow_root=True, create_root=True)
    parent.mkdir(parents=True, exist_ok=True)
    target = (parent / filename).resolve()
    target.relative_to(vault_root())
    if target.exists():
        raise FileExistsError("note already exists")
    initial = content if content is not None else f"# {safe_title}\n"
    target.write_text(initial, encoding="utf-8")
    payload = _note_payload(target)
    payload["content"] = initial
    return payload


def update_note(raw_path: str, content: str) -> dict:
    target = _resolve_vault_path(raw_path, require_markdown=True, create_root=True)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError("note not found")
    target.write_text(str(content or ""), encoding="utf-8")
    payload = _note_payload(target)
    payload["content"] = str(content or "")
    return payload


def delete_note(raw_path: str) -> dict:
    target = _resolve_vault_path(raw_path, require_markdown=True)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError("note not found")
    rel = _relative(target)
    target.unlink()
    return {"ok": True, "path": rel}


def create_directory(parent: str | None, name: str) -> dict:
    safe_name = _safe_dir_name(name)
    base = _resolve_vault_path(parent or ".", allow_root=True, create_root=True)
    if base.exists() and not base.is_dir():
        raise NotesError("parent must be a directory")
    base.mkdir(parents=True, exist_ok=True)
    target = (base / safe_name).resolve()
    target.relative_to(vault_root())
    _ensure_manageable_directory(target)
    if target.exists():
        raise FileExistsError("directory already exists")
    target.mkdir()
    return _dir_payload(target)


def rename_directory(raw_path: str, name: str, parent: str | None = None) -> dict:
    target = _resolve_vault_path(raw_path, allow_root=False)
    if not target.exists() or not target.is_dir():
        raise FileNotFoundError("directory not found")
    _ensure_manageable_directory(target)
    safe_name = _safe_dir_name(name)
    if parent:
        dest_parent = _resolve_vault_path(parent, allow_root=True)
    else:
        dest_parent = target.parent
    if not dest_parent.exists() or not dest_parent.is_dir():
        raise NotesError("parent must be an existing directory")
    dest = (dest_parent / safe_name).resolve()
    dest.relative_to(vault_root())
    _ensure_manageable_directory(dest)
    try:
        dest.relative_to(target.resolve())
    except ValueError:
        pass
    else:
        raise NotesError("directory cannot be moved into itself")
    if dest.exists():
        raise FileExistsError("directory already exists")
    target.rename(dest)
    return _dir_payload(dest)


def delete_directory(raw_path: str, *, recursive: bool = False) -> dict:
    target = _resolve_vault_path(raw_path, allow_root=False)
    if not target.exists() or not target.is_dir():
        raise FileNotFoundError("directory not found")
    _ensure_manageable_directory(target)
    rel = _relative(target)
    if recursive:
        shutil.rmtree(target)
    else:
        try:
            target.rmdir()
        except OSError as exc:
            raise FileExistsError("directory is not empty") from exc
    return {"ok": True, "path": rel}


def upload_markdown(filename: str, file_bytes: bytes, target_dir: str | None = None) -> dict:
    safe_name = _safe_upload_name(filename)
    parent = _resolve_vault_path(target_dir or ".", allow_root=True, create_root=True)
    if parent.suffix:
        raise NotesError("target_dir must be a directory")
    parent.mkdir(parents=True, exist_ok=True)
    dest = (parent / safe_name).resolve()
    dest.relative_to(vault_root())
    if dest.exists():
        raise FileExistsError("note already exists")
    dest.write_bytes(file_bytes)
    payload = _note_payload(dest)
    payload["content"] = file_bytes.decode("utf-8", errors="replace")
    return payload


def _asset_base_dir(note_path: str | None, target_dir: str | None) -> Path:
    if note_path:
        note = _resolve_vault_path(note_path, require_markdown=True)
        return note.parent
    base = _resolve_vault_path(target_dir or ".", allow_root=True, create_root=True)
    if base.suffix:
        raise NotesError("target_dir must be a directory")
    base.mkdir(parents=True, exist_ok=True)
    return base


def _relative_between(path: Path, base: Path) -> str:
    rel = os.path.relpath(path.resolve(), base.resolve())
    return Path(rel).as_posix()


def upload_asset(
    filename: str,
    file_bytes: bytes,
    *,
    note_path: str | None = None,
    target_dir: str | None = None,
) -> dict:
    safe_name = _safe_asset_name(filename)
    base = _asset_base_dir(note_path, target_dir)
    folder_stem = "uploads"
    if note_path:
        folder_stem = _safe_filename_stem(Path(note_path).stem)
    asset_dir = (base / ASSET_DIR_NAME / folder_stem).resolve()
    asset_dir.relative_to(vault_root())
    asset_dir.mkdir(parents=True, exist_ok=True)
    dest = _unique_path((asset_dir / safe_name).resolve())
    dest.relative_to(vault_root())
    dest.write_bytes(file_bytes)
    rel = _relative(dest)
    relative_path = _relative_between(dest, base)
    return {
        "ok": True,
        "type": "asset",
        "name": dest.name,
        "path": rel,
        "relative_path": relative_path,
        "markdown": f"![{Path(dest.name).stem}]({relative_path})",
        "url": "api/notes/media?path=" + quote(rel),
        "size": dest.stat().st_size,
    }


def send_note_media(handler, raw_path: str) -> bool:
    target = _resolve_vault_path(raw_path)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError("media not found")
    if target.suffix.lower() not in IMAGE_SUFFIXES:
        raise NotesError("only image media can be served")
    body = target.read_bytes()
    mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
    handler.send_response(200)
    handler.send_header("Content-Type", mime)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Disposition", f"inline; filename=\"{re.sub(r'[^A-Za-z0-9._-]+', '_', target.name)}\"")
    _security_headers(handler)
    handler.end_headers()
    handler.wfile.write(body)
    return True


def _convert_office_with_markitdown(filename: str, file_bytes: bytes) -> str:
    try:
        from markitdown import MarkItDown  # type: ignore
    except Exception as exc:
        raise NotesDependencyError("Office import requires the optional markitdown package") from exc
    with tempfile.TemporaryDirectory(prefix="hermes-office-import-") as tmp:
        source = Path(tmp) / _safe_office_name(filename)
        source.write_bytes(file_bytes)
        result = MarkItDown().convert(str(source))
    content = getattr(result, "text_content", None) or str(result or "")
    if not content.strip():
        raise NotesError("Office conversion produced empty Markdown")
    return content


def import_office_document(
    filename: str,
    file_bytes: bytes,
    *,
    target_dir: str | None = None,
    title: str | None = None,
) -> dict:
    safe_source = _safe_office_name(filename)
    safe_title = _safe_filename_stem(title or Path(safe_source).stem)
    parent = _resolve_vault_path(target_dir or ".", allow_root=True, create_root=True)
    if parent.suffix:
        raise NotesError("target_dir must be a directory")
    parent.mkdir(parents=True, exist_ok=True)
    content = _convert_office_with_markitdown(safe_source, file_bytes)
    if not re.match(r"^\s*#\s+", content):
        content = f"# {safe_title}\n\n{content.lstrip()}"
    filename_md = f"{date.today().isoformat()}_{safe_title}.md"
    dest = _unique_path((parent / filename_md).resolve())
    dest.relative_to(vault_root())
    dest.write_text(content, encoding="utf-8")
    payload = _note_payload(dest)
    payload["content"] = content
    payload["imported_from"] = safe_source
    return payload


def search_notes(query: str) -> dict:
    q = str(query or "").strip()
    if not q:
        return {"query": q, "results": []}
    q_lower = q.casefold()
    results = []
    for note in _all_notes():
        if len(results) >= MAX_SEARCH_RESULTS:
            break
        path = _resolve_vault_path(note["path"], require_markdown=True)
        text = ""
        if path.stat().st_size <= MAX_SEARCH_FILE_BYTES:
            text = path.read_text(encoding="utf-8", errors="replace")
        haystack = f"{note['title']}\n{text}".casefold()
        idx = haystack.find(q_lower)
        if idx < 0:
            continue
        source = text or note["title"]
        source_lower = source.casefold()
        src_idx = source_lower.find(q_lower)
        if src_idx < 0:
            src_idx = 0
        start = max(0, src_idx - 48)
        end = min(len(source), src_idx + len(q) + 96)
        snippet = source[start:end].replace("\n", " ").strip()
        result = dict(note)
        result["snippet"] = snippet
        results.append(result)
    return {"query": q, "results": results}


def _content_disposition(filename: str) -> str:
    ascii_name = re.sub(r'[^A-Za-z0-9._-]+', "_", filename).strip("._") or "note.md"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


def _path_suffix(parsed_path: str) -> str:
    if not parsed_path.startswith("/api/notes/"):
        return ""
    suffix = parsed_path[len("/api/notes/"):].strip("/")
    if not suffix:
        return ""
    head = "/" + suffix.split("/", 1)[0]
    if "/api/notes" + head in RESERVED_ENDPOINTS:
        return ""
    return unquote(suffix)


def send_note_download(handler, raw_path: str) -> bool:
    target = _resolve_vault_path(raw_path, require_markdown=True)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError("note not found")
    body = target.read_bytes()
    handler.send_response(200)
    handler.send_header("Content-Type", "text/markdown; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("Content-Disposition", _content_disposition(target.name))
    _security_headers(handler)
    handler.end_headers()
    handler.wfile.write(body)
    return True


def _error_response(handler, exc: Exception) -> bool:
    if isinstance(exc, NotesError):
        return bad(handler, str(exc), status=400)
    if isinstance(exc, FileNotFoundError):
        return bad(handler, str(exc), status=404)
    if isinstance(exc, FileExistsError):
        return bad(handler, str(exc), status=409)
    if isinstance(exc, NotesDependencyError):
        return bad(handler, str(exc), status=501)
    return bad(handler, _sanitize_error(exc), status=500)


def handle_notes_get(handler, parsed) -> bool:
    qs = parse_qs(parsed.query)
    try:
        if parsed.path == "/api/notes/tree":
            return j(handler, notes_tree()) or True
        if parsed.path == "/api/notes":
            return j(handler, list_notes(qs.get("dir", qs.get("path", [""]))[0])) or True
        if parsed.path == "/api/notes/content":
            return j(handler, read_note(qs.get("path", [""])[0])) or True
        if parsed.path == "/api/notes/search":
            return j(handler, search_notes(qs.get("q", [""])[0])) or True
        if parsed.path == "/api/notes/download":
            return send_note_download(handler, qs.get("path", [""])[0])
        if parsed.path == "/api/notes/media":
            return send_note_media(handler, qs.get("path", [""])[0])
        if parsed.path.startswith("/api/notes/download/"):
            return send_note_download(handler, unquote(parsed.path[len("/api/notes/download/"):]))
        suffix = _path_suffix(parsed.path)
        if suffix:
            return j(handler, read_note(suffix)) or True
    except Exception as exc:
        return _error_response(handler, exc)
    return False


def handle_notes_post(handler, parsed, body: dict) -> bool:
    try:
        if parsed.path == "/api/notes":
            return j(
                handler,
                create_note(
                    body.get("title", ""),
                    category=body.get("category") or body.get("dir") or "",
                    content=body.get("content"),
                ),
            ) or True
        if parsed.path == "/api/notes/content":
            return j(handler, update_note(body.get("path", ""), body.get("content", ""))) or True
        if parsed.path == "/api/notes/delete":
            return j(handler, delete_note(body.get("path", ""))) or True
        if parsed.path == "/api/notes/directories":
            return j(handler, create_directory(body.get("parent", ""), body.get("name", ""))) or True
    except Exception as exc:
        return _error_response(handler, exc)
    return False


def handle_notes_put(handler, parsed, body: dict) -> bool:
    try:
        if parsed.path in ("/api/notes/content",) or _path_suffix(parsed.path):
            note_path = body.get("path") or _path_suffix(parsed.path)
            return j(handler, update_note(note_path, body.get("content", ""))) or True
        if parsed.path == "/api/notes/directories":
            return j(handler, rename_directory(body.get("path", ""), body.get("name", ""), body.get("parent") or None)) or True
    except Exception as exc:
        return _error_response(handler, exc)
    return False


def handle_notes_upload(handler) -> bool:
    try:
        content_type = handler.headers.get("Content-Type", "")
        content_length = int(handler.headers.get("Content-Length", 0) or 0)
        if content_length > MAX_UPLOAD_BYTES:
            return j(handler, {"error": f"File too large (max {MAX_UPLOAD_BYTES // 1024 // 1024}MB)"}, status=413) or True
        fields, files = parse_multipart(handler.rfile, content_type, content_length)
        if "file" not in files:
            return bad(handler, "No file field in request", status=400)
        filename, file_bytes = files["file"]
        return j(handler, upload_markdown(filename, file_bytes, fields.get("target_dir", ""))) or True
    except Exception as exc:
        return _error_response(handler, exc)


def handle_notes_asset_upload(handler) -> bool:
    try:
        content_type = handler.headers.get("Content-Type", "")
        content_length = int(handler.headers.get("Content-Length", 0) or 0)
        if content_length > MAX_UPLOAD_BYTES:
            return j(handler, {"error": f"File too large (max {MAX_UPLOAD_BYTES // 1024 // 1024}MB)"}, status=413) or True
        fields, files = parse_multipart(handler.rfile, content_type, content_length)
        if "file" not in files:
            return bad(handler, "No file field in request", status=400)
        filename, file_bytes = files["file"]
        return j(
            handler,
            upload_asset(
                filename,
                file_bytes,
                note_path=fields.get("note_path", ""),
                target_dir=fields.get("target_dir", ""),
            ),
        ) or True
    except Exception as exc:
        return _error_response(handler, exc)


def handle_notes_import(handler) -> bool:
    try:
        content_type = handler.headers.get("Content-Type", "")
        content_length = int(handler.headers.get("Content-Length", 0) or 0)
        if content_length > MAX_UPLOAD_BYTES:
            return j(handler, {"error": f"File too large (max {MAX_UPLOAD_BYTES // 1024 // 1024}MB)"}, status=413) or True
        fields, files = parse_multipart(handler.rfile, content_type, content_length)
        if "file" not in files:
            return bad(handler, "No file field in request", status=400)
        filename, file_bytes = files["file"]
        return j(
            handler,
            import_office_document(
                filename,
                file_bytes,
                target_dir=fields.get("target_dir", ""),
                title=fields.get("title", ""),
            ),
        ) or True
    except Exception as exc:
        return _error_response(handler, exc)


def handle_notes_delete(handler, parsed, body: dict) -> bool:
    qs = parse_qs(parsed.query)
    try:
        if parsed.path == "/api/notes/content":
            return j(handler, delete_note(body.get("path") or qs.get("path", [""])[0])) or True
        if parsed.path == "/api/notes/directories":
            recursive = bool(body.get("recursive") or qs.get("recursive", [""])[0] in {"1", "true", "yes"})
            return j(handler, delete_directory(body.get("path") or qs.get("path", [""])[0], recursive=recursive)) or True
        suffix = _path_suffix(parsed.path)
        if suffix:
            return j(handler, delete_note(body.get("path") or suffix)) or True
    except Exception as exc:
        return _error_response(handler, exc)
    return False
