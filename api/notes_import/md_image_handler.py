from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import urlsplit

from api.notes_import.paths import resolve_local_reference


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
ATTACHMENT_DIR_NAMES = {"_attachments", "attachments", "assets", "attach", "attachment", "附件", "图片", "图像", "images", "image", "img"}
_IMAGE_RE = re.compile(r"!\[([^\]\n]*)\]\(([^)\n]+)\)")
_WIKILINK_IMAGE_RE = re.compile(r"!\[\[([^\]\n]+)\]\]")
_TITLE_RE = re.compile(r"^(.*?)(\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))$")


@dataclass(frozen=True)
class LocalImageRef:
    index: int
    syntax: str
    alt: str
    destination: str
    title_suffix: str
    resolved_path: PurePosixPath
    candidate_paths: tuple[PurePosixPath, ...]
    filename: str


def _split_destination(raw_inner: str) -> tuple[str, str]:
    inner = str(raw_inner or "").strip()
    if inner.startswith("<"):
        end = inner.find(">")
        if end > 0:
            return inner[1:end].strip(), inner[end + 1 :]
    match = _TITLE_RE.match(inner)
    if match:
        return match.group(1).strip(), match.group(2)
    return inner, ""


def _is_external_destination(destination: str) -> bool:
    raw = str(destination or "").strip()
    if not raw or raw.startswith("#"):
        return True
    lowered = raw.lower()
    if lowered.startswith(("api/notes/media?", "/api/notes/media?", "data:", "mailto:", "tel:")):
        return True
    scheme = urlsplit(raw).scheme.lower()
    return scheme in {"http", "https", "ftp", "file"}


def _path_without_query_fragment(destination: str) -> str:
    return str(destination or "").split("#", 1)[0].split("?", 1)[0]


def _attachment_candidates(source_path: PurePosixPath, asset_ref: str) -> tuple[PurePosixPath, ...]:
    primary = resolve_local_reference(source_path, asset_ref)
    candidates: list[PurePosixPath] = [primary]
    raw = _path_without_query_fragment(asset_ref)
    parts = [part for part in str(raw).replace("\\", "/").split("/") if part and part != "."]
    basename = PurePosixPath(parts[-1]).name if parts else PurePosixPath(raw).name
    if not basename:
        return tuple(candidates)

    source_parent = source_path.parent
    bases = []
    if source_parent != PurePosixPath("."):
        bases.append(source_parent)
    bases.append(PurePosixPath("."))
    for base in bases:
        for dirname in ATTACHMENT_DIR_NAMES:
            candidate = PurePosixPath(dirname) / basename if base == PurePosixPath(".") else base / dirname / basename
            if candidate not in candidates:
                candidates.append(candidate)
    return tuple(candidates)


def collect_local_image_refs(markdown: str, source_path: PurePosixPath) -> list[LocalImageRef]:
    refs: list[LocalImageRef] = []
    index = 0
    for match in _IMAGE_RE.finditer(markdown or ""):
        destination, title_suffix = _split_destination(match.group(2))
        if _is_external_destination(destination):
            continue
        asset_ref = _path_without_query_fragment(destination)
        suffix = PurePosixPath(asset_ref).suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            continue
        candidates = _attachment_candidates(source_path, asset_ref)
        refs.append(
            LocalImageRef(
                index=index,
                syntax="markdown",
                alt=match.group(1),
                destination=destination,
                title_suffix=title_suffix,
                resolved_path=candidates[0],
                candidate_paths=candidates,
                filename=PurePosixPath(asset_ref).name,
            )
        )
        index += 1
    for match in _WIKILINK_IMAGE_RE.finditer(markdown or ""):
        destination = str(match.group(1) or "").strip()
        if "|" in destination:
            destination, alt = destination.split("|", 1)
            alt = alt.strip()
        else:
            alt = PurePosixPath(destination).stem
        asset_ref = _path_without_query_fragment(destination.strip())
        suffix = PurePosixPath(asset_ref).suffix.lower()
        if suffix not in IMAGE_SUFFIXES:
            continue
        candidates = _attachment_candidates(source_path, asset_ref)
        refs.append(
            LocalImageRef(
                index=index,
                syntax="wikilink",
                alt=alt,
                destination=destination.strip(),
                title_suffix="",
                resolved_path=candidates[0],
                candidate_paths=candidates,
                filename=PurePosixPath(asset_ref).name,
            )
        )
        index += 1
    return refs


def rewrite_markdown_image_links(markdown: str, replacements: dict[int, str]) -> str:
    if not replacements:
        return markdown
    counter = -1

    def replace_markdown(match: re.Match) -> str:
        nonlocal counter
        counter += 1
        if counter not in replacements:
            return match.group(0)
        _, title_suffix = _split_destination(match.group(2))
        return f"![{match.group(1)}]({replacements[counter]}{title_suffix})"

    rewritten = _IMAGE_RE.sub(replace_markdown, markdown)

    def replace_wikilink(match: re.Match) -> str:
        nonlocal counter
        counter += 1
        if counter not in replacements:
            return match.group(0)
        inner = str(match.group(1) or "").strip()
        alt = ""
        if "|" in inner:
            _, alt = inner.split("|", 1)
            alt = alt.strip()
        if not alt:
            alt = PurePosixPath(_path_without_query_fragment(inner)).stem
        return f"![{alt}]({replacements[counter]})"

    return _WIKILINK_IMAGE_RE.sub(replace_wikilink, rewritten)
