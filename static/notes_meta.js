/* Knowledge base metadata UI: creator attribution + user ratings.
 *
 * Exposes window.NotesMeta.renderDocCard(doc) — returns HTML string
 * for a document card showing @creator + ★ rating + rate button.
 *
 * Also exposes window.NotesMeta.openRateDialog(docPath) for the rate
 * button to POST to /api/notes/meta/{path}/rate.
 *
 * The /api/notes/meta/{path}/rate endpoint is provided by api.rbac_routes
 * (or the existing obsidian notes module — whichever is wired).
 */
(function () {
  function escapeHtml(s) {
    var div = document.createElement('div');
    div.textContent = s == null ? '' : String(s);
    return div.innerHTML;
  }

  function ratingHtml(meta) {
    if (!meta || !meta.rating_count || meta.rating_count === 0) {
      return '<span class="doc-rating empty">暂无评分</span>';
    }
    var avg = (meta.rating_average || 0).toFixed(1);
    return '<span class="doc-rating" title="平均评分">★ '
      + escapeHtml(avg) + ' (' + escapeHtml(String(meta.rating_count)) + ')</span>';
  }

  function renderDocCard(doc) {
    var meta = (doc && doc.meta) || {};
    var creator = meta.creator_name || 'unknown';
    return '<div class="doc-card" data-path="' + escapeHtml(doc.path) + '">'
      + '<div class="doc-header">'
      +   '<span class="doc-title">' + escapeHtml(doc.name || doc.path) + '</span>'
      +   '<span class="doc-creator">@' + escapeHtml(creator) + '</span>'
      + '</div>'
      + '<div class="doc-footer">'
      +   ratingHtml(meta)
      +   '<button class="btn-rate" data-action="rate" data-path="'
      +     escapeHtml(doc.path) + '">评分</button>'
      + '</div>'
      + '</div>';
  }

  function openRateDialog(docPath) {
    var input = window.prompt('请输入评分 1-5:');
    var n = parseInt(input, 10);
    if (!n || n < 1 || n > 5) {
      window.alert('评分必须是 1-5 之间的整数');
      return;
    }
    fetch('/api/notes/meta/' + encodeURIComponent(docPath) + '/rate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ rating: n }),
    })
      .then(function (r) {
        if (!r.ok) {
          return r.json().catch(function () { return {}; }).then(function (e) {
            throw new Error(e.error || ('HTTP ' + r.status));
          });
        }
        return r.json();
      })
      .then(function () {
        window.alert('评分已保存');
      })
      .catch(function (e) {
        window.alert('评分失败: ' + e.message);
      });
  }

  // Click delegation for rate buttons
  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('[data-action="rate"]');
    if (!btn) return;
    var path = btn.getAttribute('data-path');
    if (path) openRateDialog(path);
  });

  window.NotesMeta = {
    renderDocCard: renderDocCard,
    openRateDialog: openRateDialog,
    escapeHtml: escapeHtml,
  };
})();