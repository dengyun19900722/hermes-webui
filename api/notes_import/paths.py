from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import unquote

from api.notes_import.errors import ImportStageError


SYSTEM_NAMES = {"__MACOSX", ".DS_Store", "Thumbs.db", "desktop.ini"}


def clean_archive_member(raw_name: str) -> PurePosixPath:
    raw = str(raw_name or "").replace("\\", "/").strip()
    if not raw or "\x00" in raw:
        raise ImportStageError("validate", "archive member path is empty or invalid")
    if raw.startswith("/"):
        raise ImportStageError("validate", "absolute archive paths are not allowed")
    parts = [part for part in raw.split("/") if part and part != "."]
    if not parts:
        raise ImportStageError("validate", "archive member path is empty")
    if any(part == ".." for part in parts):
        raise ImportStageError("validate", "archive path traversal is not allowed")
    return PurePosixPath(*parts)

def is_hidden_or_system(path: PurePosixPath) -> bool:
    return any(part.startswith(".") or part in SYSTEM_NAMES for part in path.parts)


def resolve_local_reference(source_path: PurePosixPath, raw_ref: str) -> PurePosixPath:
    ref = unquote(str(raw_ref or "").replace("\\", "/").strip())
    if not ref or "\x00" in ref or ref.startswith("/"):
        raise ImportStageError("copy_assets", "invalid local image path")
    base_parts = [] if source_path.parent == PurePosixPath(".") else list(source_path.parent.parts)
    parts: list[str] = []
    for part in [*base_parts, *ref.split("/")]:
        if not part or part == ".":
            continue
        if part == "..":
            if not parts:
                raise ImportStageError("copy_assets", "local image path escapes archive root")
            parts.pop()
            continue
        parts.append(part)
    if not parts:
        raise ImportStageError("copy_assets", "invalid local image path")
    return PurePosixPath(*parts)
