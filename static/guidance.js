/* ───────────────────────────────────────────────────────────────────────────
 * 2.1 实施助手引导页 — 前端模块
 * ───────────────────────────────────────────────────────────────────────────
 * GuidanceManager 单例 + Page2_1 全屏页实现。
 * 与 boot.js / panels.js 通过 window 事件总线解耦。
 */

(function() {
  'use strict';

  // 1.1_fill_entity_table 操作区使用的"实体/关系类型填表说明"文档 HTML。
  // 基于多 sheet xlsx 模板（实体页/关系页/填写说明）。
  const _FILL_ENTITY_DOC_HTML = `
    <div class="gp21-fill-intro">
      <b>填写说明：</b>模板为 <b>xlsx</b>，含 3 个 sheet：<span class="gp21-mono">实体页</span>、
      <span class="gp21-mono">关系页</span>、<span class="gp21-mono">填写说明</span>。
      点击下方「⬇ 下载模板」获取标准模板，填写后上传即可。<br>
      也可用 5 列 CSV（<span class="gp21-mono">from_label,from_name,properties,to_label,to_name</span>），
      实体行 4-5 列留空，关系行 5 列都填。
    </div>
    <div class="gp21-fill-section">
      <div class="gp21-fill-h">▍实体页（label + name）</div>
      <div class="gp21-fill-grid">
        <div class="gp21-fill-card">
          <div class="gp21-fill-card-h">① Host 主机</div>
          <div class="gp21-fill-card-body">服务器/IP，name 为 IP 地址。<br><b>业务线</b>用 properties 里的 <span class="gp21-mono">busi_name</span> 标注。</div>
          <div class="gp21-fill-cols">
            <div><b>label</b>：Host</div>
            <div><b>name</b>：如 <span class="gp21-mono">12.7.0.11</span>（IP）</div>
            <div><b>properties</b>：<span class="gp21-mono">{"ssh_port":22,"ssh_user":"root","busi_name":"支付线"}</span></div>
          </div>
          <div class="gp21-fill-example">label=Host, name=12.7.0.11</div>
        </div>
        <div class="gp21-fill-card">
          <div class="gp21-fill-card-h">② Service 服务</div>
          <div class="gp21-fill-card-body">服务/组件，name 为服务名。</div>
          <div class="gp21-fill-cols">
            <div><b>from_label</b>：Service</div>
            <div><b>from_name</b>：如 <span class="gp21-mono">commander</span></div>
            <div><b>properties</b>：<span class="gp21-mono">{"log_type":"host","log_path":"/usr/log/"}</span></div>
          </div>
          <div class="gp21-fill-example">Service,commander,{"rel_type":"host","log_path":"/usr/log/commander/"},,</div>
        </div>
        <div class="gp21-fill-card">
          <div class="gp21-fill-card-h">③ Program / Api</div>
          <div class="gp21-fill-card-body">程序、接口端点；name 为唯一标识。</div>
          <div class="gp21-fill-cols">
            <div><b>from_label</b>：Program / Api</div>
            <div><b>from_name</b>：如 <span class="gp21-mono">wxsshd</span></div>
            <div><b>properties</b>：JSON 字符串自定义属性</div>
          </div>
          <div class="gp21-fill-example">Program,wxsshd,{"rel_type":"host","log_path":"/usr/log/wxsshd/"},,</div>
        </div>
        <div class="gp21-fill-card">
          <div class="gp21-fill-card-h">④ Middleware 中间件</div>
          <div class="gp21-fill-card-body">服务依赖的中间件（MySQL/Redis 等），name 用类型名。</div>
          <div class="gp21-fill-cols">
            <div><b>from_label</b>：Middleware</div>
            <div><b>from_name</b>：如 <span class="gp21-mono">Mysql</span></div>
            <div><b>properties</b>：JSON 字符串自定义属性</div>
          </div>
          <div class="gp21-fill-example">Middleware,Mysql,{"version":"8.0"},,</div>
        </div>
      </div>
    </div>
    <div class="gp21-fill-section">
      <div class="gp21-fill-h">▍关系（rel_type 写在 properties）</div>
      <div class="gp21-fill-rels">
        <div><b>DEPLOY_ON</b> 服务→主机：<span class="gp21-fill-example">Service,commander,{"rel_type":"DEPLOY_ON"},Host,12.7.0.11</span></div>
        <div><b>DEPEND_ON</b> 服务→程序：<span class="gp21-fill-example">Service,bckproc,{"rel_type":"DEPEND_ON"},Program,cws</span></div>
        <div><b>DEPENDS_ON</b> 服务→中间件：<span class="gp21-fill-example">Service,commander,{"rel_type":"DEPENDS_ON"},Middleware,Mysql</span></div>
        <div><b>RUN_SERVICE</b> 主机→服务：<span class="gp21-fill-example">Host,12.7.0.11,{"rel_type":"RUN_SERVICE"},Service,commander</span></div>
        <div><b>HAS_CABINET</b> 机房→机柜：<span class="gp21-fill-example">Room,R1,{"rel_type":"HAS_CABINET"},Cabinet,C01</span></div>
      </div>
    </div>
    <div class="gp21-fill-section">
      <div class="gp21-fill-h">▍填写规则</div>
      <ul class="gp21-fill-rules">
        <li><b>from_label + from_name</b> 联合唯一，全局标识一个实体</li>
        <li>实体行 4-5 列留空；关系行 5 列都填，<span class="gp21-mono">rel_type</span> 必须写在 properties</li>
        <li><span class="gp21-mono">properties</span> 必须是合法 JSON（双引号、逗号），特殊字符用 <span class="gp21-mono">\\"</span> 转义</li>
        <li>空行或 <span class="gp21-mono">#</span> 开头的行会被忽略</li>
      </ul>
    </div>
  `;

  const GuidanceManager = {
    state: {
      '2.1': {
        loaded: false,
        data: null,
        activeGroup: 1,
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
      // 手动导航（用户主动点击入口）永远放行，不受 10 分钟防重复抑制。
      // 防重复只用于自动触发（deployment_first_seen / business_line_no_assets）。
      if (eventName === 'manual_nav') return true;
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
      const apiUser = (data.current_user != null && data.current_user !== '')
        ? String(data.current_user)
        : '';
      const byUser = ((data.tasks.find(t => t.by) || {}).by || '');
      // 后端在未登录 RBAC 时只会返回空串 (tests/test_guidance_progress.py
      // 显式覆盖此约定)，这里 fall back 到前端已知的 active profile，
      // 保证右上角 admin/admin-xxx 显示什么，助手底部就显示什么。
      const profileUser = (typeof S !== 'undefined' && S && S.activeProfile && S.activeProfile !== 'default')
        ? S.activeProfile
        : '';
      let knownBy = apiUser || byUser || profileUser || 'unknown';
      if (apiUser || byUser) {
        userEl.removeAttribute('title');
      } else if (profileUser) {
        userEl.title = '接口未读到 RBAC 用户，已回退到当前 Profile';
      } else {
        userEl.title = '';
      }
      userEl.textContent = `当前用户：${knownBy}`;

      const groups = [1, 2, 3].map(n => ({
        num: n,
        tasks: data.tasks.filter(t => t.group === n),
      }));

      const sidebarEl = overlay.querySelector('#gp21Sidebar');
      const tasksEl = overlay.querySelector('#gp21Tasks');
      this._renderSidebar(sidebarEl, groups, data);
      this._renderMain(tasksEl, groups, data);
    },

    _renderSidebar(el, groups, data) {
      el.innerHTML = '';
      el.appendChild(this._sidebarHeader());
      const steps = document.createElement('div');
      steps.className = 'gp21-steps';
      for (const g of groups) {
        steps.appendChild(this._renderStep(g, data));
      }
      el.appendChild(steps);
    },

    _sidebarHeader() {
      const hd = document.createElement('div');
      hd.className = 'gp21-sidebar-head';
      hd.textContent = '实施步骤';
      return hd;
    },

    _renderStep(g, data) {
      const step = document.createElement('div');
      const done = g.tasks.filter(t => t.done).length;
      const active = GuidanceManager.state['2.1'].activeGroup === g.num;
      step.className = 'gp21-step' + (active ? ' active' : '') + (done === g.tasks.length ? ' done' : '');
      step.dataset.group = g.num;

      const idx = document.createElement('div');
      idx.className = 'gp21-step-index';
      idx.textContent = String(g.num);

      const body = document.createElement('div');
      body.className = 'gp21-step-body';

      const gTitle = (g.tasks[0] || {}).group_title || '步骤';
      const title = document.createElement('div');
      title.className = 'gp21-step-title';
      title.textContent = `${g.num}. ${gTitle}`;

      const desc = document.createElement('div');
      desc.className = 'gp21-step-desc';
      desc.textContent = `${done}/${g.tasks.length} 已完成`;

      body.appendChild(title);
      body.appendChild(desc);
      step.appendChild(idx);
      step.appendChild(body);

      step.addEventListener('click', (ev) => {
        GuidanceManager.state['2.1'].activeGroup = g.num;
        const groups = [1, 2, 3].map(n => ({
          num: n,
          tasks: (GuidanceManager.state['2.1'].data.tasks || []).filter(t => t.group === n),
        }));
        const overlayEl = (ev.currentTarget || step).closest('.guidance-overlay-21');
        const sidebar = overlayEl ? overlayEl.querySelector('#gp21Sidebar') : null;
        const tasksEl = overlayEl ? overlayEl.querySelector('#gp21Tasks') : null;
        if (sidebar) this._renderSidebar(sidebar, groups, GuidanceManager.state['2.1'].data);
        if (tasksEl) this._renderMain(tasksEl, groups, GuidanceManager.state['2.1'].data);
      });
      return step;
    },

    _renderMain(el, groups, data) {
      const active = GuidanceManager.state['2.1'].activeGroup;
      const g = groups.find(x => x.num === active) || groups[0];
      if (!g) { el.innerHTML = ''; return; }
      el.innerHTML = '';

      const head = document.createElement('div');
      head.className = 'gp21-main-head';
      const done = g.tasks.filter(t => t.done).length;
      const gTitle = (g.tasks[0] || {}).group_title || '步骤';
      head.innerHTML = `<div class="gp21-main-title">${g.num}. ${gTitle}</div>
        <div class="gp21-main-meta">${done}/${g.tasks.length} 已完成</div>`;
      el.appendChild(head);

      const list = document.createElement('div');
      list.className = 'gp21-group-body';
      for (const task of g.tasks) {
        list.appendChild(this._renderTask(task));
      }
      el.appendChild(list);
    },

    // 每个任务的就地操作配置：
    //   ops: ['verify'|'upload_csv'|'upload_kb'|'search'|'link'|'note']
    //   label: 操作标题
    //   help: 操作提示
    //   link: 跳转地址（仅 link）
    _TASK_OPS: {
      // Group 1：1.1 填写实体关系表 = 查看文档 + 下载模板（手动任务，含就地说明区）
      '1.1_fill_entity_table': {
        ops: ['fill_entity'],
        label: '填写实体关系表',
        templateLink: '/api/guidance/implementation/template',
        docEndpoint: '/api/guidance/implementation/entity-doc',
        help: '阅读说明并下载模板，完成实体关系表的填写。',
      },
      // Group 1：1.3 上传导入 = 校验 + 真实导入一次完成，导入成功后自动验证
      '1.3_import_entities': { ops: ['upload_csv'], label: '上传并导入实体表', help: '选择模板 xlsx（实体页/关系页）或 CSV，系统将校验并导入，导入成功即自动验证。' },
      '2.1_view_template':   { ops: ['link'], label: '查看 FAQ 模板', link: '/notes' },
      '2.2_batch_import':    { ops: ['upload_kb'], label: '上传知识库压缩包导入', help: '支持 zip/tar，导入 FAQ 到知识库。' },
      '2.3_verify_search':   { ops: ['search'], label: '验证知识库可搜索', help: '输入一个查询词，系统调用知识库搜索接口确认可检索。' },
      '3.1_select_business_line': { ops: ['verify'], label: '自动验证可选业务线', help: '检查资产库存中是否已有可选业务线。' },
      '3.2_run_inspection':  { ops: ['link'], label: '进入对话执行全链路巡检', link: '/chat' },
      '3.3_run_diagnosis':   { ops: ['link'], label: '进入对话执行故障诊断', link: '/chat' },
      '3.4_record_result':   { ops: ['note'], label: '记录验证结果', help: '填写巡检/诊断的验证结果与结论。' },
    },

    _renderTask(task) {
      const row = document.createElement('div');
      row.className = 'gp21-task';
      row.dataset.taskId = task.id;

      const head = document.createElement('div');
      head.className = 'gp21-task-head';

      const checkbox = document.createElement('input');
      checkbox.type = 'checkbox';
      checkbox.checked = task.done;
      checkbox.addEventListener('change', () => this.toggleTask(task.id, checkbox.checked, task.note));

      const title = document.createElement('span');
      title.className = 'gp21-task-title';
      title.textContent = `${task.id} ${task.title}`;

      const meta = document.createElement('span');
      meta.className = 'gp21-task-meta';
      if (task.done) {
        const src = task.verification_type === 'auto' ? '✅ 自动验证' : '手动';
        meta.textContent = `(${src} by ${task.by || '?'})`;
      }

      const noteBtn = document.createElement('button');
      noteBtn.className = 'gp21-btn';
      noteBtn.textContent = task.note ? '📝 备注' : '+ 备注';
      noteBtn.addEventListener('click', () => this.editNote(task.id, task.note, row));

      head.appendChild(checkbox);
      head.appendChild(title);
      head.appendChild(meta);
      head.appendChild(noteBtn);
      row.appendChild(head);

      if (task.note) {
        const note = document.createElement('div');
        note.className = 'gp21-task-note';
        note.textContent = task.note;
        row.appendChild(note);
      }

      // 验证证据展示
      if (task.verified && task.evidence) {
        const ev = document.createElement('div');
        ev.className = 'gp21-task-evidence';
        ev.textContent = `🔍 ${task.evidence}`;
        row.appendChild(ev);
      } else if (task.last_check && task.last_check.passed) {
        const ev = document.createElement('div');
        ev.className = 'gp21-task-evidence';
        ev.textContent = `🔍 ${task.last_check.evidence || '检查通过'}`;
        row.appendChild(ev);
      }

      // 就地操作区
      const ops = this._TASK_OPS[task.id];
      if (ops && !task.done) {
        row.appendChild(this._renderOps(task, ops));
      }

      return row;
    },

    _renderOps(task, opsCfg) {
      const wrap = document.createElement('div');
      wrap.className = 'gp21-task-ops';

      for (const op of opsCfg.ops) {
        if (op === 'verify') {
          const btn = document.createElement('button');
          btn.className = 'gp21-btn gp21-btn-primary';
          btn.textContent = '⚡ 自动验证此步';
          btn.addEventListener('click', () => this.runVerify(task.id, btn));
          const help = document.createElement('span');
          help.className = 'gp21-task-help';
          help.textContent = opsCfg.help || '';
          wrap.appendChild(btn);
          wrap.appendChild(help);
        } else if (op === 'upload_csv') {
          const btn = document.createElement('button');
          btn.className = 'gp21-btn gp21-btn-primary';
          btn.textContent = '选择模板文件';
          const input = document.createElement('input');
          input.type = 'file';
          input.accept = '.xlsx,.csv';
          input.style.display = 'none';
          btn.addEventListener('click', () => input.click());
          input.addEventListener('change', () => {
            this.handleUpload(input.files[0], task.id, input);
          });
          const help = document.createElement('span');
          help.className = 'gp21-task-help';
          help.textContent = opsCfg.help || '';
          wrap.appendChild(btn);
          wrap.appendChild(input);
          wrap.appendChild(help);
        } else if (op === 'upload_kb') {
          const btn = document.createElement('button');
          btn.className = 'gp21-btn gp21-btn-primary';
          btn.textContent = '选择知识库压缩包';
          const input = document.createElement('input');
          input.type = 'file';
          input.accept = '.zip,.tar,.gz,.tgz';
          input.style.display = 'none';
          btn.addEventListener('click', () => input.click());
          input.addEventListener('change', () => {
            this.handleUpload(input.files[0], task.id, input);
          });
          const help = document.createElement('span');
          help.className = 'gp21-task-help';
          help.textContent = opsCfg.help || '';
          wrap.appendChild(btn);
          wrap.appendChild(input);
          wrap.appendChild(help);
        } else if (op === 'search') {
          const input = document.createElement('input');
          input.type = 'text';
          input.placeholder = '输入查询词，如：故障';
          input.className = 'gp21-task-input';
          const btn = document.createElement('button');
          btn.className = 'gp21-btn gp21-btn-primary';
          btn.textContent = '验证可搜索';
          btn.addEventListener('click', () => this.runVerifySearch(input.value, btn));
          const help = document.createElement('span');
          help.className = 'gp21-task-help';
          help.textContent = opsCfg.help || '';
          wrap.appendChild(input);
          wrap.appendChild(btn);
          wrap.appendChild(help);
        } else if (op === 'link') {
          const isDownload = typeof opsCfg.link === 'string' && opsCfg.link.startsWith('/api/');
          const btn = document.createElement('button');
          btn.className = 'gp21-btn';
          btn.textContent = isDownload ? '⬇ 下载' : '→ 前往操作';
          btn.addEventListener('click', () => {
            if (isDownload) {
              // 触发真实文件下载（模板等 API 端点）
              const a = document.createElement('a');
              a.href = opsCfg.link;
              a.download = '';
              document.body.appendChild(a);
              a.click();
              a.remove();
            } else {
              window.location.hash = opsCfg.link;
            }
          });
          const help = document.createElement('span');
          help.className = 'gp21-task-help';
          help.textContent = opsCfg.help || (isDownload ? '下载模板文件。' : '完成后请手动标记并填写备注。');
          wrap.appendChild(btn);
          wrap.appendChild(help);
        } else if (op === 'note') {
          const btn = document.createElement('button');
          btn.className = 'gp21-btn';
          btn.textContent = '填写验证结果';
          btn.addEventListener('click', () => this.editNote(task.id, task.note, null));
          const help = document.createElement('span');
          help.className = 'gp21-task-help';
          help.textContent = opsCfg.help || '';
          wrap.appendChild(btn);
          wrap.appendChild(help);
        } else if (op === 'fill_entity') {
          // 填写实体关系表：详细说明文档（实体类型 + 关系类型）+ 下载模板 + 查看文档
          const doc = document.createElement('div');
          doc.className = 'gp21-fill-doc';
          doc.innerHTML = _FILL_ENTITY_DOC_HTML;
          const dlBtn = document.createElement('button');
          dlBtn.className = 'gp21-btn gp21-btn-primary';
          dlBtn.textContent = '⬇ 下载模板';
          dlBtn.addEventListener('click', () => {
            const a = document.createElement('a');
            a.href = opsCfg.templateLink;
            a.download = '';
            document.body.appendChild(a);
            a.click();
            a.remove();
          });
          const docBtn = document.createElement('button');
          docBtn.className = 'gp21-btn';
          docBtn.textContent = '\u77e5\u8bc6\u5e93\u6587\u6863';
          docBtn.addEventListener('click', () => this._openEntityDoc(opsCfg.docEndpoint));
          wrap.appendChild(doc);
          wrap.appendChild(dlBtn);
          wrap.appendChild(docBtn);
        }
      }

      return wrap;
    },

    _renderError(overlay, msg) {
      const tasksEl = overlay.querySelector('#gp21Tasks');
      tasksEl.innerHTML = `<div style="padding:32px;text-align:center;color:var(--text-secondary)">${msg}</div>`;
    },

    async toggleTask(taskId, done, existingNote) {
      if (!done) {
        // 取消勾选：直接提交
        try {
          const res = await api(`/api/guidance/implementation/${taskId}`, {
            method: 'PATCH',
            body: JSON.stringify({ done: false }),
          });
          if (!res.ok) throw new Error(res.error || 'patch failed');
          const overlay = document.querySelector('[id^="guidanceOverlay21-"]');
          if (overlay) await this._refresh(overlay);
        } catch (e) {
          console.warn('[guidance] toggle task failed:', e);
          alert('保存失败，请稍后重试');
        }
        return;
      }

      // 勾选：手动标记必填备注。若已有备注则直接复用，否则弹窗要求填写。
      let note = (existingNote || '').trim();
      if (!note) {
        const input = prompt('手动标记此步：请填写完成依据/备注原因（必填）', '');
        if (input === null) {
          const overlay = document.querySelector('[id^="guidanceOverlay21-"]');
          if (overlay) await this._refresh(overlay);
          return;
        }
        note = (input || '').trim();
        if (!note) {
          alert('手动标记必须填写备注原因');
          const overlay = document.querySelector('[id^="guidanceOverlay21-"]');
          if (overlay) await this._refresh(overlay);
          return;
        }
      }
      try {
        const res = await api(`/api/guidance/implementation/${taskId}`, {
          method: 'PATCH',
          body: JSON.stringify({ done: true, note }),
        });
        if (!res.ok) {
          if (res.error === 'manual_note_required') {
            alert(res.detail || '该步骤需手动标记，请填写备注原因');
          }
          throw new Error(res.error || 'patch failed');
        }
        const overlay = document.querySelector('[id^="guidanceOverlay21-"]');
        if (overlay) await this._refresh(overlay);
      } catch (e) {
        console.warn('[guidance] toggle task failed:', e);
        alert('保存失败，请稍后重试');
        const overlay = document.querySelector('[id^="guidanceOverlay21-"]');
        if (overlay) await this._refresh(overlay);
      }
    },

    async runVerify(taskId, btn) {
      if (btn) {
        btn.disabled = true;
        btn.textContent = '验证中…';
      }
      try {
        const res = await api('/api/guidance/implementation/verify', {
          method: 'POST',
          body: JSON.stringify({ task_id: taskId }),
        });
        const overlay = document.querySelector('[id^="guidanceOverlay21-"]');
        if (res && res.passed) {
          if (overlay) await this._refresh(overlay);
          alert(`✅ 验证通过：${res.evidence || ''}`);
        } else {
          const msg = (res && res.evidence) || '未满足验证条件';
          alert(`❌ 验证未通过：${msg}`);
          if (btn) {
            btn.disabled = false;
            btn.textContent = '⚡ 自动验证此步';
          }
        }
      } catch (e) {
        console.warn('[guidance] verify failed:', e);
        alert('验证失败：' + ((e && e.message) || '请稍后重试'));
        if (btn) {
          btn.disabled = false;
          btn.textContent = '⚡ 自动验证此步';
        }
      }
    },

    async runVerifySearch(query, btn) {
      const q = (query || '').trim();
      if (!q) {
        alert('请输入查询词');
        return;
      }
      if (btn) {
        btn.disabled = true;
        btn.textContent = '验证中…';
      }
      try {
        // 直接用用户查询词调后端验证（后端在知识库中检索并记录结果）
        const res = await api('/api/guidance/implementation/verify', {
          method: 'POST',
          body: JSON.stringify({ task_id: '2.3_verify_search', query: q }),
        });
        const overlay = document.querySelector('[id^="guidanceOverlay21-"]');
        if (res && res.passed) {
          if (overlay) await this._refresh(overlay);
          alert(`✅ 验证通过：${res.evidence || ''}`);
        } else {
          const msg = (res && res.evidence) || `知识库中未检索到“${q}”相关内容`;
          alert(`❌ 验证未通过：${msg}`);
          if (btn) {
            btn.disabled = false;
            btn.textContent = '验证可搜索';
          }
        }
      } catch (e) {
        console.warn('[guidance] verify search failed:', e);
        alert('验证失败：' + ((e && e.message) || '请稍后重试'));
        if (btn) {
          btn.disabled = false;
          btn.textContent = '验证可搜索';
        }
      }
    },

    async handleUpload(file, taskId, input) {
      if (!file) return;
      let endpoint;
      if (taskId === '1.3_import_entities') endpoint = '/api/guidance/implementation/import-business-entities';
      else if (taskId === '2.2_batch_import') endpoint = '/api/guidance/implementation/import-knowledge';
      else return;
      const formData = new FormData();
      formData.append('file', file);
      try {
        const res = await fetch(endpoint, { method: 'POST', body: formData, credentials: 'include' });
        const data = await res.json().catch(() => ({}));
        if (res.ok && data && data.ok !== false) {
          const overlay = document.querySelector('[id^="guidanceOverlay21-"]');
          if (overlay) await this._refresh(overlay);
          if (taskId === '1.3_import_entities') {
            const ec = data.entity_count ?? 0;
            const rc = data.relation_count ?? 0;
            alert(`✅ 导入成功：${ec} 个实体、${rc} 条关系，已自动验证。`);
          } else if (taskId === '2.2_batch_import') {
            alert(`✅ 知识库导入完成：${data.import_result || ''} 篇，已自动验证。`);
          }
        } else if (data && data.error) {
          alert('操作失败：' + data.error);
        } else {
          alert('操作失败，请稍后重试');
        }
      } catch (e) {
        console.warn('[guidance] upload failed:', e);
        alert('上传失败，请稍后重试');
      } finally {
        if (input) input.value = '';
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

    async _openEntityDoc(endpoint) {
      try {
        const res = await fetch(endpoint, { credentials: 'include' });
        if (!res.ok) throw new Error('doc fetch failed');
        const data = await res.json();
        this._showEntityDocModal(data);
      } catch (e) {
        console.warn('[guidance] entity-doc fetch failed:', e);
        alert('加载文档失败，请稍后重试');
      }
    },

    _showEntityDocModal(data) {
      const existing = document.getElementById('gp21EntityDocModal');
      if (existing) existing.remove();
      const modal = document.createElement('div');
      modal.id = 'gp21EntityDocModal';
      modal.className = 'gp21-modal';
      const esc = s => String(s||'').replace(/[&<>]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]));
      modal.innerHTML = [
        '<div class="gp21-modal-card">',
        '  <div class="gp21-modal-head">',
        '    <div>',
        '      <div class="gp21-modal-title">', esc(data.title || ''), '</div>',
        '      <div class="gp21-modal-path">', esc(data.path || ''), '</div>',
        '    </div>',
        '    <button class="gp21-btn gp21-modal-close">关闭</button>',
        '  </div>',
        '  <div class="gp21-modal-body"><div class="gp21-md-host"></div></div>',
        '</div>'
      ].join('');
      document.body.appendChild(modal);
      const host = modal.querySelector('.gp21-md-host');
      host.innerHTML = this._renderMd(data.content || '');
      modal.querySelector('.gp21-modal-close').addEventListener('click', () => modal.remove());
      modal.addEventListener('click', (e) => { if (e.target === modal) modal.remove(); });
    },

    _renderMd(md) {
      const esc = s => String(s||'').replace(/[&<>]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;'}[c]));
      const lines = String(md || '').split(/\r?\n/);
      const out = [];
      let inCode = false;
      let inList = false;
      let para = [];
      const flushPara = () => { if (para.length) { out.push('<p>' + esc(para.join(' ')) + '</p>'); para = []; } };
      const flushList = () => { if (inList) { out.push('</ul>'); inList = false; } };
      for (const raw of lines) {
        if (raw.startsWith('```')) {
          flushPara(); flushList();
          if (inCode) { out.push('</code></pre>'); inCode = false; }
          else { out.push('<pre><code>'); inCode = true; }
          continue;
        }
        if (inCode) { out.push(esc(raw) + '\n'); continue; }
        if (!raw.trim()) { flushPara(); flushList(); continue; }
        const h = raw.match(/^(#{1,3})\s+(.*)/);
        if (h) {
          flushPara(); flushList();
          out.push('<h' + h[1].length + '>' + esc(h[2]) + '</h' + h[1].length + '>');
          continue;
        }
        const li = raw.match(/^[-*]\s+(.*)/);
        if (li) {
          flushPara();
          if (!inList) { out.push('<ul>'); inList = true; }
          const inline = esc(li[1]).replace(/`([^`]+)`/g, '<code>$1</code>');
          out.push('<li>' + inline + '</li>');
          continue;
        }
        para.push(raw);
      }
      flushPara(); flushList();
      if (inCode) out.push('</code></pre>');
      return out.join('\n');
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