/* ==========================================
   GRAPH PANEL MODULE
   Neo4j graph visualization with Cytoscape.js
   ========================================== */

(function() {
  'use strict';

  // ── State ─────────────────────────────────────────────────────────────────
  let currentLayout = 'cose';
  let isLoading = false;
  let cy = null;
  let nodeMap = {};
  let relMap = {};
  let expandedSet = new Set();
  let tooltipEl = null;
  let contextMenuEl = null;
  let searchDropdownEl = null;
  let currentDepth = 1;
  let debounceTimer = null;
  let previewTimer = null;

  // ── DOM Refs ──────────────────────────────────────────────────────────────
  const getEl = id => document.getElementById(id);
  let panel, canvas, layoutSelect, searchInput, refreshBtn, closeBtn;
  let listSidebar, statusBar, statusNodes, statusEdges;

  // ── Init ──────────────────────────────────────────────────────────────────
  function init() {
    panel = getEl('graph-panel') || getEl('panelGraph');
    canvas = getEl('graph-canvas') || getEl('graphCanvas');
    layoutSelect = getEl('graphLayoutSelect') || getEl('graph-layout-select');
    searchInput = getEl('graphSearchInput') || getEl('graph-search-input');
    refreshBtn = getEl('graphRefreshBtn');
    closeBtn = getEl('graphCloseBtn');
    listSidebar = getEl('graphList') || getEl('graph-sidebar');
    statusBar = getEl('graphStatus');
    statusNodes = getEl('graphStatusNodes');
    statusEdges = getEl('graphStatusEdges');

    if (!panel || !canvas) return;

    if (layoutSelect) layoutSelect.addEventListener('change', onLayoutChange);
    if (searchInput) {
      searchInput.addEventListener('input', onSearchInput);
      searchInput.addEventListener('keydown', onSearchKeydown);
      searchInput.addEventListener('focus', () => { if (searchDropdownEl && searchDropdownEl.children.length > 0) searchDropdownEl.style.display = ''; });
    }
    if (refreshBtn) refreshBtn.addEventListener('click', loadSchema);
    if (closeBtn) closeBtn.addEventListener('click', () => switchPanel('graph'));

    panel.addEventListener('panel:show', onPanelShow);

    // Keyboard shortcuts on panel
    panel.addEventListener('keydown', onPanelKeydown);

    // Build search dropdown
    buildSearchDropdown();

    initCytoscape();
  }

  // ── Search Dropdown ───────────────────────────────────────────────────────
  function buildSearchDropdown() {
    searchDropdownEl = document.createElement('div');
    searchDropdownEl.id = 'graph-search-dropdown';
    searchDropdownEl.style.cssText = 'position:absolute;z-index:100;display:none;min-width:280px;max-width:400px;background:var(--surface);border:1px solid var(--border);border-radius:6px;box-shadow:0 4px 16px rgba(0,0,0,0.2);max-height:240px;overflow-y:auto;';
    if (searchInput && searchInput.parentNode) {
      searchInput.parentNode.style.position = 'relative';
      searchInput.parentNode.appendChild(searchDropdownEl);
    }
    document.addEventListener('click', e => {
      if (searchDropdownEl && !searchDropdownEl.contains(e.target) && e.target !== searchInput) {
        searchDropdownEl.style.display = 'none';
      }
    });
  }

  function showSearchDropdown(nodes) {
    if (!searchDropdownEl || nodes.length === 0) return;
    searchDropdownEl.innerHTML = nodes.slice(0, 5).map(n => {
      const id = n.id || n.element_id;
      const label = (n.labels && n.labels[0]) || 'Unknown';
      const name = (n.properties && (n.properties.name || n.properties.title)) || '';
      const highlighted = searchInput ? highlightMatch(String(name), searchInput.value) : escHtml(String(name));
      return '<div class="graph-search-result" data-id="' + escHtml(id) + '" style="padding:8px 12px;cursor:pointer;border-bottom:1px solid var(--border-subtle);">' +
        '<span class="graph-node-label">' + escHtml(label) + '</span> ' +
        '<span style="color:var(--muted);font-size:11px;">' + highlighted + '</span>' +
      '</div>';
    }).join('');
    searchDropdownEl.querySelectorAll('.graph-search-result').forEach(el => {
      el.addEventListener('click', () => {
        const id = el.dataset.id;
        searchDropdownEl.style.display = 'none';
        if (searchInput) searchInput.value = '';
        expandNode(id);
      });
    });
    searchDropdownEl.style.display = '';
  }

  function hideSearchDropdown() {
    if (searchDropdownEl) searchDropdownEl.style.display = 'none';
  }

  function highlightMatch(text, query) {
    if (!query) return escHtml(text);
    const idx = text.toLowerCase().indexOf(query.toLowerCase());
    if (idx < 0) return escHtml(text);
    return escHtml(text.slice(0, idx)) + '<strong>' + escHtml(text.slice(idx, idx + query.length)) + '</strong>' + escHtml(text.slice(idx + query.length));
  }

  // ── Cytoscape Init ─────────────────────────────────────────────────────────
  function initCytoscape() {
    if (typeof cytoscape === 'undefined') {
      console.error('Cytoscape.js not loaded');
      return;
    }

    cy = cytoscape({
      container: canvas,
      style: [
        {
          selector: 'node',
          style: {
            'label': 'data(label)',
            'background-color': 'data(color)',
            'width': 40,
            'height': 40,
            'font-size': 12,
            'text-valign': 'bottom',
            'color': '#555',
            'border-width': 2,
            'border-color': 'data(borderColor)'
          }
        },
        {
          selector: 'edge',
          style: {
            'label': 'data(label)',
            'width': 2,
            'line-color': '#aaa',
            'target-arrow-color': '#aaa',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            'font-size': 10
          }
        },
        {
          selector: 'node:selected',
          style: { 'border-width': 4, 'border-color': '#FF6B35' }
        },
        {
          selector: 'node.highlighted',
          style: { 'border-width': 3, 'border-color': '#FF6B35' }
        },
        {
          selector: 'node.hovered',
          style: { 'border-width': 4, 'border-color': '#FF6B35', 'z-index': 10 }
        },
        {
          selector: 'node.dimmed',
          style: { 'opacity': 0.25 }
        },
        {
          selector: 'edge.highlighted',
          style: { 'width': 3, 'line-color': '#FF6B35', 'target-arrow-color': '#FF6B35' }
        }
      ],
      layout: { name: 'preset' },
      wheelSensitivity: 0.3,
      minZoom: 0.1,
      maxZoom: 3.0
    });

    // Enable box selection
    cy.boxSelectionEnabled(true);

    // Single tap on node
    cy.on('tap', 'node', function(evt) {
      showNodeDetails(evt.target);
    });

    // Single tap on edge
    cy.on('tap', 'edge', function(evt) {
      showRelDetails(evt.target);
    });

    // Background tap — deselect
    cy.on('tap', function(evt) {
      if (evt.target === cy) {
        closeDetails();
        hideContextMenu();
      }
    });

    // Double-click node → expand
    cy.on('dbltap', 'node', function(evt) {
      const id = evt.target.id();
      expandNode(id);
    });

    // Right-click node → context menu
    cy.on('cxttap', 'node', function(evt) {
      showContextMenu(evt.target, 'node', evt.renderedPosition());
    });

    // Right-click edge → context menu
    cy.on('cxttap', 'edge', function(evt) {
      showContextMenu(evt.target, 'edge', evt.renderedPosition());
    });

    // Hover — show tooltip and highlight neighbors
    cy.on('mouseover', 'node', function(evt) {
      const node = evt.target;
      node.addClass('hovered');
      // Dim non-neighbors
      const neighbors = node.neighborhood('node').add(node.neighborhood('edge'));
      cy.elements().not(neighbors).addClass('dimmed');
      // Show tooltip
      const pos = node.renderedPosition();
      showTooltip(node, pos);
    });

    cy.on('mouseout', 'node', function(evt) {
      evt.target.removeClass('hovered');
      cy.elements().removeClass('dimmed');
      hideTooltip();
    });

    // Hover on edge
    cy.on('mouseover', 'edge', function(evt) {
      evt.target.addClass('highlighted');
    });
    cy.on('mouseout', 'edge', function(evt) {
      evt.target.removeClass('highlighted');
    });
  }

  // ── Tooltip ────────────────────────────────────────────────────────────────
  function showTooltip(cyNode, pos) {
    hideTooltip();
    const id = cyNode.id();
    const label = cyNode.data('label') || id;
    const cyInstance = cy;
    const zoom = cyInstance.zoom();
    tooltipEl = document.createElement('div');
    tooltipEl.style.cssText = 'position:fixed;z-index:200;padding:6px 10px;background:var(--surface);border:1px solid var(--border);border-radius:4px;font-size:12px;box-shadow:0 2px 8px rgba(0,0,0,0.15);pointer-events:none;white-space:nowrap;';
    tooltipEl.innerHTML = '<strong>' + escHtml(label) + '</strong>';
    document.body.appendChild(tooltipEl);
    const tw = tooltipEl.offsetWidth;
    const th = tooltipEl.offsetHeight;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let left = pos.x * zoom + canvas.getBoundingClientRect().left + 12;
    let top = pos.y * zoom + canvas.getBoundingClientRect().top - th - 8;
    if (left + tw > vw - 8) left = vw - tw - 8;
    if (top < 4) top = pos.y * zoom + canvas.getBoundingClientRect().top + 40;
    tooltipEl.style.left = left + 'px';
    tooltipEl.style.top = top + 'px';
  }

  function hideTooltip() {
    if (tooltipEl) { tooltipEl.remove(); tooltipEl = null; }
  }

  // ── Context Menu ───────────────────────────────────────────────────────────
  function showContextMenu(ele, type, pos) {
    hideContextMenu();
    const id = ele.id();
    const zoom = cy.zoom();
    const rect = canvas.getBoundingClientRect();
    const x = pos.x * zoom + rect.left;
    const y = pos.y * zoom + rect.top;

    const html = '<div style="padding:4px 0;">' +
      (type === 'node'
        ? '<div class="ctx-item" data-action="expand" data-id="' + escHtml(id) + '" style="padding:6px 16px;cursor:pointer;font-size:12px;">Expand</div>' +
          '<div class="ctx-item" data-action="details" data-id="' + escHtml(id) + '" style="padding:6px 16px;cursor:pointer;font-size:12px;">View Details</div>' +
          '<div class="ctx-item" data-action="delete-node" data-id="' + escHtml(id) + '" style="padding:6px 16px;cursor:pointer;font-size:12px;color:#e53;">Delete</div>'
        : '<div class="ctx-item" data-action="details-edge" data-id="' + escHtml(id) + '" style="padding:6px 16px;cursor:pointer;font-size:12px;">View Details</div>' +
          '<div class="ctx-item" data-action="delete-rel" data-id="' + escHtml(id) + '" style="padding:6px 16px;cursor:pointer;font-size:12px;color:#e53;">Delete</div>'
      ) +
    '</div>';

    contextMenuEl = document.createElement('div');
    contextMenuEl.style.cssText = 'position:fixed;z-index:300;min-width:140px;background:var(--surface);border:1px solid var(--border);border-radius:6px;box-shadow:0 4px 16px rgba(0,0,0,0.25);padding:4px 0;font-size:12px;';
    contextMenuEl.innerHTML = html;
    document.body.appendChild(contextMenuEl);

    let left = x;
    let top = y;
    const cw = contextMenuEl.offsetWidth;
    const ch = contextMenuEl.offsetHeight;
    if (left + cw > window.innerWidth - 4) left = window.innerWidth - cw - 4;
    if (top + ch > window.innerHeight - 4) top = window.innerHeight - ch - 4;
    contextMenuEl.style.left = left + 'px';
    contextMenuEl.style.top = top + 'px';

    contextMenuEl.querySelectorAll('.ctx-item').forEach(item => {
      item.addEventListener('mouseover', () => item.style.background = 'var(--hover-bg)');
      item.addEventListener('mouseout', () => item.style.background = '');
      item.addEventListener('click', () => {
        const action = item.dataset.action;
        const eid = item.dataset.id;
        hideContextMenu();
        if (action === 'expand') expandNode(eid);
        else if (action === 'details') { apiGET('/api/graph/node/' + encodeURIComponent(eid)).then(r => r.json()).then(d => showDetailModal('Node', d)); }
        else if (action === 'delete-node') { deleteNode(eid); }
        else if (action === 'details-edge') { apiGET('/api/graph/relationship/' + encodeURIComponent(eid)).then(r => r.json()).then(d => showDetailModal('Relationship', d)); }
        else if (action === 'delete-rel') { deleteRelationship(eid); }
      });
    });
  }

  function hideContextMenu() {
    if (contextMenuEl) { contextMenuEl.remove(); contextMenuEl = null; }
  }

  // ── Keyboard Shortcuts ─────────────────────────────────────────────────────
  function onPanelKeydown(e) {
    if (!panel || !panel.classList.contains('active')) return;
    if (e.key === 'Escape') {
      closeDetails();
      hideContextMenu();
      hideSearchDropdown();
      cy.elements().unselectify();
    } else if (e.key === 'Delete') {
      const selected = cy.$('node:selected');
      if (selected.length > 0) {
        if (confirm('Delete ' + selected.length + ' selected node(s)?')) {
          selected.nodes().forEach(n => deleteNode(n.id()));
        }
      }
    } else if (e.key === 'f' || e.key === 'F') {
      if (cy) cy.fit(null, 50);
    } else if (e.key === 'r' || e.key === 'R') {
      loadSchema();
    }
  }

  function onSearchKeydown(e) {
    if (e.key === 'Escape') {
      hideSearchDropdown();
      searchInput.blur();
    }
  }

  // ── Panel Show ─────────────────────────────────────────────────────────────
  function onPanelShow() {
    if (!cy) return;
    resizeCanvas();
    if (cy.nodes().length === 0) loadSchema();
    panel.focus();
  }

  function resizeCanvas() {
    if (cy && canvas) {
      cy.resize();
      runLayout();
    }
  }

  // ── Load Schema ────────────────────────────────────────────────────────────
  async function loadSchema() {
    if (isLoading) return;
    isLoading = true;
    showLoading(true);

    try {
      const res = await apiGET('/api/graph/schema');
      if (res.status === 200) {
        const data = await res.json();
        updateLabelSelector(data.node_labels || []);
        updateRelTypeSelector(data.relationship_types || []);
        showEmptyState();
        updateStatus('Ready \u2014 ' + (data.node_labels || []).length + ' labels, ' + (data.relationship_types || []).length + ' relationship types');
      }
    } catch (e) {
      showError('Failed to load schema: ' + e.message);
    } finally {
      isLoading = false;
      showLoading(false);
    }
  }

  // ── Layout ─────────────────────────────────────────────────────────────────
  function onLayoutChange() {
    currentLayout = layoutSelect.value;
    if (currentLayout === 'table') {
      showTableView();
    } else {
      showGraphView();
      runLayout();
    }
  }

  function runLayout() {
    if (!cy || currentLayout === 'table') return;
    const layouts = {
      cose: { name: 'cose', animate: true, animationDuration: 500, padding: 50 },
      breadthfirst: { name: 'breadthfirst', animate: true, padding: 50 }
    };
    cy.layout(layouts[currentLayout] || layouts.cose).run();
  }

  // ── Search with adaptive debounce + preview ────────────────────────────────
  function onSearchInput() {
    const query = searchInput.value.trim();
    hideSearchDropdown();

    if (!query) {
      clearHighlights();
      return;
    }

    // Adaptive debounce: shorter for long queries
    const baseDelay = query.length > 10 ? 200 : 300;

    // Immediate preview
    clearTimeout(previewTimer);
    previewTimer = setTimeout(() => doPreviewSearch(query), 150);

    // Full search with debounce
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => doFullSearch(query), baseDelay);
  }

  async function doPreviewSearch(query) {
    try {
      const label = getSelectedLabel();
      const url = '/api/graph/search?q=' + encodeURIComponent(query) + (label ? '&label=' + encodeURIComponent(label) : '') + '&limit=5';
      const res = await apiGET(url);
      if (res.status === 200) {
        const nodes = await res.json();
        if (nodes.length > 0) showSearchDropdown(nodes);
      }
    } catch (e) { /* silent preview */ }
  }

  async function doFullSearch(query) {
    isLoading = true;
    showLoading(true);
    try {
      const label = getSelectedLabel();
      const url = '/api/graph/search?q=' + encodeURIComponent(query) + (label ? '&label=' + encodeURIComponent(label) : '') + '&limit=50';
      const res = await apiGET(url);
      if (res.status === 200) {
        const nodes = await res.json();
        highlightNodes(nodes);
        hideSearchDropdown();
        updateStatus('Found ' + nodes.length + ' nodes matching "' + query + '"');
      }
    } catch (e) {
      showError('Search failed: ' + e.message);
    } finally {
      isLoading = false;
      showLoading(false);
    }
  }

  function clearHighlights() {
    if (cy) cy.nodes().removeClass('highlighted');
  }

  function highlightNodes(nodes) {
    if (!cy) return;
    cy.nodes().removeClass('highlighted');
    nodes.forEach(n => {
      const id = n.id || n.element_id;
      const cyNode = nodeMap[id];
      if (cyNode) cyNode.addClass('highlighted');
    });
    if (nodes.length > 0) {
      expandNode(nodes[0].id || nodes[0].element_id);
    }
  }

  function clearSearch() {
    if (searchInput) searchInput.value = '';
    clearHighlights();
    hideSearchDropdown();
  }

  // ── Expand Node ────────────────────────────────────────────────────────────
  async function expandNode(elementId, depth) {
    const d = depth !== undefined ? depth : currentDepth;
    isLoading = true;
    showLoading(true);
    try {
      const res = await apiGET('/api/graph/topology/' + encodeURIComponent(elementId) + '?depth=' + d);
      if (res.status === 200) {
        const topo = await res.json();
        renderTopology(topo, d);
        expandedSet.add(elementId);
        const nc = (topo.nodes || []).length;
        const rc = (topo.relationships || []).length;
        updateStatus('Loaded ' + nc + ' nodes, ' + rc + ' edges (depth ' + d + ')');
      }
    } catch (e) {
      showError('Failed to expand node: ' + e.message);
    } finally {
      isLoading = false;
      showLoading(false);
    }
  }

  // ── Collapse Node ─────────────────────────────────────────────────────────
  function collapseNode(elementId) {
    const node = nodeMap[elementId];
    if (!node) return;
    // Get all edges connected to this node
    const connectedEdges = node.connectedEdges();
    const neighborNodes = connectedEdges.connectedNodes().not(node);
    // Remove edges first
    connectedEdges.remove();
    // Remove orphan neighbors (nodes that have no other connections)
    neighborNodes.forEach(n => {
      if (n.connectedEdges().length === 0) {
        const nid = n.id();
        n.remove();
        delete nodeMap[nid];
      }
    });
    // Remove the node's edges from relMap
    connectedEdges.forEach(e => {
      const rid = e.id();
      delete relMap[rid];
    });
    expandedSet.delete(elementId);
    updateCounts();
    runLayout();
  }

  // ── Expand All / Collapse All ─────────────────────────────────────────────
  function expandAll() {
    const ids = Object.keys(nodeMap);
    if (ids.length === 0) { updateStatus('No nodes to expand'); return; }
    let done = 0;
    ids.forEach((id, i) => {
      setTimeout(() => {
        expandNode(id, 1);
        done++;
        if (done === ids.length) updateStatus('Expanded all ' + ids.length + ' nodes');
      }, i * 100);
    });
    updateStatus('Expanding all nodes...');
  }

  function collapseAll() {
    if (!cy) return;
    cy.elements().remove();
    nodeMap = {};
    relMap = {};
    expandedSet.clear();
    updateCounts();
    showEmptyState();
    updateStatus('Graph cleared');
  }

  // ── Render Topology ────────────────────────────────────────────────────────
  function renderTopology(topo, depth) {
    const nodes = topo.nodes || [];
    const rels = topo.relationships || [];

    nodes.forEach(n => {
      const id = n.id || n.element_id;
      if (!nodeMap[id]) {
        const cyNode = cy.add({
          group: 'nodes',
          data: {
            id: id,
            label: (n.properties && (n.properties.name || n.properties.title)) || id,
            color: getLabelColor((n.labels && n.labels[0]) || 'Default'),
            borderColor: getLabelColor((n.labels && n.labels[0]) || 'Default')
          }
        });
        nodeMap[id] = cyNode;
      }
    });

    rels.forEach(r => {
      const id = r.id || r.element_id;
      if (!relMap[id]) {
        // Verify source and target nodes exist
        const srcId = r.start_node_id || r.startNodeId;
        const tgtId = r.end_node_id || r.endNodeId;
        if (nodeMap[srcId] && nodeMap[tgtId]) {
          const cyEdge = cy.add({
            group: 'edges',
            data: {
              id: id,
              source: srcId,
              target: tgtId,
              label: r.type || r.rel_type
            }
          });
          relMap[id] = cyEdge;
        }
      }
    });

    runLayout();
    updateCounts();
  }

  // ── Table View ─────────────────────────────────────────────────────────────
  function showTableView() {
    if (listSidebar) listSidebar.classList.add('visible');
    if (canvas) canvas.style.display = 'none';
    loadNodeList();
  }

  function showGraphView() {
    if (listSidebar) listSidebar.classList.remove('visible');
    if (canvas) canvas.style.display = '';
  }

  async function loadNodeList(label) {
    const url = '/api/graph/nodes?label=' + encodeURIComponent(label || '') + '&limit=100';
    try {
      const res = await apiGET(url);
      if (res.status === 200) {
        const nodes = await res.json();
        renderNodeList(nodes);
      }
    } catch (e) { /* silent */ }
  }

  function renderNodeList(nodes) {
    if (!listSidebar) return;
    listSidebar.innerHTML = nodes.map(n => {
      const id = n.id || n.element_id;
      const label = (n.labels && n.labels[0]) || 'Unknown';
      const name = (n.properties && (n.properties.name || n.properties.title)) || JSON.stringify(n.properties || {});
      return '<div class="graph-node-item" data-id="' + escHtml(id) + '">' +
        '<span class="graph-node-label">' + escHtml(label) + '</span>' +
        '<span class="graph-node-type">' + escHtml(String(name).slice(0, 50)) + '</span>' +
      '</div>';
    }).join('');

    listSidebar.querySelectorAll('.graph-node-item').forEach(el => {
      el.addEventListener('click', () => {
        const id = el.dataset.id;
        expandNode(id);
        showGraphView();
      });
    });
  }

  // ── Node / Rel Details ─────────────────────────────────────────────────────
  function showNodeDetails(cyNode) {
    const id = cyNode.id();
    apiGET('/api/graph/node/' + encodeURIComponent(id)).then(r => r.json()).then(data => {
      showDetailModal('Node', data);
    });
  }

  function showRelDetails(cyEdge) {
    const id = cyEdge.id();
    apiGET('/api/graph/relationship/' + encodeURIComponent(id)).then(r => r.json()).then(data => {
      showDetailModal('Relationship', data);
    });
  }

  function showDetailModal(type, data) {
    closeDetails();
    const props = data.properties || {};
    const propRows = Object.entries(props).map(([k, v]) =>
      '<tr><td class="prop-key">' + escHtml(k) + '</td><td class="prop-val">' + escHtml(String(v)) + '</td></tr>'
    ).join('');
    const isNode = type === 'Node';
    const html =
      '<div class="graph-detail-overlay" id="graphDetailOverlay">' +
        '<div class="graph-detail-panel">' +
          '<div class="graph-detail-header">' +
            '<h3>' + type + (isNode && data.labels ? ' (' + escHtml(data.labels[0]) + ')' : '') + '</h3>' +
            '<button class="graph-detail-close" id="graphDetailClose">\u00d7</button>' +
          '</div>' +
          '<table class="graph-detail-props">' + (propRows || '<tr><td style="color:var(--muted);">No properties</td></tr>') + '</table>' +
          (isNode ? '<div class="graph-detail-actions" id="graphDetailActions">' +
            '<button class="graph-btn" id="graphExpandBtn">Expand</button>' +
            '<button class="graph-btn" id="graphCollapseBtn">Collapse</button>' +
            '<button class="graph-btn" id="graphEditBtn">Edit</button>' +
            '<button class="graph-btn" id="graphDeleteNodeBtn" style="color:#e53;">Delete</button>' +
          '</div>' : '<div class="graph-detail-actions">' +
            '<button class="graph-btn" id="graphEditBtn">Edit</button>' +
            '<button class="graph-btn" id="graphDeleteRelBtn" style="color:#e53;">Delete</button>' +
          '</div>') +
        '</div>' +
      '</div>';
    document.body.insertAdjacentHTML('beforeend', html);

    getEl('graphDetailClose').addEventListener('click', closeDetails);
    getEl('graphDetailOverlay').addEventListener('click', e => {
      if (e.target.id === 'graphDetailOverlay') closeDetails();
    });

    if (isNode && data.id) {
      getEl('graphExpandBtn').addEventListener('click', () => { closeDetails(); expandNode(data.id); });
      getEl('graphCollapseBtn').addEventListener('click', () => { closeDetails(); collapseNode(data.id); });
      getEl('graphEditBtn').addEventListener('click', () => showEditModal('Node', data));
      getEl('graphDeleteNodeBtn').addEventListener('click', () => { deleteNode(data.id); closeDetails(); });
    } else if (!isNode && data.id) {
      getEl('graphEditBtn').addEventListener('click', () => showEditModal('Relationship', data));
      getEl('graphDeleteRelBtn').addEventListener('click', () => { deleteRelationship(data.id); closeDetails(); });
    }
  }

  function closeDetails() {
    document.querySelectorAll('.graph-detail-overlay').forEach(el => el.remove());
  }

  // ── Edit Modal (Task 14) ───────────────────────────────────────────────────
  function showEditModal(type, data) {
    closeDetails();
    const props = data.properties || {};
    const propRows = Object.entries(props).map(([k, v]) => {
      const typeHint = getInputType(v);
      return '<tr class="prop-row" data-key="' + escHtml(k) + '">' +
        '<td><input class="prop-key-input" value="' + escHtml(k) + '" style="width:100%;padding:4px 6px;border:1px solid var(--border);border-radius:3px;background:var(--input-bg);color:var(--text);font-size:12px;"></td>' +
        '<td><input class="prop-val-input" type="' + typeHint + '" value="' + escHtml(String(v)) + '" style="width:100%;padding:4px 6px;border:1px solid var(--border);border-radius:3px;background:var(--input-bg);color:var(--text);font-size:12px;"></td>' +
        '<td><button class="prop-del-btn" style="background:none;border:none;color:var(--muted);cursor:pointer;font-size:16px;padding:0 4px;" title="Remove property">\u00d7</button></td>' +
      '</tr>';
    }).join('');

    const isNode = type === 'Node';
    const html =
      '<div class="graph-detail-overlay" id="graphEditOverlay">' +
        '<div class="graph-detail-panel">' +
          '<div class="graph-detail-header">' +
            '<h3>Edit ' + type + (isNode && data.labels ? ' (' + escHtml(data.labels[0]) + ')' : '') + '</h3>' +
            '<button class="graph-detail-close" id="graphEditClose">\u00d7</button>' +
          '</div>' +
          (isNode ? '<div style="padding:8px 16px 0;">' +
            '<label style="font-size:11px;color:var(--muted);">Label</label>' +
            '<div id="editLabelValue" style="font-weight:600;margin-bottom:8px;">' + escHtml(data.labels ? data.labels[0] : '') + '</div>' +
          '</div>' : '') +
          '<div style="padding:8px 16px 0;font-size:11px;color:var(--muted);">Properties</div>' +
          '<table class="graph-detail-props" id="editPropsTable" style="margin:8px 0;">' +
            '<thead><tr><th style="width:35%;padding:4px 6px;">Key</th><th style="width:55%;padding:4px 6px;">Value</th><th style="width:10%;"></th></tr></thead>' +
            '<tbody id="editPropsBody">' + propRows + '</tbody>' +
          '</table>' +
          '<div style="padding:0 16px 8px;">' +
            '<button class="graph-btn" id="editAddPropBtn" style="font-size:11px;padding:3px 8px;">+ Add Property</button>' +
          '</div>' +
          '<div class="graph-detail-actions">' +
            '<button class="graph-btn" id="editSaveBtn" style="background:var(--accent-bg);color:var(--accent-text);">Save</button>' +
            '<button class="graph-btn" id="editCancelBtn">Cancel</button>' +
          '</div>' +
        '</div>' +
      '</div>';

    document.body.insertAdjacentHTML('beforeend', html);

    getEl('graphEditClose').addEventListener('click', closeDetails);
    getEl('graphEditOverlay').addEventListener('click', e => {
      if (e.target.id === 'graphEditOverlay') closeDetails();
    });
    getEl('editCancelBtn').addEventListener('click', closeDetails);

    // Add property button
    getEl('editAddPropBtn').addEventListener('click', () => {
      const tbody = getEl('editPropsBody');
      const row = document.createElement('tr');
      row.className = 'prop-row';
      row.innerHTML = '<td><input class="prop-key-input" style="width:100%;padding:4px 6px;border:1px solid var(--border);border-radius:3px;background:var(--input-bg);color:var(--text);font-size:12px;" placeholder="key"></td>' +
        '<td><input class="prop-val-input" type="text" style="width:100%;padding:4px 6px;border:1px solid var(--border);border-radius:3px;background:var(--input-bg);color:var(--text);font-size:12px;" placeholder="value"></td>' +
        '<td><button class="prop-del-btn" style="background:none;border:none;color:var(--muted);cursor:pointer;font-size:16px;padding:0 4px;">\u00d7</button></td>';
      tbody.appendChild(row);
      wirePropDelBtn(row.querySelector('.prop-del-btn'), row);
    });

    // Wire delete buttons on existing rows
    document.querySelectorAll('.prop-del-btn').forEach(btn => {
      const row = btn.closest('tr');
      wirePropDelBtn(btn, row);
    });

    // Save
    getEl('editSaveBtn').addEventListener('click', () => {
      const rows = document.querySelectorAll('#editPropsBody tr.prop-row');
      const properties = {};
      rows.forEach(row => {
        const kInput = row.querySelector('.prop-key-input');
        const vInput = row.querySelector('.prop-val-input');
        const key = kInput.value.trim();
        const val = vInput.value;
        if (key) {
          // Coerce type based on input type
          if (vInput.type === 'number') properties[key] = val === '' ? null : Number(val);
          else if (vInput.type === 'checkbox') properties[key] = vInput.checked;
          else {
            const n = Number(val);
            properties[key] = val === '' ? '' : (!isNaN(n) && val !== '' ? n : val);
          }
        }
      });

      if (isNode) {
        saveEditedNode(data.id, properties);
      } else {
        saveEditedRelationship(data.id, properties);
      }
    });
  }

  function wirePropDelBtn(btn, row) {
    btn.addEventListener('click', () => row.remove());
  }

  function getInputType(value) {
    if (value === true || value === false) return 'checkbox';
    if (typeof value === 'number') return 'number';
    return 'text';
  }

  async function saveEditedNode(elementId, properties) {
    try {
      const res = await apiPUT('/api/graph/node/' + encodeURIComponent(elementId), { properties });
      if (res.status === 200) {
        // Update local Cytoscape node
        const cyNode = nodeMap[elementId];
        if (cyNode) {
          const newLabel = properties.name || properties.title || cyNode.data('label');
          cyNode.data('label', newLabel);
        }
        closeDetails();
        updateStatus('Node updated');
      } else {
        const err = await res.json();
        alert('Failed to update node: ' + (err.error || res.status));
      }
    } catch (e) {
      alert('Error updating node: ' + e.message);
    }
  }

  async function saveEditedRelationship(elementId, properties) {
    try {
      const res = await apiPUT('/api/graph/relationship/' + encodeURIComponent(elementId), { properties });
      if (res.status === 200) {
        closeDetails();
        updateStatus('Relationship updated');
      } else {
        const err = await res.json();
        alert('Failed to update relationship: ' + (err.error || res.status));
      }
    } catch (e) {
      alert('Error updating relationship: ' + e.message);
    }
  }

  // ── Create Node Modal ──────────────────────────────────────────────────────
  function showCreateNodeModal() {
    closeDetails();
    const html =
      '<div class="graph-detail-overlay" id="graphEditOverlay">' +
        '<div class="graph-detail-panel">' +
          '<div class="graph-detail-header">' +
            '<h3>Create Node</h3>' +
            '<button class="graph-detail-close" id="graphEditClose">\u00d7</button>' +
          '</div>' +
          '<div style="padding:8px 16px 0;">' +
            '<label style="font-size:11px;color:var(--muted);display:block;margin-bottom:4px;">Label *</label>' +
            '<input id="createNodeLabel" type="text" style="width:100%;padding:6px 8px;border:1px solid var(--border);border-radius:4px;background:var(--input-bg);color:var(--text);font-size:13px;box-sizing:border-box;" placeholder="e.g. Person">' +
          '</div>' +
          '<div style="padding:8px 16px 0;font-size:11px;color:var(--muted);">Properties</div>' +
          '<table class="graph-detail-props" style="margin:8px 0;">' +
            '<tbody id="editPropsBody"></tbody>' +
          '</table>' +
          '<div style="padding:0 16px 8px;">' +
            '<button class="graph-btn" id="editAddPropBtn" style="font-size:11px;padding:3px 8px;">+ Add Property</button>' +
          '</div>' +
          '<div class="graph-detail-actions">' +
            '<button class="graph-btn" id="editSaveBtn" style="background:var(--accent-bg);color:var(--accent-text);">Create</button>' +
            '<button class="graph-btn" id="editCancelBtn">Cancel</button>' +
          '</div>' +
        '</div>' +
      '</div>';

    document.body.insertAdjacentHTML('beforeend', html);

    getEl('graphEditClose').addEventListener('click', closeDetails);
    getEl('graphEditOverlay').addEventListener('click', e => {
      if (e.target.id === 'graphEditOverlay') closeDetails();
    });
    getEl('editCancelBtn').addEventListener('click', closeDetails);

    getEl('editAddPropBtn').addEventListener('click', () => {
      const tbody = getEl('editPropsBody');
      const row = document.createElement('tr');
      row.className = 'prop-row';
      row.innerHTML = '<td><input class="prop-key-input" style="width:100%;padding:4px 6px;border:1px solid var(--border);border-radius:3px;background:var(--input-bg);color:var(--text);font-size:12px;" placeholder="key"></td>' +
        '<td><input class="prop-val-input" type="text" style="width:100%;padding:4px 6px;border:1px solid var(--border);border-radius:3px;background:var(--input-bg);color:var(--text);font-size:12px;" placeholder="value"></td>' +
        '<td><button class="prop-del-btn" style="background:none;border:none;color:var(--muted);cursor:pointer;font-size:16px;padding:0 4px;">\u00d7</button></td>';
      tbody.appendChild(row);
      row.querySelector('.prop-del-btn').addEventListener('click', () => row.remove());
    });

    getEl('editSaveBtn').addEventListener('click', async () => {
      const label = getEl('createNodeLabel').value.trim();
      if (!label) { alert('Label is required'); return; }
      const rows = document.querySelectorAll('#editPropsBody tr.prop-row');
      const properties = {};
      rows.forEach(row => {
        const k = row.querySelector('.prop-key-input').value.trim();
        const v = row.querySelector('.prop-val-input').value;
        if (k) {
          const n = Number(v);
          properties[k] = v === '' ? '' : (!isNaN(n) && v !== '' ? n : v);
        }
      });
      try {
        const res = await apiPOST('/api/graph/node', { label, properties });
        if (res.status === 201 || res.status === 200) {
          const result = await res.json();
          closeDetails();
          updateStatus('Node created: ' + (properties.name || label));
          // Add to graph
          expandNode(result.id, 1);
        } else {
          const err = await res.json();
          alert('Failed to create node: ' + (err.error || res.status));
        }
      } catch (e) {
        alert('Error creating node: ' + e.message);
      }
    });
  }

  // ── Delete ─────────────────────────────────────────────────────────────────
  async function deleteNode(elementId) {
    if (!confirm('Delete this node?')) return;
    const res = await apiDELETE('/api/graph/node/' + encodeURIComponent(elementId));
    if (res.status === 200) {
      const cyNode = nodeMap[elementId];
      if (cyNode) cyNode.remove();
      delete nodeMap[elementId];
      delete relMap[elementId];
      expandedSet.delete(elementId);
      updateCounts();
    }
  }

  async function deleteRelationship(elementId) {
    if (!confirm('Delete this relationship?')) return;
    const res = await apiDELETE('/api/graph/relationship/' + encodeURIComponent(elementId));
    if (res.status === 200) {
      const cyEdge = relMap[elementId];
      if (cyEdge) cyEdge.remove();
      delete relMap[elementId];
      updateCounts();
    }
  }

  // ── Helpers ────────────────────────────────────────────────────────────────
  function getLabelColor(label) {
    const colors = ['#FF6B35','#4ECDC4','#45B7D1','#96CEB4','#FFEAA7','#DDA0DD','#98D8C8','#F7DC6F'];
    let hash = 0;
    for (let c of label) hash = (hash * 31 + c.charCodeAt(0)) & 0xffffffff;
    return colors[Math.abs(hash) % colors.length];
  }

  function getSelectedLabel() {
    const sel = document.getElementById('graph-label-select');
    return sel ? sel.value : '';
  }

  function updateLabelSelector(labels) {
    let sel = document.getElementById('graph-label-select');
    if (!sel) {
      sel = document.createElement('select');
      sel.id = 'graph-label-select';
      sel.className = 'graph-label-select';
      sel.style.cssText = 'padding:4px 8px;border-radius:4px;border:1px solid var(--border);';
      if (searchInput && searchInput.parentNode) {
        searchInput.parentNode.insertBefore(sel, searchInput);
      }
    }
    sel.innerHTML = '<option value="">All Labels</option>' +
      labels.map(l => '<option value="' + escHtml(l) + '">' + escHtml(l) + '</option>').join('');
    sel.addEventListener('change', () => loadNodeList(sel.value));
  }

  function updateRelTypeSelector(types) {
    let sel = document.getElementById('graph-reltype-select');
    if (!sel) {
      sel = document.createElement('select');
      sel.id = 'graph-reltype-select';
      sel.className = 'graph-reltype-select';
      sel.style.cssText = 'padding:4px 8px;border-radius:4px;border:1px solid var(--border);';
      const labelSel = document.getElementById('graph-label-select');
      if (labelSel && labelSel.parentNode) {
        labelSel.parentNode.insertBefore(sel, labelSel.nextSibling);
      }
    }
    sel.innerHTML = '<option value="">All Rel Types</option>' +
      types.map(t => '<option value="' + escHtml(t) + '">' + escHtml(t) + '</option>').join('');
  }

  function showEmptyState() {
    if (!canvas) return;
    const existing = canvas.querySelector('.graph-empty');
    if (existing) return;
    const div = document.createElement('div');
    div.className = 'graph-empty';
    div.style.cssText = 'display:flex;align-items:center;justify-content:center;height:100%;color:var(--muted);font-size:14px;';
    div.textContent = 'Search for a node to visualize the graph';
    canvas.appendChild(div);
  }

  function showLoading(loading) {
    if (canvas) canvas.classList.toggle('graph-loading', loading);
  }

  function showError(msg) {
    updateStatus(msg);
  }

  function updateStatus(msg) {
    if (statusBar) statusBar.textContent = msg;
  }

  function updateCounts() {
    const nc = Object.keys(nodeMap).length;
    const rc = Object.keys(relMap).length;
    if (statusNodes) statusNodes.textContent = nc;
    if (statusEdges) statusEdges.textContent = rc;
  }

  function debounce(fn, delay) {
    let t;
    return function() {
      const args = arguments;
      clearTimeout(t);
      t = setTimeout(() => fn.apply(null, args), delay);
    };
  }

  function escHtml(s) {
    if (s === null || s === undefined) return '';
    const d = document.createElement('div');
    d.textContent = String(s);
    return d.innerHTML;
  }

  // ── API helpers ────────────────────────────────────────────────────────────
  async function apiGET(url) {
    return fetch(url, { credentials: 'include' });
  }

  async function apiDELETE(url) {
    return fetch(url, { method: 'DELETE', credentials: 'include' });
  }

  async function apiPOST(url, body) {
    return fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(body)
    });
  }

  async function apiPUT(url, body) {
    return fetch(url, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(body)
    });
  }

  // ── Boot ───────────────────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', init);

  // ── Expose toolbar helpers ─────────────────────────────────────────────────
  // Depth selector is added by the HTML — wire it here
  document.addEventListener('DOMContentLoaded', () => {
    const depthSelect = getEl('graphDepthSelect');
    if (depthSelect) {
      depthSelect.addEventListener('change', () => {
        currentDepth = parseInt(depthSelect.value, 10) || 1;
      });
    }
    const addNodeBtn = getEl('graphAddNodeBtn');
    if (addNodeBtn) addNodeBtn.addEventListener('click', showCreateNodeModal);
    const expandAllBtn = getEl('graphExpandAllBtn');
    if (expandAllBtn) expandAllBtn.addEventListener('click', expandAll);
    const collapseAllBtn = getEl('graphCollapseAllBtn');
    if (collapseAllBtn) collapseAllBtn.addEventListener('click', collapseAll);
    const clearSearchBtn = getEl('graphClearSearchBtn');
    if (clearSearchBtn) clearSearchBtn.addEventListener('click', clearSearch);
  });

  // ── Exports ────────────────────────────────────────────────────────────────
  window.GraphPanel = {
    loadSchema: loadSchema,
    expandNode: expandNode,
    showGraphView: showGraphView,
    expandAll: expandAll,
    collapseAll: collapseAll,
    showCreateNodeModal: showCreateNodeModal
  };

})();
