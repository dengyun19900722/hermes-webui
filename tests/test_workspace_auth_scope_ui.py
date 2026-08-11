"""Static contracts for cross-account workspace response isolation."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_workspace_loader_rejects_stale_auth_scope():
    panels = (ROOT / "static" / "panels.js").read_text(encoding="utf-8")
    assert "_workspaceAuthGeneration" in panels
    assert "responseScope!==currentScope" in panels
    assert "generation!==_workspaceAuthGeneration" in panels
    assert "api('/api/workspaces',{cache:'no-store'})" in panels


def test_auth_reset_invalidates_inflight_workspace_requests():
    panels = (ROOT / "static" / "panels.js").read_text(encoding="utf-8")
    start = panels.index("function _resetWorkspaceStateForAuthChange()")
    body = panels[start : start + 300]
    assert "_workspaceAuthGeneration++" in body


def test_bfcache_restore_refetches_workspace_scope():
    boot = (ROOT / "static" / "boot.js").read_text(encoding="utf-8")
    start = boot.index("window.addEventListener('pageshow'")
    body = boot[start : start + 1400]
    assert "await loadWorkspaceList()" in body
