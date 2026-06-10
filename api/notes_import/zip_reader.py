from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import PurePosixPath

from api.config import MAX_UPLOAD_BYTES
from api.notes_import.errors import ImportStageError, failure_dict
from api.notes_import.paths import clean_archive_member, is_hidden_or_system


MAX_ARCHIVE_EXTRACTED_BYTES = 10 * MAX_UPLOAD_BYTES
_UTF8_FILENAME_FLAG = 0x800
_CP437_MOJIBAKE_CHARS = set("ÇüéâäàåçêëèïîìÄÅÉæÆôöòûùÿÖÜ¢£¥₧ƒáíóúñÑªº¿⌐¬½¼¡«»░▒▓│┤ÁÂÀ©╣║╗╝╜╛┐└┴┬├─┼ãÃ╚╔╩╦╠═╬¤ðÐÊËÈıÍÎÏ┘┌█▄¦Ì▀ÓßÔÒõÕµþÞÚÛÙýÝ¯´≡±‗¾¶§÷¸°¨·¹³²■")


def _has_cjk(text: str) -> bool:
    return any(
        "\u3400" <= ch <= "\u4dbf"
        or "\u4e00" <= ch <= "\u9fff"
        or "\uf900" <= ch <= "\ufaff"
        for ch in text
    )


def _mojibake_score(text: str) -> int:
    return sum(1 for ch in text if ch in _CP437_MOJIBAKE_CHARS or ch == "\ufffd")


def _decode_legacy_zip_name(info: zipfile.ZipInfo) -> str:
    """Recover non-UTF-8 ZIP member names from common Chinese archive tools."""
    name = str(info.filename or "")
    if info.flag_bits & _UTF8_FILENAME_FLAG:
        return name
    try:
        raw = name.encode("cp437")
    except UnicodeEncodeError:
        return name

    candidates = [name]
    for encoding in ("utf-8", "gb18030", "big5"):
        try:
            decoded = raw.decode(encoding)
        except UnicodeDecodeError:
            continue
        if decoded not in candidates:
            candidates.append(decoded)

    def score(candidate: str) -> int:
        value = 0
        if _has_cjk(candidate):
            value += 12
        value -= _mojibake_score(candidate) * 3
        if "\x00" in candidate:
            value -= 100
        return value

    best = max(candidates, key=score)
    if score(best) > score(name):
        return best
    return name


@dataclass(frozen=True)
class ZipEntry:
    source: str
    path: PurePosixPath
    filename: str
    suffix: str
    data: bytes


@dataclass
class ZipReadResult:
    entries: list[ZipEntry]
    failed: list[dict]
    skipped_count: int = 0


def read_zip_entries(
    filename: str,
    file_bytes: bytes,
    *,
    max_total_bytes: int = MAX_ARCHIVE_EXTRACTED_BYTES,
) -> ZipReadResult:
    if not str(filename or "").lower().endswith(".zip"):
        raise ImportStageError("validate", "batch import requires a .zip archive")
    entries: list[ZipEntry] = []
    failed: list[dict] = []
    skipped_count = 0
    seen: set[str] = set()
    total_read = 0
    try:
        zf = zipfile.ZipFile(io.BytesIO(file_bytes))
    except zipfile.BadZipFile as exc:
        raise ImportStageError("validate", "invalid zip archive") from exc

    with zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            source = _decode_legacy_zip_name(info)
            try:
                rel_path = clean_archive_member(source)
                key = rel_path.as_posix()
                if key in seen:
                    raise ImportStageError("validate", "duplicate archive member path")
                seen.add(key)
                if is_hidden_or_system(rel_path):
                    skipped_count += 1
                    continue
                if total_read + max(0, info.file_size) > max_total_bytes:
                    raise ImportStageError("validate", "archive contents exceed import size limit")
                with zf.open(info) as src:
                    data = src.read(max_total_bytes - total_read + 1)
                total_read += len(data)
                if total_read > max_total_bytes:
                    raise ImportStageError("validate", "archive contents exceed import size limit")
                entries.append(
                    ZipEntry(
                        source=key,
                        path=rel_path,
                        filename=rel_path.name,
                        suffix=rel_path.suffix.lower(),
                        data=data,
                    )
                )
            except Exception as exc:
                failed.append(failure_dict(source, exc, "validate"))
    return ZipReadResult(entries=entries, failed=failed, skipped_count=skipped_count)
