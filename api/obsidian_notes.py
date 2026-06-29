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

from api.config import KNOWLEDGE_IMPORT_MAX_BYTES, MAX_UPLOAD_BYTES
from api.helpers import _sanitize_error, _security_headers, bad, j
from api.notes_import.errors import friendly_error
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
    "/api/notes/import/batch",
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
    return import_markdown_document(filename, file_bytes, target_dir=target_dir)


def _import_parent_dir(target_dir: str | None, source_rel_path: PurePosixPath | None = None) -> Path:
    parent = _resolve_vault_path(target_dir or ".", allow_root=True, create_root=True)
    if parent.suffix:
        raise NotesError("target_dir must be a directory")
    if source_rel_path:
        for part in source_rel_path.parent.parts:
            if part in {"", "."}:
                continue
            parent = (parent / _safe_dir_name(part)).resolve()
            parent.relative_to(vault_root())
    parent.mkdir(parents=True, exist_ok=True)
    return parent


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


def _note_asset_dir(note_dest: Path) -> Path:
    asset_dir = (note_dest.parent / ASSET_DIR_NAME / _safe_filename_stem(note_dest.stem)).resolve()
    asset_dir.relative_to(vault_root())
    asset_dir.mkdir(parents=True, exist_ok=True)
    return asset_dir


def _write_note_asset(filename: str, file_bytes: bytes, note_dest: Path) -> dict:
    safe_name = _safe_asset_name(filename)
    asset_dir = _note_asset_dir(note_dest)
    dest = _unique_path((asset_dir / safe_name).resolve())
    dest.relative_to(vault_root())
    dest.write_bytes(file_bytes)
    return {
        "name": dest.name,
        "path": _relative(dest),
        "relative_path": _relative_between(dest, note_dest.parent),
        "size": dest.stat().st_size,
    }


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


def import_markdown_document(
    filename: str,
    file_bytes: bytes,
    *,
    target_dir: str | None = None,
    source_rel_path: PurePosixPath | None = None,
    asset_loader=None,
) -> dict:
    from api.notes_import.errors import ImportStageError
    from api.notes_import.md_image_handler import collect_local_image_refs, rewrite_markdown_image_links
    from api.notes_import.office_image_handler import collect_data_uri_images, rewrite_data_uri_image_links

    source_path = source_rel_path or PurePosixPath(Path(filename).name)
    safe_name = _safe_upload_name(source_path.name)
    parent = _import_parent_dir(target_dir, source_path if source_rel_path else None)
    dest = (parent / safe_name).resolve()
    dest.relative_to(vault_root())
    if dest.exists():
        raise FileExistsError("note already exists")

    content = file_bytes.decode("utf-8-sig", errors="replace")
    data_uri_images = collect_data_uri_images(content)
    data_uri_replacements: dict[int, str] = {}
    assets: list[dict] = []
    for image in data_uri_images:
        try:
            asset = _write_note_asset(image.filename, image.data, dest)
        except Exception as exc:
            raise ImportStageError("copy_assets", str(exc)) from exc
        assets.append(asset)
        data_uri_replacements[image.index] = asset["relative_path"]
    generated_asset_refs = set(data_uri_replacements.values())
    if data_uri_replacements:
        content = rewrite_data_uri_image_links(content, data_uri_replacements)

    refs = collect_local_image_refs(content, source_path)
    replacements: dict[int, str] = {}
    resolved_assets = []
    if asset_loader:
        for ref in refs:
            if ref.destination in generated_asset_refs:
                continue
            image_bytes = None
            try:
                image_bytes = asset_loader(ref.resolved_path)
            except KeyError:
                for candidate_path in ref.candidate_paths:
                    if candidate_path == ref.resolved_path:
                        continue
                    try:
                        image_bytes = asset_loader(candidate_path)
                        break
                    except KeyError:
                        continue
            if image_bytes is None:
                raise ImportStageError("copy_assets", f"local image not found: {ref.destination}")
            resolved_assets.append((ref, image_bytes))
    for ref, image_bytes in resolved_assets:
        try:
            asset = _write_note_asset(ref.filename, image_bytes, dest)
        except Exception as exc:
            raise ImportStageError("copy_assets", str(exc)) from exc
        assets.append(asset)
        replacements[ref.index] = asset["relative_path"]
    if replacements:
        content = rewrite_markdown_image_links(content, replacements)

    dest.write_text(content, encoding="utf-8")
    payload = _note_payload(dest)
    payload["content"] = content
    payload["imported_from"] = source_path.as_posix()
    payload["assets"] = assets
    payload["asset_count"] = len(assets)
    return payload


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
    source_rel_path: PurePosixPath | None = None,
) -> dict:
    from api.notes_import.office_image_handler import (
        collect_data_uri_image_indexes,
        collect_data_uri_images,
        extract_office_images,
        rewrite_data_uri_image_links,
    )

    safe_source = _safe_office_name(filename)
    safe_title = _safe_filename_stem(title or Path(safe_source).stem)
    parent = _import_parent_dir(target_dir, source_rel_path)
    content = _convert_office_with_markitdown(safe_source, file_bytes)
    if not re.match(r"^\s*#\s+", content):
        content = f"# {safe_title}\n\n{content.lstrip()}"
    filename_md = f"{date.today().isoformat()}_{safe_title}.md"
    dest = _unique_path((parent / filename_md).resolve())
    dest.relative_to(vault_root())
    data_uri_images = collect_data_uri_images(content)
    replacements: dict[int, str] = {}
    assets = []
    replaced_data_uri_indexes = set()
    for image in data_uri_images:
        asset = _write_note_asset(image.filename, image.data, dest)
        assets.append(asset)
        replacements[image.index] = asset["relative_path"]
        replaced_data_uri_indexes.add(image.index)
    if replacements:
        content = rewrite_data_uri_image_links(content, replacements)

    data_uri_payloads = {image.data for image in data_uri_images}
    embedded_assets = []
    extracted_images = extract_office_images(safe_source, file_bytes)
    remaining_data_uri_indexes = collect_data_uri_image_indexes(content)
    fallback_replacements: dict[int, str] = {}
    fallback_cursor = 0
    for index in remaining_data_uri_indexes:
        while fallback_cursor < len(extracted_images) and extracted_images[fallback_cursor].data in data_uri_payloads:
            fallback_cursor += 1
        if fallback_cursor >= len(extracted_images):
            break
        image = extracted_images[fallback_cursor]
        fallback_cursor += 1
        asset = _write_note_asset(image.filename, image.data, dest)
        assets.append(asset)
        data_uri_payloads.add(image.data)
        fallback_replacements[index] = asset["relative_path"]
    if fallback_replacements:
        content = rewrite_data_uri_image_links(content, fallback_replacements)

    for image in extracted_images:
        if image.data in data_uri_payloads:
            continue
        embedded_assets.append(_write_note_asset(image.filename, image.data, dest))
    assets.extend(embedded_assets)
    if embedded_assets:
        lines = [f"![{Path(asset['name']).stem}]({asset['relative_path']})" for asset in embedded_assets]
        content = content.rstrip() + "\n\n## 附件图片\n\n" + "\n".join(lines) + "\n"
    dest.write_text(content, encoding="utf-8")
    payload = _note_payload(dest)
    payload["content"] = content
    payload["imported_from"] = source_rel_path.as_posix() if source_rel_path else safe_source
    payload["assets"] = assets
    payload["asset_count"] = len(assets)
    return payload


def import_batch_archive(filename: str, file_bytes: bytes, *, target_dir: str | None = None) -> dict:
    from api.notes_import.batch_import import import_archive
    from api.notes_import.errors import ImportStageError

    def load_archive_asset(path: PurePosixPath, entry_map: dict[str, object]) -> bytes:
        entry = entry_map.get(path.as_posix())
        if entry is None:
            raise KeyError(path.as_posix())
        return entry.data

    def import_markdown_entry(entry, entry_map: dict[str, object]) -> dict:
        return import_markdown_document(
            entry.filename,
            entry.data,
            target_dir=target_dir,
            source_rel_path=entry.path,
            asset_loader=lambda path: load_archive_asset(path, entry_map),
        )

    def import_office_entry(entry) -> dict:
        try:
            return import_office_document(
                entry.filename,
                entry.data,
                target_dir=target_dir,
                source_rel_path=entry.path,
            )
        except NotesDependencyError as exc:
            raise ImportStageError("convert", str(exc)) from exc

    return import_archive(
        filename,
        file_bytes,
        import_markdown=import_markdown_entry,
        import_office=import_office_entry,
    )


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


def _has_image_references(md_text: str) -> bool:
    """检查 Markdown 正文是否包含图片引用（标准 ![]() 或 wikilink ![][]）。"""
    import re
    if re.search(r'!\[.*?\]\(', md_text):
        return True
    if re.search(r'!\[\[.*?\]\]', md_text):
        return True
    return False


def send_note_download(handler, raw_path: str, *, as_zip: bool = False) -> bool:
    import logging
    _log = logging.getLogger(__name__)
    _log.warning("[download] send_note_download 被调用: raw_path=%r, as_zip=%s", raw_path, as_zip)
    target = _resolve_vault_path(raw_path, require_markdown=True)
    if not target.exists() or not target.is_file():
        raise FileNotFoundError("note not found")
    md_bytes = target.read_bytes()
    md_text = md_bytes.decode("utf-8", errors="replace")

    # 后端兜底：即使前端没传 zip=1，只要正文有图片引用就自动切 ZIP
    if not as_zip and _has_image_references(md_text):
        _log.warning("[download] 检测到图片引用，自动切换为 ZIP 模式")
        as_zip = True

    if as_zip:
        import zipfile
        import io as _io
        vault = vault_root()
        note_dir = target.parent
        _log.warning("[zip] 笔记路径: %s, note_dir: %s", target, note_dir)
        buf = _io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(target.name, md_text.encode("utf-8"))
            # 扫描 MD 中的图片引用: ![alt](path) 和 ![[path]]
            # 使用平衡括号解析，避免路径中含 ) 时截断
            _images = []
            _pos = 0
            while _pos < len(md_text):
                _m = re.search(r'!\[([^\]]*)\]\(', md_text[_pos:])
                if _m:
                    _alt = _m.group(1)
                    _start = _pos + _m.end()
                    _depth = 1
                    _j = _start
                    while _j < len(md_text) and _depth > 0:
                        if md_text[_j] == '(':
                            _depth += 1
                        elif md_text[_j] == ')':
                            _depth -= 1
                        _j += 1
                    if _depth == 0:
                        _dest = md_text[_start:_j-1]
                        _images.append(_dest)
                        _log.warning("[zip] 发现标准图片: alt=%r, dest=%r", _alt, _dest)
                    _pos = _j
                else:
                    break
            # ![[wikilink]] 路径不含括号，可以用简单 regex
            for _wm in re.finditer(r'!\[\[([^\]]+)\]\]', md_text):
                _wikilink = _wm.group(1)
                _parts = _wikilink.split("|", 1)
                _images.append(_parts[0].strip())
                _log.warning("[zip] 发现维基链接图片: %r", _parts[0].strip())
            _log.warning("[zip] 共发现 %d 个图片引用", len(_images))
            for _img in _images:
                try:
                    _img_clean = _img.replace("\\", "/").strip()
                    _ip = (note_dir / Path(_img_clean)).resolve()
                    _ip.relative_to(vault)  # 确保不越狱
                    if _ip.exists() and _ip.is_file():
                        _arcname = _relative_between(_ip, note_dir)
                        zf.write(str(_ip), _arcname)
                        _log.warning("[zip] 已添加图片: %s -> arcname=%s", _ip, _arcname)
                    else:
                        _log.warning("[zip] 图片文件不存在: %s", _ip)
                except Exception as _exc:
                    _log.warning("[zip] 图片处理失败: %s, 错误: %s", _img, _exc)
        payload = buf.getvalue()
        handler.send_response(200)
        handler.send_header("Content-Type", "application/zip")
        handler.send_header("Content-Length", str(len(payload)))
        handler.send_header("Cache-Control", "no-store")
        _stem = target.stem or "note"
        handler.send_header("Content-Disposition", f'attachment; filename="{_stem}.zip"')
    else:
        payload = md_bytes
        handler.send_response(200)
        handler.send_header("Content-Type", "text/markdown; charset=utf-8")
        handler.send_header("Content-Length", str(len(payload)))
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Content-Disposition", _content_disposition(target.name))
    _security_headers(handler)
    handler.end_headers()
    handler.wfile.write(payload)
    return True


def _error_response(handler, exc: Exception) -> bool:
    if isinstance(exc, NotesError):
        return bad(handler, friendly_error(str(exc)), status=400)
    if isinstance(exc, FileNotFoundError):
        return bad(handler, friendly_error(str(exc)), status=404)
    if isinstance(exc, FileExistsError):
        return bad(handler, friendly_error(str(exc)), status=409)
    if isinstance(exc, NotesDependencyError):
        return bad(handler, friendly_error(str(exc)), status=501)
    return bad(handler, friendly_error(_sanitize_error(exc)), status=500)


def _reject_oversized_upload(handler, content_length: int, max_bytes: int) -> bool:
    if content_length <= max_bytes:
        return False
    max_mb = max_bytes // 1024 // 1024
    return j(handler, {"error": friendly_error(f"File too large (max {max_mb}MB)")}, status=413) or True


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
            _zip_mode = qs.get("zip", [""])[0] in ("1", "true", "yes")
            return send_note_download(handler, qs.get("path", [""])[0], as_zip=_zip_mode)
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
        if _reject_oversized_upload(handler, content_length, KNOWLEDGE_IMPORT_MAX_BYTES):
            return True
        fields, files = parse_multipart(handler.rfile, content_type, content_length)
        if "file" not in files:
            return bad(handler, friendly_error("No file field in request"), status=400)
        filename, file_bytes = files["file"]
        return j(handler, upload_markdown(filename, file_bytes, fields.get("target_dir", ""))) or True
    except Exception as exc:
        return _error_response(handler, exc)


def handle_notes_asset_upload(handler) -> bool:
    try:
        content_type = handler.headers.get("Content-Type", "")
        content_length = int(handler.headers.get("Content-Length", 0) or 0)
        if _reject_oversized_upload(handler, content_length, MAX_UPLOAD_BYTES):
            return True
        fields, files = parse_multipart(handler.rfile, content_type, content_length)
        if "file" not in files:
            return bad(handler, friendly_error("No file field in request"), status=400)
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
        if _reject_oversized_upload(handler, content_length, KNOWLEDGE_IMPORT_MAX_BYTES):
            return True
        fields, files = parse_multipart(handler.rfile, content_type, content_length)
        if "file" not in files:
            return bad(handler, friendly_error("No file field in request"), status=400)
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


def handle_notes_batch_import(handler) -> bool:
    try:
        content_type = handler.headers.get("Content-Type", "")
        content_length = int(handler.headers.get("Content-Length", 0) or 0)
        if _reject_oversized_upload(handler, content_length, KNOWLEDGE_IMPORT_MAX_BYTES):
            return True
        fields, files = parse_multipart(handler.rfile, content_type, content_length)
        archive = files.get("archive") or files.get("file")
        if not archive:
            return bad(handler, friendly_error("No archive field in request"), status=400)
        filename, file_bytes = archive
        return j(
            handler,
            import_batch_archive(
                filename,
                file_bytes,
                target_dir=fields.get("target_dir", ""),
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
