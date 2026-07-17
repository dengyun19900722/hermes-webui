"""Regression test for the cold live-rebuild budget default (#ZKREQ-135).

The cold live provider-catalog rebuild has a hard wall-clock budget so a
flaky upstream probe (Copilot urllib timeout=10s, OpenRouter /v1/models,
Nous /models, ...) can't block the request thread for tens of seconds.

User reported the default 4.0s budget was too long for first-page-load
perceived speed. Lowered to 1.5s so first paint falls back to the
last-known disk cache / network-free catalog quickly on cold start.

Override via HERMES_WEBUI_MODELS_REBUILD_BUDGET (or 0 to restore the
legacy synchronous unbounded behaviour). This test pins the 1.5s default
so it doesn't silently regress.
"""

from __future__ import annotations

import importlib

import pytest


def test_default_rebuild_budget_is_one_and_a_half_seconds():
    """The default budget for a cold live provider-catalog rebuild must be
    1.5s — fast enough that a flaky probe doesn't make first paint feel
    sluggish, while still leaving room for a single round-trip on a healthy
    network."""
    import api.config as cfg_mod

    # The constant is read at module import time, so it reflects the
    # default encoded in source (or the env var override at import).
    assert cfg_mod._LIVE_REBUILD_BUDGET_SECONDS == pytest.approx(1.5), (
        f"default cold rebuild budget drifted from 1.5s to "
        f"{cfg_mod._LIVE_REBUILD_BUDGET_SECONDS}s — update this test if a "
        f"new default is intentional"
    )


def test_rebuild_budget_env_var_can_disable_budget():
    """Setting HERMES_WEBUI_MODELS_REBUILD_BUDGET=0 must restore the legacy
    synchronous unbounded behaviour (the budget branch is short-circuited)."""
    import os

    old = os.environ.pop("HERMES_WEBUI_MODELS_REBUILD_BUDGET", None)
    os.environ["HERMES_WEBUI_MODELS_REBUILD_BUDGET"] = "0"
    try:
        # Reload the module so the env var is read fresh at import time.
        import api.config as cfg_mod

        importlib.reload(cfg_mod)
        assert cfg_mod._LIVE_REBUILD_BUDGET_SECONDS == 0, (
            "HERMES_WEBUI_MODELS_REBUILD_BUDGET=0 must disable the budget"
        )
    finally:
        if old is None:
            os.environ.pop("HERMES_WEBUI_MODELS_REBUILD_BUDGET", None)
        else:
            os.environ["HERMES_WEBUI_MODELS_REBUILD_BUDGET"] = old
        # Restore the module to its default state for downstream tests.
        importlib.reload(cfg_mod)


def test_rebuild_budget_env_var_override_takes_effect():
    """Non-zero env values must override the default."""
    import os

    old = os.environ.pop("HERMES_WEBUI_MODELS_REBUILD_BUDGET", None)
    os.environ["HERMES_WEBUI_MODELS_REBUILD_BUDGET"] = "2.5"
    try:
        import api.config as cfg_mod

        importlib.reload(cfg_mod)
        assert cfg_mod._LIVE_REBUILD_BUDGET_SECONDS == pytest.approx(2.5)
    finally:
        if old is None:
            os.environ.pop("HERMES_WEBUI_MODELS_REBUILD_BUDGET", None)
        else:
            os.environ["HERMES_WEBUI_MODELS_REBUILD_BUDGET"] = old
        importlib.reload(cfg_mod)