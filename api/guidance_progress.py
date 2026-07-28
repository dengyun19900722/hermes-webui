"""实施助手引导页（2.1）后端模块。

读写 ~/.hermes/guidance_progress.yaml，提供 5 个 endpoint 的业务逻辑。
YAML 写采用原子替换（tmp + os.replace）避免半写损坏。
"""
from __future__ import annotations

import os
import yaml
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

# 12 项任务白名单（与 spec §4.1 一致）
ALLOWED_TASKS = frozenset({
    "1.1_view_doc", "1.2_download_tpl", "1.3_validate", "1.3_import", "1.3_verify",
    "2.1_view_template", "2.2_batch_import", "2.3_verify_search",
    "3.1_select_business_line", "3.2_run_inspection", "3.3_run_diagnosis", "3.4_record_result",
})


def _guidance_progress_path() -> Path:
    """Return ~/.hermes/guidance_progress.yaml for the active profile."""
    home = Path(os.getenv("HERMES_HOME", str(Path.home() / ".hermes"))).expanduser()
    return home / "guidance_progress.yaml"


def _atomic_write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Atomically write data to YAML via tmp + os.replace. On failure, tmp is cleaned."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)
        os.replace(tmp, path)
    except OSError as e:
        if tmp.exists():
            tmp.unlink()
        raise RuntimeError(f"guidance_progress.yaml write failed: {e}") from e


def load_progress() -> dict[str, Any]:
    """Read guidance_progress.yaml; return empty schema if file missing."""
    path = _guidance_progress_path()
    if not path.exists():
        return {"schema_version": SCHEMA_VERSION, "implementation": {}}
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    data.setdefault("schema_version", SCHEMA_VERSION)
    data.setdefault("implementation", {})
    return data


def save_progress(data: dict[str, Any]) -> None:
    """Atomically write progress data to disk."""
    _atomic_write_yaml(_guidance_progress_path(), data)
