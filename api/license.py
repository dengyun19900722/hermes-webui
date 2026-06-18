"""License management module for hermes-webui activation and validation."""

import base64
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

PLATFORM_ID_SALT = "hermes-webui-license"


def get_mac_address() -> str:
    """Get the first non-loopback MAC address, format AA:BB:CC:DD:EE:FF."""
    import platform
    system = platform.system()

    if system == "Linux":
        # Linux: read from /sys/class/net/
        for ifname in os.listdir("/sys/class/net/"):
            if ifname == "lo":
                continue
            path = f"/sys/class/net/{ifname}/address"
            if os.path.exists(path):
                with open(path, "r") as f:
                    mac = f.read().strip()
                if mac and mac != "00:00:00:00:00:00":
                    return mac.upper()
    elif system == "Darwin":
        # macOS: use uuid.getnode which returns the hardware MAC
        try:
            mac_int = uuid.getnode()
            mac_str = ":".join(f"{(mac_int >> i) & 0xff:02x}" for i in range(0, 48, 8)).upper()
            return mac_str
        except (OSError, IOError, ValueError):
            pass

    # Fallback: generate a stable pseudo-MAC based on hostname
    hostname = os.environ.get("HOSTNAME", uuid.gethostname())
    return hashlib.md5((hostname + PLATFORM_ID_SALT).encode()).hexdigest()[:12].upper()


def generate_platform_id(secret_key: str, mac_address: str) -> str:
    """Generate platform_id: PLAT- + SHA256(secret_key + MAC + salt)[:6]."""
    data = f"{secret_key}{mac_address}{PLATFORM_ID_SALT}".encode()
    short = hashlib.sha256(data).hexdigest()[:6].upper()
    return f"PLAT-{short}"


def compute_mac_hash(secret_key: str, mac_address: str) -> str:
    """Compute SHA256(secret_key + MAC) for storage verification."""
    data = f"{secret_key}{mac_address}".encode()
    return hashlib.sha256(data).hexdigest()


def _aes_encrypt(plaintext: str, key: str) -> bytes:
    """AES-256-CBC encrypt, return base64(iv+ciphertext)."""
    key_bytes = hashlib.sha256(key.encode()).digest()
    iv = os.urandom(16)
    cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv), backend=default_backend())
    encryptor = cipher.encryptor()
    # PKCS7 padding
    pad_len = 16 - (len(plaintext) % 16)
    padded = plaintext.encode() + bytes([pad_len] * pad_len)
    ciphertext = encryptor.update(padded) + encryptor.finalize()
    return base64.b64encode(iv + ciphertext)


def _aes_decrypt(data: bytes, key: str) -> str | None:
    """AES-256-CBC decrypt, return plaintext or None."""
    try:
        key_bytes = hashlib.sha256(key.encode()).digest()
        raw = base64.b64decode(data)
        iv = raw[:16]
        ciphertext = raw[16:]
        cipher = Cipher(algorithms.AES(key_bytes), modes.CBC(iv), backend=default_backend())
        decryptor = cipher.decryptor()
        padded = decryptor.update(ciphertext) + decryptor.finalize()
        pad_len = padded[-1]
        if not (1 <= pad_len <= 16):
            return None
        return (padded[:-pad_len]).decode()
    except (ValueError, KeyError, base64.binascii.Error):
        return None


def generate_license_string(secret_key: str, platform_id: str, mac_address: str, expires_at: str) -> str:
    """Generate AES-encrypted license string. Returns base64(encrypted)."""
    plaintext = f"{platform_id}|{mac_address}|{expires_at}"
    return _aes_encrypt(plaintext, secret_key).decode()


def decrypt_license_string(license_string: str, secret_key: str) -> dict | None:
    """AES decrypt license string. Returns {"platform_id", "mac_address", "expires_at"} or None."""
    try:
        plaintext = _aes_decrypt(license_string.encode(), secret_key)
        if plaintext is None:
            return None
        parts = plaintext.split("|")
        if len(parts) != 3:
            return None
        return {"platform_id": parts[0], "mac_address": parts[1], "expires_at": parts[2]}
    except Exception:
        return None


def get_license_dir(workspace: Path) -> Path:
    """Return {workspace}/.license/"""
    return workspace / ".license"


def get_license_config_path(workspace: Path) -> Path:
    """Return {workspace}/.license/license.json"""
    return get_license_dir(workspace) / "license.json"


def get_secret_key_path(workspace: Path) -> Path:
    """Return {workspace}/.license/secret_key"""
    return get_license_dir(workspace) / "secret_key"


def load_license_config(workspace: Path) -> dict:
    """Load license.json, return default structure if not exists."""
    path = get_license_config_path(workspace)
    if path.exists():
        with open(path, "r") as f:
            return json.load(f)
    return {
        "activated": False,
        "mac_hash": None,
        "expires_at": None,
        "imported_at": None,
    }


def save_license_config(workspace: Path, config: dict) -> None:
    """Write license.json."""
    license_dir = get_license_dir(workspace)
    license_dir.mkdir(parents=True, exist_ok=True)
    path = get_license_config_path(workspace)
    with open(path, "w") as f:
        json.dump(config, f, indent=2)


def init_license_config(workspace: Path) -> dict:
    """Initialize license config: read/create license.json, compute platform_id and mac_hash."""
    secret_key_path = get_secret_key_path(workspace)
    if not secret_key_path.exists():
        raise FileNotFoundError(f"secret_key not found at {secret_key_path}")

    with open(secret_key_path, "r") as f:
        secret_key = f.read().strip()

    config = load_license_config(workspace)

    mac_address = get_mac_address()
    platform_id = generate_platform_id(secret_key, mac_address)
    mac_hash = compute_mac_hash(secret_key, mac_address)

    config["platform_id"] = platform_id
    config["mac_hash"] = mac_hash
    config["mac_address"] = mac_address

    save_license_config(workspace, config)
    return config


def check_license_status(workspace: Path) -> dict:
    """
    Check license status. Returns:
    {"activated": bool, "expires_at": str|null, "days_remaining": int|null, "status": str}
    status: "valid" | "expired" | "not_activated" | "copied"
    """
    config = load_license_config(workspace)

    if not config.get("activated"):
        return {
            "activated": False,
            "expires_at": config.get("expires_at"),
            "days_remaining": None,
            "status": "not_activated",
        }

    expires_at_str = config.get("expires_at")
    if not expires_at_str:
        return {
            "activated": True,
            "expires_at": None,
            "days_remaining": None,
            "status": "valid",
        }

    try:
        expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
    except ValueError:
        return {
            "activated": True,
            "expires_at": expires_at_str,
            "days_remaining": None,
            "status": "valid",
        }

    now = datetime.now(timezone.utc)
    remaining = (expires_at - now).days

    if remaining < 0:
        return {
            "activated": True,
            "expires_at": expires_at_str,
            "days_remaining": remaining,
            "status": "expired",
        }

    # Verify MAC hasn't changed (anti-copy check)
    try:
        secret_key_path = get_secret_key_path(workspace)
        if secret_key_path.exists():
            with open(secret_key_path, "r") as f:
                secret_key = f.read().strip()
            current_mac = get_mac_address()
            current_hash = compute_mac_hash(secret_key, current_mac)
            stored_hash = config.get("mac_hash")
            if stored_hash and current_hash != stored_hash:
                return {
                    "activated": True,
                    "expires_at": expires_at_str,
                    "days_remaining": remaining,
                    "status": "copied",
                }
    except Exception:
        import logging
        logging.getLogger(__name__).warning("Failed to verify MAC hash", exc_info=True)
        pass

    return {
        "activated": True,
        "expires_at": expires_at_str,
        "days_remaining": remaining,
        "status": "valid",
    }


def import_license(workspace: Path, license_string: str) -> dict:
    """
    Import and activate license.
    1. Decrypt license_string with secret_key
    2. Verify platform_id and MAC match local
    3. Verify not expired
    4. Update license.json
    Returns {"ok": bool, "error"?: str, "expires_at"?: str}
    """
    secret_key_path = get_secret_key_path(workspace)
    if not secret_key_path.exists():
        return {"ok": False, "error": "secret_key not found"}

    with open(secret_key_path, "r") as f:
        secret_key = f.read().strip()

    decrypted = decrypt_license_string(license_string, secret_key)
    if decrypted is None:
        return {"ok": False, "error": "Invalid license string"}

    license_platform_id = decrypted["platform_id"]
    license_mac = decrypted["mac_address"]
    expires_at = decrypted["expires_at"]

    # Verify platform_id matches
    local_mac = get_mac_address()
    local_platform_id = generate_platform_id(secret_key, local_mac)
    if license_platform_id != local_platform_id:
        return {"ok": False, "error": "Platform ID mismatch"}

    # Verify MAC matches
    if license_mac != local_mac:
        return {"ok": False, "error": "MAC address mismatch"}

    # Verify not expired
    if expires_at:
        try:
            expires_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if expires_dt < datetime.now(timezone.utc):
                return {"ok": False, "error": "License expired"}
        except ValueError:
            pass

    # Update config
    config = load_license_config(workspace)
    config["activated"] = True
    config["expires_at"] = expires_at
    config["imported_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    save_license_config(workspace, config)

    return {"ok": True, "expires_at": expires_at}


# ── Admin functions ────────────────────────────────────────────────────────────

def get_admin_license_list(workspace: Path) -> list[dict]:
    """Return list of generated licenses from licenses.json."""
    license_dir = get_license_dir(workspace)
    list_path = license_dir / "licenses.json"
    if not list_path.exists():
        return []
    try:
        with open(list_path, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []


def save_generated_license(workspace: Path, platform_id: str, mac_address: str, expires_at: str) -> dict:
    """Save a generated license record to licenses.json. Returns the record."""
    license_dir = get_license_dir(workspace)
    license_dir.mkdir(parents=True, exist_ok=True)
    list_path = license_dir / "licenses.json"

    record = {
        "platform_id": platform_id,
        "mac_address": mac_address,
        "expires_at": expires_at,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }

    licenses = []
    if list_path.exists():
        try:
            with open(list_path, "r") as f:
                licenses = json.load(f)
        except (json.JSONDecodeError, IOError):
            licenses = []

    licenses.append(record)

    with open(list_path, "w") as f:
        json.dump(licenses, f, indent=2)

    return record
