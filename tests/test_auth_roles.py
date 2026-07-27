"""Tests for role check helpers."""
import pytest

from api.auth import is_admin, require_role


def test_is_admin_true():
    user = {"role": "admin"}
    assert is_admin(user) is True


def test_is_admin_false_for_user_role():
    user = {"role": "user"}
    assert is_admin(user) is False


def test_is_admin_false_for_none():
    assert is_admin(None) is False


def test_is_admin_false_for_empty_dict():
    assert is_admin({}) is False


def test_require_role_admin_passes():
    user = {"role": "admin"}
    require_role(user, "admin")  # should not raise


def test_require_role_user_passes_for_user():
    user = {"role": "user"}
    require_role(user, "user")  # should not raise


def test_require_role_admin_fails_for_user():
    user = {"role": "user"}
    with pytest.raises(PermissionError):
        require_role(user, "admin")


def test_require_role_fails_for_none_user():
    with pytest.raises(PermissionError, match="Authentication required"):
        require_role(None, "admin")


def test_require_role_error_message_contains_role():
    user = {"role": "user"}
    with pytest.raises(PermissionError, match="admin"):
        require_role(user, "admin")