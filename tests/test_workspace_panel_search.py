"""Regression coverage for the Workspaces panel name search."""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
INDEX_HTML = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
PANELS_JS = (ROOT / "static" / "panels.js").read_text(encoding="utf-8")
I18N_JS = (ROOT / "static" / "i18n.js").read_text(encoding="utf-8")
NODE = shutil.which("node")


node_test = pytest.mark.skipif(NODE is None, reason="node not on PATH")


def _extract_function(source: str, name: str) -> str:
    marker = f"function {name}("
    start = source.find(marker)
    assert start >= 0, f"{name}() must exist"
    brace = source.find("{", source.find(")", start))
    assert brace > start, f"{name}() body must start"
    depth = 0
    in_string = None
    escaped = False
    for idx in range(brace, len(source)):
        ch = source[idx]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == in_string:
                in_string = None
            continue
        if ch in ("'", '"', "`"):
            in_string = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return source[start:idx + 1]
    raise AssertionError(f"could not extract {name}()")


def test_workspace_panel_has_name_search_input():
    assert 'id="workspaceSearchInput"' in INDEX_HTML
    assert 'data-i18n-placeholder="workspace_search_placeholder"' in INDEX_HTML
    assert 'oninput="filterWorkspacePanel(this.value)"' in INDEX_HTML
    assert INDEX_HTML.find('id="workspaceSearchInput"') < INDEX_HTML.find('id="workspacesPanel"')


@node_test
def test_workspace_search_matches_name_only():
    matcher = _extract_function(PANELS_JS, "_workspaceNameMatchesSearch")
    script = textwrap.dedent(
        f"""
        {matcher}
        const rows = [
          _workspaceNameMatchesSearch({{name:'Production Ops', path:'/srv/prod'}}, 'ops'),
          _workspaceNameMatchesSearch({{name:'Production Ops', path:'/srv/prod'}}, 'production'),
          _workspaceNameMatchesSearch({{name:'Audit Lab', path:'/srv/prod'}}, 'prod'),
        ];
        process.stdout.write(JSON.stringify(rows));
        """
    )
    result = subprocess.run(
        [NODE, "-e", script],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert json.loads(result.stdout) == [True, True, False]


def test_render_filters_visible_rows_without_mutating_workspace_source():
    assert "const allWorkspaces=Array.isArray(workspaces)?workspaces:[];" in PANELS_JS
    assert "const visibleWorkspaces=searchQuery" in PANELS_JS
    assert "? allWorkspaces.filter(w=>_workspaceNameMatchesSearch(w, searchQuery))" in PANELS_JS
    assert "const currentPaths = allWorkspaces.map(ws => ws.path);" in PANELS_JS
    assert "const refreshed = allWorkspaces.find(w => w.path === _currentWorkspaceDetail.path);" in PANELS_JS


def test_auth_change_clears_workspace_search_state():
    reset_idx = PANELS_JS.find("function _resetWorkspaceStateForAuthChange()")
    assert reset_idx >= 0
    reset_body = PANELS_JS[reset_idx:reset_idx + 800]
    assert "_workspaceSearchQuery = '';" in reset_body
    assert "if(searchInput) searchInput.value='';" in reset_body


def test_workspace_search_empty_state_and_i18n_exist():
    assert "workspace_search_no_results" in PANELS_JS
    assert "workspace_search_placeholder:" in I18N_JS
    assert "workspace_search_no_results:" in I18N_JS
    assert I18N_JS.count("workspace_search_placeholder:") >= 2
    assert I18N_JS.count("workspace_search_no_results:") >= 2
