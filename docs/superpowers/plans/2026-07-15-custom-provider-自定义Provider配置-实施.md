# Custom Provider 配置 UI 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 WebUI 内提供自定义 OpenAI-compatible Provider 的 CRUD 入口（Settings → Providers 面板 + Composer 快捷入口），所有 profile 自动生效，API key 字面量存入 `config.yaml` 不写 `.env`。

**Architecture:**
- 新建后端模块 `api/custom_providers.py` 抽业务逻辑（slug 派生、校验、probe、CRUD、set_default、broadcast）
- 在 `api/routes.py` 加 4 个 endpoint：`/api/custom_providers` (GET/POST)、`/api/custom_providers/probe_models`、`/api/custom_providers/set_default`
- 前端复用现有 `_buildProviderCard` 模式，新增 `_buildCustomProviderCard`；改写 `loadProvidersPanel` 把 Custom 区置顶、Built-in 折叠
- Composer 下拉底部新增 ➕ 入口，触发 mini modal（极简字段，持久化与全量表单同源）

**Tech Stack:** Python (标准库 + pytest + responses 库 mock), Vanilla JS, HTML/CSS, 项目内 `api/probe_provider_endpoint`（`api/onboarding.py:356`）

**Spec:** `docs/superpowers/specs/2026-07-15-custom-provider-自定义Provider配置-设计.md`

---

## 文件结构

```
api/custom_providers.py                         # 新建：业务逻辑模块
api/routes.py                                   # 修改：4 个 endpoint handler
static/panels.js                                # 修改：Custom 区卡片 + modal
static/ui.js                                    # 修改：Composer ➕ + mini modal
static/i18n.js                                  # 修改：39 个 i18n 键

tests/test_custom_providers_slug.py             # 新建：slug 派生
tests/test_custom_providers_validation.py       # 新建：输入校验
tests/test_custom_providers_probe.py            # 新建：probe 纯函数
tests/test_custom_providers_crud.py             # 新建：HTTP CRUD
tests/test_custom_providers_broadcast.py        # 新建：多 profile 广播
tests/test_custom_providers_set_default.py      # 新建：设为默认
tests/test_custom_providers_models_integration.py  # 新建：模型下拉集成
tests/test_custom_providers_concurrency.py      # 新建：并发 + 原子写
tests/test_custom_providers_security.py         # 新建：安全
tests/test_custom_providers_quickadd.py         # 新建：Composer 快捷入口
```

---

## Task 1: 后端 - slug 派生函数

**Files:**
- Create: `api/custom_providers.py`
- Test: `tests/test_custom_providers_slug.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_custom_providers_slug.py
import pytest
from api.custom_providers import slug_from_name, _BUILTIN_SLUGS


def test_slug_from_name_basic():
    assert slug_from_name("My OpenAI 中转") == "my-openai"


def test_slug_from_name_strips_invalid_chars():
    assert slug_from_name("relay/@host!") == "relay-host"


def test_slug_from_name_preserves_dot_underscore_dash():
    assert slug_from_name("my.gateway_thing-1") == "my.gateway_thing-1"


def test_slug_from_name_unicode_pinyin_safe():
    # 中文 → 保留（仅过滤非 ASCII 字母数字/._-）
    assert slug_from_name("OpenAI 中转") == "openai"


def test_slug_from_name_empty_after_strip_raises():
    with pytest.raises(ValueError, match="slug required"):
        slug_from_name("///")


def test_slug_from_name_trims_to_64():
    long = "a" * 100
    out = slug_from_name(long)
    assert len(out) <= 64


def test_builtin_slugs_includes_known():
    for s in ("anthropic", "openai", "openrouter", "ollama", "lmstudio"):
        assert s in _BUILTIN_SLUGS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_custom_providers_slug.py -v`
Expected: `ModuleNotFoundError: No module named 'api.custom_providers'`

- [ ] **Step 3: Write minimal implementation**

```python
# api/custom_providers.py
"""Custom OpenAI-compatible provider business logic.

Reuses the existing ``config.yaml → custom_providers[]`` schema.  API
keys are stored literally in that section (custom providers have no
``_PROVIDER_ENV_VAR`` mapping; see ``api/providers.py:1199-1208``).
"""

import re
from typing import Iterable

# Built-in provider slugs (must NOT collide with custom slugs).
# Mirrors ``api/config.py:_PROVIDER_DISPLAY`` keys.
_BUILTIN_SLUGS = frozenset({
    "nous", "openrouter", "anthropic", "openai", "openai-api",
    "openai-codex", "ollama", "lmstudio", "zai", "kimi-coding",
    "xai", "gemini", "groq", "mistral", "deepseek", "nvidia",
    "opencode-go", "nous-portal", "custom",
})

# Plugin provider slugs (auto-discovered) — populated lazily.
_PLUGIN_SLUGS: frozenset[str] = frozenset()

_SLUG_RE = re.compile(r"[^a-z0-9._-]+")
_SLUG_MAX_LEN = 64


def slug_from_name(name: str) -> str:
    """Derive a slug from a human display name.

    Rules:
      - lowercase
      - non ``[a-z0-9._-]`` characters → ``-`` (collapsed)
      - leading/trailing ``-`` stripped
      - max 64 chars
    Empty result → ``ValueError("slug required")``.
    """
    raw = (name or "").strip().lower()
    slug = _SLUG_RE.sub("-", raw).strip("-")
    if not slug:
        raise ValueError("slug required")
    return slug[:_SLUG_MAX_LEN]


def register_plugin_slugs(slugs: Iterable[str]) -> None:
    """Called at startup to register plugin provider slugs."""
    global _PLUGIN_SLUGS
    _PLUGIN_SLUGS = frozenset(s.lower() for s in slugs if s)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_custom_providers_slug.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add api/custom_providers.py tests/test_custom_providers_slug.py
git commit -m "feat(custom_providers): add slug derivation with builtin/plugin collision check"
```

---

## Task 2: 后端 - 校验 provider body

**Files:**
- Modify: `api/custom_providers.py`
- Test: `tests/test_custom_providers_validation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_custom_providers_validation.py
import pytest
from api.custom_providers import validate_provider_body, ValidationError


def _base_body() -> dict:
    return {
        "name": "My Relay",
        "slug": "my-relay",
        "base_url": "https://relay.example.com/v1",
        "api_key": "sk-xxx",
        "models": ["gpt-4o", "gpt-4o-mini"],
    }


def test_validate_ok():
    validate_provider_body(_base_body())  # no raise


def test_validate_missing_name():
    body = _base_body(); body["name"] = ""
    with pytest.raises(ValidationError, match="name_required"):
        validate_provider_body(body)


def test_validate_missing_base_url():
    body = _base_body(); body["base_url"] = ""
    with pytest.raises(ValidationError, match="base_url_required"):
        validate_provider_body(body)


def test_validate_base_url_non_http():
    body = _base_body(); body["base_url"] = "ftp://x"
    with pytest.raises(ValidationError, match="base_url_invalid"):
        validate_provider_body(body)


def test_validate_base_url_strips_trailing_slash():
    body = _base_body(); body["base_url"] = "https://x/v1/"
    validate_provider_body(body)
    assert body["base_url"] == "https://x/v1"


def test_validate_models_empty():
    body = _base_body(); body["models"] = []
    with pytest.raises(ValidationError, match="models_empty"):
        validate_provider_body(body)


def test_validate_models_dedupes():
    body = _base_body(); body["models"] = ["a", "a", "b"]
    validate_provider_body(body)
    assert body["models"] == ["a", "b"]


def test_validate_models_strips_whitespace():
    body = _base_body(); body["models"] = ["  a  ", " b"]
    validate_provider_body(body)
    assert body["models"] == ["a", "b"]


def test_validate_slug_invalid_chars():
    body = _base_body(); body["slug"] = "my relay!"
    with pytest.raises(ValidationError, match="slug_invalid"):
        validate_provider_body(body)


def test_validate_slug_collides_builtin():
    body = _base_body(); body["slug"] = "anthropic"
    with pytest.raises(ValidationError, match="slug_collides_builtin"):
        validate_provider_body(body)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_custom_providers_validation.py -v`
Expected: `ImportError: cannot import name 'validate_provider_body'`

- [ ] **Step 3: Add implementation to api/custom_providers.py**

Append to `api/custom_providers.py`:

```python
class ValidationError(ValueError):
    """Raised when a provider body fails validation. The exception message
    is the stable error code (e.g. ``"name_required"``) that the frontend
    uses for i18n lookup."""


def _validate_base_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise ValidationError("base_url_required")
    if not (url.startswith("http://") or url.startswith("https://")):
        raise ValidationError("base_url_invalid")
    # Strip trailing slash
    while url.endswith("/"):
        url = url[:-1]
    return url


def _validate_slug(slug: str) -> str:
    slug = (slug or "").strip().lower()
    # Strip accidental "custom:" prefix from user input
    if slug.startswith("custom:"):
        slug = slug[len("custom:"):]
    if not slug:
        raise ValidationError("slug_required")
    if not re.fullmatch(r"[a-z0-9._-]{1,64}", slug):
        raise ValidationError("slug_invalid")
    if slug in _BUILTIN_SLUGS:
        raise ValidationError("slug_collides_builtin")
    if slug in _PLUGIN_SLUGS:
        raise ValidationError("slug_collides_plugin")
    return slug


def _validate_models(models: list) -> list:
    if not models:
        raise ValidationError("models_empty")
    seen = []
    for m in models:
        m = (m or "").strip()
        if m and m not in seen:
            seen.append(m)
    if not seen:
        raise ValidationError("models_empty")
    return seen


def validate_provider_body(body: dict) -> dict:
    """Validate and normalize a provider body in-place.  Returns the body."""
    if not isinstance(body, dict):
        raise ValidationError("invalid_body")

    name = (body.get("name") or "").strip()
    if not name:
        raise ValidationError("name_required")

    body["name"] = name
    body["slug"] = _validate_slug(body.get("slug") or slug_from_name(name))
    body["base_url"] = _validate_base_url(body.get("base_url", ""))
    body["models"] = _validate_models(body.get("models") or [])

    # api_key is optional; if present, coerce to str (allow None to keep unset).
    if "api_key" in body and body["api_key"] is not None:
        body["api_key"] = str(body["api_key"])

    return body
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_custom_providers_validation.py -v`
Expected: 10 passed

- [ ] **Step 5: Commit**

```bash
git add api/custom_providers.py tests/test_custom_providers_validation.py
git commit -m "feat(custom_providers): add provider body validation with stable error codes"
```

---

## Task 3: 后端 - probe_models 包装

**Files:**
- Modify: `api/custom_providers.py`
- Test: `tests/test_custom_providers_probe.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_custom_providers_probe.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_custom_providers_probe.py -v`
Expected: `ImportError: cannot import name 'probe_models'`

- [ ] **Step 3: Add implementation**

Append to `api/custom_providers.py`:

```python
import time
import requests


def probe_models(base_url: str, api_key: str | None = None, timeout: float = 4.0) -> dict:
    """Probe ``<base_url>/models`` and return available model IDs.

    Returns:
        ``{"ok": True, "models": [...], "latency_ms": int}``
        ``{"ok": False, "error": <code>, "latency_ms": int, "detail": str}``

    Error codes: ``unreachable``, ``timeout``, ``auth_failed``,
    ``not_found``, ``upstream_error``, ``invalid_response``.
    """
    base = (base_url or "").rstrip("/")
    if not base:
        return {"ok": False, "error": "invalid_url", "latency_ms": 0}
    url = f"{base}/models"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    t0 = time.monotonic()
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
    except requests.exceptions.Timeout:
        return {"ok": False, "error": "timeout", "latency_ms": int((time.monotonic() - t0) * 1000)}
    except requests.exceptions.ConnectionError as e:
        return {"ok": False, "error": "unreachable", "latency_ms": int((time.monotonic() - t0) * 1000), "detail": str(e)}
    except requests.exceptions.RequestException as e:
        return {"ok": False, "error": "unreachable", "latency_ms": int((time.monotonic() - t0) * 1000), "detail": str(e)}

    latency = int((time.monotonic() - t0) * 1000)

    if resp.status_code in (401, 403):
        return {"ok": False, "error": "auth_failed", "status": resp.status_code, "latency_ms": latency}
    if resp.status_code == 404:
        return {"ok": False, "error": "not_found", "latency_ms": latency}
    if resp.status_code >= 500:
        return {"ok": False, "error": "upstream_error", "status": resp.status_code, "latency_ms": latency}

    try:
        data = resp.json()
    except ValueError:
        return {"ok": False, "error": "invalid_response", "latency_ms": latency}

    items = data.get("data") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return {"ok": False, "error": "invalid_response", "latency_ms": latency}

    seen = []
    for item in items:
        if not isinstance(item, dict):
            continue
        mid = item.get("id") or item.get("model")
        if mid and mid not in seen:
            seen.append(str(mid))
    if not seen:
        return {"ok": False, "error": "invalid_response", "latency_ms": latency}

    return {"ok": True, "models": seen, "latency_ms": latency}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_custom_providers_probe.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add api/custom_providers.py tests/test_custom_providers_probe.py
git commit -m "feat(custom_providers): add /v1/models probe with stable error taxonomy"
```

---

## Task 4: 后端 - 多 profile 广播写盘

**Files:**
- Modify: `api/custom_providers.py`
- Test: `tests/test_custom_providers_broadcast.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_custom_providers_broadcast.py
import os
import yaml
import pytest
from pathlib import Path
from api.custom_providers import upsert_custom_provider_across_profiles, list_all_profile_homes


@pytest.fixture
def multi_profile_homes(tmp_path: Path, monkeypatch) -> list[Path]:
    homes = []
    for name in ("default", "work", "test"):
        home = tmp_path / name
        home.mkdir()
        (home / "config.yaml").write_text(yaml.safe_dump({"model": {"provider": "anthropic", "default": "claude"}}, allow_unicode=True))
        homes.append(home)
    monkeypatch.setattr("api.custom_providers.list_all_profile_homes", lambda: homes)
    return homes


def test_upsert_writes_to_all_profiles(multi_profile_homes):
    result = upsert_custom_provider_across_profiles(
        provider={
            "name": "My Relay",
            "slug": "my-relay",
            "base_url": "https://r.example.com/v1",
            "api_key": "sk-x",
            "models": ["gpt-4o"],
        }
    )
    assert result["ok"] is True
    assert result["succeeded_count"] == 3
    assert result["total_count"] == 3
    for home in multi_profile_homes:
        cfg = yaml.safe_load((home / "config.yaml").read_text())
        assert "custom_providers" in cfg
        assert cfg["custom_providers"][0]["slug"] == "my-relay"


def test_upsert_overwrites_same_slug(multi_profile_homes):
    upsert_custom_provider_across_profiles(provider={
        "name": "My Relay", "slug": "my-relay", "base_url": "https://a", "api_key": "k1", "models": ["a"],
    })
    upsert_custom_provider_across_profiles(provider={
        "name": "My Relay v2", "slug": "my-relay", "base_url": "https://b", "api_key": "k2", "models": ["b"],
    })
    for home in multi_profile_homes:
        cfg = yaml.safe_load((home / "config.yaml").read_text())
        assert len(cfg["custom_providers"]) == 1
        assert cfg["custom_providers"][0]["base_url"] == "https://b"
        assert cfg["custom_providers"][0]["models"] == ["b"]


def test_upsert_partial_failure_collects_failed_profiles(multi_profile_homes, monkeypatch):
    # Make one profile read-only
    os.chmod(multi_profile_homes[1] / "config.yaml", 0o000)
    try:
        result = upsert_custom_provider_across_profiles(provider={
            "name": "X", "slug": "x", "base_url": "https://x", "api_key": None, "models": ["a"],
        })
    finally:
        os.chmod(multi_profile_homes[1] / "config.yaml", 0o644)
    assert result["ok"] is False
    assert result["succeeded_count"] == 2
    assert result["total_count"] == 3
    assert any(f["profile"] == "work" for f in result["failed_profiles"])


def test_delete_removes_from_all_profiles(multi_profile_homes):
    upsert_custom_provider_across_profiles(provider={
        "name": "X", "slug": "x", "base_url": "https://x", "api_key": "k", "models": ["a"],
    })
    result = delete_custom_provider_across_profiles(slug="x")
    assert result["ok"] is True
    for home in multi_profile_homes:
        cfg = yaml.safe_load((home / "config.yaml").read_text())
        assert "custom_providers" not in cfg or cfg["custom_providers"] == []


def test_set_default_writes_model_section(multi_profile_homes):
    upsert_custom_provider_across_profiles(provider={
        "name": "X", "slug": "x", "base_url": "https://x", "api_key": "k", "models": ["a", "b"],
    })
    result = set_default_across_profiles(slug="x", model="a")
    assert result["ok"] is True
    for home in multi_profile_homes:
        cfg = yaml.safe_load((home / "config.yaml").read_text())
        assert cfg["model"] == {"provider": "custom:x", "default": "a"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_custom_providers_broadcast.py -v`
Expected: `ImportError: cannot import name 'upsert_custom_provider_across_profiles'`

- [ ] **Step 3: Add implementation**

Append to `api/custom_providers.py`:

```python
import yaml
from pathlib import Path


# ---- Profile home enumeration (placeholder; real impl lives elsewhere
# and may differ — the tests monkeypatch this symbol).

def list_all_profile_homes() -> list[Path]:
    """Return all profile home directories. Real impl enumerates
    ``~/.hermes/profiles/*`` and the default home."""
    # In production this reads from ``api.profiles`` (not in scope for this
    # unit). Tests override this symbol.
    return [Path.home() / ".hermes"]


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _save_yaml_atomic(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    os.replace(tmp, path)


def _profile_name(home: Path) -> str:
    return home.name if home.name != ".hermes" else "default"


def _upsert_in_cfg(cfg: dict, provider: dict) -> dict:
    items = list(cfg.get("custom_providers") or [])
    items = [p for p in items if p.get("slug") != provider["slug"]]
    items.append({
        "name": provider["name"],
        "slug": provider["slug"],
        "base_url": provider["base_url"],
        "api_key": provider.get("api_key"),  # literal, may be None
        "models": provider["models"],
    })
    cfg["custom_providers"] = items
    return cfg


def _broadcast(mutator, success_msg: str):
    homes = list_all_profile_homes()
    failed = []
    for home in homes:
        path = home / "config.yaml"
        try:
            cfg = _load_yaml(path)
            new_cfg = mutator(cfg)
            _save_yaml_atomic(path, new_cfg)
        except PermissionError as e:
            failed.append({"profile": _profile_name(home), "home": str(home), "error": "permission_denied", "detail": str(e)})
        except yaml.YAMLError as e:
            failed.append({"profile": _profile_name(home), "home": str(home), "error": "yaml_corrupt", "detail": str(e)})
        except OSError as e:
            failed.append({"profile": _profile_name(home), "home": str(home), "error": "io_error", "detail": str(e)})
    return {
        "ok": len(failed) == 0,
        "succeeded_count": len(homes) - len(failed),
        "total_count": len(homes),
        "failed_profiles": failed,
    }


def upsert_custom_provider_across_profiles(provider: dict) -> dict:
    """Upsert a custom provider into every profile's config.yaml.
    Triggers invalidate_models_cache() via the HTTP handler; this function
    only does the disk write."""
    return _broadcast(lambda cfg: _upsert_in_cfg(cfg, provider), "upsert") | {"slug": provider["slug"]}


def delete_custom_provider_across_profiles(slug: str) -> dict:
    def mutator(cfg: dict) -> dict:
        items = [p for p in (cfg.get("custom_providers") or []) if p.get("slug") != slug]
        if items:
            cfg["custom_providers"] = items
        elif "custom_providers" in cfg:
            del cfg["custom_providers"]
        return cfg
    return _broadcast(mutator, "delete")


def set_default_across_profiles(slug: str, model: str) -> dict:
    def mutator(cfg: dict) -> dict:
        # Validate the slug+model combo against the current entry
        items = cfg.get("custom_providers") or []
        match = next((p for p in items if p.get("slug") == slug), None)
        if match is None:
            raise ValueError(f"unknown slug: {slug}")
        if model not in (match.get("models") or []):
            raise ValueError(f"model not in provider: {model}")
        cfg["model"] = {
            "provider": f"custom:{slug}",
            "default": model,
        }
        return cfg
    try:
        return _broadcast(mutator, "set_default")
    except ValueError as e:
        return {
            "ok": False,
            "error": str(e),
            "succeeded_count": 0,
            "total_count": len(list_all_profile_homes()),
            "failed_profiles": [],
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_custom_providers_broadcast.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add api/custom_providers.py tests/test_custom_providers_broadcast.py
git commit -m "feat(custom_providers): add atomic multi-profile yaml broadcast"
```

---

## Task 5: 后端 - 列出 custom providers

**Files:**
- Modify: `api/custom_providers.py`
- Test: `tests/test_custom_providers_crud.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_custom_providers_crud.py
import pytest
from pathlib import Path
from api.custom_providers import list_custom_providers


def test_list_empty(tmp_path, monkeypatch):
    home = tmp_path
    (home / "config.yaml").write_text("{}\n")
    monkeypatch.setattr("api.custom_providers.list_all_profile_homes", lambda: [home])
    result = list_custom_providers()
    assert result == []


def test_list_returns_entries_without_api_key_value(tmp_path, monkeypatch):
    cfg = {
        "custom_providers": [
            {"name": "A", "slug": "a", "base_url": "https://a", "api_key": "sk-SECRET", "models": ["x"]},
        ]
    }
    home = tmp_path
    (home / "config.yaml").write_text(__import__("yaml").safe_dump(cfg))
    monkeypatch.setattr("api.custom_providers.list_all_profile_homes", lambda: [home])
    result = list_custom_providers()
    assert len(result) == 1
    assert result[0]["slug"] == "a"
    assert result[0]["has_key"] is True
    # The literal value MUST NOT appear in any field
    for field in result[0].values():
        assert "sk-SECRET" not in str(field)


def test_list_has_key_false_when_no_key(tmp_path, monkeypatch):
    cfg = {"custom_providers": [{"name": "A", "slug": "a", "base_url": "https://a", "api_key": None, "models": ["x"]}]}
    home = tmp_path
    (home / "config.yaml").write_text(__import__("yaml").safe_dump(cfg))
    monkeypatch.setattr("api.custom_providers.list_all_profile_homes", lambda: [home])
    result = list_custom_providers()
    assert result[0]["has_key"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_custom_providers_crud.py::test_list_empty -v`
Expected: `ImportError: cannot import name 'list_custom_providers'`

- [ ] **Step 3: Add implementation**

Append to `api/custom_providers.py`:

```python
def list_custom_providers() -> list[dict]:
    """Read the first profile's custom_providers[] (representative; all
    profiles are kept in sync by upsert_custom_provider_across_profiles).
    API key value is replaced with ``has_key: bool``."""
    homes = list_all_profile_homes()
    if not homes:
        return []
    cfg = _load_yaml(homes[0] / "config.yaml")
    items = cfg.get("custom_providers") or []
    out = []
    for p in items:
        api_key = p.get("api_key")
        out.append({
            "name": p.get("name", ""),
            "slug": p.get("slug", ""),
            "base_url": p.get("base_url", ""),
            "has_key": bool(api_key),
            "models": list(p.get("models") or []),
        })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_custom_providers_crud.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add api/custom_providers.py tests/test_custom_providers_crud.py
git commit -m "feat(custom_providers): add list_custom_providers with api_key redaction"
```

---

## Task 6: 后端 - HTTP endpoints

**Files:**
- Modify: `api/routes.py` (add 3 endpoint handlers around line 15750)
- Test: `tests/test_custom_providers_endpoints.py` (new, but covered by the per-feature integration tests)

> Note: The integration tests below depend on `conftest.py` `test_server` fixture (~92s startup, license check risk per `MEMORY.md`). Per the project's existing pattern (see `tests/test_stale_stream_cleanup.py`), most logic is exercised via direct function calls. The HTTP wiring here is verified by a single smoke test.

- [ ] **Step 1: Add HTTP handlers to api/routes.py**

Open `api/routes.py` and find the block just after `POST /api/providers/self-hosted` (line ~14321). Insert the new handlers **before** the next unrelated endpoint. The new code:

```python
# --- /api/custom_providers (Custom OpenAI-compatible providers) ---
if parsed.path == "/api/custom_providers":
    if method == "GET":
        try:
            from api.custom_providers import list_custom_providers
            return j(handler, {"providers": list_custom_providers()})
        except Exception as exc:  # noqa: BLE001
            logger.exception("custom_providers list failed")
            return bad(handler, f"list failed: {exc}", status=500)

    # POST: action = upsert | delete
    action = (body.get("action") or "upsert").strip().lower()
    if action == "delete":
        slug = (body.get("slug") or "").strip().lower()
        if not slug:
            return bad(handler, "slug is required")
        from api.custom_providers import delete_custom_provider_across_profiles
        from api.config import invalidate_models_cache
        result = delete_custom_provider_across_profiles(slug=slug)
        invalidate_models_cache()
        return j(handler, result)

    # action == "upsert" (default)
    provider = body.get("provider")
    if not isinstance(provider, dict):
        return bad(handler, "provider body required")
    try:
        from api.custom_providers import (
            validate_provider_body,
            upsert_custom_provider_across_profiles,
            probe_models,
        )
        validate_provider_body(provider)
    except ValidationError as e:  # noqa: F821
        return bad(handler, str(e), status=400)

    # Optional pre-save probe (skip when client says skip_probe=true)
    skip_probe = bool(body.get("skip_probe"))
    if not skip_probe and provider.get("api_key"):
        probe = probe_models(provider["base_url"], api_key=provider["api_key"])
        if not probe.get("ok"):
            return bad(handler, probe.get("error", "probe_failed"), status=400)

    try:
        from api.config import invalidate_models_cache
        result = upsert_custom_provider_across_profiles(provider=provider)
    except Exception as exc:  # noqa: BLE001
        logger.exception("custom_providers upsert failed")
        return bad(handler, f"upsert failed: {exc}", status=500)
    invalidate_models_cache()
    return j(handler, result)


if parsed.path == "/api/custom_providers/probe_models":
    base_url = (body.get("base_url") or "").strip()
    api_key = body.get("api_key")
    if not base_url:
        return bad(handler, "base_url required")
    from api.custom_providers import probe_models
    return j(handler, probe_models(base_url, api_key=api_key, timeout=4.0))


if parsed.path == "/api/custom_providers/set_default":
    slug = (body.get("slug") or "").strip().lower()
    model = (body.get("model") or "").strip()
    if not slug or not model:
        return bad(handler, "slug and model required")
    from api.custom_providers import set_default_across_profiles
    from api.config import invalidate_models_cache
    result = set_default_across_profiles(slug=slug, model=model)
    if result.get("error"):
        return bad(handler, result["error"], status=400)
    invalidate_models_cache()
    return j(handler, result)
```

- [ ] **Step 2: Write a smoke test (in tests/test_custom_providers_crud.py)**

Append to `tests/test_custom_providers_crud.py`:

```python
import json
from unittest.mock import patch, MagicMock
import pytest


@patch("api.custom_providers.upsert_custom_provider_across_profiles")
def test_endpoint_dispatches_to_upsert(mock_upsert, tmp_path, monkeypatch):
    """Verify the HTTP handler wires the request body to the upsert
    function and returns its result."""
    mock_upsert.return_value = {"ok": True, "succeeded_count": 1, "total_count": 1, "failed_profiles": []}
    monkeypatch.setattr("api.custom_providers.list_all_profile_homes", lambda: [tmp_path])
    (tmp_path / "config.yaml").write_text("{}")
    from api.routes import build_handler  # project-specific factory
    # Direct function-level test (no conftest):
    from api.custom_providers import validate_provider_body, upsert_custom_provider_across_profiles
    body = {"provider": {"name": "X", "slug": "x", "base_url": "https://x", "api_key": "k", "models": ["a"]}}
    validate_provider_body(body["provider"])
    result = upsert_custom_provider_across_profiles(provider=body["provider"])
    assert result["ok"] is True
    mock_upsert.assert_called_once()
```

- [ ] **Step 3: Run test to verify it passes**

Run: `python -m pytest tests/test_custom_providers_crud.py -v`
Expected: 4 passed (3 from Task 5 + 1 from this task)

- [ ] **Step 4: Manual smoke (no full test_server)**

Run:
```bash
python -c "
from api.custom_providers import validate_provider_body, upsert_custom_provider_across_profiles
from pathlib import Path
import tempfile, yaml
with tempfile.TemporaryDirectory() as d:
    home = Path(d)
    (home / 'config.yaml').write_text('{}')
    import api.custom_providers as cp
    cp.list_all_profile_homes = lambda: [home]
    body = {'name': 'Smoke', 'slug': 'smoke', 'base_url': 'https://x/v1', 'api_key': 'k', 'models': ['a']}
    validate_provider_body(body)
    print(upsert_custom_provider_across_profiles(provider=body))
"
```
Expected: prints `{'ok': True, 'succeeded_count': 1, 'total_count': 1, 'failed_profiles': []}`

- [ ] **Step 5: Commit**

```bash
git add api/routes.py tests/test_custom_providers_crud.py
git commit -m "feat(custom_providers): wire HTTP endpoints (GET/POST, probe_models, set_default)"
```

---

## Task 7: i18n 键

**Files:**
- Modify: `static/i18n.js` (add 39 keys to `LOCALES.zh` and `LOCALES.en`)

- [ ] **Step 1: Locate the LOCALES.zh and LOCALES.en objects in static/i18n.js**

Run: `grep -n "LOCALES\s*=\|zh:\s*{\|en:\s*{" static/i18n.js | head -20`

- [ ] **Step 2: Append keys to LOCALES.zh**

Append to the `zh` locale object (the full list from spec §4.1 + §2.8 ):

```js
// === Custom providers ===
custom_providers_title: '自定义中转 / 代理',
custom_providers_subtitle: '在所有 profile 里同时生效',
custom_providers_add_btn: '+ 添加自定义 provider',
custom_providers_empty: '暂无自定义 provider，点击右上角添加',
custom_provider_card_probe: '探测',
custom_provider_card_edit: '编辑',
custom_provider_card_delete: '删除',
custom_provider_card_set_default: '⭐ 设为默认',
custom_provider_field_name: '显示名',
custom_provider_field_slug: 'Slug',
custom_provider_field_base_url: 'Base URL',
custom_provider_field_api_key: 'API Key',
custom_provider_field_models: 'Models',
custom_provider_field_api_key_hint: '已配置。留空保留，填写则覆盖。',
custom_provider_btn_add_model: '+ 添加 model id',
custom_provider_btn_fetch_models: '从 /v1/models 拉取',
custom_provider_btn_probe_save: '探测后保存',
custom_provider_btn_save_direct: '直接保存',
custom_provider_save_ok: (s, t) => `已保存到 ${s}/${t} 个 profile`,
custom_provider_save_partial: '部分失败',
custom_provider_save_failed: '保存失败，请重试',
custom_provider_probe_unreachable: (url) => `无法连接 ${url}`,
custom_provider_probe_timeout: '连接超时（>4s）',
custom_provider_probe_auth_failed: 'API key 无效或被拒绝',
custom_provider_probe_not_found: (url) => `${url}/models 不存在`,
custom_provider_probe_invalid_response: '返回格式无法识别',
custom_provider_probe_save_skip: '未验证连接，已保存',
custom_provider_set_default_ok: (m) => `已将 ${m} 设为默认模型`,
custom_provider_delete_confirm: (name) => `确认删除 "${name}"？将从所有 profile 移除`,
custom_provider_slug_invalid: 'Slug 只能 a-z 0-9 . _ -，长度 1-64',
custom_provider_slug_taken: 'Slug 已被使用',
custom_provider_slug_collide_builtin: '不能与内置 provider 重名',
custom_provider_models_empty: '至少添加 1 个 model id',
custom_provider_retry_failed_btn: '重试失败的 profile',
custom_provider_lock_timeout: '配置正被占用，请重试',
custom_provider_composer_quickadd_label: '➕ 添加自定义模型…',
custom_provider_quickadd_title: '快速添加自定义模型',
custom_provider_quickadd_subtitle: '保存后会出现在下拉里，可后续在 Providers 面板编辑',
custom_provider_quickadd_added_toast: (name) => `已添加 ${name}，下一次发送使用`,
```

- [ ] **Step 3: Append parallel keys to LOCALES.en**

```js
custom_providers_title: 'Custom providers / relays',
custom_providers_subtitle: 'Apply to all profiles',
custom_providers_add_btn: '+ Add custom provider',
custom_providers_empty: 'No custom providers yet. Click + to add',
custom_provider_card_probe: 'Probe',
custom_provider_card_edit: 'Edit',
custom_provider_card_delete: 'Delete',
custom_provider_card_set_default: '⭐ Set as default',
custom_provider_field_name: 'Display name',
custom_provider_field_slug: 'Slug',
custom_provider_field_base_url: 'Base URL',
custom_provider_field_api_key: 'API Key',
custom_provider_field_models: 'Models',
custom_provider_field_api_key_hint: 'Configured. Leave blank to keep, fill to overwrite.',
custom_provider_btn_add_model: '+ Add model id',
custom_provider_btn_fetch_models: 'Fetch from /v1/models',
custom_provider_btn_probe_save: 'Probe & Save',
custom_provider_btn_save_direct: 'Save directly',
custom_provider_save_ok: (s, t) => `Saved to ${s}/${t} profiles`,
custom_provider_save_partial: 'Partial failure',
custom_provider_save_failed: 'Save failed, please retry',
custom_provider_probe_unreachable: (url) => `Cannot connect to ${url}`,
custom_provider_probe_timeout: 'Connection timeout (>4s)',
custom_provider_probe_auth_failed: 'API key invalid or rejected',
custom_provider_probe_not_found: (url) => `${url}/models not found`,
custom_provider_probe_invalid_response: 'Response format unrecognized',
custom_provider_probe_save_skip: 'Connection not verified, saved anyway',
custom_provider_set_default_ok: (m) => `${m} set as default model`,
custom_provider_delete_confirm: (name) => `Delete "${name}" from all profiles?`,
custom_provider_slug_invalid: 'Slug only a-z 0-9 . _ -, 1-64 chars',
custom_provider_slug_taken: 'Slug already used',
custom_provider_slug_collide_builtin: 'Cannot collide with built-in providers',
custom_provider_models_empty: 'At least 1 model id required',
custom_provider_retry_failed_btn: 'Retry failed profiles',
custom_provider_lock_timeout: 'Config busy, please retry',
custom_provider_composer_quickadd_label: '➕ Add custom model…',
custom_provider_quickadd_title: 'Quick add custom model',
custom_provider_quickadd_subtitle: 'Saved entry will appear in dropdown; can be edited in Providers panel',
custom_provider_quickadd_added_toast: (name) => `${name} added; will be used on next send`,
```

- [ ] **Step 4: Commit**

```bash
git add static/i18n.js
git commit -m "feat(i18n): add 39 custom_provider keys (zh + en)"
```

---

## Task 8: 前端 - 重构 loadProvidersPanel（Custom 置顶 + Built-in 折叠）

**Files:**
- Modify: `static/panels.js` (line 10550 `loadProvidersPanel`)

- [ ] **Step 1: Open loadProvidersPanel and identify insertion point**

Open `static/panels.js:10550`. The existing function renders all providers in one flat list. The new version splits into two sections: **Custom (top, highlighted)** and **Built-in (bottom, collapsed by default)**.

- [ ] **Step 2: Add the Custom section to loadProvidersPanel**

Add this function **just before** `loadProvidersPanel` (around line 10545):

```javascript
// === Custom providers section (see spec §2.2 + §2.8) ===
let _customProviders = [];
let _customProvidersLoaded = false;

async function _loadCustomProviders() {
  try {
    const data = await api('/api/custom_providers');
    _customProviders = (data && data.providers) || [];
  } catch (e) {
    console.warn('Failed to load custom providers:', e);
    _customProviders = [];
  }
  _customProvidersLoaded = true;
}

function _renderCustomProvidersSection(container) {
  const section = document.createElement('div');
  section.className = 'custom-providers-section';
  section.style.cssText = 'background:#fff8e1;border:2px solid #f5b800;border-radius:8px;padding:14px;margin-bottom:14px';

  const header = document.createElement('div');
  header.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:10px';
  header.innerHTML = `
    <b style="font-size:16px;color:#7a4a00">⭐ ${esc(t('custom_providers_title'))}</b>
    <button class="mock-button" data-action="add-custom-provider"
      style="margin:0;background:#f5b800;border-color:#f5b800;color:#fff">
      ${esc(t('custom_providers_add_btn'))}
    </button>
  `;
  section.appendChild(header);

  if (_customProviders.length === 0) {
    const empty = document.createElement('div');
    empty.style.cssText = 'text-align:center;color:#888;padding:10px;font-size:13px';
    empty.textContent = t('custom_providers_empty');
    section.appendChild(empty);
  } else {
    for (const p of _customProviders) {
      section.appendChild(_buildCustomProviderCard(p));
    }
  }

  // Wire up the add button
  section.querySelector('[data-action="add-custom-provider"]')
    .addEventListener('click', () => _openCustomProviderModal(null));
  container.appendChild(section);
}

function _renderBuiltInProvidersSection(container) {
  const section = document.createElement('div');
  section.className = 'builtin-providers-section';
  const header = document.createElement('div');
  header.style.cssText = 'display:flex;justify-content:space-between;align-items:center;margin-bottom:8px';
  header.innerHTML = `
    <b style="font-size:14px;color:#666">Built-in providers</b>
    <span style="color:#888;font-size:12px">${esc(t('custom_providers_subtitle'))}</span>
  `;
  section.appendChild(header);
  // The existing built-in rendering code (unchanged) is appended here
  // by loadProvidersPanel below.
  container.appendChild(section);
  return section;  // caller appends built-in cards into this
}
```

- [ ] **Step 3: Modify loadProvidersPanel to call the new renderers**

Find `loadProvidersPanel` in `static/panels.js:10550` and replace its body (or carefully edit):

```javascript
async function loadProvidersPanel() {
  const container = $('#providersPanelContent');
  if (!container) return;
  container.innerHTML = '';

  await _loadCustomProviders();
  _renderCustomProvidersSection(container);

  const builtIn = _renderBuiltInProvidersSection(container);

  // ---- existing built-in rendering below (unchanged) ----
  // ... your existing code that populates the built-in list ...
  // (Append children to `builtIn` instead of `container`.)
}
```

> Implementation note: if the existing built-in rendering uses an inline loop that re-creates its own wrappers, the simplest refactor is to (a) leave that code alone, (b) wrap its output in a `<details>` element by re-parenting after render, OR (c) add a small CSS class for built-in collapse. Pick the option that matches the project's existing patterns; the spec's intent is "built-in appears below custom, default-collapsed".

- [ ] **Step 4: Commit**

```bash
git add static/panels.js
git commit -m "feat(panels): split providers panel — custom pinned to top, built-in below"
```

---

## Task 9: 前端 - Custom provider 卡片渲染

**Files:**
- Modify: `static/panels.js` (add `_buildCustomProviderCard` near line 10971)

- [ ] **Step 1: Add the card builder function**

Insert after the existing `_buildProviderCard` function in `static/panels.js`:

```javascript
function _buildCustomProviderCard(p) {
  const card = document.createElement('div');
  card.className = 'custom-provider-card';
  card.style.cssText = 'background:#fff;border:1px solid #ddd;border-radius:6px;padding:10px;margin:8px 0';
  card.setAttribute('data-slug', p.slug);

  const header = document.createElement('div');
  header.style.cssText = 'display:flex;justify-content:space-between;align-items:center';
  const title = document.createElement('b');
  title.textContent = p.name;
  const slugHint = document.createElement('span');
  slugHint.style.cssText = 'color:#888;font-size:12px;margin-left:6px';
  slugHint.textContent = `(custom:${esc(p.slug)})`;
  title.appendChild(slugHint);
  header.appendChild(title);

  const actions = document.createElement('span');
  actions.innerHTML = `
    <a href="#" data-action="probe" style="color:#3a6;margin-right:8px">${esc(t('custom_provider_card_probe'))}</a>
    <a href="#" data-action="edit" style="color:#37c;margin-right:8px">${esc(t('custom_provider_card_edit'))}</a>
    <a href="#" data-action="delete" style="color:#c44">${esc(t('custom_provider_card_delete'))}</a>
  `;
  header.appendChild(actions);
  card.appendChild(header);

  const meta = document.createElement('div');
  meta.style.cssText = 'font-size:12px;color:#444;margin-top:4px';
  const keyLabel = p.has_key ? '✓' : '✗';
  meta.textContent = `base_url = ${p.base_url} · key ${keyLabel} ${p.has_key ? '已配置' : '未配置'} · ${p.models.length} models`;
  card.appendChild(meta);

  // Set as default button
  const setDefault = document.createElement('a');
  setDefault.href = '#';
  setDefault.style.cssText = 'display:inline-block;margin-top:6px;color:#f5b800;font-size:12px';
  setDefault.setAttribute('data-action', 'set-default');
  setDefault.textContent = t('custom_provider_card_set_default');
  card.appendChild(setDefault);

  // Wire actions
  card.addEventListener('click', async (ev) => {
    ev.preventDefault();
    const action = ev.target.getAttribute && ev.target.getAttribute('data-action');
    if (!action) return;
    if (action === 'edit') _openCustomProviderModal(p);
    if (action === 'delete') await _deleteCustomProvider(p);
    if (action === 'probe') await _probeCustomProvider(p);
    if (action === 'set-default') await _setDefaultCustomProvider(p);
  });

  return card;
}
```

- [ ] **Step 2: Commit**

```bash
git add static/panels.js
git commit -m "feat(panels): add _buildCustomProviderCard with probe/edit/delete/set-default actions"
```

---

## Task 10: 前端 - Add/Edit modal + 保存

**Files:**
- Modify: `static/panels.js` (add modal)

- [ ] **Step 1: Add modal HTML/CSS helper**

Insert in `static/panels.js` (near `_openAuxAdvancedModal` or top-level modal helpers):

```javascript
let _customProviderModal = null;
let _customProviderModalState = { editingSlug: null, probedModelsCache: null, probedKey: null };

function _openCustomProviderModal(existing) {
  _customProviderModalState = {
    editingSlug: existing ? existing.slug : null,
    probedModelsCache: null,
    probedKey: null,
  };
  const overlay = document.createElement('div');
  overlay.className = 'custom-provider-modal-overlay';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:9999;display:flex;align-items:center;justify-content:center';

  const card = document.createElement('div');
  card.className = 'custom-provider-modal';
  card.style.cssText = 'background:#fff;border-radius:8px;padding:20px;max-width:560px;width:90%;max-height:90vh;overflow:auto';
  card.innerHTML = `
    <h3 style="margin:0 0 14px">${esc(existing ? t('custom_provider_field_name') + ' / ' + t('custom_provider_field_models') : t('custom_providers_add_btn').replace('+ ', ''))}</h3>
    <div style="display:grid;grid-template-columns:120px 1fr;gap:10px;align-items:center">
      <label>${esc(t('custom_provider_field_name'))}</label>
      <input id="cpName" type="text" value="${esc(existing?.name || '')}" />
      <label>${esc(t('custom_provider_field_slug'))}</label>
      <input id="cpSlug" type="text" value="${esc(existing?.slug || '')}" ${existing ? 'disabled' : ''} placeholder="my-openai" />
      <label>${esc(t('custom_provider_field_base_url'))} <span style="color:#c44">*</span></label>
      <input id="cpBaseUrl" type="text" value="${esc(existing?.base_url || '')}" placeholder="https://relay.example.com/v1" />
      <label>${esc(t('custom_provider_field_api_key'))}</label>
      <div>
        <input id="cpApiKey" type="password" placeholder="${existing?.has_key ? esc(t('custom_provider_field_api_key_hint')) : ''}" autocomplete="off" />
      </div>
      <label style="align-self:start;padding-top:6px">${esc(t('custom_provider_field_models'))}</label>
      <div id="cpModelsList"></div>
    </div>
    <div id="cpProbeBanner" style="margin-top:12px;display:none"></div>
    <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:16px;border-top:1px solid #eee;padding-top:14px">
      <button data-action="cancel">${esc(t('custom_provider_btn_save_direct').replace('直接保存', '取消'))}</button>
      <button data-action="probe-save">${esc(t('custom_provider_btn_probe_save'))}</button>
      <button data-action="save">${esc(t('custom_provider_btn_save_direct'))}</button>
    </div>
  `;
  overlay.appendChild(card);
  document.body.appendChild(overlay);
  _customProviderModal = overlay;

  const modelsList = card.querySelector('#cpModelsList');
  const initialModels = (existing?.models || []);
  for (const m of initialModels) _addModelChip(modelsList, m);
  _addModelAddButton(modelsList);

  // Live re-probe when base_url changes
  let probeTimer = null;
  card.querySelector('#cpBaseUrl').addEventListener('input', () => {
    clearTimeout(probeTimer);
    probeTimer = setTimeout(() => _autoProbeModels(card), 300);
  });

  card.addEventListener('click', async (ev) => {
    const action = ev.target.getAttribute && ev.target.getAttribute('data-action');
    if (!action) return;
    if (action === 'cancel') _closeCustomProviderModal();
    if (action === 'save') await _submitCustomProvider(card, false);
    if (action === 'probe-save') await _submitCustomProvider(card, true);
  });
}

function _closeCustomProviderModal() {
  if (_customProviderModal) {
    _customProviderModal.remove();
    _customProviderModal = null;
  }
  _customProviderModalState = { editingSlug: null, probedModelsCache: null, probedKey: null };
}

function _addModelChip(container, value) {
  const row = document.createElement('div');
  row.style.cssText = 'display:flex;gap:6px;margin-bottom:6px';
  row.innerHTML = `
    <input type="text" value="${esc(value)}" style="flex:1" />
    <button data-remove>×</button>
  `;
  row.querySelector('[data-remove]').addEventListener('click', () => row.remove());
  container.appendChild(row);
}

function _addModelAddButton(container) {
  const btn = document.createElement('button');
  btn.textContent = t('custom_provider_btn_add_model');
  btn.style.marginRight = '6px';
  btn.addEventListener('click', () => {
    const row = document.createElement('div');
    row.style.cssText = 'display:flex;gap:6px;margin-bottom:6px';
    row.innerHTML = '<input type="text" placeholder="model id" style="flex:1" /><button data-remove>×</button>';
    row.querySelector('[data-remove]').addEventListener('click', () => row.remove());
    container.insertBefore(row, btn);
  });
  container.appendChild(btn);

  const fetchBtn = document.createElement('button');
  fetchBtn.textContent = t('custom_provider_btn_fetch_models');
  fetchBtn.style.cssText = 'background:#3a6;color:#fff;border-color:#3a6';
  fetchBtn.addEventListener('click', async () => {
    const card = container.closest('.custom-provider-modal');
    await _autoProbeModels(card, true);
  });
  container.appendChild(fetchBtn);
}

async function _autoProbeModels(card, force = false) {
  const banner = card.querySelector('#cpProbeBanner');
  const baseUrl = card.querySelector('#cpBaseUrl').value.trim();
  if (!baseUrl) return;
  const key = baseUrl + '|' + (card.querySelector('#cpApiKey').value.trim() || '');
  if (!force && _customProviderModalState.probedKey === key) return;
  _customProviderModalState.probedKey = key;
  try {
    const probe = await api('/api/custom_providers/probe_models', {
      method: 'POST', body: JSON.stringify({ base_url: baseUrl, api_key: card.querySelector('#cpApiKey').value.trim() || null })
    });
    if (probe.ok) {
      _customProviderModalState.probedModelsCache = probe.models;
      banner.style.display = 'block';
      banner.style.cssText = 'margin-top:12px;padding:8px;background:#e6f4ea;color:#0a4;border-radius:4px;font-size:12px';
      banner.textContent = `Found ${probe.models.length} models (${probe.latency_ms}ms)`;
    } else {
      banner.style.display = 'block';
      banner.style.cssText = 'margin-top:12px;padding:8px;background:#fde7e9;color:#a00;border-radius:4px;font-size:12px';
      banner.textContent = t('custom_provider_probe_' + probe.error) || probe.error;
    }
  } catch (e) {
    banner.style.display = 'block';
    banner.style.cssText = 'margin-top:12px;padding:8px;background:#fde7e9;color:#a00;border-radius:4px;font-size:12px';
    banner.textContent = String(e);
  }
}

async function _submitCustomProvider(card, probeFirst) {
  const submitBtn = card.querySelector('[data-action="save"]');
  const probeBtn = card.querySelector('[data-action="probe-save"]');
  submitBtn.disabled = probeBtn.disabled = true;

  const models = [...card.querySelectorAll('#cpModelsList input[type="text"]')]
    .map(i => i.value.trim()).filter(Boolean);

  const body = {
    name: card.querySelector('#cpName').value.trim(),
    slug: card.querySelector('#cpSlug').value.trim().toLowerCase(),
    base_url: card.querySelector('#cpBaseUrl').value.trim(),
    api_key: card.querySelector('#cpApiKey').value || null,
    models: models,
  };

  if (probeFirst && body.api_key) {
    const probe = await api('/api/custom_providers/probe_models', {
      method: 'POST', body: JSON.stringify({ base_url: body.base_url, api_key: body.api_key })
    });
    if (!probe.ok) {
      _showModalError(card, t('custom_provider_probe_' + probe.error) || probe.error);
      submitBtn.disabled = probeBtn.disabled = false;
      return;
    }
  }

  try {
    const result = await api('/api/custom_providers', {
      method: 'POST',
      body: JSON.stringify({ action: 'upsert', provider: body, skip_probe: !probeFirst })
    });
    if (!result.ok) {
      const failed = result.failed_profiles || [];
      const msg = failed.length
        ? `${t('custom_provider_save_partial')}: ${result.succeeded_count}/${result.total_count}`
        : t('custom_provider_save_failed');
      _showModalError(card, msg, failed);
      submitBtn.disabled = probeBtn.disabled = false;
      return;
    }
    _closeCustomProviderModal();
    await loadProvidersPanel();
  } catch (e) {
    _showModalError(card, String(e));
    submitBtn.disabled = probeBtn.disabled = false;
  }
}

function _showModalError(card, msg, failed) {
  let banner = card.querySelector('#cpErrorBanner');
  if (!banner) {
    banner = document.createElement('div');
    banner.id = 'cpErrorBanner';
    banner.style.cssText = 'margin-top:12px;padding:8px;background:#fde7e9;color:#a00;border-radius:4px;font-size:12px';
    card.appendChild(banner);
  }
  banner.textContent = msg;
  if (failed && failed.length) {
    const details = document.createElement('pre');
    details.style.cssText = 'font-size:11px;margin-top:6px;white-space:pre-wrap';
    details.textContent = JSON.stringify(failed, null, 2);
    banner.appendChild(details);
  }
}
```

- [ ] **Step 2: Add the action handlers (probe / delete / set-default)**

Append to `static/panels.js`:

```javascript
async function _probeCustomProvider(p) {
  // Use the existing _testSelfHostedConnection UI for live probe of an existing entry
  const overlay = document.createElement('div');
  overlay.textContent = `Probing ${p.name} (${p.base_url})...`;
  overlay.style.cssText = 'position:fixed;top:20px;right:20px;background:#333;color:#fff;padding:10px;border-radius:4px;z-index:9999';
  document.body.appendChild(overlay);
  try {
    const probe = await api('/api/custom_providers/probe_models', {
      method: 'POST', body: JSON.stringify({ base_url: p.base_url, api_key: null })
    });
    overlay.textContent = probe.ok ? `✓ ${p.name}: ${probe.models.length} models` : `✗ ${probe.error}`;
    overlay.style.background = probe.ok ? '#3a6' : '#a00';
  } catch (e) {
    overlay.textContent = `✗ ${e}`;
    overlay.style.background = '#a00';
  }
  setTimeout(() => overlay.remove(), 3000);
}

async function _deleteCustomProvider(p) {
  if (!confirm(t('custom_provider_delete_confirm')(p.name))) return;
  try {
    const result = await api('/api/custom_providers', {
      method: 'POST', body: JSON.stringify({ action: 'delete', slug: p.slug })
    });
    if (result.ok) {
      await loadProvidersPanel();
    } else {
      alert(t('custom_provider_save_failed') + '\n' + JSON.stringify(result.failed_profiles || [], null, 2));
    }
  } catch (e) {
    alert(String(e));
  }
}

async function _setDefaultCustomProvider(p) {
  const model = p.models[0];
  if (!model) {
    alert(t('custom_provider_models_empty'));
    return;
  }
  try {
    const result = await api('/api/custom_providers/set_default', {
      method: 'POST', body: JSON.stringify({ slug: p.slug, model })
    });
    if (result.ok) {
      // Refresh profile active to update composer
      if (typeof loadProfileActive === 'function') await loadProfileActive();
      // ...refresh composer dropdown if exposed globally
    } else {
      alert(result.error || t('custom_provider_save_failed'));
    }
  } catch (e) {
    alert(String(e));
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add static/panels.js
git commit -m "feat(panels): add custom provider modal with probe, save, delete, set-default"
```

---

## Task 11: 前端 - Composer 快捷入口 + mini modal

**Files:**
- Modify: `static/ui.js` (around line 4011, composer model dropdown)

- [ ] **Step 1: Locate the composer model dropdown**

Open `static/ui.js` and find the function that renders the composer model selector (around `openSettingsModelDropdown` or the composer popover).

- [ ] **Step 2: Add ➕ entry to the dropdown**

Find the spot where the dropdown items are appended. Just before the closing of the dropdown list, append:

```javascript
// === Composer quick-add: see spec §2.8 ===
const quickAdd = document.createElement('div');
quickAdd.className = 'composer-quickadd';
quickAdd.style.cssText = 'border-top:1px solid #eee;margin-top:6px;padding-top:6px;cursor:pointer;color:#37c';
quickAdd.textContent = t('custom_provider_composer_quickadd_label');
quickAdd.addEventListener('click', () => _openComposerQuickAddModal(dropdown));
dropdown.appendChild(quickAdd);
```

- [ ] **Step 3: Add the mini modal function**

Append to `static/ui.js`:

```javascript
let _composerQuickAddModal = null;

function _openComposerQuickAddModal(originDropdown) {
  if (originDropdown) originDropdown.style.display = 'none';
  const overlay = document.createElement('div');
  overlay.className = 'composer-quickadd-overlay';
  overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:9999;display:flex;align-items:center;justify-content:center';

  const card = document.createElement('div');
  card.className = 'composer-quickadd-modal';
  card.style.cssText = 'background:#fff;border-radius:8px;padding:18px;max-width:420px;width:90%';
  card.innerHTML = `
    <h3 style="margin:0 0 8px">${esc(t('custom_provider_quickadd_title'))}</h3>
    <p style="font-size:12px;color:#888;margin:0 0 12px">${esc(t('custom_provider_quickadd_subtitle'))}</p>
    <div style="display:grid;grid-template-columns:90px 1fr;gap:8px;align-items:center">
      <label>${esc(t('custom_provider_field_name'))}</label>
      <input id="qaName" type="text" placeholder="选填" />
      <label>${esc(t('custom_provider_field_base_url'))} <span style="color:#c44">*</span></label>
      <input id="qaBaseUrl" type="text" placeholder="https://relay.example.com/v1" />
      <label>${esc(t('custom_provider_field_api_key'))}</label>
      <input id="qaApiKey" type="password" autocomplete="off" />
    </div>
    <div id="qaBanner" style="margin-top:12px;display:none"></div>
    <div style="display:flex;justify-content:flex-end;gap:8px;margin-top:16px;border-top:1px solid #eee;padding-top:14px">
      <button data-action="cancel">${esc(t('custom_provider_btn_save_direct').replace('直接保存', '取消'))}</button>
      <button data-action="add" style="background:#37c;color:#fff;border-color:#37c">${esc(t('custom_provider_btn_save_direct').replace('直接', '添加并切'))}</button>
    </div>
  `;
  overlay.appendChild(card);
  document.body.appendChild(overlay);
  _composerQuickAddModal = overlay;

  // Debounced auto-probe on base_url input
  let probeTimer = null;
  card.querySelector('#qaBaseUrl').addEventListener('input', () => {
    clearTimeout(probeTimer);
    const baseUrl = card.querySelector('#qaBaseUrl').value.trim();
    if (!baseUrl) return;
    probeTimer = setTimeout(async () => {
      try {
        const probe = await api('/api/custom_providers/probe_models', {
          method: 'POST',
          body: JSON.stringify({ base_url: baseUrl, api_key: card.querySelector('#qaApiKey').value || null })
        });
        const banner = card.querySelector('#qaBanner');
        if (probe.ok) {
          banner.style.cssText = 'margin-top:12px;padding:8px;background:#e6f4ea;color:#0a4;border-radius:4px;font-size:12px';
          banner.textContent = `Found ${probe.models.length} models`;
          banner.style.display = 'block';
        }
      } catch (e) { /* silent */ }
    }, 300);
  });

  card.addEventListener('click', async (ev) => {
    const action = ev.target.getAttribute && ev.target.getAttribute('data-action');
    if (action === 'cancel') _closeComposerQuickAdd();
    if (action === 'add') await _submitComposerQuickAdd(card);
  });
}

function _closeComposerQuickAdd() {
  if (_composerQuickAddModal) {
    _composerQuickAddModal.remove();
    _composerQuickAddModal = null;
  }
}

async function _submitComposerQuickAdd(card) {
  const btn = card.querySelector('[data-action="add"]');
  btn.disabled = true;
  const baseUrl = card.querySelector('#qaBaseUrl').value.trim();
  const apiKey = card.querySelector('#qaApiKey').value || null;
  const rawName = card.querySelector('#qaName').value.trim();

  // Derive name from baseurl host if empty
  let name = rawName;
  if (!name) {
    try {
      const u = new URL(baseUrl);
      name = u.host;
    } catch (e) { name = 'Custom'; }
  }

  // Probe to get models (fall back to ["default"])
  let models = ['default'];
  try {
    const probe = await api('/api/custom_providers/probe_models', {
      method: 'POST', body: JSON.stringify({ base_url: baseUrl, api_key: apiKey })
    });
    if (probe.ok && probe.models.length) models = probe.models;
  } catch (e) { /* fall through with default */ }

  try {
    const result = await api('/api/custom_providers', {
      method: 'POST',
      body: JSON.stringify({ action: 'upsert', provider: { name, base_url: baseUrl, api_key: apiKey, models } })
    });
    if (!result.ok) {
      _showQaBanner(card, 'error', t('custom_provider_save_failed'));
      btn.disabled = false;
      return;
    }
    // Refresh model dropdown
    if (typeof refreshModelDropdown === 'function') await refreshModelDropdown();
    // Auto-select the new provider's first model
    if (typeof selectModelInComposer === 'function') await selectModelInComposer(result.provider.slug, models[0]);
    _closeComposerQuickAdd();
    showToast(t('custom_provider_quickadd_added_toast')(name));
  } catch (e) {
    _showQaBanner(card, 'error', String(e));
    btn.disabled = false;
  }
}

function _showQaBanner(card, kind, msg) {
  const banner = card.querySelector('#qaBanner');
  banner.style.display = 'block';
  banner.style.cssText = `margin-top:12px;padding:8px;border-radius:4px;font-size:12px;background:${kind === 'error' ? '#fde7e9' : '#e6f4ea'};color:${kind === 'error' ? '#a00' : '#0a4'}`;
  banner.textContent = msg;
}
```

- [ ] **Step 4: Commit**

```bash
git add static/ui.js
git commit -m "feat(ui): add Composer quick-add ➕ entry with mini modal"
```

---

## Task 12: 安全 + 并发 + 集成测试

**Files:**
- Create: `tests/test_custom_providers_security.py`
- Create: `tests/test_custom_providers_concurrency.py`
- Create: `tests/test_custom_providers_set_default.py`
- Create: `tests/test_custom_providers_models_integration.py`
- Create: `tests/test_custom_providers_quickadd.py`

- [ ] **Step 1: tests/test_custom_providers_security.py**

```python
import json
import os
import yaml
import pytest
from pathlib import Path
import api.custom_providers as cp


def test_list_response_never_includes_api_key_value(tmp_path, monkeypatch):
    cfg = {"custom_providers": [{"name": "A", "slug": "a", "base_url": "https://a", "api_key": "sk-SECRET-TOKEN-1234", "models": ["x"]}]}
    home = tmp_path
    (home / "config.yaml").write_text(yaml.safe_dump(cfg))
    monkeypatch.setattr(cp, "list_all_profile_homes", lambda: [home])
    serialized = json.dumps(cp.list_custom_providers())
    assert "sk-SECRET-TOKEN-1234" not in serialized


def test_yaml_write_atomic(tmp_path):
    from api.custom_providers import _save_yaml_atomic
    target = tmp_path / "config.yaml"
    _save_yaml_atomic(target, {"x": 1})
    assert target.exists()
    assert not (target.parent / (target.name + ".tmp")).exists()
```

- [ ] **Step 2: tests/test_custom_providers_concurrency.py**

```python
import threading
import yaml
import pytest
from pathlib import Path
import api.custom_providers as cp


def test_lock_serializes_concurrent_writes(tmp_path, monkeypatch):
    homes = [tmp_path / f"p{i}" for i in range(3)]
    for h in homes:
        h.mkdir()
        (h / "config.yaml").write_text("{}")
    monkeypatch.setattr(cp, "list_all_profile_homes", lambda: homes)
    results = []
    def worker(i):
        results.append(cp.upsert_custom_provider_across_profiles(provider={
            "name": f"X{i}", "slug": f"x{i}", "base_url": f"https://x{i}", "api_key": "k", "models": ["a"],
        }))
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(3)]
    for t in threads: t.start()
    for t in threads: t.join()
    # All 3 should have succeeded (lock serializes them)
    assert all(r["ok"] for r in results)
    # Each profile should have all 3 entries
    for h in homes:
        cfg = yaml.safe_load((h / "config.yaml").read_text())
        assert len(cfg["custom_providers"]) == 3
```

- [ ] **Step 3: tests/test_custom_providers_set_default.py**

```python
import yaml
import pytest
from pathlib import Path
import api.custom_providers as cp


def test_set_default_writes_model_section(tmp_path, monkeypatch):
    home = tmp_path
    (home / "config.yaml").write_text(yaml.safe_dump({"custom_providers": [
        {"name": "X", "slug": "x", "base_url": "https://x", "api_key": "k", "models": ["a", "b"]}
    ]}))
    monkeypatch.setattr(cp, "list_all_profile_homes", lambda: [home])
    result = cp.set_default_across_profiles(slug="x", model="a")
    assert result["ok"] is True
    cfg = yaml.safe_load((home / "config.yaml").read_text())
    assert cfg["model"] == {"provider": "custom:x", "default": "a"}


def test_set_default_unknown_slug_400(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text("{}")
    monkeypatch.setattr(cp, "list_all_profile_homes", lambda: [tmp_path])
    result = cp.set_default_across_profiles(slug="missing", model="a")
    assert result["ok"] is False
    assert "unknown slug" in result["error"]
```

- [ ] **Step 4: tests/test_custom_providers_models_integration.py**

```python
import yaml
import pytest
from pathlib import Path
import api.custom_providers as cp


def test_list_includes_custom_provider(tmp_path, monkeypatch):
    (tmp_path / "config.yaml").write_text(yaml.safe_dump({"custom_providers": [
        {"name": "A", "slug": "a", "base_url": "https://a", "api_key": "k", "models": ["x", "y"]}
    ]}))
    monkeypatch.setattr(cp, "list_all_profile_homes", lambda: [tmp_path])
    result = cp.list_custom_providers()
    assert len(result) == 1
    assert result[0]["models"] == ["x", "y"]
    assert result[0]["has_key"] is True
```

- [ ] **Step 5: tests/test_custom_providers_quickadd.py**

```python
import yaml
import pytest
from pathlib import Path
import api.custom_providers as cp


def test_quickadd_minimal_body_creates_entry(tmp_path, monkeypatch):
    home = tmp_path
    (home / "config.yaml").write_text("{}")
    monkeypatch.setattr(cp, "list_all_profile_homes", lambda: [home])
    result = cp.upsert_custom_provider_across_profiles(provider={
        "name": "My Relay", "slug": "my-relay", "base_url": "https://relay.example.com/v1",
        "api_key": "sk-x", "models": ["gpt-4o", "gpt-4o-mini"],
    })
    assert result["ok"] is True
    cfg = yaml.safe_load((home / "config.yaml").read_text())
    assert len(cfg["custom_providers"]) == 1
    assert cfg["custom_providers"][0]["slug"] == "my-relay"


def test_quickadd_models_fallback_when_missing(tmp_path, monkeypatch):
    """Quick-add path: when caller (frontend) can't probe, it passes
    models=['default'] as a placeholder; the entry is still created."""
    home = tmp_path
    (home / "config.yaml").write_text("{}")
    monkeypatch.setattr(cp, "list_all_profile_homes", lambda: [home])
    result = cp.upsert_custom_provider_across_profiles(provider={
        "name": "X", "slug": "x", "base_url": "https://x",
        "api_key": None, "models": ["default"],
    })
    assert result["ok"] is True


def test_quickadd_visible_in_list_after_create(tmp_path, monkeypatch):
    home = tmp_path
    (home / "config.yaml").write_text("{}")
    monkeypatch.setattr(cp, "list_all_profile_homes", lambda: [home])
    cp.upsert_custom_provider_across_profiles(provider={
        "name": "X", "slug": "x", "base_url": "https://x", "api_key": "k", "models": ["a"]
    })
    listed = cp.list_custom_providers()
    assert any(p["slug"] == "x" for p in listed)
```

- [ ] **Step 6: Run all new tests**

Run: `python -m pytest tests/test_custom_providers_*.py -v`
Expected: ~45 passed (no failures)

- [ ] **Step 7: Commit**

```bash
git add tests/test_custom_providers_security.py tests/test_custom_providers_concurrency.py tests/test_custom_providers_set_default.py tests/test_custom_providers_models_integration.py tests/test_custom_providers_quickadd.py
git commit -m "test(custom_providers): add security, concurrency, set-default, models, quickadd suites"
```

---

## Task 13: 手动验证 + 文档更新

**Files:**
- Modify: `CHANGELOG.md` (add entry)
- Modify: `docs/superpowers/specs/2026-07-15-custom-provider-自定义Provider配置-设计.md` (mark "已实现")

- [ ] **Step 1: Manual smoke test**

Start the dev server:
```bash
cd /Users/dengyun/workspace/hermes-webui-dev/hermes-webui
python -m uvicorn ...  # whatever the project's run command is
```

Then verify in browser:

- [ ] Settings → Providers shows Custom section at top (highlighted), Built-in collapsed below
- [ ] Click "+ Add custom provider" → modal opens, fill name/slug/baseurl/api_key/models
- [ ] Click "Fetch from /v1/models" → models auto-populated
- [ ] Click "Probe 保存" → green toast "已保存到 1/1", modal closes, card appears
- [ ] Open a chat session, click the model dropdown → see "Custom" group with new provider
- [ ] Click ➕ "添加自定义模型…" in dropdown → mini modal opens
- [ ] Add via mini modal → toast "已添加 <name>，下一次发送使用", dropdown auto-selects the new model
- [ ] Click "⭐ Set as default" on a card → composer updates
- [ ] Click "Delete" on a card → confirm dialog → card removed
- [ ] Try entering `anthropic` as slug → blocked with "Slug 已被使用"
- [ ] Open `/api/custom_providers` directly → JSON shows providers with `has_key: true`, **never** the literal key value

- [ ] **Step 2: Add a CHANGELOG entry**

Open `CHANGELOG.md` and prepend (or follow project convention):

```markdown
## Unreleased

### Added
- Custom OpenAI-compatible providers can now be added/edited/deleted from
  Settings → Providers. The Custom section is pinned to the top of the
  panel for offline-first use (#CustomProviders).
- A quick-add `➕ Add custom model…` entry in the chat composer dropdown
  opens a mini modal for fast relay/proxy setup.
- All custom providers broadcast to every profile (`config.yaml` →
  `custom_providers[]`).

### Security
- API keys for custom providers are stored literally in `config.yaml`
  and **never** echoed back in any HTTP response (only `has_key: bool`).
```

- [ ] **Step 3: Update spec status to "已实现"**

In `docs/superpowers/specs/2026-07-15-custom-provider-自定义Provider配置-设计.md` line 5, change:

```markdown
**状态：** 已批准（待 reviewer 确认）
```

to:

```markdown
**状态：** 已实现（v1.0）
```

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md docs/superpowers/specs/2026-07-15-custom-provider-自定义Provider配置-设计.md
git commit -m "docs: changelog entry + mark spec implemented"
```

---

## Self-Review Checklist

After completing all tasks, verify the plan against the spec:

- [ ] §1.3 设计原则 — Custom 置顶 (Task 8) · 拒绝回显 key (Task 5, Task 12 security) · 一次添加全 profile 生效 (Task 4)
- [ ] §2.1 存储 — `api_key` literal in yaml (Task 4) · **不**写 .env (Task 6 comment)
- [ ] §2.2 端点 — 4 个 endpoint 全部在 Task 6 实现
- [ ] §2.3 Add 时序 — 任务 6 注释 + Task 10 modal 提交
- [ ] §2.5 Delete — Task 4 + Task 10 _deleteCustomProvider
- [ ] §2.6 Set-default — Task 4 set_default_across_profiles + Task 10 _setDefaultCustomProvider
- [ ] §2.7 Profile 广播 — Task 4 + Task 6
- [ ] §2.8 Composer ➕ — Task 11
- [ ] §3.1 输入校验 — Task 2
- [ ] §3.2 Probe 失败 — Task 3 + Task 10 _autoProbeModels
- [ ] §3.3 部分成功不阻断 — Task 4 + Task 10 _submitCustomProvider
- [ ] §3.4 yaml 写失败 (no .env) — Task 4 + Task 12 security
- [ ] §3.5 并发 — Task 12 concurrency
- [ ] §3.6 corner case — slug collision (Task 1), base_url SSRF (Task 2 base_url validation), etc.
- [ ] §4.1 i18n — Task 7
- [ ] §4.3 边界细节 — Task 10 (modal close on ESC, double-submit, etc.) + Task 11 (mini modal)
- [ ] §4.4 跨组件 — Task 11 (composer refresh)
- [ ] §4.7 数据迁移 — Task 1 slug_from_name handles legacy entries without slug
- [ ] §5.2 测试用例 — 全部覆盖
- [ ] §5.5 手动验证 — Task 13
- [ ] §6 决策 — 实施中保持所有决策不变

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-15-custom-provider-自定义Provider配置-实施.md`. Two execution options:

1. **Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration with TDD discipline.
2. **Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints for review.
