"""Verify session sharing UI elements exist."""
from pathlib import Path


def test_session_sharing_js_exists():
    assert Path("static/session_sharing.js").exists()


def test_session_sharing_js_loads_share_recipient_users():
    src = Path("static/session_sharing.js").read_text(encoding="utf-8")
    assert "api('/api/users'" in src


def test_session_sharing_js_calls_share_endpoint():
    src = Path("static/session_sharing.js").read_text(encoding="utf-8")
    # 必须包含用户分享和 token 分享两个 endpoint
    assert "/share" in src
    assert "/share/token" in src


def test_session_sharing_js_uses_collapsed_multi_select_dropdown():
    src = Path("static/session_sharing.js").read_text(encoding="utf-8")
    assert "share-multiselect" in src
    assert "panel.hidden = true" in src
    assert "share-user-cb" in src
    assert "share-multiselect-all-cb" in src
    assert "user_ids" in src
    assert "usernames" in src


def test_session_sharing_incoming_cache_is_scoped_by_user():
    src = Path("static/session_sharing.js").read_text(encoding="utf-8")
    assert "_sharedSessionsUserId" in src
    assert "_clearSharedSessionsCache(true)" in src
    assert "_sharedSessionsUserId === userId" in src


def test_session_share_css_keeps_dropdown_collapsed_when_hidden():
    css = Path("static/style.css").read_text(encoding="utf-8")
    assert ".share-multiselect-panel" in css
    assert ".share-multiselect-panel[hidden]" in css
    assert "display:none!important" in css
    assert ".share-trigger-label" in css
    assert "text-overflow:ellipsis" in css
    assert ".skeleton-list.session-list-loading" in css
    assert "session-loading-shimmer" in css


def test_session_actions_menu_exposes_share_dialog_entry():
    src = Path("static/sessions.js").read_text(encoding="utf-8")
    assert "openShareDialog(session)" in src
    assert "canShareSession(session)" in src


def test_session_sidebar_treats_rbac_owned_empty_rows_as_visible():
    src = Path("static/sessions.js").read_text(encoding="utf-8")
    assert "!!s.rbac_user_id" in src


def test_session_sidebar_cache_is_scoped_by_authenticated_user():
    sessions_src = Path("static/sessions.js").read_text(encoding="utf-8")
    boot_src = Path("static/boot.js").read_text(encoding="utf-8")
    login_src = Path("static/login.js").read_text(encoding="utf-8")
    assert "resetSessionStateForAuthChange" in sessions_src
    assert "rbacUserId" in sessions_src
    assert "_sessionRowVisibleForRbacScope" in sessions_src
    assert "serverSessions.filter(s=>_sessionRowVisibleForRbacScope" in sessions_src
    assert "if(!_sessionRowVisibleForRbacScope(local)) continue" in sessions_src
    assert "_syncAuthScopeBeforeSessionListRefresh" in sessions_src
    assert "await _syncAuthScopeBeforeSessionListRefresh()" in sessions_src
    assert "opts&&opts.authScopeAlreadySynced===true" in sessions_src
    assert "new CustomEvent('hermes:session-list-ready')" in sessions_src
    assert "hermes-webui-auth-user-id" in sessions_src
    assert "_cachedRbacUserId !== _currentRbacUserId" in sessions_src
    assert "_invalidateSessionListRenders();" in sessions_src
    assert "_lastSessionListRenderSig = null" in sessions_src
    assert "list.setAttribute('aria-busy', 'true')" in sessions_src
    assert "list.dataset.sessionLoading = '1'" in sessions_src
    assert "wrap.classList.add('session-list-loading')" in sessions_src
    assert "Promise.race([" in sessions_src
    assert "_sessionListHasLoadedOnce ? 500 : 700" in sessions_src
    assert "_isAdminInitialSessionList" in sessions_src
    assert "'limit=120'" in sessions_src
    assert "!_sessionListHasLoadedOnce && !_sessionListSkeletonActive" in sessions_src
    assert "_sessionListHasLoadedOnce = false" in sessions_src
    assert "AUTH_SCOPE_STORAGE_KEY='hermes-webui-auth-user-id'" in boot_src
    assert "window._currentAuthRole" in boot_src
    assert "changedFromLivePage" in boot_src
    assert "await renderSessionList({deferWhileInteracting:false})" in boot_src
    assert "refreshSharedSessionsSection(true)" in boot_src
    assert "await syncAuthIdentityScope()" in boot_src
    assert "AUTH_SCOPE_SNAPSHOT_TTL_MS=1500" in boot_src
    assert "_authIdentityStatusPromise" in boot_src
    assert "_authIdentityStatusGeneration" in boot_src
    assert "statusGeneration===_authIdentityStatusGeneration" in boot_src
    assert "renderSessionList({authScopeAlreadySynced:true})" in boot_src
    assert "_bootAuthStatusReady" in boot_src
    assert "_bootSessionListReady" in boot_src
    assert "authScopeReady:_bootAuthStatusReady" in boot_src
    assert "refetchWhenAuthScopeChanges:true" in boot_src
    assert "Promise.all([payloadReady, Promise.resolve(authScopeReady).catch(()=>null)])" in sessions_src
    assert "_canStartInitialSessionListBeforeSettings" in sessions_src
    assert "syncAuthIdentityScope({force:true})" in boot_src
    settings_ready = boot_src.index("const s=await api('/api/settings');")
    auth_dispatch = boot_src.index("await _bootAuthStatusReady;", settings_ready)
    settings_apply = boot_src.index("_bootSettings=s;", settings_ready)
    assert settings_ready < auth_dispatch < settings_apply
    assert "hermes-webui-auth-user-id" in login_src
    assert "hermes-webui-auth-role" in login_src
    assert "localStorage.removeItem('hermes-webui-session')" in login_src


def test_shared_sessions_wait_until_primary_sidebar_is_ready():
    src = Path("static/session_sharing.js").read_text(encoding="utf-8")
    assert "hermes:session-list-ready" in src
    assert "_startInitialSharedSessions" in src
    init = src[src.index("function init()") : src.index("// Public API")]
    assert "loadSharedSessions(false)" not in init.split("let _initialSharedSessionsStarted", 1)[0]
    assert "_subscribeSessionEvents();" not in init.split("let _initialSharedSessionsStarted", 1)[0]


def test_session_sharing_js_has_escape_html_helper():
    """防止 XSS — 用户/会话名插入 DOM 前必须转义。"""
    src = Path("static/session_sharing.js").read_text(encoding="utf-8")
    assert "textContent" in src


def test_rating_star_click_enables_feedback_submit_fallback():
    src = Path("static/sessions.js").read_text(encoding="utf-8")
    assert "_installRatingSubmitEnableFallback" in src
    assert "starSelector" in src
    assert "selectedRatingIn(root)" in src
    assert "_hermesRatingSelected" in src
    assert "btn.disabled = false" in src
    assert "setTimeout(()=>enableSubmitButtons(root),200)" in src


def test_settings_user_panel_localization_and_license_fallback():
    src = Path("static/sessions.js").read_text(encoding="utf-8")
    assert "_installSettingsLocalizationAndLicenseFallback" in src
    assert "['Users','用户']" in src
    assert "['Current account','当前账号']" in src
    assert "['Add user','添加用户']" in src
    assert "['All users','所有用户']" in src
    assert "['USERNAME','用户名']" in src
    assert "['ACTIONS','操作']" in src
    assert "['username','用户名']" in src
    assert "['password (>=8 chars)','密码（至少 8 位）']" in src
    assert "normalizeLicensePayload" in src
    assert "'/api/license/status'" in src
    assert "'/api/admin/license/status'" in src
    assert "findLicenseValueNode('状态')" not in src


def test_license_activation_page_refetches_machine_info_when_na():
    src = Path("static/login.js").read_text(encoding="utf-8")
    assert "_installLicenseActivationMachineInfoFallback" in src
    assert "'/api/license/machine'" in src
    assert "'/api/license/status'" in src
    assert "_setLicenseValue('平台 ID', info.platformId)" in src
    assert "_setLicenseValue('MAC 地址', info.macAddress)" in src
    assert "未能读取平台 ID / MAC 地址" in src


def test_license_machine_identity_runtime_fallback_exists():
    src = Path("sitecustomize.py").read_text(encoding="utf-8")
    assert "_patched_uuid_getnode" in src
    assert "HERMES_WEBUI_PLATFORM_ID" in src
    assert "HERMES_WEBUI_MACHINE_MAC" in src
    assert "_fallback_mac" in src
