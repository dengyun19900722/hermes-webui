"""Integration tests for License API endpoints.

Tests the following endpoints:
- GET  /api/license/status        - Get license status
- GET  /api/admin/license/list    - List generated licenses
- POST /api/license/apply         - Get platform info for license application
- POST /api/license/import        - Import license string
- POST /api/admin/license/generate - Generate new license
"""

import json
import urllib.error
import urllib.request

import pytest

from tests._pytest_port import BASE
from tests.conftest import TEST_STATE_DIR


pytestmark = pytest.mark.usefixtures("test_server")


def _get(path):
    """Make GET request and return (json_data, status_code)."""
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        payload = e.read()
        return json.loads(payload or b"{}"), e.code


def _post(path, body):
    """Make POST request and return (json_data, status_code)."""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        BASE + path,
        data=data,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read()), r.status
    except urllib.error.HTTPError as e:
        payload = e.read()
        return json.loads(payload or b"{}"), e.code


def _clear_license_env():
    """Clear license environment for test isolation."""
    import shutil
    license_dir = TEST_STATE_DIR / ".license"
    if license_dir.exists():
        shutil.rmtree(license_dir)


def _init_license_env(secret_key: str = "test-secret-key-12345"):
    """Initialize license environment by creating secret_key file."""
    _clear_license_env()
    license_dir = TEST_STATE_DIR / ".license"
    license_dir.mkdir(parents=True, exist_ok=True)
    secret_key_path = license_dir / "secret_key"
    secret_key_path.write_text(secret_key)
    return secret_key_path


class TestLicenseStatusEndpoint:
    """Tests for GET /api/license/status"""

    def test_license_status_without_initialization(self):
        """Without secret_key file, should return 400."""
        _clear_license_env()
        resp, status = _get("/api/license/status")
        assert status == 400

    def test_license_status_with_initialization(self):
        """With secret_key file, should return 200 with status info."""
        _init_license_env()
        resp, status = _get("/api/license/status")
        assert status == 200
        assert "activated" in resp
        assert "status" in resp
        assert "platform_id" in resp
        assert "mac_address" in resp


class TestLicenseApplyEndpoint:
    """Tests for POST /api/license/apply (note: this is POST, not GET)"""

    def test_license_apply_without_initialization(self):
        """Without secret_key file, should return 400."""
        _clear_license_env()
        resp, status = _post("/api/license/apply", {})
        assert status == 400

    def test_license_apply_with_initialization(self):
        """With secret_key file, should return platform_id and mac_address."""
        _init_license_env()
        resp, status = _post("/api/license/apply", {})
        assert status == 200
        assert "platform_id" in resp
        assert "mac_address" in resp
        assert resp["platform_id"].startswith("PLAT-")


class TestLicenseImportEndpoint:
    """Tests for POST /api/license/import"""

    def test_license_import_invalid_string(self):
        """Invalid license string should return 400."""
        resp, status = _post("/api/license/import", {"license_string": "invalid"})
        assert status == 400
        assert "error" in resp

    def test_license_import_missing_field(self):
        """Missing license_string field should return 400."""
        resp, status = _post("/api/license/import", {})
        assert status == 400

    def test_license_import_without_initialization(self):
        """Without secret_key file, should return 400."""
        _clear_license_env()
        resp, status = _post("/api/license/import", {"license_string": "some-license"})
        assert status == 400


class TestLicenseAdminListEndpoint:
    """Tests for GET /api/admin/license/list"""

    def test_license_admin_list_empty(self):
        """Should return empty licenses list initially."""
        _clear_license_env()
        resp, status = _get("/api/admin/license/list")
        assert status == 200
        assert "licenses" in resp
        assert isinstance(resp["licenses"], list)

    def test_license_admin_list_after_generate(self):
        """Should return generated licenses."""
        # First initialize and generate a license
        _init_license_env()
        _post(
            "/api/admin/license/generate",
            {
                "platform_id": "PLAT-123456",
                "mac_address": "AA:BB:CC:DD:EE:FF",
                "expires_at": "2027-06-30T23:59:59Z",
            },
        )

        resp, status = _get("/api/admin/license/list")
        assert status == 200
        assert "licenses" in resp
        assert len(resp["licenses"]) >= 1


class TestLicenseAdminGenerateEndpoint:
    """Tests for POST /api/admin/license/generate"""

    def test_license_generate_without_initialization(self):
        """Without secret_key file, should return 400."""
        _clear_license_env()
        resp, status = _post(
            "/api/admin/license/generate",
            {
                "platform_id": "PLAT-123456",
                "mac_address": "AA:BB:CC:DD:EE:FF",
                "expires_at": "2027-06-30T23:59:59Z",
            },
        )
        assert status == 400

    def test_license_generate_with_initialization(self):
        """With secret_key file, should generate license and return 200."""
        _init_license_env()
        resp, status = _post(
            "/api/admin/license/generate",
            {
                "platform_id": "PLAT-123456",
                "mac_address": "AA:BB:CC:DD:EE:FF",
                "expires_at": "2027-06-30T23:59:59Z",
            },
        )
        assert status == 200
        assert resp.get("ok") is True
        assert "license_string" in resp

    def test_license_generate_missing_fields(self):
        """Missing required fields should return 400."""
        _init_license_env()
        resp, status = _post("/api/admin/license/generate", {"platform_id": "PLAT-123456"})
        assert status == 400