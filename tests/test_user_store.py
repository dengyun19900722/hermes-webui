"""Tests for users.json-backed user store."""
import json
import pytest
from pathlib import Path

from api.user_store import (
    load_users, save_users, find_user_by_username, find_user_by_id, add_user,
)


def test_load_users_empty(tmp_path: Path):
    assert load_users(tmp_path) == []


def test_save_and_load_users(tmp_path: Path):
    users = [{"id": "u1", "username": "alice", "password_hash": "x", "role": "user"}]
    save_users(tmp_path, users)
    assert load_users(tmp_path) == users


def test_find_user_by_username(tmp_path: Path):
    users = [
        {"id": "u1", "username": "alice", "password_hash": "x", "role": "user"},
        {"id": "u2", "username": "bob", "password_hash": "y", "role": "admin"},
    ]
    save_users(tmp_path, users)
    assert find_user_by_username(tmp_path, "alice")["id"] == "u1"
    assert find_user_by_username(tmp_path, "bob")["role"] == "admin"
    assert find_user_by_username(tmp_path, "nobody") is None


def test_find_user_by_id(tmp_path: Path):
    users = [
        {"id": "u1", "username": "alice", "password_hash": "x", "role": "user"},
        {"id": "u2", "username": "bob", "password_hash": "y", "role": "admin"},
    ]
    save_users(tmp_path, users)
    assert find_user_by_id(tmp_path, "u1")["username"] == "alice"
    assert find_user_by_id(tmp_path, "u999") is None


def test_add_user_creates_id(tmp_path: Path):
    user = add_user(tmp_path, {"username": "alice", "password_hash": "x", "role": "user"})
    assert "id" in user
    assert user["username"] == "alice"
    assert user["role"] == "user"
    # 持久化到磁盘
    assert find_user_by_username(tmp_path, "alice") is not None


def test_add_user_appends_to_existing(tmp_path: Path):
    add_user(tmp_path, {"username": "alice", "password_hash": "x", "role": "user"})
    add_user(tmp_path, {"username": "bob", "password_hash": "y", "role": "admin"})
    users = load_users(tmp_path)
    assert len(users) == 2
    assert {u["username"] for u in users} == {"alice", "bob"}


def test_save_users_is_atomic(tmp_path: Path):
    """Atomic write: temp file + replace, no .tmp left over on success."""
    save_users(tmp_path, [{"id": "u1", "username": "alice", "password_hash": "x", "role": "user"}])
    assert (tmp_path / "users.json").exists()
    # 不应残留 temp 文件
    leftover = list(tmp_path.glob("users.json.tmp*"))
    assert leftover == [], f"leftover temp files: {leftover}"


def test_load_corrupted_file_returns_empty(tmp_path: Path):
    """Corrupted JSON → empty list (don't crash startup)."""
    (tmp_path / "users.json").write_text("{not valid json", encoding="utf-8")
    assert load_users(tmp_path) == []


def test_load_non_dict_file_returns_empty(tmp_path: Path):
    """Top-level array (not dict) → empty list."""
    (tmp_path / "users.json").write_text("[1, 2, 3]", encoding="utf-8")
    assert load_users(tmp_path) == []