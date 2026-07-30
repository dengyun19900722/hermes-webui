/* ==========================================
   GRAPH — JSON view
   ========================================== */
(function() {
  "use strict";

  let selected = null;

  async function onShow(schema) {
    if (!schema) return;
    await renderTree(schema);
  }

  async function renderTree(schema) {
    const treeEl = document.getElementById("graphJsonTree");
    if (!treeEl) return;
    let html = '<div class="graph-json-section"><h4>Nodes</h4><ul>';
    for (const label of schema.node_labels || []) {
      html += `<li class="graph-json-label" data-label="${escAttr(label)}">${escHtml(label)}</li>`;
    }
    html += '</ul></div><div class="graph-json-section"><h4>Relationships</h4><ul>';
    for (const t of schema.relationship_types || []) {
      html += `<li class="graph-json-type">${escHtml(t)}</li>`;
    }
    html += "</ul></div>";
    treeEl.innerHTML = html;

    treeEl.querySelectorAll(".graph-json-label").forEach(el => {
      el.addEventListener("click", async () => {
        const res = await fetch("/api/graph/nodes?label=" + encodeURIComponent(el.dataset.label));
        const json = await res.json();
        if (json.ok) showList(el.dataset.label, json.data.results || []);
      });
    });
  }

  function showList(label, nodes) {
    const treeEl = document.getElementById("graphJsonTree");
    const detailEl = document.getElementById("graphJsonDetail");
    if (!treeEl || !detailEl) return;
    treeEl.innerHTML = `<button class="btn-link" id="graphJsonBack">← Back</button>
      <h4>${escHtml(label)} (${nodes.length})</h4>
      <ul class="graph-json-list">${nodes.map(n => `
        <li data-id="${escAttr(n.id)}" class="graph-json-item">${escHtml((n.properties && n.properties.name) || n.id)}</li>
      `).join("")}</ul>`;
    treeEl.querySelectorAll(".graph-json-item").forEach(el => {
      el.addEventListener("click", async () => {
        const res = await fetch("/api/graph/node/" + encodeURIComponent(el.dataset.id));
        const json = await res.json();
        if (json.ok) showDetail(json.data);
      });
    });
    const back = document.getElementById("graphJsonBack");
    if (back) back.addEventListener("click", () => onShow(window.GraphMain.state.schema));
  }

  function showDetail(data) {
    const detailEl = document.getElementById("graphJsonDetail");
    if (!detailEl) return;
    selected = data;
    detailEl.innerHTML = `
      <div class="graph-json-toolbar">
        <button class="btn btn-secondary" id="graphJsonCopy">Copy</button>
        <button class="btn btn-secondary" id="graphJsonDownload">Download</button>
      </div>
      <pre class="graph-json-pre">${escHtml(JSON.stringify(data, null, 2))}</pre>
    `;
    document.getElementById("graphJsonCopy").addEventListener("click", () => {
      navigator.clipboard.writeText(JSON.stringify(data, null, 2));
      if (window.GraphMain) window.GraphMain.setStatus("Copied to clipboard");
    });
    document.getElementById("graphJsonDownload").addEventListener("click", () => {
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = (data.properties && data.properties.name) || data.id;
      a.click();
      URL.revokeObjectURL(url);
    });
  }

  function escHtml(s) { return String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
  function escAttr(s) { return escHtml(s); }

  window.GraphViewJson = { onShow };
})();
