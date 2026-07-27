"""Regression test for the composer dropdown not refreshing after upsert.

When the user saves a new custom provider (or edits/deletes one), the chat
composer's model picker must reflect the change the next time it's opened.
The fix has two pieces:

1. ``_refreshComposerModelCatalog`` (panels.js) nulls the cached
   ``_modelDropdownReady`` promise and re-invokes ``_ensureModelDropdownReady``
   to force a fresh ``/api/models`` fetch after every upsert/delete/set-default.

2. ``toggleModelDropdown`` (ui.js) MUST ``await`` the ready promise before
   calling ``renderModelDropdown()``. Otherwise the dropdown renders from the
   stale <select> while the populate fetch is still in flight, and the new
   provider doesn't appear (the original bug reported in production:
   "保存后页面没刷新，看不到新加的模型").

This file pins both pieces so the bug can't silently regress.
"""

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
UI_JS = (ROOT / "static" / "ui.js").read_text(encoding="utf-8")
PANELS_JS = (ROOT / "static" / "panels.js").read_text(encoding="utf-8")


def _extract_function(src: str, name: str) -> str:
    """Extract the body of a top-level function declaration ``name(...)``."""
    pattern = re.compile(rf"function\s+{re.escape(name)}\s*\([^)]*\)\s*\{{", re.MULTILINE)
    m = pattern.search(src)
    if not m:
        raise AssertionError(f"function {name} not found")
    start = m.end()
    depth, i = 1, start
    while i < len(src) and depth > 0:
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
        i += 1
    return src[start : i - 1]


# ---------------------------------------------------------------------------
# 1. panels.js: _refreshComposerModelCatalog must bust the cache and trigger a
#    fresh fetch.
# ---------------------------------------------------------------------------

def test_refresh_composer_model_catalog_busts_cache():
    """``_refreshComposerModelCatalog`` must null ``window._modelDropdownReady``
    so the next ``_ensureModelDropdownReady()`` call actually re-fetches."""
    body = _extract_function(PANELS_JS, "_refreshComposerModelCatalog")
    assert "window._modelDropdownReady = null" in body or \
        "window._modelDropdownReady=null" in body, (
        "_refreshComposerModelCatalog must clear the cached dropdown promise "
        "before re-invoking _ensureModelDropdownReady"
    )
    assert "window._ensureModelDropdownReady" in body, (
        "_refreshComposerModelCatalog must call _ensureModelDropdownReady"
    )


def test_refresh_composer_model_catalog_called_after_upsert():
    """Every upsert success branch must trigger _refreshComposerModelCatalog
    so the chat composer picks up the new provider."""
    # Search for the call site rather than the function definition so we know
    # it's actually invoked from the save flow.
    assert "_refreshComposerModelCatalog()" in PANELS_JS, (
        "_refreshComposerModelCatalog() must be invoked from panels.js"
    )
    # The call should appear AFTER the upsert POST (so the server cache has
    # been invalidated by then). We just count how many call sites exist — if
    # fewer than 3 (upsert, delete, set_default), something regressed.
    occurrences = PANELS_JS.count("_refreshComposerModelCatalog()")
    assert occurrences >= 3, (
        f"expected _refreshComposerModelCatalog() in upsert/delete/set-default "
        f"call sites; got {occurrences}"
    )


# ---------------------------------------------------------------------------
# 2. ui.js: toggleModelDropdown must await the ready promise.
# ---------------------------------------------------------------------------

def test_toggle_model_dropdown_awaits_ready_promise():
    """toggleModelDropdown MUST ``await`` the _ensureModelDropdownReady()
    promise before renderModelDropdown(), otherwise the visible picker reads
    from the stale <select> while /api/models is still in flight."""
    body = _extract_function(UI_JS, "toggleModelDropdown")
    assert "_ensureModelDropdownReady" in body, \
        "toggleModelDropdown must invoke _ensureModelDropdownReady"
    # The bug was: `const ready=window._ensureModelDropdownReady(); ... .catch(...)`
    # with NO `await`. The fix is to await the promise so renderModelDropdown
    # sees fresh data.
    has_await = re.search(r"\bawait\s+ready\b|\bawait\s+window\._ensureModelDropdownReady\b",
                          body) is not None
    assert has_await, (
        "toggleModelDropdown must `await` the _ensureModelDropdownReady() "
        "promise before calling renderModelDropdown, otherwise the visible "
        "picker shows stale data while /api/models is in flight (#WebUI "
        "custom-model-config refresh regression)"
    )


def test_toggle_model_dropdown_renders_after_await():
    """renderModelDropdown() must be called AFTER the awaited populate so it
    picks up the fresh optgroups."""
    body = _extract_function(UI_JS, "toggleModelDropdown")
    # Strip line + block comments first so we measure positions in the same
    # string and skip doc-comment mentions.
    code_only = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
    code_only = re.sub(r"//[^\n]*", "", code_only)
    await_match = re.search(r"\bawait\s+(?:ready|window\._ensureModelDropdownReady)", code_only)
    assert await_match, "expected `await ready` or `await window._ensureModelDropdownReady`"
    render_match = re.search(r"\brenderModelDropdown\s*\(", code_only)
    assert render_match, "expected renderModelDropdown() call"
    assert await_match.start() < render_match.start(), (
        f"renderModelDropdown() must come AFTER the await of "
        f"_ensureModelDropdownReady() (await@{await_match.start()}, "
        f"render@{render_match.start()})"
    )