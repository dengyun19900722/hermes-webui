/* ==========================================
   GRAPH PANEL — Main controller
   ========================================== */
(function() {
  "use strict";

  const state = {
    backend: "unknown",
    healthOk: false,
    schema: null,
    currentView: "graph",
    selectedNodeId: null,
    selectedRelId: null,
    dictEnabled: true,
    dictMap: {
      node_labels: {},
      rel_types: {},
      property_keys: {},
      property_values: {},
    },
  };

  let panel, tabs, views, searchInput, searchDropdown, statusNodes, statusEdges, statusMsg, backendBadge;

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json" },
      ...opts,
    });
    const json = await res.json();
    if (!json.ok) throw new Error(json.error || "API error");
    return json.data;
  }

  function $(id) { return document.getElementById(id); }
  function $$(sel, root = document) { return Array.from(root.querySelectorAll(sel)); }

  async function init() {
    panel = $("panelGraph");
    if (!panel) return;

    tabs = $$(".graph-tab", panel);
    views = $$(".graph-view", panel);
    searchInput = $("graphSearchInput");
    searchDropdown = $("graphSearchDropdown");
    statusNodes = $("graphStatusNodes");
    statusEdges = $("graphStatusEdges");
    statusMsg = $("graphStatusMsg");
    backendBadge = $("graphBackendBadge");

    tabs.forEach(tab => tab.addEventListener("click", () => switchView(tab.dataset.view)));
    if (searchInput) {
      let timer = null;
      searchInput.addEventListener("input", () => {
        clearTimeout(timer);
        timer = setTimeout(doSearch, 250);
      });
    }

    const seedBtn = $("graphSeedBtn");
    if (seedBtn) seedBtn.addEventListener("click", loadSample);
    const refreshBtn = $("graphRefreshBtn");
    if (refreshBtn) refreshBtn.addEventListener("click", loadSchema);
    const closeBtn = $("graphCloseBtn");
    if (closeBtn) closeBtn.addEventListener("click", () => switchPanel && switchPanel("graph"));
    const dictBtn = $("graphDictBtn");
    if (dictBtn) dictBtn.addEventListener("click", () => {
      if (window.GraphDict) window.GraphDict.open();
    });
    const emptySeedBtn = $("graphEmptySeedBtn");
    if (emptySeedBtn) emptySeedBtn.addEventListener("click", loadSample);
    const emptyCreateBtn = $("graphEmptyCreateBtn");
    if (emptyCreateBtn) emptyCreateBtn.addEventListener("click", () => {
      if (window.GraphCRUD) window.GraphCRUD.openCreateNode();
    });

    // 监听 panel 获得 active 类（其他面板切换可能不会派发 panel:show）
    const observer = new MutationObserver(muts => {
      for (const m of muts) {
        if (m.attributeName === "class" && panel.classList.contains("active")) {
          onPanelShow();
          return;
        }
      }
    });
    observer.observe(panel, { attributes: true, attributeFilter: ["class"] });

    // 兼容性：保留 panel:show 事件监听（其他代码可能派发）
    panel.addEventListener("panel:show", onPanelShow);

    // 同步 body.graph-fullscreen 状态：让 graph 面板在 active 时铺满 topbar 以下区域。
    // 监听 class 与 hidden 属性变化，确保切回其他面板时立刻收起。
    const layoutObserver = new MutationObserver(() => syncFullscreenState());
    layoutObserver.observe(panel, { attributes: true, attributeFilter: ["class", "hidden"] });
    syncFullscreenState();
  }

  function syncFullscreenState() {
    if (!panel) return;
    const isActive = panel.classList.contains("active");
    document.body.classList.toggle("graph-fullscreen", isActive);
  }

  async function onPanelShow() {
    if (!panel.classList.contains("active")) return;
    await checkHealth();
    await loadSchema();
    await loadDictionary();
    if (window.GraphViewGraph && typeof window.GraphViewGraph.onShow === "function") {
      window.GraphViewGraph.onShow();
    }
  }

  async function checkHealth() {
    try {
      const h = await api("/api/graph/health");
      state.backend = h.backend;
      state.healthOk = h.ok;
      renderBackendBadge();
    } catch (e) {
      setStatus("Health check failed: " + e.message, "error");
    }
  }

  function renderBackendBadge() {
    if (!backendBadge) return;
    backendBadge.hidden = false;
    backendBadge.textContent = state.backend === "neo4j" ? "Neo4j" : "Mock";
    backendBadge.className = "graph-backend-badge " + (state.backend === "neo4j" ? "ok" : "warn");
  }

  async function loadSchema() {
    try {
      state.schema = await api("/api/graph/schema");
      renderSchema();
      checkEmptyState();
      notifyViews("schema");
    } catch (e) {
      setStatus("Schema load failed: " + e.message, "error");
    }
  }

  function renderSchema() {
    const s = state.schema;
    if (!s) return;
    if (statusNodes) statusNodes.textContent = s.stats?.node_count ?? 0;
    if (statusEdges) statusEdges.textContent = s.stats?.relationship_count ?? 0;
    setStatus("Ready — " + (s.node_labels?.length || 0) + " labels, " +
              (s.relationship_types?.length || 0) + " relationship types");
  }

  function checkEmptyState() {
    const emptyEl = $("graphEmptyState");
    if (!emptyEl) return;
    const count = state.schema?.stats?.node_count;
    const isEmpty = state.backend === "mock" &&
                    typeof count === "number" &&
                    count === 0;
    emptyEl.hidden = !isEmpty;
  }

  async function loadSample() {
    if (!confirm("Load sample data into the graph? This may add new nodes if not already present.")) return;
    try {
      const res = await api("/api/graph/seed", { method: "POST", body: "{}" });
      setStatus(`Loaded ${res.nodes_added} nodes, ${res.relationships_added} relationships`);
      await loadSchema();
    } catch (e) {
      setStatus("Seed failed: " + e.message, "error");
    }
  }

  async function doSearch() {
    const q = searchInput.value.trim();
    if (!q) {
      if (searchDropdown) searchDropdown.hidden = true;
      return;
    }
    try {
      const res = await api("/api/graph/search?q=" + encodeURIComponent(q) + "&limit=5");
      // api() 已 unwrap {ok, data}，所以 res 就是 {results, query, count}
      const results = (res && res.results) || [];
      showSearchDropdown(results);
    } catch (e) {
      // Silent: search is progressive enhancement
    }
  }

  // 计算 label 颜色（与 graph_view_graph.js 的 colorForLabel 保持一致）
  const _searchLabelColorCache = { Host: "#4A90E2", Service: "#7ED321", Incident: "#D0021B", Runbook: "#F5A623" };
  const _searchLabelPalette = ["#FF6B6B", "#4A90E2", "#F5A623", "#7ED321", "#9013FE", "#50E3C2", "#D0021B", "#BD10E6", "#417505", "#8B572A", "#FF8C00", "#00CED1", "#FF1493", "#32CD32", "#FFD700"];
  function _searchLabelColor(label) {
    if (_searchLabelColorCache[label]) return _searchLabelColorCache[label];
    let h = 0;
    for (let i = 0; i < label.length; i++) h = (h * 31 + label.charCodeAt(i)) | 0;
    const c = _searchLabelPalette[Math.abs(h) % _searchLabelPalette.length];
    _searchLabelColorCache[label] = c;
    return c;
  }

  function showSearchDropdown(nodes) {
    if (!searchDropdown) return;
    if (!nodes || nodes.length === 0) {
      searchDropdown.hidden = true;
      return;
    }
    const rows = nodes.map(n => {
      const label = (n.labels && n.labels[0]) || "?";
      // label 走字典翻译，属性名也走
      const labelTr = applyDictToLabels(label, "node_labels");
      // 智能 name fallback：name → title → serviceName → hostname → code → id → 短化 id
      const p = n.properties || {};
      let name = p.name || p.title || p.serviceName || p.hostname || p.code || p.service || p.id;
      if (!name && p.id) name = p.id;
      if (!name) {
        // fallback: 取 id 最后一段（Neo4j 的 id 类似 "4:uuid:123"）
        const idStr = String(n.id);
        name = idStr.length > 16 ? idStr.substring(0, 8) + "..." : idStr;
      }
      const color = _searchLabelColor(label);
      return `<div class="graph-search-result" data-id="${escAttr(n.id)}" title="${escAttr(labelTr + " · " + name)}">
        <span class="graph-search-label-pill" style="background:${escAttr(color)}">${escHtml(labelTr)}</span>
        <span class="graph-search-result-meta">
          <span class="graph-search-node-name">${escHtml(String(name))}</span>
        </span>
        <span class="graph-search-action">全链路</span>
      </div>`;
    }).join("");
    const hint = `<div class="graph-search-hint">提示：<kbd>单击</kbd> 查看详情 · <kbd>双击</kbd> 查看全链路（顶部出现工具栏调整深度/方向）</div>`;
    searchDropdown.innerHTML = rows + hint;
    searchDropdown.querySelectorAll(".graph-search-result").forEach(el => {
      el.addEventListener("click", () => {
        const id = el.dataset.id;
        const name = el.querySelector(".graph-search-node-name")?.textContent || id;
        searchInput.value = name;
        searchDropdown.hidden = true;
        if (window.GraphViewGraph) {
          switchView("graph");
          // 搜索命中 → 激活全链路视图（默认 3 层双向），并展示中心节点详情
          window.GraphViewGraph.expandNode(id);
          window.GraphViewGraph.showNodeDetail(id);
        }
      });
      el.addEventListener("dblclick", e => {
        e.preventDefault();
        e.stopPropagation();
        const id = el.dataset.id;
        searchDropdown.hidden = true;
        if (window.GraphViewGraph) {
          switchView("graph");
          window.GraphViewGraph.expandNode(id);
        }
      });
    });
    searchDropdown.hidden = false;
  }

  function setStatus(msg, kind = "info") {
    if (!statusMsg) return;
    statusMsg.textContent = msg;
    statusMsg.dataset.kind = kind;
  }

  function switchView(view) {
    if (!["graph", "table", "json"].includes(view)) return;
    state.currentView = view;
    tabs.forEach(t => {
      const active = t.dataset.view === view;
      t.classList.toggle("active", active);
      t.setAttribute("aria-selected", active ? "true" : "false");
    });
    views.forEach(v => v.hidden = v.dataset.view !== view);
    notifyViews("view-changed", view);
  }

  function notifyViews(event, payload) {
    if (event === "view-changed" && payload === "graph" && window.GraphViewGraph) {
      window.GraphViewGraph.onShow();
    }
    if (event === "view-changed" && payload === "table" && window.GraphViewTable) {
      window.GraphViewTable.onShow(state.schema);
    }
    if (event === "view-changed" && payload === "json" && window.GraphViewJson) {
      window.GraphViewJson.onShow(state.schema);
    }
    if (event === "schema" && window.GraphViewTable) {
      window.GraphViewTable.onShow(state.schema);
    }
  }

  function escHtml(s) {
    return String(s).replace(/[&<>"']/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function escAttr(s) { return escHtml(s); }

  // ── 字典管理 ────────────────────────────────────────
  async function loadDictionary() {
    try {
      const res = await fetch("/api/graph/dictionary/apply");
      const json = await res.json();
      if (json.ok && json.data) {
        state.dictMap = json.data;
      }
    } catch (e) {
      console.warn("load dictionary failed:", e);
    }
  }

  function applyDictToLabels(text, mapType) {
    if (!state.dictEnabled || !text) return text;
    const map = state.dictMap[mapType];
    if (!map) return text;
    return map[text] || text;
  }

  // 监听字典变更事件，刷新字典映射
  document.addEventListener("DOMContentLoaded", () => {
    const panel = document.getElementById("panelGraph");
    if (panel) {
      panel.addEventListener("dict:changed", async () => {
        await loadDictionary();
        if (window.GraphViewGraph && typeof window.GraphViewGraph.applyDictToGraph === "function") {
          window.GraphViewGraph.applyDictToGraph();
        }
        // 重新跑一次 i18n stamping，确保新增/编辑后的占位文本等也跟随 locale
        if (typeof window.applyLocaleToDOM === "function") window.applyLocaleToDOM();
      });
    }
  });

  document.addEventListener("DOMContentLoaded", init);

  window.GraphMain = { state, switchView, getState: () => state, setStatus, loadDictionary, applyDictToLabels };
})();
