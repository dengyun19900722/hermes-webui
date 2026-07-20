"""Tests for session sharing (user-to-user and token-link)."""
import pytest
from pathlib import Path

from api.session_sharing import (
    share_session_to_user, share_session_with_token,
    list_outgoing_shares, list_incoming_shares,
    list_shared_sessions, revoke_share, resolve_share_token,
)
from api.session_store import add_session


@pytest.fixture
def setup_users(tmp_path: Path):
    """Create alice and bob with one session each."""
    sessions_dir = tmp_path / "sessions"
    s1 = add_session(sessions_dir, "alice", {"title": "Alice Chat"})
    s2 = add_session(sessions_dir, "bob", {"title": "Bob Chat"})
    return {"sessions_dir": sessions_dir, "alice_s": s1, "bob_s": s2}


def test_share_to_user(setup_users):
    s = share_session_to_user(
        setup_users["sessions_dir"], "alice", "bob",
        setup_users["alice_s"]["id"]
    )
    assert s["to_user_id"] == "bob"
    assert s["session_id"] == setup_users["alice_s"]["id"]
    assert s["type"] == "user"
    # alice 看到 1 条 outgoing
    assert len(list_outgoing_shares(setup_users["sessions_dir"], "alice")) == 1
    # bob 看到 1 条 incoming
    assert len(list_incoming_shares(setup_users["sessions_dir"], "bob")) == 1


def test_list_shared_sessions_for_bob(setup_users):
    """Bob should see Alice's session in his shared list."""
    share_session_to_user(
        setup_users["sessions_dir"], "alice", "bob",
        setup_users["alice_s"]["id"]
    )
    shared = list_shared_sessions(setup_users["sessions_dir"], "bob")
    assert len(shared) == 1
    assert shared[0]["session"]["id"] == setup_users["alice_s"]["id"]
    assert shared[0]["from_user_id"] == "alice"
    assert shared[0]["session"]["title"] == "Alice Chat"


def test_bob_cannot_see_alice_own_sessions(setup_users):
    """Bob 的 incoming 不会包含 alice 的 outgoing（没有反向）。"""
    share_session_to_user(
        setup_users["sessions_dir"], "alice", "bob",
        setup_users["alice_s"]["id"]
    )
    alice_out = list_outgoing_shares(setup_users["sessions_dir"], "alice")
    bob_in = list_incoming_shares(setup_users["sessions_dir"], "bob")
    assert len(alice_out) == 1
    assert len(bob_in) == 1
    # Alice 的 incoming 应该是空的（她没收到任何分享）
    assert len(list_incoming_shares(setup_users["sessions_dir"], "alice")) == 0


def test_share_with_token(setup_users):
    s = share_session_with_token(
        setup_users["sessions_dir"], "alice",
        setup_users["alice_s"]["id"]
    )
    assert s["type"] == "token"
    assert s["token"] is not None
    assert len(s["token"]) >= 32  # token-urlsafe produces long tokens
    # 通过 token 解析
    resolved = resolve_share_token(setup_users["sessions_dir"], s["token"])
    assert resolved is not None
    assert resolved["session_id"] == setup_users["alice_s"]["id"]
    assert resolved["from_user_id"] == "alice"
    assert resolved["session"]["title"] == "Alice Chat"


def test_resolve_invalid_token_returns_none(setup_users):
    assert resolve_share_token(setup_users["sessions_dir"], "fake-token") is None


def test_revoke_user_share(setup_users):
    s = share_session_to_user(
        setup_users["sessions_dir"], "alice", "bob",
        setup_users["alice_s"]["id"]
    )
    assert revoke_share(setup_users["sessions_dir"], "alice", s["id"]) is True
    assert len(list_outgoing_shares(setup_users["sessions_dir"], "alice")) == 0
    # bob 的 incoming 也应该被同步移除
    assert len(list_incoming_shares(setup_users["sessions_dir"], "bob")) == 0


def test_revoke_nonexistent_share(setup_users):
    assert revoke_share(setup_users["sessions_dir"], "alice", "fake-id") is False


def test_revoke_token_share(setup_users):
    s = share_session_with_token(
        setup_users["sessions_dir"], "alice",
        setup_users["alice_s"]["id"]
    )
    assert revoke_share(setup_users["sessions_dir"], "alice", s["id"]) is True
    # token 现在无法解析
    assert resolve_share_token(setup_users["sessions_dir"], s["token"]) is None


def test_multiple_shares(setup_users):
    """Alice 可以分享给多个用户，每个用户的 incoming 独立。"""
    from api.user_store import add_user
    from pathlib import Path as _P
    state_dir = _P("/tmp")  # 不重要
    add_user(state_dir, {"id": "charlie", "username": "charlie", "password_hash": "x", "role": "user"})
    try:
        share_session_to_user(
            setup_users["sessions_dir"], "alice", "bob",
            setup_users["alice_s"]["id"]
        )
        share_session_to_user(
            setup_users["sessions_dir"], "alice", "charlie",
            setup_users["alice_s"]["id"]
        )
        assert len(list_outgoing_shares(setup_users["sessions_dir"], "alice")) == 2
        assert len(list_incoming_shares(setup_users["sessions_dir"], "bob")) == 1
        assert len(list_incoming_shares(setup_users["sessions_dir"], "charlie")) == 1
    finally:
        # 清理
        from api.user_store import save_users, load_users
        users = load_users(state_dir)
        users = [u for u in users if u.get("id") != "charlie"]
        save_users(state_dir, users)