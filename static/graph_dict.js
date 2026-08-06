/* ==========================================
   GRAPH — Dictionary management modal
   ========================================== */
(function() {
  "use strict";

  let mount = null;
  let state = {
    items: [],
    total: 0,
    page: 1,
    size: 50,
    category: "all",
    query: "",
    editingId: null,   // 正在行内编辑的条目 id
    editForm: {},      // 编辑中的临时数据
  };

  const CATEGORIES = [
    { key: "all",        label: "全部" },
    { key: "node_label", label: "节点标签" },
    { key: "rel_type",   label: "关系类型" },
    { key: "property_key", label: "属性名" },
    { key: "property_value", label: "属性值" },
  ];

  const CATEGORY_SHORT = {
    node_label: "节点",
    rel_type:   "关系",
    property_key: "属性",
    property_value: "值",
  };

  document.addEventListener("DOMContentLoaded", () => {
    mount = document.getElementById("graphCrudMount");
  });

  function escHtml(s) {
    return String(s).replace(/[&<>"']/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // ── 打开字典管理模态框 ────────────────────────────
  function open() {
    if (!mount) mount = document.getElementById("graphCrudMount");
    if (!mount) return;
    state.page = 1;
    state.editingId = null;
    render();
    loadItems();
  }

  function close() {
    if (mount) mount.innerHTML = "";
    state.editingId = null;
  }

  // ── 数据加载 ──────────────────────────────────────
  async function loadItems() {
    const params = new URLSearchParams();
    if (state.category !== "all") params.set("category", state.category);
    if (state.query) params.set("q", state.query);
    params.set("page", String(state.page));
    params.set("size", String(state.size));
    try {
      const res = await fetch("/api/graph/dictionary?" + params.toString());
      const json = await res.json();
      if (!json.ok) throw new Error(json.error || "加载失败");
      state.items = json.data.items || [];
      state.total = json.data.total || 0;
    } catch (e) {
      state.items = [];
      state.total = 0;
      console.error("load dictionary items failed:", e);
    }
    renderTable();
    renderPagination();
  }

  // ── 渲染 ──────────────────────────────────────────
  function render() {
    if (!mount) return;
    mount.innerHTML = `
      <div class="graph-crud-backdrop"></div>
      <div class="graph-dict-modal">
        <div class="graph-crud-head">
          <h3>图库字典管理</h3>
          <div class="graph-dict-head-actions">
            <button class="panel-head-btn" id="dictRefreshBtn" title="刷新">🔄</button>
            <button class="panel-head-btn" id="dictCloseBtn">✕</button>
          </div>
        </div>
        <div class="graph-dict-body">
          <div class="graph-dict-toolbar">
            <button class="btn btn-primary" id="dictAddBtn">+ 新增条目</button>
            <button class="btn btn-secondary" id="dictImportCsvBtn">导入 CSV</button>
            <button class="btn btn-secondary" id="dictImportJsonBtn">导入 JSON</button>
            <button class="btn btn-secondary" id="dictExportJsonBtn">导出 JSON</button>
            <button class="btn btn-secondary" id="dictExportYamlBtn">导出 YAML</button>
            <span class="graph-dict-stats" id="dictStats"></span>
          </div>
          <div class="graph-dict-filters">
            <div class="graph-dict-categories" id="dictCategories">
              ${CATEGORIES.map(c =>
                `<button class="graph-dict-cat ${state.category === c.key ? "active" : ""}" data-cat="${c.key}">${c.label}</button>`
              ).join("")}
            </div>
            <div class="graph-dict-search-wrap">
              <input class="graph-dict-search" id="dictSearchInput" placeholder="搜索原文/译文..." value="${escHtml(state.query)}">
            </div>
          </div>
          <div class="graph-dict-table-wrap">
            <table class="graph-dict-table">
              <thead>
                <tr>
                  <th class="col-cat">分类</th>
                  <th class="col-source">原文</th>
                  <th class="col-target">译文</th>
                  <th class="col-desc">描述</th>
                  <th class="col-toggle">启用</th>
                  <th class="col-actions">操作</th>
                </tr>
              </thead>
              <tbody id="dictTableBody"></tbody>
            </table>
          </div>
          <div class="graph-dict-pagination" id="dictPagination"></div>
        </div>
      </div>`;

    // 绑定事件
    mount.querySelector("#dictCloseBtn").addEventListener("click", close);
    mount.querySelector(".graph-crud-backdrop").addEventListener("click", close);
    mount.querySelector("#dictRefreshBtn").addEventListener("click", () => loadItems());

    mount.querySelector("#dictAddBtn").addEventListener("click", () => showAddForm());
    mount.querySelector("#dictImportCsvBtn").addEventListener("click", () => showImportDialog("csv"));
    mount.querySelector("#dictImportJsonBtn").addEventListener("click", () => showImportDialog("json"));
    mount.querySelector("#dictExportJsonBtn").addEventListener("click", () => doExport("json"));
    mount.querySelector("#dictExportYamlBtn").addEventListener("click", () => doExport("yaml"));

    // 分类筛选
    mount.querySelector("#dictCategories").addEventListener("click", (e) => {
      const btn = e.target.closest(".graph-dict-cat");
      if (!btn) return;
      state.category = btn.dataset.cat;
      state.page = 1;
      document.querySelectorAll(".graph-dict-cat").forEach(b => b.classList.toggle("active", b.dataset.cat === state.category));
      loadItems();
    });

    // 搜索（防抖）
    let debounceTimer = null;
    mount.querySelector("#dictSearchInput").addEventListener("input", (e) => {
      clearTimeout(debounceTimer);
      debounceTimer = setTimeout(() => {
        state.query = e.target.value;
        state.page = 1;
        loadItems();
      }, 300);
    });
  }

  function renderTable() {
    const tbody = document.getElementById("dictTableBody");
    if (!tbody) return;
    if (state.items.length === 0) {
      tbody.innerHTML = `<tr><td colspan="6" class="graph-dict-empty">暂无字典条目</td></tr>`;
      return;
    }
    tbody.innerHTML = state.items.map(item => {
      const isEditing = state.editingId === item.id;
      if (isEditing) {
        return renderEditRow(item);
      }
      const catLabel = CATEGORY_SHORT[item.category] || item.category;
      return `
        <tr data-id="${item.id}">
          <td><span class="dict-cat-badge dict-cat-${item.category}">${catLabel}</span></td>
          <td class="col-source">${escHtml(item.source)}</td>
          <td class="col-target">${escHtml(item.target)}</td>
          <td class="col-desc">${escHtml(item.description || "")}</td>
          <td><label class="dict-toggle"><input type="checkbox" ${item.enabled ? "checked" : ""} data-id="${item.id}"><span class="dict-toggle-slider"></span></label></td>
          <td>
            <button class="dict-btn-icon dict-btn-edit" data-id="${item.id}" title="编辑">✎</button>
            <button class="dict-btn-icon dict-btn-del" data-id="${item.id}" title="删除">✕</button>
          </td>
        </tr>`;
    }).join("");

    // 绑定 toggle 事件
    tbody.querySelectorAll(".dict-toggle input").forEach(cb => {
      cb.addEventListener("change", () => doToggle(cb.dataset.id));
    });
    // 绑定编辑事件
    tbody.querySelectorAll(".dict-btn-edit").forEach(btn => {
      btn.addEventListener("click", () => startEdit(btn.dataset.id));
    });
    // 绑定删除事件
    tbody.querySelectorAll(".dict-btn-del").forEach(btn => {
      btn.addEventListener("click", () => doDelete(btn.dataset.id));
    });
  }

  function renderEditRow(item) {
    const f = state.editForm;
    const catOpts = CATEGORIES.filter(c => c.key !== "all").map(c =>
      `<option value="${c.key}" ${(f.category || item.category) === c.key ? "selected" : ""}>${c.label}</option>`
    ).join("");
    return `
      <tr class="dict-editing" data-id="${item.id}">
        <td><select class="dict-edit-select">${catOpts}</select></td>
        <td><input class="dict-edit-input" value="${escHtml(f.source || item.source)}" data-field="source"></td>
        <td><input class="dict-edit-input" value="${escHtml(f.target || item.target)}" data-field="target"></td>
        <td><input class="dict-edit-input" value="${escHtml(f.description || item.description || "")}" data-field="description"></td>
        <td></td>
        <td>
          <button class="dict-btn-icon dict-btn-save" data-id="${item.id}" title="保存">✓</button>
          <button class="dict-btn-icon dict-btn-cancel" title="取消">↩</button>
        </td>
      </tr>`;
  }

  function renderPagination() {
    const el = document.getElementById("dictPagination");
    if (!el) return;
    const totalPages = Math.ceil(state.total / state.size) || 1;
    el.innerHTML = `
      <span class="dict-page-info">共 ${state.total} 条，第 ${state.page}/${totalPages} 页</span>
      <button class="btn btn-secondary btn-sm" id="dictPrevPage" ${state.page <= 1 ? "disabled" : ""}>← 上一页</button>
      <button class="btn btn-secondary btn-sm" id="dictNextPage" ${state.page >= totalPages ? "disabled" : ""}>下一页 →</button>`;
    el.querySelector("#dictPrevPage")?.addEventListener("click", () => { if (state.page > 1) { state.page--; loadItems(); }});
    el.querySelector("#dictNextPage")?.addEventListener("click", () => { if (state.page < totalPages) { state.page++; loadItems(); }});
  }

  // ── CRUD ──────────────────────────────────────────

  function startEdit(id) {
    const item = state.items.find(i => i.id === id);
    if (!item) return;
    state.editingId = id;
    state.editForm = {};
    renderTable();
    // 绑定编辑行事件
    const row = document.querySelector(`tr.dict-editing[data-id="${id}"]`);
    if (!row) return;
    // 输入框变化收集
    row.querySelectorAll(".dict-edit-input").forEach(inp => {
      inp.addEventListener("input", () => {
        state.editForm[inp.dataset.field] = inp.value;
      });
    });
    // 分类变化
    row.querySelector(".dict-edit-select")?.addEventListener("change", (e) => {
      state.editForm.category = e.target.value;
    });
    // 保存
    row.querySelector(".dict-btn-save")?.addEventListener("click", () => doEdit(id));
    // 取消
    row.querySelector(".dict-btn-cancel")?.addEventListener("click", () => {
      state.editingId = null;
      state.editForm = {};
      renderTable();
    });
    // 回车保存
    row.querySelectorAll(".dict-edit-input").forEach(inp => {
      inp.addEventListener("keydown", (e) => {
        if (e.key === "Enter") doEdit(id);
        if (e.key === "Escape") { state.editingId = null; state.editForm = {}; renderTable(); }
      });
    });
  }

  async function doEdit(id) {
    const item = state.items.find(i => i.id === id);
    if (!item) return;
    const row = document.querySelector(`tr.dict-editing[data-id="${id}"]`);
    if (!row) return;
    const patch = {};
    const select = row.querySelector(".dict-edit-select");
    if (select) patch.category = select.value;
    row.querySelectorAll(".dict-edit-input").forEach(inp => {
      patch[inp.dataset.field] = inp.value;
    });
    if (!patch.source || !patch.target) { alert("原文和译文不能为空"); return; }
    try {
      const res = await fetch("/api/graph/dictionary/" + encodeURIComponent(id), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      const json = await res.json();
      if (!json.ok) throw new Error(json.error || "更新失败");
      state.editingId = null;
      state.editForm = {};
      loadItems();
      notifyDictChange();
    } catch (e) {
      alert("更新失败: " + e.message);
    }
  }

  async function doToggle(id) {
    try {
      const res = await fetch("/api/graph/dictionary/" + encodeURIComponent(id) + "/toggle", {
        method: "PATCH",
      });
      const json = await res.json();
      if (!json.ok) throw new Error(json.error || "操作失败");
      loadItems();
      notifyDictChange();
    } catch (e) {
      console.error("toggle failed:", e);
      loadItems(); // 回滚 UI
    }
  }

  async function doDelete(id) {
    if (!confirm("确定删除该字典条目？")) return;
    try {
      const res = await fetch("/api/graph/dictionary/" + encodeURIComponent(id), {
        method: "DELETE",
      });
      const json = await res.json();
      if (!json.ok) throw new Error(json.error || "删除失败");
      loadItems();
      notifyDictChange();
    } catch (e) {
      alert("删除失败: " + e.message);
    }
  }

  // ── 新增表单（子模态框） ────────────────────────────
  function showAddForm() {
    const backdrop = document.createElement("div");
    backdrop.className = "graph-crud-backdrop";
    backdrop.addEventListener("click", () => backdrop.remove() || formWrap.remove());

    const formWrap = document.createElement("div");
    formWrap.className = "graph-dict-form-wrap";
    formWrap.innerHTML = `
      <div class="graph-dict-form">
        <div class="graph-crud-head">
          <h3>新增字典条目</h3>
          <button class="panel-head-btn" id="dictFormClose">✕</button>
        </div>
        <div class="graph-dict-form-body">
          <label>分类
            <select id="dictFormCategory">
              <option value="node_label">节点标签</option>
              <option value="rel_type">关系类型</option>
              <option value="property_key">属性名</option>
              <option value="property_value">属性值</option>
            </select>
          </label>
          <label>原文（英文）
            <input id="dictFormSource" placeholder="例: Host" autocomplete="off">
          </label>
          <label>译文（中文）
            <input id="dictFormTarget" placeholder="例: 主机" autocomplete="off">
          </label>
          <label>描述（可选）
            <input id="dictFormDesc" placeholder="描述信息" autocomplete="off">
          </label>
          <div class="graph-crud-actions">
            <button class="btn btn-secondary" id="dictFormCancel">取消</button>
            <button class="btn btn-primary" id="dictFormSave">保存</button>
          </div>
        </div>
      </div>`;

    document.body.appendChild(backdrop);
    document.body.appendChild(formWrap);

    formWrap.querySelector("#dictFormClose").addEventListener("click", () => { backdrop.remove(); formWrap.remove(); });
    formWrap.querySelector("#dictFormCancel").addEventListener("click", () => { backdrop.remove(); formWrap.remove(); });
    formWrap.querySelector("#dictFormSave").addEventListener("click", async () => {
      const source = document.getElementById("dictFormSource").value.trim();
      const target = document.getElementById("dictFormTarget").value.trim();
      const category = document.getElementById("dictFormCategory").value;
      const description = document.getElementById("dictFormDesc").value.trim();
      if (!source || !target) { alert("原文和译文不能为空"); return; }
      try {
        const res = await fetch("/api/graph/dictionary", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ source, target, category, description }),
        });
        const json = await res.json();
        if (!json.ok) throw new Error(json.error || "创建失败");
        backdrop.remove();
        formWrap.remove();
        loadItems();
        notifyDictChange();
      } catch (e) {
        alert("创建失败: " + e.message);
      }
    });
    // 回车保存
    formWrap.querySelectorAll("input").forEach(inp => {
      inp.addEventListener("keydown", (e) => {
        if (e.key === "Enter") formWrap.querySelector("#dictFormSave").click();
      });
    });
    setTimeout(() => document.getElementById("dictFormSource")?.focus(), 100);
  }

  // ── 导入对话框 ────────────────────────────────────
  function showImportDialog(format) {
    const label = format === "csv" ? "CSV" : "JSON";
    const placeholder = format === "csv"
      ? "category,source,target\nnode_label,Host,主机\nrel_type,DEPENDS_ON,依赖"
      : '[{"category":"node_label","source":"Host","target":"主机"}]';

    const backdrop = document.createElement("div");
    backdrop.className = "graph-crud-backdrop";
    backdrop.addEventListener("click", () => backdrop.remove() || dialogWrap.remove());

    const dialogWrap = document.createElement("div");
    dialogWrap.className = "graph-dict-form-wrap";
    dialogWrap.innerHTML = `
      <div class="graph-dict-form graph-dict-import">
        <div class="graph-crud-head">
          <h3>导入字典 (${label})</h3>
          <button class="panel-head-btn" id="dictImportClose">✕</button>
        </div>
        <div class="graph-dict-form-body">
          <label>请粘贴 ${label} 内容</label>
          <textarea id="dictImportContent" rows="8" placeholder="${placeholder}"></textarea>
          <div class="graph-crud-actions">
            <button class="btn btn-secondary" id="dictImportCancel">取消</button>
            <button class="btn btn-primary" id="dictImportSave">导入</button>
          </div>
        </div>
      </div>`;

    document.body.appendChild(backdrop);
    document.body.appendChild(dialogWrap);

    dialogWrap.querySelector("#dictImportClose").addEventListener("click", () => { backdrop.remove(); dialogWrap.remove(); });
    dialogWrap.querySelector("#dictImportCancel").addEventListener("click", () => { backdrop.remove(); dialogWrap.remove(); });
    dialogWrap.querySelector("#dictImportSave").addEventListener("click", async () => {
      const content = document.getElementById("dictImportContent").value.trim();
      if (!content) { alert("内容不能为空"); return; }
      try {
        const res = await fetch("/api/graph/dictionary/import", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ format, content }),
        });
        const json = await res.json();
        if (!json.ok) throw new Error(json.error || "导入失败");
        const msg = `导入完成: 新增 ${json.added} 条，跳过 ${json.failed} 条`;
        if (json.errors && json.errors.length > 0) {
          alert(msg + "\n\n错误详情:\n" + json.errors.slice(0, 5).join("\n"));
        } else {
          alert(msg);
        }
        backdrop.remove();
        dialogWrap.remove();
        loadItems();
        notifyDictChange();
      } catch (e) {
        alert("导入失败: " + e.message);
      }
    });
  }

  // ── 导出 ──────────────────────────────────────────
  async function doExport(format) {
    try {
      const params = new URLSearchParams();
      params.set("format", format);
      if (state.category !== "all") params.set("category", state.category);
      const res = await fetch("/api/graph/dictionary/export?" + params.toString());
      const json = await res.json();
      if (!json.ok) throw new Error(json.error || "导出失败");
      const content = json.data;
      const ext = format === "yaml" ? "yaml" : "json";
      const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `graph-dictionary.${ext}`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      alert("导出失败: " + e.message);
    }
  }

  // ── 通知字典变更 ──────────────────────────────────
  function notifyDictChange() {
    // 触发自定义事件，让 graph_view_graph.js 重新加载字典映射
    const panel = document.getElementById("panelGraph");
    if (panel) {
      panel.dispatchEvent(new CustomEvent("dict:changed"));
    }
  }

  // ── 导出 API ──────────────────────────────────────
  window.GraphDict = { open, close };

})();
