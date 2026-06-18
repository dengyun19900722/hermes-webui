"""Controlled remote log context lookup for WebUI chat log references."""

from __future__ import annotations

import ipaddress
import json
import os
import posixpath
import re
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qs

from api.config import REPO_ROOT, get_config


BEGIN_MARKER = "__HERMES_LOG_CONTEXT_BEGIN__"
END_MARKER = "__HERMES_LOG_CONTEXT_END__"
TRUNCATED_MARKER = "__HERMES_LOG_CONTEXT_TRUNCATED__"

_log_buf: list[str] = []


def _log_event(**fields: Any) -> None:
    record = json.dumps({
        'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        **fields,
    })
    print(f'[webui] {record}', flush=True)


def _log_context_req(req: LogContextRequest) -> dict[str, Any]:
    return {
        "source": req.source.source_id,
        "host_ip": req.host_ip,
        "account": req.account,
        "path": req.path,
        "line": req.line,
        "before": req.before,
        "after": req.after,
    }

DEFAULT_BEFORE = 50
DEFAULT_AFTER = 50
DEFAULT_TIMEOUT_SECONDS = 8
DEFAULT_MAX_CONTEXT_LINES = 500
DEFAULT_MAX_RESPONSE_BYTES = 1024 * 1024
DEFAULT_ALLOWED_SUFFIXES = (".log", ".txt", ".out")
HARD_MAX_CONTEXT_LINES = 5000
HARD_MAX_RESPONSE_BYTES = 5 * 1024 * 1024
HARD_MAX_TIMEOUT_SECONDS = 60

_SOURCE_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_HOST_RE = re.compile(r"^[A-Za-z0-9._:-]{1,255}$")
_USER_RE = re.compile(r"^[A-Za-z0-9._@-]{1,128}$")


class LogContextError(Exception):
    """Expected API-facing log context failure."""

    def __init__(self, message: str, *, code: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class LogContextSource:
    source_id: str
    mode: str
    host: str
    port: int
    user: str
    password_env: str
    roots: tuple[str, ...]
    timeout_seconds: int
    max_context_lines: int
    max_response_bytes: int
    allowed_suffixes: tuple[str, ...] | None
    host_ip: str = ""
    account: str = ""
    password_value: str = field(default="", repr=False)


@dataclass(frozen=True)
class LogContextRequest:
    source: LogContextSource
    path: str
    line: int
    start_line: int
    end_line: int
    before: int
    after: int
    requested_before: int
    requested_after: int
    session_id: str
    clipped: bool
    host_ip: str
    account: str


def _int_value(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _config_value(*keys: str) -> Any:
    cfg = get_config()
    if isinstance(cfg, dict):
        for key in keys:
            if key in cfg:
                return cfg.get(key)
        webui_cfg = cfg.get("webui")
        if isinstance(webui_cfg, dict):
            for key in keys:
                if key in webui_cfg:
                    return webui_cfg.get(key)
    return None


def _configured_sources() -> dict[str, Any]:
    raw = _config_value("log_context_sources")
    return raw if isinstance(raw, dict) else {}


def _normalize_remote_path(path: str) -> str:
    raw = str(path or "").strip()
    if not raw:
        raise LogContextError("path is required", code="missing_path", status=400)
    if "\x00" in raw or any(ord(ch) < 32 for ch in raw):
        raise LogContextError("log path contains invalid characters", code="invalid_path", status=400)
    if len(raw) > 4096:
        raise LogContextError("log path is too long", code="invalid_path", status=400)
    if not raw.startswith("/"):
        raise LogContextError("log path must be absolute", code="invalid_path", status=400)
    normalized = posixpath.normpath(raw)
    if not normalized.startswith("/"):
        raise LogContextError("log path must be absolute", code="invalid_path", status=400)
    return normalized


def _normalize_host_ip(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if len(raw) > 128 or "\x00" in raw or any(ord(ch) < 32 for ch in raw):
        raise LogContextError("host_ip is invalid", code="invalid_host_ip", status=400)
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError as exc:
        raise LogContextError("host_ip is invalid", code="invalid_host_ip", status=400) from exc


def _normalize_account(value: Any) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    if not _USER_RE.fullmatch(raw):
        raise LogContextError("account is invalid", code="invalid_account", status=400)
    return raw


def _normalize_password_value(value: Any) -> str:
    raw = str(value or "")
    if not raw:
        return ""
    if "\x00" in raw or any(ord(ch) < 32 for ch in raw):
        return ""
    if len(raw) > 4096:
        return ""
    return raw


def _normalize_roots(raw_roots: Any) -> tuple[str, ...]:
    roots: list[str] = []
    if not isinstance(raw_roots, list):
        return tuple()
    for raw in raw_roots:
        try:
            root = _normalize_remote_path(str(raw))
        except LogContextError:
            continue
        if root not in roots:
            roots.append(root.rstrip("/") or "/")
    return tuple(roots)


def _path_under_roots(path: str, roots: tuple[str, ...]) -> bool:
    for root in roots:
        if root == "/":
            return True
        if path == root or path.startswith(root.rstrip("/") + "/"):
            return True
    return False


def _normalize_allowed_suffixes(raw: Any) -> tuple[str, ...] | None:
    if raw is None:
        return DEFAULT_ALLOWED_SUFFIXES
    if not isinstance(raw, list):
        return DEFAULT_ALLOWED_SUFFIXES
    suffixes: list[str] = []
    for item in raw:
        suffix = str(item or "").strip().lower()
        if not suffix:
            continue
        if not suffix.startswith("."):
            suffix = "." + suffix
        if re.fullmatch(r"\.[a-z0-9._-]{1,32}", suffix):
            suffixes.append(suffix)
    return tuple(dict.fromkeys(suffixes)) if suffixes else None


def _suffix_allowed(path: str, suffixes: tuple[str, ...] | None) -> bool:
    if suffixes is None:
        return True
    name = PurePosixPath(path).name.lower()
    for suffix in suffixes:
        if name.endswith(suffix) or f"{suffix}." in name:
            return True
    return False








def _neo4j_host_lookup(host_ip: str) -> tuple[str, dict[str, Any]] | None:
    uri = str(os.environ.get("NEO4J_URI") or "").strip()
    user = str(os.environ.get("NEO4J_USER") or "").strip()
    password = str(os.environ.get("NEO4J_PASSWORD") or "")
    if not uri or not user or not password:
        print(json.dumps({
            'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'level': 'WARN',
            'event': 'neo4j_env_missing',
            'host_ip': host_ip,
            'uri': bool(uri),
            'user': bool(user),
            'password': bool(password),
        }), flush=True)
        return None
    try:
        from neo4j import GraphDatabase, Query
    except Exception as exc:
        print(json.dumps({
            'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'level': 'WARN',
            'event': 'neo4j_import_failed',
            'host_ip': host_ip,
            'error': str(exc),
        }), flush=True)
        return None

    driver = None
    try:
        driver = GraphDatabase.driver(
            uri,
            auth=(user, password),
            connection_timeout=3,
        )
        query = (
            "MATCH (h:Host {ip: $host_ip}) "
            "RETURN h.ssh_user AS ssh_user, "
            "h.ssh_password AS ssh_password, "
            "h.ssh_port AS ssh_port"
        )
        with driver.session() as session:
            record = session.run(Query(query, timeout=5), host_ip=host_ip).single()
        if not record:
            print(json.dumps({
                'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'level': 'WARN',
                'event': 'neo4j_no_record',
                'host_ip': host_ip,
            }), flush=True)
            return None
        ssh_user = _normalize_account(record.get("ssh_user"))
        ssh_password = _normalize_password_value(record.get("ssh_password"))
        if not ssh_user or not ssh_password:
            print(json.dumps({
                'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'level': 'WARN',
                'event': 'neo4j_incomplete_credentials',
                'host_ip': host_ip,
                'ssh_user': bool(ssh_user),
                'ssh_password': bool(ssh_password),
            }), flush=True)
            return None
        port = _int_value(record.get("ssh_port", 22), default=22, minimum=1, maximum=65535)
        print(json.dumps({
            'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'level': 'INFO',
            'event': 'neo4j_lookup_ok',
            'host_ip': host_ip,
            'user': ssh_user,
            'port': port,
        }), flush=True)
        return (
            f"neo4j:{host_ip}",
            {
                "mode": "expect_ssh",
                "host": host_ip,
                "host_ip": host_ip,
                "user": ssh_user,
                "account": ssh_user,
                "password_value": ssh_password,
                "port": port,
            },
        )
    except Exception as exc:
        print(json.dumps({
            'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'level': 'WARN',
            'event': 'neo4j_lookup_failed',
            'host_ip': host_ip,
            'error': str(exc),
        }), flush=True)
        return None
    finally:
        if driver is not None:
            try:
                driver.close()
            except Exception:
                pass


def _copy_source_defaults(raw: dict[str, Any], template: LogContextSource | None) -> dict[str, Any]:
    if template is None:
        return raw
    merged = dict(raw)
    merged.setdefault("mode", template.mode)
    merged.setdefault("port", template.port)
    merged.setdefault("roots", list(template.roots))
    merged.setdefault("timeout_seconds", template.timeout_seconds)
    merged.setdefault("max_context_lines", template.max_context_lines)
    merged.setdefault("max_response_bytes", template.max_response_bytes)
    if "allowed_suffixes" not in merged:
        merged["allowed_suffixes"] = (
            list(template.allowed_suffixes)
            if template.allowed_suffixes is not None
            else []
        )
    return merged


def _host_source_from_lookup(
    host_ip: str,
    account: str,
    *,
    source_id: str = "",
    template: LogContextSource | None = None,
) -> LogContextSource:
    found = _neo4j_host_lookup(host_ip)
    if found is None:
        raise LogContextError("log context host is not configured", code="host_not_found", status=404)
    lookup_source_id, raw = found
    effective = _copy_source_defaults(dict(raw), template)
    effective.setdefault("host", host_ip)
    effective.setdefault("roots", ["/"])
    effective.setdefault("allowed_suffixes", [])
    resolved_account = _normalize_account(
        effective.get("account") or effective.get("user") or effective.get("username") or account
    )
    if not resolved_account:
        raise LogContextError("log context host account is missing", code="source_invalid", status=503)
    effective["user"] = resolved_account
    if effective.get("password") or effective.get("password_runtime"):
        raise LogContextError(
            "inline log context passwords are not allowed",
            code="inline_password_not_allowed",
            status=503,
        )
    resolved_source_id = str(effective.get("source_id") or source_id or host_ip)
    source = _source_from_config(resolved_source_id, effective, password_value_allowed=True)
    return LogContextSource(
        source_id=source.source_id,
        mode=source.mode,
        host=host_ip,
        port=source.port,
        user=source.user,
        password_env=source.password_env,
        roots=source.roots,
        timeout_seconds=source.timeout_seconds,
        max_context_lines=source.max_context_lines,
        max_response_bytes=source.max_response_bytes,
        allowed_suffixes=source.allowed_suffixes,
        host_ip=host_ip,
        account=resolved_account,
        password_value=source.password_value,
    )


def _source_from_config(
    source_id: str,
    raw: Any,
    *,
    password_value_allowed: bool = False,
) -> LogContextSource:
    if not isinstance(raw, dict):
        raise LogContextError("log context source is invalid", code="source_invalid", status=503)
    mode = str(raw.get("mode") or "expect_ssh").strip().lower()
    if mode != "expect_ssh":
        raise LogContextError("log context source mode is not supported", code="mode_unsupported", status=503)
    if raw.get("password") or raw.get("password_runtime"):
        raise LogContextError(
            "inline log context passwords are not allowed",
            code="inline_password_not_allowed",
            status=503,
        )
    password_value = _normalize_password_value(raw.get("password_value")) if password_value_allowed else ""
    if raw.get("password_value") and not password_value_allowed:
        raise LogContextError(
            "inline log context passwords are not allowed",
            code="inline_password_not_allowed",
            status=503,
        )
    host = str(raw.get("host") or "").strip()
    user = str(raw.get("user") or "").strip()
    password_env = str(raw.get("password_env") or "").strip()
    if not host or not _HOST_RE.fullmatch(host):
        raise LogContextError("log context source host is invalid", code="source_invalid", status=503)
    if not user or not _USER_RE.fullmatch(user):
        raise LogContextError("log context source user is invalid", code="source_invalid", status=503)
    if password_env and not _ENV_NAME_RE.fullmatch(password_env):
        raise LogContextError("log context password_env is invalid", code="source_invalid", status=503)
    if not password_env and not password_value:
        raise LogContextError("log context password_env is invalid", code="source_invalid", status=503)
    roots = _normalize_roots(raw.get("roots"))
    if not roots:
        raise LogContextError("log context source has no allowed roots", code="source_invalid", status=503)
    port = _int_value(raw.get("port", 22), default=22, minimum=1, maximum=65535)
    timeout_seconds = _int_value(
        raw.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS),
        default=DEFAULT_TIMEOUT_SECONDS,
        minimum=1,
        maximum=HARD_MAX_TIMEOUT_SECONDS,
    )
    max_context_lines = _int_value(
        raw.get("max_context_lines", DEFAULT_MAX_CONTEXT_LINES),
        default=DEFAULT_MAX_CONTEXT_LINES,
        minimum=1,
        maximum=HARD_MAX_CONTEXT_LINES,
    )
    max_response_bytes = _int_value(
        raw.get("max_response_bytes", DEFAULT_MAX_RESPONSE_BYTES),
        default=DEFAULT_MAX_RESPONSE_BYTES,
        minimum=1024,
        maximum=HARD_MAX_RESPONSE_BYTES,
    )
    return LogContextSource(
        source_id=source_id,
        mode=mode,
        host=host,
        port=port,
        user=user,
        password_env=password_env,
        roots=roots,
        timeout_seconds=timeout_seconds,
        max_context_lines=max_context_lines,
        max_response_bytes=max_response_bytes,
        allowed_suffixes=_normalize_allowed_suffixes(raw.get("allowed_suffixes")),
        host_ip=str(raw.get("host_ip") or raw.get("ip") or "").strip(),
        account=str(raw.get("account") or "").strip(),
        password_value=password_value,
    )


def _requested_int(qs: dict[str, list[str]], key: str, default: int, *, minimum: int = 0) -> int:
    raw = qs.get(key, [str(default)])[0]
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise LogContextError(f"{key} must be a number", code=f"invalid_{key}", status=400)
    if value < minimum:
        raise LogContextError(f"{key} is out of range", code=f"invalid_{key}", status=400)
    return value


def build_request_from_query(query: str) -> LogContextRequest:
    qs = parse_qs(query, keep_blank_values=True)
    source_id = str(qs.get("source", [""])[0] or "").strip()
    host_ip = _normalize_host_ip(qs.get("host_ip", [""])[0])
    account = _normalize_account(qs.get("account", [""])[0])
    if not source_id and not host_ip:
        raise LogContextError("source or host_ip is required", code="missing_source", status=400)
    if source_id and not _SOURCE_RE.fullmatch(source_id):
        raise LogContextError("source is invalid", code="invalid_source", status=400)

    if host_ip:
        template = None
        if source_id:
            sources = _configured_sources()
            if source_id not in sources:
                raise LogContextError("log context source is not configured", code="source_not_found", status=404)
            template = _source_from_config(source_id, sources[source_id])
        source = _host_source_from_lookup(host_ip, account, source_id=source_id, template=template)
    else:
        sources = _configured_sources()
        if source_id not in sources:
            raise LogContextError("log context source is not configured", code="source_not_found", status=404)
        source = _source_from_config(source_id, sources[source_id])
        host_ip = source.host_ip
        account = source.account

    path = _normalize_remote_path(qs.get("path", [""])[0])
    if not _path_under_roots(path, source.roots):
        raise LogContextError("log path is not allowed", code="path_not_allowed", status=403)
    if not _suffix_allowed(path, source.allowed_suffixes):
        raise LogContextError("log file suffix is not allowed", code="suffix_not_allowed", status=403)

    line = _requested_int(qs, "line", 0, minimum=1)
    requested_before = _requested_int(qs, "before", DEFAULT_BEFORE, minimum=0)
    requested_after = _requested_int(qs, "after", DEFAULT_AFTER, minimum=0)
    before, after, clipped = _clip_context_window(
        requested_before,
        requested_after,
        source.max_context_lines,
    )
    start_line = max(1, line - before)
    end_line = line + after
    effective_before = line - start_line
    if effective_before != before:
        clipped = True
    session_id = str(qs.get("session_id", [""])[0] or "").strip()
    if session_id and not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", session_id):
        raise LogContextError("session_id is invalid", code="invalid_session_id", status=400)
    return LogContextRequest(
        source=source,
        path=path,
        line=line,
        start_line=start_line,
        end_line=end_line,
        before=effective_before,
        after=after,
        requested_before=requested_before,
        requested_after=requested_after,
        session_id=session_id,
        clipped=clipped,
        host_ip=host_ip,
        account=account or source.account,
    )


def _clip_context_window(before: int, after: int, max_context_lines: int) -> tuple[int, int, bool]:
    max_extra = max(0, max_context_lines - 1)
    total_extra = before + after
    if total_extra <= max_extra:
        return before, after, False
    if total_extra <= 0:
        return 0, 0, True
    clipped_before = int(max_extra * before / total_extra)
    clipped_after = max_extra - clipped_before
    if clipped_before > before:
        clipped_before = before
        clipped_after = max_extra - clipped_before
    if clipped_after > after:
        clipped_after = after
        clipped_before = max_extra - clipped_after
    return max(0, clipped_before), max(0, clipped_after), True


def _shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _remote_command(req: LogContextRequest) -> str:
    awk_program = (
        "NR >= s && NR <= e { "
        "out = sprintf(\"%d\\t%s\\n\", NR, $0); "
        "if (bytes + length(out) > max) { print trunc; exit } "
        "bytes += length(out); printf \"%s\", out "
        "} NR > e { exit }"
    )
    return (
        f"printf '%s\\n' {_shell_quote(BEGIN_MARKER)}; "
        "awk "
        f"-v s={req.start_line} "
        f"-v e={req.end_line} "
        f"-v max={req.source.max_response_bytes} "
        f"-v trunc={_shell_quote(TRUNCATED_MARKER)} "
        f"{_shell_quote(awk_program)} {_shell_quote(req.path)}; "  # no '--' — some awk variants (busybox, mawk) choke on it
        "rc=$?; "
        f"printf '\\n%s\\n' {_shell_quote(END_MARKER)}; "
        "exit $rc"
    )


def _expect_script_path() -> Path:
    return REPO_ROOT / "scripts" / "log_context_expect.sh"


def _run_expect_script(req: LogContextRequest, password: str) -> subprocess.CompletedProcess[bytes]:
    ctx = _log_context_req(req)
    if not shutil.which("expect"):
        _log_event(level="ERROR", event="expect_missing", **ctx)
        raise LogContextError("expect is not installed on the WebUI host", code="expect_missing", status=503)
    script = _expect_script_path()
    if not script.exists():
        _log_event(level="ERROR", event="connector_missing", script=str(script), **ctx)
        raise LogContextError("log context expect script is missing", code="connector_missing", status=503)
    env = os.environ.copy()
    env.update(
        {
            "LOGCTX_HOST": req.source.host,
            "LOGCTX_PORT": str(req.source.port),
            "LOGCTX_USER": req.source.user,
            "LOGCTX_PASSWORD": password,
            "LOGCTX_REMOTE_COMMAND": _remote_command(req),
            "LOGCTX_TIMEOUT": str(req.source.timeout_seconds),
        }
    )
    _log_event(level="INFO", event="connector_run", **ctx,
               host=req.source.host, port=req.source.port, user=req.source.user,
               timeout=req.source.timeout_seconds,
               roots=list(req.source.roots))
    try:
        return subprocess.run(
            ["bash", str(script)],
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=req.source.timeout_seconds + 2,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        _log_event(level="ERROR", event="connector_timeout",
                   timeout=req.source.timeout_seconds, **ctx)
        raise LogContextError("获取日志上下文超时，请减少行数或稍后重试", code="timeout", status=504) from exc


def _extract_marked_output(stdout: bytes) -> tuple[str, bool]:
    text = stdout.decode("utf-8", errors="replace").replace("\r\n", "\n").replace("\r", "\n")
    # Use rfind to skip the expect spawn line (log_user 1 echoes the full
    # command which also contains both markers). The actual SSH output
    # markers always appear after the spawn line.
    begin_idx = text.rfind(BEGIN_MARKER)
    end_idx = text.rfind(END_MARKER)
    if begin_idx < 0 or end_idx < 0 or end_idx < begin_idx:
        _log_event(level="ERROR", event="marker_not_found",
                   begin_pos=begin_idx, end_pos=end_idx,
                   stdout_preview=stdout[:2048].decode("utf-8", errors="replace"))
        raise LogContextError("log context connector returned invalid output", code="invalid_connector_output", status=502)
    body = text[begin_idx + len(BEGIN_MARKER):end_idx]
    body = body.strip("\n")
    truncated = False
    cleaned: list[str] = []
    for line in body.splitlines():
        if line.strip() == TRUNCATED_MARKER:
            truncated = True
            continue
        cleaned.append(line)
    return "\n".join(cleaned), truncated


def _parse_lines(body: str, target_line: int) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = []
    for raw in body.splitlines():
        if not raw:
            continue
        no_raw, sep, text = raw.partition("\t")
        if not sep:
            continue
        try:
            no = int(no_raw)
        except ValueError:
            continue
        lines.append({"no": no, "text": text, "match": no == target_line})
    return lines


def _classify_connector_failure(returncode: int, stderr: bytes) -> LogContextError:
    err = stderr.decode("utf-8", errors="replace").lower()
    if returncode == 124 or "timed out" in err or "timeout" in err:
        return LogContextError("获取日志上下文超时，请减少行数或稍后重试", code="timeout", status=504)
    if "permission denied" in err or "authentication failed" in err:
        return LogContextError("登录服务器失败，请检查日志只读账号配置", code="login_failed", status=502)
    if "no such file" in err or "cannot open" in err or "not found" in err:
        return LogContextError("服务器上未找到该日志文件，可能已轮转", code="file_not_found", status=404)
    # awk exit code 2 = usage error → file missing or unreadable on remote
    if returncode == 2:
        return LogContextError("服务器上未找到该日志文件，可能已轮转或路径不正确", code="file_not_found", status=404)
    print(json.dumps({
        'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'level': 'ERROR',
        'event': 'connector_read_failed',
        'returncode': returncode,
        'stderr': stderr.decode("utf-8", errors="replace"),
    }), flush=True)
    return LogContextError("读取日志上下文失败", code="read_failed", status=502)


def fetch_log_context(req: LogContextRequest) -> dict[str, Any]:
    ctx = _log_context_req(req)
    password = req.source.password_value or (
        os.environ.get(req.source.password_env, "") if req.source.password_env else ""
    )
    if not password:
        _log_event(level="ERROR", event="password_missing", password_env=req.source.password_env, **ctx)
        raise LogContextError(
            "log context password environment variable is not set",
            code="password_env_missing",
            status=503,
        )
    result = _run_expect_script(req, password)
    body = ""
    truncated_by_connector = False
    try:
        body, truncated_by_connector = _extract_marked_output(result.stdout)
    except LogContextError:
        if result.returncode != 0:
            raise _classify_connector_failure(result.returncode, result.stderr)
        _log_event(level="ERROR", event="invalid_output_with_ok_returncode",
                   returncode=result.returncode,
                   stderr=result.stderr.decode("utf-8", errors="replace"),
                   stdout_preview=result.stdout[:2048].decode("utf-8", errors="replace"),
                   **ctx)
        raise
    if result.returncode != 0:
        _log_event(level="ERROR", event="connector_exit_nonzero",
                   returncode=result.returncode,
                   stderr=result.stderr.decode("utf-8", errors="replace"),
                   stdout_preview=result.stdout[:1024].decode("utf-8", errors="replace"),
                   **ctx)
        raise _classify_connector_failure(result.returncode, result.stderr)
    lines = _parse_lines(body, req.line)
    _log_event(level="INFO", event="fetch_ok", line_count=len(lines),
               truncated=bool(req.clipped or truncated_by_connector),
               body_preview=body[:2048] if not lines else "", **ctx)
    return {
        "ok": True,
        "source": req.source.source_id,
        "host_ip": req.host_ip,
        "account": req.account,
        "path": req.path,
        "line": req.line,
        "start_line": req.start_line,
        "end_line": req.end_line,
        "before": req.before,
        "after": req.after,
        "requested_before": req.requested_before,
        "requested_after": req.requested_after,
        "lines": lines,
        "truncated": bool(req.clipped or truncated_by_connector),
    }


def audit_log_context(req: LogContextRequest | None, *, outcome: str, client_ip: str, error_code: str = "") -> None:
    try:
        from api import audit

        audit.write(
            category="log_context",
            action="view_log_context",
            operation="view_log_context",
            outcome=outcome,
            source=req.source.source_id if req else "",
            path=req.path if req else "",
            line=req.line if req else "",
            before=req.before if req else "",
            after=req.after if req else "",
            host_ip=req.host_ip if req else "",
            account=req.account if req else "",
            client_ip=client_ip or "-",
            session_id=req.session_id if req and req.session_id else "-",
            error_code=error_code,
        )
    except Exception:
        pass
