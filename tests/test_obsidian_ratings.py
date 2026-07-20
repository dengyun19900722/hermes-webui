"""Integration tests for the rating flow on knowledge base documents.

These tests exercise the same API surface that will be exposed via HTTP
routes, ensuring the rating workflow behaves correctly end-to-end without
needing the full HTTP stack.
"""
import pytest
from pathlib import Path

from api.obsidian_meta import (
    add_or_update_rating, get_ratings, compute_rating_summary, ensure_meta,
)


def test_full_rating_flow(tmp_path: Path):
    """3 个用户评价同一文档 → 平均分正确。"""
    doc = "01-故障知识库/test.md"
    add_or_update_rating(tmp_path, doc, "u1", "alice", 5)
    add_or_update_rating(tmp_path, doc, "u2", "bob", 4)
    add_or_update_rating(tmp_path, doc, "u3", "charlie", 3)

    ratings = get_ratings(tmp_path, doc)
    assert len(ratings) == 3

    summary = compute_rating_summary(tmp_path, doc)
    assert summary["count"] == 3
    assert summary["average"] == 4.0


def test_user_can_only_rate_once(tmp_path: Path):
    """同一用户多次评分 → 只保留最新。"""
    doc = "test.md"
    add_or_update_rating(tmp_path, doc, "u1", "alice", 5)
    add_or_update_rating(tmp_path, doc, "u1", "alice", 1)  # 修改
    ratings = get_ratings(tmp_path, doc)
    assert len(ratings) == 1
    assert ratings[0]["rating"] == 1
    assert ratings[0]["username"] == "alice"


def test_creator_can_also_rate(tmp_path: Path):
    """创建者本人也可以评价自己的文档。"""
    doc = "test.md"
    ensure_meta(tmp_path, doc, creator_id="u1", creator_name="alice")
    add_or_update_rating(tmp_path, doc, "u1", "alice", 5)
    ratings = get_ratings(tmp_path, doc)
    assert len(ratings) == 1
    assert ratings[0]["user_id"] == "u1"


def test_rating_with_unicode_username(tmp_path: Path):
    """用户名支持非 ASCII。"""
    doc = "test.md"
    add_or_update_rating(tmp_path, doc, "u1", "运维小张", 4)
    ratings = get_ratings(tmp_path, doc)
    assert ratings[0]["username"] == "运维小张"


def test_rating_persisted_across_reads(tmp_path: Path):
    """评分写入磁盘后, 重新读取应得到一致结果。"""
    doc = "test.md"
    add_or_update_rating(tmp_path, doc, "u1", "alice", 4)
    # 强制重新读取（绕过 in-memory cache）
    from api.obsidian_meta import load_meta
    meta = load_meta(tmp_path, doc)
    assert len(meta["ratings"]) == 1
    assert meta["ratings"][0]["rating"] == 4


def test_multiple_documents_independent(tmp_path: Path):
    """不同文档的评分相互独立。"""
    add_or_update_rating(tmp_path, "doc1.md", "u1", "alice", 5)
    add_or_update_rating(tmp_path, "doc2.md", "u1", "alice", 2)

    r1 = get_ratings(tmp_path, "doc1.md")
    r2 = get_ratings(tmp_path, "doc2.md")
    assert len(r1) == 1 and r1[0]["rating"] == 5
    assert len(r2) == 1 and r2[0]["rating"] == 2

    s1 = compute_rating_summary(tmp_path, "doc1.md")
    s2 = compute_rating_summary(tmp_path, "doc2.md")
    assert s1 == {"count": 1, "average": 5.0}
    assert s2 == {"count": 1, "average": 2.0}