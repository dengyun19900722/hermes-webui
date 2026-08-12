"""End-to-end integration tests for the workspace RBAC flow (Task 11).

These tests verify the *full* data path through the real route handlers
without spinning up a real HTTP server — too slow and the conftest
``test_server`` fixture is blocked by the license check on ``/health``.

The pattern mirrors ``tests/test_workspace_member_ops.py`` (29 tests,
all passing under ``--noconftest``): mock every collaborator that the
handlers call as a module attribute on ``api.routes`` and call the
handlers directly. The handlers themselves are untouched, so this
exercises the same code path a real request would hit.

What we cover end-to-end:

  1. **Full RBAC visibility** — admin creates a workspace, a non-member
     user can't see it, admin grants membership, the user can now see it.
  2. **Member-add permission gate** — non-owner/non-admin gets 403.
  3. **Owner add/remove round trip** — grant then revoke, list count
     tracks.
  4. **Admin ``?view=all``** — admin sees everything plus the
     ``owner_username`` augmentation; non-admin gets 403 on that path.

Run with ``--noconftest`` so the slow ``test_server`` fixture is skipped::

    python -m pytest tests/test_workspace_rbac_integration.py -v \
        --no-header -p no:cacheprovider --noconftest
"""
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from api import routes as rmod


ADMIN = {"id": "u-admin", "username": "admin", "role": "admin"}
USER = {"id": "u-user", "username": "alice", "role": "user"}
STRANGER = {"id": "u-stranger", "username": "mallory", "role": "user"}


class _Parsed:
    """Stand-in for a parsed HTTP request — only the fields the
    workspace handlers consult are populated."""

    def __init__(self, query: str = ""):
        self.path = "/api/workspaces"
        self.query = query


class _State:
    """Mutable per-test scratch for workspaces + captured responses."""

    def __init__(self):
        self.workspaces: list[dict] = []
        self.response_status: int | None = None
        self.response_payload: dict | None = None
        self.error_status: int | None = None
        self.error_msg: str | None = None
        self.last_saved: list[dict] | None = None


def _patch_stack(state: _State, *, user: dict | None, rbac_configured: bool = True,
                 state_dir: Path):
    """Return an ``ExitStack`` that mocks every route-handler collaborator.

    The handlers touch many globals (``_current_rbac_user``, ``_audit``,
    ``find_user_by_id``, ``get_last_workspace``, …). Each is bound at
    *module import* time on ``api.routes``, so ``patch.object(rmod, ...)``
    is the correct hook. The tests must keep the same name set as
    ``tests/test_workspace_member_ops.py`` — if a real handler starts
    reading a new attribute, both files need to be updated together.
    """
    audit = MagicMock()

    def fake_bad(handler, msg, status=400):
        state.error_status = status
        state.error_msg = msg

    def fake_j(handler, payload, status=200, **kwargs):
        state.response_status = status
        state.response_payload = payload

    def fake_save(new_wss):
        state.workspaces = list(new_wss)
        state.last_saved = list(new_wss)

    def fake_find_user(_state_dir, user_id):
        if user_id in {u["id"] for u in (ADMIN, USER, STRANGER)}:
            return next(u for u in (ADMIN, USER, STRANGER) if u["id"] == user_id)
        return None

    stack = ExitStack()
    p = stack.enter_context
    p(patch.object(rmod, "load_workspaces", side_effect=lambda: list(state.workspaces)))
    p(patch.object(rmod, "save_workspaces", side_effect=fake_save))
    p(patch.object(rmod, "_current_rbac_user", return_value=user))
    p(patch.object(rmod, "_current_rbac_user_id",
                   return_value=(user or {}).get("id")))
    p(patch.object(rmod, "_current_rbac_user_is_admin",
                   return_value=(user or {}).get("role") == "admin"))
    p(patch.object(rmod, "_rbac_users_configured", return_value=rbac_configured))
    p(patch.object(rmod, "find_user_by_id", side_effect=fake_find_user))
    p(patch.object(rmod, "_get_state_dir", return_value=state_dir))
    p(patch.object(rmod, "_audit", audit))
    p(patch.object(rmod, "bad", side_effect=fake_bad))
    p(patch.object(rmod, "j", side_effect=fake_j))
    p(patch.object(rmod, "get_last_workspace", return_value=None))
    p(patch.object(rmod, "_terminal_remote_backend_enabled", return_value=False))
    return stack, audit


def _reset_response(state: _State):
    """Clear response captures between sequential handler invocations."""
    state.response_status = None
    state.response_payload = None
    state.error_status = None
    state.error_msg = None


# ── 1. Full RBAC flow: create → grant → see ─────────────────────────────────


def test_admin_create_then_grant_then_user_sees(tmp_path):
    """Admin creates a workspace, ordinary user can't see it yet, admin
    grants membership through the real handler, the user can now see it
    on the next GET.

    This is the headline integration test: it walks the full data path
    handler → list → ``visible_workspaces`` → next handler, mock-free
    apart from the HTTP plumbing.
    """
    state = _State()

    # Persist users.json so the ``view=all`` owner_username lookup has
    # something to read. SAVE not strictly required for this test, but
    # it documents the intended user_store state.
    from api.user_store import save_users
    save_users(tmp_path, [
        {**ADMIN, "password_hash": "x", "created_at": "2026-08-01", "last_login": None},
        {**USER, "password_hash": "x", "created_at": "2026-08-02", "last_login": None},
    ])

    # ── (a) Admin creates a workspace via the real handler ────────────
    real_dir = tmp_path / "proj"
    real_dir.mkdir()
    with _patch_stack(state, user=ADMIN, state_dir=tmp_path)[0]:
        rmod._handle_workspace_add(
            None,
            {"path": str(real_dir), "name": "E2E"},
        )

    assert state.error_status is None, state.error_msg
    assert state.response_status == 200
    assert state.last_saved is not None, "add must persist"
    created = state.workspaces[0]
    assert created["owner"] == ADMIN["id"]
    assert created["members"] == [ADMIN["id"]]

    # ── (b) Ordinary user GETs — must NOT see admin's workspace ───────
    _reset_response(state)
    with _patch_stack(state, user=USER, state_dir=tmp_path)[0]:
        rmod._handle_workspaces_list(None, _Parsed())

    assert state.error_status is None, state.error_msg
    assert state.response_status == 200
    assert state.response_payload["workspaces"] == [], (
        f"user should not see workspaces they are not a member of, "
        f"got {state.response_payload['workspaces']}"
    )
    assert state.response_payload["scope_user_id"] == USER["id"]

    # ── (c) Admin grants membership through the real handler ──────────
    _reset_response(state)
    with _patch_stack(state, user=ADMIN, state_dir=tmp_path)[0]:
        rmod._handle_workspace_member_add(
            None,
            {"path": str(real_dir), "user_id": USER["id"]},
        )

    assert state.error_status is None, state.error_msg
    assert state.response_status == 200
    assert USER["id"] in state.last_saved[0]["members"], (
        f"admin grant must add user to members, got {state.last_saved[0]['members']}"
    )

    # ── (d) User GETs AGAIN — now they can see it ─────────────────────
    _reset_response(state)
    with _patch_stack(state, user=USER, state_dir=tmp_path)[0]:
        rmod._handle_workspaces_list(None, _Parsed())

    assert state.response_status == 200
    assert state.response_payload["scope_user_id"] == USER["id"]
    visible_paths = [w["path"] for w in state.response_payload["workspaces"]]
    assert visible_paths == [str(real_dir)], (
        f"after admin grant, user should see the workspace, got {visible_paths}"
    )


# ── 2. Non-owner non-admin cannot add members (403) ─────────────────────────


def test_non_owner_cannot_grant_membership(tmp_path):
    """A plain user who is neither owner nor admin must get 403 when
    attempting to add a member, and the workspace list must NOT be
    rewritten.
    """
    real_dir = tmp_path / "owned-by-someone-else"
    real_dir.mkdir()
    state = _State()
    state.workspaces = [
        {"path": str(real_dir), "name": "Other", "owner": ADMIN["id"], "members": [ADMIN["id"]]},
    ]

    with _patch_stack(state, user=STRANGER, state_dir=tmp_path)[0]:
        rmod._handle_workspace_member_add(
            None,
            {"path": str(real_dir), "user_id": USER["id"]},
        )

    assert state.error_status == 403, (
        f"stranger must be forbidden, got error_status={state.error_status} "
        f"msg={state.error_msg} response={state.response_payload}"
    )
    assert state.last_saved is None, "a rejected member-add must not rewrite workspaces.json"
    # Original workspace list untouched — no member added.
    assert state.workspaces[0]["members"] == [ADMIN["id"]]


# ── 3. Owner full lifecycle: add → list → remove → list ─────────────────────


def test_owner_grant_then_revoke_round_trip(tmp_path):
    """Owner adds a member, the member sees the workspace, owner revokes,
    the member is blind again. Round-trips the entire owner→member flow.
    """
    real_dir = tmp_path / "round-trip"
    real_dir.mkdir()
    state = _State()
    state.workspaces = [
        {"path": str(real_dir), "name": "RT", "owner": ADMIN["id"], "members": [ADMIN["id"]]},
    ]

    # ── Owner grants USER ─────────────────────────────────────────────
    with _patch_stack(state, user=ADMIN, state_dir=tmp_path)[0]:
        rmod._handle_workspace_member_add(
            None,
            {"path": str(real_dir), "user_id": USER["id"]},
        )
    assert state.last_saved and USER["id"] in state.last_saved[0]["members"]

    # ── USER sees it ──────────────────────────────────────────────────
    _reset_response(state)
    with _patch_stack(state, user=USER, state_dir=tmp_path)[0]:
        rmod._handle_workspaces_list(None, _Parsed())
    assert [w["path"] for w in state.response_payload["workspaces"]] == [str(real_dir)]

    # ── Owner revokes USER ────────────────────────────────────────────
    _reset_response(state)
    with _patch_stack(state, user=ADMIN, state_dir=tmp_path)[0]:
        rmod._handle_workspace_member_remove(
            None,
            {"path": str(real_dir), "user_id": USER["id"]},
        )
    assert state.last_saved and USER["id"] not in state.last_saved[0]["members"]

    # ── USER is blind again ───────────────────────────────────────────
    _reset_response(state)
    with _patch_stack(state, user=USER, state_dir=tmp_path)[0]:
        rmod._handle_workspaces_list(None, _Parsed())
    assert state.response_payload["workspaces"] == [], (
        "after revoke, the ex-member must not see the workspace again"
    )


# ── 4. Admin view=all augmentation ──────────────────────────────────────────


def test_admin_view_all_returns_owner_username(tmp_path):
    """``GET /api/workspaces?view=all`` as admin returns every workspace
    with an ``owner_username`` field resolved against users.json.

    This is the augmentation added in Task 10 — the admin console uses
    it to render "owner: <username>" per row without making the client
    fetch every user.
    """
    from api.user_store import save_users

    save_users(tmp_path, [
        {**ADMIN, "password_hash": "x", "created_at": "2026-08-01", "last_login": None},
        {"id": "u-bob", "username": "bob", "password_hash": "x", "role": "user",
         "created_at": "2026-08-02", "last_login": None},
    ])
    state = _State()
    state.workspaces = [
        {"path": "/a", "name": "A", "owner": ADMIN["id"], "members": [ADMIN["id"]]},
        {"path": "/b", "name": "B", "owner": "u-bob", "members": ["u-bob"]},
    ]

    with _patch_stack(state, user=ADMIN, state_dir=tmp_path)[0]:
        rmod._handle_workspaces_list(None, _Parsed("view=all"))

    assert state.error_status is None, (
        f"admin view=all must not 403, got error={state.error_status} {state.error_msg}"
    )
    assert state.response_status == 200
    assert state.response_payload["view"] == "all"

    by_path = {w["path"]: w for w in state.response_payload["workspaces"]}
    # Workspace /a is owned by the admin user — owner_username comes from
    # the user_store record for ADMIN.
    assert by_path["/a"]["owner_username"] == ADMIN["username"]
    # Workspace /b is owned by u-bob — must be resolved to "bob".
    assert by_path["/b"]["owner_username"] == "bob"


def test_admin_view_all_forbidden_for_non_admin(tmp_path):
    """Non-admin calling ``?view=all`` is rejected with 403, even when
    the caller is itself a member of one of the workspaces.
    """
    state = _State()
    state.workspaces = [
        {"path": "/shared", "name": "Shared", "owner": ADMIN["id"],
         "members": [ADMIN["id"], USER["id"]]},
    ]

    with _patch_stack(state, user=USER, state_dir=tmp_path)[0]:
        rmod._handle_workspaces_list(None, _Parsed("view=all"))

    assert state.error_status == 403, (
        f"non-admin view=all must 403, got error_status={state.error_status} "
        f"msg={state.error_msg}"
    )
    assert state.response_payload is None


# ── 5. Admin without explicit view=all still sees everything (regression) ─


def test_admin_default_view_sees_all_spaces(tmp_path):
    """Even without ``view=all``, an admin caller sees every workspace.
    This is the unfiltered admin path — the legacy behavior we must keep
    so admin tooling that builds on the default view doesn't break.
    """
    state = _State()
    state.workspaces = [
        {"path": "/a", "name": "A", "owner": ADMIN["id"], "members": [ADMIN["id"]]},
        {"path": "/b", "name": "B", "owner": "u-bob", "members": ["u-bob"]},
        {"path": "/c", "name": "C", "owner": "u-carol", "members": ["u-carol"]},
    ]

    with _patch_stack(state, user=ADMIN, state_dir=tmp_path)[0]:
        rmod._handle_workspaces_list(None, _Parsed())

    assert state.response_status == 200
    # The default (non-view=all) response shape omits the ``view`` key —
    # only the explicit ``?view=all`` branch adds it. We only assert on
    # what the contract actually returns.
    assert "view" not in state.response_payload
    paths = sorted(w["path"] for w in state.response_payload["workspaces"])
    assert paths == ["/a", "/b", "/c"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "--noconftest"]))
