import json
import logging
from pathlib import Path

import api.models as models
from api.models import Session
from api.request_diagnostics import RequestDiagnostics


class _StageRecorder:
    def __init__(self):
        self.stages = []

    def stage(self, name):
        self.stages.append(name)


def test_request_diagnostics_timeout_record_includes_stage_and_thread_stacks(caplog):
    logger = logging.getLogger("test.issue1855.timeout")
    diag = RequestDiagnostics(
        "GET",
        "/api/sessions?all_profiles=1",
        logger=logger,
        timeout_seconds=5,
        auto_start=False,
    )
    diag.stage("all_sessions.read_index")

    with caplog.at_level(logging.WARNING, logger=logger.name):
        diag._on_timeout()

    assert len(caplog.records) == 1
    record = json.loads(caplog.records[0].args[0])
    assert record["method"] == "GET"
    assert record["path"] == "/api/sessions"
    assert record["current_stage"] == "all_sessions.read_index"
    assert record["elapsed_ms"] >= 0
    assert any(stage["name"] == "all_sessions.read_index" for stage in record["stages"])
    assert record["thread_stacks"]


def test_request_diagnostics_maybe_start_covers_p0_target_paths_only():
    for path in (
        "/api/sessions",
        "/api/session/status",
        "/api/approval/pending",
        "/api/clarify/pending",
        "/api/auth/status",
        "/api/license/status",
        "/api/health/agent",
        "/api/crons/recent",
        "/api/dashboard/status",
    ):
        assert RequestDiagnostics.maybe_start("GET", path) is not None
    assert RequestDiagnostics.maybe_start("POST", "/api/chat/start") is not None
    assert RequestDiagnostics.maybe_start("GET", "/health") is None
    assert RequestDiagnostics.maybe_start("POST", "/api/session/new") is None


def test_request_diagnostics_hashes_identity_context_and_keeps_response_metadata_private():
    logger = logging.getLogger("test.issue1855.context")
    diag = RequestDiagnostics("GET", "/api/auth/status", logger=logger, auto_start=False)
    diag.bind_context(profile="ops", user_id="user-13", auth_cookie="session-secret")
    diag.set_response(status=200, body_bytes=123)
    with diag._lock:
        record = diag._build_record_locked(include_stacks=False)

    context = record["context"]
    assert set(context) == {
        "profile_hash",
        "user_id_hash",
        "auth_cookie_hash",
    }
    assert "ops" not in json.dumps(record)
    assert "user-13" not in json.dumps(record)
    assert "session-secret" not in json.dumps(record)
    assert record["response_status"] == 200
    assert record["response_bytes"] == 123


def test_all_sessions_reports_internal_index_stages(tmp_path, monkeypatch):
    session_dir = tmp_path / "sessions"
    session_dir.mkdir()
    index_file = session_dir / "_index.json"
    monkeypatch.setattr(models, "SESSION_DIR", session_dir)
    monkeypatch.setattr(models, "SESSION_INDEX_FILE", index_file)
    monkeypatch.setattr(models, "_enrich_sidebar_lineage_metadata", lambda sessions: None)
    models.SESSIONS.clear()

    s = Session(
        session_id="issue1855_indexed",
        title="Indexed",
        messages=[{"role": "user", "content": "hi", "timestamp": 100}],
    )
    s.path.write_text(json.dumps(s.__dict__, ensure_ascii=False), encoding="utf-8")
    index_file.write_text(
        json.dumps(
            [
                {
                    "session_id": s.session_id,
                    "title": s.title,
                    "updated_at": s.updated_at,
                    "workspace": s.workspace,
                    "model": s.model,
                    "message_count": 1,
                    "created_at": s.created_at,
                    "pinned": False,
                    "archived": False,
                    "last_message_at": 100,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    diag = _StageRecorder()
    rows = models.all_sessions(diag=diag)

    assert [row["session_id"] for row in rows] == [s.session_id]
    assert "all_sessions.read_index" in diag.stages
    assert "all_sessions.overlay_lock" in diag.stages
    assert "all_sessions.lineage_metadata" in diag.stages


def test_issue1855_target_routes_are_wired_to_diagnostics():
    src = Path("api/routes.py").read_text(encoding="utf-8")

    assert 'RequestDiagnostics.maybe_start(' in src
    assert "all_sessions(diag=diag, include_lineage_metadata=False)" in src
    assert 'RequestDiagnostics.maybe_start(' in src
    assert "_handle_chat_start(handler, body, diag=diag)" in src
    for stage in (
        "read_body",
        "resolve_model_provider",
        "session_lock_wait",
        "save_pending_state",
        "stream_registration",
        "worker_thread_start",
        "response_write",
    ):
        assert stage in src


def test_p0_server_diagnostics_stage_order_and_no_raw_identity_logging():
    src = Path("server.py").read_text(encoding="utf-8")
    positions = [src.index(f'diag.stage("{stage}")') for stage in (
        "request_entry",
        "license_middleware",
        "auth_middleware",
        "handler",
    )]
    assert positions == sorted(positions)
    assert 'diag.bind_context(' in src
    assert 'auth_cookie=self._header_value("Cookie")' in src

    diag_src = Path("api/request_diagnostics.py").read_text(encoding="utf-8")
    assert "hashlib.sha256" in diag_src
    assert "response_bytes" in diag_src
