// ── Workspace empty state ────────────────────────────────────────────────
// When a user lands on /chat or /session/{id} without any accessible
// workspaces, the standard "What can I help with?" empty state is
// misleading — there is no workspace context to operate on. Instead we
// render a dedicated "no workspace" state with a single "Create workspace"
// button that reuses the existing workspace creation dialog.
//
// Reused globals (resolved lazily so the script can load before / after
// any other static module):
//   - `t(key)`        → i18n translation (i18n.js)
//   - `api(path,...)` → fetch helper (ui.js)
//   - `showToast(...)`→ global toast (ui.js)
//   - `openWorkspaceCreate()` → existing create dialog (panels.js)
//   - `$`             → $(id) shortcut (ui.js)
//   - `esc`           → HTML escaper (ui.js)

function renderNoWorkspaceEmptyState(){
  const root = $('emptyState');
  if(!root) return;
  const escStr = (typeof esc === 'function')
    ? esc
    : (s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])));
  const title = (typeof t === 'function') ? t('workspace_empty_title') : 'You have no accessible workspaces';
  const hint  = (typeof t === 'function') ? t('workspace_empty_hint')  : 'Contact your administrator to be added, or create one yourself';
  const btn   = (typeof t === 'function') ? t('workspace_empty_create_btn') : '+ Create workspace';
  const emptyLabel = (typeof t === 'function') ? t('no_workspace') : '无可用工作区';
  // Snapshot the original chat empty-state HTML before we overwrite it so the
  // auth-change reset can restore it for the *next* user (see panels.js
  // _resetWorkspaceStateForAuthChange). Without this, a user who has no
  // workspace and then logs out leaves the workspace empty state stuck on the
  // default page for whoever logs in next, even if they actually have
  // workspaces (e.g. test2 receiving a shared workspace from dengy).
  try{
    if(typeof S !== 'undefined' && S && S._emptyStateOriginalHTML === undefined){
      S._emptyStateOriginalHTML = root.innerHTML;
    }
  }catch(_){}
  root.classList.add('workspace-empty-state', 'no-suggestions');
  root.innerHTML = `
    <div class="workspace-empty-state__icon" aria-hidden="true">📁</div>
    <h2>${escStr(title)}</h2>
    <p>${escStr(hint)}</p>
    <button type="button" class="primary-btn workspace-empty-state__cta" data-action="create-workspace">
      ${escStr(btn)}
    </button>
  `;
  const btnEl = root.querySelector('[data-action="create-workspace"]');
  if(btnEl) btnEl.addEventListener('click', () => openCreateWorkspaceDialog());
  // Surface the empty state and hide any chat-specific siblings.
  root.style.display = '';
  const msgInner = $('msgInner');
  if(msgInner) msgInner.innerHTML = '';
  const liveRun = $('liveRunStatus');
  if(liveRun) liveRun.hidden = true;
  const liveTools = $('liveToolCards');
  if(liveTools) liveTools.style.display = 'none';
  const liveCards = $('liveCompressionCards');
  if(liveCards) liveCards.innerHTML = '';
  // Mirror the empty state to the composer / sidebar workspace chips so they
  // do not keep showing the stale session workspace while the main view says
  // "no workspaces available" (e.g. admin removed all workspaces for this user).
  const chipLabel = $('composerWorkspaceLabel');
  if(chipLabel) chipLabel.textContent = emptyLabel;
  const chip = $('composerWorkspaceChip');
  if(chip) { chip.disabled = true; chip.title = emptyLabel; chip.classList.add('no-workspace'); }
  const mobileLabel = $('composerMobileWorkspaceLabel');
  if(mobileLabel) mobileLabel.textContent = emptyLabel;
  const mobileAction = $('composerMobileWorkspaceAction');
  if(mobileAction) { mobileAction.title = emptyLabel; mobileAction.classList.add('no-workspace'); }
  const sidebarName = $('sidebarWsName');
  if(sidebarName) sidebarName.textContent = emptyLabel;
}

function openCreateWorkspaceDialog(){
  // Prefer the existing workspace-create form (panels.js). It opens the
  // form inside the Workspaces panel; if the user is currently on the
  // chat/session route we proactively switch to the Workspaces panel
  // first so the form is visible.
  if(typeof openWorkspaceCreate === 'function'){
    try{
      openWorkspaceCreate();
      return;
    }catch(_e){
      // Fall through to the prompt-based path below.
    }
  }
  // Backstop: fall back to a prompt that POSTs /api/workspaces/add
  // directly with `create: true` so the path is auto-created.
  if(typeof api !== 'function' || typeof showToast !== 'function') return;
  const path = (typeof window.prompt === 'function')
    ? window.prompt('Workspace path (absolute):')
    : null;
  if(!path) return;
  api('/api/workspaces/add', {method:'POST', body: JSON.stringify({path: String(path).trim(), name: '', create: true})})
    .then(() => {
      showToast('Workspace added');
      // Reload so the workspace list, sidebar, and any composer chip
      // are repopulated from the fresh server state.
      try{ window.location.reload(); }catch(_){}
    })
    .catch((e) => {
      showToast((e && e.message) ? e.message : 'Failed to add workspace', 5000, 'error');
    });
}

// Decide whether we should render the no-workspace empty state for the
// current route. Returns a Promise<boolean>: true if the empty state
// was rendered (and the boot sequence should early-return).
async function maybeRenderNoWorkspaceEmptyState(){
  const _dbg = (window && window._emptyStateDebug !== false);
  const _log = (...a) => { if(_dbg){ try{ console.log('[emptyState]', ...a); }catch(_){} } };
  // Only intercept the chat-style routes. Other surfaces (workspaces
  // panel, settings) have their own empty UX.
  const path = (typeof window !== 'undefined' && window.location)
    ? (window.location.pathname || '')
    : '';
  try{ sessionStorage.setItem('hermes-empty-debug', JSON.stringify({t:Date.now(), path:path, hasFn:true})); }catch(_){}
  _log('enter', {path});
  const isChatRoute =
    path === '/' || path === '' ||
    path === '/chat' || path === '/chat/' ||
    /^\/session\//.test(path);
  if(!isChatRoute){ _log('return false: not a chat route', {path}); return false; }
  // Fetch the workspace list directly. We do NOT depend on the
  // module-scoped `_workspaceList` inside panels.js — the boot sequence
  // may or may not have populated it yet by the time we run.
  if(typeof api !== 'function'){ _log('return false: api not a function', {apiType: typeof api}); return false; }
  let list = null;
  try{
    const data = await api('/api/workspaces', {redirect401: false});
    // NOTE: api() returns undefined on 401 when redirect401:false (it skips
    // navigation). During early boot the login cookie may not have been applied
    // yet, so a genuine first-time user with no workspaces would otherwise be
    // skipped and never see the "create a workspace" empty state. We briefly
    // wait for auth to settle and retry once. If it is still 401 we bail out
    // (not authenticated → do not render).
    if(!data){
      _log('api returned undefined (likely 401) — retrying once');
      await new Promise((_r)=>setTimeout(_r, 600));
      const retry = await api('/api/workspaces', {redirect401: false}).catch(()=>undefined);
      if(!retry){ _log('return false: still 401 after retry'); return false; }
      list = (Array.isArray(retry.workspaces)) ? retry.workspaces : [];
      _log('api retry ok', {listLen: list.length});
    }else{
      list = (Array.isArray(data.workspaces)) ? data.workspaces : [];
      _log('api /api/workspaces ok', {dataKeys: data ? Object.keys(data) : null, listLen: list.length, sample: list.slice(0, 1)});
    }
  }catch(_e){
    // If the request fails (network, etc.) fall through and let
    // the normal boot logic handle it — never block the app on our
    // empty-state probe.
    _log('return false: api threw', {message: _e && _e.message, status: _e && _e.status, name: _e && _e.name});
    return false;
  }
  if(list.length > 0){ _log('return false: list has items', {listLen: list.length, first: list[0]}); return false; }
  _log('about to render no-workspace empty state', {listLen: list.length});
  renderNoWorkspaceEmptyState();
  return true;
}

window.renderNoWorkspaceEmptyState = renderNoWorkspaceEmptyState;
window.openCreateWorkspaceDialog = openCreateWorkspaceDialog;
window.maybeRenderNoWorkspaceEmptyState = maybeRenderNoWorkspaceEmptyState;
