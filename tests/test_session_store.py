"""Tests for per-user session storage."""
import pytest
from pathlib import Path

from api.session_store import (
    load_user_sessions, save_user_sessions,
    list_user_sessions, add_session, get_session,
    delete_session, list_all_sessions_for_admin, update_session,
)


def _setup(tmp_path):
    return tmp_path / "sessions"


def test_empty_returns_no_sessions(tmp_path: Path):
    sessions_dir = _setup(tmp_path)
    assert list_user_sessions(sessions_dir, "u1") == []


def test_add_and_list_session(tmp_path: Path):
    sessions_dir = _setup(tmp_path)
    session = add_session(sessions_dir, "u1", {"title": "Test Chat"})
    assert session["title"] == "Test Chat"
    assert session["owner_id"] == "u1"
    assert "id" in session
    assert "created_at" in session
    listed = list_user_sessions(sessions_dir, "u1")
    assert len(listed) == 1
    assert listed[0]["id"] == session["id"]


def test_session_isolation_between_users(tmp_path: Path):
    """alice 不应看到 bob 的会话，反之亦然。"""
    sessions_dir = _setup(tmp_path)
    add_session(sessions_dir, "alice", {"title": "Alice Chat"})
    add_session(sessions_dir, "bob", {"title": "Bob Chat"})
    alice_sessions = list_user_sessions(sessions_dir, "alice")
    bob_sessions = list_user_sessions(sessions_dir, "bob")
    assert len(alice_sessions) == 1
    assert len(bob_sessions) == 1
    assert alice_sessions[0]["title"] == "Alice Chat"
    assert bob_sessions[0]["title"] == "Bob Chat"


def test_get_session(tmp_path: Path):
    sessions_dir = _setup(tmp_path)
    s = add_session(sessions_dir, "u1", {"title": "T"})
    assert get_session(sessions_dir, "u1", s["id"])["title"] == "T"
    assert get_session(sessions_dir, "u1", "nonexistent") is None


def test_get_session_wrong_user_returns_none(tmp_path: Path):
    sessions_dir = _setup(tmp_path)
    s = add_session(sessions_dir, "u1", {"title": "T"})
    # bob cannot access alice's session
    assert get_session(sessions_dir, "bob", s["id"]) is None


def test_delete_session(tmp_path: Path):
    sessions_dir = _setup(tmp_path)
    s = add_session(sessions_dir, "u1", {"title": "T"})
    assert delete_session(sessions_dir, "u1", s["id"]) is True
    assert get_session(sessions_dir, "u1", s["id"]) is None
    assert delete_session(sessions_dir, "u1", s["id"]) is False  # already gone


def test_update_session(tmp_path: Path):
    sessions_dir = _setup(tmp_path)
    s = add_session(sessions_dir, "u1", {"title": "Old"})
    updated = update_session(sessions_dir, "u1", s["id"], {"title": "New"})
    assert updated is not None
    assert updated["title"] == "New"
    # 磁盘上已更新
    assert get_session(sessions_dir, "u1", s["id"])["title"] == "New"


def test_update_session_not_found(tmp_path: Path):
    sessions_dir = _setup(tmp_path)
    assert update_session(sessions_dir, "u1", "nonexistent", {"title": "x"}) is None


def test_list_all_for_admin(tmp_path: Path):
    sessions_dir = _setup(tmp_path)
    add_session(sessions_dir, "u1", {"title": "A"})
    add_session(sessions_dir, "u2", {"title": "B"})
    all_s = list_all_sessions_for_admin(sessions_dir)
    assert len(all_s) == 2
    titles = {s["title"] for s in all_s}
    assert titles == {"A", "B"}


def test_save_user_sessions_atomic(tmp_path: Path):
    """Atomic write 不应残留 temp 文件。"""
    sessions_dir = _setup(tmp_path)
    save_user_sessions(sessions_dir, "u1", [
        {"id": "s1", "title": "T", "owner_id": "u1", "created_at": "x", "updated_at": "x"}
    ])
    assert (sessions_dir / "u1" / "sessions.json").exists()
    leftover = list((sessions_dir / "u1").glob("sessions.json.tmp*"))
    assert leftover == [], f"leftover temp files: {leftover}"


def test_load_user_sessions_corrupted_file(tmp_path: Path):
    """损坏的 JSON 文件应返回空列表，不抛异常。"""
    sessions_dir = _setup(tmp_path)
    user_dir = sessions_dir / "u1"
    user_dir.mkdir(parents=True, exist_ok=True)
    (user_dir / "sessions.json").write_text("{not valid", encoding="utf-8")
    assert load_user_sessions(sessions_dir, "u1") == []