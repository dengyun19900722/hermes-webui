"""Tests for api/license.py"""

import pytest


def test_generate_platform_id():
    """Test platform_id generation"""
    from api.license import generate_platform_id

    pid = generate_platform_id("test_secret", "AA:BB:CC:DD:EE:FF")
    assert pid.startswith("PLAT-")
    assert len(pid) == 11  # PLAT- + 6 chars


def test_generate_platform_id_consistency():
    """Test same inputs generate same platform_id"""
    from api.license import generate_platform_id

    pid1 = generate_platform_id("secret", "AA:BB:CC:DD:EE:FF")
    pid2 = generate_platform_id("secret", "AA:BB:CC:DD:EE:FF")
    assert pid1 == pid2


def test_compute_mac_hash():
    """Test MAC hash computation"""
    from api.license import compute_mac_hash

    hash1 = compute_mac_hash("secret", "AA:BB:CC:DD:EE:FF")
    hash2 = compute_mac_hash("secret", "AA:BB:CC:DD:EE:FF")
    assert hash1 == hash2
    assert len(hash1) == 64  # SHA256 hex


def test_compute_mac_hash_different_inputs():
    """Test different inputs produce different hashes"""
    from api.license import compute_mac_hash

    hash1 = compute_mac_hash("secret1", "AA:BB:CC:DD:EE:FF")
    hash2 = compute_mac_hash("secret2", "AA:BB:CC:DD:EE:FF")
    assert hash1 != hash2


def test_license_encrypt_decrypt():
    """Test license encrypt/decrypt round-trip"""
    from api.license import generate_license_string, decrypt_license_string

    secret = "my_secret_key"
    pid = "PLAT-123456"
    mac = "AA:BB:CC:DD:EE:FF"
    expires = "2027-06-30T23:59:59Z"

    license_str = generate_license_string(secret, pid, mac, expires)
    result = decrypt_license_string(license_str, secret)
    assert result is not None
    assert result["platform_id"] == pid
    assert result["mac_address"] == mac
    assert result["expires_at"] == expires


def test_license_decrypt_wrong_key():
    """Test decryption with wrong key returns None"""
    from api.license import generate_license_string, decrypt_license_string

    license_str = generate_license_string("secret1", "PLAT-123456", "AA:BB:CC:DD:EE:FF", "2027-06-30")
    result = decrypt_license_string(license_str, "wrong_secret")
    assert result is None


def test_license_decrypt_invalid_string():
    """Test decryption of invalid string returns None"""
    from api.license import decrypt_license_string

    result = decrypt_license_string("not_valid_base64!", "secret")
    assert result is None