from __future__ import annotations

import io
import json
import subprocess
import sys
import types
from pathlib import Path
from urllib.parse import urlencode, urlparse

import pytest


def _config():
    return {
        "log_context_sources": {
            "zk-app-01": {
                "mode": "expect_ssh",
                "host": "10.10.20.11",
                "host_ip": "10.10.20.11",
                "account": "logreader",
                "port": 22,
                "user": "logreader",
                "password_env": "ZK_APP_01_LOG_PASSWORD",
                "roots": ["/data/app/logs", "/var/log/zk"],
                "timeout_seconds": 8,
                "max_context_lines": 5,
                "max_response_bytes": 4096,
            }
        },
    }


def test_build_request_rejects_unknown_source(monkeypatch):
    from api import log_context

    monkeypatch.setattr(log_context, "get_config", lambda: _config())

    with pytest.raises(log_context.LogContextError) as exc:
        log_context.build_request_from_query(
            urlencode({"source": "missing", "path": "/data/app/logs/app.log", "line": "10"})
        )

    assert exc.value.code == "source_not_found"
    assert exc.value.status == 404


def test_build_request_rejects_path_outside_roots(monkeypatch):
    from api import log_context

    monkeypatch.setattr(log_context, "get_config", lambda: _config())

    with pytest.raises(log_context.LogContextError) as exc:
        log_context.build_request_from_query(
            urlencode({"source": "zk-app-01", "path": "/data/app/logs/../../etc/passwd", "line": "10"})
        )

    assert exc.value.code == "path_not_allowed"
    assert exc.value.status == 403


def test_build_request_clips_context_window(monkeypatch):
    from api import log_context

    monkeypatch.setattr(log_context, "get_config", lambda: _config())

    req = log_context.build_request_from_query(
        urlencode({
            "source": "zk-app-01",
            "path": "/data/app/logs/app.log",
            "line": "100",
            "before": "100",
            "after": "100",
            "session_id": "abc123",
        })
    )

    assert req.start_line == 98
    assert req.end_line == 102
    assert req.before == 2
    assert req.after == 2
    assert req.clipped is True


def test_build_request_rejects_invalid_host_ip(monkeypatch):
    from api import log_context

    monkeypatch.setattr(log_context, "get_config", lambda: _config())

    with pytest.raises(log_context.LogContextError) as exc:
        log_context.build_request_from_query(
            urlencode({
                "source": "zk-app-01",
                "host_ip": "not-an-ip",
                "path": "/data/app/logs/app.log",
                "line": "10",
            })
        )

    assert exc.value.code == "invalid_host_ip"
    assert exc.value.status == 400


def _install_fake_neo4j(monkeypatch, record):
    class _Result:
        def single(self):
            return record

    class _Session:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def run(self, query, **params):
            assert "MATCH (h:Host {ip: $host_ip})" in query.text
            assert query.timeout == 5
            assert params["host_ip"] == "10.10.20.11"
            return _Result()

    class _Driver:
        closed = False

        def session(self):
            return _Session()

        def close(self):
            self.closed = True

    class _GraphDatabase:
        @staticmethod
        def driver(uri, auth, connection_timeout):
            assert uri == "bolt://neo4j.local:7687"
            assert auth == ("neo4j", "neo4j-password")
            assert connection_timeout == 3
            return _Driver()

    class _Query:
        def __init__(self, text, *, timeout):
            self.text = text
            self.timeout = timeout

    fake_module = types.SimpleNamespace(GraphDatabase=_GraphDatabase, Query=_Query)
    monkeypatch.setitem(sys.modules, "neo4j", fake_module)


def test_build_request_can_use_neo4j_credentials_without_source(monkeypatch):
    from api import log_context

    monkeypatch.setattr(log_context, "get_config", lambda: {})
    monkeypatch.setenv("NEO4J_URI", "bolt://neo4j.local:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "neo4j-password")
    _install_fake_neo4j(
        monkeypatch,
        {"ssh_user": "root", "ssh_password": "ssh-secret", "ssh_port": 2202},
    )

    req = log_context.build_request_from_query(
        urlencode({
            "host_ip": "10.10.20.11",
            "path": "/any/log/path/app.log",
            "line": "100",
        })
    )

    assert req.source.source_id == "10.10.20.11"
    assert req.source.host == "10.10.20.11"
    assert req.source.user == "root"
    assert req.source.password_env == ""
    assert req.source.password_value == "ssh-secret"
    assert req.source.port == 2202
    assert req.source.roots == ("/",)
    assert req.account == "root"


def test_neo4j_credentials_use_source_template_roots_when_source_is_present(monkeypatch):
    from api import log_context

    monkeypatch.setattr(log_context, "get_config", lambda: _config())
    monkeypatch.setenv("NEO4J_URI", "bolt://neo4j.local:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "neo4j-password")
    _install_fake_neo4j(
        monkeypatch,
        {"ssh_user": "root", "ssh_password": "ssh-secret", "ssh_port": 22},
    )

    req = log_context.build_request_from_query(
        urlencode({
            "source": "zk-app-01",
            "host_ip": "10.10.20.11",
            "path": "/data/app/logs/app.log",
            "line": "100",
        })
    )

    assert req.source.source_id == "zk-app-01"
    assert req.source.roots == ("/data/app/logs", "/var/log/zk")
    assert req.source.password_value == "ssh-secret"

    with pytest.raises(log_context.LogContextError) as exc:
        log_context.build_request_from_query(
            urlencode({
                "source": "zk-app-01",
                "host_ip": "10.10.20.11",
                "path": "/tmp/app.log",
                "line": "100",
            })
        )

    assert exc.value.code == "path_not_allowed"


def test_fetch_log_context_parses_expect_markers(monkeypatch):
    from api import log_context

    monkeypatch.setattr(log_context, "get_config", lambda: _config())
    monkeypatch.setenv("ZK_APP_01_LOG_PASSWORD", "secret")
    req = log_context.build_request_from_query(
        urlencode({"source": "zk-app-01", "path": "/data/app/logs/app.log", "line": "12345", "before": "1", "after": "1"})
    )

    def fake_run(_req, password):
        assert _req is req
        assert password == "secret"
        stdout = (
            "ssh banner\n"
            f"{log_context.BEGIN_MARKER}\n"
            "12344\tbefore\n"
            "12345\tERROR connection timeout\n"
            f"{log_context.TRUNCATED_MARKER}\n"
            f"{log_context.END_MARKER}\n"
        ).encode()
        return subprocess.CompletedProcess(["fake"], 0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(log_context, "_run_expect_script", fake_run)

    payload = log_context.fetch_log_context(req)

    assert payload["ok"] is True
    assert payload["source"] == "zk-app-01"
    assert payload["host_ip"] == ""
    assert payload["account"] == ""
    assert payload["path"] == "/data/app/logs/app.log"
    assert payload["line"] == 12345
    assert payload["truncated"] is True
    assert payload["lines"] == [
        {"no": 12344, "text": "before", "match": False},
        {"no": 12345, "text": "ERROR connection timeout", "match": True},
    ]


def test_fetch_log_context_uses_neo4j_password_value_without_env(monkeypatch):
    from api import log_context

    monkeypatch.setattr(log_context, "get_config", lambda: {})
    monkeypatch.setenv("NEO4J_URI", "bolt://neo4j.local:7687")
    monkeypatch.setenv("NEO4J_USER", "neo4j")
    monkeypatch.setenv("NEO4J_PASSWORD", "neo4j-password")
    monkeypatch.delenv("ZK_APP_01_LOG_PASSWORD", raising=False)
    _install_fake_neo4j(
        monkeypatch,
        {"ssh_user": "root", "ssh_password": "ssh-secret", "ssh_port": 22},
    )
    req = log_context.build_request_from_query(
        urlencode({"host_ip": "10.10.20.11", "path": "/var/log/app.log", "line": "10"})
    )

    def fake_run(_req, password):
        assert _req is req
        assert password == "ssh-secret"
        stdout = f"{log_context.BEGIN_MARKER}\n10\tok\n{log_context.END_MARKER}\n".encode()
        return subprocess.CompletedProcess(["fake"], 0, stdout=stdout, stderr=b"")

    monkeypatch.setattr(log_context, "_run_expect_script", fake_run)

    payload = log_context.fetch_log_context(req)

    assert payload["lines"] == [{"no": 10, "text": "ok", "match": True}]


def test_fetch_log_context_maps_file_not_found(monkeypatch):
    from api import log_context

    monkeypatch.setattr(log_context, "get_config", lambda: _config())
    monkeypatch.setenv("ZK_APP_01_LOG_PASSWORD", "secret")
    req = log_context.build_request_from_query(
        urlencode({"source": "zk-app-01", "path": "/data/app/logs/app.log", "line": "10"})
    )

    def fake_run(_req, _password):
        stdout = f"{log_context.BEGIN_MARKER}\n{log_context.END_MARKER}\n".encode()
        return subprocess.CompletedProcess(["fake"], 2, stdout=stdout, stderr=b"awk: cannot open /data/app/logs/app.log")

    monkeypatch.setattr(log_context, "_run_expect_script", fake_run)

    with pytest.raises(log_context.LogContextError) as exc:
        log_context.fetch_log_context(req)

    assert exc.value.code == "file_not_found"
    assert exc.value.status == 404


class _FakeHandler:
    def __init__(self):
        self.headers = {
            "X-Forwarded-For": "203.0.113.77, 198.51.100.1",
            "User-Agent": "log-context-test/1.0",
        }
        self.client_address = ("192.0.2.10", 54321)
        self.wfile = io.BytesIO()
        self.status = None
        self.sent_headers = {}

    def send_response(self, status):
        self.status = status

    def send_header(self, key, value):
        self.sent_headers[key] = value

    def end_headers(self):
        return None


def test_log_context_route_returns_payload_and_audits_client_ip(monkeypatch):
    from api import audit, log_context, routes

    monkeypatch.setattr(log_context, "get_config", lambda: _config())
    monkeypatch.setenv("ZK_APP_01_LOG_PASSWORD", "secret")

    def fake_run(_req, _password):
        stdout = f"{log_context.BEGIN_MARKER}\n10\tok\n{log_context.END_MARKER}\n".encode()
        return subprocess.CompletedProcess(["fake"], 0, stdout=stdout, stderr=b"")

    captured = {}
    monkeypatch.setattr(log_context, "_run_expect_script", fake_run)
    monkeypatch.setattr(audit, "write", lambda **entry: captured.update(entry))

    handler = _FakeHandler()
    handled = routes.handle_get(
        handler,
        urlparse("/api/log-context?" + urlencode({
            "source": "zk-app-01",
            "path": "/data/app/logs/app.log",
            "line": "10",
            "session_id": "session-1",
        })),
    )

    assert handled is None
    assert handler.status == 200
    payload = json.loads(handler.wfile.getvalue().decode("utf-8"))
    assert payload["lines"] == [{"no": 10, "text": "ok", "match": True}]
    assert payload["host_ip"] == "10.10.20.11"
    assert payload["account"] == "logreader"
    assert "password_env" not in payload
    assert captured["category"] == "log_context"
    assert captured["action"] == "view_log_context"
    assert captured["source"] == "zk-app-01"
    assert captured["path"] == "/data/app/logs/app.log"
    assert captured["line"] == 10
    assert captured["host_ip"] == "10.10.20.11"
    assert captured["account"] == "logreader"
    assert captured["session_id"] == "session-1"
    assert captured["client_ip"] == "203.0.113.77"


def test_expect_script_uses_fixed_awk_reader_not_tail():
    script = Path("scripts/log_context_expect.sh").read_text(encoding="utf-8")
    connector = Path("api/log_context.py").read_text(encoding="utf-8")

    assert "spawn ssh" in script
    assert "LOGCTX_REMOTE_COMMAND" in script
    assert "tail" not in script
    assert "tail" not in connector
    assert "awk " in connector
