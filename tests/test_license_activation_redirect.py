"""Regression tests for the first-deployment License activation redirect."""
from types import SimpleNamespace
from unittest.mock import MagicMock


def _activation_handler():
    handler = MagicMock()
    handler.headers = {}
    return handler


def _run_activation_route(monkeypatch, initialized, tmp_path):
    import api.auth as auth
    import api.rbac_routes as rbac_routes
    import api.routes as routes

    handler = _activation_handler()
    parsed = SimpleNamespace(path="/license/activate", query="")
    monkeypatch.setattr(routes, "DEFAULT_WORKSPACE", tmp_path)
    monkeypatch.setattr(
        "api.license.init_license_config",
        lambda _workspace: {"platform_id": "PLAT-TEST"},
    )
    monkeypatch.setattr(
        "api.license.check_license_status",
        lambda _workspace: {"status": "valid"},
    )
    def needs_setup():
        return not initialized

    monkeypatch.setattr(auth, "needs_initialization", needs_setup)
    # rbac_routes imports this helper at module load time, so patch its alias
    # too and avoid leaking the test state into later route tests.
    monkeypatch.setattr(rbac_routes, "needs_initialization", needs_setup)

    assert routes.handle_get(handler, parsed) is True
    locations = [
        call.args[1]
        for call in handler.send_header.call_args_list
        if call.args[0] == "Location"
    ]
    assert locations == ["/setup" if not initialized else "/"]


def test_license_activation_redirects_fresh_deployment_to_setup(monkeypatch, tmp_path):
    _run_activation_route(monkeypatch, initialized=False, tmp_path=tmp_path)


def test_license_activation_redirects_initialized_deployment_to_app(monkeypatch, tmp_path):
    _run_activation_route(monkeypatch, initialized=True, tmp_path=tmp_path)
