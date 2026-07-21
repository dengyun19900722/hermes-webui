/* Users admin panel — manages users + audit log.
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
    if (window.t) return window.t(key);
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
    return '<tr data-user-id="' + escapeHtml(u.id) + '">'
      + '<td>' + escapeHtml(u.username) + '</td>'
      + '<td>' + roleBadge + '</td>'
      + '<td>' + lastLogin + '</td>'
      + '<td class="users-actions">'
      +   '<button class="settings-action-btn" data-action="toggle-role" data-id="' + escapeHtml(u.id) + '" data-current="' + escapeHtml(u.role) + '">'
      +     escapeHtml(u.role === 'admin' ? t('users_demote', 'Demote') : t('users_promote', 'Promote'))
      +   '</button>'
      +   deleteBtn
      + '</td>'
      + '</tr>';
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
      + '</div>';
  }

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
      await api('/api/admin/users/' + encodeURIComponent(userId) + '/role', {
        method: 'PUT', body: { role: newRole },
      });
      await loadUsers();
      await loadAudit();
    } catch (e) {
      window.alert(e.message || String(e));
    }
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
      var id = btn.getAttribute('data-id');
      if (action === 'toggle-role') {
        toggleRole(id, btn.getAttribute('data-current'));
      } else if (action === 'delete-user') {
        deleteUser(id, btn.getAttribute('data-name'));
      }
    });
  }

  async function loadUsersPanel() {
    renderPanel();
    bindActions();
    await Promise.all([loadUsers(), loadAudit()]);
  }

  // 暴露给 panels.js 懒加载契约
  window.loadUsersPanel = loadUsersPanel;
})();