import io
import json
import pathlib
import sqlite3
import time
from types import SimpleNamespace
from urllib.parse import urlparse

import api.profiles as profiles
import api.routes as routes
import pytest


def test_sidebar_state_db_overrides_fail_fast_while_database_is_locked(tmp_path):
    from api import models

    db = tmp_path / "state.db"
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY,
            source TEXT,
            title TEXT,
            message_count INTEGER DEFAULT 0
        );
        CREATE TABLE messages (session_id TEXT, timestamp REAL);
        INSERT INTO sessions (id, source, title, message_count)
        VALUES ('locked', 'webui', 'Locked', 1);
        """
    )
    conn.commit()
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("BEGIN EXCLUSIVE")

    started = time.monotonic()
    result = models._read_state_db_sidebar_overrides(db, {"locked"}, {"locked"})
    elapsed = time.monotonic() - started

    conn.rollback()
    conn.close()
    assert result == {}
    assert elapsed < 0.5, f"locked sidebar override read blocked for {elapsed:.3f}s"


@pytest.fixture(autouse=True)
def _clear_session_list_cache_between_tests():
    routes._session_list_cache_clear()
    yield
    routes._session_list_cache_clear()


class _FakeHandler:
    def __init__(self):
        self.status = None
        self.headers = {}
        self.wfile = io.BytesIO()

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.headers[key] = value

    def end_headers(self):
        pass

    def json_body(self):
        return json.loads(self.wfile.getvalue().decode("utf-8"))


def _sessions_payload_rows():
    return [
        {
            "session_id": "visible-active",
            "title": "Visible active",
            "profile": "default",
            "archived": False,
            "message_count": 3,
            "updated_at": 30,
            "last_message_at": 30,
        },
        {
            "session_id": "archived-history",
            "title": "Archived history",
            "profile": "default",
            "archived": True,
            "message_count": 4,
            "updated_at": 20,
            "last_message_at": 20,
        },
        {
            "session_id": "other-profile",
            "title": "Other profile",
            "profile": "other",
            "archived": False,
            "message_count": 5,
            "updated_at": 10,
            "last_message_at": 10,
        },
    ]


def test_sessions_api_enriches_only_returned_rows_by_default(monkeypatch):
    all_sessions_kwargs = []
    enriched_batches = []

    def fake_all_sessions(**kwargs):
        all_sessions_kwargs.append(kwargs)
        return _sessions_payload_rows()

    def fake_enrich(rows):
        enriched_batches.append([row["session_id"] for row in rows])
        for row in rows:
            row["_lineage_root_id"] = row["session_id"]

    monkeypatch.setattr(routes, "all_sessions", fake_all_sessions)
    monkeypatch.setattr(routes, "_enrich_sidebar_lineage_metadata", fake_enrich)
    monkeypatch.setattr(routes, "_reconcile_stale_stream_state_for_session_rows", lambda rows: False)
    monkeypatch.setattr(routes, "load_settings", lambda: {"show_cli_sessions": False})
    monkeypatch.setattr(profiles, "get_active_profile_name", lambda: "default")
    routes._session_list_cache_clear()

    handler = _FakeHandler()
    routes.handle_get(handler, urlparse("http://example.com/api/sessions"))

    assert handler.status == 200
    body = handler.json_body()
    assert [row["session_id"] for row in body["sessions"]] == ["visible-active"]
    assert body["archived_count"] == 1
    assert body["archived_webui_count"] == 1
    assert body["include_archived"] is False
    assert enriched_batches == [["visible-active"]]
    assert all_sessions_kwargs[0]["include_lineage_metadata"] is False


def test_initial_session_limit_bounds_state_db_count_budget(monkeypatch):
    calls = []

    def fake_all_sessions(**kwargs):
        calls.append(kwargs)
        return [{
            "session_id": "visible",
            "title": "Visible",
            "profile": "default",
            "archived": False,
            "message_count": 1,
            "updated_at": 1,
            "last_message_at": 1,
        }]

    monkeypatch.setattr(routes, "all_sessions", fake_all_sessions)
    monkeypatch.setattr(routes, "_enrich_sidebar_lineage_metadata", lambda _rows: None)
    monkeypatch.setattr(routes, "_reconcile_stale_stream_state_for_session_rows", lambda _rows: False)
    monkeypatch.setattr(routes, "load_settings", lambda: {"show_cli_sessions": False})
    monkeypatch.setattr(profiles, "get_active_profile_name", lambda: "default")
    handler = _FakeHandler()

    routes.handle_get(handler, urlparse(
        "http://example.com/api/sessions?sidebar_source=webui&limit=120"
    ))

    assert handler.status == 200
    assert calls[0]["state_db_override_top_n"] == 120


def test_sessions_api_fetches_archived_rows_only_when_requested(monkeypatch):
    enriched_batches = []

    monkeypatch.setattr(routes, "all_sessions", lambda **_kwargs: _sessions_payload_rows())
    monkeypatch.setattr(
        routes,
        "_enrich_sidebar_lineage_metadata",
        lambda rows: enriched_batches.append([row["session_id"] for row in rows]),
    )
    monkeypatch.setattr(routes, "_reconcile_stale_stream_state_for_session_rows", lambda rows: False)
    monkeypatch.setattr(routes, "load_settings", lambda: {"show_cli_sessions": False})
    monkeypatch.setattr(profiles, "get_active_profile_name", lambda: "default")
    routes._session_list_cache_clear()

    handler = _FakeHandler()
    routes.handle_get(handler, urlparse("http://example.com/api/sessions?include_archived=1"))

    assert handler.status == 200
    body = handler.json_body()
    assert [row["session_id"] for row in body["sessions"]] == [
        "visible-active",
        "archived-history",
    ]
    assert body["archived_count"] == 1
    assert body["include_archived"] is True
    assert enriched_batches == [["visible-active", "archived-history"]]


def test_sessions_api_can_limit_archived_rows_without_hiding_visible_rows(monkeypatch):
    rows = [
        {"session_id": "visible-a", "title": "Visible A", "profile": "default", "archived": False, "message_count": 1, "updated_at": 50, "last_message_at": 50},
        {"session_id": "visible-b", "title": "Visible B", "profile": "default", "archived": False, "message_count": 1, "updated_at": 40, "last_message_at": 40},
        {"session_id": "archived-new", "title": "Archived New", "profile": "default", "archived": True, "message_count": 1, "updated_at": 30, "last_message_at": 30},
        {"session_id": "archived-mid", "title": "Archived Mid", "profile": "default", "archived": True, "message_count": 1, "updated_at": 20, "last_message_at": 20},
        {"session_id": "archived-old", "title": "Archived Old", "profile": "default", "archived": True, "message_count": 1, "updated_at": 10, "last_message_at": 10},
    ]
    enriched_batches = []

    monkeypatch.setattr(routes, "all_sessions", lambda **_kwargs: rows)
    monkeypatch.setattr(
        routes,
        "_enrich_sidebar_lineage_metadata",
        lambda batch: enriched_batches.append([row["session_id"] for row in batch]),
    )
    monkeypatch.setattr(routes, "_reconcile_stale_stream_state_for_session_rows", lambda rows: False)
    monkeypatch.setattr(routes, "load_settings", lambda: {"show_cli_sessions": False})
    monkeypatch.setattr(profiles, "get_active_profile_name", lambda: "default")
    routes._session_list_cache_clear()

    handler = _FakeHandler()
    routes.handle_get(handler, urlparse("http://example.com/api/sessions?include_archived=1&archived_limit=2"))

    assert handler.status == 200
    body = handler.json_body()
    assert [row["session_id"] for row in body["sessions"]] == [
        "visible-a",
        "visible-b",
        "archived-new",
        "archived-mid",
    ]
    assert body["archived_count"] == 3
    assert body["webui_session_count"] == 5
    assert body["archived_limit"] == 2
    assert enriched_batches == [["visible-a", "visible-b", "archived-new", "archived-mid"]]


def test_archived_limit_varies_session_list_cache_key():
    base = routes._session_list_cache_key(
        active_profile="default",
        all_profiles=False,
        show_cli_sessions=False,
        show_previous_messaging_sessions=False,
        show_cron_sessions=False,
        include_archived=True,
        archived_limit=100,
    )
    larger = routes._session_list_cache_key(
        active_profile="default",
        all_profiles=False,
        show_cli_sessions=False,
        show_previous_messaging_sessions=False,
        show_cron_sessions=False,
        include_archived=True,
        archived_limit=200,
    )

    assert base != larger


def test_initial_session_limit_applies_after_scope_and_preserves_counts(monkeypatch):
    rows = [
        {
            "session_id": f"default-{idx}",
            "title": f"Default {idx}",
            "profile": "default",
            "message_count": 1,
            "updated_at": 100 - idx,
            "last_message_at": 100 - idx,
        }
        for idx in range(5)
    ] + [
        {
            "session_id": f"other-{idx}",
            "title": f"Other {idx}",
            "profile": "other",
            "message_count": 1,
            "updated_at": 50 - idx,
            "last_message_at": 50 - idx,
        }
        for idx in range(2)
    ]
    enriched_batches = []

    monkeypatch.setattr(routes, "all_sessions", lambda **_kwargs: rows)
    monkeypatch.setattr(
        routes,
        "_enrich_sidebar_lineage_metadata",
        lambda batch: enriched_batches.append([row["session_id"] for row in batch]),
    )
    monkeypatch.setattr(routes, "_reconcile_stale_stream_state_for_session_rows", lambda _rows: False)
    monkeypatch.setattr(routes, "_rbac_users_configured", lambda: False)

    payload = routes._build_session_list_cache_payload(
        active_profile="default",
        all_profiles=False,
        show_cli_sessions=False,
        show_previous_messaging_sessions=False,
        show_cron_sessions=False,
        visible_only=True,
        session_limit=2,
    )

    assert [row["session_id"] for row in payload["sessions"]] == ["default-0", "default-1"]
    assert payload["webui_session_count"] == 5
    assert payload["other_profile_count"] == 2
    assert enriched_batches == [["default-0", "default-1"]]


def test_session_limit_varies_session_list_cache_key():
    base = dict(
        active_profile="default",
        all_profiles=False,
        show_cli_sessions=False,
        show_previous_messaging_sessions=False,
        show_cron_sessions=False,
    )

    assert routes._session_list_cache_key(**base, session_limit=120) != routes._session_list_cache_key(
        **base, session_limit=240
    )


def test_subagent_sidebar_coercion_reuses_state_db_metadata(monkeypatch):
    rows = [{
        "session_id": "subagent-from-state-db",
        "title": "Delegated child",
        "profile": "default",
        "archived": False,
        "message_count": 1,
        "updated_at": 10,
        "last_message_at": 10,
        "source": "webui",
    }]

    def fake_all_sessions(**kwargs):
        metadata = kwargs["state_db_metadata_out"]
        metadata[rows[0]["session_id"]] = {"_state_db_source": "subagent"}
        return [dict(rows[0])]

    monkeypatch.setattr(routes, "all_sessions", fake_all_sessions)
    monkeypatch.setattr(routes, "_enrich_sidebar_lineage_metadata", lambda _rows: None)
    monkeypatch.setattr(routes, "_reconcile_stale_stream_state_for_session_rows", lambda _rows: False)
    monkeypatch.setattr(
        routes,
        "_is_subagent_child_session_id",
        lambda _sid: pytest.fail("sidebar coercion must not issue an N+1 state.db probe"),
    )

    payload = routes._build_session_list_cache_payload(
        active_profile="default",
        all_profiles=False,
        show_cli_sessions=False,
        show_previous_messaging_sessions=False,
        show_cron_sessions=False,
        visible_only=True,
    )

    assert payload["sessions"][0]["read_only"] is True
    assert payload["sessions"][0]["is_cli_session"] is False


def test_sessions_api_legacy_all_sessions_monkeypatch_fallback_is_narrow(monkeypatch):
    calls = []

    def legacy_all_sessions(*, diag=None):
        calls.append(diag)
        return _sessions_payload_rows()

    monkeypatch.setattr(routes, "all_sessions", legacy_all_sessions)
    monkeypatch.setattr(routes, "_enrich_sidebar_lineage_metadata", lambda rows: None)
    monkeypatch.setattr(routes, "_reconcile_stale_stream_state_for_session_rows", lambda rows: False)
    monkeypatch.setattr(routes, "load_settings", lambda: {"show_cli_sessions": False})
    monkeypatch.setattr(profiles, "get_active_profile_name", lambda: "default")

    handler = _FakeHandler()
    routes.handle_get(handler, urlparse("http://example.com/api/sessions"))

    assert handler.status == 200
    assert len(calls) == 1


def test_sessions_api_internal_typeerror_is_not_hidden_by_legacy_fallback(monkeypatch):
    def broken_all_sessions(**_kwargs):
        raise TypeError("internal include_lineage_metadata transformation failed")

    monkeypatch.setattr(routes, "all_sessions", broken_all_sessions)
    monkeypatch.setattr(routes, "_reconcile_stale_stream_state_for_session_rows", lambda rows: False)
    monkeypatch.setattr(routes, "load_settings", lambda: {"show_cli_sessions": False})
    monkeypatch.setattr(profiles, "get_active_profile_name", lambda: "default")

    with pytest.raises(TypeError, match="internal include_lineage_metadata"):
        routes._build_session_list_cache_payload(
            active_profile="default",
            all_profiles=False,
            show_cli_sessions=False,
            show_previous_messaging_sessions=False,
            show_cron_sessions=False,
        )


def test_session_list_fetch_adds_include_archived_only_when_toggle_is_on():
    src = (pathlib.Path(__file__).parent.parent / "static" / "sessions.js").read_text(encoding="utf-8")

    assert "qs.set('include_archived','1');" in src
    assert "const archiveLimit=Math.min(" in src
    assert "SESSION_ARCHIVED_MAX_LOADED_LIMIT" in src
    assert "qs.set('archived_limit', String(archiveLimit));" in src
    assert "api('/api/sessions' + sessionListQS" in src
    assert "if(_showArchived) _archivedRowsLoadedLimit=SESSION_ARCHIVED_PAGE_SIZE;" in src
    assert "className='session-archive-more'" in src
    assert "_archivedRowsLoadedLimit=Math.min(" in src
    assert "Math.max(SESSION_ARCHIVED_PAGE_SIZE, Number(_archivedRowsLoadedLimit)||SESSION_ARCHIVED_PAGE_SIZE)+SESSION_ARCHIVED_PAGE_SIZE" in src
    assert "_archivedWebuiCount" in src
    assert "sessData.archived_webui_count ?? sessData.archived_count ?? 0" in src
    assert "archived_webui_count" in src


def test_sessions_api_runtime_overlay_sorts_active_rows_first(monkeypatch):
    payload = {
        "sessions": [
            {
                "session_id": "newer-complete",
                "title": "Newer complete",
                "updated_at": 300,
                "last_message_at": 300,
            },
            {
                "session_id": "older-running",
                "title": "Older running",
                "updated_at": 100,
                "last_message_at": 100,
            },
            {
                "session_id": "old-complete",
                "title": "Old complete",
                "updated_at": 50,
                "last_message_at": 50,
            },
        ],
        "cli_count": 0,
        "archived_count": 0,
        "archived_webui_count": 0,
        "archived_cli_count": 0,
        "include_archived": False,
        "all_profiles": False,
        "active_profile": "default",
        "other_profile_count": 0,
    }
    live = SimpleNamespace(
        active_stream_id="stream-running",
        pending_user_message="go",
        pending_started_at="400",
        updated_at="400",
        last_message_at="400",
    )

    monkeypatch.setattr(routes, "_active_stream_ids", lambda: {"stream-running"})
    with routes.LOCK:
        previous = routes.SESSIONS.get("older-running")
        routes.SESSIONS["older-running"] = live
    try:
        body = routes._session_list_payload_to_response(payload)
    finally:
        with routes.LOCK:
            if previous is None:
                routes.SESSIONS.pop("older-running", None)
            else:
                routes.SESSIONS["older-running"] = previous

    assert [row["session_id"] for row in body["sessions"]] == [
        "older-running",
        "newer-complete",
        "old-complete",
    ]
    assert body["sessions"][0]["is_streaming"] is True
    assert body["sessions"][0]["updated_at"] == "400"


def test_frontend_session_list_sorts_effective_streaming_rows_first():
    src = (pathlib.Path(__file__).parent.parent / "static" / "sessions.js").read_text(encoding="utf-8")

    assert "function _sessionSidebarSortCompare(a, b)" in src
    assert "function _sessionRunningSortRank(session)" in src
    assert "_isSessionEffectivelyStreaming(session)" in src
    assert "session.active_stream_id && session.has_pending_user_message" in src
    assert "const orderedSessions=[...sessions].sort(_sessionSidebarSortCompare);" in src


def test_frontend_session_date_buckets_use_runtime_sort_timestamp():
    src = (pathlib.Path(__file__).parent.parent / "static" / "sessions.js").read_text(encoding="utf-8")
    loop_start = src.index("for(const s of unpinned){")
    loop_body = src[loop_start:src.index("if(curItems.length) groups.push", loop_start)]

    assert "const ts=_sessionSortTimestampMs(s);" in loop_body
    assert "_sessionTimeBucketLabel(ts, now)" in loop_body
