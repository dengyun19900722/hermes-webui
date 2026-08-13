/* Users admin panel — manages users + audit log + panel permissions.
 *
 * Lives in Settings → Users (alongside Appearance / Preferences).
 * Backed by /api/admin/users and /api/admin/audit (admin-only).
 *
 * Conventions:
 *   - XSS-safe: all user-supplied text goes through escapeHtml()
 *   - Reuses existing CSS tokens (settings-pane / settings-section-head /
 *     settings-field / btn), no new colors or radii
 *   - Lazy-loaded by panels.js's switchSettingsSection → loadUsersPanel()
 */
(function () {
  function escapeHtml(s) {
    var div = document.createElement('div');
    div.textContent = s == null ? '' : String(s);
    return div.innerHTML;
  }

  function t(key, fallback) {
    if (window.t) {
      var value = window.t(key);
      return value === key && fallback ? fallback : value;
    }
    return fallback || key;
  }

  function api(path, opts) {
    if (window.api) return window.api(path, opts);
    opts = opts || {};
    opts.credentials = 'same-origin';
    if (opts.body && typeof opts.body !== 'string') {
      opts.headers = Object.assign({'Content-Type': 'application/json'}, opts.headers || {});
      opts.body = JSON.stringify(opts.body);
    }
    return fetch(path, opts).then(function (r) {
      var p = r.json().catch(function () { return {}; });
      return p.then(function (data) {
        if (!r.ok) throw new Error(data.error || ('HTTP ' + r.status));
        return data;
      });
    });
  }

  /* ── All available panels (same as index.html rail/data-panel values) ── */
  var ALL_PANELS = [
    'chat', 'tasks', 'kanban', 'skills', 'knowledge',
    'memory', 'workspaces', 'profiles', 'todos', 'insights',
    'dashboard', 'logs',
  ];
  var PANEL_LABELS = {
    chat: '会话', tasks: '定时任务', kanban: '看板',
    skills: '技能', knowledge: '知识库', memory: '记忆',
    workspaces: '工作区', profiles: '配置文件', todos: '待办',
    insights: '洞察', dashboard: '仪表板', logs: '日志',
  };

  function renderUserRow(u) {
    var isSelf = u.username === (window.currentUsername || '');
    var roleBadge = u.role === 'admin'
      ? '<span class="badge badge-admin">' + escapeHtml(t('users_role_admin', 'Admin')) + '</span>'
      : '<span class="badge badge-user">' + escapeHtml(t('users_role_user', 'User')) + '</span>';
    var lastLogin = u.last_login
      ? escapeHtml(new Date(u.last_login).toLocaleString())
      : escapeHtml(t('users_never_logged_in', 'never'));
    var deleteBtn = isSelf
      ? '<button class="settings-action-btn" disabled title="' + escapeHtml(t('users_cannot_delete_self', 'Cannot delete yourself')) + '">' + escapeHtml(t('delete', 'Delete')) + '</button>'
      : '<button class="settings-action-btn danger" data-action="delete-user" data-id="' + escapeHtml(u.id) + '" data-name="' + escapeHtml(u.username) + '">' + escapeHtml(t('delete', 'Delete')) + '</button>';
    var panelsCount = Array.isArray(u.panels) ? u.panels.length : 0;
    var resetPasswordBtn = '<button class="action-btn settings-action-btn" data-action="reset-password" data-user-id="' + escapeHtml(u.id) + '" data-username="' + escapeHtml(u.username) + '">' + escapeHtml(t('admin_reset_password', 'Reset password')) + '</button>';
    return '<tr data-user-id="' + escapeHtml(u.id) + '">'
      + '<td>' + escapeHtml(u.username) + '</td>'
      + '<td>' + roleBadge + '</td>'
      + '<td>' + lastLogin + '</td>'
      + '<td class="users-actions">'
      +   '<button class="settings-action-btn" data-action="toggle-role" data-id="' + escapeHtml(u.id) + '" data-current="' + escapeHtml(u.role) + '">'
      +     escapeHtml(u.role === 'admin' ? t('users_demote', 'Demote') : t('users_promote', 'Promote'))
      +   '</button>'
      +   '<button class="settings-action-btn" data-action="edit-panels" data-id="' + escapeHtml(u.id) + '" data-username="' + escapeHtml(u.username) + '" title="编辑可访问的面板">面板(' + panelsCount + ')</button>'
      +   resetPasswordBtn
      +   deleteBtn
      + '</td>'
      + '</tr>';
  }

  function currentAuthUserMatches(userId, user) {
    var id = String(userId || (user && user.id) || '').trim();
    var currentId = String(window.currentUserId || '').trim();
    var currentIdentity = String(window._currentAuthUserId || '').trim();
    if (id && currentId && id === currentId) return true;
    if (id && currentIdentity && (currentIdentity === id || currentIdentity === ('user:' + id))) return true;
    var username = String((user && user.username) || '').trim();
    var currentUsername = String(window.currentUsername || '').trim();
    if (username && currentIdentity === ('user:' + username)) return true;
    return !!(username && currentUsername && username === currentUsername);
  }

  async function refreshCurrentAuthAfterUserMutation(userId, user) {
    if (!currentAuthUserMatches(userId, user)) return;
    var status = null;
    try {
      if (typeof window.syncAuthIdentityScope === 'function') {
        status = await window.syncAuthIdentityScope({ force: true, clearOnChange: false });
      } else {
        status = await api('/api/auth/status', { redirect401: false });
      }
    } catch (_) {}
    if (status) renderCurrentAccount(status);
    if (typeof window._applyTabVisibility === 'function' && typeof window._getHiddenTabs === 'function') {
      try { window._applyTabVisibility(window._getHiddenTabs()); } catch (_) {}
    }
    if (typeof window.renderSessionListFromCache === 'function') {
      try { window.renderSessionListFromCache(); } catch (_) {}
    }
  }

  function renderAuditRow(e) {
    var ts = e.ts || e.timestamp || '';
    var detail = '';
    if (e.details && Object.keys(e.details).length) {
      try { detail = ' ' + JSON.stringify(e.details); } catch (_) {}
    }
    return '<tr class="users-audit-row">'
      + '<td class="users-audit-time">' + escapeHtml(ts) + '</td>'
      + '<td>' + escapeHtml(e.actor_name || e.actor_id || '-') + '</td>'
      + '<td>' + escapeHtml(e.action || '-') + '</td>'
      + '<td>' + escapeHtml(e.target_name || e.target_id || '-') + detail + '</td>'
      + '</tr>';
  }

  function renderPanel() {
    var pane = document.getElementById('settingsPaneUsers');
    if (!pane) return;
    pane.innerHTML =
      // ── Page header ────────────────────────────────────────────────────
      '<div class="settings-section-head">'
        + '<div>'
          + '<div class="settings-section-title" data-i18n="settings_section_users_title">Users</div>'
          + '<div class="settings-section-meta" data-i18n="settings_section_users_meta">Manage user accounts and review audit log. Admin only.</div>'
        + '</div>'
      + '</div>'
      // ── Current account ─────────────────────────────────────────────────
      + '<div class="settings-field users-section users-account-section" id="users-account-section">'
        + '<div class="users-account-main">'
          + '<div>'
            + '<label data-i18n="users_current_account">Current account</label>'
            + '<div id="users-current-account" class="users-current-account">' + escapeHtml(t('loading', 'Loading…')) + '</div>'
          + '</div>'
          + '<button class="settings-action-btn" id="users-sign-out-btn" data-action="sign-out" hidden>' + escapeHtml(t('sign_out', 'Sign Out')) + '</button>'
        + '</div>'
      + '</div>'
      // ── Create user ─────────────────────────────────────────────────────
      + '<div class="settings-field users-section">'
        + '<label data-i18n="users_create_heading">Add user</label>'
        + '<div class="users-create-row">'
          + '<input type="text" id="users-new-username" placeholder="username" pattern="[A-Za-z0-9_.\-]{3,32}" minlength="3" maxlength="32" required>'
          + '<input type="password" id="users-new-password" placeholder="password (≥8 chars)" minlength="8" required>'
          + '<select id="users-new-role"><option value="user">user</option><option value="admin">admin</option></select>'
          + '<button class="settings-action-btn primary" id="users-create-btn" data-i18n="users_create_btn">Create</button>'
        + '</div>'
        + '<div id="users-create-error" class="settings-error" hidden></div>'
      + '</div>'
      // ── Users table ─────────────────────────────────────────────────────
      + '<div class="settings-field users-section">'
        + '<label data-i18n="users_list_heading">All users</label>'
        + '<table class="settings-table users-table">'
        + '<thead><tr>'
          + '<th data-i18n="users_col_username">Username</th>'
          + '<th data-i18n="users_col_role">Role</th>'
          + '<th data-i18n="users_col_last_login">Last login</th>'
          + '<th data-i18n="users_col_actions">Actions</th>'
        + '</tr></thead>'
        + '<tbody id="users-tbody"><tr><td colspan="4" data-i18n="loading">' + escapeHtml(t('loading', 'Loading…')) + '</td></tr></tbody>'
        + '</table>'
        + '<div id="users-list-error" class="settings-error" hidden></div>'
      + '</div>'
      // ── Audit log ───────────────────────────────────────────────────────
      + '<div class="settings-field users-section">'
        + '<label data-i18n="users_audit_heading">Recent audit log (last 50)</label>'
        + '<table class="settings-table users-audit-table">'
          + '<thead><tr>'
            + '<th data-i18n="users_audit_time">Time</th>'
            + '<th data-i18n="users_audit_actor">Actor</th>'
            + '<th data-i18n="users_audit_action">Action</th>'
            + '<th data-i18n="users_audit_target">Target</th>'
          + '</tr></thead>'
          + '<tbody id="users-audit-tbody"><tr><td colspan="4">' + escapeHtml(t('loading', 'Loading…')) + '</td></tr></tbody>'
        + '</table>'
      + '</div>'
      // ── Panel editor modal (hidden) ─────────────────────────────────────
      + '<div id="users-panels-modal" class="users-panels-modal" style="display:none" onclick="if(event.target===this)closePanelsEditor()">'
        + '<div class="users-panels-modal-content">'
          + '<div class="users-panels-modal-header">'
            + '<span id="users-panels-modal-title">编辑面板权限</span>'
            + '<button class="settings-action-btn" onclick="closePanelsEditor()" style="padding:2px 8px">✕</button>'
          + '</div>'
          + '<div id="users-panels-modal-body" class="users-panels-modal-body"></div>'
          + '<div class="users-panels-modal-footer">'
            + '<button class="settings-action-btn" onclick="closePanelsEditor()">取消</button>'
            + '<button class="settings-action-btn primary" id="users-panels-save-btn" onclick="savePanelsEditor()">保存</button>'
          + '</div>'
        + '</div>'
      + '</div>';
  }

  /* ── Panel editor state ────────────────────────────────────────────── */
  var _editingUserId = '';
  var _editingPanels = [];

  window.closePanelsEditor = function () {
    var modal = document.getElementById('users-panels-modal');
    if (modal) modal.style.display = 'none';
    _editingUserId = '';
    _editingPanels = [];
  };

  window.savePanelsEditor = async function () {
    if (!_editingUserId) return;
    var targetUserId = _editingUserId;
    var saveBtn = document.getElementById('users-panels-save-btn');
    if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = '保存中…'; }
    try {
      var result = await api('/api/admin/users/' + encodeURIComponent(targetUserId) + '/panels', {
        method: 'PUT', body: { panels: _editingPanels },
      });
      closePanelsEditor();
      await refreshCurrentAuthAfterUserMutation(targetUserId, result && result.user);
      await loadUsers();
      await loadAudit();
    } catch (e) {
      window.alert('保存失败：' + (e.message || String(e)));
    } finally {
      if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = '保存'; }
    }
  };

  function openPanelsEditor(userId, username, currentPanels) {
    _editingUserId = userId;
    _editingPanels = Array.isArray(currentPanels) ? currentPanels.slice() : [];

    var modal = document.getElementById('users-panels-modal');
    var titleEl = document.getElementById('users-panels-modal-title');
    var bodyEl = document.getElementById('users-panels-modal-body');
    if (titleEl) titleEl.textContent = '编辑面板权限 - ' + (username || userId);
    if (bodyEl) {
      bodyEl.innerHTML = '<div class="users-panels-hint">选择此用户可以访问的面板（admin 不受限制）</div>'
        + '<div class="users-panels-grid">'
        + ALL_PANELS.map(function (p) {
            var checked = _editingPanels.indexOf(p) !== -1 ? 'checked' : '';
            var label = PANEL_LABELS[p] || p;
            return '<label class="users-panels-item">'
              + '<input type="checkbox" value="' + p + '" ' + checked + ' onchange="togglePanelPerm(this)">'
              + '<span>' + escapeHtml(label) + '</span>'
              + '</label>';
          }).join('')
        + '</div>';
    }
    if (modal) modal.style.display = '';
  }

  window.togglePanelPerm = function (el) {
    var panel = el && el.value;
    if (!panel) return;
    var idx = _editingPanels.indexOf(panel);
    if (el.checked && idx === -1) {
      _editingPanels.push(panel);
    } else if (!el.checked && idx !== -1) {
      _editingPanels.splice(idx, 1);
    }
  };

  function showError(elId, msg) {
    var el = document.getElementById(elId);
    if (el) { el.textContent = msg; el.hidden = false; }
  }

  function hideError(elId) {
    var el = document.getElementById(elId);
    if (el) el.hidden = true;
  }

  async function loadUsers() {
    var tbody = document.getElementById('users-tbody');
    if (!tbody) return;
    hideError('users-list-error');
    try {
      var data = await api('/api/admin/users');
      var users = data.users || [];
      if (!users.length) {
        tbody.innerHTML = '<tr><td colspan="4" data-i18n="users_none">No users.</td></tr>';
        return;
      }
      tbody.innerHTML = users.map(renderUserRow).join('');
    } catch (e) {
      tbody.innerHTML = '';
      showError('users-list-error', e.message || String(e));
    }
  }

  function renderCurrentAccount(status) {
    var el = document.getElementById('users-current-account');
    var signOutBtn = document.getElementById('users-sign-out-btn');
    if (!el) return;
    var user = status && status.user;
    if (user && user.username) {
      window.currentUserId = user.id || '';
      window.currentUsername = user.username;
      el.innerHTML = '<strong>' + escapeHtml(user.username) + '</strong>'
        + '<span class="users-current-role">' + escapeHtml(user.role || 'user') + '</span>';
      if (signOutBtn) signOutBtn.hidden = false;
      return;
    }
    window.currentUserId = '';
    window.currentUsername = '';
    el.textContent = status && status.logged_in
      ? t('users_current_account_password_auth', 'Signed in with instance password')
      : t('auth_status_unauthenticated', 'Unauthenticated');
    if (signOutBtn) signOutBtn.hidden = !(status && status.logged_in);
  }

  async function loadCurrentAccount() {
    try {
      var status = await api('/api/auth/status', { redirect401: false });
      renderCurrentAccount(status || {});
    } catch (e) {
      renderCurrentAccount(null);
    }
  }

  async function loadAudit() {
    var tbody = document.getElementById('users-audit-tbody');
    if (!tbody) return;
    try {
      var data = await api('/api/admin/audit?limit=50');
      var events = data.events || [];
      if (!events.length) {
        tbody.innerHTML = '<tr><td colspan="4" data-i18n="users_audit_none">No audit events yet.</td></tr>';
        return;
      }
      tbody.innerHTML = events.map(renderAuditRow).join('');
    } catch (e) {
      tbody.innerHTML = '<tr><td colspan="4">' + escapeHtml(e.message || String(e)) + '</td></tr>';
    }
  }

  async function createUser() {
    hideError('users-create-error');
    var usernameEl = document.getElementById('users-new-username');
    var passwordEl = document.getElementById('users-new-password');
    var roleEl = document.getElementById('users-new-role');
    if (!usernameEl || !passwordEl || !roleEl) return;
    var username = usernameEl.value.trim();
    var password = passwordEl.value;
    var role = roleEl.value;
    if (!username || !password) {
      showError('users-create-error', 'username and password required');
      return;
    }
    try {
      await api('/api/admin/users', { method: 'POST', body: { username: username, password: password, role: role } });
      usernameEl.value = '';
      passwordEl.value = '';
      await loadUsers();
      await loadAudit();
    } catch (e) {
      showError('users-create-error', e.message || String(e));
    }
  }

  async function toggleRole(userId, currentRole) {
    var newRole = currentRole === 'admin' ? 'user' : 'admin';
    try {
      var result = await api('/api/admin/users/' + encodeURIComponent(userId) + '/role', {
        method: 'PUT', body: { role: newRole },
      });
      await refreshCurrentAuthAfterUserMutation(userId, result && result.user);
      await loadUsers();
      await loadAudit();
    } catch (e) {
      window.alert(e.message || String(e));
    }
  }

  async function resetPassword(userId, username) {
    var title = formatResetPasswordMessage('admin_reset_password_title', username);
    var hint = t('admin_reset_password_hint', 'Admin reset skips old password check and signs out other sessions');
    var newPassword;

    // Prefer the shared application modal; keep prompt() as a compatibility
    // fallback for stripped-down/test pages that do not render appDialogOverlay.
    if (typeof window.showPromptDialog === 'function' && document.getElementById('appDialogOverlay')) {
      newPassword = await window.showPromptDialog({
        title: title,
        message: hint,
        inputType: 'password',
        confirmLabel: t('change_password_submit', 'Submit'),
        cancelLabel: t('change_password_cancel', 'Cancel'),
      });
    } else if (typeof window.prompt === 'function') {
      newPassword = window.prompt(title + '\n\n' + hint);
    }
    if (!newPassword) return;

    try {
      await api('/api/admin/users/' + encodeURIComponent(userId) + '/password', {
        method: 'PUT',
        body: { new_password: newPassword },
      });
      if (typeof window.showToast === 'function') {
        window.showToast(formatResetPasswordMessage('admin_reset_password_ok', username));
      }
      // The reset creates an audit event; refresh that table without making a
      // successful password reset appear to fail if the refresh is unavailable.
      loadAudit();
    } catch (e) {
      var message = 'Error: ' + (e && e.message ? e.message : String(e));
      if (typeof window.showToast === 'function') {
        window.showToast(message, 5000, 'error');
      } else if (typeof window.alert === 'function') {
        window.alert(message);
      }
    }
  }

  function formatResetPasswordMessage(key, username) {
    return String(t(key, '')).replace(/\{username\}/g, username == null ? '' : String(username));
  }

  async function deleteUser(userId, name) {
    if (!window.confirm('Delete user "' + name + '"? This cannot be undone.')) return;
    try {
      await api('/api/admin/users/' + encodeURIComponent(userId), { method: 'DELETE' });
      await loadUsers();
      await loadAudit();
    } catch (e) {
      window.alert(e.message || String(e));
    }
  }

  async function signOutUser() {
    try {
      if (typeof window.signOut === 'function') {
        await window.signOut();
        return;
      }
      await api('/api/auth/logout', { method: 'POST', body: '{}' });
      window.location.href = 'login';
    } catch (e) {
      showError('users-list-error', (t('sign_out_failed', 'Sign out failed: ')) + (e.message || String(e)));
    }
  }

  /* ── Fetch user data to open panel editor ─────────────────────────── */
  async function editPanels(userId, username) {
    try {
      var data = await api('/api/admin/users');
      var users = data.users || [];
      var u = null;
      for (var i = 0; i < users.length; i++) {
        if (users[i].id === userId) { u = users[i]; break; }
      }
      if (!u) throw new Error('User not found');
      openPanelsEditor(userId, username, u.panels);
    } catch (e) {
      window.alert('加载用户信息失败：' + (e.message || String(e)));
    }
  }

  function bindActions() {
    var pane = document.getElementById('settingsPaneUsers');
    if (!pane) return;
    var createBtn = document.getElementById('users-create-btn');
    if (createBtn && !createBtn.dataset.bound) {
      createBtn.dataset.bound = '1';
      createBtn.addEventListener('click', createUser);
    }
    pane.addEventListener('click', function (e) {
      var btn = e.target.closest && e.target.closest('[data-action]');
      if (!btn) return;
      var action = btn.getAttribute('data-action');
      if (action === 'reset-password') {
        e.preventDefault();
        resetPassword(btn.getAttribute('data-user-id'), btn.getAttribute('data-username'));
        return;
      }
      var id = btn.getAttribute('data-id');
      if (action === 'toggle-role') {
        toggleRole(id, btn.getAttribute('data-current'));
      } else if (action === 'delete-user') {
        deleteUser(id, btn.getAttribute('data-name'));
      } else if (action === 'sign-out') {
        signOutUser();
      } else if (action === 'edit-panels') {
        editPanels(id, btn.getAttribute('data-username'));
      }
    });
  }

  async function loadUsersPanel() {
    renderPanel();
    bindActions();
    await loadCurrentAccount();
    await Promise.all([loadUsers(), loadAudit()]);
  }

  // Expose to panels.js lazy-load contract
  window.loadUsersPanel = loadUsersPanel;
  window.openResetPasswordDialog = resetPassword;
})();
