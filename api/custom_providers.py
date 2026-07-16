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
