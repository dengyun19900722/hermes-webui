"""Tests for License state middleware (pre-RBAC gating)."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch
from api.license_middleware import (
    check_license_gate, _is_whitelisted_path,
)


def test_whitelist_static_paths():
    assert _is_whitelisted_path("/static/login.js") is True
    assert _is_whitelisted_path("/session/static/main.css") is True


def test_whitelist_health():
    assert _is_whitelisted_path("/health") is True


def test_whitelist_license_routes():
    assert _is_whitelisted_path("/license") is True
    assert _is_whitelisted_path("/license/activate") is True
    assert _is_whitelisted_path("/api/license/status") is True
    assert _is_whitelisted_path("/api/license/import") is True


def test_non_whitelisted_needs_license_check():
    assert _is_whitelisted_path("/login") is False
    assert _is_whitelisted_path("/api/sessions") is False
    assert _is_whitelisted_path("/admin") is False


def test_check_license_gate_not_activated_redirects(tmp_path):
    """未激活时 HTML 请求重定向到 /license/activate。"""
    handler = MagicMock()
    parsed = MagicMock()
    parsed.path = "/login"

    with patch("api.license_middleware.check_license_status") as mock_status:
        mock_status.return_value = {"status": "not_activated"}
        result = check_license_gate(handler, parsed, tmp_path)
    assert result is False
    handler.send_response.assert_called_once_with(302)
    location = handler.send_header.call_args_list[0][0][1]
    assert location == "/license/activate"


def test_check_license_gate_expired_returns_403(tmp_path):
    """expired 状态返回 403。"""
    handler = MagicMock()
    parsed = MagicMock()
    parsed.path = "/login"

    with patch("api.license_middleware.check_license_status") as mock_status:
        mock_status.return_value = {"status": "expired"}
        result = check_license_gate(handler, parsed, tmp_path)
    assert result is False
    handler.send_response.assert_called_once_with(403)


def test_check_license_gate_copied_returns_403(tmp_path):
    """copied 状态返回 403。"""
    handler = MagicMock()
    parsed = MagicMock()
    parsed.path = "/api/sessions"

    with patch("api.license_middleware.check_license_status") as mock_status:
        mock_status.return_value = {"status": "copied"}
        result = check_license_gate(handler, parsed, tmp_path)
    assert result is False
    handler.send_response.assert_called_once_with(403)


def test_check_license_gate_valid_passes_through(tmp_path):
    """valid 状态放行。"""
    handler = MagicMock()
    parsed = MagicMock()
    parsed.path = "/login"

    with patch("api.license_middleware.check_license_status") as mock_status:
        mock_status.return_value = {"status": "valid"}
        result = check_license_gate(handler, parsed, tmp_path)
    assert result is True
    handler.send_response.assert_not_called()


def test_check_license_gate_whitelist_passes_through(tmp_path):
    """白名单路径不检查 license 状态。"""
    handler = MagicMock()
    parsed = MagicMock()
    parsed.path = "/health"

    result = check_license_gate(handler, parsed, tmp_path)
    assert result is True
    handler.send_response.assert_not_called()


def test_check_license_gate_module_error_passes_through(tmp_path):
    """license 模块异常时放行（向后兼容）。"""
    handler = MagicMock()
    parsed = MagicMock()
    parsed.path = "/login"

    with patch("api.license_middleware.check_license_status",
               side_effect=Exception("module broken")):
        result = check_license_gate(handler, parsed, tmp_path)
    assert result is True