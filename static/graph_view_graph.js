/* ==========================================
   GRAPH — Cytoscape view
   ========================================== */
(function() {
  "use strict";

  let cy = null;
  let canvas = null;
  let nodeMap = {};
  let relMap = {};
  let loadAllNodesPromise = null;
  let loadAllNodesAbort = null;
  // Neo4j Browser 风格的 label 调色板（按出现顺序分配，多余的用 hash 派生）
  const LABEL_PALETTE = [
    "#FF6B6B", "#4A90E2", "#F5A623", "#7ED321", "#9013FE",
    "#50E3C2", "#D0021B", "#BD10E6", "#417505", "#8B572A",
    "#FF8C00", "#00CED1", "#FF1493", "#32CD32", "#FFD700",
  ];
  // 兼容老数据：固定颜色覆盖
  const LABEL_COLORS = {
    Host: "#4A90E2", Service: "#7ED321", Incident: "#D0021B", Runbook: "#F5A623",
  };
  const _labelColorCache = Object.assign({}, LABEL_COLORS);
  function colorForLabel(label) {
    if (_labelColorCache[label]) return _labelColorCache[label];
    // 用 label 字符串的 hash 稳定分配颜色
    let h = 0;
    for (let i = 0; i < label.length; i++) h = (h * 31 + label.charCodeAt(i)) | 0;
    const color = LABEL_PALETTE[Math.abs(h) % LABEL_PALETTE.length];
    _labelColorCache[label] = color;
    return color;
  }
  // 当前 filter：null / "label:LABEL" / "rel:TYPE"
  let activeFilter = null;
  // 单个 fetch 带超时（防止 server 卡住时无限 pending）
  async function fetchWithTimeout(url, opts = {}, timeoutMs = 8000) {
    const ctrl = new AbortController();
    const t = setTimeout(() => ctrl.abort(), timeoutMs);
    try {
      return await fetch(url, { ...opts, signal: ctrl.signal });
    } finally {
      clearTimeout(t);
    }
  }

  function $(id) { return document.getElementById(id); }

  function init() {
    canvas = $("graphCanvas");
    if (!canvas || typeof cytoscape === "undefined") return;

    cy = cytoscape({
      container: canvas,
      style: [
        { selector: "node", style: {
            // 名字显示在节点正中间（text-valign: center）
            label: "data(name)",
            "background-color": "data(color)",
            "border-width": 2,
            "border-color": "data(borderColor)",
            width: 48, height: 48,
            "font-size": 10,
            "text-valign": "center",
            "text-halign": "center",
            color: "#fff",
            "text-wrap": "ellipsis",
            "text-max-width": "44px",
            "font-weight": 600,
        }},
        { selector: "edge", style: {
            label: "data(label)",
            width: 2, "line-color": "#aaa", "target-arrow-color": "#aaa",
            "target-arrow-shape": "triangle", "curve-style": "bezier", "font-size": 10,
        }},
        { selector: "node:selected", style: { "border-width": 4, "border-color": "#FF6B35" }},
        { selector: "node.highlighted", style: { "border-width": 3, "border-color": "#FF6B35" }},
      ],
      layout: { name: "preset" },
      wheelSensitivity: 0.3,
    });

    cy.on("tap", "node", e => onSelectNode(e.target.id()));
    cy.on("dbltap", "node", e => expandNode(e.target.id()));
    cy.on("tap", e => {
      if (e.target === cy) clearSelection();
    });

    document.querySelectorAll(".graph-fab").forEach(btn => {
      btn.addEventListener("click", () => {
        const a = btn.dataset.action;
        if (a === "fit") cy.fit(null, 50);
        else if (a === "zoom-in") cy.zoom({ level: cy.zoom() * 1.2, renderedPosition: { x: cy.width()/2, y: cy.height()/2 }});
        else if (a === "zoom-out") cy.zoom({ level: cy.zoom() / 1.2, renderedPosition: { x: cy.width()/2, y: cy.height()/2 }});
        else if (a === "layout") cy.layout({ name: "cose", animate: true, padding: 50 }).run();
        else if (a === "clear-filter") clearFilter();
      });
    });
  }

  function onShow() {
    if (!cy) return;
    // Critical: must resize after tab switch, otherwise Cytoscape won't render
    setTimeout(() => {
      if (cy) {
        cy.resize();
        // 进入 Graph 视图时自动把数据库里已有的节点全部画出来，
        // 避免用户看到 "Graph is empty" 误以为数据没加载。
        loadAllNodes();
      }
    }, 50);
  }

  // 首次进入 panel 时也要拉（onShow 只会响应 tab 切换，panel 首次显示不会发）
  document.addEventListener("DOMContentLoaded", () => {
    if (typeof window === "undefined") return;
    // 等 panel 真的 active 之后才拉
    const tryAutoload = () => {
      const panel = document.getElementById("panelGraph");
      if (panel && panel.classList.contains("active") && cy && Object.keys(nodeMap).length === 0) {
        loadAllNodes();
      }
    };
    // 初次进来 1s 后试一次（等 schema 完成 + 视图激活）
    setTimeout(tryAutoload, 1000);
    // 之后观察 panel 的 active 类变化
    const panel = document.getElementById("panelGraph");
    if (panel) {
      const obs = new MutationObserver(() => {
        if (panel.classList.contains("active")) tryAutoload();
      });
      obs.observe(panel, { attributes: true, attributeFilter: ["class"] });
    }
  });

  async function loadAllNodes() {
    if (!cy) return;
    // 已经画过节点就不再重复拉（手动 expandNode 会增量添加新邻居）
    if (Object.keys(nodeMap).length > 0) return;
    // 防止并发：上一次还没结束就复用同一个 Promise
    if (loadAllNodesPromise) return loadAllNodesPromise;
    loadAllNodesPromise = (async () => {
      loadAllNodesAbort = new AbortController();
      const signal = loadAllNodesAbort.signal;
      try {
        // 单次全量获取所有节点，不再按 label 并发拉（避免 N 次 Neo4j round-trip）
        const nodesRes = await fetchWithTimeout(
          "/api/graph/nodes?limit=500", { signal }, 30000);
        const nodesJson = await nodesRes.json();
        if (!nodesJson.ok || !nodesJson.data) return;
        const fetched = nodesJson.data.results || [];
        if (fetched.length === 0) return;
        // 加入 cytoscape（用 colorForLabel 兜底任意 label）
        const labelCounts = Object.create(null);
        let added = 0;
        fetched.forEach(n => {
          const id = n.id;
          if (!nodeMap[id]) {
            const label = (n.labels && n.labels[0]) || "Node";
            const name = pickNodeName(n.properties, id);
            const color = colorForLabel(label);
            nodeMap[id] = cy.add({
              group: "nodes",
              data: {
                id,
                label,
                name,
                color,
                borderColor: color,
              },
            });
            labelCounts[label] = (labelCounts[label] || 0) + 1;
            added++;
          }
        });
        // 拉关系并画边，同时统计 type
        const relTypeCounts = Object.create(null);
        let relAdded = 0;
        try {
          const relsRes = await fetchWithTimeout(
            "/api/graph/relationships?limit=500", { signal }, 30000);
          const relsJson = await relsRes.json();
          if (relsJson.ok && relsJson.data && relsJson.data.results) {
            for (const r of relsJson.data.results) {
              if (!relMap[r.id] && nodeMap[r.start_node_id] && nodeMap[r.end_node_id]) {
                relMap[r.id] = cy.add({
                  group: "edges",
                  data: { id: r.id, source: r.start_node_id, target: r.end_node_id, label: r.type },
                });
                relTypeCounts[r.type] = (relTypeCounts[r.type] || 0) + 1;
                relAdded++;
              }
            }
          }
        } catch (e) {
          console.warn("fetch relationships failed:", e);
        }
        if (added > 0) {
          cy.layout({ name: "cose", animate: true, padding: 50 }).run();
          if (window.GraphMain) {
            window.GraphMain.setStatus(
              `Loaded ${added} nodes, ${relAdded} relationships`);
          }
          const emptyEl = document.getElementById("graphEmptyState");
          if (emptyEl) emptyEl.hidden = true;
          // 填充右侧 Results overview
          renderOverview();
        }
      } catch (e) {
        console.error("loadAllNodes failed", e);
      } finally {
        loadAllNodesPromise = null;
        loadAllNodesAbort = null;
      }
    })();
    return loadAllNodesPromise;
  }

  // ── Results overview (Neo4j Browser 风格) ─────────────────────────────
  // 从 nodeMap / relMap 实时统计，不依赖 cy.nodes()（防止异步时序问题）
  function renderOverview() {
    const nodeIds = Object.keys(nodeMap);
    const relIds = Object.keys(relMap);
    console.warn("[graph] renderOverview called, nodeMap=%d relMap=%d", nodeIds.length, relIds.length);
    if (nodeIds.length === 0 && relIds.length === 0) return;
    const labelCounts = Object.create(null);
    nodeIds.forEach(id => {
      const n = nodeMap[id];
      if (!n || !n.data) return;
      const lbl = n.data("label") || "Node";
      labelCounts[lbl] = (labelCounts[lbl] || 0) + 1;
    });
    const relTypeCounts = Object.create(null);
    relIds.forEach(id => {
      const r = relMap[id];
      if (!r || !r.data) return;
      const t = r.data("label") || "?";
      relTypeCounts[t] = (relTypeCounts[t] || 0) + 1;
    });
    const totalNodes = nodeIds.length;
    const totalRels = relIds.length;

    const labelPills = document.getElementById("graphLabelPills");
    const relPills = document.getElementById("graphRelPills");
    const allNodesEl = document.getElementById("graphOverviewAllNodes");
    const allRelsEl = document.getElementById("graphOverviewAllRels");
    const nodesCountEl = document.getElementById("graphOverviewNodesCount");
    const relsCountEl = document.getElementById("graphOverviewRelsCount");
    if (nodesCountEl) nodesCountEl.textContent = `(${totalNodes})`;
    if (relsCountEl) relsCountEl.textContent = `(${totalRels})`;
    if (allNodesEl) allNodesEl.textContent = totalNodes;
    if (allRelsEl) allRelsEl.textContent = totalRels;
    if (labelPills) {
      // 保留 * 通配 pill，替换其它
      const wildcard = labelPills.querySelector('[data-label="*"]');
      labelPills.innerHTML = "";
      if (wildcard) labelPills.appendChild(wildcard);
      Object.keys(labelCounts).sort().forEach(label => {
        const color = colorForLabel(label);
        const pill = document.createElement("button");
        pill.type = "button";
        pill.className = "graph-pill";
        pill.dataset.label = label;
        pill.style.background = color;
        pill.style.color = "#fff";
        pill.innerHTML = `<span class="graph-pill-name">${escHtml(label)}</span><span class="graph-pill-count">${labelCounts[label]}</span>`;
        pill.addEventListener("click", () => toggleFilter("label", label));
        labelPills.appendChild(pill);
      });
    }
    if (relPills) {
      const wildcard = relPills.querySelector('[data-rel="*"]');
      relPills.innerHTML = "";
      if (wildcard) relPills.appendChild(wildcard);
      Object.keys(relTypeCounts).sort().forEach(type => {
        const pill = document.createElement("button");
        pill.type = "button";
        pill.className = "graph-pill graph-pill--rel";
        pill.dataset.rel = type;
        pill.innerHTML = `<span class="graph-pill-name">${escHtml(type)}</span><span class="graph-pill-count">${relTypeCounts[type]}</span>`;
        pill.addEventListener("click", () => toggleFilter("rel", type));
        relPills.appendChild(pill);
      });
    }
    // 给 * 通配 pill 加事件
    const wildLabel = labelPills && labelPills.querySelector('[data-label="*"]');
    const wildRel = relPills && relPills.querySelector('[data-rel="*"]');
    if (wildLabel) wildLabel.addEventListener("click", () => clearFilter());
    if (wildRel) wildRel.addEventListener("click", () => clearFilter());
  }

  function toggleFilter(kind, value) {
    const key = kind + ":" + value;
    if (activeFilter === key) { clearFilter(); return; }
    activeFilter = key;
    applyFilter();
    updateFilterUI();
  }

  function clearFilter() {
    activeFilter = null;
    applyFilter();
    updateFilterUI();
  }

  function applyFilter() {
    if (!cy) return;
    if (!activeFilter) {
      cy.elements().style("opacity", 1);
      return;
    }
    const [kind, value] = activeFilter.split(":");
    if (kind === "label") {
      // 高亮匹配的节点，dim 其它
      cy.nodes().forEach(n => {
        const match = n.data("label") === value;
        n.style("opacity", match ? 1 : 0.18);
      });
      cy.edges().forEach(e => {
        const s = e.source().data("label") === value;
        const t = e.target().data("label") === value;
        e.style("opacity", (s || t) ? 0.8 : 0.1);
      });
    } else if (kind === "rel") {
      cy.edges().forEach(e => {
        const match = e.data("label") === value;
        e.style("opacity", match ? 1 : 0.1);
        e.style("width", match ? 3 : 1);
      });
      cy.nodes().forEach(n => n.style("opacity", 0.5));
    }
  }

  function updateFilterUI() {
    document.querySelectorAll("#graphLabelPills .graph-pill, #graphRelPills .graph-pill")
      .forEach(p => p.classList.remove("active"));
    if (activeFilter) {
      const [kind, value] = activeFilter.split(":");
      const sel = kind === "label"
        ? `#graphLabelPills [data-label="${cssEsc(value)}"]`
        : `#graphRelPills [data-rel="${cssEsc(value)}"]`;
      const pill = document.querySelector(sel);
      if (pill) pill.classList.add("active");
    }
    const clearBtn = document.getElementById("graphFabClearFilter");
    if (clearBtn) clearBtn.hidden = !activeFilter;
  }

  function escHtml(s) {
    return String(s).replace(/[&<>"']/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // 智能选节点的展示名：优先常见字段，缺失则截断 element_id
  function pickNodeName(props, id) {
    if (props) {
      const cand = props.name || props.title || props.hostname || props.host
                 || props.service || props.key || props.id;
      if (cand) return String(cand);
    }
    // element_id 形如 "4:fa891369-...:51"，太长了，截断
    const s = String(id || "");
    return s.length > 12 ? s.slice(0, 8) + "…" : s;
  }
  function cssEsc(s) {
    if (window.CSS && window.CSS.escape) return window.CSS.escape(s);
    return String(s).replace(/["\\]/g, "\\$&");
  }

  async function expandNode(elementId, depth = 1) {
    try {
      const res = await fetch("/api/graph/topology/" + encodeURIComponent(elementId) + "?depth=" + depth);
      const json = await res.json();
      if (!json.ok) throw new Error(json.error);
      renderTopology(json.data, depth);
      if (window.GraphMain) window.GraphMain.setStatus(
        `Loaded ${json.data.nodes.length} nodes, ${json.data.relationships.length} relationships`);
    } catch (e) {
      if (window.GraphMain) window.GraphMain.setStatus("Expand failed: " + e.message, "error");
    }
  }

  function renderTopology(topo) {
    if (!cy) return;
    topo.nodes.forEach(n => {
      const id = n.id;
      if (!nodeMap[id]) {
        const label = (n.labels && n.labels[0]) || "Node";
        const name = pickNodeName(n.properties, id);
        const color = colorForLabel(label);
        nodeMap[id] = cy.add({
          group: "nodes",
          data: {
            id,
            label,
            name,
            color,
            borderColor: color,
          },
        });
      }
    });
    topo.relationships.forEach(r => {
      const id = r.id;
      if (!relMap[id] && nodeMap[r.start_node_id] && nodeMap[r.end_node_id]) {
        relMap[id] = cy.add({
          group: "edges",
          data: { id, source: r.start_node_id, target: r.end_node_id, label: r.type },
        });
      }
    });
    cy.layout({ name: "cose", animate: true, padding: 50 }).run();
    // 拓扑展开后，刷新 Results overview
    renderOverview();
  }

  function onSelectNode(id) {
    if (window.GraphMain) {
      window.GraphMain.state.selectedNodeId = id;
    }
    if (window.GraphCRUD) window.GraphCRUD.showNodeActions(id);
  }

  function clearSelection() {
    if (cy) cy.elements().unselect();
    if (window.GraphMain) {
      window.GraphMain.state.selectedNodeId = null;
      window.GraphMain.state.selectedRelId = null;
    }
  }

  document.addEventListener("DOMContentLoaded", init);
  window.GraphViewGraph = { expandNode, onShow, loadAllNodes };
})();
