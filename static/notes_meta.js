/* Knowledge base metadata UI: creator attribution + 5-star rating.
 *
 * Exposes:
 *   window.NotesMeta.renderRowMeta(doc)      – HTML string for tree-row meta line
 *   window.NotesMeta.renderRatingSection(doc) – HTML for detail-page rating
 *   window.NotesMeta.initDetailRating()       – wire up interactive stars + submit
 *   window.NotesMeta.clearRating()            – hide/clear rating section
 */
(function () {
  'use strict';

  /* ── Safe path encoding for DOM IDs (replace / with __, no CSS.escape) ── */
  function _safeId(path) {
    return (path || '_').replace(/\//g, '__').replace(/[^a-zA-Z0-9_\u4e00-\u9fff\-]/g, '_');
  }

  function esc(s) {
    var div = document.createElement('div');
    div.textContent = s == null ? '' : String(s);
    return div.innerHTML;
  }

  /* ── Clear / show / hide rating section ───────────────────────────── */
  function clearRating() {
    var el = document.getElementById('knowledgeDetailRating');
    if (el) { el.style.display = 'none'; el.innerHTML = ''; }
  }

  /* ── Read-only star display (for tree rows) ────────────────────────── */
  function starDisplay(count, average) {
    if (!count || count === 0) return '<span class="ns-star-display empty">—</span>';
    var full = Math.round(average);
    var html = '<span class="ns-star-display" title="平均评分 ' + average.toFixed(1) + ' / 5">';
    for (var i = 1; i <= 5; i++) {
      html += i <= full
        ? '<svg class="ns-star filled" width="11" height="11" viewBox="0 0 24 24" fill="currentColor"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>'
        : '<svg class="ns-star" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>';
    }
    html += '</span>';
    return html;
  }

  /* ── Tree-row meta line: @creator + stars ──────────────────────────── */
  function renderRowMeta(doc) {
    var m = (doc && doc.meta) || {};
    if (!m.creator_name && !m.rating_count) return '';
    var parts = [];
    if (m.creator_name) parts.push('<span class="ns-meta-creator">@' + esc(m.creator_name) + '</span>');
    if (m.rating_count) parts.push(starDisplay(m.rating_count, m.rating_average));
    return '<span class="ns-row-meta">' + parts.join('') + '</span>';
  }

  /* ── 5 star SVGs (always full DOM, no innerHTML replacement) ──────── */
  function _starSvgs() {
    var h = '';
    for (var i = 1; i <= 5; i++) {
      h += '<svg class="ns-s" data-idx="' + i + '" width="18" height="18" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="1"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>';
    }
    return h;
  }

  /* ── Toggle .hover class on stars 0..n-1 ──────────────────────────────── */
  function _setStars(container, n) {
    var svgs = container.querySelectorAll('svg');
    for (var i = 0; i < svgs.length; i++) {
      svgs[i].classList.toggle('hover', i < n);
    }
  }

  function _summaryHtml(m) {
    if (!m.rating_count) return '<span class="ns-sum-text muted">暂无评分</span>';
    return '<span class="ns-sum-text">' + m.rating_average.toFixed(1) + ' 分 · ' + m.rating_count + ' 人</span>';
  }

  /* ── Interactive star rating (detail page) ─────────────────────────── */
  function renderRatingSection(doc) {
    var m = (doc && doc.meta) || {};
    var path = (doc && doc.path) || '';
    var sid = _safeId(path);
    var creatorHtml = m.creator_name
      ? '<span class="ns-creator">创建者 @' + esc(m.creator_name) + '</span>'
      : '';

    return '<div class="ns-rating-wrap" data-sid="' + sid + '">'
      +   creatorHtml
      +   '<span class="ns-rating-label">评分</span>'
      +   '<span class="ns-stars" id="nsStars-' + sid + '">' + _starSvgs() + '</span>'
      +   '<span class="ns-my" id="nsMy-' + sid + '"></span>'
      +   '<button class="ns-btn" id="nsBtn-' + sid + '" disabled>提交</button>'
      +   '<span class="ns-summary" id="nsSum-' + sid + '">' + _summaryHtml(m) + '</span>'
      +   '<span class="ns-err" id="nsErr-' + sid + '" style="display:none"></span>'
      + '</div>';
  }

  /* ── Wire up interactive stars (class-based, no innerHTML replace) ─── */
  var _selected = 0;

  function initDetailRating(docPath) {
    var el = document.getElementById('knowledgeDetailRating');
    if (!el || !docPath || el.style.display === 'none') return;

    var sid = _safeId(docPath);
    // Verify our wrap is present
    var wrap = el.querySelector('.ns-rating-wrap[data-sid="' + sid + '"]');
    if (!wrap) return;

    _selected = 0;

    var starBox = document.getElementById('nsStars-' + sid);
    var btn = document.getElementById('nsBtn-' + sid);
    var myEl = document.getElementById('nsMy-' + sid);
    var sumEl = document.getElementById('nsSum-' + sid);
    var errEl = document.getElementById('nsErr-' + sid);
    if (!starBox || !btn) return;

    /* Load my_rating from server */
    fetch('/api/notes/meta/' + encodeURIComponent(docPath))
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (meta) {
        if (!meta) return;
        if (meta.my_rating) {
          _selected = meta.my_rating;
          _setStars(starBox, _selected);
          if (myEl) myEl.textContent = '我的评分：' + meta.my_rating + ' 星';
          btn.disabled = false;
        }
        if (sumEl) sumEl.innerHTML = _summaryHtml(meta);
      })
      .catch(function () {});

    /* Hover: toggle class on SVGs via index */
    starBox.addEventListener('mouseover', function (e) {
      var svg = e.target.closest('svg');
      if (!svg || !svg.parentNode || svg.parentNode !== starBox) return;
      var idx = parseInt(svg.getAttribute('data-idx'), 10);
      if (isNaN(idx)) return;
      _setStars(starBox, idx);
    });

    starBox.addEventListener('mouseout', function () {
      _setStars(starBox, _selected);
    });

    /* Click: select */
    starBox.addEventListener('click', function (e) {
      var svg = e.target.closest('svg');
      if (!svg || !svg.parentNode || svg.parentNode !== starBox) return;
      var idx = parseInt(svg.getAttribute('data-idx'), 10);
      if (isNaN(idx)) return;
      _selected = idx;
      _setStars(starBox, _selected);
      if (myEl) myEl.textContent = '我的评分：' + _selected + ' 星';
      btn.disabled = false;
    });

    /* Submit */
    btn.addEventListener('click', function () {
      if (!_selected) return;
      btn.disabled = true;
      btn.textContent = '提交中…';
      if (errEl) errEl.style.display = 'none';
      fetch('/api/notes/meta/' + encodeURIComponent(docPath) + '/rate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify({ rating: _selected }),
      })
        .then(function (r) {
          if (!r.ok) return r.json().catch(function () { return {}; }).then(function (e) { throw new Error(e.error || ('HTTP ' + r.status)); });
          return r.json();
        })
        .then(function () {
          btn.textContent = '已提交';
          btn.disabled = false;
          return fetch('/api/notes/meta/' + encodeURIComponent(docPath));
        })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (meta) {
          if (meta && sumEl) sumEl.innerHTML = _summaryHtml(meta);
        })
        .catch(function (e) {
          btn.textContent = '提交评分';
          btn.disabled = false;
          if (errEl) { errEl.textContent = '失败：' + e.message; errEl.style.display = ''; }
        });
    });
  }

  /* ── Public API ────────────────────────────────────────────────────── */
  window.NotesMeta = {
    renderRowMeta: renderRowMeta,
    renderRatingSection: renderRatingSection,
    initDetailRating: initDetailRating,
    clearRating: clearRating,
    esc: esc,
  };
})();
