"""Static coverage for the WorkBuddy empty-session guide."""

from pathlib import Path
import shutil
import subprocess

import pytest


REPO = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (REPO / path).read_text(encoding="utf-8")


def test_empty_session_shell_loads_the_workbuddy_guide():
    html = _read("static/index.html")

    assert 'id="sessionGuide"' in html
    assert "WorkBuddy" not in html
    assert 'id="sessionGuideEyebrow"' not in html
    assert 'id="sessionGuideAgents"' in html
    assert 'id="sessionGuideCapabilities"' in html
    assert 'id="sessionGuideDictionaryBtn"' in html
    assert 'class="session-guide-capability-row"' in html
    assert 'id="sessionGuideCases"' in html
    assert 'id="sessionGuideSkillList"' in html
    assert 'id="sessionGuideRotateCases"' in html
    assert 'class="messages session-guide-shell-active" id="messages"' in html
    assert 'src="static/session_guide.js?v=__WEBUI_VERSION__"' in html


def test_session_guide_uses_profile_launchpad_and_composer_prefill():
    source = _read("static/session_guide.js")

    assert "api('/api/profiles'" in source
    assert "api('/api/skills'" in source
    assert "const DEFAULT_AGENT = 'zk';" in source
    assert "const DEFAULT_CAPABILITY = 'asset';" in source
    assert "const STORAGE_DICTIONARY = 'hermes-workbuddy-session-guide-dictionary-v1';" in source
    assert "const GUIDE_TRANSLATION_DICTIONARY = {" in source
    assert "agents: {" in source and "'ui-designer': {zh:'UI 设计智能体'" in source
    assert "capabilities: {" in source and "inspection: {zh:'日常巡检'" in source
    assert "skills: {" in source and "'host-discovery': {" in source
    assert "translateAgentName(name, name)" in source
    assert "translateGuideEntry('capabilities', capability.id" in source
    assert "skillDisplayText(skill.name, 'label', fallbackLabel)" in source
    assert "function skillDirectory(skill)" in source
    assert "function catalogCapabilities()" in source
    assert "(state.skills || []).forEach(skill =>" in source
    assert "const directory = skillDirectory(skill);" in source
    assert "const capability = directory || override.capability || inferCapability(skill) || '';" in source
    assert "catalogCapabilities().some(capability => capability.id === id)" in source
    assert "function openDictionaryManager()" in source
    assert "dictionaryManagerRows()" in source
    assert "function dictionaryFilterOptions()" in source
    assert "function applyDictionaryFilters(overlay)" in source
    assert "id=\"sessionGuideDictSearch\"" in source
    assert "data-dict-filter" in source
    assert "setGuideDictionaryValue(input.dataset.dictSection, input.dataset.dictKey, input.dataset.dictPath, input.value)" in source
    assert "writeStoredGuideDictionary();" in source
    assert "state.initializing = true;" in source
    assert "const profiles = loadProfiles();" in source
    assert "const skills = loadSkills();" in source
    assert "loading_cases" in source
    assert "发现主机、服务、端口和资产归属信息。" in source
    assert "asset-inventory" in source and "asset-compliance" in source
    assert "switchToProfile(" in source and "'zk'" in source
    assert "data-session-guide-agent" in source
    assert "data-session-guide-capability" in source
    assert "data-session-guide-skill" in source
    assert "data-session-guide-case" in source
    assert "window._clearPendingSelections" in source
    assert "window._addNamedContextBlock" in source
    assert "messages.classList.toggle('session-guide-shell-active', active)" in source
    assert "syncShellScrollState();\n    if(!rootElement || rootElement.classList.contains('workspace-empty-state') || !guide()) return false;" in source
    assert "input.dispatchEvent(new Event('input', {bubbles: true}))" in source
    assert "compactText(skill.description || '', 88)" in source
    assert "compactText(skill.raw && skill.raw.description || '', 88)" in source
    assert "attributeFilter: ['lang']" in source
    assert "attributeFilter: ['style', 'class']" in source
    assert "switchPanel('skills')" not in source


def test_session_guide_can_name_composer_context_chips():
    source = _read("static/messages.js")

    assert "function _addNamedContextBlock(text, nameOverride)" in source
    assert "window._addNamedContextBlock=_addNamedContextBlock" in source


def test_session_guide_keeps_no_workspace_and_suggestion_preferences_compatible():
    css = _read("static/style.css")
    workspace_empty = _read("static/workspace_empty.js")

    assert ".empty-state.no-suggestions .session-guide-cases" in css
    assert "root.classList.remove('session-guide-active')" in workspace_empty
    assert "messages.classList.remove('session-guide-shell-active')" in workspace_empty


def test_session_guide_has_narrow_layout_rules():
    css = _read("static/style.css")

    assert "@media(max-width:900px){" in css
    assert "#mainChat:has(.messages.session-guide-shell-active){--session-guide-content-max:1280px;}" in css
    assert "#mainChat:has(.messages.session-guide-shell-active) .composer-box{width:100%;max-width:var(--session-guide-content-max);}" in css
    assert ".messages.session-guide-shell-active>.empty-state.session-guide-active{height:100%;min-height:0;}" in css
    assert ".session-guide{width:100%;max-width:var(--session-guide-content-max);margin:0 auto;padding:0;" in css
    assert ".session-guide{width:100%;max-width:none;margin:0 auto;padding:0;" in css
    assert "padding:14px 28px 12px" in css
    assert ".empty-state.session-guide-active{padding:12px 14px 14px;}" in css
    assert ".session-guide-hero{margin:0;padding:14px 18px;background:var(--session-guide-panel);border:1px solid var(--session-guide-border);border-radius:8px;" in css
    assert ".session-guide-capability-row{display:flex;align-items:center;gap:10px;min-width:0;}" in css
    assert ".session-guide-dictionary-btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;" in css
    assert ".session-guide-dict-overlay{position:fixed;inset:0;z-index:1300;" in css
    assert ".session-guide-dict-filters{display:flex;align-items:center;gap:12px;" in css
    assert ".session-guide-dict-filter[aria-pressed=\"true\"]" in css
    assert ".session-guide-dict-search{margin-left:auto;display:flex;align-items:center;" in css
    assert ".session-guide-dict-table-wrap{flex:1 1 auto;min-height:0;overflow:auto;}" in css
    assert ".session-guide-grid{grid-template-columns:minmax(0,1fr);" in css
    assert ".messages.session-guide-shell-active{overflow:hidden;}" in css
    assert ".messages.session-guide-shell-active>.messages-inner" in css
    assert "overflow-x:hidden;overflow-y:hidden;" in css
    assert ".session-guide-grid{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:16px;margin-top:14px;align-items:stretch;flex:1 1 auto;min-height:0;}" in css
    assert ".session-guide-grid>.session-guide-section{min-height:0;align-self:stretch;" in css
    assert ".session-guide-agent-list .session-guide-chip[aria-pressed=\"true\"]{background:var(--session-guide-panel);border-color:var(--session-guide-accent);" in css
    assert ".session-guide-agent-list,.session-guide-capability-list{justify-content:flex-start;" in css
    assert ".session-guide-skill-grid,.session-guide-case-grid{flex:1 1 auto;min-height:0;overflow-y:auto;" in css
    assert ".session-guide-skill-card-head{display:grid;grid-template-columns:52px minmax(0,1fr) 20px;" in css
    assert ".session-guide-skill-desc{color:var(--session-guide-muted);font-size:12px;line-height:1.45;min-width:0;overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;" in css
    assert ".session-guide-card-arrow{margin-left:0;width:20px;" in css
    assert ".session-guide-grid{grid-template-columns:minmax(0,1fr);grid-template-rows:minmax(0,1fr) minmax(0,1fr);" in css
    assert ".session-guide-skill-grid,.session-guide-case-grid{grid-template-columns:repeat(2,minmax(0,1fr));}" in css
    assert ".session-guide-case-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));" in css
    assert ".session-guide-skill-grid{grid-template-columns:minmax(0,1fr);}" in css


def test_session_guide_javascript_parses():
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not available")

    result = subprocess.run(
        [node, "--check", "static/session_guide.js"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
