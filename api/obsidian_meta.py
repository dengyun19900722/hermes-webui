"""Obsidian vault document metadata (sidecar .meta.json files).

Stores per-document metadata (creator, ratings, etc.) as sidecar JSON
files. The meta_dir is typically {vault_root}/.meta/ — kept outside the
vault proper so Obsidian doesn't try to render it.

Path encoding: document paths like "01-故障知识库/test.md" are flattened
to a single filename-safe key by replacing '/' with '__'. This avoids
filesystem traversal issues and keeps each doc's meta in a single file.
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def _meta_path(meta_dir: Path, doc_rel_path: str) -> Path:
    """Get the sidecar meta file path for a document.

    Path separators in the document path are encoded as double-underscore
    so nested paths produce a single meta file rather than a directory
    tree mirroring the vault.
    """
    safe = doc_rel_path.replace("/", "__").replace("\\", "__")
    return meta_dir / f"{safe}.meta.json"


def load_meta(meta_dir: Path, doc_rel_path: str) -> dict[str, Any]:
    """Load metadata for a document. Returns empty dict if missing or corrupt."""
    path = _meta_path(meta_dir, doc_rel_path)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_meta(meta_dir: Path, doc_rel_path: str, meta: dict) -> None:
    """Atomically save metadata."""
    meta_dir.mkdir(parents=True, exist_ok=True)
    path = _meta_path(meta_dir, doc_rel_path)
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp.replace(path)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def ensure_meta(
    meta_dir: Path, doc_rel_path: str,
    *, creator_id: str, creator_name: str
) -> dict:
    """Ensure metadata exists with creator info. Idempotent — won't overwrite.

    If the document already has metadata (e.g. it was created before this
    function was called), returns the existing record unchanged. This
    protects creator attribution from accidental overwrites when the
    document is touched by a non-creator user.
    """
    existing = load_meta(meta_dir, doc_rel_path)
    if existing:
        return existing
    meta = {
        "creator_id": creator_id,
        "creator_name": creator_name,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "ratings": [],
    }
    save_meta(meta_dir, doc_rel_path, meta)
    return meta


def get_creator(meta_dir: Path, doc_rel_path: str) -> dict | None:
    """Return {creator_id, creator_name} or None if no metadata exists."""
    meta = load_meta(meta_dir, doc_rel_path)
    if "creator_id" in meta:
        return {
            "creator_id": meta["creator_id"],
            "creator_name": meta.get("creator_name", ""),
        }
    return None


def get_ratings(meta_dir: Path, doc_rel_path: str) -> list[dict]:
    """Return list of rating records for a document."""
    meta = load_meta(meta_dir, doc_rel_path)
    ratings = meta.get("ratings", [])
    return ratings if isinstance(ratings, list) else []


def add_or_update_rating(
    meta_dir: Path, doc_rel_path: str,
    user_id: str, username: str, rating: int
) -> dict:
    """Add or update a user's rating. Returns the rating record.

    Raises ValueError if rating is not in [1, 5]. One rating per user —
    subsequent calls for the same user_id update the existing record
    rather than appending a new one.
    """
    if not isinstance(rating, int) or not (1 <= rating <= 5):
        raise ValueError("rating must be an integer between 1 and 5")
    meta = load_meta(meta_dir, doc_rel_path)
    if "ratings" not in meta or not isinstance(meta["ratings"], list):
        meta["ratings"] = []
    now = datetime.utcnow().isoformat() + "Z"
    # 查找现有评分
    existing = next(
        (r for r in meta["ratings"] if r.get("user_id") == user_id),
        None,
    )
    if existing:
        existing["rating"] = rating
        existing["updated_at"] = now
        record = existing
    else:
        record = {
            "user_id": user_id,
            "username": username,
            "rating": rating,
            "created_at": now,
        }
        meta["ratings"].append(record)
    save_meta(meta_dir, doc_rel_path, meta)
    return record


def compute_rating_summary(meta_dir: Path, doc_rel_path: str) -> dict:
    """Return {count, average} for a document's ratings.

    Returns count=0, average=0.0 when no ratings exist.
    """
    ratings = get_ratings(meta_dir, doc_rel_path)
    if not ratings:
        return {"count": 0, "average": 0.0}
    total = sum(r.get("rating", 0) for r in ratings)
    return {"count": len(ratings), "average": round(total / len(ratings), 2)}


def list_all_meta(meta_dir: Path) -> list[dict]:
    """List all metadata records under meta_dir.

    Each result includes a synthesized "_path" field with the original
    document path (decoded from the safe filename).
    """
    if not meta_dir.exists():
        return []
    results = []
    for meta_file in meta_dir.glob("*.meta.json"):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        stem = meta_file.name[:-len(".meta.json")]
        doc_path = stem.replace("__", "/")
        results.append({"_path": doc_path, **meta})
    return results