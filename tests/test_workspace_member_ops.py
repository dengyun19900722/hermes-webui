"""RBAC gating for workspace write handlers + member add/remove (Task 5).

Run standalone (the project conftest spawns a real server and is far too slow
for these pure-unit tests)::

    python -m pytest tests/test_workspace_member_ops.py -v --noconftest

Patch style: every collaborator the handlers touch (``load_workspaces``,
``save_workspaces``, ``_current_rbac_user``, ``find_user_by_id``, ``_audit``)
is a *module attribute* of ``api.routes``, so ``patch.object(rmod, ...)`` is
the correct hook. Note this file patches ``_current_rbac_user`` — routes.py has
no ``_current_user``; that name lives in ``api.rbac_routes``.
"""

from contextlib import ExitStack
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from api import routes as rmod


OWNER = {"id": "u-owner", "role": "user"}
ADMIN = {"id": "u-admin", "role": "admin"}
STRANGER = {"id": "u-stranger", "role": "user"}


def _ws(path="/a", name="A", owner="u-owner", members=None):
    return {
        "path": path,
        "name": name,
        "owner": owner,
        "members": list(members) if members is not None else [owner],
    }


class Captured:
    """Records what the handler sent instead of touching a real HTTP handler."""

    def __init__(self):
        self.status = None
        self.payload = None
        self.error = None
        self.saved = None
        self.audit = None


def _invoke(fn, body, user=OWNER, workspaces=None, known_users=("u-new", "u-other"),
            parsed=None, rbac_configured=True):
    """Call a workspace handler with every collaborator mocked out.

    Returns a :class:`Captured` describing the response and the persisted state.
    """
    cap = Captured()
    wss = workspaces if workspaces is not None else [_ws()]

    def fake_bad(handler, msg, status=400):
        cap.status = status
        cap.error = msg

    def fake_j(handler, payload, status=200, **kwargs):
        cap.status = status
        cap.payload = payload

    def fake_save(new_wss):
        cap.saved = new_wss

    def fake_find_user(state_dir, user_id):
        return {"id": user_id} if user_id in known_users else None

    audit = MagicMock()

    with ExitStack() as stack:
        p = stack.enter_context
        p(patch.object(rmod, "load_workspaces", return_value=wss))
        p(patch.object(rmod, "save_workspaces", side_effect=fake_save))
        p(patch.object(rmod, "_current_rbac_user", return_value=user))
        p(patch.object(rmod, "_current_rbac_user_id",
                       return_value=(user or {}).get("id")))
        p(patch.object(rmod, "_current_rbac_user_is_admin",
                       return_value=(user or {}).get("role") == "admin"))
        p(patch.object(rmod, "_rbac_users_configured", return_value=rbac_configured))
        p(patch.object(rmod, "find_user_by_id", side_effect=fake_find_user))
        p(patch.object(rmod, "_get_state_dir", return_value=Path("/tmp/state")))
        p(patch.object(rmod, "_audit", audit))
        p(patch.object(rmod, "bad", side_effect=fake_bad))
        p(patch.object(rmod, "j", side_effect=fake_j))
        p(patch.object(rmod, "get_last_workspace", return_value="/a"))
        p(patch.object(rmod, "_terminal_remote_backend_enabled", return_value=False))
        if parsed is not None:
            fn(None, parsed)
        else:
            fn(None, body)

    cap.audit = audit
    return cap


# ── _handle_workspace_member_add ────────────────────────────────────────────

def test_member_add_owner_can_add():
    """Owner adds a user — 200, members grows, audit written."""
    cap = _invoke(rmod._handle_workspace_member_add,
                  {"path": "/a", "user_id": "u-new"}, user=OWNER)

    assert cap.status == 200, cap.error
    assert cap.payload["workspaces"][0]["members"] == ["u-owner", "u-new"]
    assert cap.saved is not None, "member add must persist"
    cap.audit.write.assert_called_once()
    kwargs = cap.audit.write.call_args.kwargs
    assert kwargs["action"] == "workspace.member_add"
    assert kwargs["member_id"] == "u-new"
    assert kwargs["actor_id"] == "u-owner"


def test_member_add_admin_can_add_workspace_they_do_not_own():
    """Admin is not the owner and not a member — still allowed."""
    cap = _invoke(rmod._handle_workspace_member_add,
                  {"path": "/a", "user_id": "u-new"}, user=ADMIN)

    assert cap.status == 200, cap.error
    assert "u-new" in cap.payload["workspaces"][0]["members"]


def test_member_add_non_owner_forbidden():
    """A plain user who is not the owner gets 403 and nothing is saved."""
    cap = _invoke(rmod._handle_workspace_member_add,
                  {"path": "/a", "user_id": "u-new"}, user=STRANGER)

    assert cap.status == 403
    assert cap.saved is None, "403 must not persist a change"
    cap.audit.write.assert_not_called()


def test_member_add_existing_member_who_is_not_owner_still_forbidden():
    """Membership alone does not grant the right to add other members."""
    cap = _invoke(rmod._handle_workspace_member_add,
                  {"path": "/a", "user_id": "u-new"},
                  user=STRANGER,
                  workspaces=[_ws(members=["u-owner", "u-stranger"])])

    assert cap.status == 403
    assert cap.saved is None


def test_member_add_unknown_user_404():
    """user_id that no user record matches → 404, no mutation."""
    cap = _invoke(rmod._handle_workspace_member_add,
                  {"path": "/a", "user_id": "u-ghost"}, user=OWNER)

    assert cap.status == 404
    assert cap.saved is None
    cap.audit.write.assert_not_called()


def test_member_add_permission_checked_before_user_existence():
    """A non-owner must not be able to probe which user ids exist.

    Both a bogus id and a real id must produce the same 403, never a 404.
    """
    ghost = _invoke(rmod._handle_workspace_member_add,
                    {"path": "/a", "user_id": "u-ghost"}, user=STRANGER)
    real = _invoke(rmod._handle_workspace_member_add,
                   {"path": "/a", "user_id": "u-new"}, user=STRANGER)

    assert ghost.status == 403
    assert real.status == 403


def test_member_add_is_idempotent():
    """Adding an existing member does not duplicate the entry."""
    cap = _invoke(rmod._handle_workspace_member_add,
                  {"path": "/a", "user_id": "u-new"},
                  user=OWNER,
                  workspaces=[_ws(members=["u-owner", "u-new"])])

    assert cap.status == 200, cap.error
    assert cap.payload["workspaces"][0]["members"].count("u-new") == 1


def test_member_add_unknown_workspace_404():
    cap = _invoke(rmod._handle_workspace_member_add,
                  {"path": "/nope", "user_id": "u-new"}, user=ADMIN)
    assert cap.status == 404


def test_member_add_missing_user_id_400():
    cap = _invoke(rmod._handle_workspace_member_add, {"path": "/a"}, user=OWNER)
    assert cap.status == 400


# ── _handle_workspace_member_remove ─────────────────────────────────────────

def test_member_remove_owner_can_remove():
    cap = _invoke(rmod._handle_workspace_member_remove,
                  {"path": "/a", "user_id": "u-other"},
                  user=OWNER,
                  workspaces=[_ws(members=["u-owner", "u-other"])])

    assert cap.status == 200, cap.error
    assert cap.payload["workspaces"][0]["members"] == ["u-owner"]
    cap.audit.write.assert_called_once()
    assert cap.audit.write.call_args.kwargs["action"] == "workspace.member_remove"


def test_member_remove_cannot_remove_owner():
    """Removing the owner would orphan the workspace → 400, no mutation."""
    cap = _invoke(rmod._handle_workspace_member_remove,
                  {"path": "/a", "user_id": "u-owner"},
                  user=OWNER,
                  workspaces=[_ws(members=["u-owner", "u-other"])])

    assert cap.status == 400
    assert cap.saved is None
    cap.audit.write.assert_not_called()


def test_member_remove_admin_cannot_remove_owner_either():
    """The owner guard is not an authorization check — it binds admins too."""
    cap = _invoke(rmod._handle_workspace_member_remove,
                  {"path": "/a", "user_id": "u-owner"},
                  user=ADMIN,
                  workspaces=[_ws(members=["u-owner", "u-other"])])

    assert cap.status == 400
    assert cap.saved is None


def test_member_remove_non_owner_forbidden():
    cap = _invoke(rmod._handle_workspace_member_remove,
                  {"path": "/a", "user_id": "u-other"},
                  user=STRANGER,
                  workspaces=[_ws(members=["u-owner", "u-other"])])

    assert cap.status == 403
    assert cap.saved is None


# ── _handle_workspace_remove ────────────────────────────────────────────────

def test_workspace_remove_owner_allowed():
    cap = _invoke(rmod._handle_workspace_remove, {"path": "/a"}, user=OWNER,
                  workspaces=[_ws(), _ws(path="/b", name="B", owner="u-other")])

    assert cap.status == 200, cap.error
    assert [w["path"] for w in cap.payload["workspaces"]] == ["/b"]
    cap.audit.write.assert_called_once()
    assert cap.audit.write.call_args.kwargs["action"] == "workspace.remove"


def test_workspace_remove_admin_allowed():
    cap = _invoke(rmod._handle_workspace_remove, {"path": "/a"}, user=ADMIN)
    assert cap.status == 200, cap.error
    assert cap.payload["workspaces"] == []


def test_workspace_remove_non_owner_forbidden():
    cap = _invoke(rmod._handle_workspace_remove, {"path": "/a"}, user=STRANGER)

    assert cap.status == 403
    assert cap.saved is None, "a rejected delete must not rewrite workspaces.json"


def test_workspace_remove_unknown_path_404():
    cap = _invoke(rmod._handle_workspace_remove, {"path": "/nope"}, user=ADMIN)
    assert cap.status == 404


# ── _handle_workspace_rename ────────────────────────────────────────────────

def test_workspace_rename_owner_allowed():
    cap = _invoke(rmod._handle_workspace_rename,
                  {"path": "/a", "name": "Renamed"}, user=OWNER)

    assert cap.status == 200, cap.error
    assert cap.payload["workspaces"][0]["name"] == "Renamed"
    cap.audit.write.assert_called_once()
    kwargs = cap.audit.write.call_args.kwargs
    assert kwargs["action"] == "workspace.rename"
    assert kwargs["old_name"] == "A" and kwargs["new_name"] == "Renamed"


def test_workspace_rename_admin_allowed():
    cap = _invoke(rmod._handle_workspace_rename,
                  {"path": "/a", "name": "Renamed"}, user=ADMIN)
    assert cap.status == 200, cap.error
    assert cap.payload["workspaces"][0]["name"] == "Renamed"


def test_workspace_rename_non_owner_forbidden():
    cap = _invoke(rmod._handle_workspace_rename,
                  {"path": "/a", "name": "Hijacked"}, user=STRANGER)

    assert cap.status == 403
    assert cap.saved is None


def test_workspace_rename_missing_name_400():
    cap = _invoke(rmod._handle_workspace_rename, {"path": "/a"}, user=OWNER)
    assert cap.status == 400


# ── GET /api/workspaces filtering ───────────────────────────────────────────

class _Parsed:
    def __init__(self, query=""):
        self.path = "/api/workspaces"
        self.query = query


def test_list_filters_to_caller_membership():
    """A plain user sees only workspaces they own or belong to."""
    cap = _invoke(rmod._handle_workspaces_list, None, user=STRANGER,
                  workspaces=[
                      _ws(path="/a", owner="u-owner"),
                      _ws(path="/b", owner="u-owner", members=["u-owner", "u-stranger"]),
                      _ws(path="/c", owner="u-stranger"),
                  ],
                  parsed=_Parsed())

    assert cap.status == 200, cap.error
    assert [w["path"] for w in cap.payload["workspaces"]] == ["/b", "/c"]


def test_list_admin_sees_everything_without_view_all():
    cap = _invoke(rmod._handle_workspaces_list, None, user=ADMIN,
                  workspaces=[_ws(path="/a"), _ws(path="/b", owner="u-other")],
                  parsed=_Parsed())

    assert cap.status == 200, cap.error
    assert len(cap.payload["workspaces"]) == 2


def test_list_view_all_requires_admin():
    cap = _invoke(rmod._handle_workspaces_list, None, user=STRANGER,
                  parsed=_Parsed("view=all"))
    assert cap.status == 403


def test_list_view_all_admin_returns_unfiltered():
    cap = _invoke(rmod._handle_workspaces_list, None, user=ADMIN,
                  workspaces=[_ws(path="/a"), {"path": "/legacy", "name": "L"}],
                  parsed=_Parsed("view=all"))

    assert cap.status == 200, cap.error
    assert [w["path"] for w in cap.payload["workspaces"]] == ["/a", "/legacy"]


def test_list_unfiltered_when_rbac_not_configured():
    """Legacy single-user deploy: filtering would hide every workspace."""
    cap = _invoke(rmod._handle_workspaces_list, None, user=None,
                  workspaces=[{"path": "/a", "name": "A"}],
                  parsed=_Parsed(),
                  rbac_configured=False)

    assert cap.status == 200, cap.error
    assert [w["path"] for w in cap.payload["workspaces"]] == ["/a"]


# ── _handle_workspace_add ───────────────────────────────────────────────────

def _invoke_add(body, user=OWNER, workspaces=None, tmp_path=None):
    """_handle_workspace_add needs a real, validatable directory."""
    cap = Captured()
    wss = workspaces if workspaces is not None else []
    audit = MagicMock()

    def fake_bad(handler, msg, status=400):
        cap.status, cap.error = status, msg

    def fake_j(handler, payload, status=200, **kwargs):
        cap.status, cap.payload = status, payload

    with ExitStack() as stack:
        p = stack.enter_context
        p(patch.object(rmod, "load_workspaces", return_value=wss))
        p(patch.object(rmod, "save_workspaces",
                       side_effect=lambda n: setattr(cap, "saved", n)))
        p(patch.object(rmod, "_current_rbac_user", return_value=user))
        p(patch.object(rmod, "_audit", audit))
        p(patch.object(rmod, "bad", side_effect=fake_bad))
        p(patch.object(rmod, "j", side_effect=fake_j))
        rmod._handle_workspace_add(None, body)

    cap.audit = audit
    return cap


def test_workspace_add_sets_owner_and_members(tmp_path):
    """The creator becomes owner and sole member."""
    d = tmp_path / "proj"
    d.mkdir()
    cap = _invoke_add({"path": str(d), "name": "Proj"}, user=OWNER)

    assert cap.status == 200, cap.error
    entry = cap.payload["workspaces"][0]
    assert entry["owner"] == "u-owner"
    assert entry["members"] == ["u-owner"]
    cap.audit.write.assert_called_once()
    assert cap.audit.write.call_args.kwargs["action"] == "workspace.add"


def test_workspace_add_without_rbac_user_omits_owner(tmp_path):
    """No authenticated user → leave owner unset so migration can backfill."""
    d = tmp_path / "proj2"
    d.mkdir()
    cap = _invoke_add({"path": str(d), "name": "P2"}, user=None)

    assert cap.status == 200, cap.error
    entry = cap.payload["workspaces"][0]
    assert "owner" not in entry and "members" not in entry


# ── Integration: add member → visible in list → remove → invisible ──────────

def test_member_lifecycle_end_to_end():
    """Owner grants access, the new member's list shows it, revoke hides it."""
    state = [_ws(path="/a", owner="u-owner")]
    newcomer = {"id": "u-new", "role": "user"}

    # Before: newcomer sees nothing.
    before = _invoke(rmod._handle_workspaces_list, None, user=newcomer,
                     workspaces=[dict(w, members=list(w["members"])) for w in state],
                     parsed=_Parsed())
    assert before.payload["workspaces"] == []

    # Owner adds the newcomer.
    added = _invoke(rmod._handle_workspace_member_add,
                    {"path": "/a", "user_id": "u-new"}, user=OWNER,
                    workspaces=[dict(w, members=list(w["members"])) for w in state])
    assert added.status == 200, added.error
    state = added.saved
    assert "u-new" in state[0]["members"]

    # Newcomer now sees it.
    during = _invoke(rmod._handle_workspaces_list, None, user=newcomer,
                     workspaces=[dict(w, members=list(w["members"])) for w in state],
                     parsed=_Parsed())
    assert [w["path"] for w in during.payload["workspaces"]] == ["/a"]

    # Owner revokes.
    removed = _invoke(rmod._handle_workspace_member_remove,
                      {"path": "/a", "user_id": "u-new"}, user=OWNER,
                      workspaces=[dict(w, members=list(w["members"])) for w in state])
    assert removed.status == 200, removed.error
    state = removed.saved

    # Newcomer is blind again.
    after = _invoke(rmod._handle_workspaces_list, None, user=newcomer,
                    workspaces=[dict(w, members=list(w["members"])) for w in state],
                    parsed=_Parsed())
    assert after.payload["workspaces"] == []


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v", "--noconftest"]))
