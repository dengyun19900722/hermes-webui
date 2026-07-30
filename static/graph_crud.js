/* ==========================================
   GRAPH — CRUD modal
   ========================================== */
(function() {
  "use strict";

  let mount = null;

  document.addEventListener("DOMContentLoaded", () => {
    mount = document.getElementById("graphCrudMount");
  });

  function openModal(title, body) {
    if (!mount) mount = document.getElementById("graphCrudMount");
    if (!mount) return;
    mount.innerHTML = `
      <div class="graph-crud-backdrop"></div>
      <div class="graph-crud-modal">
        <div class="graph-crud-head">
          <h3>${title}</h3>
          <button class="panel-head-btn" id="graphCrudClose">✕</button>
        </div>
        <div class="graph-crud-body">${body}</div>
      </div>`;
    mount.querySelector(".graph-crud-backdrop").addEventListener("click", close);
    mount.querySelector("#graphCrudClose").addEventListener("click", close);
  }

  function close() { if (mount) mount.innerHTML = ""; }

  function openCreateNode() {
    const schema = window.GraphMain ? window.GraphMain.state.schema : null;
    const labels = (schema && schema.node_labels) || ["Host", "Service", "Incident", "Runbook"];
    const body = `
      <label>Labels
        <div class="graph-crud-labels">${labels.map(l =>
          `<label class="graph-crud-chip"><input type="checkbox" value="${escAttr(l)}">${escHtml(l)}</label>`
        ).join("")}</div>
      </label>
      <label>Properties (key=value, one per line)
        <textarea id="graphCrudProps" rows="5" placeholder="name=web-01&#10;ip=10.0.0.1"></textarea>
      </label>
      <div class="graph-crud-actions">
        <button class="btn btn-secondary" id="graphCrudCancel">Cancel</button>
        <button class="btn btn-primary" id="graphCrudSave">Create</button>
      </div>`;
    openModal("Create Node", body);
    document.getElementById("graphCrudCancel").addEventListener("click", close);
    document.getElementById("graphCrudSave").addEventListener("click", saveCreate);
  }

  async function saveCreate() {
    const labels = Array.from(document.querySelectorAll(".graph-crud-labels input:checked")).map(i => i.value);
    const propsText = document.getElementById("graphCrudProps").value.trim();
    const properties = {};
    propsText.split(/\n+/).forEach(line => {
      const [k, ...rest] = line.split("=");
      if (k && rest.length) properties[k.trim()] = rest.join("=").trim();
    });
    if (labels.length === 0) { alert("Select at least one label"); return; }
    try {
      const res = await fetch("/api/graph/nodes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ labels, properties }),
      });
      const json = await res.json();
      if (!json.ok) throw new Error(json.error);
      close();
      const panel = document.getElementById("panelGraph");
      if (panel) panel.dispatchEvent(new CustomEvent("panel:show"));
    } catch (e) {
      alert("Create failed: " + e.message);
    }
  }

  async function openEditNode(nodeId) {
    const res = await fetch("/api/graph/node/" + encodeURIComponent(nodeId));
    const json = await res.json();
    if (!json.ok) {
      // 用状态栏而不是 alert，避免阻塞 UI 和破坏使用体验
      if (window.GraphMain) {
        window.GraphMain.setStatus(
          "Load node failed: " + (json.error || res.statusText || "unknown"), "error");
      }
      return;
    }
    const n = json.data;
    const propsText = Object.entries(n.properties || {})
      .map(([k, v]) => `${k}=${typeof v === "string" ? v : JSON.stringify(v)}`).join("\n");
    const body = `
      <p><strong>ID:</strong> <code>${escHtml(n.id)}</code></p>
      <p><strong>Labels:</strong> ${(n.labels || []).map(escHtml).join(", ")}</p>
      <label>Properties
        <textarea id="graphCrudProps" rows="8">${escHtml(propsText)}</textarea>
      </label>
      <div class="graph-crud-actions">
        <button class="btn btn-secondary" id="graphCrudCancel">Cancel</button>
        <button class="btn btn-primary" id="graphCrudSave">Save</button>
      </div>`;
    openModal("Edit Node", body);
    document.getElementById("graphCrudCancel").addEventListener("click", close);
    document.getElementById("graphCrudSave").addEventListener("click", () => saveEdit(nodeId));
  }

  async function saveEdit(nodeId) {
    const propsText = document.getElementById("graphCrudProps").value.trim();
    const properties = {};
    propsText.split(/\n+/).forEach(line => {
      const [k, ...rest] = line.split("=");
      if (k && rest.length) properties[k.trim()] = rest.join("=").trim();
    });
    try {
      const res = await fetch("/api/graph/node/" + encodeURIComponent(nodeId), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ properties }),
      });
      const json = await res.json();
      if (!json.ok) throw new Error(json.error);
      if (window.GraphMain) window.GraphMain.setStatus("Node updated");
      close();
    } catch (e) {
      alert("Update failed: " + e.message);
    }
  }

  async function deleteNode(nodeId) {
    if (!confirm(`Delete node ${nodeId.slice(0, 12)}…? This will cascade delete relationships.`)) return;
    try {
      const res = await fetch("/api/graph/node/" + encodeURIComponent(nodeId), { method: "DELETE" });
      const json = await res.json();
      if (!json.ok) throw new Error(json.error);
      if (window.GraphMain) window.GraphMain.setStatus("Node deleted");
      const panel = document.getElementById("panelGraph");
      if (panel) panel.dispatchEvent(new CustomEvent("panel:show"));
    } catch (e) {
      alert("Delete failed: " + e.message);
    }
  }

  function showNodeActions(nodeId) {
    // Lightweight stub: reserved for future floating menu
  }

  function escHtml(s) { return String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
  function escAttr(s) { return escHtml(s); }

  window.GraphCRUD = { openCreateNode, openEditNode, deleteNode, showNodeActions };
})();
