/* ==========================================
   GRAPH — Table view
   ========================================== */
(function() {
  "use strict";

  let currentSubtab = "nodes";
  let allNodes = [];
  let allRels = [];

  async function onShow(schema) {
    if (!schema) return;
    await Promise.all([loadNodes(schema), loadRels()]);
  }

  async function loadNodes(schema) {
    try {
      let collected = [];
      if (schema && schema.node_labels && schema.node_labels.length > 0) {
        for (const label of schema.node_labels) {
          const res = await fetch("/api/graph/nodes?label=" + encodeURIComponent(label) + "&limit=200");
          const json = await res.json();
          if (json.ok && json.data) collected = collected.concat(json.data.results || []);
        }
      }
      allNodes = collected;
      renderNodesTable();
    } catch (e) {
      console.error("loadNodes failed", e);
    }
  }

  async function loadRels() {
    try {
      const res = await fetch("/api/graph/relationships?limit=500");
      const json = await res.json();
      allRels = (json.ok && json.data) ? (json.data.results || []) : [];
      renderRelsTable();
    } catch (e) { /* silent */ }
  }

  function renderNodesTable() {
    const tbody = document.querySelector("#graphTableNodes tbody");
    if (!tbody) return;
    tbody.innerHTML = allNodes.map(n => `
      <tr data-id="${escAttr(n.id)}">
        <td class="graph-td-id">${escHtml(n.id.slice(0, 12))}…</td>
        <td>${escHtml((n.labels || []).join(", "))}</td>
        <td>${escHtml((n.properties && (n.properties.name || n.properties.title)) || "")}</td>
        <td class="graph-td-actions">
          <button class="graph-row-btn" data-action="locate">Locate</button>
          <button class="graph-row-btn" data-action="edit">Edit</button>
          <button class="graph-row-btn danger" data-action="delete">Delete</button>
        </td>
      </tr>
    `).join("");
    tbody.querySelectorAll("button").forEach(btn => {
      btn.addEventListener("click", e => {
        const tr = e.target.closest("tr");
        const id = tr.dataset.id;
        const a = btn.dataset.action;
        if (a === "locate") switchToGraph(id);
        else if (a === "edit") window.GraphCRUD && window.GraphCRUD.openEditNode(id);
        else if (a === "delete") window.GraphCRUD && window.GraphCRUD.deleteNode(id);
      });
    });
  }

  function renderRelsTable() {
    const tbody = document.querySelector("#graphTableRels tbody");
    if (!tbody) return;
    tbody.innerHTML = allRels.map(r => `
      <tr data-id="${escAttr(r.id)}">
        <td class="graph-td-id">${escHtml(r.id.slice(0, 12))}…</td>
        <td>${escHtml(r.type)}</td>
        <td>${escHtml((r.start_node_id || "").slice(0, 12))}…</td>
        <td>${escHtml((r.end_node_id || "").slice(0, 12))}…</td>
        <td class="graph-td-actions">
          <button class="graph-row-btn danger" data-action="delete">Delete</button>
        </td>
      </tr>
    `).join("");
    tbody.querySelectorAll("button").forEach(btn => {
      btn.addEventListener("click", e => {
        const tr = e.target.closest("tr");
        const id = tr.dataset.id;
        if (confirm(`Delete relationship ${id.slice(0, 12)}…?`)) {
          fetch("/api/graph/relationship/" + encodeURIComponent(id), { method: "DELETE" })
            .then(r => r.json())
            .then(j => {
              if (j.ok) {
                if (window.GraphMain) window.GraphMain.setStatus("Relationship deleted");
                loadRels();
              }
            });
        }
      });
    });
  }

  function switchToGraph(nodeId) {
    if (window.GraphMain) window.GraphMain.switchView("graph");
    if (window.GraphViewGraph) window.GraphViewGraph.expandNode(nodeId);
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".graph-subtab").forEach(btn => {
      btn.addEventListener("click", () => {
        currentSubtab = btn.dataset.table;
        document.querySelectorAll(".graph-subtab").forEach(b => b.classList.toggle("active", b === btn));
        document.getElementById("graphTableNodes").hidden = currentSubtab !== "nodes";
        document.getElementById("graphTableRels").hidden = currentSubtab !== "relationships";
      });
    });
  });

  function escHtml(s) { return String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
  function escAttr(s) { return escHtml(s); }

  window.GraphViewTable = { onShow };
})();
