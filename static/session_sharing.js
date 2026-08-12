/* Session sharing UI — share dialog, "收到的分享" sidebar section, read-only view.
 *
 * Backed by:
 *   POST   /api/sessions/{id}/share          (user share)
 *   GET    /api/sessions/{id}/shares         (list share records)
 *   DELETE /api/sessions/{id}/share/{share}  (revoke)
 *   POST   /api/sessions/{id}/share/token    (token link)
 *   GET    /api/sessions/shared              (incoming shares)
 *
 * Read-only mode: GET /api/session returns viewer:"shared" for non-owners;
 * this module locks the composer and shows a banner.
 */
(function () {
  'use strict';

  // ── Current user (cached) ─────────────────────────────────────────────────
  let _currentUser = null;
  let _currentUserPromise = null;

  function currentUser() {
    if (_currentUserPromise) return _currentUserPromise;
    _currentUserPromise = (async () => {
      try {
        const status = typeof syncAuthIdentityScope === 'function'
          ? await syncAuthIdentityScope({ clearOnChange: true })
          : await api('/api/auth/status', { redirect401: false, timeoutMs: 5000, timeoutToast: false });
        _currentUser = (status && status.user) || null;
      } catch (_) {
        _currentUser = null;
      }
      return _currentUser;
    })();
    return _currentUserPromise;
  }

  function _resetCurrentUser() {
    _currentUser = null;
    _currentUserPromise = null;
    _clearSharedSessionsCache(true);
  }

  // Decide whether the share entry should appear for a sidebar session row.
  async function canShareSession(session) {
    if (!session || !session.session_id) return false;
    if (typeof _isReadOnlySession === 'function' && _isReadOnlySession(session)) return false;
    if (typeof _isExternalSession === 'function' && _isExternalSession(session)) return false;
    const user = await currentUser();
    if (!user) return false; // RBAC not active → hide entry entirely
    const owner = String(session.rbac_user_id || '').trim();
    if (!owner) return user.role === 'admin';
    return owner === String(user.id || '') || user.role === 'admin';
  }

  // ── Share dialog ──────────────────────────────────────────────────────────
  let _shareDialog = null;
  let _shareDialogCleanup = [];

  function closeShareDialog() {
    for (const cleanup of _shareDialogCleanup.splice(0)) {
      try { cleanup(); } catch (_) {}
    }
    if (_shareDialog) {
      _shareDialog.remove();
      _shareDialog = null;
    }
  }

  function _el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  }

  function _esc(s) {
    const d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  async function openShareDialog(session) {
    closeShareDialog();
    const overlay = _el('div', 'share-dialog-overlay');
    const dialog = _el('div', 'share-dialog');
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-label', t('share_dialog_title') || '分享会话');

    const head = _el('div', 'share-dialog-head');
    head.appendChild(_el('div', 'share-dialog-title', t('share_dialog_title') || '分享会话'));
    const closeBtn = _el('button', 'share-dialog-close', '×');
    closeBtn.type = 'button';
    closeBtn.setAttribute('aria-label', t('close') || 'Close');
    closeBtn.onclick = closeShareDialog;
    head.appendChild(closeBtn);
    dialog.appendChild(head);

    const subtitle = _el('div', 'share-dialog-subtitle', session.title || t('untitled') || 'Untitled');
    dialog.appendChild(subtitle);

    const body = _el('div', 'share-dialog-body');
    dialog.appendChild(body);

    overlay.appendChild(dialog);
    overlay.addEventListener('mousedown', (e) => {
      if (e.target === overlay) closeShareDialog();
    });
    document.addEventListener('keydown', function onKey(e) {
      if (e.key === 'Escape') {
        closeShareDialog();
        document.removeEventListener('keydown', onKey);
      }
    });
    _shareDialogCleanup.push(() => document.removeEventListener('keydown', onKey));
    document.body.appendChild(overlay);
    _shareDialog = overlay;

    await _renderShareDialogBody(body, session);
  }

  async function _renderShareDialogBody(body, session) {
    body.innerHTML = '';
    const sid = session.session_id;

    // ── Section 1: share to user (multi-select dropdown) ──
    const secUser = _el('div', 'share-section share-section-users');
    secUser.appendChild(_el('div', 'share-section-title', t('share_to_user') || '分享给用户'));

    // Dropdown trigger that opens a multi-select checkbox panel.
    const dropdown = _el('div', 'share-multiselect');
    const trigger = _el('button', 'btn share-input share-trigger');
    trigger.type = 'button';
    trigger.setAttribute('aria-haspopup', 'listbox');
    trigger.setAttribute('aria-expanded', 'false');
    const triggerLabel = _el('span', 'share-trigger-label');
    triggerLabel.textContent = t('share_select_users') || '选择用户…';
    trigger.appendChild(triggerLabel);
    const triggerCaret = _el('span', 'share-trigger-caret', '▾');
    trigger.appendChild(triggerCaret);

    const panel = _el('div', 'share-multiselect-panel');
    panel.hidden = true;
    panel.setAttribute('role', 'listbox');

    const panelHeader = _el('div', 'share-multiselect-header');
    const selectAll = _el('label', 'share-multiselect-all');
    const allCheckbox = document.createElement('input');
    allCheckbox.type = 'checkbox';
    allCheckbox.className = 'share-multiselect-all-cb';
    const allLabel = _el('span', null, t('share_select_all') || '全选');
    selectAll.appendChild(allCheckbox);
    selectAll.appendChild(allLabel);
    panelHeader.appendChild(selectAll);
    panel.appendChild(panelHeader);

    const userList = _el('div', 'share-multiselect-list');
    panel.appendChild(userList);
    const userHint = _el('div', 'share-multiselect-hint');
    userHint.textContent = t('share_loading_users') || '加载中…';
    panel.appendChild(userHint);

    dropdown.appendChild(trigger);
    dropdown.appendChild(panel);
    secUser.appendChild(dropdown);

    const userErr = _el('div', 'share-error');
    userErr.hidden = true;
    secUser.appendChild(userErr);

    // Load user list from /api/users.
    let availableUsers = [];
    try {
      const data = await api('/api/users', { timeoutMs: 6000, timeoutToast: false });
      availableUsers = (data && Array.isArray(data.users)) ? data.users : [];
    } catch (e) {
      userHint.textContent = (e && e.message) || String(e);
    }
    userList.innerHTML = '';
    if (!availableUsers.length) {
      userHint.textContent = t('share_no_users') || '无可分享用户';
      userHint.hidden = false;
    } else {
      userHint.hidden = true;
    }
    for (const u of availableUsers) {
      const opt = _el('label', 'share-multiselect-option');
      const cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.value = String(u.id || '');
      cb.dataset.username = String(u.username || '');
      cb.dataset.userId = String(u.id || '');
      cb.className = 'share-user-cb';
      const name = _el('span', null, u.username || u.id || '');
      opt.appendChild(cb);
      opt.appendChild(name);
      userList.appendChild(opt);
      const onChange = () => {
        _syncSelectAllState();
        _syncTriggerLabel();
      };
      cb.addEventListener('change', onChange);
    }

    function _checkedCheckboxes() {
      return userList.querySelectorAll('input.share-user-cb:checked');
    }
    function _syncSelectAllState() {
      const all = userList.querySelectorAll('input.share-user-cb');
      const checked = _checkedCheckboxes();
      allCheckbox.checked = all.length > 0 && checked.length === all.length;
      allCheckbox.indeterminate = checked.length > 0 && checked.length < all.length;
    }
    function _syncTriggerLabel() {
      const checked = _checkedCheckboxes();
      if (checked.length === 0) {
        triggerLabel.textContent = t('share_select_users') || '选择用户…';
      } else {
        // Show all selected usernames comma-separated so the user can
        // confirm who's chosen without keeping the panel open.
        const names = [];
        checked.forEach((cb) => { names.push(cb.dataset.username || '?'); });
        triggerLabel.textContent = names.join(', ');
      }
    }
    allCheckbox.addEventListener('change', () => {
      const want = allCheckbox.checked;
      userList.querySelectorAll('input.share-user-cb').forEach((cb) => { cb.checked = want; });
      _syncSelectAllState();
      _syncTriggerLabel();
      _updateShareBtn();
      // Don't auto-close on select-all (user may want to inspect the list);
      // but the share button below remains accessible.
    });
    function _setDropdownOpen(open) {
      panel.hidden = !open;
      dropdown.classList.toggle('is-open', open);
      trigger.setAttribute('aria-expanded', open ? 'true' : 'false');
    }
    trigger.addEventListener('click', (e) => {
      e.stopPropagation();
      _setDropdownOpen(panel.hidden);
    });
    // Close panel when clicking outside.
    const onDocClick = (e) => {
      if (dropdown.contains(e.target)) return;
      _setDropdownOpen(false);
    };
    document.addEventListener('mousedown', onDocClick);
    _shareDialogCleanup.push(() => document.removeEventListener('mousedown', onDocClick));

    // Share button (outside the dropdown to keep layout consistent).
    const shareBtn = _el('button', 'btn share-btn-primary');
    shareBtn.type = 'button';
    const shareBtnLabel = _el('span', null, t('share_button') || '分享');
    const shareBtnCount = _el('span', 'share-btn-count');
    shareBtn.appendChild(shareBtnLabel);
    shareBtn.appendChild(document.createTextNode(' '));
    shareBtn.appendChild(shareBtnCount);
    const _updateShareBtn = () => {
      const n = _checkedCheckboxes().length;
      if (n > 0) {
        shareBtnCount.textContent = '(' + n + ')';
        shareBtn.classList.add('has-selection');
        shareBtn.disabled = false;
      } else {
        shareBtnCount.textContent = '';
        shareBtn.classList.remove('has-selection');
        shareBtn.disabled = true;
      }
    };
    // Update on every change (hook into existing change events).
    userList.addEventListener('change', _updateShareBtn);
    _updateShareBtn();
    const doUserShare = async () => {
      const checked = _checkedCheckboxes();
      if (!checked.length) {
        userErr.textContent = t('share_select_one') || '请至少选择一个用户';
        userErr.hidden = false;
        return;
      }
      shareBtn.disabled = true;
      userErr.hidden = true;
      try {
        const user_ids = [];
        const usernames = [];
        checked.forEach((cb) => {
          user_ids.push(cb.dataset.userId);
          usernames.push(cb.dataset.username);
        });
        const resp = await api(`/api/sessions/${encodeURIComponent(sid)}/share`, {
          method: 'POST',
          body: JSON.stringify({ user_ids, usernames }),
        });
        const created = (resp && resp.shares) || [];
        const failed = (resp && resp.failed) || [];
        if (failed.length) {
          userErr.textContent = (t('share_partial') || '部分分享失败: {n}').replace('{n}', String(failed.length));
          userErr.hidden = false;
        } else {
          showToast((t('share_success') || '已分享') + ' · ' + created.length, 2200);
        }
        // Reset selection and refresh.
        userList.querySelectorAll('input.share-user-cb').forEach((cb) => { cb.checked = false; });
        _syncSelectAllState();
        _syncTriggerLabel();
        _setDropdownOpen(false);
        await _renderShareDialogBody(body, session);
      } catch (e) {
        userErr.textContent = (e && e.message) || String(e);
        userErr.hidden = false;
      } finally {
        shareBtn.disabled = false;
      }
    };
    shareBtn.onclick = doUserShare;
    const shareRow = _el('div', 'share-input-row');
    shareRow.appendChild(shareBtn);
    secUser.appendChild(shareRow);
    body.appendChild(secUser);

    // ── Section 2: token link ──
    const secLink = _el('div', 'share-section');
    secLink.appendChild(_el('div', 'share-section-title', t('share_link') || '链接分享'));
    const linkRow = _el('div', 'share-input-row');
    const genBtn = _el('button', 'btn', t('share_generate_link') || '生成链接');
    genBtn.type = 'button';
    linkRow.appendChild(genBtn);
    secLink.appendChild(linkRow);
    const linkOut = _el('div', 'share-link-out');
    linkOut.hidden = true;
    secLink.appendChild(linkOut);
    genBtn.onclick = async () => {
      genBtn.disabled = true;
      try {
        const data = await api(`/api/sessions/${encodeURIComponent(sid)}/share/token`, {
          method: 'POST',
          body: '{}',
        });
        const url = (data && data.share && data.share.url) || '';
        const absolute = url ? new URL(url, window.location.origin).href : '';
        linkOut.innerHTML = '';
        const linkText = _el('input', 'share-input share-link-text');
        linkText.readOnly = true;
        linkText.value = absolute;
        const copyBtn = _el('button', 'btn share-btn-primary', t('copy') || '复制');
        copyBtn.type = 'button';
        copyBtn.onclick = async () => {
          try {
            await navigator.clipboard.writeText(absolute);
            showToast(t('copied') || '已复制', 1600);
          } catch (_) {
            linkText.select();
          }
        };
        const row = _el('div', 'share-input-row');
        row.appendChild(linkText);
        row.appendChild(copyBtn);
        linkOut.appendChild(row);
        linkOut.hidden = false;
      } catch (e) {
        showToast(((e && e.message) || String(e)), 3000, 'error');
      } finally {
        genBtn.disabled = false;
      }
    };
    body.appendChild(secLink);

    // ── Section 3: existing shares ──
    const secList = _el('div', 'share-section');
    secList.appendChild(_el('div', 'share-section-title', t('share_existing') || '已分享'));
    const listBox = _el('div', 'share-existing-list');
    listBox.appendChild(_el('div', 'share-loading', t('loading') || '加载中…'));
    secList.appendChild(listBox);
    body.appendChild(secList);

    try {
      const data = await api(`/api/sessions/${encodeURIComponent(sid)}/shares`);
      const shares = (data && data.shares) || [];
      listBox.innerHTML = '';
      if (!shares.length) {
        listBox.appendChild(_el('div', 'share-empty', t('share_none') || '尚未分享'));
        return;
      }
      for (const share of shares) {
        const row = _el('div', 'share-existing-row');
        const label = share.type === 'token'
          ? (t('share_link_label') || '链接')
          : (share.to_username || share.to_user_id || '');
        const kind = _el('span', 'share-existing-kind', share.type === 'token' ? '🔗' : '👤');
        const name = _el('span', 'share-existing-name', label);
        const revoke = _el('button', 'share-revoke-btn', t('share_revoke') || '撤销');
        revoke.type = 'button';
        revoke.onclick = async () => {
          revoke.disabled = true;
          try {
            await api(`/api/sessions/${encodeURIComponent(sid)}/share/${encodeURIComponent(share.id)}`, {
              method: 'DELETE',
            });
            showToast(t('share_revoked') || '已撤销', 2000);
            await _renderShareDialogBody(body, session);
          } catch (e) {
            showToast(((e && e.message) || String(e)), 3000, 'error');
            revoke.disabled = false;
          }
        };
        row.appendChild(kind);
        row.appendChild(name);
        row.appendChild(revoke);
        listBox.appendChild(row);
      }
    } catch (e) {
      listBox.innerHTML = '';
      listBox.appendChild(_el('div', 'share-error', (e && e.message) || String(e)));
    }
  }

  // ── "收到的分享" sidebar section ──────────────────────────────────────────
  let _sharedSessions = [];
  let _sharedLoaded = false;
  let _sharedSessionsUserId = '';

  function _clearSharedSessionsCache(removeSection) {
    _sharedSessions = [];
    _sharedLoaded = false;
    _sharedSessionsUserId = '';
    if (removeSection) {
      const section = document.getElementById('sharedSessionsSection');
      if (section) section.remove();
    }
  }

  async function loadSharedSessions(force) {
    const user = await currentUser();
    if (!user) {
      _sharedSessions = [];
      _sharedLoaded = true;
      _sharedSessionsUserId = '';
      return _sharedSessions;
    }
    const userId = String(user.id || '').trim();
    if (_sharedLoaded && !force && _sharedSessionsUserId === userId) return _sharedSessions;
    try {
      const data = await api('/api/sessions/shared', { timeoutMs: 8000, timeoutToast: false });
      _sharedSessions = (data && data.shared) || [];
    } catch (_) {
      _sharedSessions = [];
    }
    _sharedLoaded = true;
    _sharedSessionsUserId = userId;
    return _sharedSessions;
  }

  function _renderSharedSection() {
    // Remove any previous render.
    const prev = document.getElementById('sharedSessionsSection');
    if (prev) prev.remove();
    const list = document.getElementById('sessionList');
    if (!list) return;

    const section = _el('div', 'shared-sessions-section');
    section.id = 'sharedSessionsSection';
    const head = _el('div', 'shared-sessions-head');
    head.appendChild(_el('span', 'shared-sessions-title',
      (t('share_incoming_title') || '收到的分享') + ' (' + _sharedSessions.length + ')'));
    section.appendChild(head);

    if (!_sharedSessions.length) {
      // Show an empty hint so the user knows the feature exists.
      const empty = _el('div', 'share-empty');
      empty.textContent = t('share_none') || 'No incoming shares';
      section.appendChild(empty);
      list.appendChild(section);
      return;
    }

    for (const item of _sharedSessions) {
      const sess = item.session || {};
      const row = _el('div', 'session-row shared-session-row');
      row.dataset.sessionId = sess.session_id || '';
      const main = _el('div', 'session-row-main');
      const title = _el('div', 'session-row-title', sess.title || t('untitled') || 'Untitled');
      const sub = _el('div', 'session-row-sub shared-session-sub');
      sub.appendChild(_el('span', 'shared-from',
        (t('shared_from') || '来自 {name} 的分享').replace('{name}', item.from_username || '')));
      const badge = _el('span', 'shared-readonly-badge', t('readonly') || '只读');
      main.appendChild(title);
      main.appendChild(sub);
      row.appendChild(main);
      row.appendChild(badge);
      row.onclick = () => {
        if (sess.session_id && typeof loadSession === 'function') {
          loadSession(sess.session_id);
        }
      };
      section.appendChild(row);
    }
    list.appendChild(section);
  }

  async function refreshSharedSessionsSection(force) {
    await loadSharedSessions(force);
    _renderSharedSection();
  }

  // ── Read-only view for shared sessions ────────────────────────────────────
  let _readOnlyBanner = null;

  function isCurrentSessionSharedReadOnly() {
    return !!(window.S && S.session && S.session.viewer === 'shared');
  }

  function applySharedReadOnlyState() {
    const shared = isCurrentSessionSharedReadOnly();
    const msg = document.getElementById('msg');
    const composer = msg && msg.closest('.composer, #composer, form');
    const sharedBy = shared && S.session.shared_by ? S.session.shared_by : '';

    if (shared) {
      if (!_readOnlyBanner) {
        _readOnlyBanner = _el('div', 'shared-readonly-banner');
        _readOnlyBanner.id = 'sharedReadonlyBanner';
      }
      _readOnlyBanner.textContent =
        (t('shared_readonly_banner') || '此会话由 {name} 分享，只读').replace('{name}', sharedBy);
      const msgInner = document.getElementById('msgInner');
      if (msgInner && !_readOnlyBanner.isConnected) {
        msgInner.prepend(_readOnlyBanner);
      }
      if (msg) {
        msg.disabled = true;
        msg.placeholder = t('shared_readonly_composer') || '只读会话，无法发送消息';
      }
      if (composer) composer.classList.add('composer-readonly');
      if (typeof updateSendBtn === 'function') updateSendBtn();
    } else {
      if (_readOnlyBanner && _readOnlyBanner.isConnected) _readOnlyBanner.remove();
      if (msg && msg.disabled) {
        msg.disabled = false;
        msg.placeholder = msg.getAttribute('data-default-placeholder') || 'Message Hermes…';
      }
      if (composer) composer.classList.remove('composer-readonly');
      if (typeof updateSendBtn === 'function') updateSendBtn();
    }
  }

  // ── Wire into session loading ─────────────────────────────────────────────
  function _wrapLoadSession() {
    if (typeof loadSession !== 'function' || loadSession._shareWrapped) return;
    const orig = loadSession;
    const wrapped = function () {
      return orig.apply(this, arguments).then((result) => {
        try { applySharedReadOnlyState(); } catch (_) {}
        return result;
      }, (err) => {
        try { applySharedReadOnlyState(); } catch (_) {}
        throw err;
      });
    };
    wrapped._shareWrapped = true;
    window.loadSession = wrapped;
  }

  // Remember the default composer placeholder once at boot.
  function _captureDefaultPlaceholder() {
    const msg = document.getElementById('msg');
    if (msg && !msg.getAttribute('data-default-placeholder')) {
      msg.setAttribute('data-default-placeholder', msg.placeholder || 'Message Hermes…');
    }
  }

  // ── Sidebar render hook: append the shared section after each list render ──
  function _wrapRenderSessionList() {
    if (typeof renderSessionListFromCache !== 'function' || renderSessionListFromCache._shareWrapped) return;
    const orig = renderSessionListFromCache;
    const wrapped = function () {
      const result = orig.apply(this, arguments);
      try { _renderSharedSection(); } catch (_) {}
      return result;
    };
    wrapped._shareWrapped = true;
    window.renderSessionListFromCache = wrapped;
  }

  // Refresh shared list when the server signals session changes. Use an
  // independent lightweight EventSource so we don't interfere with
  // sessions.js's own SSE management.
  function _subscribeSessionEvents() {
    if (typeof EventSource === 'undefined') return;
    let es = null;
    let reconnectTimer = 0;
    const connect = () => {
      if (document.hidden) return;
      try {
        es = new EventSource('api/sessions/events');
        es.addEventListener('sessions_changed', () => {
          _sharedLoaded = false;
          loadSharedSessions(true).then(_renderSharedSection).catch(() => {});
        });
        es.onerror = () => {
          try { es && es.close(); } catch (_) {}
          es = null;
          if (!reconnectTimer) {
            reconnectTimer = setTimeout(() => {
              reconnectTimer = 0;
              connect();
            }, 5000);
          }
        };
      } catch (_) {}
    };
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        try { es && es.close(); } catch (_) {}
        es = null;
      } else {
        connect();
      }
    });
    connect();
  }

  function init() {
    _captureDefaultPlaceholder();
    _wrapLoadSession();
    _wrapRenderSessionList();
  }

  let _initialSharedSessionsStarted = false;
  function _startInitialSharedSessions() {
    if (_initialSharedSessionsStarted) return;
    _initialSharedSessionsStarted = true;
    loadSharedSessions(false).then(() => {
      _renderSharedSection();
    }).catch(() => {});
    _subscribeSessionEvents();
  }

  // Shared rows are secondary sidebar content. Keep their auth request and
  // independent EventSource out of the six-connection initial-load budget.
  window.addEventListener('hermes:session-list-ready', _startInitialSharedSessions, { once: true });
  setTimeout(_startInitialSharedSessions, 8000);

  // Public API
  window.openShareDialog = openShareDialog;
  window.closeShareDialog = closeShareDialog;
  window.canShareSession = canShareSession;
  window.refreshSharedSessionsSection = refreshSharedSessionsSection;
  window.applySharedReadOnlyState = applySharedReadOnlyState;
  window.isCurrentSessionSharedReadOnly = isCurrentSessionSharedReadOnly;
  window._resetShareCurrentUser = _resetCurrentUser;

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
