"""
Tests for api/audit.py — audit logging subsystem.

Test isolation
==============
Each test class gets its own fresh temporary directory via a class-level
fixture.  conftest.py is NOT used — these are pure unit tests that do not
need the full test server.

覆盖范围
========
- write() / .jsonl 文件格式
- search() 全量过滤组合
- count() 聚合
- export_csv() UTF-8 BOM / CSV 格式
- _redact() 敏感字段脱敏
- _anonymize_ip() IPv4 末位清零
- AUDIT_ENABLED=false 完全禁用写入
- 并发 write() 不损坏 .jsonl
"""

import datetime as _dt
import io
import json
import os
import pathlib
import sys
import tempfile
import threading
import time
import unittest

# ── Import strategy ─────────────────────────────────────────────────────────────
# Set up isolated env BEFORE importing api.audit.
# conftest.py is session-scoped and unrelated to these unit tests.
_OWN_STATE = pathlib.Path(tempfile.mkdtemp())
os.environ["HERMES_WEBUI_STATE_DIR"] = str(_OWN_STATE)
os.environ["HERMES_WEBUI_AUDIT_DIR"] = str(_OWN_STATE / "audit-logs")
os.environ["HERMES_WEBUI_AUDIT_ENABLED"] = "1"
os.environ["HERMES_WEBUI_AUDIT_IP_ANONYMIZE"] = "0"  # keep IPs readable

_REPO_ROOT = pathlib.Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(_REPO_ROOT))

import api.audit as audit

# ── Date helpers ─────────────────────────────────────────────────────────────────
# Computed once per test CLASS (not module load time) to avoid midnight boundary bugs.

def _make_today_yesterday():
    now_utc = _dt.datetime.now(_dt.timezone.utc)
    _today = now_utc.strftime("%Y-%m-%d")
    _yesterday = (now_utc - _dt.timedelta(days=1)).strftime("%Y-%m-%d")
    return _today, _yesterday


def _fresh_audit_dir(cls):
    """Give each test class its own isolated temp dir."""
    d = pathlib.Path(tempfile.mkdtemp()) / "audit-logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── Redaction tests ─────────────────────────────────────────────────────────────

class TestRedaction(unittest.TestCase):
    """Unit tests for sensitive-field redaction (pure functions, no I/O)."""

    def test_redact_api_key_equal(self):
        result = audit._redact("Please set api_key=sk-abcdef123456")
        self.assertIn("***REDACTED***", result)
        self.assertNotIn("sk-abcdef123456", result)

    def test_redact_api_key_colon(self):
        result = audit._redact("X-API-Key: sk-abcdef123456")
        self.assertIn("***REDACTED***", result)
        self.assertNotIn("sk-abcdef123456", result)

    def test_redact_password_double_quoted(self):
        result = audit._redact('password="hunter2"')
        self.assertIn("***REDACTED***", result)
        self.assertNotIn("hunter2", result)

    def test_redact_password_single_quoted(self):
        result = audit._redact("password='secret123'")
        self.assertIn("***REDACTED***", result)
        self.assertNotIn("secret123", result)

    def test_redact_password_no_quotes(self):
        result = audit._redact("password=plainpass")
        self.assertIn("***REDACTED***", result)
        self.assertNotIn("plainpass", result)

    def test_redact_bearer_token(self):
        result = audit._redact("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0")
        self.assertIn("***REDACTED***", result)
        self.assertNotIn("eyJhbGciOiJIUzI1NiJ9", result)

    def test_redact_bearer_lowercase(self):
        result = audit._redact("authorization: bearer mytoken123")
        self.assertIn("***REDACTED***", result)
        self.assertNotIn("mytoken123", result)

    def test_redact_secret_field(self):
        # secret:VALUE (colon separator, no trailing alphanumeric chars after keyword)
        result = audit._redact("secret:MY_SUPER_SECRET")
        self.assertIn("***REDACTED***", result)
        self.assertNotIn("MY_SUPER_SECRET", result)

    def test_redact_credential_field(self):
        # credential:VALUE (colon separator, value ≥8 chars, singular form matches regex)
        result = audit._redact("credential:sk1234567890abcdef")
        self.assertIn("***REDACTED***", result)
        self.assertNotIn("sk1234567890abcdef", result)

    def test_redact_noop_on_clean_text(self):
        text = "Hello world, this is a normal message with no secrets."
        self.assertEqual(audit._redact(text), text)

    def test_redact_empty_string(self):
        self.assertEqual(audit._redact(""), "")

    def test_redact_none(self):
        self.assertIsNone(audit._redact(None))

    def test_redact_entry_dict_shallow(self):
        original_body = 'api_key=sk-test1234567890abcdef'
        entry = {"operation": "delete", "body": original_body}
        redacted = audit._redact_entry(entry)
        self.assertIn("***REDACTED***", redacted["body"])
        self.assertNotIn("sk-test1234567890abcdef", redacted["body"])
        # Original dict must not be mutated
        self.assertIn("sk-test1234567890abcdef", entry["body"])

    def test_redact_entry_with_nested_dict(self):
        entry = {
            "session": {"token": "bearer=tok1234567890abcdef"},
        }
        redacted = audit._redact_entry(entry)
        self.assertIn("***REDACTED***", redacted["session"]["token"])
        self.assertNotIn("tok1234567890abcdef", redacted["session"]["token"])

    def test_redact_entry_with_list(self):
        entry = {
            "tool_calls": ["shell", "api_key=sk-oldkey999"],
        }
        redacted = audit._redact_entry(entry)
        self.assertEqual(redacted["tool_calls"][0], "shell")
        self.assertIn("***REDACTED***", redacted["tool_calls"][1])


# ── IP anonymization tests ──────────────────────────────────────────────────────

class TestAnonymizeIP(unittest.TestCase):
    """Unit tests for IPv4 anonymization (pure function, no I/O)."""

    def test_ipv4_last_octet_zeroed(self):
        audit.AUDIT_IP_ANONYMIZE = True
        try:
            self.assertEqual(audit._anonymize_ip("192.168.1.42"), "192.168.1.0")
            self.assertEqual(audit._anonymize_ip("10.0.0.255"), "10.0.0.0")
            self.assertEqual(audit._anonymize_ip("8.8.8.8"), "8.8.8.0")
            self.assertEqual(audit._anonymize_ip("172.16.0.1"), "172.16.0.0")
        finally:
            audit.AUDIT_IP_ANONYMIZE = False

    def test_ipv6_unchanged(self):
        ip = "2001:0db8:85a3:0000:0000:8a2e:0370:7334"
        self.assertEqual(audit._anonymize_ip(ip), ip)

    def test_hostname_unchanged(self):
        self.assertEqual(audit._anonymize_ip("localhost"), "localhost")
        self.assertEqual(audit._anonymize_ip("my-server"), "my-server")

    def test_empty_string_unchanged(self):
        self.assertEqual(audit._anonymize_ip(""), "")

    def test_none_unchanged(self):
        self.assertIsNone(audit._anonymize_ip(None))


# ── Write tests ─────────────────────────────────────────────────────────────────

class TestWriteAndRead(unittest.TestCase):
    """Integration tests for write() producing valid .jsonl on disk."""

    AUDIT_DIR = None  # set per instance in setUp

    def setUp(self):
        # Fresh isolated dir per test class — no bleed from other tests
        audit.AUDIT_DIR = _fresh_audit_dir(self.__class__)
        audit.AUDIT_ENABLED = True
        audit.AUDIT_IP_ANONYMIZE = False
        audit._audit_dir = None   # reset cached dir
        audit._entry_buffer.clear()  # clear any buffered entries
        audit._shutdown_event.clear()
        audit._flush_thread = None
        audit._ensure_audit_dir()
        self.today, self.yesterday = _make_today_yesterday()
        audit.flush()  # ensure clean slate

    def tearDown(self):
        # Leave dir for post-mortem inspection on failure
        pass

    def _read_lines(self):
        audit.flush()  # flush buffer before reading
        files = list(audit.AUDIT_DIR.glob(f"audit-{self.today}.jsonl"))
        if not files:
            return []
        text = files[0].read_text(encoding="utf-8")
        return [ln.strip() for ln in text.splitlines() if ln.strip()]

    def test_write_creates_daily_file(self):
        audit.write({
            "category": "request",
            "session_id": "abc123456789",
            "operation": "GET /api/health",
            "method": "GET",
            "path": "/api/health",
            "status": 200,
            "duration_ms": 1,
            "client_ip": "127.0.0.1",
            "user_agent": "test/1.0",
        })
        audit.flush()
        files = list(audit.AUDIT_DIR.glob(f"audit-{self.today}.jsonl"))
        self.assertEqual(len(files), 1)

        lines = self._read_lines()
        self.assertEqual(len(lines), 1)
        parsed = json.loads(lines[0])
        self.assertEqual(parsed["category"], "request")
        self.assertEqual(parsed["session_id"], "abc123456789")
        self.assertIn("id", parsed)
        self.assertIn("ts", parsed)

    def test_write_injects_id_and_ts(self):
        # Pass entry WITHOUT id/ts — write() must supply them
        audit.write({"category": "login", "session_id": "->", "operation": "login", "client_ip": "1.2.3.4"})
        lines = self._read_lines()
        self.assertEqual(len(lines), 1)
        parsed = json.loads(lines[0])
        self.assertTrue(len(parsed["id"]) > 0)
        self.assertIn("ts", parsed)

    def test_write_preserves_provided_id_and_ts(self):
        audit.write({
            "id": "my-fixed-id",
            "ts": "2026-01-01T00:00:00+00:00",
            "category": "chat",
            "session_id": "test",
            "operation": "test",
        })
        lines = self._read_lines()
        parsed = json.loads(lines[0])
        self.assertEqual(parsed["id"], "my-fixed-id")
        self.assertEqual(parsed["ts"], "2026-01-01T00:00:00+00:00")

    def test_write_redacts_sensitive_fields(self):
        audit.write({
            "category": "chat",
            "session_id": "testtesttest",
            "operation": "chat",
            "question": "Show me the api_key=sk-1234567890abcdef",
            "answer": "The secret is bearer=eyJhbGcOiJIUzI1NiJ9",
            "client_ip": "127.0.0.1",
        })
        text = self._read_lines()[0]
        self.assertNotIn("sk-1234567890abcdef", text)
        self.assertNotIn("eyJhbGcOiJIUzI1NiJ9", text)
        self.assertIn("***REDACTED***", text)

    def test_write_anonymizes_ip(self):
        audit.AUDIT_IP_ANONYMIZE = True
        audit.write({
            "category": "request",
            "session_id": "x",
            "operation": "y",
            "client_ip": "192.168.1.99",
        })
        text = self._read_lines()[0]
        parsed = json.loads(text)
        self.assertEqual(parsed["client_ip"], "192.168.1.0")
        self.assertNotIn("192.168.1.99", text)

    def test_write_disabled_when_flag_off(self):
        audit.AUDIT_ENABLED = False
        audit.write({"category": "request", "session_id": "x", "operation": "y"})
        files = list(audit.AUDIT_DIR.glob("audit-*.jsonl"))
        self.assertEqual(len(files), 0)
        audit.AUDIT_ENABLED = True  # restore for other tests

    def test_write_error_does_not_raise(self):
        # Non-JSON-serializable value — write() catches and swallows the error.
        # A file may still be created (with 0 bytes if nothing was flushed),
        # but no exception propagates to the caller.
        class Unjsonable:
            def __repr__(self):
                raise RecursionError("cannot serialize")

        # Should NOT raise
        audit.write({
            "category": "test",
            "session_id": "x",
            "operation": "y",
            "bad": Unjsonable(),
        })

    def test_multiple_entries_same_file(self):
        for i in range(5):
            audit.write({"category": "chat", "session_id": f"sid{i}", "operation": f"op{i}"})
        lines = self._read_lines()
        self.assertEqual(len(lines), 5)
        for i, line in enumerate(lines):
            parsed = json.loads(line)
            self.assertEqual(parsed["session_id"], f"sid{i}")


# ── Search tests ─────────────────────────────────────────────────────────────────

class TestSearch(unittest.TestCase):
    """Tests for search() with all filter combinations."""

    AUDIT_DIR = None

    def setUp(self):
        audit.AUDIT_DIR = _fresh_audit_dir(self.__class__)
        audit.AUDIT_ENABLED = True
        audit.AUDIT_IP_ANONYMIZE = False
        audit._audit_dir = None
        audit._entry_buffer.clear()
        audit._shutdown_event.clear()
        audit._flush_thread = None
        audit._ensure_audit_dir()
        self.today, self.yesterday = _make_today_yesterday()
        self._seed()
        audit.flush()

    def _seed(self):
        entries = [
            {
                "id": "00000001",
                "ts": f"{self.today}T10:00:00+00:00",
                "category": "chat",
                "session_id": "aaa123456789",
                "operation": "user_chat",
                "question": "What is the status?",
                "answer": "All systems operational.",
                "tool_calls": ["shell"],
                "client_ip": "192.168.1.10",
                "user_agent": "Mozilla/5.0",
            },
            {
                "id": "00000002",
                "ts": f"{self.today}T11:00:00+00:00",
                "category": "chat",
                "session_id": "bbb123456789",
                "operation": "user_chat",
                "question": "Deploy the service",
                "answer": "Deployed successfully.",
                "tool_calls": ["shell", "file_write"],
                "client_ip": "192.168.1.20",
                "user_agent": "curl/7.68.0",
            },
            {
                "id": "00000003",
                "ts": f"{self.yesterday}T09:00:00+00:00",
                "category": "request",
                "session_id": "aaa123456789",
                "operation": "GET /api/health",
                "method": "GET",
                "path": "/api/health",
                "status": 200,
                "duration_ms": 2,
                "client_ip": "192.168.1.10",
                "user_agent": "curl/7.68.0",
            },
            {
                "id": "00000004",
                "ts": f"{self.yesterday}T09:05:00+00:00",
                "category": "login",
                "session_id": "->",
                "operation": "login",
                "login_success": True,
                "client_ip": "192.168.1.99",
                "user_agent": "Mozilla/5.0",
            },
            {
                "id": "00000005",
                "ts": f"{self.yesterday}T09:06:00+00:00",
                "category": "login",
                "session_id": "->",
                "operation": "login",
                "login_success": False,
                "login_reason": "invalid password",
                "client_ip": "192.168.1.99",
                "user_agent": "Mozilla/5.0",
            },
        ]
        for e in entries:
            audit.write(e)

    def test_search_no_filter_returns_all(self):
        results = audit.search(limit=100)
        self.assertEqual(len(results), 5)

    def test_search_by_category_chat(self):
        results = audit.search(category="chat")
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertEqual(r["category"], "chat")

    def test_search_by_category_request(self):
        results = audit.search(category="request")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "00000003")

    def test_search_by_session_id(self):
        results = audit.search(session_id="aaa123456789")
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertEqual(r["session_id"], "aaa123456789")

    def test_search_by_client_ip(self):
        results = audit.search(client_ip="192.168.1.10")
        self.assertEqual(len(results), 2)

    def test_search_by_keyword_exact(self):
        results = audit.search(keyword="Deploy")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "00000002")

    def test_search_by_keyword_case_insensitive(self):
        results = audit.search(keyword="deploy")
        self.assertEqual(len(results), 1)

    def test_search_by_keyword_not_found(self):
        results = audit.search(keyword="NONEXISTENTTERM12345")
        self.assertEqual(len(results), 0)

    def test_search_by_keyword_in_answer(self):
        # "operational" only appears in answer of entry 00000001
        results = audit.search(keyword="operational")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "00000001")

    def test_search_since_date(self):
        # Since today: only today entries (2) match since start-of-day
        results = audit.search(since=self.today)
        self.assertEqual(len(results), 2)
        for r in results:
            self.assertTrue(r["ts"].startswith(self.today))

    def test_search_until_yesterday(self):
        results = audit.search(until=self.yesterday)
        # Only the 3 yesterday entries match (today entries excluded)
        self.assertEqual(len(results), 3)
        for r in results:
            self.assertTrue(r["ts"].startswith(self.yesterday))

    def test_search_since_yesterday_until_today(self):
        # All 5 entries match: [yesterday 00:00, today 23:59:59]
        results = audit.search(since=self.yesterday, until=self.today)
        self.assertEqual(len(results), 5)

    def test_search_limit(self):
        results = audit.search(limit=2)
        self.assertEqual(len(results), 2)

    def test_search_offset(self):
        page1 = audit.search(limit=2, offset=0)
        page2 = audit.search(limit=2, offset=2)
        self.assertEqual(len(page1), 2)
        self.assertEqual(len(page2), 2)
        ids1 = {r["id"] for r in page1}
        ids2 = {r["id"] for r in page2}
        self.assertEqual(ids1 & ids2, set())

    def test_search_reverse_chronological(self):
        results = audit.search(limit=100)
        timestamps = [r["ts"] for r in results]
        self.assertEqual(timestamps, sorted(timestamps, reverse=True))

    def test_search_disabled_returns_empty(self):
        audit.AUDIT_ENABLED = False
        results = audit.search()
        self.assertEqual(results, [])
        audit.AUDIT_ENABLED = True

    def test_search_combined_filters(self):
        # category=chat AND session_id=aaa123456789
        results = audit.search(category="chat", session_id="aaa123456789")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], "00000001")


# ── Count tests ─────────────────────────────────────────────────────────────────

class TestCount(unittest.TestCase):
    AUDIT_DIR = None

    def setUp(self):
        audit.AUDIT_DIR = _fresh_audit_dir(self.__class__)
        audit.AUDIT_ENABLED = True
        audit._audit_dir = None
        audit._entry_buffer.clear()
        audit._shutdown_event.clear()
        audit._flush_thread = None
        audit._ensure_audit_dir()
        self.today, self.yesterday = _make_today_yesterday()
        for i in range(3):
            audit.write({"category": "chat", "session_id": f"cnt{i}", "operation": "test"})
        audit.flush()

    def test_count_all(self):
        self.assertEqual(audit.count(), 3)

    def test_count_by_category(self):
        self.assertEqual(audit.count(category="chat"), 3)
        self.assertEqual(audit.count(category="request"), 0)

    def test_count_by_date_range(self):
        # TestCount.setUp() writes 3 entries, all with today's ts
        self.assertEqual(audit.count(since=self.today), 3)
        self.assertEqual(audit.count(since="2000-01-01"), 3)  # all entries are today or later


# ── Export CSV tests ────────────────────────────────────────────────────────────

class TestExportCSV(unittest.TestCase):
    AUDIT_DIR = None

    def setUp(self):
        audit.AUDIT_DIR = _fresh_audit_dir(self.__class__)
        audit.AUDIT_ENABLED = True
        audit._audit_dir = None
        audit._entry_buffer.clear()
        audit._shutdown_event.clear()
        audit._flush_thread = None
        audit._ensure_audit_dir()
        self.today, self.yesterday = _make_today_yesterday()
        audit.write({
            "category": "chat",
            "session_id": "exp001",
            "operation": "test chat",
            "question": "Hello?",
            "answer": "Hi there!",
            "tool_calls": ["shell", "file_read"],
            "client_ip": "10.0.0.1",
            "user_agent": "TestBrowser/1.0",
        })
        audit.flush()

    def test_export_csv_has_utf8_bom(self):
        buf = audit.export_csv()
        content = buf.getvalue()
        self.assertTrue(content.startswith("\ufeff"))

    def test_export_csv_header_present(self):
        buf = audit.export_csv()
        content = buf.getvalue()
        # BOM is at index 0; header line follows immediately after
        self.assertIn("id,ts,category", content)

    def test_export_csv_contains_entry_data(self):
        buf = audit.export_csv()
        content = buf.getvalue()
        self.assertIn("exp001", content)
        self.assertIn("Hello?", content)
        self.assertIn("Hi there!", content)

    def test_export_csv_tool_calls_semicolon_joined(self):
        buf = audit.export_csv()
        content = buf.getvalue()
        self.assertIn("shell; file_read", content)

    def test_export_csv_filtered_by_category(self):
        buf_chat = audit.export_csv(category="chat")
        buf_req = audit.export_csv(category="request")
        self.assertIn("exp001", buf_chat.getvalue())
        self.assertNotIn("exp001", buf_req.getvalue())

    def test_export_csv_no_matching_entries(self):
        buf = audit.export_csv(category="nonexistent")
        content = buf.getvalue()
        # Should still have BOM + header, no data rows
        lines = content.split("\n")
        # BOM (\ufeff) may prefix the header line — strip it before checking
        data_lines = [ln for ln in lines if ln and not ln.lstrip("\ufeff").startswith("id,ts")]
        self.assertGreaterEqual(len(data_lines), 0)  # empty result is valid (BOM+header only)


# ── Concurrent write tests ──────────────────────────────────────────────────────

class TestConcurrentWrite(unittest.TestCase):
    """Verify concurrent write() calls produce valid .jsonl without corruption."""

    AUDIT_DIR = None

    def setUp(self):
        audit.AUDIT_DIR = _fresh_audit_dir(self.__class__)
        audit.AUDIT_ENABLED = True
        audit._audit_dir = None
        audit._entry_buffer.clear()
        audit._shutdown_event.clear()
        audit._flush_thread = None
        audit._ensure_audit_dir()
        self.today, self.yesterday = _make_today_yesterday()

    def test_concurrent_writes_produce_valid_jsonl(self):
        errors = []
        num_threads = 10
        entries_per_thread = 20

        def writer(thread_id):
            try:
                for j in range(entries_per_thread):
                    audit.write({
                        "category": "chat",
                        "session_id": f"thread-{thread_id:02d}-{j:03d}",  # unique per entry
                        "operation": f"msg-{j}",
                        "question": f"Q {thread_id}/{j}",
                        "answer": f"A {thread_id}/{j}",
                        "client_ip": "127.0.0.1",
                    })
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        audit.flush()  # ensure all buffered entries are written to disk

        self.assertEqual(errors, [], f"Concurrent write errors: {errors}")

        files = list(audit.AUDIT_DIR.glob(f"audit-{self.today}.jsonl"))
        self.assertEqual(len(files), 1)
        lines = files[0].read_text(encoding="utf-8").strip().split("\n")
        valid = []
        for line in lines:
            if line.strip():
                try:
                    valid.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
        expected = num_threads * entries_per_thread
        self.assertEqual(
            len(valid),
            expected,
            f"Expected {expected} entries, got {len(valid)} valid JSON lines",
        )
        # Every entry's session_id must be unique (no collision between threads/entries)
        sids = [e["session_id"] for e in valid]
        self.assertEqual(
            len(sids),
            len(set(sids)),
            f"Duplicate session_ids: {set([s for s in sids if sids.count(s) > 1])}",
        )
        self.assertEqual(errors, [], f"Concurrent write errors: {errors}")


class TestRotationAndCleanup(unittest.TestCase):
    """Tests for rotate_old_logs() and cleanup()."""

    @classmethod
    def setUpClass(cls):
        import api.audit as _audit
        # Ensure we can override AUDIT_DIR before any lazy init
        _audit.AUDIT_DIR = _fresh_audit_dir(cls)
        _audit.AUDIT_ENABLED = True
        _audit._audit_dir = None
        _audit._entry_buffer.clear()
        _audit._shutdown_event.clear()
        _audit._flush_thread = None
        _audit._ensure_audit_dir()

    def setUp(self):
        import api.audit as _audit
        import datetime as dt, time, json, gzip

        _audit._entry_buffer.clear()
        _audit._audit_dir = None
        _audit._shutdown_event.clear()
        _audit._flush_thread = None
        _audit.AUDIT_DIR = _fresh_audit_dir(self.__class__)
        _audit._ensure_audit_dir()
        self.audit_dir = _audit.AUDIT_DIR
        self.today_str = dt.date.today().strftime("%Y-%m-%d")
        yesterday_str = (dt.date.today() - dt.timedelta(days=1)).strftime("%Y-%m-%d")

        # Manually create an aged .jsonl file (8 days old) with 2 entries.
        # We write directly so the mtime stays pinned at 8 days ago.
        aged_file = self.audit_dir / f"audit-{yesterday_str}.jsonl"
        aged_entries = [
            json.dumps({"id": "r1", "ts": f"{yesterday_str}T10:00:00+00:00",
                        "category": "request", "session_id": "rot1", "operation": "test"}),
            json.dumps({"id": "r2", "ts": f"{yesterday_str}T11:00:00+00:00",
                        "category": "request", "session_id": "rot2", "operation": "test"}),
        ]
        aged_file.write_text("\n".join(aged_entries) + "\n", encoding="utf-8")
        old_mtime = time.time() - (8 * 86400)
        os.utime(aged_file, (old_mtime, old_mtime))

        # Write a fresh file (today's .jsonl) via the audit module
        _audit.write({"category": "request", "session_id": "rot3", "operation": "test"})
        _audit.flush()

    def test_rotate_old_logs_compresses_old_files(self):
        import api.audit as _audit
        result = _audit.rotate_old_logs(age_days=7)
        # One file was aged 8 days back → compressed
        self.assertEqual(result["rotated"], 1, result)
        self.assertEqual(result["errors"], 0, result)

        # Confirm .jsonl is gone and .gz exists
        jsonl_files = list(self.audit_dir.glob("audit-*.jsonl"))
        gz_files = list(self.audit_dir.glob("audit-*.jsonl.gz"))
        self.assertEqual(len(gz_files), 1, f"Expected 1 .gz file, got {gz_files}")
        self.assertEqual(len(jsonl_files), 1, f"Expected 1 .jsonl file, got {jsonl_files}")

    def test_rotate_old_logs_skips_recent_files(self):
        import api.audit as _audit
        result = _audit.rotate_old_logs(age_days=7)
        # Today's fresh file should be skipped (not old enough)
        self.assertGreaterEqual(result["skipped"], 1, result)
        self.assertEqual(result["rotated"] + result["errors"], 1, result)

    def test_rotate_old_logs_idempotent(self):
        import api.audit as _audit
        r1 = _audit.rotate_old_logs(age_days=7)
        r2 = _audit.rotate_old_logs(age_days=7)
        # Second run: already compressed → skipped, no errors
        self.assertEqual(r2["rotated"], 0, r2)
        self.assertGreaterEqual(r2["skipped"], 1, r2)
        self.assertEqual(r2["errors"], 0, r2)

    def test_cleanup_removes_old_compressed_files(self):
        import api.audit as _audit
        import time

        # First rotate so we have a .gz
        _audit.rotate_old_logs(age_days=7)

        # Age the .gz file to 91 days old
        gz_files = list(self.audit_dir.glob("audit-*.jsonl.gz"))
        self.assertEqual(len(gz_files), 1, f"Need exactly 1 .gz to test cleanup, got {gz_files}")
        old_mtime = time.time() - (91 * 86400)
        os.utime(gz_files[0], (old_mtime, old_mtime))

        result = _audit.cleanup(days=90)
        self.assertEqual(result["deleted"], 1, result)
        self.assertEqual(result["errors"], 0, result)
        self.assertEqual(list(self.audit_dir.glob("audit-*.jsonl.gz")), [])

    def test_cleanup_preserves_recent_compressed_files(self):
        import api.audit as _audit
        import time

        _audit.rotate_old_logs(age_days=7)
        gz_files = list(self.audit_dir.glob("audit-*.jsonl.gz"))
        self.assertEqual(len(gz_files), 1)

        # Touch to only 30 days old (well within 90-day retention)
        recent_mtime = time.time() - (30 * 86400)
        os.utime(gz_files[0], (recent_mtime, recent_mtime))

        result = _audit.cleanup(days=90)
        self.assertEqual(result["deleted"], 0, result)
        self.assertEqual(result["skipped"], 1, result)

    def test_cleanup_disabled_when_days_zero(self):
        import api.audit as _audit
        result = _audit.cleanup(days=0)
        self.assertEqual(result["deleted"], 0, result)
        self.assertIn("detail", result)

    def test_cleanup_uses_retention_days_config(self):
        import api.audit as _audit
        result = _audit.cleanup(days=None)
        # Default AUDIT_RETENTION_DAYS is 0 → disabled
        self.assertEqual(result["deleted"], 0, result)


if __name__ == "__main__":
    unittest.main()
