import json
from pathlib import Path

from server import Handler


def test_log_request_handles_malformed_request_without_path(capsys):
    """Malformed request lines can call log_request before path is assigned."""
    handler = Handler.__new__(Handler)
    handler.command = None

    Handler.log_request(handler, "400")

    line = capsys.readouterr().out.strip()
    assert line.startswith("[webui] ")
    record = json.loads(line.removeprefix("[webui] "))
    assert record["method"] == "-"
    assert record["path"] == "-"
    assert record["status"] == 400
    assert record["remote"] == "-"


def test_log_request_includes_remote_address(capsys):
    handler = Handler.__new__(Handler)
    handler.command = "POST"
    handler.path = "/api/auth/login"
    handler.client_address = ("192.0.2.10", 54321)
    handler.headers = {}

    Handler.log_request(handler, "401")

    line = capsys.readouterr().out.strip()
    record = json.loads(line.removeprefix("[webui] "))
    assert record["remote"] == "192.0.2.10"
    assert "forwarded_for" not in record


def test_log_request_includes_first_forwarded_for_address(capsys):
    class Headers:
        def get(self, key):
            assert key == "X-Forwarded-For"
            return "203.0.113.7, 198.51.100.9"

    handler = Handler.__new__(Handler)
    handler.command = "POST"
    handler.path = "/api/auth/login"
    handler.client_address = ("192.0.2.10", 54321)
    handler.headers = Headers()

    Handler.log_request(handler, "401")

    line = capsys.readouterr().out.strip()
    record = json.loads(line.removeprefix("[webui] "))
    assert record["remote"] == "192.0.2.10"
    assert record["forwarded_for"] == "203.0.113.7"


def test_log_request_audit_entry_uses_forwarded_ip_when_not_preseeded(capsys):
    captured = {}

    class AuditStub:
        @staticmethod
        def write(**entry):
            captured.update(entry)

    class Headers:
        def get(self, key):
            return {
                "X-Forwarded-For": "203.0.113.7, 198.51.100.9",
                "User-Agent": "audit-test/1.0",
            }.get(key, "")

    handler = Handler.__new__(Handler)
    handler.command = "POST"
    handler.path = "/api/chat/start"
    handler.client_address = ("192.0.2.10", 54321)
    handler.headers = Headers()

    previous = Handler._audit_module
    Handler._audit_module = AuditStub
    try:
        Handler.log_request(handler, "200")
    finally:
        Handler._audit_module = previous

    capsys.readouterr()
    assert captured["client_ip"] == "203.0.113.7"
    assert captured["user_agent"] == "audit-test/1.0"
    assert captured["action"] == "POST /api/chat/start"
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/chat/start"
    assert captured["status"] == 200
    assert "duration_ms" in captured


def test_chat_start_records_pending_client_ip_from_forwarded_headers():
    from api import routes

    class Headers:
        def get(self, key):
            return {
                "X-Forwarded-For": "203.0.113.9, 198.51.100.9",
                "X-Real-IP": "198.51.100.99",
            }.get(key, "")

    handler = type("Handler", (), {})()
    handler.headers = Headers()
    handler.client_address = ("192.0.2.10", 54321)

    assert routes._client_ip_for_audit(handler) == "203.0.113.9"

    fallback_handler = type("Handler", (), {})()
    fallback_handler.headers = {}
    fallback_handler._client_ip = "-"
    fallback_handler.client_address = ("192.0.2.11", 54321)
    assert routes._client_ip_for_audit(fallback_handler) == "192.0.2.11"

    src = Path(routes.__file__).read_text(encoding="utf-8")
    assert "s.pending_client_ip = client_ip if client_ip and client_ip != \"-\" else None" in src
