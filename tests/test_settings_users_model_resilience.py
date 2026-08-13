"""Regression coverage for Settings Users responsiveness and model fallback.

Production failure shape:
- Settings -> Users became sluggish because Settings waited on /api/models and
  Users waited on the audit table before the panel became usable.
- A bad or unreachable configured default model could keep new chats pinned to
  that stale default after the browser had already fallen back to a usable
  dropdown option.
"""
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read_static(name: str) -> str:
    return (ROOT / "static" / name).read_text(encoding="utf-8")


def _function_block(src: str, name: str) -> str:
    marker = re.search(rf"(^|\n)\s*(?:async\s+)?function\s+{re.escape(name)}\(", src)
    assert marker is not None, f"{name}() not found"
    start = marker.start()
    header_end = src.find("){", marker.end())
    if header_end == -1:
        header_end = src.find(") {", marker.end())
    assert header_end != -1, f"{name}() body start not found"
    open_idx = src.find("{", header_end)
    assert open_idx != -1, f"{name}() body start not found"
    depth = 0
    for i in range(open_idx, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start : i + 1]
    raise AssertionError(f"{name}() body is unbalanced")


def test_users_panel_first_paint_does_not_wait_for_audit_log():
    users_js = _read_static("users_panel.js")
    body = _function_block(users_js, "loadUsersPanel")

    assert not body.lstrip().startswith("async function loadUsersPanel"), (
        "loadUsersPanel should render and schedule async work without making "
        "Settings wait on admin/audit requests."
    )
    assert "await loadCurrentAccount()" not in body
    assert "await Promise.all([loadUsers(), loadAudit()])" not in body
    assert "_usersPanelLoadInFlight" in body
    assert "Promise.allSettled([loadCurrentAccount(), loadUsers()])" in body
    assert "refreshAuditSoon()" in body


def test_users_panel_reuses_mounted_dom_and_binds_actions_once():
    users_js = _read_static("users_panel.js")
    load_body = _function_block(users_js, "loadUsersPanel")
    bind_body = _function_block(users_js, "bindActions")

    assert "pane.dataset.usersPanelMounted" in load_body
    assert "!pane.querySelector('#users-tbody')" in load_body
    assert "pane.dataset.usersActionsBound" in bind_body


def test_users_panel_mutations_refresh_audit_without_blocking_actions():
    users_js = _read_static("users_panel.js")

    assert "function refreshAuditSoon()" in users_js
    assert "await loadAudit()" not in users_js
    assert "loadAudit();" not in _function_block(users_js, "createUser")
    assert "refreshAuditSoon();" in _function_block(users_js, "createUser")
    assert "refreshAuditSoon();" in _function_block(users_js, "toggleRole")
    assert "refreshAuditSoon();" in _function_block(users_js, "deleteUser")


def test_settings_panel_model_catalog_load_is_background_and_bounded():
    panels_js = _read_static("panels.js")
    load_body = _function_block(panels_js, "loadSettingsPanel")
    model_body = _function_block(panels_js, "_loadSettingsModelPicker")

    assert "await api('/api/models')" not in load_body
    assert "Promise.resolve(_loadSettingsModelPicker()).catch(()=>{});" in load_body
    assert "/api/models?freshness=session_visit" in model_body
    assert "timeoutMs:8000" in model_body
    assert "timeoutToast:false" in model_body
    assert "_applySettingsModelFallback" in model_body


def test_auxiliary_models_use_fast_model_catalog_path():
    panels_js = _read_static("panels.js")
    body = _function_block(panels_js, "_loadAuxiliaryModels")

    assert "/api/models?freshness=session_visit" in body
    assert "timeoutMs:8000" in body
    assert "timeoutToast:false" in body
    assert "api('/api/models').catch" not in body


def test_model_dropdown_timeout_retries_session_visit_and_marks_bad_default():
    ui_js = _read_static("ui.js")
    body = _function_block(ui_js, "populateModelDropdown")
    fallback_body = _function_block(ui_js, "_applySessionModelFallback")

    assert "60000" not in body
    compact = body.replace(" ", "").replace("\n", "")
    assert "requestedFreshness==='session_visit'?8000:12000" in compact
    assert "populateModelDropdown({...opts,freshness:'session_visit',timeoutMs:8000})" in body
    assert "window._defaultModelUnavailable=true" in fallback_body
    assert "window._defaultModelUnavailable=false" in fallback_body


def test_new_session_does_not_force_unavailable_default_model():
    sessions_js = _read_static("sessions.js")
    body = _function_block(sessions_js, "newSession")

    assert "window._defaultModelUnavailable&&modelSelForNew&&modelSelForNew.value" in body
