"""Tests for Obsidian vault document metadata (creator + ratings).

Metadata is stored as sidecar JSON files under a configurable meta dir,
keyed by the document's relative path (sanitized to safe filename).
"""
import json
import pytest
from pathlib import Path

from api.obsidian_meta import (
    load_meta, save_meta, ensure_meta,
    get_creator, get_ratings, add_or_update_rating,
    compute_rating_summary, list_all_meta,
)


def test_load_meta_missing(tmp_path: Path):
    meta = load_meta(tmp_path, "doc1.md")
    assert meta == {}


def test_save_and_load_meta(tmp_path: Path):
    save_meta(tmp_path, "doc1.md", {"creator_id": "u1", "creator_name": "alice"})
    loaded = load_meta(tmp_path, "doc1.md")
    assert loaded["creator_id"] == "u1"


def test_ensure_meta_creates(tmp_path: Path):
    meta = ensure_meta(tmp_path, "doc1.md", creator_id="u1", creator_name="alice")
    assert meta["creator_id"] == "u1"
    assert meta["creator_name"] == "alice"
    assert "created_at" in meta
    assert "ratings" in meta
    assert meta["ratings"] == []


def test_ensure_meta_idempotent(tmp_path: Path):
    """已存在元数据时再次调用不应覆盖。"""
    meta1 = ensure_meta(tmp_path, "doc1.md", creator_id="u1", creator_name="alice")
    # 再次调用（即使是不同 creator）
    meta2 = ensure_meta(tmp_path, "doc1.md", creator_id="u2", creator_name="bob")
    assert meta2["creator_id"] == "u1"  # 保留原有
    assert meta2["creator_name"] == "alice"


def test_meta_path_with_subdirs(tmp_path: Path):
    """嵌套路径应被安全编码为单一文件名。"""
    save_meta(tmp_path, "01-故障知识库/test.md", {"creator_id": "u1"})
    loaded = load_meta(tmp_path, "01-故障知识库/test.md")
    assert loaded["creator_id"] == "u1"


def test_get_creator_present(tmp_path: Path):
    ensure_meta(tmp_path, "doc1.md", creator_id="u1", creator_name="alice")
    creator = get_creator(tmp_path, "doc1.md")
    assert creator == {"creator_id": "u1", "creator_name": "alice"}


def test_get_creator_missing(tmp_path: Path):
    assert get_creator(tmp_path, "nonexistent.md") is None


def test_get_ratings_empty(tmp_path: Path):
    assert get_ratings(tmp_path, "doc1.md") == []


def test_add_rating(tmp_path: Path):
    add_or_update_rating(tmp_path, "doc1.md", "u1", "alice", 5)
    add_or_update_rating(tmp_path, "doc1.md", "u2", "bob", 3)
    ratings = get_ratings(tmp_path, "doc1.md")
    assert len(ratings) == 2
    rating_values = sorted(r["rating"] for r in ratings)
    assert rating_values == [3, 5]


def test_update_existing_rating(tmp_path: Path):
    add_or_update_rating(tmp_path, "doc1.md", "u1", "alice", 5)
    add_or_update_rating(tmp_path, "doc1.md", "u1", "alice", 2)  # 修改
    ratings = get_ratings(tmp_path, "doc1.md")
    assert len(ratings) == 1
    assert ratings[0]["rating"] == 2


def test_invalid_rating_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        add_or_update_rating(tmp_path, "doc1.md", "u1", "alice", 0)
    with pytest.raises(ValueError):
        add_or_update_rating(tmp_path, "doc1.md", "u1", "alice", 6)
    with pytest.raises(ValueError):
        add_or_update_rating(tmp_path, "doc1.md", "u1", "alice", -1)


def test_compute_rating_summary_empty(tmp_path: Path):
    summary = compute_rating_summary(tmp_path, "doc1.md")
    assert summary == {"count": 0, "average": 0.0}


def test_compute_rating_summary_aggregates(tmp_path: Path):
    add_or_update_rating(tmp_path, "doc1.md", "u1", "alice", 5)
    add_or_update_rating(tmp_path, "doc1.md", "u2", "bob", 4)
    add_or_update_rating(tmp_path, "doc1.md", "u3", "charlie", 3)
    summary = compute_rating_summary(tmp_path, "doc1.md")
    assert summary["count"] == 3
    assert summary["average"] == 4.0


def test_list_all_meta(tmp_path: Path):
    ensure_meta(tmp_path, "doc1.md", creator_id="u1", creator_name="alice")
    ensure_meta(tmp_path, "doc2.md", creator_id="u2", creator_name="bob")
    all_meta = list_all_meta(tmp_path)
    assert len(all_meta) == 2
    paths = {m["_path"] for m in all_meta}
    assert paths == {"doc1.md", "doc2.md"}