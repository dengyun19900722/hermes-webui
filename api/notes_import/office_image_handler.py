from __future__ import annotations

import base64
import binascii
import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from urllib.parse import unquote_to_bytes

from api.config import MAX_UPLOAD_BYTES


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
OFFICE_MEDIA_PREFIXES = ("word/media/", "xl/media/", "ppt/media/")
_TITLE_RE = re.compile(r"^(.*?)(\s+(?:\"[^\"]*\"|'[^']*'|\([^)]*\)))$", re.DOTALL)
_MIME_EXTENSIONS = {
    "png": ".png",
    "jpg": ".jpg",
    "jpeg": ".jpg",
    "gif": ".gif",
    "webp": ".webp",
}


@dataclass(frozen=True)
class OfficeImage:
    source: str
    filename: str
    data: bytes


@dataclass(frozen=True)
class OfficeDataUriImage:
    index: int
    alt: str
    filename: str
    data: bytes


@dataclass(frozen=True)
class _MarkdownImageLink:
    start: int
    end: int
    alt: str
    destination: str
    title_suffix: str


def _strip_data_uri_wrapper(uri: str) -> str:
    raw = str(uri or "").strip()
    if raw.startswith("<") and raw.endswith(">"):
        return raw[1:-1].strip()
    return raw


def _data_uri_filename(alt: str, index: int, extension: str) -> str:
    stem = PurePosixPath(str(alt or "")).stem.strip() or "image"
    return f"{stem}-{index + 1}{extension}"


def _split_markdown_destination(raw_inner: str) -> tuple[str, str]:
    inner = str(raw_inner or "").strip()
    if inner.startswith("<"):
        end = inner.find(">")
        if end > 0:
            return inner[1:end].strip(), inner[end + 1 :]
    match = _TITLE_RE.match(inner)
    if match:
        return match.group(1).strip(), match.group(2)
    return inner, ""


def _iter_markdown_image_links(markdown: str):
    source = str(markdown or "")
    i = 0
    while i < len(source):
        start = source.find("![", i)
        if start < 0:
            break
        alt_end = -1
        j = start + 2
        while j < len(source):
            char = source[j]
            if char == "\\":
                j += 2
                continue
            if char == "]":
                alt_end = j
                break
            j += 1
        if alt_end < 0 or alt_end + 1 >= len(source) or source[alt_end + 1] != "(":
            i = start + 2
            continue
        depth = 0
        dest_end = -1
        j = alt_end + 2
        while j < len(source):
            char = source[j]
            if char == "\\":
                j += 2
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                if depth == 0:
                    dest_end = j
                    break
                depth -= 1
            j += 1
        if dest_end < 0:
            i = start + 2
            continue
        destination, title_suffix = _split_markdown_destination(source[alt_end + 2 : dest_end])
        yield _MarkdownImageLink(
            start=start,
            end=dest_end + 1,
            alt=source[start + 2 : alt_end],
            destination=destination,
            title_suffix=title_suffix,
        )
        i = dest_end + 1


def _decode_data_uri(destination: str) -> tuple[str, bytes] | None:
    uri = _strip_data_uri_wrapper(destination)
    if not uri.lower().startswith("data:image/"):
        return None
    header, separator, encoded = uri.partition(",")
    if not separator:
        return None
    parts = [part.strip().lower() for part in header[5:].split(";") if part.strip()]
    if not parts or "base64" not in parts[1:]:
        return None
    mime = parts[0]
    if not mime.startswith("image/"):
        return None
    mime_subtype = mime.split("/", 1)[1].split("+", 1)[0]
    extension = _MIME_EXTENSIONS.get(mime_subtype)
    if not extension:
        return None
    encoded = re.sub(r"\s+", "", encoded or "")
    if not encoded:
        return None
    try:
        encoded = unquote_to_bytes(encoded).decode("ascii")
    except UnicodeDecodeError:
        return None
    encoded = encoded.replace("-", "+").replace("_", "/")
    if len(encoded) % 4:
        encoded += "=" * (4 - len(encoded) % 4)
    try:
        return extension, base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError):
        return None


def _is_data_image_destination(destination: str) -> bool:
    return _strip_data_uri_wrapper(destination).lower().startswith("data:image/")


def collect_data_uri_image_indexes(markdown: str) -> list[int]:
    indexes: list[int] = []
    index = -1
    for link in _iter_markdown_image_links(markdown or ""):
        if not _is_data_image_destination(link.destination):
            continue
        index += 1
        indexes.append(index)
    return indexes


def collect_data_uri_images(
    markdown: str,
    *,
    max_total_bytes: int = MAX_UPLOAD_BYTES,
) -> list[OfficeDataUriImage]:
    images: list[OfficeDataUriImage] = []
    total = 0
    index = -1
    for link in _iter_markdown_image_links(markdown or ""):
        if not _is_data_image_destination(link.destination):
            continue
        index += 1
        decoded = _decode_data_uri(link.destination)
        if decoded is None:
            continue
        extension, data = decoded
        total += len(data)
        if total > max_total_bytes:
            break
        images.append(
            OfficeDataUriImage(
                index=index,
                alt=link.alt,
                filename=_data_uri_filename(link.alt, index, extension),
                data=data,
            )
        )
    return images


def rewrite_data_uri_image_links(markdown: str, replacements: dict[int, str]) -> str:
    if not replacements:
        return markdown
    source = str(markdown or "")
    out: list[str] = []
    last = 0
    index = -1
    for link in _iter_markdown_image_links(source):
        if not _is_data_image_destination(link.destination):
            continue
        index += 1
        if index not in replacements:
            continue
        out.append(source[last : link.start])
        out.append(f"![{link.alt}]({replacements[index]}{link.title_suffix})")
        last = link.end
    out.append(source[last:])
    return "".join(out)


def extract_office_images(
    filename: str,
    file_bytes: bytes,
    *,
    max_total_bytes: int = MAX_UPLOAD_BYTES,
) -> list[OfficeImage]:
    suffix = PurePosixPath(str(filename or "")).suffix.lower()
    if suffix not in {".docx", ".xlsx", ".pptx"}:
        return []
    try:
        zf = zipfile.ZipFile(io.BytesIO(file_bytes))
    except zipfile.BadZipFile:
        return []
    images: list[OfficeImage] = []
    total = 0
    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            raw = info.filename.replace("\\", "/")
            lowered = raw.lower()
            if not any(lowered.startswith(prefix) for prefix in OFFICE_MEDIA_PREFIXES):
                continue
            name = PurePosixPath(raw).name
            if PurePosixPath(name).suffix.lower() not in IMAGE_SUFFIXES:
                continue
            if total + max(0, info.file_size) > max_total_bytes:
                break
            data = zf.read(info)
            total += len(data)
            if total > max_total_bytes:
                break
            images.append(OfficeImage(source=raw, filename=name, data=data))
    return images
