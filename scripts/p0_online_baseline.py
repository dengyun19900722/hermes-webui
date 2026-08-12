#!/usr/bin/env python3
"""Collect a bounded P0 HTTP and server-stage latency baseline.

The runner is read-only by default. It never logs cookies or response bodies.
Use HERMES_WEBUI_REQUEST_DIAGNOSTICS=1 on the target server during the bounded
collection window, then pass the captured server log with --server-log.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import http.client
import json
import math
import os
import secrets
import statistics
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


STATIC_ENDPOINTS = (
    ("auth_status", "/api/auth/status"),
    ("license_status", "/api/license/status"),
    ("agent_health", "/api/health/agent"),
    ("dashboard_status", "/api/dashboard/status"),
    ("cron_recent", "/api/crons/recent"),
    ("sessions", "/api/sessions"),
)


@dataclass
class Sample:
    endpoint: str
    path: str
    status: int
    connect_ms: float
    request_ms: float
    ttfb_ms: float
    read_ms: float
    total_ms: float
    body_bytes: int
    error: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "endpoint": self.endpoint,
            "path": self.path.split("?", 1)[0],
            "status": self.status,
            "connect_ms": round(self.connect_ms, 3),
            "request_ms": round(self.request_ms, 3),
            "ttfb_ms": round(self.ttfb_ms, 3),
            "read_ms": round(self.read_ms, 3),
            "total_ms": round(self.total_ms, 3),
            "body_bytes": self.body_bytes,
            "error": self.error,
        }


class HTTP11Client:
    def __init__(self, base_url: str, *, cookie: str, timeout: float) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("base URL must be absolute http(s)")
        self.scheme = parsed.scheme
        self.host = parsed.hostname
        self.port = parsed.port or (443 if parsed.scheme == "https" else 80)
        self.base_path = parsed.path.rstrip("/")
        self.cookie = cookie
        self.timeout = timeout
        self.conn: http.client.HTTPConnection | None = None

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def _connect(self) -> float:
        if self.conn is not None:
            return 0.0
        conn_cls = (
            http.client.HTTPSConnection
            if self.scheme == "https"
            else http.client.HTTPConnection
        )
        self.conn = conn_cls(self.host, self.port, timeout=self.timeout)
        started = time.perf_counter()
        self.conn.connect()
        return (time.perf_counter() - started) * 1000

    def get(self, endpoint: str, path: str) -> tuple[Sample, bytes]:
        started = time.perf_counter()
        connect_ms = request_ms = ttfb_ms = read_ms = 0.0
        status = 0
        body = b""
        try:
            connect_ms = self._connect()
            headers = {
                "Accept": "application/json",
                "Connection": "keep-alive",
                "User-Agent": "Hermes-P0-Baseline/1.0",
            }
            if self.cookie:
                headers["Cookie"] = self.cookie
            request_started = time.perf_counter()
            assert self.conn is not None
            self.conn.request("GET", self.base_path + path, headers=headers)
            request_ms = (time.perf_counter() - request_started) * 1000
            response_started = time.perf_counter()
            response = self.conn.getresponse()
            ttfb_ms = (time.perf_counter() - response_started) * 1000
            status = response.status
            read_started = time.perf_counter()
            body = response.read()
            read_ms = (time.perf_counter() - read_started) * 1000
            if response.getheader("Connection", "").lower() == "close":
                self.close()
            error = ""
        except Exception as exc:
            self.close()
            error = type(exc).__name__
        total_ms = (time.perf_counter() - started) * 1000
        return Sample(
            endpoint=endpoint,
            path=path,
            status=status,
            connect_ms=connect_ms,
            request_ms=request_ms,
            ttfb_ms=ttfb_ms,
            read_ms=read_ms,
            total_ms=total_ms,
            body_bytes=len(body),
            error=error,
        ), body


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(0, math.ceil(percentile * len(ordered)) - 1)
    return round(ordered[rank], 3)


def _distribution(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"count": 0, "p50": None, "p95": None, "p99": None, "max": None}
    return {
        "count": len(values),
        "p50": round(statistics.median(values), 3),
        "p95": _percentile(values, 0.95),
        "p99": _percentile(values, 0.99),
        "max": round(max(values), 3),
    }


def _discover_session_id(client: HTTP11Client) -> tuple[str, Sample]:
    sample, body = client.get("sessions_discovery", "/api/sessions")
    if sample.status != 200:
        return "", sample
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "", sample
    rows = payload.get("sessions", []) if isinstance(payload, dict) else []
    for row in rows:
        if not isinstance(row, dict) or row.get("is_cli_session") is True:
            continue
        session_id = str(row.get("session_id") or "")
        if session_id:
            return session_id, sample
    return "", sample


def _verify_expected_user(client: HTTP11Client, expected_user_id: str) -> None:
    if not expected_user_id:
        return
    sample, body = client.get("auth_identity_check", "/api/auth/status")
    if sample.status != 200 or sample.error:
        raise ValueError("authentication identity preflight failed")
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("authentication identity preflight returned invalid JSON") from exc
    user = payload.get("user") if isinstance(payload, dict) else None
    actual_user_id = str(user.get("id") or "") if isinstance(user, dict) else ""
    if not actual_user_id or not secrets.compare_digest(
        actual_user_id,
        expected_user_id,
    ):
        raise ValueError("authenticated user does not match P0_EXPECTED_USER_ID")


def _endpoint_matrix(session_id: str) -> list[tuple[str, str]]:
    endpoints = list(STATIC_ENDPOINTS)
    if session_id:
        suffix = f"?session_id={session_id}"
        endpoints.extend(
            (
                ("session_status", "/api/session/status" + suffix),
                ("approval_pending", "/api/approval/pending" + suffix),
                ("clarify_pending", "/api/clarify/pending" + suffix),
            )
        )
    return endpoints


def _run_worker(
    base_url: str,
    cookie: str,
    timeout: float,
    endpoint: str,
    path: str,
    count: int,
) -> list[Sample]:
    client = HTTP11Client(base_url, cookie=cookie, timeout=timeout)
    try:
        return [client.get(endpoint, path)[0] for _ in range(count)]
    finally:
        client.close()


def _run_samples(
    base_url: str,
    cookie: str,
    timeout: float,
    endpoints: list[tuple[str, str]],
    requests_per_endpoint: int,
    concurrency: int,
) -> list[Sample]:
    samples: list[Sample] = []
    for endpoint, path in endpoints:
        counts = [requests_per_endpoint // concurrency] * concurrency
        for index in range(requests_per_endpoint % concurrency):
            counts[index] += 1
        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = [
                pool.submit(
                    _run_worker,
                    base_url,
                    cookie,
                    timeout,
                    endpoint,
                    path,
                    count,
                )
                for count in counts
                if count
            ]
            for future in futures:
                samples.extend(future.result())
    return samples


def _summarize_client(samples: list[Sample]) -> dict[str, Any]:
    grouped: dict[str, list[Sample]] = defaultdict(list)
    for sample in samples:
        grouped[sample.endpoint].append(sample)
    result: dict[str, Any] = {}
    for endpoint, rows in sorted(grouped.items()):
        result[endpoint] = {
            "statuses": dict(sorted(Counter(row.status for row in rows).items())),
            "errors": dict(sorted(Counter(row.error for row in rows if row.error).items())),
            "body_bytes": _distribution([float(row.body_bytes) for row in rows]),
            "connect_ms": _distribution([row.connect_ms for row in rows]),
            "request_ms": _distribution([row.request_ms for row in rows]),
            "ttfb_ms": _distribution([row.ttfb_ms for row in rows]),
            "read_ms": _distribution([row.read_ms for row in rows]),
            "total_ms": _distribution([row.total_ms for row in rows]),
        }
    return result


def _server_log_size(path: Path | None) -> int:
    if path is None:
        return 0
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _parse_server_diagnostics(
    path: Path | None,
    *,
    start_offset: int = 0,
) -> list[dict[str, Any]]:
    if path is None or not path.exists():
        return []
    records: list[dict[str, Any]] = []
    markers = ("WebUI request diagnostics: ", "Slow WebUI request completed: ")
    with path.open("rb") as log_file:
        log_file.seek(0, os.SEEK_END)
        end_offset = log_file.tell()
        safe_offset = start_offset if 0 <= start_offset <= end_offset else 0
        if safe_offset:
            log_file.seek(safe_offset - 1)
            if log_file.read(1) != b"\n":
                log_file.readline()
        else:
            log_file.seek(0)
        log_text = log_file.read().decode("utf-8", errors="replace")
    for line in log_text.splitlines():
        payload = ""
        for marker in markers:
            if marker in line:
                payload = line.split(marker, 1)[1].strip()
                break
        if not payload:
            continue
        try:
            record = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _validate_client(samples: list[Sample]) -> list[str]:
    failures = []
    for sample in samples:
        if sample.error:
            failures.append(f"{sample.endpoint}: {sample.error}")
        elif sample.status != 200:
            failures.append(f"{sample.endpoint}: unexpected HTTP {sample.status}")
    return sorted(set(failures))


def _summarize_server(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_path: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        by_path[str(record.get("path") or "unknown")].append(record)
    result: dict[str, Any] = {}
    for path, path_records in sorted(by_path.items()):
        stage_values: dict[str, list[float]] = defaultdict(list)
        elapsed = []
        for record in path_records:
            elapsed.append(float(record.get("elapsed_ms") or 0))
            for stage in record.get("stages") or []:
                if not isinstance(stage, dict):
                    continue
                stage_values[str(stage.get("name") or "unknown")].append(
                    float(stage.get("ms") or 0)
                )
        stage_summary = {
            stage: _distribution(values)
            for stage, values in sorted(stage_values.items())
        }
        p50_total = _distribution(elapsed)["p50"] or 0
        stage_share = {}
        if p50_total:
            for stage, summary in stage_summary.items():
                stage_share[stage] = round(
                    100 * float(summary["p50"] or 0) / float(p50_total), 2
                )
        result[path] = {
            "elapsed_ms": _distribution(elapsed),
            "stages_ms": stage_summary,
            "p50_stage_share_percent": stage_share,
        }
    return result


def _render_report(
    base_url: str,
    client_summary: dict[str, Any],
    server_summary: dict[str, Any],
    record_count: int,
    validation_failures: list[str],
) -> str:
    lines = [
        "# P0 Online Baseline Result",
        "",
        f"- Base URL: `{base_url}`",
        f"- Generated at: `{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}`",
        f"- Server diagnostic records: `{record_count}`",
        f"- Validation: `{'FAIL' if validation_failures else 'PASS'}`",
        "",
        "## Client Latency",
        "",
        "| Endpoint | Status | p50 total | p95 total | p99 total | p50 TTFB |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for endpoint, summary in sorted(client_summary.items()):
        status = ", ".join(f"{key}:{value}" for key, value in summary["statuses"].items())
        total = summary["total_ms"]
        ttfb = summary["ttfb_ms"]
        lines.append(
            f"| {endpoint} | {status} | {total['p50']} ms | {total['p95']} ms | "
            f"{total['p99']} ms | {ttfb['p50']} ms |"
        )
    if validation_failures:
        lines.extend(["", "## Validation Failures", ""])
        lines.extend(f"- `{failure}`" for failure in validation_failures)
    lines.extend(["", "## Server Stage Distribution", ""])
    if not server_summary:
        lines.append(
            "No server stage records found. Enable `HERMES_WEBUI_REQUEST_DIAGNOSTICS=1` "
            "for the bounded collection window and provide `--server-log`."
        )
    for path, summary in sorted(server_summary.items()):
        lines.extend(
            [
                f"### `{path}`",
                "",
                "| Stage | p50 | p95 | p99 | p50 share |",
                "|---|---:|---:|---:|---:|",
            ]
        )
        shares = summary["p50_stage_share_percent"]
        for stage, distribution in summary["stages_ms"].items():
            lines.append(
                f"| {stage} | {distribution['p50']} ms | {distribution['p95']} ms | "
                f"{distribution['p99']} ms | {shares.get(stage, 0)}% |"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--requests-per-endpoint", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--server-log", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--cookie-env",
        default="P0_TEST_COOKIE",
        help="environment variable containing a Cookie header; value is never written",
    )
    parser.add_argument(
        "--expected-user-id-env",
        default="P0_EXPECTED_USER_ID",
        help="environment variable containing the required authenticated user id",
    )
    args = parser.parse_args()
    if args.requests_per_endpoint < 1 or args.concurrency < 1:
        parser.error("requests and concurrency must be positive")

    cookie = os.getenv(args.cookie_env, "")
    expected_user_id = os.getenv(args.expected_user_id_env, "").strip()
    discovery_client = HTTP11Client(args.base_url, cookie=cookie, timeout=args.timeout)
    try:
        try:
            _verify_expected_user(discovery_client, expected_user_id)
        except ValueError as exc:
            print(f"P0 preflight failed: {exc}", file=sys.stderr)
            return 2
        session_id, discovery_sample = _discover_session_id(discovery_client)
        # Keep the discovery/cold request in client evidence, but exclude it
        # from the warm server-stage distribution used for endpoint comparison.
        server_log_start_offset = _server_log_size(args.server_log)
    finally:
        discovery_client.close()
    endpoints = _endpoint_matrix(session_id)
    samples = [discovery_sample]
    samples.extend(
        _run_samples(
            args.base_url,
            cookie,
            args.timeout,
            endpoints,
            args.requests_per_endpoint,
            args.concurrency,
        )
    )
    records = _parse_server_diagnostics(
        args.server_log,
        start_offset=server_log_start_offset,
    )
    client_summary = _summarize_client(samples)
    server_summary = _summarize_server(records)
    validation_failures = _validate_client(samples)

    args.output_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "base_url": args.base_url,
        "requests_per_endpoint": args.requests_per_endpoint,
        "concurrency": args.concurrency,
        "expected_identity_checked": bool(expected_user_id),
        "session_status_endpoints_included": bool(session_id),
        "server_log_start_offset": server_log_start_offset,
        "validation_failures": validation_failures,
        "client": client_summary,
        "server": server_summary,
        "samples": [sample.as_dict() for sample in samples],
    }
    (args.output_dir / "p0-baseline.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
    )
    (args.output_dir / "p0-baseline.md").write_text(
        _render_report(
            args.base_url,
            client_summary,
            server_summary,
            len(records),
            validation_failures,
        ),
        encoding="utf-8",
    )
    print(args.output_dir / "p0-baseline.md")
    return 2 if validation_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
