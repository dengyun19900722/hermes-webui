import json

from scripts.p0_online_baseline import (
    Sample,
    _discover_session_id,
    _parse_server_diagnostics,
    _validate_client,
    _verify_expected_user,
)


class StubClient:
    def __init__(self, status, payload, *, error=""):
        self.status = status
        self.payload = payload
        self.error = error

    def get(self, endpoint, path):
        sample = Sample(endpoint, path, self.status, 0, 0, 0, 0, 0, 0, self.error)
        return sample, json.dumps(self.payload).encode()


def test_discover_session_skips_cli_projection_and_selects_webui_session():
    client = StubClient(
        200,
        {
            "sessions": [
                {"session_id": "cli", "is_cli_session": True},
                {"session_id": "webui", "is_cli_session": False},
            ]
        },
    )

    session_id, sample = _discover_session_id(client)

    assert sample.status == 200
    assert session_id == "webui"


def test_parse_server_diagnostics_reads_only_records_after_byte_offset(tmp_path):
    log_path = tmp_path / "server.log"
    log_path.write_text(
        'WARNING old WebUI request diagnostics: {"path": "/old"}\n',
        encoding="utf-8",
    )
    offset = log_path.stat().st_size
    with log_path.open("a", encoding="utf-8") as log_file:
        log_file.write(
            'WARNING new WebUI request diagnostics: {"path": "/api/sessions"}\n'
        )

    records = _parse_server_diagnostics(log_path, start_offset=offset)

    assert records == [{"path": "/api/sessions"}]


def test_verify_expected_user_never_accepts_a_different_identity():
    client = StubClient(200, {"user": {"id": "actual-user"}})

    try:
        _verify_expected_user(client, "expected-user")
    except ValueError as exc:
        assert str(exc) == "authenticated user does not match P0_EXPECTED_USER_ID"
    else:
        raise AssertionError("identity mismatch was accepted")


def test_validate_client_rejects_http_and_transport_failures():
    samples = [
        Sample("ok", "/ok", 200, 0, 0, 0, 0, 1, 2),
        Sample("denied", "/denied", 403, 0, 0, 0, 0, 1, 2),
        Sample("timeout", "/timeout", 0, 0, 0, 0, 0, 1, 0, "TimeoutError"),
    ]

    assert _validate_client(samples) == [
        "denied: unexpected HTTP 403",
        "timeout: TimeoutError",
    ]
