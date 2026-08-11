"""Slow request diagnostics for latency-sensitive browser API paths."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sys
import threading
import time
import traceback
import uuid
from typing import Any


DEFAULT_SLOW_REQUEST_SECONDS = 5.0
MAX_STACK_FRAMES_PER_THREAD = 40

# Process-global watchdog: a single daemon thread scans all in-flight
# RequestDiagnostics instances instead of each request spawning its own
# threading.Timer. A Timer-per-request spawns one OS thread per request, held
# alive until finish() cancels it; under sustained /api/sessions poll load that
# exhausts the per-process thread cap ("RuntimeError: can't start new thread")
# and the server stops accepting connections (#4973). One watchdog thread per
# process caps the timeout-tracking cost regardless of request rate.
_WATCHDOG_TICK_SECONDS = 1.0
_watchdog_lock = threading.Lock()
_watchdog_pending: "dict[str, tuple[float, RequestDiagnostics]]" = {}
_watchdog_cv = threading.Condition(_watchdog_lock)
_watchdog_thread: "threading.Thread | None" = None


def _ensure_watchdog_running() -> None:
    global _watchdog_thread
    # Caller already holds _watchdog_lock.
    if _watchdog_thread is not None and _watchdog_thread.is_alive():
        return
    t = threading.Thread(
        target=_watchdog_loop,
        name="request-diagnostics-watchdog",
        daemon=True,
    )
    _watchdog_thread = t
    t.start()


def _watchdog_loop() -> None:
    # The loop body cannot raise while holding _watchdog_cv (the scan is pure
    # dict ops; _on_timeout is fired outside the lock inside a try/except), so
    # the watchdog thread never dies with entries pending. _ensure_watchdog_running
    # therefore only needs to (re)spawn lazily on register, not supervise a crash.
    while True:
        fired: list[RequestDiagnostics] = []
        with _watchdog_cv:
            # Sleep until the next tick, but wake early if work arrives/changes.
            _watchdog_cv.wait(_WATCHDOG_TICK_SECONDS)
            if _watchdog_pending:
                now = time.monotonic()
                expired = [
                    rid for rid, (deadline, _diag) in _watchdog_pending.items()
                    if now >= deadline
                ]
                for rid in expired:
                    _deadline, diag = _watchdog_pending.pop(rid)
                    fired.append(diag)
        # Fire _on_timeout outside the watchdog lock so a slow logger / stack
        # snapshot can't stall the scan or block registering new requests.
        for diag in fired:
            try:
                diag._on_timeout()
            except Exception:  # never let one bad record kill the watchdog
                pass


def _watchdog_register(request_id: str, deadline: float, diag: "RequestDiagnostics") -> None:
    with _watchdog_cv:
        _watchdog_pending[request_id] = (deadline, diag)
        _ensure_watchdog_running()
        _watchdog_cv.notify()


def _watchdog_unregister(request_id: str) -> None:
    with _watchdog_cv:
        _watchdog_pending.pop(request_id, None)


def _slow_request_seconds() -> float:
    raw = os.getenv("HERMES_WEBUI_SLOW_REQUEST_SECONDS", "").strip()
    if not raw:
        return DEFAULT_SLOW_REQUEST_SECONDS
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_SLOW_REQUEST_SECONDS
    return max(0.0, value)


def _log_all_requests() -> bool:
    """Return whether completed target requests should be logged.

    The default remains slow-request-only.  The opt-in mode is intended for a
    bounded staging/production measurement window and is deliberately read at
    finish time so operators can turn collection off without restarting.
    """
    enabled = os.getenv("HERMES_WEBUI_REQUEST_DIAGNOSTICS", "").strip().lower()
    if enabled in {
        "1",
        "true",
        "yes",
        "on",
        "all",
    }:
        return True
    # Preserve the documented legacy switch: SLOW_REQUEST_SECONDS=0 means
    # collect every completed target request, without enabling stack watchdogs.
    legacy_value = os.getenv("HERMES_WEBUI_SLOW_REQUEST_SECONDS", "").strip()
    return bool(legacy_value) and _slow_request_seconds() == 0


class RequestDiagnostics:
    """Track request stages and emit a watchdog record if a request wedges."""

    def __init__(
        self,
        method: str,
        path: str,
        *,
        logger: logging.Logger | None = None,
        timeout_seconds: float | None = None,
        auto_start: bool = True,
    ) -> None:
        self.request_id = uuid.uuid4().hex[:10]
        self.method = str(method or "-")
        self.path = str(path or "-").split("?", 1)[0]
        self.logger = logger or logging.getLogger(__name__)
        self.timeout_seconds = _slow_request_seconds() if timeout_seconds is None else max(0.0, float(timeout_seconds))
        self.started_monotonic = time.monotonic()
        self.started_wall = time.time()
        self._lock = threading.Lock()
        self._stages: list[dict[str, Any]] = []
        self._current_stage = "start"
        self._current_stage_started = self.started_monotonic
        self._finished = False
        self._watchdog_logged = False
        self._context: dict[str, Any] = {}
        self._response_status: int | None = None
        self._response_bytes: int | None = None
        if auto_start and self.timeout_seconds > 0:
            _watchdog_register(
                self.request_id,
                self.started_monotonic + self.timeout_seconds,
                self,
            )

    @classmethod
    def maybe_start(
        cls,
        method: str,
        path: str,
        *,
        logger: logging.Logger | None = None,
    ) -> "RequestDiagnostics | None":
        clean_path = str(path or "").split("?", 1)[0]
        if method.upper() == "GET":
            target = clean_path in {
                "/api/sessions",
                "/api/session/status",
                "/api/approval/pending",
                "/api/clarify/pending",
                "/api/auth/status",
                "/api/license/status",
                "/api/health/agent",
                "/api/crons/recent",
                "/api/dashboard/status",
            }
        else:
            target = method.upper() == "POST" and clean_path == "/api/chat/start"
        if not target:
            return None
        return cls(method, clean_path, logger=logger)

    def bind_context(self, **values: Any) -> None:
        """Attach non-sensitive request context for slow-request records.

        Values named ``*_cookie``, ``user_id`` or ``profile`` are hashed with
        this request's id before logging.  The request id acts as a per-record
        salt, so diagnostics can correlate stages within one request without
        creating a reusable identity lookup table.
        """
        with self._lock:
            if self._finished:
                return
            for key, value in values.items():
                if value is None or value == "":
                    continue
                text = str(value)
                if key.endswith("_cookie") or key in {"user_id", "profile"}:
                    digest = hashlib.sha256(
                        f"{self.request_id}:{key}:{text}".encode("utf-8")
                    ).hexdigest()[:16]
                    self._context[f"{key}_hash"] = digest
                else:
                    self._context[key] = value

    def set_response(self, *, status: int | None = None, body_bytes: int | None = None) -> None:
        """Record response metadata without retaining the response payload."""
        with self._lock:
            if status is not None:
                try:
                    self._response_status = int(status)
                except (TypeError, ValueError):
                    self._response_status = None
            if body_bytes is not None:
                try:
                    self._response_bytes = max(0, int(body_bytes))
                except (TypeError, ValueError):
                    self._response_bytes = None

    def stage(self, name: str) -> None:
        now = time.monotonic()
        clean = str(name or "unknown").strip() or "unknown"
        with self._lock:
            if self._finished:
                return
            self._stages.append(
                {
                    "name": self._current_stage,
                    "ms": round((now - self._current_stage_started) * 1000, 1),
                }
            )
            self._current_stage = clean
            self._current_stage_started = now

    def finish(self) -> None:
        record = None
        with self._lock:
            if self._finished:
                return
            self._finished = True
            record = self._build_record_locked(include_stacks=False)
        # Drop ourselves from the watchdog so the process-global scan never
        # fires _on_timeout for a completed request (and the pending dict stays
        # bounded by the number of in-flight requests).
        _watchdog_unregister(self.request_id)
        if not record:
            return
        elapsed_over_threshold = (
            self.timeout_seconds > 0
            and record["elapsed_ms"] >= self.timeout_seconds * 1000
        )
        if _log_all_requests():
            # Warning is intentional here: the standalone server keeps the
            # root logger at WARNING unless an operator configures logging.
            # The opt-in flag already acknowledges the temporary log volume.
            self.logger.warning(
                "WebUI request diagnostics: %s",
                json.dumps(record, sort_keys=True),
            )
        elif elapsed_over_threshold:
            self.logger.warning(
                "Slow WebUI request completed: %s",
                json.dumps(record, sort_keys=True),
            )

    def _on_timeout(self) -> None:
        with self._lock:
            if self._finished or self._watchdog_logged:
                return
            self._watchdog_logged = True
            record = self._build_record_locked(include_stacks=True)
        self.logger.warning(
            "Slow WebUI request still running: %s",
            json.dumps(record, sort_keys=True),
        )

    def _build_record_locked(self, *, include_stacks: bool) -> dict[str, Any]:
        now = time.monotonic()
        stages = list(self._stages)
        stages.append(
            {
                "name": self._current_stage,
                "ms": round((now - self._current_stage_started) * 1000, 1),
            }
        )
        record: dict[str, Any] = {
            "request_id": self.request_id,
            "method": self.method,
            "path": self.path,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.started_wall)),
            "elapsed_ms": round((now - self.started_monotonic) * 1000, 1),
            "current_stage": self._current_stage,
            "stages": stages,
        }
        if self._context:
            record["context"] = dict(self._context)
        if self._response_status is not None:
            record["response_status"] = self._response_status
        if self._response_bytes is not None:
            record["response_bytes"] = self._response_bytes
        if include_stacks:
            record["thread_stacks"] = _thread_stack_snapshot()
        return record


def _thread_stack_snapshot() -> list[dict[str, Any]]:
    frames = sys._current_frames()
    threads = {thread.ident: thread for thread in threading.enumerate()}
    snapshot: list[dict[str, Any]] = []
    for ident, frame in frames.items():
        thread = threads.get(ident)
        stack = traceback.format_stack(frame, limit=MAX_STACK_FRAMES_PER_THREAD)
        snapshot.append(
            {
                "thread_id": ident,
                "thread_name": thread.name if thread else "",
                "daemon": bool(thread.daemon) if thread else None,
                "stack": [line.rstrip() for line in stack],
            }
        )
    snapshot.sort(key=lambda item: str(item.get("thread_name") or ""))
    return snapshot
