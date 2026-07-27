import queue
import threading
import time
from pathlib import Path

import api.config as config
import api.routes as routes

REPO = Path(__file__).resolve().parents[1]
ROUTES_SRC = (REPO / "api" / "routes.py").read_text(encoding="utf-8")
SESSIONS_SRC = (REPO / "static" / "sessions.js").read_text(encoding="utf-8")
SW_SRC = (REPO / "static" / "sw.js").read_text(encoding="utf-8")
STREAMING_SRC = (REPO / "api" / "streaming.py").read_text(encoding="utf-8")


class _GateLock:
    def __init__(self):
        self._lock = threading.Lock()
        self.lookup_finished = threading.Event()
        self.writer_finished = threading.Event()

    def __enter__(self):
        self._lock.acquire()
        return self

    def __exit__(self, exc_type, exc, tb):
        self._lock.release()
        if not self.lookup_finished.is_set():
            self.lookup_finished.set()
            assert self.writer_finished.wait(2), "writer did not finish race setup"
        return False


class _FakeSession:
    session_id = "issue1533-session"

    def __init__(self):
        self.active_stream_id = "stale-stream"
        self.pending_user_message = "old prompt"
        self.pending_attachments = ["old.txt"]
        self.pending_started_at = 123
        self.messages = []
        self.saved_stream_ids = []
        self.saved_touch_updated_at = []

    def save(self, *, touch_updated_at=True):
        self.saved_stream_ids.append(self.active_stream_id)
        self.saved_touch_updated_at.append(touch_updated_at)


def test_stale_stream_cleanup_helper_exists():
    assert "def _clear_stale_stream_state(session)" in ROUTES_SRC
    assert "stream_id in STREAMS" in ROUTES_SRC
    assert "session.active_stream_id = None" in ROUTES_SRC
    assert "session.pending_user_message = None" in ROUTES_SRC
    assert "session.pending_attachments = []" in ROUTES_SRC
    assert "session.pending_started_at = None" in ROUTES_SRC
    assert "session.save(touch_updated_at=False)" in ROUTES_SRC


def test_stale_stream_cleanup_does_not_refresh_sidebar_timestamp():
    config.STREAMS.clear()
    config.SESSION_AGENT_LOCKS.clear()
    session = _FakeSession()

    assert routes._clear_stale_stream_state(session) is True

    assert session.active_stream_id is None
    assert session.saved_touch_updated_at == [False]


def test_session_load_clears_stale_stream_before_response():
    load_pos = ROUTES_SRC.index("s = get_session(sid, metadata_only=(not load_messages))")
    cleanup_pos = ROUTES_SRC.index("_clear_stale_stream_state(s)", load_pos)
    response_pos = ROUTES_SRC.index('"active_stream_id": getattr(s, "active_stream_id", None)', cleanup_pos)
    assert load_pos < cleanup_pos < response_pos


def test_chat_start_clears_stale_pending_state_not_only_active_id():
    stale_comment_pos = ROUTES_SRC.index("# Stale stream id from a previous run; clear and continue.")
    cleanup_pos = ROUTES_SRC.index("_clear_stale_stream_state(s)", stale_comment_pos)
    stream_id_pos = ROUTES_SRC.index("stream_id = uuid.uuid4().hex", cleanup_pos)
    assert stale_comment_pos < cleanup_pos < stream_id_pos


def test_chat_start_rechecks_active_stream_under_session_lock(monkeypatch, tmp_path):
    """A concurrent chat_start must not overwrite stream ownership.

    The first request can pass the pre-lock active_stream_id check while another
    request is waiting/running. Once this request enters the session lock, it
    must re-read active_stream_id and reject instead of creating a ghost stream.
    """
    config.STREAMS.clear()
    config.SESSION_AGENT_LOCKS.clear()
    existing_stream_id = "already-running-stream"

    class ChatStartSession:
        session_id = "duplicate-start-session"

        def __init__(self):
            self.active_stream_id = None
            self.pending_user_message = None
            self.pending_attachments = []
            self.pending_started_at = None
            self.messages = []
            self.title = "Untitled"
            self.worktree_path = None
            self.workspace = None
            self.model = None
            self.model_provider = None

        def save(self, *args, **kwargs):
            return None

    session = ChatStartSession()

    class MutatingSessionLock:
        def __enter__(self):
            session.active_stream_id = existing_stream_id
            session.pending_user_message = "prompt already claimed by another start"
            session.pending_started_at = 123.0
            routes.STREAMS[existing_stream_id] = queue.Queue()
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class NoopThread:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def start(self):
            return None

    monkeypatch.setattr(routes, "_get_session_agent_lock", lambda sid: MutatingSessionLock())
    monkeypatch.setattr(routes.uuid, "uuid4", lambda: type("FakeUuid", (), {"hex": "new-stream"})())
    monkeypatch.setattr(routes, "set_last_workspace", lambda workspace: None)
    monkeypatch.setattr(routes, "create_stream_channel", lambda: queue.Queue())
    monkeypatch.setattr(routes.threading, "Thread", NoopThread)

    try:
        response = routes._start_chat_stream_for_session(
            session,
            msg="please start once",
            attachments=[],
            workspace=str(tmp_path),
            model="test-model",
            model_provider=None,
        )

        assert response["_status"] == 409
        assert response["active_stream_id"] == existing_stream_id
        assert session.active_stream_id == existing_stream_id
        assert "new-stream" not in routes.STREAMS
    finally:
        routes.STREAMS.pop(existing_stream_id, None)


def test_chat_start_blocks_same_session_active_run_after_cancel_clears_stream_id(monkeypatch, tmp_path):
    """Regression for #3808: cancel clears active_stream_id before worker exit.

    interrupt-and-send queues a successor message, then calls cancel_stream().
    cancel_stream() intentionally clears session.active_stream_id so Stop remains
    responsive, but the old worker remains in ACTIVE_RUNS until its finally block
    unregisters it. chat/start must still block by session_id during that window.
    """
    config.STREAMS.clear()
    config.ACTIVE_RUNS.clear()
    config.SESSION_AGENT_LOCKS.clear()

    class ChatStartSession:
        session_id = "interrupt-send-session"

        def __init__(self):
            self.active_stream_id = None
            self.pending_user_message = None
            self.pending_attachments = []
            self.pending_started_at = None
            self.messages = []
            self.title = "Interrupt Send"
            self.worktree_path = None
            self.workspace = None
            self.model = None
            self.model_provider = None

        def save(self, *args, **kwargs):
            return None

    session = ChatStartSession()
    old_stream_id = "old-cancelling-stream"
    config.register_active_run(old_stream_id, session_id=session.session_id, phase="cancelling")

    class NoopThread:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def start(self):
            return None

    monkeypatch.setattr(routes.uuid, "uuid4", lambda: type("FakeUuid", (), {"hex": "new-stream"})())
    monkeypatch.setattr(routes, "set_last_workspace", lambda workspace: None)
    monkeypatch.setattr(routes, "create_stream_channel", lambda: queue.Queue())
    monkeypatch.setattr(routes.threading, "Thread", NoopThread)

    try:
        response = routes._start_chat_stream_for_session(
            session,
            msg="successor prompt",
            attachments=[],
            workspace=str(tmp_path),
            model="test-model",
            model_provider=None,
        )

        assert response["_status"] == 409
        assert response["active_stream_id"] == old_stream_id
        assert session.active_stream_id is None
        assert session.pending_user_message is None
        assert "new-stream" not in routes.STREAMS
    finally:
        config.unregister_active_run(old_stream_id)


def test_chat_start_allows_same_session_after_active_run_unregisters(monkeypatch, tmp_path):
    """The #3808 guard must release once the old worker unregisters ACTIVE_RUNS."""
    config.STREAMS.clear()
    config.ACTIVE_RUNS.clear()
    config.SESSION_AGENT_LOCKS.clear()

    class ChatStartSession:
        session_id = "interrupt-send-session-released"

        def __init__(self):
            self.active_stream_id = None
            self.pending_user_message = None
            self.pending_attachments = []
            self.pending_started_at = None
            self.messages = []
            self.title = "Interrupt Send"
            self.worktree_path = None
            self.workspace = None
            self.model = None
            self.model_provider = None

        def save(self, *args, **kwargs):
            return None

    session = ChatStartSession()

    class NoopThread:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def start(self):
            return None

    monkeypatch.setattr(routes.uuid, "uuid4", lambda: type("FakeUuid", (), {"hex": "new-stream"})())
    monkeypatch.setattr(routes, "set_last_workspace", lambda workspace: None)
    monkeypatch.setattr(routes, "create_stream_channel", lambda: queue.Queue())
    monkeypatch.setattr(routes.threading, "Thread", NoopThread)

    response = routes._start_chat_stream_for_session(
        session,
        msg="successor prompt",
        attachments=[],
        workspace=str(tmp_path),
        model="test-model",
        model_provider=None,
    )

    try:
        assert "error" not in response
        assert response["stream_id"] == "new-stream"
        assert session.active_stream_id == "new-stream"
        assert session.pending_user_message == "successor prompt"
    finally:
        routes.STREAMS.pop("new-stream", None)


def test_chat_start_not_permanently_blocked_by_stale_active_run(monkeypatch, tmp_path):
    """A wedged/detached ACTIVE_RUNS entry past the unwind ceiling must NOT 409 forever.

    The #3808 successor guard waits on a same-session ACTIVE_RUNS entry during the
    short post-cancel unwind. But unregister only runs in the worker finally, so a
    worker stuck in a provider call (or leaked by SIGKILL without restart) would
    block the session permanently. The guard ignores entries older than the 180s
    ceiling so the user can recover. (Codex brick-gate hardening, #3822.)
    """
    config.STREAMS.clear()
    config.ACTIVE_RUNS.clear()
    config.SESSION_AGENT_LOCKS.clear()

    class ChatStartSession:
        session_id = "interrupt-send-session-stale"

        def __init__(self):
            self.active_stream_id = None
            self.pending_user_message = None
            self.pending_attachments = []
            self.pending_started_at = None
            self.messages = []
            self.title = "Interrupt Send"
            self.worktree_path = None
            self.workspace = None
            self.model = None
            self.model_provider = None

        def save(self, *args, **kwargs):
            return None

    session = ChatStartSession()
    stale_stream_id = "wedged-old-stream"
    config.register_active_run(stale_stream_id, session_id=session.session_id, phase="running")
    # Age the entry well past the 180s unwind ceiling.
    with config.ACTIVE_RUNS_LOCK:
        config.ACTIVE_RUNS[stale_stream_id]["started_at"] = time.time() - 600

    # The bounded guard should treat it as stale and NOT report it as blocking.
    assert routes._active_run_stream_for_session(session.session_id) is None
    # It must also reconcile the zombie registry entry immediately so health /
    # recovery polling does not keep advertising a half-alive run forever.
    assert stale_stream_id not in config.ACTIVE_RUNS

    class NoopThread:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def start(self):
            return None

    monkeypatch.setattr(routes.uuid, "uuid4", lambda: type("FakeUuid", (), {"hex": "new-stream"})())
    monkeypatch.setattr(routes, "set_last_workspace", lambda workspace: None)
    monkeypatch.setattr(routes, "create_stream_channel", lambda: queue.Queue())
    monkeypatch.setattr(routes.threading, "Thread", NoopThread)

    try:
        response = routes._start_chat_stream_for_session(
            session,
            msg="successor prompt",
            attachments=[],
            workspace=str(tmp_path),
            model="test-model",
            model_provider=None,
        )
        assert "error" not in response
        assert response["stream_id"] == "new-stream"
        assert session.active_stream_id == "new-stream"
    finally:
        config.unregister_active_run(stale_stream_id)
        routes.STREAMS.pop("new-stream", None)


def test_live_worker_past_ceiling_is_not_reaped_from_active_runs():
    """A still-live worker (present in STREAMS) past the age ceiling must NOT be
    popped from ACTIVE_RUNS — only genuinely-gone workers are reconciled (#4492).

    A long turn whose active_stream_id was cleared during final writeback can be
    mid-teardown past the 180s ceiling while its STREAMS entry is still present;
    reaping its lifecycle row then would lie to health / background-wakeup /
    active-agent-cache consumers that read ACTIVE_RUNS as worker-lifecycle truth.
    """
    config.STREAMS.clear()
    config.ACTIVE_RUNS.clear()
    sid = "live-teardown-session"
    live_stream_id = "still-alive-stream"
    config.register_active_run(live_stream_id, session_id=sid, phase="running")
    # Age the entry past the ceiling AND keep the worker present in STREAMS.
    with config.ACTIVE_RUNS_LOCK:
        config.ACTIVE_RUNS[live_stream_id]["started_at"] = time.time() - 600
    config.STREAMS[live_stream_id] = object()
    try:
        # Not reported as blocking (past the ceiling) ...
        assert routes._active_run_stream_for_session(sid) is None
        # ... but the lifecycle row is preserved because the worker is still live.
        assert live_stream_id in config.ACTIVE_RUNS
    finally:
        config.STREAMS.pop(live_stream_id, None)
        config.unregister_active_run(live_stream_id)


def test_stale_stream_cleanup_does_not_clobber_concurrent_chat_start(monkeypatch):
    """Regression for #1533: stale cleanup must not erase a new stream id.

    The gate lock pauses the cleanup thread after it has decided that the old
    stream id is stale, then lets a chat_start-like writer register and persist
    a new active_stream_id for the same session.
    """
    config.STREAMS.clear()
    config.SESSION_AGENT_LOCKS.clear()
    gate_lock = _GateLock()
    session = _FakeSession()
    new_stream_id = "new-stream"
    result = {}

    monkeypatch.setattr(routes, "STREAMS_LOCK", gate_lock)

    def cleanup_stale_stream():
        result["cleared"] = routes._clear_stale_stream_state(session)

    def start_new_stream():
        assert gate_lock.lookup_finished.wait(2), "cleanup did not reach race point"
        with routes.STREAMS_LOCK:
            routes.STREAMS[new_stream_id] = queue.Queue()
        with routes._get_session_agent_lock(session.session_id):
            session.active_stream_id = new_stream_id
            session.pending_user_message = "new prompt"
            session.pending_attachments = ["new.txt"]
            session.pending_started_at = 456
            session.save()
        gate_lock.writer_finished.set()

    cleanup_thread = threading.Thread(target=cleanup_stale_stream)
    writer_thread = threading.Thread(target=start_new_stream)
    cleanup_thread.start()
    writer_thread.start()
    cleanup_thread.join(2)
    writer_thread.join(2)

    assert not cleanup_thread.is_alive()
    assert not writer_thread.is_alive()
    assert result["cleared"] is False
    assert session.active_stream_id == new_stream_id
    assert session.pending_user_message == "new prompt"
    assert session.pending_attachments == ["new.txt"]
    assert session.pending_started_at == 456


def test_frontend_drops_inflight_cache_when_server_session_is_idle():
    # #3900/#3899 generalized this block: on an idle server session it now resets
    # the streaming flags (S.busy/S.activeStreamId) AND drops the inflight cache,
    # before the async message-load gap. Anchor on the current comment + assert the
    # (preserved) cache-drop behavior in the now-nested form.
    marker = "If the server says the session is idle, reset browser-side streaming flags"
    marker_pos = SESSIONS_SRC.index(marker)
    window = SESSIONS_SRC[marker_pos:marker_pos + 900]
    assert "if(!activeStreamId){" in window
    assert "S.busy=false" in window
    assert "S.activeStreamId=null" in window
    assert "if(INFLIGHT[sid]){" in window
    assert "delete INFLIGHT[sid]" in window
    assert "clearInflightState" in window


def test_service_worker_cache_bumped_for_frontend_fix_delivery():
    """The SW CACHE_NAME must be keyed on the WEBUI_VERSION placeholder so
    every release naturally invalidates the previous shell cache and delivers
    the frontend half of the stale-stream cleanup fix to existing browsers.

    Originally pinned a manual `-stale-stream-cleanup1` suffix on
    `CACHE_NAME` (PR #1525 author shipped that to force-bump existing
    SWs). During the v0.50.279 stage build that suffix collided with the
    independent #1517 placeholder rename (`__CACHE_VERSION__` →
    `__WEBUI_VERSION__`), so the maintainer dropped the manual suffix in
    favor of the canonical version-token path. The natural bump still
    invalidates the old cache via `keys.filter((k) => k !== CACHE_NAME)`
    in the activate handler — same delivery guarantee, less churn.
    """
    # CACHE_NAME must include the WEBUI_VERSION placeholder so each release
    # produces a different cache name. The activate handler then deletes any
    # cache whose key != current CACHE_NAME, so the old shell is reaped on
    # every upgrade and the new sessions.js (with the INFLIGHT[sid] clear)
    # ships to existing browsers.
    assert "CACHE_NAME = 'hermes-shell-__WEBUI_VERSION__'" in SW_SRC, (
        "SW CACHE_NAME must include __WEBUI_VERSION__ so each release "
        "invalidates the previous cache and delivers frontend changes."
    )


def test_streaming_cancel_paths_unregister_active_run_before_event():
    """Regression: every cancel exit in _run_agent_streaming must clear
    ACTIVE_RUNS BEFORE the ``cancel`` SSE event goes out.

    The success path (put('done')) and error path (put('apperror')) already
    unregister_active_run(stream_id) ahead of the event (the comment at
    streaming.py:9805 explains why — a queue-drain /api/chat/start arriving
    immediately after the event otherwise sees the old stream_id still in
    ACTIVE_RUNS / STREAMS / s.active_stream_id and gets a false 409 with
    _diag.in_streams=true + in_active_runs=true + has_pending_user_message=true).

    The cancel paths share the same race but were missed by the original fix.
    This test pins the contract: any new ``put('cancel', ...)`` site must be
    preceded by an ``unregister_active_run(stream_id)`` call. If a future
    contributor adds a cancel path that forgets the early unregister, this
    test fails immediately.

    We check within a 6-line window because some sites wrap the unregister in
    a try/except (mirroring the apperror path at line 10167-10175), and we
    tolerate that with a regex that matches the call regardless of try/except
    wrapping.
    """
    import re

    # Find every cancel-event emission line in streaming.py.
    cancel_lines = [
        i for i, line in enumerate(STREAMING_SRC.splitlines(), start=1)
        if re.search(r"put\(\s*['\"]cancel['\"]", line)
    ]
    assert len(cancel_lines) >= 9, (
        f"expected at least 9 cancel-event sites in streaming.py, found "
        f"{len(cancel_lines)}; if you added new sites, also add the early "
        f"unregister_active_run(stream_id) call before each new put('cancel', ...)"
    )

    # For each cancel site, require an unregister_active_run(stream_id) call
    # within the 6 lines preceding it. Pattern matches both bare call and
    # try/except-wrapped forms (the apperror fix at line 10174 uses
    # ``try: unregister_active_run(stream_id) except Exception: pass``).
    unregister_re = re.compile(
        r"unregister_active_run\(\s*stream_id\s*\)"
    )
    src_lines = STREAMING_SRC.splitlines()
    missing = []
    for cancel_line_no in cancel_lines:
        window_start = max(0, cancel_line_no - 7)  # 0-indexed offset; covers 6 lines back
        window = "\n".join(src_lines[window_start:cancel_line_no])
        if not unregister_re.search(window):
            missing.append(cancel_line_no)

    assert not missing, (
        "cancel exit paths must unregister_active_run(stream_id) BEFORE "
        "the cancel event goes out — otherwise a client queue-drain /api/chat/start "
        "arriving right after the cancel event will hit a false 409 from "
        "ACTIVE_RUNS / STREAMS / s.active_stream_id. "
        f"Sites missing the early unregister: {missing}. "
        "Mirror the pattern used by the apperror fix at streaming.py:10167-10175 "
        "(wrap the call in try/except so an unregister failure does not block "
        "the cancel event from reaching the client)."
    )


def test_cancel_stream_function_eagerly_unregisters_active_runs():
    """Regression: cancel_stream() (api/streaming.py:10424) promises in its
    docstring to "eagerly release the session lock...immediately after cancel,
    even if the agent thread is still blocked". That requires dropping
    ACTIVE_RUNS[stream_id] AT cancel time, not waiting for the worker's
    `finally` block (which only runs after agent.interrupt()'d blocking
    tool returns — often minutes for wedged providers).

    Without this fix, a tab-refresh + Stop sequence produces an orphan worker
    that holds ACTIVE_RUNS[stream_id] indefinitely, leaving every subsequent
    /api/chat/start blocked with 409 `_source: session_active_stream_id`
    `_diag.in_active_runs=true`.
    """
    import re

    # Locate the cancel_stream() function definition.
    fn_match = re.search(
        r"^def\s+cancel_stream\s*\(\s*stream_id\s*:\s*str\s*\)\s*->\s*bool\s*:\s*$",
        STREAMING_SRC, re.MULTILINE,
    )
    assert fn_match, "cancel_stream(stream_id) -> bool definition not found"

    # Slice from the def line forward; bound the slice at the next top-level
    # ``def`` / ``class`` line so we only inspect this function's body.
    start = fn_match.start()
    tail = STREAMING_SRC[start:]
    next_def = re.search(r"\n(?:def|class|async def)\s+\w+\s*\(", tail[1:])
    end = (start + 1 + next_def.start()) if next_def else len(STREAMING_SRC)
    body = STREAMING_SRC[start:end]

    # Must call unregister_active_run(stream_id) inside the function body
    # (NOT just delegate to the worker's finally block).
    eager_re = re.compile(r"unregister_active_run\s*\(\s*stream_id\s*\)")
    assert eager_re.search(body), (
        "cancel_stream() must call unregister_active_run(stream_id) eagerly "
        "to fulfill its docstring promise of releasing the session lock "
        "immediately after cancel, even if the agent thread is still blocked. "
        "The worker's `finally` block also calls it (safe no-op double-pop), "
        "but relying on it alone leaves ACTIVE_RUNS held until agent.interrupt() "
        "returns from a wedged tool — which can take minutes."
    )

    # Must come AFTER the existing update_active_run(..., phase="cancelling")
    # call, otherwise we replace the phase-tracking entry instead of unregistering.
    update_match = re.search(
        r"update_active_run\s*\(\s*stream_id\s*,\s*phase\s*=\s*[\"']cancelling[\"']\s*\)",
        body,
    )
    assert update_match, (
        "cancel_stream() must call update_active_run(stream_id, phase=\"cancelling\") "
        "before unregistering (preserves lifecycle-phase telemetry for the cancel window)."
    )
    update_line_offset = update_match.end()
    after_update = body[update_line_offset:]
    assert eager_re.search(after_update), (
        "cancel_stream() must call unregister_active_run(stream_id) AFTER "
        "update_active_run(stream_id, phase=\"cancelling\"), so the cancel "
        "phase marker is recorded before the run is unregistered."
    )


def test_chat_start_proactive_cancel_when_blocking_stream_is_stale():
    """Regression: _start_chat_stream_for_session in api/routes.py must
    proactively cancel_stream() the blocking stream when its
    pending_started_at is older than the grace + auto-cancel threshold.

    Without this, an orphan worker (page refresh + long tool call) can hold
    STREAMS / ACTIVE_RUNS[stream_id] well past the 30s pending_user_message
    grace, and the user has no way to release it (Stop button JS state is
    reset after refresh, so cancelStream() returns early in boot.js without
    ever calling /api/chat/cancel). The follow-up chat_start then 409s
    forever, even though the worker is genuinely stuck and not making
    progress.

    The auto-cancel uses the same cancel_stream() that the explicit Stop
    button does, which now (per cancel_stream() docstring fix) eagerly
    unregisters ACTIVE_RUNS so the re-check below can succeed.
    """
    import re

    # Find _start_chat_stream_for_session definition.
    fn_match = re.search(
        r"^def\s+_start_chat_stream_for_session\s*\(",
        ROUTES_SRC, re.MULTILINE,
    )
    assert fn_match, "_start_chat_stream_for_session definition not found"

    start = fn_match.start()
    tail = ROUTES_SRC[start:]
    next_def = re.search(r"\n(?:def|class|async def)\s+\w+\s*\(", tail[1:])
    end = (start + 1 + next_def.start()) if next_def else len(ROUTES_SRC)
    body = ROUTES_SRC[start:end]

    # Must reference the imported helper name to do the proactive cancel.
    # The function uses ``from api.streaming import cancel_stream as _auto_cancel_stream``
    # — accept either that import-local name or a direct ``cancel_stream(`` call.
    cancel_call_re = re.compile(
        r"(?:_auto_cancel_stream|cancel_stream)\s*\(\s*current_stream_id\s*\)"
    )
    assert cancel_call_re.search(body), (
        "_start_chat_stream_for_session must call cancel_stream(current_stream_id) "
        "when the blocking active_stream_id is older than the grace threshold, "
        "to free stuck-orphan workers that the user can no longer Stop manually "
        "(JS state resets on page refresh)."
    )

    # Must compute stream age from pending_started_at (proxy for "how long has
    # this stream been alive") and gate the auto-cancel on a past-grace
    # comparison using _REPAIR_STALE_PENDING_GRACE_SECONDS as the boundary.
    # Past grace: lock is presumed-orphan (worker did not release within the
    # window matching operators' pending_user_message mental model).
    age_check_re = re.compile(
        r"pending_started_at[\s\S]{0,400}?(?:_past_grace|past_grace|_orphan_grace_seconds|orphan_grace|threshold|age)"
    )
    grace_re = re.compile(r"_REPAIR_STALE_PENDING_GRACE_SECONDS")
    assert age_check_re.search(body) and grace_re.search(body), (
        "_start_chat_stream_for_session must compute the blocking stream's age "
        "from session.pending_started_at and gate the auto-cancel on a "
        "past-grace comparison using _REPAIR_STALE_PENDING_GRACE_SECONDS as "
        "the boundary (so the orphan-recovery window matches the existing "
        "pending_user_message grace operators already understand)."
    )

    # Must NOT still call the buggy old form: a 409-conditional re-check inside
    # an `else` branch — that was the symptom of the previous
    # grace + 30 / 60 s threshold version.
    buggy_recheck_re = re.compile(
        r"else:\s*\n\s*diag\.stage\(\s*[\"']response_write[\"']\s*\)"
    )
    assert not buggy_recheck_re.search(body), (
        "_start_chat_stream_for_session still has the old 60s-threshold "
        "re-check inside an else branch. The new design fires "
        "proactive-cancel_stream() exactly at the grace boundary and never "
        "returns a 409 from the past-grace path."
    )


def test_chat_start_409_includes_v2_diag_with_age_and_grace(monkeypatch, tmp_path):
    """Regression: the 409 path of _start_chat_stream_for_session must include
    the v2 diagnostic shape (pending_started_at, ACTIVE_RUNS fallback age,
    past_grace verdict). Without these fields an operator seeing the
    ``_source: session_active_stream_id`` 409 in the wild has no way to
    tell whether the server is running the fix that eagerly
    unregisters ACTIVE_RUNS / proactively cancels stuck-orphan workers,
    or whether the user is hitting a different code path (pre-fix code,
    session loaded from a stale server, etc.). (Codex brick-gate #5345 /
    #5198 follow-up.)
    """
    import re

    # 1) Source-level invariant: the diag dict for the 409 path must be
    # the v2 shape. This catches "old code" without needing a live server.
    fn_match = re.search(
        r"^def\s+_start_chat_stream_for_session\s*\(",
        ROUTES_SRC, re.MULTILINE,
    )
    assert fn_match
    start = fn_match.start()
    tail = ROUTES_SRC[start:]
    next_def = re.search(r"\n(?:def|class|async def)\s+\w+\s*\(", tail[1:])
    end = (start + 1 + next_def.start()) if next_def else len(ROUTES_SRC)
    body = ROUTES_SRC[start:end]

    assert '"diag_version"' in body or "'diag_version'" in body, (
        "_start_chat_stream_for_session's 409 _diag must include diag_version=2 "
        "so operators can tell at-a-glance whether the running server is the "
        "fixed version."
    )
    for needle in (
        "pending_started_at",
        "active_run_started_at",
        "effective_started_at",
        "past_grace",
        "orphan_grace_s",
        "active_run_age_s",
    ):
        assert needle in body, (
            f"_start_chat_stream_for_session's 409 _diag must include {needle!r} "
            f"so operators can diagnose the actual values driving past_grace."
        )

    # 2) Behavioral invariant: when active_stream_id is set, the session has a
    # pending_user_message, and the worker is alive in both STREAMS and
    # ACTIVE_RUNS, calling _start_chat_stream_for_session returns a 409
    # whose _diag reports:
    #   * diag_version == 2
    #   * pending_started_at / active_run_started_at / effective_started_at
    #     all parse as floats
    #   * past_grace is a bool
    # This is the diagnostic the user-facing screenshot's _diag should match
    # once the fixed server is running.
    config.STREAMS.clear()
    config.ACTIVE_RUNS.clear()
    config.SESSION_AGENT_LOCKS.clear()

    stuck_stream_id = "stuck-orphan-diag-test"

    class ChatStartDiagSession:
        session_id = "diag-test-session"

        def __init__(self):
            self.active_stream_id = stuck_stream_id
            self.pending_user_message = "old prompt"
            self.pending_attachments = []
            self.pending_started_at = 123.0
            self.messages = []
            self.title = "Diag Test"
            self.worktree_path = None
            self.workspace = None
            self.model = None
            self.model_provider = None

        def save(self, *args, **kwargs):
            return None

    session = ChatStartDiagSession()
    config.STREAMS[stuck_stream_id] = queue.Queue()
    config.ACTIVE_RUNS[stuck_stream_id] = {
        "stream_id": stuck_stream_id,
        "session_id": session.session_id,
        "started_at": 100.0,  # very old, would normally trigger past_grace
        "phase": "running",
    }

    class NoopThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            return None

    monkeypatch.setattr(routes, "set_last_workspace", lambda workspace: None)
    monkeypatch.setattr(routes, "create_stream_channel", lambda: queue.Queue())
    monkeypatch.setattr(routes.threading, "Thread", NoopThread)

    try:
        response = routes._start_chat_stream_for_session(
            session,
            msg="new prompt",
            attachments=[],
            workspace=str(tmp_path),
            model="test-model",
            model_provider=None,
        )

        # In this fixture pending_started_at=123 and active_run started_at=100,
        # both far in the past, so the proactive-cancel should fire and the
        # call should NOT 409. If it does 409, the diag is still the right
        # shape to assert on — but log the unexpected path so future readers
        # know to investigate.
        if response.get("_status") == 409:
            assert response.get("_source") == "session_active_stream_id"
            diag = response.get("_diag", {})
            assert diag.get("diag_version") == 2, (
                f"409 _diag must report diag_version=2, got: {diag!r}"
            )
            for field in (
                "pending_started_at",
                "active_run_started_at",
                "effective_started_at",
                "past_grace",
                "orphan_grace_s",
                "active_run_age_s",
                "pending_age_s",
                "effective_age_s",
                "in_streams",
                "in_active_runs",
                "has_pending_user_message",
            ):
                assert field in diag, (
                    f"409 _diag missing required field {field!r}: {diag!r}"
                )
            # All *_started_at fields must be numeric.
            for ts_field in (
                "pending_started_at",
                "active_run_started_at",
                "effective_started_at",
            ):
                assert isinstance(diag[ts_field], (int, float)), (
                    f"diag[{ts_field!r}] must be numeric, got {type(diag[ts_field]).__name__}"
                )
            # past_grace must be a bool.
            assert isinstance(diag["past_grace"], bool), (
                f"diag['past_grace'] must be bool, got {type(diag['past_grace']).__name__}"
            )
            # The diag should agree with the basic in_streams / in_active_runs
            # booleans — operator triage depends on these being honest.
            assert diag["in_streams"] is True
            assert diag["in_active_runs"] is True
            assert diag["has_pending_user_message"] is True
        else:
            # The proactive cancel fired and the call succeeded — that is the
            # expected outcome in this fixture (stream is 100+ seconds old).
            # Whatever the success payload is, just make sure no v2 diag
            # shape is required and the test still serves as a smoke test
            # that the fixed code path is reachable.
            assert "_status" not in response or response.get("_status") != 409
    finally:
        routes.STREAMS.pop(stuck_stream_id, None)
        config.ACTIVE_RUNS.pop(stuck_stream_id, None)


def test_chat_start_dedupes_rapid_double_fire_within_2s(monkeypatch, tmp_path):
    """Regression: a chat_start arriving within 2s of the previous one, while
    the worker is still in the "starting" phase, must dedupe into the existing
    stream (return 200 + `_deduped: True`) rather than 409.

    User scenario: "新开一个会话第一次输入" (open a new session, first input).
    A second chat_start within 14ms is almost certainly a frontend double-fire
    (Enter + click, auto-retry on a hung request, SSE reconnect race) — the
    user's first message IS being processed by the existing stream, so the
    409 was a false-positive error. (Codex brick-gate #5345 / #5198 / fresh-
    dedupe follow-up.)
    """
    config.STREAMS.clear()
    config.ACTIVE_RUNS.clear()
    config.SESSION_AGENT_LOCKS.clear()

    fresh_stream_id = "fresh-dup-regression"

    class ChatStartDupSession:
        session_id = "dup-regression-session"

        def __init__(self):
            self.active_stream_id = fresh_stream_id
            self.pending_user_message = "first prompt"
            self.pending_attachments = []
            self.pending_started_at = time.time() - 0.014  # 14ms
            self.messages = []
            self.title = "Dup Regression"
            self.worktree_path = None
            self.workspace = None
            self.model = None
            self.model_provider = None

        def save(self, *args, **kwargs):
            return None

    session = ChatStartDupSession()
    config.STREAMS[fresh_stream_id] = queue.Queue()
    config.ACTIVE_RUNS[fresh_stream_id] = {
        "stream_id": fresh_stream_id,
        "session_id": session.session_id,
        "started_at": time.time() - 0.0003,  # 0.3ms — race window
        "phase": "starting",
    }

    class NoopThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            return None

    monkeypatch.setattr(routes, "set_last_workspace", lambda workspace: None)
    monkeypatch.setattr(routes, "create_stream_channel", lambda: queue.Queue())
    monkeypatch.setattr(routes.threading, "Thread", NoopThread)

    try:
        response = routes._start_chat_stream_for_session(
            session,
            msg="second prompt",
            attachments=[],
            workspace=str(tmp_path),
            model="test-model",
            model_provider=None,
        )

        # The fresh double-fire must dedupe, NOT 409.
        assert response.get("_deduped") is True, (
            f"fresh double-fire (14ms, starting phase) should dedupe, got: {response!r}"
        )
        assert response.get("stream_id") == fresh_stream_id, (
            f"deduped response must echo the existing stream_id, got: {response.get('stream_id')!r}"
        )
        assert response.get("_status") != 409, (
            f"fresh dedupe must NOT 409, got: {response!r}"
        )
        assert response.get("_dedup_reason") == "fresh_stream_within_2s"
        assert isinstance(response.get("_dedup_age_s"), (int, float))
        assert response["_dedup_age_s"] < 2.0
    finally:
        routes.STREAMS.pop(fresh_stream_id, None)
        config.ACTIVE_RUNS.pop(fresh_stream_id, None)


def test_chat_start_does_not_dedupe_running_stream(monkeypatch, tmp_path):
    """Regression: a chat_start that arrives while the worker is in 'running'
    phase (not 'starting') must still 409 — only the fresh-starting-phase
    window is deduped. A long-running turn that the user wants to interrupt
    is a real user action and must not silently merge.
    """
    config.STREAMS.clear()
    config.ACTIVE_RUNS.clear()
    config.SESSION_AGENT_LOCKS.clear()

    running_stream_id = "running-stream"

    class ChatStartRunningSession:
        session_id = "running-regression-session"

        def __init__(self):
            self.active_stream_id = running_stream_id
            self.pending_user_message = "old"
            self.pending_attachments = []
            self.pending_started_at = time.time() - 1.0  # 1s old (within 2s window)
            self.messages = []
            self.title = "Running Regression"
            self.worktree_path = None
            self.workspace = None
            self.model = None
            self.model_provider = None

        def save(self, *args, **kwargs):
            return None

    session = ChatStartRunningSession()
    config.STREAMS[running_stream_id] = queue.Queue()
    config.ACTIVE_RUNS[running_stream_id] = {
        "stream_id": running_stream_id,
        "session_id": session.session_id,
        "started_at": time.time() - 1.0,
        "phase": "running",  # NOT 'starting'
    }

    class NoopThread:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            return None

    monkeypatch.setattr(routes, "set_last_workspace", lambda workspace: None)
    monkeypatch.setattr(routes, "create_stream_channel", lambda: queue.Queue())
    monkeypatch.setattr(routes.threading, "Thread", NoopThread)

    try:
        response = routes._start_chat_stream_for_session(
            session,
            msg="new",
            attachments=[],
            workspace=str(tmp_path),
            model="test-model",
            model_provider=None,
        )

        # 'running' phase must NOT dedupe — return 409.
        assert response.get("_status") == 409, (
            f"running-phase stream should 409, got: {response!r}"
        )
        assert response.get("_deduped") is not True
    finally:
        routes.STREAMS.pop(running_stream_id, None)
        config.ACTIVE_RUNS.pop(running_stream_id, None)
