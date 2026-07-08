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
    if (searchInput) searchInput.addEventListener('input', debounce(onSearch, 300));
    if (refreshBtn) refreshBtn.addEventListener('click', loadSchema);
    if (closeBtn) closeBtn.addEventListener('click', () => switchPanel('graph'));

    panel.addEventListener('panel:show', onPanelShow);

    initCytoscape();
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
          style: {
            'border-width': 4,
            'border-color': '#FF6B35'
          }
        },
        {
          selector: 'node.highlighted',
          style: {
            'border-width': 3,
            'border-color': '#FF6B35'
          }
        }
      ],
      layout: { name: 'preset' },
      wheelSensitivity: 0.3,
      minZoom: 0.1,
      maxZoom: 3.0
    });

    cy.on('tap', 'node', function(evt) {
      showNodeDetails(evt.target);
    });

    cy.on('tap', 'edge', function(evt) {
      showRelDetails(evt.target);
    });

    cy.on('tap', function(evt) {
      if (evt.target === cy) closeDetails();
    });
  }

  // ── Panel Show ─────────────────────────────────────────────────────────────
  function onPanelShow() {
    if (!cy) return;
    resizeCanvas();
    if (cy.nodes().length === 0) loadSchema();
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

  // ── Search ─────────────────────────────────────────────────────────────────
  async function onSearch() {
    const query = searchInput.value.trim();
    if (!query) {
      if (cy) cy.nodes().removeClass('highlighted');
      return;
    }

    isLoading = true;
    showLoading(true);
    try {
      const label = getSelectedLabel();
      const url = '/api/graph/search?q=' + encodeURIComponent(query) + (label ? '&label=' + encodeURIComponent(label) : '');
      const res = await apiGET(url);
      if (res.status === 200) {
        const nodes = await res.json();
        highlightNodes(nodes);
        updateStatus('Found ' + nodes.length + ' nodes matching "' + query + '"');
      }
    } catch (e) {
      showError('Search failed: ' + e.message);
    } finally {
      isLoading = false;
      showLoading(false);
    }
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

  // ── Expand Node ────────────────────────────────────────────────────────────
  async function expandNode(elementId) {
    isLoading = true;
    showLoading(true);
    try {
      const res = await apiGET('/api/graph/topology/' + encodeURIComponent(elementId) + '?depth=1');
      if (res.status === 200) {
        const topo = await res.json();
        renderTopology(topo);
        const nc = (topo.nodes || []).length;
        const rc = (topo.relationships || []).length;
        updateStatus('Loaded ' + nc + ' nodes, ' + rc + ' edges');
      }
    } catch (e) {
      showError('Failed to expand node: ' + e.message);
    } finally {
      isLoading = false;
      showLoading(false);
    }
  }

  // ── Render Topology ────────────────────────────────────────────────────────
  function renderTopology(topo) {
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
        const cyEdge = cy.add({
          group: 'edges',
          data: {
            id: id,
            source: r.start_node_id || r.startNodeId,
            target: r.end_node_id || r.endNodeId,
            label: r.type || r.rel_type
          }
        });
        relMap[id] = cyEdge;
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
    const html =
      '<div class="graph-detail-overlay" id="graphDetailOverlay">' +
        '<div class="graph-detail-panel">' +
          '<div class="graph-detail-header">' +
            '<h3>' + type + '</h3>' +
            '<button class="graph-detail-close" id="graphDetailClose">\u00d7</button>' +
          '</div>' +
          '<table class="graph-detail-props">' + propRows + '</table>' +
          (type === 'Node' ? '<div class="graph-detail-actions">' +
            '<button class="graph-btn" id="graphExpandBtn">Expand</button>' +
            '<button class="graph-btn" id="graphDeleteNodeBtn">Delete</button>' +
          '</div>' : '') +
        '</div>' +
      '</div>';
    document.body.insertAdjacentHTML('beforeend', html);
    const closeBtnEl = getEl('graphDetailClose');
    if (closeBtnEl) closeBtnEl.addEventListener('click', closeDetails);
    const overlay = getEl('graphDetailOverlay');
    if (overlay) overlay.addEventListener('click', e => {
      if (e.target.id === 'graphDetailOverlay') closeDetails();
    });
    if (type === 'Node' && data.id) {
      const expandBtn = getEl('graphExpandBtn');
      const deleteBtn = getEl('graphDeleteNodeBtn');
      if (expandBtn) expandBtn.addEventListener('click', () => { closeDetails(); expandNode(data.id); });
      if (deleteBtn) deleteBtn.addEventListener('click', () => { deleteNode(data.id); closeDetails(); });
    }
  }

  function closeDetails() {
    document.querySelectorAll('.graph-detail-overlay').forEach(el => el.remove());
  }

  async function deleteNode(elementId) {
    if (!confirm('Delete this node?')) return;
    const res = await apiDELETE('/api/graph/node/' + encodeURIComponent(elementId));
    if (res.status === 200) {
      const cyNode = nodeMap[elementId];
      if (cyNode) cyNode.remove();
      delete nodeMap[elementId];
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

  // ── Boot ───────────────────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', init);

  // ── Exports ────────────────────────────────────────────────────────────────
  window.GraphPanel = { loadSchema: loadSchema, expandNode: expandNode, showGraphView: showGraphView };

})();