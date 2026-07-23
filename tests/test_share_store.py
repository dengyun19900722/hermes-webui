"""Unit tests for api.share_store — shares.json CRUD, token lookup, expiry."""
import time
from pathlib import Path

import pytest


@pytest.fixture()
def state_dir(tmp_path: Path) -> Path:
    return tmp_path / "state"


def test_add_user_share_roundtrip(state_dir):
    from api import share_store

    rec = share_store.add_user_share(
        state_dir,
        session_id="sess-1",
        owner_id="alice",
        owner_name="Alice",
        to_user_id="bob",
        to_username="Bob",
    )
    assert rec["type"] == "user"
    assert rec["to_user_id"] == "bob"

    incoming = share_store.list_shares_for_user(state_dir, "bob")
    assert len(incoming) == 1
    assert incoming[0]["session_id"] == "sess-1"
    assert share_store.shared_session_ids_for_user(state_dir, "bob") == {"sess-1"}
    assert share_store.shared_session_ids_for_user(state_dir, "carol") == set()


def test_add_user_share_idempotent(state_dir):
    from api import share_store

    first = share_store.add_user_share(
        state_dir, session_id="sess-1", owner_id="a", owner_name="A",
        to_user_id="bob", to_username="Bob",
    )
    second = share_store.add_user_share(
        state_dir, session_id="sess-1", owner_id="a", owner_name="A",
        to_user_id="bob", to_username="Bob",
    )
    assert first["id"] == second["id"]
    assert len(share_store.list_shares_for_user(state_dir, "bob")) == 1


def test_token_share_create_and_resolve(state_dir):
    from api import share_store

    rec = share_store.add_token_share(
        state_dir, session_id="sess-9", owner_id="alice", owner_name="Alice",
    )
    assert rec["type"] == "token"
    assert rec["token"]

    found = share_store.find_share_by_token(state_dir, rec["token"])
    assert found is not None
    assert found["session_id"] == "sess-9"
    assert share_store.find_share_by_token(state_dir, "nope") is None

    # Reuse: second call returns the same record.
    again = share_store.add_token_share(
        state_dir, session_id="sess-9", owner_id="alice", owner_name="Alice",
    )
    assert again["id"] == rec["id"]
    assert again["token"] == rec["token"]


def test_remove_share(state_dir):
    from api import share_store

    rec = share_store.add_user_share(
        state_dir, session_id="sess-1", owner_id="a", owner_name="A",
        to_user_id="bob", to_username="Bob",
    )
    assert share_store.remove_share(state_dir, rec["id"]) is True
    assert share_store.remove_share(state_dir, rec["id"]) is False
    assert share_store.list_shares_for_user(state_dir, "bob") == []


def test_remove_shares_for_session(state_dir):
    from api import share_store

    share_store.add_user_share(
        state_dir, session_id="sess-1", owner_id="a", owner_name="A",
        to_user_id="bob", to_username="Bob",
    )
    share_store.add_token_share(state_dir, session_id="sess-1", owner_id="a", owner_name="A")
    share_store.add_user_share(
        state_dir, session_id="sess-2", owner_id="a", owner_name="A",
        to_user_id="carol", to_username="Carol",
    )
    removed = share_store.remove_shares_for_session(state_dir, "sess-1")
    assert removed == 2
    assert share_store.list_shares_for_session(state_dir, "sess-1") == []
    assert len(share_store.list_shares_for_session(state_dir, "sess-2")) == 1


def test_expired_share_excluded(state_dir):
    from api import share_store

    past = "2020-01-01T00:00:00Z"
    rec = share_store.add_token_share(
        state_dir, session_id="sess-1", owner_id="a", owner_name="A",
        expires_at=past,
    )
    assert share_store.find_share_by_token(state_dir, rec["token"]) is None
    assert share_store.list_shares_for_session(state_dir, "sess-1") == []


def test_corrupt_file_degrades_to_empty(state_dir):
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "shares.json").write_text("{not json", encoding="utf-8")
    from api import share_store

    share_store.invalidate_cache()
    assert share_store.load_shares(state_dir) == []
    # Recovery: a valid write replaces the corrupt file.
    share_store.add_user_share(
        state_dir, session_id="s", owner_id="a", owner_name="A",
        to_user_id="b", to_username="B",
    )
    assert len(share_store.list_shares_for_user(state_dir, "b")) == 1
