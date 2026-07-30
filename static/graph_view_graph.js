/* ==========================================
   GRAPH — Cytoscape view
   ========================================== */
(function() {
  "use strict";

  let cy = null;
  let canvas = null;
  let nodeMap = {};
  let relMap = {};
  const LABEL_COLORS = {
    Host: "#4A90E2", Service: "#7ED321", Incident: "#D0021B", Runbook: "#F5A623",
  };

  function $(id) { return document.getElementById(id); }

  function init() {
    canvas = $("graphCanvas");
    if (!canvas || typeof cytoscape === "undefined") return;

    cy = cytoscape({
      container: canvas,
      style: [
        { selector: "node", style: {
            label: "data(label)",
            "background-color": "data(color)",
            "border-width": 2,
            "border-color": "data(borderColor)",
            width: 40, height: 40,
            "font-size": 12, "text-valign": "bottom", color: "#555",
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
      });
    });
  }

  function onShow() {
    if (cy) {
      // Critical: must resize after tab switch, otherwise Cytoscape won't render
      setTimeout(() => { if (cy) cy.resize(); }, 50);
    }
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
        const name = (n.properties && (n.properties.name || n.properties.title)) || id;
        nodeMap[id] = cy.add({
          group: "nodes",
          data: {
            id,
            label: name,
            color: LABEL_COLORS[label] || "#999",
            borderColor: LABEL_COLORS[label] || "#999",
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
  window.GraphViewGraph = { expandNode, onShow };
})();
