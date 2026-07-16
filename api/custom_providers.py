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
