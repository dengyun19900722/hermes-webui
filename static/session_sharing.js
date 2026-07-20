/* Session sharing UI.
 *
 * Renders two sections:
 *   .own-sessions    — sessions owned by the current user
 *   .shared-sessions — sessions other users shared to the current user
 *
 * Each own session has a 分享 button that opens a small dialog asking
 * for either a target username (user-to-user share) or the literal
 * "link" to generate a share-token URL.
 */
(function () {
  function escapeHtml(s) {
    var div = document.createElement('div');
    div.textContent = s == null ? '' : String(s);
    return div.innerHTML;
  }

  function loadSessions() {
    return fetch('/api/sessions', { credentials: 'same-origin' })
      .then(function (r) {
        if (!r.ok) return { own: [], shared: [] };
        return r.json();
      })
      .catch(function () { return { own: [], shared: [] }; });
  }

  function shareSessionToUser(sessionId, username) {
    return fetch('/api/sessions/' + encodeURIComponent(sessionId) + '/share', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ username: username }),
    }).then(function (r) {
      if (!r.ok) {
        return r.json().catch(function () { return {}; }).then(function (e) {
          throw new Error(e.error || ('HTTP ' + r.status));
        });
      }
      return r.json();
    });
  }

  function shareSessionWithToken(sessionId) {
    return fetch('/api/sessions/' + encodeURIComponent(sessionId) + '/share/token', {
      method: 'POST',
      credentials: 'same-origin',
    }).then(function (r) {
      if (!r.ok) {
        return r.json().catch(function () { return {}; }).then(function (e) {
          throw new Error(e.error || ('HTTP ' + r.status));
        });
      }
      return r.json();
    });
  }

  function revokeShare(sessionId, shareId) {
    return fetch(
      '/api/sessions/' + encodeURIComponent(sessionId)
        + '/share/' + encodeURIComponent(shareId),
      { method: 'DELETE', credentials: 'same-origin' }
    ).then(function (r) {
      if (!r.ok) throw new Error('HTTP ' + r.status);
      return r.json();
    });
  }

  function renderSessionList(container, data) {
    var own = data.own || [];
    var shared = data.shared || [];

    var ownHtml = own.map(function (s) {
      return '<li class="session-item" data-id="' + escapeHtml(s.id) + '">'
        + '<span class="session-title">' + escapeHtml(s.title) + '</span>'
        + '<div class="session-actions">'
        +   '<button class="btn-share" data-action="share" data-id="'
        +     escapeHtml(s.id) + '">分享</button>'
        +   '<button class="btn-delete" data-action="delete" data-id="'
        +     escapeHtml(s.id) + '">删除</button>'
        + '</div></li>';
    }).join('') || '<li class="empty">暂无会话</li>';

    var sharedHtml = shared.map(function (item) {
      var s = item.session || {};
      return '<li class="session-item shared" data-share-id="'
        + escapeHtml(item.share_id) + '">'
        + '<span class="session-title">' + escapeHtml(s.title) + '</span>'
        + '<span class="shared-from">来自 ' + escapeHtml(item.from_user_id) + '</span>'
        + '<span class="readonly-badge">只读</span>'
        + '</li>';
    }).join('') || '<li class="empty">暂无分享</li>';

    container.innerHTML =
      '<section class="own-sessions">'
        + '<h3>我的会话 (' + own.length + ')</h3>'
        + '<ul>' + ownHtml + '</ul>'
      + '</section>'
      + '<section class="shared-sessions">'
        + '<h3>收到的分享 (' + shared.length + ')</h3>'
        + '<ul>' + sharedHtml + '</ul>'
      + '</section>';
  }

  function openShareDialog(sessionId) {
    var choice = window.prompt(
      '分享方式: 输入目标用户名（用户分享）\n或输入 "link" 生成分享链接'
    );
    if (!choice) return;
    var trimmed = choice.trim();
    if (trimmed === 'link') {
      shareSessionWithToken(sessionId)
        .then(function (r) {
          var token = r && r.share && r.share.token;
          var url = token
            ? (window.location.origin + '/shared/session?token=' + token)
            : '(无法生成链接)';
          window.prompt('复制以下分享链接:', url);
          refreshSessions();
        })
        .catch(function (e) { window.alert('生成分享链接失败: ' + e.message); });
    } else {
      shareSessionToUser(sessionId, trimmed)
        .then(function () {
          window.alert('已分享给 ' + trimmed);
          refreshSessions();
        })
        .catch(function (e) { window.alert('分享失败: ' + e.message); });
    }
  }

  function refreshSessions() {
    var container = document.getElementById('sessions-container');
    if (!container) return;
    loadSessions().then(function (data) { renderSessionList(container, data); });
  }

  // Click delegation for share / delete buttons
  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('[data-action]');
    if (!btn) return;
    var action = btn.getAttribute('data-action');
    var id = btn.getAttribute('data-id');
    if (action === 'share' && id) {
      openShareDialog(id);
    } else if (action === 'delete' && id) {
      // 删除走现有 chat 接口 — 此处只 refresh, 不实际删除
      refreshSessions();
    }
  });

  document.addEventListener('DOMContentLoaded', refreshSessions);

  // 暴露给其他脚本（如 chat 主界面）调用
  window.refreshSessions = refreshSessions;
})();