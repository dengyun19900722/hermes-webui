"""Tests for per-user last_workspace isolation (RBAC §1.1 follow-up).

Before this change, get_last_workspace() read from a single profile-global
last_workspace.txt, so user A's most-recent workspace would bleed into user B's
composer chip and new-session default on the same profile. Now there is a
per-user file fallback chain; even if the per-user file is missing or stale,
the caller can pass allowed_paths to make sure the returned path is one the
caller can actually see.
"""
from pathlib import Path

from api.workspace import (
    _last_workspace_file,
    get_last_workspace,
    set_last_workspace,
)


def _isolate_profile_state(tmp_path, monkeypatch):
    sd = tmp_path / "webui_state"
    sd.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("api.workspace._profile_state_dir", lambda: sd)


def _make_dir(tmp_path: Path, name: str) -> str:
    """Create a real directory under tmp_path and return its absolute path."""
    p = tmp_path / name
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def test_per_user_file_isolates_users(tmp_path, monkeypatch):
    _isolate_profile_state(tmp_path, monkeypatch)
    ws_a = _make_dir(tmp_path, "ws-a")
    ws_b = _make_dir(tmp_path, "ws-b")
    alice = "u-alice"
    bob = "u-bob"

    set_last_workspace(ws_a, alice)
    set_last_workspace(ws_b, bob)

    assert get_last_workspace(alice) == ws_a, "alice should see her own last"
    assert get_last_workspace(bob) == ws_b, "bob should see his own last"
    # Brand new user with no per-user file falls back to profile default,
    # NOT to alice's or bob's leaked value.
    newcomer = get_last_workspace("u-newcomer")
    assert newcomer != ws_a, f"newcomer must not see alice's leak: {newcomer}"
    assert newcomer != ws_b, f"newcomer must not see bob's leak: {newcomer}"


def test_allowed_paths_filter_blocks_stale_or_removed_workspace(tmp_path, monkeypatch):
    _isolate_profile_state(tmp_path, monkeypatch)
    user = "u-x"
    ws_a = _make_dir(tmp_path, "ws-a")
    ws_b = _make_dir(tmp_path, "ws-b")
    set_last_workspace(ws_a, user)

    # Without filter: stale value returned.
    assert get_last_workspace(user) == ws_a
    # With filter that excludes ws_a: caller is NOT handed a workspace
    # they cannot access — the helper refuses to surface it.
    assert get_last_workspace(user, allowed_paths={ws_b}) != ws_a, (
        "filter must NOT leak ws_a when only ws_b is allowed"
    )
    # Caller IS allowed ws_a: value passes the filter.
    assert get_last_workspace(user, allowed_paths={ws_a, ws_b}) == ws_a


def test_empty_allowed_paths_blocks_profile_default_fallback(tmp_path, monkeypatch):
    _isolate_profile_state(tmp_path, monkeypatch)
    profile_default = _make_dir(tmp_path, "profile-default")
    monkeypatch.setattr("api.workspace._profile_default_workspace", lambda: profile_default)

    assert get_last_workspace("u-with-no-access", allowed_paths=set()) == ""


def test_filename_sanitization_strips_path_separators(tmp_path, monkeypatch):
    """Per-user filename must never contain path separators or '..'."""
    _isolate_profile_state(tmp_path, monkeypatch)
    # uuid-shaped id: passes through unchanged.
    f = _last_workspace_file("bb30f8f0-d13a-4247-a776-f1fbd3642d8e")
    assert f.name == "last_workspace_bb30f8f0-d13a-4247-a776-f1fbd3642d8e.txt"
    # Path-traversal id: stripped of '/' and '.', leaves only letters.
    f2 = _last_workspace_file("../../etc/passwd")
    assert "/" not in f2.name, f"path separator leaked: {f2}"
    assert ".." not in f2.name, f"parent traversal leaked: {f2}"
    assert f2.parent == tmp_path / "webui_state"


def test_backwards_compat_global_still_works(tmp_path, monkeypatch):
    """Callers that omit user_id keep reading + writing the legacy global file."""
    _isolate_profile_state(tmp_path, monkeypatch)
    ws = _make_dir(tmp_path, "global-ws")
    set_last_workspace(ws)  # no user_id → writes legacy file
    assert get_last_workspace() == ws
    # And a per-user caller with no per-user file gets the global fallback.
    assert get_last_workspace("u-without-file") == ws


def test_per_user_file_is_preferred_over_global(tmp_path, monkeypatch):
    """When both per-user and global files exist, per-user wins."""
    _isolate_profile_state(tmp_path, monkeypatch)
    global_ws = _make_dir(tmp_path, "global-ws")
    user_ws = _make_dir(tmp_path, "user-ws")
    user = "u-test"

    # Write global first, then per-user.
    set_last_workspace(global_ws)
    set_last_workspace(user_ws, user)

    # user_id caller: prefers per-user file
    assert get_last_workspace(user) == user_ws
    # No-user caller: reads global file
    assert get_last_workspace() == global_ws
