import pytest
import responses
from api.custom_providers import probe_models, ProbeError


@responses.activate
def test_probe_ok_extracts_id_field():
    responses.add(
        responses.GET,
        "https://relay.example.com/v1/models",
        json={"data": [{"id": "gpt-4o"}, {"id": "gpt-4o-mini"}]},
        status=200,
    )
    result = probe_models("https://relay.example.com/v1", api_key="sk-xxx", timeout=4.0)
    assert result["ok"] is True
    assert result["models"] == ["gpt-4o", "gpt-4o-mini"]


@responses.activate
def test_probe_ok_falls_back_to_model_field():
    responses.add(
        responses.GET,
        "https://relay.example.com/v1/models",
        json={"data": [{"model": "llama-3"}, {"model": "llama-2"}]},
        status=200,
    )
    result = probe_models("https://relay.example.com/v1", timeout=4.0)
    assert result["models"] == ["llama-3", "llama-2"]


@responses.activate
def test_probe_dedupes():
    responses.add(
        responses.GET,
        "https://x/v1/models",
        json={"data": [{"id": "a"}, {"id": "a"}, {"id": "b"}]},
        status=200,
    )
    result = probe_models("https://x/v1", timeout=4.0)
    assert result["models"] == ["a", "b"]


@responses.activate
def test_probe_401_returns_auth_failed():
    responses.add(responses.GET, "https://x/v1/models", status=401, body="Unauthorized")
    result = probe_models("https://x/v1", api_key="bad", timeout=4.0)
    assert result["ok"] is False
    assert result["error"] == "auth_failed"


@responses.activate
def test_probe_404_returns_not_found():
    responses.add(responses.GET, "https://x/v1/models", status=404)
    result = probe_models("https://x/v1", timeout=4.0)
    assert result["error"] == "not_found"


@responses.activate
def test_probe_invalid_json_returns_invalid_response():
    responses.add(responses.GET, "https://x/v1/models", body="<html>oops</html>", status=200)
    result = probe_models("https://x/v1", timeout=4.0)
    assert result["error"] == "invalid_response"


@responses.activate
def test_probe_connection_error_returns_unreachable():
    import requests as _r
    responses.add(
        responses.GET,
        "https://x/v1/models",
        body=_r.exceptions.ConnectionError("no route"),
    )
    result = probe_models("https://x/v1", timeout=4.0)
    assert result["error"] == "unreachable"


@responses.activate
def test_probe_passes_api_key_in_authorization_header():
    responses.add(
        responses.GET,
        "https://x/v1/models",
        json={"data": [{"id": "a"}]},
        status=200,
    )
    probe_models("https://x/v1", api_key="sk-test", timeout=4.0)
    sent = responses.calls[0].request
    assert sent.headers.get("Authorization") == "Bearer sk-test"