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
  }

  async function onPanelShow() {
    if (!panel.classList.contains("active")) return;
    await checkHealth();
    await loadSchema();
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
    const isEmpty = state.backend === "mock" &&
                    state.schema?.stats?.node_count === 0;
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
      showSearchDropdown(res.results || []);
    } catch (e) {
      // Silent: search is progressive enhancement
    }
  }

  function showSearchDropdown(nodes) {
    if (!searchDropdown) return;
    if (!nodes || nodes.length === 0) {
      searchDropdown.hidden = true;
      return;
    }
    searchDropdown.innerHTML = nodes.map(n => {
      const label = (n.labels && n.labels[0]) || "?";
      const name = (n.properties && (n.properties.name || n.properties.title)) || n.id;
      return `<div class="graph-search-result" data-id="${escAttr(n.id)}">
        <span class="graph-node-label">${escHtml(label)}</span>
        <span class="graph-node-name">${escHtml(String(name))}</span>
      </div>`;
    }).join("");
    searchDropdown.querySelectorAll(".graph-search-result").forEach(el => {
      el.addEventListener("click", () => {
        const id = el.dataset.id;
        searchInput.value = "";
        searchDropdown.hidden = true;
        if (window.GraphViewGraph) window.GraphViewGraph.expandNode(id);
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

  document.addEventListener("DOMContentLoaded", init);

  window.GraphMain = { state, switchView, getState: () => state, setStatus };
})();
