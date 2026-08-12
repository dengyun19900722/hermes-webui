"""Tests for workspace RBAC: visibility filter, permission gate, owner/members migration.

Covers:
  - visible_workspaces (admin / owner / member filtering, missing-fields fallback)
  - _require_workspace_op (owner pass, admin pass, non-owner raise)
  - _migrate_workspace_access (idempotent, backfill owner from earliest admin)

Run with --noconftest so the test_server fixture doesn't spin up a real server:
    python -m pytest tests/test_workspace_rbac.py -v --no-header \
        -p no:cacheprovider --noconftest
"""
import pytest
from pathlib import Path
from unittest.mock import patch

from api.workspace import (
    visible_workspaces,
    _require_workspace_op,
    _migrate_workspace_access,
    WorkspacePermissionError,
)
from api import workspace as wmod


# ── visible_workspaces ──────────────────────────────────────────────────────


def test_visible_workspaces_admin_sees_all():
    """is_admin=True bypasses owner/member filtering entirely."""
    all_ws = [
        {"path": "/a", "name": "A", "owner": "u1", "members": ["u1"]},
        {"path": "/b", "name": "B", "owner": "u2", "members": ["u2"]},
        {"path": "/c", "name": "C", "owner": "u3", "members": ["u3"]},
    ]
    out = visible_workspaces("u1", is_admin=True, all_ws=all_ws)
    assert out == all_ws


def test_visible_workspaces_user_filters_by_owner_or_member():
    """Non-admin user sees workspaces where they own OR are listed in members."""
    all_ws = [
        {"path": "/a", "name": "A", "owner": "u1", "members": ["u1"]},          # owner
        {"path": "/b", "name": "B", "owner": "u2", "members": ["u2", "u1"]},   # member
        {"path": "/c", "name": "C", "owner": "u3", "members": ["u3"]},          # neither
    ]
    out = visible_workspaces("u1", is_admin=False, all_ws=all_ws)
    paths = {w["path"] for w in out}
    assert paths == {"/a", "/b"}, f"unexpected visibility: {paths}"


def test_visible_workspaces_handles_missing_members():
    """Workspace with owner set but members absent → judged by owner alone."""
    all_ws = [
        {"path": "/a", "name": "A", "owner": "u1"},                              # owner match
        {"path": "/b", "name": "B", "owner": "u2"},                              # owner mismatch
        {"path": "/c", "name": "C", "owner": "u1", "members": []},              # owner match, empty members
    ]
    out = visible_workspaces("u1", is_admin=False, all_ws=all_ws)
    paths = {w["path"] for w in out}
    assert paths == {"/a", "/c"}


# ── _require_workspace_op ──────────────────────────────────────────────────


def test_require_workspace_op_owner_allowed():
    ws = {"path": "/a", "owner": "u1", "members": ["u1"]}
    # Owner should pass without raising.
    _require_workspace_op(ws, {"id": "u1", "role": "user"}, "delete")


def test_require_workspace_op_admin_allowed():
    ws = {"path": "/a", "owner": "u2", "members": ["u2"]}
    # Non-owner admin should still pass.
    _require_workspace_op(ws, {"id": "u3", "role": "admin"}, "delete")


def test_require_workspace_op_random_user_raises():
    from api.workspace import WorkspacePermissionError as _WPE
    ws = {"path": "/a", "owner": "u2", "members": ["u2"]}
    # Non-owner, non-admin user must be rejected.
    with pytest.raises(_WPE):
        _require_workspace_op(ws, {"id": "u1", "role": "user"}, "delete")
    # Also assert it's a PermissionError subclass (handler catch compatibility).
    with pytest.raises(PermissionError):
        _require_workspace_op(ws, {"id": "u1", "role": "user"}, "delete")


# ── _migrate_workspace_access ──────────────────────────────────────────────


def test_migrate_workspace_access_backfills_owner(tmp_path: Path):
    """Workspaces missing owner/members get the earliest admin as owner.

    Two admins exist in users.json — u-admin (created_at 2026-08-01) and
    u-admin2 (created_at 2026-08-03). Migration picks the earliest one.
    """
    from api.user_store import save_users

    save_users(tmp_path, [
        {
            "id": "u-admin", "username": "admin1", "password_hash": "x",
            "role": "admin", "created_at": "2026-08-01T00:00:00", "last_login": None,
        },
        {
            "id": "u-admin2", "username": "admin2", "password_hash": "x",
            "role": "admin", "created_at": "2026-08-03T00:00:00", "last_login": None,
        },
        {
            "id": "u-user", "username": "user1", "password_hash": "x",
            "role": "user", "created_at": "2026-08-02T00:00:00", "last_login": None,
        },
    ])

    workspaces = [
        {"path": "/a", "name": "A"},  # missing both fields
        {"path": "/b", "name": "B", "owner": "u-user", "members": ["u-user"]},  # already filled
    ]

    with patch.object(wmod, "save_workspaces") as save_patch:
        result = _migrate_workspace_access(workspaces, tmp_path)
        save_patch.assert_called_once()

    # /a should be backfilled with the earliest admin as owner and sole member.
    assert result[0]["owner"] == "u-admin"
    assert result[0]["members"] == ["u-admin"]
    # /b unchanged (already had owner/members — idempotency).
    assert result[1]["owner"] == "u-user"
    assert result[1]["members"] == ["u-user"]


def test_migrate_workspace_access_idempotent(tmp_path: Path):
    """Running migration twice on the same data is a no-op the second time.

    First call persists; second call sees both fields present and skips
    save_workspaces / audit_write.
    """
    from api.user_store import save_users

    save_users(tmp_path, [
        {
            "id": "u-admin", "username": "admin", "password_hash": "x",
            "role": "admin", "created_at": "2026-08-01T00:00:00", "last_login": None,
        },
    ])

    workspaces = [{"path": "/a", "name": "A"}]

    # First migration — should persist.
    with patch.object(wmod, "save_workspaces") as save_patch:
        first = _migrate_workspace_access(workspaces, tmp_path)
        assert save_patch.call_count == 1
    assert first[0]["owner"] == "u-admin"

    # Second migration on the already-migrated list — must NOT call save.
    with patch.object(wmod, "save_workspaces") as save_patch:
        second = _migrate_workspace_access(first, tmp_path)
        save_patch.assert_not_called()
    assert second[0] == first[0]


def test_migrate_workspace_access_skips_when_no_admin(tmp_path: Path):
    """If no admin user exists, migration is a no-op (no save, no crash).

    Skipping (vs. guessing) protects against assigning a non-admin as the
    workspace owner on a misconfigured server.
    """
    from api.user_store import save_users

    save_users(tmp_path, [
        {
            "id": "u-user", "username": "alice", "password_hash": "x",
            "role": "user", "created_at": "2026-08-01T00:00:00", "last_login": None,
        },
    ])

    workspaces = [{"path": "/a", "name": "A"}]

    with patch.object(wmod, "save_workspaces") as save_patch:
        result = _migrate_workspace_access(workspaces, tmp_path)
        save_patch.assert_not_called()

    # Workspace untouched — owner/members still absent.
    assert "owner" not in result[0]
    assert "members" not in result[0]