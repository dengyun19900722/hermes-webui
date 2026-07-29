/* ───────────────────────────────────────────────────────────────────────────
 * 2.1 实施助手引导页 — 前端模块
 * ───────────────────────────────────────────────────────────────────────────
 * GuidanceManager 单例 + Page2_1 全屏页实现。
 * 与 boot.js / panels.js 通过 window 事件总线解耦。
 */

(function() {
  'use strict';

  const GuidanceManager = {
    state: {
      '2.1': {
        loaded: false,
        data: null,
        collapsed: { 1: true, 2: true, 3: false },
        currentUser: null,
        dismissed: false,
      },
    },

    triggers: {
      '2.1': {
        on: ['deployment_first_seen', 'business_line_no_assets', 'manual_nav'],
        surface: 'fullscreen_page',
        auto_show: true,
      },
    },

    init() {
      this._hydrateFromLocalStorage();
      this._registerEventListeners();
      window.__guidanceMgr = this;
      console.log('[guidance] initialized');
    },

    _hydrateFromLocalStorage() {
      try {
        const raw = localStorage.getItem('guidance.dismissed.2_1');
        if (raw) this.state['2.1'].dismissed = raw === 'true';
      } catch (e) {
        console.warn('[guidance] localStorage read failed:', e);
      }
    },

    _registerEventListeners() {
      window.addEventListener('hermes:license_activated', () => {
        this.evaluate('deployment_first_seen', { autoTriggered: true });
      });
      window.addEventListener('hermes:onboarding_complete', () => {
        if (!this.state['2.1'].loaded) {
          this.evaluate('deployment_first_seen', { autoTriggered: true });
        }
      });
    },

    evaluate(eventName, payload) {
      for (const [pageId, cfg] of Object.entries(this.triggers)) {
        if (cfg.on.includes(eventName) && this._shouldShow(pageId, eventName, payload)) {
          this._dispatch(pageId, payload);
        }
      }
    },

    _shouldShow(pageId, eventName, payload) {
      if (this.state[pageId].dismissed && eventName !== 'manual_nav') return false;
      const key = `guidance.${pageId.replace('.', '_')}.auto_shown_at`;
      try {
        const lastShown = sessionStorage.getItem(key);
        if (lastShown && Date.now() - parseInt(lastShown, 10) < 600_000) return false;
      } catch (e) {}
      return true;
    },

    _dispatch(pageId, payload) {
      if (pageId === '2.1') {
        try {
          sessionStorage.setItem('guidance.2_1.auto_shown_at', String(Date.now()));
        } catch (e) {}
        Page2_1_Implementation.openFullscreen({ autoTriggered: payload.autoTriggered });
      }
    },
  };

  const Page2_1_Implementation = {
    async openFullscreen({ autoTriggered = false } = {}) {
      const tpl = document.getElementById('tpl-guidance-2-1');
      if (!tpl) {
        console.warn('[guidance] template tpl-guidance-2-1 not found');
        return;
      }
      const overlay = tpl.content.firstElementChild.cloneNode(true);
      overlay.id = `guidanceOverlay21-${Date.now()}`;
      document.body.appendChild(overlay);

      overlay.querySelector('#gp21CloseBtn').addEventListener('click', () => this.close(overlay));
      overlay.querySelector('#gp21ExportBtn').addEventListener('click', () => this.exportReport());
      overlay.querySelector('#gp21ResetBtn').addEventListener('click', () => this.resetProgress(overlay));
      overlay.querySelector('#gp21ImportBtn').addEventListener('click', () => {
        overlay.querySelector('#gp21ImportFile').click();
      });
      overlay.querySelector('#gp21ImportFile').addEventListener('change', (e) => {
        this.handleImport(e.target.files[0], overlay);
      });

      await this._refresh(overlay);

      if (autoTriggered) {
        console.log('[guidance] 2.1 auto-shown after deployment');
      }
    },

    close(overlay) {
      overlay.remove();
      try {
        localStorage.setItem('guidance.dismissed.2_1', 'true');
        GuidanceManager.state['2.1'].dismissed = true;
      } catch (e) {}
    },

    async _refresh(overlay) {
      try {
        const res = await api('/api/guidance/implementation');
        if (!res || !res.tasks) throw new Error('invalid response');
        GuidanceManager.state['2.1'].data = res;
        GuidanceManager.state['2.1'].loaded = true;
        this._render(overlay, res);
      } catch (e) {
        console.warn('[guidance] failed to load implementation state:', e);
        this._renderError(overlay, (window.t ? window.t('guidance_2_1_load_failed') : '加载失败，请稍后重试'));
      }
    },

    _render(overlay, data) {
      const pct = data.summary.total ? Math.round(data.summary.done / data.summary.total * 100) : 0;
      overlay.querySelector('#gp21ProgressFill').style.width = pct + '%';
      const labelTpl = (window.t ? window.t('guidance_2_1_progress') : '总进度：{done}/{total}');
      overlay.querySelector('#gp21ProgressLabel').textContent =
        labelTpl.replace('{done}', String(data.summary.done)).replace('{total}', String(data.summary.total));

      const userEl = overlay.querySelector('#gp21CurrentUser');
      const knownBy = (data.tasks.find(t => t.by) || {}).by || 'unknown';
      userEl.textContent = `当前用户：${knownBy}`;

      const tasksEl = overlay.querySelector('#gp21Tasks');
      tasksEl.innerHTML = '';

      for (const groupNum of [1, 2, 3]) {
        const groupTasks = data.tasks.filter(t => t.group === groupNum);
        const groupEl = this._renderGroup(groupNum, groupTasks);
        tasksEl.appendChild(groupEl);
      }
    },

    _renderGroup(groupNum, tasks) {
      const group = document.createElement('div');
      group.className = 'gp21-group';

      const groupDone = tasks.filter(t => t.done).length;
      const collapsed = GuidanceManager.state['2.1'].collapsed[groupNum];

      const header = document.createElement('div');
      header.className = 'gp21-group-header';
      header.innerHTML = `
        <span>${collapsed ? '▶' : '▼'}</span>
        <span style="flex:1">${groupNum}. ${tasks[0].group_title}</span>
        <span style="color:var(--text-secondary)">${groupDone}/${tasks.length}</span>
      `;
      header.addEventListener('click', () => {
        GuidanceManager.state['2.1'].collapsed[groupNum] = !collapsed;
        body.style.display = collapsed ? 'block' : 'none';
        header.querySelector('span').textContent = collapsed ? '▼' : '▶';
      });

      const body = document.createElement('div');
      body.className = 'gp21-group-body';
      body.style.display = collapsed ? 'none' : 'block';

      for (const task of tasks) {
        body.appendChild(this._renderTask(task));
      }

      group.appendChild(header);
      group.appendChild(body);
      return group;
    },

    _renderTask(task) {
      const row = document.createElement('div');
      row.className = 'gp21-task';
      row.dataset.taskId = task.id;

      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.checked = task.done;
      checkbox.addEventListener('change', () => this.toggleTask(task.id, checkbox.checked));

      const title = document.createElement('span');
      title.className = 'gp21-task-title';
      title.textContent = `${task.id} ${task.title}`;

      const meta = document.createElement('span');
      meta.className = 'gp21-task-meta';
      if (task.done && task.by) meta.textContent = `(by ${task.by})`;

      const noteBtn = document.createElement('button');
      noteBtn.className = 'gp21-btn';
      noteBtn.style.fontSize = '12px';
      noteBtn.textContent = task.note ? '📝 编辑备注' : '+ 备注';
      noteBtn.addEventListener('click', () => this.editNote(task.id, task.note, row));

      row.appendChild(checkbox);
      row.appendChild(title);
      row.appendChild(meta);
      row.appendChild(noteBtn);

      if (task.note) {
        const note = document.createElement('span');
        note.className = 'gp21-task-note';
        note.textContent = task.note;
        row.appendChild(note);
      }

      return row;
    },

    _renderError(overlay, msg) {
      const tasksEl = overlay.querySelector('#gp21Tasks');
      tasksEl.innerHTML = `<div style="padding:32px;text-align:center;color:var(--text-secondary)">${msg}</div>`;
    },

    async toggleTask(taskId, done) {
      try {
        const res = await api(`/api/guidance/implementation/${taskId}`, {
          method: 'PATCH',
          body: JSON.stringify({ done }),
        });
        if (!res.ok) throw new Error(res.error || 'patch failed');
        const overlay = document.querySelector('[id^="guidanceOverlay21-"]');
        if (overlay) await this._refresh(overlay);
      } catch (e) {
        console.warn('[guidance] toggle task failed:', e);
        alert((window.t ? window.t('guidance_2_1_save_failed') : '保存失败，请稍后重试'));
      }
    },

    async editNote(taskId, currentNote, row) {
      const note = prompt('备注（关联需求号 / 说明）：', currentNote || '');
      if (note === null) return;
      try {
        const res = await api(`/api/guidance/implementation/${taskId}/note`, {
          method: 'POST',
          body: JSON.stringify({ note }),
        });
        if (!res.ok) throw new Error(res.error || 'note failed');
        const overlay = document.querySelector('[id^="guidanceOverlay21-"]');
        if (overlay) await this._refresh(overlay);
      } catch (e) {
        console.warn('[guidance] edit note failed:', e);
        alert('保存备注失败');
      }
    },

    async exportReport() {
      try {
        const res = await fetch('/api/guidance/implementation/report', { credentials: 'include' });
        if (!res.ok) throw new Error('export failed');
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        const cdHeader = res.headers.get('Content-Disposition');
        const filenameMatch = cdHeader && cdHeader.match(/filename="?([^"]+)"?/);
        a.download = filenameMatch ? filenameMatch[1] : 'implementation-report.md';
        a.click();
        URL.revokeObjectURL(url);
      } catch (e) {
        console.warn('[guidance] export failed:', e);
        alert('导出失败，请稍后重试');
      }
    },

    async resetProgress(overlay) {
      const confirmMsg = (window.t ? window.t('guidance_2_1_reset_confirm') : '确定要重置所有进度吗？此操作不可恢复。');
      if (!confirm(confirmMsg)) return;
      try {
        const res = await api('/api/guidance/implementation', { method: 'DELETE' });
        if (!res.ok) throw new Error('reset failed');
        await this._refresh(overlay);
      } catch (e) {
        console.warn('[guidance] reset failed:', e);
        alert('重置失败，请稍后重试');
      }
    },

    async handleImport(file, overlay) {
      if (!file) return;
      if (!file.name.toLowerCase().endsWith('.csv')) {
        alert('v1.1.0 仅支持 CSV 文件');
        return;
      }
      const formData = new FormData();
      formData.append('file', file);
      try {
        const res = await fetch('/api/guidance/implementation/import-business-entities', {
          method: 'POST',
          body: formData,
          credentials: 'include',
        });
        const data = await res.json();
        if (res.ok && data.ok) {
          await this._refresh(overlay);
          alert(`成功导入 ${data.imported_rows} 行`);
        } else {
          this._showImportErrors(data);
        }
      } catch (e) {
        console.warn('[guidance] import failed:', e);
        alert('导入失败，请稍后重试');
      }
    },

    _showImportErrors(data) {
      const tpl = document.getElementById('tpl-guidance-2-1-errors');
      if (!tpl) return;
      const overlay = tpl.content.firstElementChild.cloneNode(true);
      document.body.appendChild(overlay);

      const summary = overlay.querySelector('#gp21ErrorsSummary');
      if (data.error === 'missing_columns') {
        summary.textContent = `缺少必填列：${data.missing.join('、')}`;
      } else if (data.error === 'size_limit') {
        summary.textContent = data.detail || '文件过大';
      } else {
        summary.textContent = `共 ${data.total_failed} 行错误，已显示前 ${data.failed_rows.length} 行`;
        const tbody = overlay.querySelector('#gp21ErrorsTable tbody');
        for (const row of data.failed_rows) {
          const tr = document.createElement('tr');
          tr.innerHTML = `<td>${row.line}</td><td>${row.field}</td><td>${row.reason}</td>`;
          tbody.appendChild(tr);
        }
      }

      overlay.querySelector('#gp21ErrorsClose').addEventListener('click', () => overlay.remove());
    },
  };

  window.GuidanceManager = GuidanceManager;
  window.Page2_1_Implementation = Page2_1_Implementation;
})();