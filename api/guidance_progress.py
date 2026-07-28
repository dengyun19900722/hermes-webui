"""实施助手引导页（2.1）后端模块。

读写 ~/.hermes/guidance_progress.yaml，提供 5 个 endpoint 的业务逻辑。
YAML 写采用原子替换（UUID tmp + os.replace）避免半写损坏 + 并发写冲突。
"""
from __future__ import annotations

import os
import uuid
import yaml
from pathlib import Path
from typing import Any

from api.profiles import get_active_hermes_home

SCHEMA_VERSION = 1

# 12 项任务白名单（与 spec §4.1 一致）
ALLOWED_TASKS = frozenset({
    "1.1_view_doc", "1.2_download_tpl", "1.3_validate", "1.3_import", "1.3_verify",
    "2.1_view_template", "2.2_batch_import", "2.3_verify_search",
    "3.1_select_business_line", "3.2_run_inspection", "3.3_run_diagnosis", "3.4_record_result",
})


def _guidance_progress_path() -> Path:
    """Return the active profile's ~/.hermes/guidance_progress.yaml.

    Uses get_active_hermes_home() so per-request TLS profile context (#798)
    is respected, not just the process-level HERMES_HOME env var. This ensures
    progress state follows the logged-in user's profile, not the server's
    startup profile.
    """
    return get_active_hermes_home() / "guidance_progress.yaml"


def _atomic_write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Atomically write data to YAML via UUID tmp + os.replace.

    - UUID tmp suffix prevents concurrent writers from clobbering each other.
    - Creates parent directory if missing (matches project convention in
      api/passkeys.py:70, api/config.py:791, api/onboarding.py:253).
    - Catches both OSError (file system) and yaml.YAMLError (serialization).
    - On any failure, tmp is cleaned and RuntimeError raised with context.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        os.replace(tmp, path)
    except (OSError, yaml.YAMLError) as e:
        if tmp.exists():
            tmp.unlink()
        raise RuntimeError(f"guidance_progress.yaml write failed: {e}") from e


def load_progress() -> dict[str, Any]:
    """Read guidance_progress.yaml; return empty schema if file missing or invalid.

    Robust against:
    - Missing file → empty schema
    - Empty file → empty schema
    - Non-mapping YAML (e.g., scalar/list from user edit) → empty schema
    - Missing required keys → defaults applied
    """
    path = _guidance_progress_path()
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "implementation": {}}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError:
        # Corrupted YAML — return empty rather than crash
        return {"schema_version": SCHEMA_VERSION, "implementation": {}}

    if not isinstance(data, dict):
        # User-edited file with non-mapping (scalar/list) — fall back to empty
        return {"schema_version": SCHEMA_VERSION, "implementation": {}}

    data.setdefault("schema_version", SCHEMA_VERSION)
    data.setdefault("implementation", {})
    return data


def save_progress(data: dict[str, Any]) -> None:
    """Atomically write progress data to disk."""
    _atomic_write_yaml(_guidance_progress_path(), data)