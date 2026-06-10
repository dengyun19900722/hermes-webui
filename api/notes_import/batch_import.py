from __future__ import annotations

from collections.abc import Callable

from api.notes_import.errors import failure_dict
from api.notes_import.zip_reader import ZipEntry, read_zip_entries


MARKDOWN_SUFFIXES = {".md", ".markdown"}
OFFICE_SUFFIXES = {".docx", ".xlsx", ".pptx"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}

MarkdownImporter = Callable[[ZipEntry, dict[str, ZipEntry]], dict]
OfficeImporter = Callable[[ZipEntry], dict]


def import_archive(
    filename: str,
    file_bytes: bytes,
    *,
    import_markdown: MarkdownImporter,
    import_office: OfficeImporter,
) -> dict:
    read_result = read_zip_entries(filename, file_bytes)
    entries = read_result.entries
    entry_map = {entry.path.as_posix(): entry for entry in entries}
    imported: list[dict] = []
    failed: list[dict] = list(read_result.failed)
    skipped_count = read_result.skipped_count

    for entry in entries:
        try:
            if entry.suffix in MARKDOWN_SUFFIXES:
                payload = import_markdown(entry, entry_map)
            elif entry.suffix in OFFICE_SUFFIXES:
                payload = import_office(entry)
            elif entry.suffix in IMAGE_SUFFIXES:
                skipped_count += 1
                continue
            else:
                failed.append(
                    {
                        "source": entry.source,
                        "stage": "validate",
                        "error": "unsupported file type in batch import",
                    }
                )
                continue
            imported.append(
                {
                    "source": entry.source,
                    "path": payload.get("path", ""),
                    "assets": int(payload.get("asset_count", 0) or len(payload.get("assets", []) or [])),
                }
            )
        except Exception as exc:
            failed.append(failure_dict(entry.source, exc, "import"))

    success_count = len(imported)
    failure_count = len(failed)
    return {
        "ok": failure_count == 0,
        "imported": imported,
        "failed": failed,
        "total": success_count + failure_count,
        "success_count": success_count,
        "failure_count": failure_count,
        "skipped_count": skipped_count,
    }
