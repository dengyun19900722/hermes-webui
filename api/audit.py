"""
Hermes WebUI -- Audit logging subsystem.

Architecture
============
- One .jsonl file per day under AUDIT_DIR/ (default: ~/.hermes/webui/audit-logs/).
- Each line is a self-contained JSON object (utf-8).
- File-level lock (threading.Lock + fcntl) prevents concurrent writes from
  racing across processes (Docker multi-worker, or future gunicorn).
- write() is fire-and-forget: a logging error never blocks the request path.
- search() and export_csv() scan in-process .jsonl files already on disk —
  no additional indexing.

Audit entry fields
==================
Every entry MUST contain at least these top-level keys::

    {
        "id":        "<uuid4>",           # globally unique entry ID
        "ts":        "<iso8601>",         # when the event occurred (UTC)
        "category":  "request"|"chat"|"login",   # event category
        "session_id":"<hex12 or ->",      # webui session id (or "->" for system)
        "operation": "<string>",          # human-readable operation name
    }

Category-specific required fields::

    request:
        method, path, status, duration_ms, client_ip, user_agent

    chat:
        session_id, question (first user message), answer (last assistant msg),
        tool_calls (list of tool names, may be empty)

    login:
        success, client_ip, user_agent, reason (on failure)

All other fields are optional.  Unknown fields are accepted (forward compat).
"""

import csv
import fcntl
import io
import json
import logging
import os
import re
import time
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from api.config import STATE_DIR, AUDIT_DIR as _CFG_AUDIT_DIR, AUDIT_IP_ANONYMIZE as _CFG_AUDIT_IP_ANONYMIZE, AUDIT_RETENTION_DAYS

logger = logging.getLogger(__name__)

# ── Config (imported directly from api.config — edit config.py to change) ──────
AUDIT_ENABLED = True              # ← 审计总开关（False=禁用，暂无config.py对应变量）
AUDIT_DIR = _CFG_AUDIT_DIR       # ← /data/audit-logs（见 config.py）
AUDIT_IP_ANONYMIZE = _CFG_AUDIT_IP_ANONYMIZE  # ← False（见 config.py）

# ── Async buffered write ───────────────────────────────────────────────────────

_BUFFER_SIZE = 32
_FLUSH_INTERVAL = 5.0  # seconds

_entry_buffer: list[dict] = []
_buffer_lock = threading.Lock()
_flush_thread: threading.Thread | None = None
_shutdown_event = threading.Event()


def _start_flush_thread() -> None:
    """Lazily start the background flush thread (idempotent)."""
    global _flush_thread
    if _flush_thread is not None:
        return

    def _run() -> None:
        while not _shutdown_event.wait(timeout=_FLUSH_INTERVAL):
            _flush_buffer()

    t = threading.Thread(target=_run, daemon=True, name="AuditFlush")
    t.start()
    _flush_thread = t


def _flush_buffer() -> None:
    """Write all buffered entries to disk, then clear the buffer."""
    global _entry_buffer
    if not _entry_buffer:
        return

    batch = _entry_buffer
    _entry_buffer = []

    if not batch:
        return

    try:
        _audit_d = _ensure_audit_dir()
        now_utc = datetime.now(timezone.utc)
        path = _audit_d / f"audit-{now_utc.strftime('%Y-%m-%d')}.jsonl"
        f = open(path, "a", encoding="utf-8", newline="")
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            for entry in batch:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            f.close()
    except Exception:
        logger.exception("[audit] flush failed (%d entries)", len(batch))


def write(entry: dict | None = None, /, **kwargs) -> None:
    """
    Buffer one audit entry for async write to today's .jsonl file.

    Supports two call styles:
      write({'category': 'http', 'action': 'GET /api/chat', ...})
      write(category='http', action='GET /api/chat', ...)

    Entries are accumulated in memory (up to _BUFFER_SIZE or _FLUSH_INTERVAL s)
    before being flushed to disk by a background thread, keeping write() latency
    near zero.  On shutdown the process calls flush() to drain remaining entries.

    Fire-and-forget: errors are logged but never raised, and never block the
    caller's request path.
    """
    if not AUDIT_ENABLED:
        return

    try:
        # Accept both dict and keyword-argument call styles
        if entry is None:
            entry = dict(kwargs)
        else:
            entry = dict(entry)  # shallow copy — caller may reuse the dict
            entry.update(kwargs)  # merge kwargs into entry (kwargs take precedence)

        entry.setdefault("id", __import__("uuid").uuid4().hex)
        if "ts" not in entry:
            entry["ts"] = datetime.now(timezone.utc).isoformat(timespec="seconds")

        if "client_ip" in entry:
            entry["client_ip"] = _anonymize_ip(entry["client_ip"])

        entry = _redact_entry(entry)

        with _buffer_lock:
            _entry_buffer.append(entry)
            if len(_entry_buffer) >= _BUFFER_SIZE:
                # Immediate flush triggered by buffer full
                _flush_buffer()

        _start_flush_thread()

    except Exception:
        logger.exception("[audit] failed to buffer entry %s", entry.get("id", "?"))


def flush() -> None:
    """Synchronously flush all buffered entries to disk.  Call on shutdown."""
    global _shutdown_event
    _shutdown_event.set()
    with _buffer_lock:
        _flush_buffer()


# ── Internal helpers ───────────────────────────────────────────────────────────

_audit_dir: Path | None = None


def _ensure_audit_dir() -> Path:
    global _audit_dir
    if _audit_dir is not None:
        return _audit_dir
    if AUDIT_DIR is None:
        raise RuntimeError("AUDIT_DIR is not configured")
    _audit_dir = AUDIT_DIR
    _audit_dir.mkdir(parents=True, exist_ok=True)
    return _audit_dir


def _audit_file_for_date(dt: datetime) -> Path:
    """Return the .jsonl path for a given UTC date."""
    return _ensure_audit_dir() / f"audit-{dt.strftime('%Y-%m-%d')}.jsonl"


def _open_audit_file(path: Path, mode: str):
    """Return (file, lock_type) for the given mode."""
    f = open(path, mode, encoding="utf-8", newline="")
    if mode.startswith("r"):
        return f, None
    lock_type = fcntl.LOCK_EX if "w" in mode or "a" in mode else fcntl.LOCK_SH
    fcntl.flock(f.fileno(), lock_type)
# ── Sensitive-field redaction ──────────────────────────────────────────────────

# Compiled once at import time.
# Group structure: (1) keyword | (2) separator | (3) value
# Replacement: keyword + separator + REDACTED (full match replaced with redaction)
_RE_SENSITIVE = re.compile(
    r"(api[_-]?key|secret|password|token|auth|bearer|credential)"
    r"(?![a-zA-Z0-9])"
    r"([:= \t]+['\"]?)([a-zA-Z0-9_\-+/=<>.@!]{1,})",
    re.IGNORECASE,
)
_RE_IPV4_SEG = re.compile(r"\.\d+$")   # last segment of an IPv4


def _redact(text: str) -> str:
    """Replace value of detected sensitive fields with '***REDACTED***'."""
    if not text:
        return text
    return _RE_SENSITIVE.sub(r"\1\2***REDACTED***", text)


def _anonymize_ip(ip: str) -> str:
    """Zero-out the last octet of an IPv4 address when AUDIT_IP_ANONYMIZE is set."""
    if not ip:
        return ip
    if AUDIT_IP_ANONYMIZE and _RE_IPV4_SEG.search(ip):
        return _RE_IPV4_SEG.sub(".0", ip)
    return ip


def _redact_entry(entry: dict) -> dict:
    """Shallow-copy entry and redact string fields that may contain secrets."""
    out = dict(entry)
    for k, v in out.items():
        if isinstance(v, str):
            out[k] = _redact(v)
        elif isinstance(v, dict):
            out[k] = {kk: _redact(str(vv)) if isinstance(vv, str) else vv for kk, vv in v.items()}
        elif isinstance(v, list):
            out[k] = [
                _redact(str(i)) if isinstance(i, str) else i
                for i in v
            ]
    return out


# ── Public interface ───────────────────────────────────────────────────────────

def search(
    category: Optional[str] = None,
    session_id: Optional[str] = None,
    client_ip: Optional[str] = None,
    keyword: Optional[str] = None,
    since: Optional[str] = None,       # ISO-8601 or 'YYYY-MM-DD'
    until: Optional[str] = None,        # ISO-8601 or 'YYYY-MM-DD'
    limit: int = 100,
    offset: int = 0,
) -> list[dict]:
    """
    Scan audit logs and return matching entries in reverse-chronological order.

    Parameters
    ----------
    category : str, optional
        Filter by entry category (e.g. ``"chat"``, ``"request"``).
    session_id : str, optional
        Exact session ID match.
    client_ip : str, optional
        Substring match on client IP (anonymized if AUDIT_IP_ANONYMIZE is on).
    keyword : str, optional
        Case-insensitive substring search across all string values.
    since, until : str, optional
        Inclusive lower/upper bound on entry ``ts``.  Accepts ISO-8601 or
        bare date strings (interpreted as that day's midnight in UTC).
    limit : int, default 100
        Maximum number of entries returned.
    offset : int, default 0
        Number of leading matches to skip (for pagination).

    Returns
    -------
    list[dict]
        Matching entries, newest-first, up to ``limit`` entries.
    """
    if not AUDIT_ENABLED:
        return []

    # Parse dates — bare date strings are inclusive in both directions:
    # since="2026-05-02" → start of that day; until="2026-05-02" → end of that day.
    _RE_BARE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    def parse_date(s, is_until=False):
        if not s:
            return None
        if _RE_BARE_DATE.match(s):
            base = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return base + timedelta(days=1) - timedelta(microseconds=1) if is_until else base
        try:
            dt_val = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt_val.tzinfo is None:
                dt_val = dt_val.replace(tzinfo=timezone.utc)
            return dt_val
        except ValueError:
            base = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return base + timedelta(days=1) - timedelta(microseconds=1) if is_until else base

    since_dt = parse_date(since, is_until=False)
    until_dt = parse_date(until, is_until=True)

    keyword_lower = keyword.lower() if keyword else None

    def matches(entry: dict) -> bool:
        if category and entry.get("category") != category:
            return False
        if session_id and entry.get("session_id") != session_id:
            return False
        if client_ip and client_ip not in (entry.get("client_ip") or ""):
            return False
        ts_str = entry.get("ts", "")
        if since_dt or until_dt:
            try:
                ts_dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                if ts_dt.tzinfo is None:
                    ts_dt = ts_dt.replace(tzinfo=timezone.utc)
            except ValueError:
                return False
            if since_dt and ts_dt < since_dt:
                return False
            if until_dt and ts_dt > until_dt:
                return False
        if keyword_lower:
            text = json.dumps(entry, ensure_ascii=False).lower()
            if keyword_lower not in text:
                return False
        return True

    # Collect matching .jsonl files newest-first
    try:
        audit_dir = _ensure_audit_dir()
        files = sorted(audit_dir.glob("audit-*.jsonl"), reverse=True)
    except Exception:
        return []

    results: list[tuple[str, dict]] = []  # (ts, entry)
    for fpath in files:
        try:
            f, _lock = _open_audit_file(fpath, "r")
        except Exception:
            continue
        try:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if matches(entry):
                    results.append((entry.get("ts", ""), entry))
        finally:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                f.close()
            except Exception:
                pass

    results.sort(key=lambda x: x[0], reverse=True)
    return [entry for _ts, entry in results[offset : offset + limit]]


def count(
    category: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
) -> int:
    """Return the total number of matching entries without pagination."""
    if not AUDIT_ENABLED:
        return 0

    _RE_BARE_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

    def parse_date(s, is_until=False):
        if not s:
            return None
        if _RE_BARE_DATE.match(s):
            base = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return base + timedelta(days=1) - timedelta(microseconds=1) if is_until else base
        try:
            dt_val = datetime.fromisoformat(s.replace("Z", "+00:00"))
            if dt_val.tzinfo is None:
                dt_val = dt_val.replace(tzinfo=timezone.utc)
            return dt_val
        except ValueError:
            base = datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            return base + timedelta(days=1) - timedelta(microseconds=1) if is_until else base

    since_dt = parse_date(since, is_until=False)
    until_dt = parse_date(until, is_until=True)

    try:
        audit_dir = _ensure_audit_dir()
        files = sorted(audit_dir.glob("audit-*.jsonl"), reverse=True)
    except Exception:
        return 0

    total = 0
    for fpath in files:
        try:
            f, _lock = _open_audit_file(fpath, "r")
        except Exception:
            continue
        try:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if category and entry.get("category") != category:
                    continue
                ts_str = entry.get("ts", "")
                if since_dt or until_dt:
                    try:
                        ts_dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                        if ts_dt.tzinfo is None:
                            ts_dt = ts_dt.replace(tzinfo=timezone.utc)
                    except ValueError:
                        continue
                    if since_dt and ts_dt < since_dt:
                        continue
                    if until_dt and ts_dt > until_dt:
                        continue
                total += 1
        finally:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                f.close()
            except Exception:
                pass
    return total


def get(id: str) -> dict | None:
    """Fetch a single audit entry by its globally unique id, or None if not found."""
    if not AUDIT_ENABLED:
        return None
    try:
        audit_dir = _ensure_audit_dir()
        files = sorted(audit_dir.glob("audit-*.jsonl"), reverse=True)
    except Exception:
        return None
    for fpath in files:
        try:
            f, _lock = _open_audit_file(fpath, "r")
        except Exception:
            continue
        try:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("id") == id:
                    return entry
        finally:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                f.close()
            except Exception:
                pass
    return None



def export_csv(
    category: Optional[str] = None,
    session_id: Optional[str] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    keyword: Optional[str] = None,
) -> io.StringIO:
    """
    Export matching audit entries as a CSV (UTF-8 BOM for Excel compat).

    Returns a StringIO ready to be served as ``text/csv``.
    """
    entries = search(
        category=category,
        session_id=session_id,
        keyword=keyword,
        since=since,
        until=until,
        limit=1_000_000,   # no offset pagination for exports
    )

    fieldnames = [
        "id", "ts", "category", "session_id", "action", "outcome",
        "client_ip", "question", "answer",
        "method", "path", "status", "duration_ms",
        "model", "workspace", "usage", "tool_calls",
        "login_success", "login_reason",
    ]

    buf = io.StringIO()
    # UTF-8 BOM — makes Excel open the file with correct encoding
    buf.write("\ufeff")
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for entry in entries:
        row = dict(entry)
        # Flatten metadata sub-fields for CSV columns
        if isinstance(row.get("metadata"), dict):
            for _k, _v in row["metadata"].items():
                if _k not in row:
                    row[_k] = _v
        # Serialize list fields as semicolon-joined strings for CSV readability
        if isinstance(row.get("tool_calls"), list):
            row["tool_calls"] = "; ".join(str(t) for t in row["tool_calls"])
        if isinstance(row.get("usage"), dict):
            row["usage"] = json.dumps(row["usage"])
        writer.writerow(row)

    buf.seek(0)
    return buf


def _audit_dir_size_bytes() -> int:
    """Return total size of all .jsonl files (approximate, for health checks)."""
    try:
        audit_dir = _ensure_audit_dir()
        return sum(f.stat().st_size for f in audit_dir.glob("audit-*.jsonl"))
    except Exception:
        return 0


# ── Log rotation & cleanup ──────────────────────────────────────────────────────

def rotate_old_logs(age_days: int = 7) -> dict[str, int]:
    """
    Gzip-compress .jsonl files older than ``age_days`` days.

    Skips files that are already compressed (.jsonl.gz) or currently open.
    Returns ``{"rotated": N, "skipped": M, "errors": K}`` for display purposes.
    """
    import gzip

    try:
        audit_dir = _ensure_audit_dir()
    except Exception as exc:
        return {"rotated": 0, "skipped": 0, "errors": 1, "error_detail": str(exc)}

    cutoff = datetime.now(timezone.utc) - timedelta(days=age_days)
    rotated = skipped = errors = 0

    for fpath in audit_dir.glob("audit-*.jsonl"):
        try:
            mtime = datetime.fromtimestamp(fpath.stat().st_mtime, tz=timezone.utc)
        except Exception:
            skipped += 1
            continue
        if mtime >= cutoff:
            skipped += 1
            continue
        gz_path = Path(str(fpath) + ".gz")
        if gz_path.exists():
            skipped += 1
            continue
        try:
            with open(fpath, "rb") as fin, gzip.open(gz_path, "wb") as fout:
                fout.writelines(fin)
            # Verify integrity
            with gzip.open(gz_path, "rb") as verify:
                verify.read()
            fpath.unlink()
            rotated += 1
        except Exception:
            # Corrupt / still-writing file — leave as-is
            errors += 1
            if gz_path.exists():
                gz_path.unlink()
            skipped += 1

    return {"rotated": rotated, "skipped": skipped, "errors": errors}


def cleanup(days: int | None = None) -> dict[str, int]:
    """
    Delete audit files older than ``days``.

    If ``days`` is None, uses ``AUDIT_RETENTION_DAYS`` from config (0=never delete).
    Only removes .jsonl.gz compressed files to avoid deleting live data.
    Returns ``{"deleted": N, "skipped": M, "errors": K}``.
    """
    if days is None:
        days = AUDIT_RETENTION_DAYS
    if days <= 0:
        return {"deleted": 0, "skipped": 0, "errors": 0, "detail": "retention disabled (days=0)"}

    try:
        audit_dir = _ensure_audit_dir()
    except Exception as exc:
        return {"deleted": 0, "skipped": 0, "errors": 1, "error_detail": str(exc)}

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    deleted = skipped = errors = 0

    for gz_path in audit_dir.glob("audit-*.jsonl.gz"):
        try:
            mtime = datetime.fromtimestamp(gz_path.stat().st_mtime, tz=timezone.utc)
        except Exception:
            skipped += 1
            continue
        if mtime >= cutoff:
            skipped += 1
            continue
        try:
            gz_path.unlink()
            deleted += 1
        except Exception:
            errors += 1
            skipped += 1

    return {"deleted": deleted, "skipped": skipped, "errors": errors}
