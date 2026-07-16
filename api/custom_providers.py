"""Custom OpenAI-compatible provider business logic.

Reuses the existing ``config.yaml → custom_providers[]`` schema.  API
keys are stored literally in that section (custom providers have no
``_PROVIDER_ENV_VAR`` mapping; see ``api/providers.py:1199-1208``).
"""

import re
from collections.abc import Iterable

# Built-in provider slugs (must NOT collide with custom slugs).
# Subset of common built-in slugs sourced from ``api/config.py:_PROVIDER_DISPLAY``
# / ``_PROVIDER_MODELS``. NOT a full mirror — intentionally curated to the
# names the custom-provider UI is known to clash with (see
# ``tests/test_custom_providers_slug.py::test_builtin_slugs_includes_known``).
# Any future slug added here must NOT change behavior; if you intend to
# reserve a new name, add a regression test alongside it.
_BUILTIN_SLUGS: frozenset[str] = frozenset({
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

    Note: ``name`` is the user-facing display name, not a provider id;
    the ``custom:`` prefix is added separately by the caller.
    """
    raw = (name or "").strip().lower()
    # ``sub`` may have introduced leading/trailing dashes (e.g. "---" →
    # "---" before collapsing, or non-ASCII edges); trim them.
    slug = _SLUG_RE.sub("-", raw).strip("-")
    if not slug:
        raise ValueError("slug required")
    return slug[:_SLUG_MAX_LEN]


def register_plugin_slugs(slugs: Iterable[str]) -> None:
    """Called at startup to register plugin provider slugs."""
    global _PLUGIN_SLUGS
    _PLUGIN_SLUGS = frozenset(s.lower() for s in slugs if s)


# === Validation (Task 2) ================================================


class ValidationError(ValueError):
    """Raised when a provider body fails validation.

    The exception message is the stable error code (e.g.
    ``"name_required"``) that the frontend uses for i18n lookup.
    """


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


# === Probe (Task 3) =====================================================

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


# === Broadcast writes (Task 4) ===========================================
#
# Imports kept inside this section per the append-only discipline enforced
# after Task 3 review (do not promote one-off imports to the top-of-file
# block).  ``yaml`` and ``os`` are first-introduced here; ``Path`` is also
# first used here.
import os
import yaml as _yaml
from pathlib import Path


def list_all_profile_homes() -> list[Path]:
    """Return all profile home directories.

    Real implementation enumerates ``~/.hermes/profiles/*`` and the default
    home.  Tests override this via ``monkeypatch.setattr`` (see
    ``tests/test_custom_providers_broadcast.py::multi_profile_homes``).
    """
    # Placeholder; production wiring is out of scope for this unit.
    return [Path.home() / ".hermes"]


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return _yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _save_yaml_atomic(path: Path, data: dict) -> None:
    """Atomic yaml write via tmp + os.replace. Cleans up the tmp on failure."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp.write_text(_yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        # Replace failed (cross-device, IsADirectoryError, etc.); don't leave a stray .tmp
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _profile_name(home: Path) -> str:
    return home.name if home.name != ".hermes" else "default"


def _upsert_in_cfg(cfg: dict, provider: dict) -> dict:
    items = list(cfg.get("custom_providers") or [])
    items = [p for p in items if p.get("slug") != provider["slug"]]
    items.append(
        {
            "name": provider["name"],
            "slug": provider["slug"],
            "base_url": provider["base_url"],
            "api_key": provider.get("api_key"),
            "models": provider["models"],
        }
    )
    cfg["custom_providers"] = items
    return cfg


def _broadcast(mutator) -> dict:
    """Run ``mutator(cfg) → cfg`` against every profile's ``config.yaml``.

    Returns a result dict with ``ok``, ``succeeded_count``, ``total_count``,
    ``failed_profiles``.  Per-profile failures are collected, not raised,
    so a single read-only profile doesn't abort the whole broadcast.
    """
    homes = list_all_profile_homes()
    failed = []
    for home in homes:
        path = home / "config.yaml"
        try:
            cfg = _load_yaml(path)
            new_cfg = mutator(cfg)
            _save_yaml_atomic(path, new_cfg)
        except PermissionError as e:
            failed.append(
                {
                    "profile": _profile_name(home),
                    "home": str(home),
                    "error": "permission_denied",
                    "detail": str(e),
                }
            )
        except _yaml.YAMLError as e:
            failed.append(
                {
                    "profile": _profile_name(home),
                    "home": str(home),
                    "error": "yaml_corrupt",
                    "detail": str(e),
                }
            )
        except OSError as e:
            failed.append(
                {
                    "profile": _profile_name(home),
                    "home": str(home),
                    "error": "io_error",
                    "detail": str(e),
                }
            )
    return {
        "ok": len(failed) == 0,
        "succeeded_count": len(homes) - len(failed),
        "total_count": len(homes),
        "failed_profiles": failed,
    }


def upsert_custom_provider_across_profiles(provider: dict) -> dict:
    """Upsert a custom provider into every profile's ``config.yaml``.

    Returns a broadcast result that includes ``slug`` for callers
    (e.g., the composer quick-add modal needs it to auto-select the new
    model after save).  Same-slug upserts overwrite the existing entry
    in-place rather than appending a duplicate.
    """
    result = _broadcast(lambda cfg: _upsert_in_cfg(cfg, provider))
    result["slug"] = provider["slug"]
    return result


def delete_custom_provider_across_profiles(slug: str) -> dict:
    """Remove a custom provider from every profile's ``config.yaml``.

    Idempotent: a profile that doesn't contain the slug is left untouched
    (the mutator returns the same ``cfg``), and the broadcast reports
    ``ok=True`` with no failed profiles.
    """
    def mutator(cfg: dict) -> dict:
        items = [p for p in (cfg.get("custom_providers") or []) if p.get("slug") != slug]
        if items:
            cfg["custom_providers"] = items
        elif "custom_providers" in cfg:
            del cfg["custom_providers"]
        return cfg
    return _broadcast(mutator)


def set_default_across_profiles(slug: str, model: str) -> dict:
    """Set ``model`` as the default for provider ``slug`` across profiles.

    Writes the ``model: { provider: 'custom:<slug>', default: <model> }``
    block.  Refuses (returns ``ok=False``) if the slug is unknown or if
    ``model`` is not in the provider's ``models`` list — those checks
    raise ``ValueError`` which the wrapper translates into a failed result
    so the broadcast itself can still report per-profile I/O outcomes.
    """
    def mutator(cfg: dict) -> dict:
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
        return _broadcast(mutator)
    except ValueError as e:
        return {
            "ok": False,
            "error": str(e),
            "succeeded_count": 0,
            "total_count": len(list_all_profile_homes()),
            "failed_profiles": [],
        }


# === List (Task 5) ======================================================


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
