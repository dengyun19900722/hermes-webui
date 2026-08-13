"""Task 8: verify loadProvidersPanel is split into Custom (top) + Built-in (below).

We have no JS test runner, so this is a static structural check of
static/panels.js: it asserts the new helper functions exist, that
loadProvidersPanel wires them up in the right order, that the built-in list
excludes is_custom providers, and that the new section class names are present.

Run with: pytest --noconftest tests/test_load_providers_split.py -v
"""

import os
import re
import json
import shutil
import subprocess

from tests.js_source_extract import extract_function

PANELS = os.path.join(os.path.dirname(__file__), "..", "static", "panels.js")
NODE = shutil.which("node")


def _read():
    with open(PANELS, encoding="utf-8") as f:
        return f.read()


def test_render_custom_providers_section_defined():
    js = _read()
    assert "function _renderCustomProvidersSection(" in js


def test_render_builtin_providers_section_defined():
    js = _read()
    assert "function _renderBuiltInProvidersSection(" in js


def test_load_custom_providers_defined():
    js = _read()
    assert "function _loadCustomProviders(" in js


def test_load_providers_panel_calls_new_renderers():
    body = extract_function(_read(), "loadProvidersPanel", prefix="async function")
    assert "_loadCustomProviders(" in body
    assert "_renderCustomProvidersSection(" in body
    assert "_renderBuiltInProvidersSection(" in body


def test_load_providers_panel_ordering():
    body = extract_function(_read(), "loadProvidersPanel", prefix="async function")
    load_pos = body.find("_loadCustomProviders(")
    custom_pos = body.find("_renderCustomProvidersSection(")
    builtin_pos = body.find("_renderBuiltInProvidersSection(")
    assert load_pos >= 0 and custom_pos >= 0 and builtin_pos >= 0
    assert load_pos < custom_pos < builtin_pos, (
        f"expected order load({load_pos}) < custom({custom_pos}) < builtin({builtin_pos})"
    )


def test_builtin_list_excludes_custom():
    body = extract_function(_read(), "loadProvidersPanel", prefix="async function")
    assert re.search(r"filter\(\s*p\s*=>\s*!p\.is_custom", body), (
        "built-in provider filter must exclude is_custom"
    )


def test_new_section_class_names_present():
    js = _read()
    assert "custom-providers-section" in js
    assert "builtin-providers-section" in js


def test_builtin_cards_still_use_build_provider_card():
    body = extract_function(_read(), "loadProvidersPanel", prefix="async function")
    assert "_buildProviderCard(p)" in body


def test_builtin_section_uses_details_element():
    """Plan §2.2: Built-in section should be wrapped in a <details> element
    so it collapses by default. Verify the helper creates a <details> tag."""
    body = extract_function(_read(), "_renderBuiltInProvidersSection", prefix="function")
    assert "details" in body, "Built-in section helper must use a <details> element"
    # Also verify .open=false (collapsed by default)
    assert ".open = false" in body or "open=false" in body, (
        "Built-in <details> should default to collapsed"
    )


def test_providers_panel_renders_loading_shell_before_fetch():
    body = extract_function(_read(), "loadProvidersPanel", prefix="async function")
    shell_pos = body.find("_renderProvidersPanelShell(list, empty)")
    fetch_pos = body.find("await api('/api/providers')")
    assert shell_pos >= 0 and fetch_pos >= 0
    assert shell_pos < fetch_pos
    assert "const seq=++_providersPanelLoadSeq" in body
    assert body.count("seq!==_providersPanelLoadSeq") >= 3


def test_provider_quota_no_longer_blocks_initial_provider_cards():
    body = extract_function(_read(), "loadProvidersPanel", prefix="async function")
    assert "const quota=await _fetchProviderQuotaStatus(false)" not in body
    assert "const quotaPromise=_fetchProviderQuotaStatus(false)" in body
    assert "_renderProviderQuotaIntoSection(builtIn, quota)" in body
    assert "quotaPromise.catch(()=>{});" in body


def test_settings_search_index_does_not_await_lazy_provider_panes():
    body = extract_function(_read(), "_buildSettingsIndex", prefix="async function")
    assert "await Promise.all([loadProvidersPanel(), loadPluginsPanel(), loadExtensionsPanel()])" not in body
    assert "_warmSettingsLazyPanes();" in body
    warmup = extract_function(_read(), "_warmSettingsLazyPanes", prefix="function")
    assert "Promise.allSettled" in warmup
    assert "loadProvidersPanel()" in warmup
    assert "_settingsLazyPaneWarmupPromise" in warmup


def test_settings_open_does_not_eagerly_load_slow_integration_panes():
    body = extract_function(_read(), "loadSettingsPanel", prefix="async function")
    assert "loadProvidersPanel(); // load provider cards in background" not in body
    assert "loadPluginsPanel(); // load plugin/hook visibility in background" not in body
    assert "loadExtensionsPanel(); // load extension diagnostics in background" not in body
    assert "switchSettingsSection(_settingsSection);" in body


def test_load_providers_panel_completes_when_quota_request_never_resolves(tmp_path):
    if NODE is None:
        return
    js = "\n".join([
        "let _providersPanelLoadSeq = 0;",
        "const _providerCardEls = new Map();",
        extract_function(_read(), "_renderProvidersPanelShell", prefix="function"),
        extract_function(_read(), "_providerQuotaFallback", prefix="function"),
        extract_function(_read(), "loadProvidersPanel", prefix="async function"),
    ])
    fn_path = tmp_path / "providersPanel.js"
    fn_path.write_text(js, encoding="utf-8")
    driver = r"""
const fs = require('fs');

class FakeElement {
  constructor(tagName = 'div') {
    this.tagName = tagName;
    this.children = [];
    this.parentElement = null;
    this.style = {};
    this.className = '';
    this.textContent = '';
    this.isConnected = true;
  }
  set innerHTML(value) {
    this._innerHTML = String(value || '');
    if (!this._innerHTML) this.children = [];
  }
  get innerHTML() {
    return this._innerHTML || '';
  }
  appendChild(child) {
    child.parentElement = this;
    child.isConnected = true;
    this.children.push(child);
    return child;
  }
  prepend(child) {
    child.parentElement = this;
    child.isConnected = true;
    this.children.unshift(child);
    return child;
  }
  querySelectorAll(selector) {
    const out = [];
    const wanted = selector.startsWith('.') ? selector.slice(1) : selector;
    const walk = (node) => {
      for (const child of node.children || []) {
        if (String(child.className || '').split(/\s+/).includes(wanted)) out.push(child);
        walk(child);
      }
    };
    walk(this);
    return out;
  }
}

const elements = {
  providersList: new FakeElement('div'),
  providersEmpty: new FakeElement('div'),
};
globalThis.document = { createElement: (tag) => new FakeElement(tag) };
globalThis.$ = (id) => elements[id] || null;
globalThis.t = (key) => ({
  providers_refreshing: 'Refreshing...',
  provider_quota_unavailable: 'Quota unavailable',
})[key] || key;
globalThis.esc = (value) => String(value == null ? '' : value);

const calls = [];
globalThis.api = async (url) => {
  calls.push(url);
  if (url === '/api/providers') {
    return { providers: [{ id: 'openai', configurable: true, is_custom: false }] };
  }
  throw new Error('unexpected api call: ' + url);
};
globalThis._loadCustomProviders = async () => { calls.push('/api/custom_providers'); };
globalThis._renderCustomProvidersSection = (list) => {
  const el = new FakeElement('div');
  el.className = 'custom-providers-section';
  list.appendChild(el);
};
globalThis._renderBuiltInProvidersSection = (list) => {
  const el = new FakeElement('div');
  el.className = 'builtin-providers-section';
  list.appendChild(el);
  return el;
};
globalThis._buildProviderCard = (provider) => {
  const el = new FakeElement('div');
  el.className = 'provider-card';
  el.textContent = provider.id;
  return el;
};
globalThis._fetchProviderQuotaStatus = () => {
  calls.push('/api/provider/quota');
  return new Promise(() => {});
};
globalThis._renderProviderQuotaIntoSection = () => {
  throw new Error('quota renderer should not run while quota is pending');
};

eval(fs.readFileSync(process.argv[2], 'utf8'));

(async () => {
  const completed = await Promise.race([
    loadProvidersPanel().then(() => true),
    new Promise((resolve) => setTimeout(() => resolve(false), 100)),
  ]);
  const cards = elements.providersList.querySelectorAll('.provider-card').length;
  process.stdout.write(JSON.stringify({
    completed,
    calls,
    cards,
    emptyDisplay: elements.providersEmpty.style.display || '',
    listDisplay: elements.providersList.style.display || '',
  }));
})().catch((err) => {
  process.stderr.write(String(err && err.stack || err));
  process.exit(1);
});
"""
    driver_path = tmp_path / "driver.js"
    driver_path.write_text(driver, encoding="utf-8")
    result = subprocess.run(
        [NODE, str(driver_path), str(fn_path)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout
    payload = json.loads(result.stdout)
    assert payload["completed"] is True
    assert payload["cards"] == 1
    assert payload["calls"] == [
        "/api/providers",
        "/api/custom_providers",
        "/api/provider/quota",
    ]
    assert payload["emptyDisplay"] == "none"
    assert payload["listDisplay"] == ""
