"""End-to-end RBAC integration test.

Walks the entire RBAC workflow across all modules:
1. First-time admin initialization
2. Admin creates additional users
3. Users authenticate
4. Sessions are isolated by owner
5. Sessions can be shared (user-to-user + token)
6. Knowledge base docs have creator attribution + ratings
7. Audit log captures all key actions

Uses temp dirs for full isolation. No HTTP server required.
"""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from api.auth import (
    initialize_first_admin, authenticate, create_user_session,
    get_user_from_session, _state_dir, _hash_password,
)
from api.user_store import find_user_by_username, add_user
from api.admin import list_users, create_user, update_user_role, delete_user
from api.session_store import (
    add_session, list_user_sessions, list_all_sessions_for_admin,
    get_session,
)
from api.session_sharing import (
    share_session_to_user, list_shared_sessions, resolve_share_token,
)
from api.obsidian_meta import (
    ensure_meta, add_or_update_rating, compute_rating_summary, get_creator,
)
from api.audit import search


@pytest.fixture
def isolated_world(tmp_path, monkeypatch):
    """Redirect all RBAC state to tmp_path."""
    monkeypatch.setattr("api.auth._state_dir", lambda: tmp_path)
    monkeypatch.setattr("api.admin._state_dir", lambda: tmp_path)
    # 隔离 audit
    import api.audit as audit_mod
    monkeypatch.setattr(audit_mod, "AUDIT_DIR", tmp_path / "audits")
    (tmp_path / "audits").mkdir()
    # 隔离 session 目录
    return tmp_path


def test_full_rbac_flow(isolated_world):
    """完整流程: 初始化 → 创建用户 → 登录 → 隔离 → 分享 → 评分 → 审计。"""
    # 1. 首次部署初始化
    assert not (list_users())
    admin = initialize_first_admin("admin", "admin123")
    assert admin["role"] == "admin"
    assert len(list_users()) == 1

    # 2. admin 创建 alice 和 bob
    alice = create_user("alice", "alice123", "user")
    bob = create_user("bob", "bob123", "user")
    assert len(list_users()) == 3

    # 3. 验证登录
    auth_admin = authenticate("admin", "admin123")
    auth_alice = authenticate("alice", "alice123")
    auth_bob = authenticate("bob", "bob123")
    assert auth_admin and auth_alice and auth_bob
    assert authenticate("alice", "WRONG") is None

    # 4. 会话隔离: alice 创建会话, bob 看不到
    sessions_dir = isolated_world / "sessions"
    alice_session = add_session(sessions_dir, alice["id"], {"title": "Alice Chat"})
    bob_session = add_session(sessions_dir, bob["id"], {"title": "Bob Chat"})

    alice_list = list_user_sessions(sessions_dir, alice["id"])
    bob_list = list_user_sessions(sessions_dir, bob["id"])
    assert len(alice_list) == 1
    assert len(bob_list) == 1
    # 跨用户访问应返回 None
    assert get_session(sessions_dir, alice["id"], bob_session["id"]) is None

    # 5. 分享: alice 分享给 bob
    share = share_session_to_user(
        sessions_dir, alice["id"], bob["id"], alice_session["id"]
    )
    # bob 看到 alice 的分享
    shared_for_bob = list_shared_sessions(sessions_dir, bob["id"])
    assert len(shared_for_bob) == 1
    assert shared_for_bob[0]["from_user_id"] == alice["id"]
    assert shared_for_bob[0]["session"]["title"] == "Alice Chat"

    # 6. Token 分享
    from api.session_sharing import share_session_with_token
    token_share = share_session_with_token(sessions_dir, alice["id"], alice_session["id"])
    resolved = resolve_share_token(sessions_dir, token_share["token"])
    assert resolved is not None
    assert resolved["session"]["title"] == "Alice Chat"

    # 7. 知识库: 文档创建者标记 + 评分
    meta_dir = isolated_world / "knowledge" / ".meta"
    ensure_meta(meta_dir, "故障排查.md",
                creator_id=alice["id"], creator_name="alice")
    creator = get_creator(meta_dir, "故障排查.md")
    assert creator["creator_id"] == alice["id"]
    assert creator["creator_name"] == "alice"

    add_or_update_rating(meta_dir, "故障排查.md", alice["id"], "alice", 5)
    add_or_update_rating(meta_dir, "故障排查.md", bob["id"], "bob", 4)
    add_or_update_rating(meta_dir, "故障排查.md", auth_admin["id"], "admin", 3)
    summary = compute_rating_summary(meta_dir, "故障排查.md")
    assert summary["count"] == 3
    assert summary["average"] == 4.0

    # 8. admin 角色提升
    updated_alice = update_user_role(alice["id"], "admin")
    assert updated_alice["role"] == "admin"
    # 审计: 角色变化 (force flush before search)
    from api.audit import flush
    flush()
    events = search(category="rbac", keyword="user.role_change", limit=10)
    assert any(e["action"] == "user.role_change" for e in events)

    # 9. admin 可查看所有用户的会话
    admin_view = list_all_sessions_for_admin(sessions_dir)
    assert len(admin_view) == 2

    # 10. 完整审计: 应包含 user.create / user.role_change / session.share
    from api.audit import flush
    flush()
    all_events = search(category="rbac", limit=100)
    actions = {e["action"] for e in all_events}
    assert "user.create" in actions
    assert "user.role_change" in actions
    assert "session.share" in actions


def test_admin_user_management_safety(isolated_world):
    """admin 用户管理的安全约束。"""
    initialize_first_admin("root", "root123")
    # 唯一 admin 不能删除
    root_id = list_users()[0]["id"]
    assert delete_user(root_id) is False

    # 创建第二个 admin 后可以删除第一个
    admin2 = create_user("admin2", "admin123", "admin")
    assert delete_user(root_id) is True


def test_session_sharing_revoke_propagates(isolated_world):
    """撤销分享应同时清理对方 incoming。"""
    admin = initialize_first_admin("admin", "admin123")
    alice = create_user("alice", "alice123", "user")
    bob = create_user("bob", "bob123", "user")
    sessions_dir = isolated_world / "sessions"
    s = add_session(sessions_dir, alice["id"], {"title": "S"})
    share = share_session_to_user(sessions_dir, alice["id"], bob["id"], s["id"])
    # bob 看到了
    assert len(list_shared_sessions(sessions_dir, bob["id"])) == 1
    # alice 撤销
    from api.session_sharing import revoke_share
    assert revoke_share(sessions_dir, alice["id"], share["id"]) is True
    # bob 的 incoming 也消失了
    assert len(list_shared_sessions(sessions_dir, bob["id"])) == 0


def test_knowledge_base_ratings_aggregate_correctly(isolated_world):
    """多人评分后 average 准确, 且同一人多次评分只保留最新。"""
    alice = create_user("alice", "alice123", "user")
    bob = create_user("bob", "bob123", "user")
    meta_dir = isolated_world / "meta"

    doc = "01/test.md"
    ensure_meta(meta_dir, doc, creator_id=alice["id"], creator_name="alice")
    add_or_update_rating(meta_dir, doc, alice["id"], "alice", 5)
    add_or_update_rating(meta_dir, doc, alice["id"], "alice", 3)  # 更新为 3
    add_or_update_rating(meta_dir, doc, bob["id"], "bob", 4)
    summary = compute_rating_summary(meta_dir, doc)
    assert summary["count"] == 2  # alice 只记一次
    assert summary["average"] == 3.5  # (3+4)/2


def test_audit_log_records_all_admin_actions(isolated_world):
    initialize_first_admin("admin", "admin123")
    # 创建用户 → user.create 事件
    create_user("alice", "alice123", "user")
    alice_id = find_user_by_username(isolated_world, "alice")["id"]
    # 改角色 → user.role_change 事件
    update_user_role(alice_id, "admin")
    # 删除用户 → user.delete 事件
    delete_user(alice_id)

    from api.audit import flush
    flush()  # 立即写入
    events = search(category="rbac", limit=100)
    actions = [e["action"] for e in events]
    assert "user.create" in actions
    assert "user.role_change" in actions
    assert "user.delete" in actions


def test_session_token_revoke_invalidates_link(isolated_world):
    """token 分享撤销后, link 不再有效。"""
    admin = initialize_first_admin("admin", "admin123")
    alice = create_user("alice", "alice123", "user")
    sessions_dir = isolated_world / "sessions"
    s = add_session(sessions_dir, alice["id"], {"title": "S"})
    from api.session_sharing import share_session_with_token, revoke_share
    share = share_session_with_token(sessions_dir, alice["id"], s["id"])
    assert resolve_share_token(sessions_dir, share["token"]) is not None
    revoke_share(sessions_dir, alice["id"], share["id"])
    assert resolve_share_token(sessions_dir, share["token"]) is None