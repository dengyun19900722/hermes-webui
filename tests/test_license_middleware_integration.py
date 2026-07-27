"""Integration: License middleware inserted before auth check in server.py."""
import sys
from pathlib import Path

# server.py 在项目根目录，不在 api/ 包内
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import inspect  # noqa: E402
from unittest.mock import MagicMock  # noqa: E402


def test_server_dispatch_calls_license_gate_first():
    """Verify server.py dispatch invokes license gate before check_auth."""
    import server  # noqa: PLC0415
    src = inspect.getsource(server)
    assert "_check_license_middleware" in src, (
        "server.py must wire in license middleware wrapper"
    )
    license_pos = src.find("_check_license_middleware(")
    auth_pos = src.find("check_auth(self, parsed)")
    assert license_pos > 0 and auth_pos > 0, "expected both calls present"
    assert license_pos < auth_pos, "license gate must run before check_auth"


def test_check_license_middleware_wrapper_exists():
    """Wrapper function _check_license_middleware must be exported by server."""
    import server  # noqa: PLC0415
    assert hasattr(server, "_check_license_middleware"), (
        "server._check_license_middleware wrapper is missing"
    )
    assert callable(server._check_license_middleware)


def test_wrapper_passes_through_when_handler_unauthorized():
    """When license is valid and auth disabled, wrapper returns True (pass)."""
    import server  # noqa: PLC0415
    handler = MagicMock()
    parsed = MagicMock()
    parsed.path = "/health"
    # /health is whitelisted → no license check needed, returns True
    result = server._check_license_middleware(handler, parsed)
    assert result is True