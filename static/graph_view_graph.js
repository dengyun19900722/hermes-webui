/* ==========================================
   GRAPH — Cytoscape view
   ========================================== */
(function() {
  "use strict";

  let cy = null;
  let canvas = null;
  let nodeMap = {};
  let relMap = {};
  // 详情面板"关系"区：未画进画布的邻居节点（如反向 RUNS_ON 上游 Service）
  // 异步通过 /api/graph/node/{eid} 补齐的真实 label / name，按 elementId 缓存
  const _extraNodeInfo = {};
  // in-flight 单飞：同一 eid 只发一次请求，后续复用同一个 Promise
  const _pendingNodeFetches = new Map();
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
            width: 70, height: 70,
            "font-size": 12,
            "text-valign": "center",
            "text-halign": "center",
            color: "#fff",
            "text-wrap": "ellipsis",
            "text-max-width": "60px",
            "font-weight": 600,
        }},
        { selector: "edge", style: {
            label: "data(labelTr)",
            width: 2, "line-color": "#aaa", "target-arrow-color": "#aaa",
            "target-arrow-shape": "triangle", "curve-style": "bezier", "font-size": 10,
            color: "#e8e8e8", "text-outline-color": "#1a1a1a", "text-outline-width": 1,
        }},
        { selector: "node:selected", style: { "border-width": 4, "border-color": "#FF6B35" }},
        { selector: "node.highlighted", style: { "border-width": 3, "border-color": "#FF6B35" }},
      ],
      layout: { name: "preset" },
      wheelSensitivity: 0.3,
    });

    cy.on("tap", "node", e => {
      const id = e.target.id();
      onSelectNode(id);
      showNodeDetail(id);
      if (_chainRoot) {
        // 已在全链路视图：单击 = 切换中心节点，重新拉取该节点的全链路
        expandNode(id, _filterDepth, _chainDirection);
      } else {
        // 普通视图：单击 = focus（以该节点为中心展开 N 层并隐藏其它）
        focusOnNode(id);
      }
    });
    cy.on("dbltap", "node", e => {
      // 双击节点 → 查看全链路（默认 3 层双向）
      expandNode(e.target.id(), _filterDepth, _chainDirection);
    });
    cy.on("tap", e => {
      if (e.target === cy) {
        if (_chainRoot) {
          // 链视图下点空白：仅清节点选择，不退出链路
          try { cy.elements().unselect(); } catch (err) {}
          _selectedNodeId = null;
          if (window.GraphMain) window.GraphMain.state.selectedNodeId = null;
        } else {
          clearSelection();
          hideNodeDetail();
          clearHighlight();
        }
      }
    });
    // hover 高亮子图（hover out 恢复，除非已 tap 选中）
    cy.on("mouseover", "node", e => {
      if (!_selectedNodeId) highlightSubgraph(e.target.id());
    });
    cy.on("mouseout", "node", () => {
      if (!_selectedNodeId) clearHighlight();
    });

    document.querySelectorAll(".graph-fab").forEach(btn => {
      btn.addEventListener("click", () => {
        const a = btn.dataset.action;
        if (a === "fit") cy.fit(null, 50);
        else if (a === "zoom-in") cy.zoom({ level: cy.zoom() * 1.2, renderedPosition: { x: cy.width()/2, y: cy.height()/2 }});
        else if (a === "zoom-out") cy.zoom({ level: cy.zoom() / 1.2, renderedPosition: { x: cy.width()/2, y: cy.height()/2 }});
        else if (a === "layout") cy.layout({ name: "cose", animate: true, padding: 30, idealEdgeLength: 80, nodeRepulsion: 8000, spacingFactor: 1.0 }).run();
        else if (a === "clear-filter") clearFilter();
      });
    });
    // 初始化过滤层级按钮
    initFilterDepth();
    // 初始化链路方向按钮
    initChainDirection();
    // 同步工具栏的初始 active 状态
    updateFilterUI();
    // 顶部全链路工具栏的关闭按钮（恢复全图）
    const chainClose = document.getElementById("graphChainClose");
    if (chainClose && !chainClose.__closeBound) {
      chainClose.__closeBound = true;
      chainClose.addEventListener("click", exitChainView);
    }
    // 操作提示 banner：检查 localStorage 是否已关闭
    const hint = document.getElementById("graphHintBanner");
    if (hint) {
      if (localStorage.getItem("graph_hint_dismissed") === "1") {
        hint.hidden = true;
      }
      const closeBtn = hint.querySelector(".graph-hint-close");
      if (closeBtn) {
        closeBtn.addEventListener("click", () => {
          hint.hidden = true;
          try { localStorage.setItem("graph_hint_dismissed", "1"); } catch (e) {}
        });
      }
    }
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
    // 尝试从 GraphMain 加载字典
    loadDictMap();
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
            const name = pickNodeName(n.properties, id, label);
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
                  data: { id: r.id, source: r.start_node_id, target: r.end_node_id,
                          label: r.type, labelTr: tr(r.type, "rel_types") || r.type },
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
          cy.layout({ name: "cose", animate: true, padding: 30, idealEdgeLength: 80, nodeRepulsion: 8000, spacingFactor: 1.0 }).run();
          if (window.GraphMain) {
            window.GraphMain.setStatus(
              `Loaded ${added} nodes, ${relAdded} relationships`);
          }
          const emptyEl = document.getElementById("graphEmptyState");
          if (emptyEl) emptyEl.hidden = true;
          // 填充右侧 Results overview
          renderOverview();
          // 应用字典翻译（等待字典就绪后再翻译，避免首次时序问题）
          await applyDictToGraph();
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
    // 每次渲染前强制刷新字典映射，避免 GraphMain 异步加载字典的时序问题
    loadDictMap();
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
        // 节点标签保持彩色底框；关系和属性用单色卡片（CSS 控制）
        pill.style.background = color;
        pill.style.color = "#fff";
        pill.style.borderColor = "transparent";
        const labelTr = tr(label, "node_labels") || label;
        pill.innerHTML = `<span class="graph-pill-name">${escHtml(labelTr)}</span><span class="graph-pill-count">${labelCounts[label]}</span>`;
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
        const typeTr = tr(type, "rel_types") || type;
        pill.innerHTML = `<span class="graph-pill-name">${escHtml(typeTr)}</span><span class="graph-pill-count">${relTypeCounts[type]}</span>`;
        pill.addEventListener("click", () => toggleFilter("rel", type));
        relPills.appendChild(pill);
      });
    }
    // ── 属性（property keys）统计 ──
    const propCounts = Object.create(null);
    nodeIds.forEach(id => {
      const n = nodeMap[id];
      if (!n || !n.data) return;
      // properties 不存储在 cytoscape data 里，需要从 API 获取
      // 这里从 nodeMap 中已经缓存的 data 尝试读取（仅当当初存了 props）
    });
    // 用 API 拉所有节点属性（仅首次渲染时），汇总到 propCounts
    _fetchPropertyKeys(propPillCallback);

    function propPillCallback(propCounts) {
      const propPills = document.getElementById("graphPropPills");
      const propsCountEl = document.getElementById("graphPropsCount");
      const totalProps = Object.keys(propCounts).length;
      if (propsCountEl) propsCountEl.textContent = totalProps;
      if (!propPills) return;
      propPills.innerHTML = "";
      Object.keys(propCounts).sort().forEach(k => {
        const pill = document.createElement("button");
        pill.type = "button";
        pill.className = "graph-pill graph-pill--prop";
        pill.dataset.propkey = k;
        const kTr = tr(k, "property_keys") || k;
        pill.innerHTML = `<span class="graph-pill-name">${escHtml(kTr)}</span><span class="graph-pill-count">${propCounts[k]}</span>`;
        pill.addEventListener("click", () => toggleFilter("prop", k));
        propPills.appendChild(pill);
      });
    }

    // 给 * 通配 pill 加事件
    const wildLabel = labelPills && labelPills.querySelector('[data-label="*"]');
    const wildRel = relPills && relPills.querySelector('[data-rel="*"]');
    if (wildLabel) wildLabel.addEventListener("click", () => clearFilter());
    if (wildRel) wildRel.addEventListener("click", () => clearFilter());
  }

  // 异步统计所有节点的 property keys（仅当 overview 首次渲染时拉一次）
  let _fetchedPropertyKeys = null;
  function _fetchPropertyKeys(cb) {
    if (_fetchedPropertyKeys) { cb(_fetchedPropertyKeys); return; }
    // 取前 200 个节点就够了（统计属性名）
    fetch("/api/graph/nodes?limit=500")
      .then(r => r.json())
      .then(j => {
        if (!j.ok || !j.data) { _fetchedPropertyKeys = {}; cb({}); return; }
        const acc = Object.create(null);
        (j.data.results || []).forEach(n => {
          if (!n.properties) return;
          Object.keys(n.properties).forEach(k => { acc[k] = (acc[k] || 0) + 1; });
        });
        _fetchedPropertyKeys = acc;
        cb(acc);
      })
      .catch(() => { _fetchedPropertyKeys = {}; cb({}); });
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

  // 当前过滤的扩展层级（1=只匹配节点本身，2=匹配节点 + 1 层邻居，...）
  let _filterDepth = 3;

  // 以某节点为中心，隐藏其它（按 _filterDepth 展开 N 层）。
  // 语义：_filterDepth=3 意为"展示根 + 3 跳邻居"，BFS 跑 3 轮。
  function focusOnNode(nodeId) {
    if (!cy) return;
    const root = cy.getElementById(nodeId);
    if (root.empty()) return;
    let frontier = cy.collection().union(root);
    const visited = cy.collection().union(root);
    for (let d = 1; d <= _filterDepth; d++) {
      // 取 frontier 所有未访问的邻居
      const next = frontier.neighborhood().nodes().subtract(visited);
      if (next.empty()) break;
      visited.union(next);
      frontier = next;
    }
    const edges = visited.connectedEdges();
    cy.elements().hide();
    visited.show();
    edges.show();
    // 选中节点加视觉强调
    try { cy.elements().unselect(); root.select(); } catch (e) {}
    try { cy.fit(visited, 20); } catch (e) {}
  }
  function clearNodeFocus() {
    if (!cy) return;
    cy.elements().show();
    try { cy.elements().unselect(); } catch (e) {}
    _selectedNodeId = null;
    if (window.GraphMain) window.GraphMain.state.selectedNodeId = null;
  }
  function applyFilter() {
    if (!cy) return;
    if (!activeFilter) {
      cy.elements().show().style("opacity", 1);
      return;
    }
    const [kind, value] = activeFilter.split(":");
    // 先全部隐藏
    cy.elements().hide();
    if (kind === "label") {
      // 收集匹配的节点（标签为 value），再扩展 N 层邻居
      const matches = cy.nodes().filter(n => n.data("label") === value);
      let visible = matches;
      // 与 focusOnNode / 全链路深度保持一致：_filterDepth=N 表示 N 跳
      for (let d = 1; d <= _filterDepth; d++) {
        const neighbors = visible.neighborhood().nodes();
        const newOnes = neighbors.subtract(visible);
        if (newOnes.empty()) break;
        visible = visible.union(newOnes);
      }
      // 显示节点 + 它们之间的边
      const edges = visible.connectedEdges();
      visible.show();
      edges.show();
    } else if (kind === "rel") {
      // 显示指定类型的关系 + 其两端节点
      const relEdges = cy.edges().filter(e => e.data("label") === value);
      const nodes = relEdges.connectedNodes();
      relEdges.show();
      nodes.show();
    } else if (kind === "prop") {
      // 属性过滤 fallback：仅作 UI 占位（无 properties 缓存）
      cy.elements().show().style("opacity", 0.4);
      return;
    }
    // 过滤后自适应放大（类似 Neo4j Browser）
    try { cy.fit(null, 20); } catch (e) { /* ignore */ }
  }

  function updateFilterUI() {
    document.querySelectorAll("#graphLabelPills .graph-pill, #graphRelPills .graph-pill, #graphPropPills .graph-pill")
      .forEach(p => p.classList.remove("active"));
    if (activeFilter) {
      const [kind, value] = activeFilter.split(":");
      const sel = kind === "label" ? `#graphLabelPills [data-label="${cssEsc(value)}"]`
                 : kind === "rel"  ? `#graphRelPills [data-rel="${cssEsc(value)}"]`
                 :                   `#graphPropPills [data-propkey="${cssEsc(value)}"]`;
      const pill = document.querySelector(sel);
      if (pill) pill.classList.add("active");
    }
    const clearBtn = document.getElementById("graphFabClearFilter");
    if (clearBtn) clearBtn.hidden = !activeFilter;
    // 层级选择控件（顶部全链路工具栏 + inline 工具栏）
    document.querySelectorAll("#graphChainToolbar, .graph-toolbar-inline").forEach(row => {
      row.querySelectorAll(".graph-depth-btn, .graph-chain-btn[data-depth], .graph-toolbar-btn[data-depth]").forEach(b => {
        b.classList.toggle("active", String(_filterDepth) === b.dataset.depth);
      });
    });
    // 方向切换控件（顶部全链路工具栏 + inline 工具栏）
    document.querySelectorAll("#graphChainToolbar, .graph-toolbar-inline").forEach(ctrl => {
      const dirBtns = ctrl.querySelectorAll(".graph-chain-btn[data-dir], .graph-toolbar-btn[data-dir]");
      if (dirBtns.length > 0) {
        dirBtns.forEach(b => {
          b.classList.toggle("active", b.dataset.dir === _chainDirection);
        });
      }
    });
  }

  // 初始化层级按钮事件（覆盖顶部工具栏 + inline 工具栏）
  function initFilterDepth() {
    const rows = [
      document.getElementById("graphChainToolbar"),
      document.querySelector(".graph-toolbar-inline"),
    ].filter(Boolean);
    rows.forEach(row => {
      row.querySelectorAll(".graph-depth-btn, .graph-chain-btn[data-depth], .graph-toolbar-btn[data-depth]").forEach(btn => {
        if (btn.__chainBound) return;
        btn.__chainBound = true;
        btn.addEventListener("click", () => {
          const raw = btn.dataset.depth;
          const d = raw === "0" ? 0 : (parseInt(raw, 10) || 1);
          if (_filterDepth === d) return;
          setChainDepth(d);
        });
      });
    });
  }

  // 初始化链路方向按钮事件（覆盖顶部工具栏 + inline 工具栏）
  function initChainDirection() {
    const ctrls = [
      document.getElementById("graphChainToolbar"),
      document.querySelector(".graph-toolbar-inline"),
    ].filter(Boolean);
    ctrls.forEach(ctrl => {
      ctrl.querySelectorAll(".graph-chain-btn[data-dir], .graph-toolbar-btn[data-dir]").forEach(btn => {
        if (btn.__chainDirBound) return;
        btn.__chainDirBound = true;
        btn.addEventListener("click", () => {
          const dir = btn.dataset.dir;
          if (!dir || _chainDirection === dir) return;
          setChainDirection(dir);
        });
      });
    });
  }

  // 切换深度（统一入口）
  function setChainDepth(d) {
    _filterDepth = d;
    if (activeFilter) applyFilter();
    // 有链路中心 → 重查；无链路但已选节点 → 重新 focus
    if (_chainRoot) {
      expandNode(_chainRoot, _filterDepth, _chainDirection);
    } else if (_selectedNodeId) {
      focusOnNode(_selectedNodeId);
    }
    updateFilterUI();
  }
  // 切换方向（统一入口）
  function setChainDirection(dir) {
    _chainDirection = dir;
    // 有链路中心 → 重查；无链路但已选节点 → 以选中节点为链路中心重查
    const root = _chainRoot || _selectedNodeId;
    if (root) {
      _chainRoot = root;
      expandNode(root, _filterDepth, _chainDirection);
    }
    updateFilterUI();
  }

  function escHtml(s) {
    return String(s).replace(/[&<>"']/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }
  function escAttr(s) { return escHtml(s); }

  // 节点展示名：固定优先 name 字段；缺失则用 [标签] + id 截断
  // 目的：name 是中文/有意义字段；其他字段（hostname/host_ip 等）是技术信息，
  // 截断的 id 比技术字段更短更易识别。
  function pickNodeName(props, id, label) {
    if (props && props.name) return String(props.name);
    if (label) return "[" + String(label) + "] " + shortId(id);
    return shortId(id);
  }
  function shortId(id) {
    const s = String(id || "");
    return s.length > 12 ? s.slice(0, 8) + "…" : s;
  }
  function cssEsc(s) {
    if (window.CSS && window.CSS.escape) return window.CSS.escape(s);
    return String(s).replace(/["\\]/g, "\\$&");
  }

  // 全链路方向（上游依赖 / 下游被依赖 / 双向）
  let _chainDirection = "both";
  // 当前链路中心节点（方向切换时重查）
  let _chainRoot = null;

  // 清空当前图谱元素（节点 + 边）
  function clearGraph() {
    if (!cy) return;
    try {
      cy.elements().remove();
    } catch (e) {}
    Object.keys(nodeMap).forEach(k => delete nodeMap[k]);
    Object.keys(relMap).forEach(k => delete relMap[k]);
    // 画布外的邻居缓存也一并清掉，避免跨图谱残留旧 label/name
    Object.keys(_extraNodeInfo).forEach(k => delete _extraNodeInfo[k]);
  }

  // 查看全链路：替换图谱为 topology（深度 + 方向）结果
  async function expandNode(elementId, depth = _filterDepth, direction = _chainDirection) {
    try {
      const res = await fetch(
        "/api/graph/topology/" + encodeURIComponent(elementId) +
        "?depth=" + depth + "&direction=" + direction
      );
      const json = await res.json();
      if (!json.ok) throw new Error(json.error);
      const topo = json.data;
      // 替换图谱（非增量），避免旧节点残留
      clearGraph();
      renderTopology(topo);
      // 强制 fit：让剩余节点自适应放大居中
      try { cy.fit(undefined, 30); } catch (e) {}
      // 默认选中最中心节点并展示详情
      try { cy.getElementById(elementId).select(); } catch (e) {}
      onSelectNode(elementId);
      // 记录当前链路中心，供方向切换时重查
      _chainRoot = elementId;
      // 链路工具栏：让用户能立即看到层级/方向控件
      showChainToolbar();
      updateFilterUI();
      if (window.GraphMain) window.GraphMain.setStatus(
        `全链路 · ${topo.nodes.length} 节点 / ${topo.relationships.length} 关系 · 深度 ${_depthLabel(depth)} · 方向 ${_dirLabel(direction)}`, "ok");
    } catch (e) {
      if (window.GraphMain) window.GraphMain.setStatus("查看全链路失败: " + e.message, "error");
    }
  }

  // 深度数字 → 中文标签
  function _depthLabel(d) {
    if (d === 0) return "全部";
    return String(d);
  }

  // 方向的中文标签
  function _dirLabel(direction) {
    return direction === "in" ? "上游(依赖)" : direction === "out" ? "下游(被依赖)" : "双向";
  }

  function renderTopology(topo) {
    if (!cy) return;
    topo.nodes.forEach(n => {
      const id = n.id;
      if (!nodeMap[id]) {
        const label = (n.labels && n.labels[0]) || "Node";
        const name = pickNodeName(n.properties, id, label);
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
          data: { id, source: r.start_node_id, target: r.end_node_id,
                  label: r.type, labelTr: tr(r.type, "rel_types") || r.type },
        });
      }
    });
    // 先 resize 让 cytoscape 拿到最新的画布尺寸（工具栏出现可能压缩 canvas）
    try { cy.resize(); } catch (e) { /* ignore */ }
    // 链视图：用 breadthfirst 让根节点在中心、邻居按 hop 分层呈同心环
    const useBreadthfirst = !!_chainRoot && cy.getElementById(_chainRoot).length > 0;
    const layoutOpts = useBreadthfirst
      ? {
          // directed:false 让 in/out 邻居处于同一 BFS 层，呈真正同心环
          name: "breadthfirst",
          directed: false,
          fit: true,
          padding: 30,
          // 1.0 = cytoscape 默认：同层节点间距约等于节点宽度，
          // 过去 1.8 会把同层邻居拉得很远、圆环外圈更远，连线显得过长。
          spacingFactor: 1.0,
          avoidOverlap: true,
          // circle:false 让 BFS 自行横向排版（带 depth 轴），
          // 避免 circle 强制满圆环导致节点外圈被等距散开、画布被拉成细长条。
          circle: false,
          roots: _chainRoot ? [_chainRoot] : undefined,
          animate: true,
          animationDuration: 360,
        }
      : { name: "cose", animate: true, padding: 30, idealEdgeLength: 80, nodeRepulsion: 8000, spacingFactor: 1.0 };
    const layout = cy.layout(layoutOpts);
    layout.one("layoutstop", () => {
      // layout 完成后再次 fit，给画布边距留缓冲
      try { cy.fit(undefined, 30); } catch (e) { /* ignore */ }
    });
    layout.run();
    // 拓扑展开后，刷新 Results overview 与工具栏摘要
    renderOverview();
    if (typeof updateChainToolbarSummary === "function") updateChainToolbarSummary();
  }

  // 顶部全链路工具栏：显示/隐藏/摘要更新
  function showChainToolbar() {
    const toolbar = document.getElementById("graphChainToolbar");
    if (!toolbar) return;
    toolbar.hidden = false;
    updateChainToolbarSummary();
  }
  function hideChainToolbar() {
    const toolbar = document.getElementById("graphChainToolbar");
    if (toolbar) toolbar.hidden = true;
  }
  function updateChainToolbarSummary() {
    const toolbar = document.getElementById("graphChainToolbar");
    if (!toolbar) return;
    // 根节点名
    const nameEl = document.getElementById("graphChainRootName");
    if (nameEl) {
      let label = "--";
      if (_chainRoot) {
        const n = nodeMap[_chainRoot];
        if (n && n.data) label = n.data("name") || _chainRoot;
        else label = String(_chainRoot);
      }
      nameEl.textContent = label;
    }
    // 摘要：节点/关系 · 深度 · 方向
    const summary = document.getElementById("graphChainSummary");
    if (summary && cy) {
      const n = cy.nodes().length;
      const e = cy.edges().length;
      summary.textContent = `${n} 节点 / ${e} 关系 · 深度 ${_depthLabel(_filterDepth)} · 方向 ${_dirLabel(_chainDirection)}`;
    }
  }
  // 退出全链路视图：清空 _chainRoot、隐藏工具栏、恢复全图
  async function exitChainView() {
    _chainRoot = null;
    hideChainToolbar();
    _selectedNodeId = null;
    if (window.GraphMain) window.GraphMain.state.selectedNodeId = null;
    try { hideNodeDetail(); } catch (e) {}
    if (cy) {
      // 已有全图节点 → 直接显示全部
      if (Object.keys(nodeMap).length > 0) {
        cy.elements().show();
        try { cy.fit(null, 50); } catch (e) {}
        if (activeFilter) applyFilter();
      } else {
        // 第一次进来就开了链路 → 拉全图
        await loadAllNodes();
      }
    }
    updateFilterUI();
    if (window.GraphMain) window.GraphMain.setStatus("已退出全链路视图");
  }

  let _selectedNodeId = null;

  function onSelectNode(id) {
    _selectedNodeId = id;
    if (window.GraphMain) {
      window.GraphMain.state.selectedNodeId = id;
    }
  }

  function clearSelection() {
    _selectedNodeId = null;
    if (cy) cy.elements().unselect();
    if (window.GraphMain) {
      window.GraphMain.state.selectedNodeId = null;
      window.GraphMain.state.selectedRelId = null;
    }
  }

  // ── 字典翻译集成 ──────────────────────────────────────
  let _dictMap = { node_labels: {}, rel_types: {}, property_keys: {}, property_values: {} };

  async function loadDictMap() {
    // 优先从 GraphMain.state 读（由 onPanelShow -> loadDictionary 填充）
    if (window.GraphMain && window.GraphMain.state && window.GraphMain.state.dictMap) {
      const d = window.GraphMain.state.dictMap;
      if (Object.keys(d.node_labels || {}).length || Object.keys(d.rel_types || {}).length) {
        _dictMap = d;
        return _dictMap;
      }
    }
    // 兜底：GraphMain 尚未异步加载字典时，直接拉取字典 apply 接口
    try {
      const res = await fetch("/api/graph/dictionary/apply");
      const json = await res.json();
      if (json.ok && json.data) {
        _dictMap = json.data;
        if (window.GraphMain && window.GraphMain.state) {
          window.GraphMain.state.dictMap = json.data;
        }
      }
    } catch (e) {
      console.warn("loadDictMap fetch failed:", e);
    }
    return _dictMap;
  }

  function tr(text, mapType) {
    if (!text) return text;
    const map = _dictMap[mapType];
    if (!map) return text;
    return map[text] || text;
  }

  async function applyDictToGraph() {
    await loadDictMap();
    if (!cy) return;
    // 更新节点标签
    cy.nodes().forEach(n => {
      const origName = n.data("origName") || n.data("name");
      n.data("origName", origName);
      const label = n.data("label");
      const translated = tr(origName, "property_values") || origName;
      n.data("name", translated);
      n.style("label", "data(name)");
    });
    // 更新边标签
    cy.edges().forEach(e => {
      const origLabel = e.data("origLabel") || e.data("label");
      e.data("origLabel", origLabel);
      const translated = tr(origLabel, "rel_types") || origLabel;
      e.data("label", translated);
      e.style("label", "data(label)");
    });
    // 刷新 overview
    renderOverview();
    // 如果当前有节点详情打开，刷新
    const detailEl = document.getElementById("graphNodeDetail");
    if (detailEl && !detailEl.hidden) {
      const idEl = document.getElementById("graphNodeDetailId");
      if (idEl && idEl.textContent) {
        showNodeDetail(idEl.textContent);
      }
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    const panel = document.getElementById("panelGraph");
    if (panel) {
      panel.addEventListener("dict:changed", () => {
        loadDictMap();
        applyDictToGraph();
      });
    }
  });

  // ── 1. 子图高亮（同一链路上的节点/边不透明，其它 dim）─────────────────────
  // 注：当前过滤方案已改为"隐藏非匹配"（见 applyFilter），
  // 此处仅保留兼容路径 — 点击节点 dim 其他链路。
  function highlightSubgraph(nodeId) {
    if (!cy) return;
    // 重置所有透明度
    cy.elements().style("opacity", 1);
    const connected = cy.getElementById(nodeId).closedNeighborhood();
    cy.nodes().not(connected).style("opacity", 0.12);
    cy.edges().not(connected.edgesWith(cy.nodes())).style("opacity", 0.06);
  }
  function clearHighlight() {
    if (!cy) return;
    cy.elements().style("opacity", 1);
    // 如果之前有 activeFilter，重新应用过滤
    if (activeFilter) applyFilter();
  }

  // ── 2. 节点详情面板 ─────────────────────────────────────────────────────
  function showNodeDetail(nodeId) {
    const detailEl = document.getElementById("graphNodeDetail");
    const overviewEl = document.getElementById("graphOverviewContent");
    if (!detailEl) return;
    // 记录选中节点（供方向/层级切换作为链路中心兜底）
    _selectedNodeId = nodeId;
    // 选中节点后：以该节点为中心展开 N 层（其它隐藏）
    focusOnNode(nodeId);
    const idEl = document.getElementById("graphNodeDetailId");
    const labelsEl = document.getElementById("graphNodeDetailLabels");
    const propsEl = document.getElementById("graphNodeDetailProps");
    const relsEl = document.getElementById("graphNodeDetailRels");
    if (!idEl || !labelsEl || !propsEl || !relsEl) return;
    // 从 nodeMap 或 API 获取节点数据
    let nodeData = null;
    const cyNode = cy && cy.getElementById(nodeId);
    if (cyNode && cyNode.length) {
      // 先找 labels
      const label = cyNode.data("label") || "Node";
      nodeData = { id: nodeId, label: label, name: cyNode.data("name") || nodeId };
    }
    idEl.textContent = nodeId;
    // 从 API 获取完整数据（含 properties 和 relationships）
    fetch("/api/graph/node/" + nodeId)
      .then(r => r.json())
      .then(j => {
        if (j.ok) {
          renderNodeDetail(j.data, labelsEl, propsEl, relsEl);
        } else {
          if (relsEl) relsEl.innerHTML = '<div style="color:var(--muted);font-size:12px">Failed to load: ' + escHtml(j.error || "unknown error") + '</div>';
        }
      })
      .catch(e => {
        console.error("fetch node detail failed:", e);
        if (relsEl) relsEl.innerHTML = '<div style="color:var(--muted);font-size:12px">Failed to load node details</div>';
      });
    if (labelsEl) labelsEl.innerHTML = "";
    if (propsEl) propsEl.innerHTML = '<div style="color:var(--muted);font-size:12px">Loading…</div>';
    if (relsEl) relsEl.innerHTML = "";
    overviewEl.hidden = true;
    detailEl.hidden = false;
  }
  function hideNodeDetail() {
    const detailEl = document.getElementById("graphNodeDetail");
    const overviewEl = document.getElementById("graphOverviewContent");
    if (!detailEl) return;
    detailEl.hidden = true;
    if (overviewEl) overviewEl.hidden = false;
  }
  function renderNodeDetail(data, labelsEl, propsEl, relsEl) {
    if (!data) return;
    loadDictMap();
    // labels：用带颜色（label color）+ 字典翻译的 pill，一眼看出节点类型
    if (labelsEl && data.labels) {
      labelsEl.innerHTML = data.labels.map(l => {
        const color = colorForLabel(l);
        const labelTr = tr(l, "node_labels") || l;
        // !important 防止 .graph-node-detail-labels .graph-pill--colored 的 background:var(--accent) 覆盖
        return `<button class="graph-pill graph-pill--colored graph-pill--node-label" type="button" data-filter-label="${escAttr(l)}" style="background:${escAttr(color)} !important; border-color:${escAttr(color)} !important; color:#fff !important;" title="${escAttr(l)}">${escHtml(labelTr)}</button>`;
      }).join("");
      // 点击标签 pill = 过滤该类型（Neo4j Browser 风格）
      labelsEl.querySelectorAll("[data-filter-label]").forEach(el => {
        el.addEventListener("click", () => {
          const lbl = el.getAttribute("data-filter-label");
          toggleFilter("label", lbl);
          try { cy.fit(null, 30); } catch (e) {}
        });
      });
    }
    // properties
    if (propsEl && data.properties) {
      const keys = Object.keys(data.properties);
      if (keys.length === 0) {
        propsEl.innerHTML = '<div style="color:var(--muted);font-size:12px">(no properties)</div>';
      } else {
        propsEl.innerHTML = keys.map(k =>
          `<div class="graph-node-prop-row"><span class="graph-node-prop-key">${escHtml(tr(k, "property_keys") || k)}</span><span class="graph-node-prop-value">${escHtml(tr(formatValue(data.properties[k]), "property_values") || formatValue(data.properties[k]))}</span></div>`
        ).join("");
      }
    }
    // relationships — 先拉拓扑
    fetch("/api/graph/relationships/" + data.id + "?direction=both")
      .then(r => r.json())
      .then(j => {
        if (!relsEl) return;
        const rels = (j.ok && j.data && j.data.results) ? j.data.results : [];
        if (rels.length === 0) {
          relsEl.innerHTML = '<div style="color:var(--muted);font-size:12px">(no relationships)</div>';
          return;
        }
        // 按 type + direction + otherId 合并去重（避免重复关系显示两次）
        const grouped = new Map();
        for (const r of rels) {
          const isOut = r.start_node_id === data.id;
          const otherId = isOut ? r.end_node_id : r.start_node_id;
          const key = `${isOut ? 'out' : 'in'}|${r.type}|${otherId}`;
          if (!grouped.has(key)) {
            grouped.set(key, { r, isOut, otherId, count: 1 });
          } else {
            grouped.get(key).count += 1;
          }
        }
        const renderRelRow = g => {
          // 其他节点：取它的 label（英文原文）算色，name 单独展示
          const otherLabelRaw = _labelForId(g.otherId);
          const otherColor = otherLabelRaw ? colorForLabel(otherLabelRaw) : "var(--accent, #4a9eff)";
          const otherLabelTr = otherLabelRaw ? (tr(otherLabelRaw, "node_labels") || otherLabelRaw) : "Node";
          const otherName = _nameForId(g.otherId);
          const relTypeTr = tr(g.r.type, "rel_types") || g.r.type;
          const countBadge = g.count > 1 ? ` <span class="graph-node-rel-count">×${g.count}</span>` : "";
          // 节点类型 pill：与详情顶部 label 同款（带颜色圆角），点击按类型过滤
          const otherLabelPill = `<button type="button" class="graph-pill graph-pill--colored graph-pill--node-label graph-pill--node-mini" data-filter-label="${escAttr(otherLabelRaw)}" style="background:${escAttr(otherColor)} !important; border-color:${escAttr(otherColor)} !important; color:#fff !important;" title="${escAttr(otherLabelRaw)}">${escHtml(otherLabelTr)}</button>`;
          // 关系类型 pill：方角 + 紫底，与 label pill 区分（一眼分清"节点类型"vs"关系类型"）
          const relTypePill = `<span class="graph-pill graph-pill--rel-type" title="${escAttr(g.r.type)}">${escHtml(relTypeTr)}${countBadge}</span>`;
          return `<div class="graph-node-rel-row" data-rel-id="${escAttr(g.r.id)}" data-node-id="${escAttr(g.otherId)}" data-direction="${g.isOut ? 'out' : 'in'}">
            ${g.isOut
              ? `${relTypePill}<span class="graph-node-rel-arrow">→</span>${otherLabelPill}<span class="graph-node-rel-name">${escHtml(otherName)}</span>`
              : `${otherLabelPill}<span class="graph-node-rel-name">${escHtml(otherName)}</span><span class="graph-node-rel-arrow">←</span>${relTypePill}`}
          </div>`;
        };
        const groupedArr = Array.from(grouped.values());
        relsEl.innerHTML = groupedArr.map(renderRelRow).join("");
        // rel-row 里的 label pill 也支持点击过滤（与顶部 label pill 一致）
        relsEl.querySelectorAll("[data-filter-label]").forEach(el => {
          el.addEventListener("click", e => {
            e.stopPropagation();
            const lbl = el.getAttribute("data-filter-label");
            if (lbl) { toggleFilter("label", lbl); try { cy.fit(null, 30); } catch (err) {} }
          });
        });
        relsEl.querySelectorAll(".graph-node-rel-row").forEach(el => {
          el.addEventListener("click", () => {
            const nid = el.dataset.nodeId;
            if (nid) { showNodeDetail(nid); highlightSubgraph(nid); }
          });
        });
        // 邻居节点若未画进画布（如反向 RUNS_ON 的上游 Service），异步补齐真实
        // label/name，补齐后仅重渲染受影响的关系行，避免整块闪烁。
        groupedArr.forEach(g => {
          ensureExtraNodeInfo(g.otherId, eid => {
            const row = relsEl.querySelector(`[data-node-id="${cssEsc(eid)}"]`);
            if (!row) return;
            // 直接用已缓存的 _labelForId/_nameForId 重渲染该行（此时 extra info 已就绪）
            const src = groupedArr.find(x => x.otherId === eid);
            if (src) row.outerHTML = renderRelRow(src);
          });
        });
      })
      .catch(e => {
        console.error("fetch relationships failed:", e);
        if (relsEl) relsEl.innerHTML = '<div style="color:var(--muted);font-size:12px">Failed to load relationships</div>';
      });
  }
  // 异步补齐"未画进画布"的邻居节点信息（真实 label/name），补齐后刷新关系行。
  // 单飞：同一 eid 的请求只发一次，后续复用同一个 Promise。
  function ensureExtraNodeInfo(eid, onReady) {
    if (nodeMap[eid]) return; // 已在画布中，无需补齐
    if (_extraNodeInfo[eid]) { if (onReady) onReady(eid); return; }
    if (!_pendingNodeFetches.has(eid)) {
      const p = fetch("/api/graph/node/" + encodeURIComponent(eid))
        .then(r => r.json())
        .then(j => {
          if (j && j.ok && j.data) {
            const d = j.data;
            const label = (d.labels && d.labels[0]) || "Node";
            _extraNodeInfo[eid] = {
              label: label,
              name: pickNodeName(d.properties, eid, label),
            };
          } else {
            _extraNodeInfo[eid] = { label: null, name: null };
          }
        })
        .catch(() => {
          _extraNodeInfo[eid] = { label: null, name: null };
        })
        .finally(() => _pendingNodeFetches.delete(eid));
      _pendingNodeFetches.set(eid, p);
    }
    if (onReady) {
      _pendingNodeFetches.get(eid).then(() => onReady(eid));
    }
  }
  function _nameForId(id) {
    const n = nodeMap[id];
    if (n && n.data) return n.data("name") || id;
    const extra = _extraNodeInfo[id];
    if (extra && extra.name) return extra.name;
    if (extra) return id.length > 16 ? id.slice(0, 12) + "…" : id;
    return id.length > 16 ? id.slice(0, 12) + "…" : id;
  }
  function _labelForId(id) {
    const n = nodeMap[id];
    if (n && n.data) return n.data("label") || null;
    const extra = _extraNodeInfo[id];
    return extra ? (extra.label || null) : null;
  }
  function formatValue(v) {
    if (v === null || v === undefined) return "(null)";
    if (typeof v === "object") return JSON.stringify(v);
    if (typeof v === "boolean") return v ? "true" : "false";
    return String(v);
  }

  // ── 3. 属性和数据统计（在 renderOverview 里补充）───────────────────────
  // renderOverview 已经存在，下面追加 property 统计逻辑
  // 在原有 renderOverview 末尾补充 property pills。见下面的补丁。

  // ── 4. 面板折叠 ────────────────────────────────────────────────────────
  document.addEventListener("DOMContentLoaded", () => {
    const toggle = document.getElementById("graphOverviewToggle");
    if (!toggle) return;
    toggle.addEventListener("click", () => {
      const panel = document.getElementById("graphResultsOverview");
      if (!panel) return;
      const collapsed = panel.classList.toggle("collapsed");
      toggle.textContent = collapsed ? "▶" : "◀";
    });
    // 节点详情 Back 按钮
    const backBtn = document.getElementById("graphNodeDetailBack");
    if (backBtn) backBtn.addEventListener("click", hideNodeDetail);
    // 搜索改进 — 选中后在输入框显示
    const searchInput = document.getElementById("graphSearchInput");
    if (searchInput) {
      searchInput.addEventListener("keydown", e => {
        if (e.key === "Enter" && searchInput.value.trim()) {
          // 让搜索 dropdown 的点击处理已在 graph_main.js 中
        }
      });
    }
  });

  document.addEventListener("DOMContentLoaded", init);
  window.GraphViewGraph = { expandNode, onShow, loadAllNodes, showNodeDetail, hideNodeDetail, highlightSubgraph, clearHighlight, filterToLabel: toggleFilter, filterToRel: null, applyDictToGraph };
})();
