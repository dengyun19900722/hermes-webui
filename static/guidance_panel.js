/* Guidance Center panel — 实施助手 2.1 设置页入口。
 *
 * Lives in Settings → 引导中心 (alongside Appearance / Preferences / Users).
 * Backed by /api/guidance/implementation (admin/ops only).
 *
 * Conventions:
 *   - XSS-safe: all server text goes through escapeHtml()
 *   - Reuses existing CSS tokens (settings-pane / settings-section-head /
 *     settings-field / btn), no new colors or radii
 *   - Lazy-loaded by panels.js's switchSettingsSection → loadGuidancePanel()
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
      opts.headers = Object.assign({ 'Content-Type': 'application/json' }, opts.headers || {});
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

  function openGuidanceCenter() {
    // 打开全屏实施助手页（manual_nav 绕过 dismissed 抑制）
    if (window.GuidanceManager && !window.__guidanceMgr) {
      try { window.GuidanceManager.init(); } catch (e) {}
    }
    if (window.__guidanceMgr) {
      try { window.__guidanceMgr.evaluate('manual_nav', {}); return; } catch (e) {}
    }
    // GuidanceManager 未加载（脚本被禁用/失败）时的兜底
    alert(t('guidance_2_1_load_failed', '实施助手加载失败，请刷新页面重试'));
  }

  function renderPanel(state) {
    var pane = document.getElementById('settingsPaneGuidance');
    if (!pane) return;

    var summary = state && state.summary ? state.summary : { total: 0, done: 0 };
    var pct = summary.total ? Math.round(summary.done / summary.total * 100) : 0;
    var deploymentId = state && state.deployment_id ? state.deployment_id : '—';

    var groupsHtml = '';
    if (state && Array.isArray(state.tasks)) {
      var groupTitles = {};
      state.tasks.forEach(function (task) {
        if (!groupTitles[task.group]) groupTitles[task.group] = task.group_title || ('Group ' + task.group);
      });
      groupsHtml = Object.keys(groupTitles).map(function (g) {
        var tasks = state.tasks.filter(function (t) { return String(t.group) === String(g); });
        var done = tasks.filter(function (t) { return t.done; }).length;
        return '<div class="settings-field">'
          + '<div style="display:flex;justify-content:space-between;align-items:center;gap:8px">'
          + '<span style="font-weight:600">' + escapeHtml(groupTitles[g]) + '</span>'
          + '<span class="guidance-group-count">' + done + '/' + tasks.length + '</span>'
          + '</div></div>';
      }).join('');
    }

    pane.innerHTML = ''
      + '<div class="settings-section-head">'
      + '<div>'
      + '<div class="settings-section-title" data-i18n="guidance_sidebar_entry">引导中心</div>'
      + '<div class="settings-section-desc">' + escapeHtml(t('guidance_2_1_panel_desc', '实施助手用于追踪 ZK 运维智能体部署落地的关键检查项与进度。')) + '</div>'
      + '</div>'
      + '</div>'

      + '<div class="settings-field">'
      + '<div class="guidance-overview" style="display:flex;gap:24px;flex-wrap:wrap;padding:8px 0">'
      + '<div><div class="guidance-stat-num">' + summary.done + '/' + summary.total + '</div>'
      + '<div class="guidance-stat-label">' + escapeHtml(t('guidance_2_1_progress_label', '总进度')) + '</div></div>'
      + '<div><div class="guidance-stat-num">' + pct + '%</div>'
      + '<div class="guidance-stat-label">' + escapeHtml(t('guidance_2_1_completed_pct', '完成度')) + '</div></div>'
      + '<div><div class="guidance-stat-num" style="font-size:14px">' + escapeHtml(deploymentId) + '</div>'
      + '<div class="guidance-stat-label">' + escapeHtml(t('guidance_2_1_deployment_id', '部署 ID')) + '</div></div>'
      + '</div>'
      + '</div>'

      + '<div class="settings-field" style="margin-top:4px">'
      + '<button class="sm-btn" onclick="window.__openGuidanceCenter && window.__openGuidanceCenter()" '
      + 'style="width:100%;padding:9px;font-weight:600" data-i18n="guidance_2_1_open">打开实施助手</button>'
      + '</div>'

      + '<div class="settings-section-head" style="margin-top:16px">'
      + '<div><div class="settings-section-title">' + escapeHtml(t('guidance_2_1_groups', '分组进度')) + '</div></div>'
      + '</div>'
      + groupsHtml;

    // 绑定手动入口
    window.__openGuidanceCenter = openGuidanceCenter;
  }

  function renderError(msg) {
    var pane = document.getElementById('settingsPaneGuidance');
    if (!pane) return;
    pane.innerHTML = '<div class="settings-section-head">'
      + '<div><div class="settings-section-title">引导中心</div></div></div>'
      + '<div style="padding:24px;text-align:center;color:var(--muted)">' + escapeHtml(msg) + '</div>';
  }

  async function loadGuidancePanel() {
    var pane = document.getElementById('settingsPaneGuidance');
    if (!pane) return;
    pane.innerHTML = '<div class="settings-section-head">'
      + '<div><div class="settings-section-title">引导中心</div></div></div>'
      + '<div style="padding:24px;text-align:center;color:var(--muted)">' + escapeHtml(t('loading', '加载中…')) + '</div>';
    try {
      var state = await api('/api/guidance/implementation');
      renderPanel(state);
    } catch (e) {
      renderError((e && e.message) || 'Failed to load');
    }
  }

  // Expose to panels.js lazy-load contract
  window.loadGuidancePanel = loadGuidancePanel;
  window.__openGuidanceCenter = openGuidanceCenter;
})();
