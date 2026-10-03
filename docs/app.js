"use strict";

const AREA_NAMES = {
  modification: "Modification-based",
  generative: "Generative",
  steganalysis: "Steganalysis",
  surveys: "Surveys",
};
const FEATURES = [
  { id: "llm_adaptable", label: "LLM-adaptable", test: (e) => e.features?.llm_adaptable },
  { id: "training_free", label: "Training-free", test: (e) => e.features?.training_free },
  { id: "asymmetric", label: "Asymmetric", test: (e) => e.features?.asymmetric },
  { id: "black_box", label: "Black-box", test: (e) => e.features?.black_box },
  { id: "multi", label: "Multi-objective", test: (e) => (e.targets || []).length > 1 },
  { id: "pretrained", label: "Pre-trained detector", test: (e) => e.features?.pretrained },
  { id: "llm_based", label: "LLM-based detector", test: (e) => e.features?.llm_based },
  { id: "code", label: "Has code", test: (e) => Boolean(e.links?.code) },
  { id: "beyond", label: "Beyond the survey", test: (e) => !e.in_survey },
];
const LINK_LABELS = { paper: "Paper", arxiv: "arXiv", code: "Code", project: "Project", video: "Video",
  slides: "Slides", poster: "Poster" };

const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

let DATA;
const state = { q: "", area: "", category: "", from: "", to: "", sort: "new", features: new Set() };

function readHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  for (const k of ["q", "area", "category", "from", "to", "sort"]) if (p.has(k)) state[k] = p.get(k);
  if (p.has("f")) state.features = new Set(p.get("f").split(",").filter(Boolean));
}

function writeHash() {
  const p = new URLSearchParams();
  for (const k of ["q", "area", "category", "from", "to"]) if (state[k]) p.set(k, state[k]);
  if (state.sort !== "new") p.set("sort", state.sort);
  if (state.features.size) p.set("f", [...state.features].join(","));
  const hash = p.toString();
  history.replaceState(null, "", hash ? `#${hash}` : location.pathname);
}

function renderStats() {
  const s = DATA.stats;
  const cards = [
    [s.papers, "entries"], [s.methods, "steganographic methods"], [s.by_area.steganalysis, "steganalysis methods"],
    [s.by_area.surveys, "surveys"], [s.metrics, "evaluation metrics"], [s.with_code, "with code"],
  ];
  $("#stats").innerHTML = cards.map(([n, l]) =>
    `<div class="card"><div class="num">${n}</div><div class="label">${esc(l)}</div></div>`).join("");
  $("#charts").innerHTML = DATA.charts.map((c) => `<img src="${esc(c)}" alt="${esc(c)}" loading="lazy">`).join("");
}

function renderControls() {
  const area = $("#area");
  area.innerHTML = `<option value="">All areas</option>` +
    Object.entries(AREA_NAMES).map(([k, v]) => `<option value="${k}">${v}</option>`).join("");
  $("#chips").innerHTML = FEATURES.map((f) =>
    `<button type="button" class="chip" data-f="${f.id}" aria-pressed="false">${f.label}</button>`).join("");
  const years = DATA.entries.map((e) => e.year);
  $("#from").placeholder = Math.min(...years);
  $("#to").placeholder = Math.max(...years);
}

function renderCategoryOptions() {
  const cats = Object.entries(DATA.category_names)
    .filter(([path]) => !state.area || path.startsWith(`${state.area}/`));
  $("#category").innerHTML = `<option value="">All categories</option>` + cats.map(([path, name]) => {
    const parts = path.split("/");
    const parent = DATA.taxonomy[parts[0]].children[parts[1]].name;
    return `<option value="${path}">${esc(AREA_NAMES[parts[0]])} › ${esc(parent)} › ${esc(name)}</option>`;
  }).join("");
  if (![...$("#category").options].some((o) => o.value === state.category)) state.category = "";
  $("#category").value = state.category;
}

function syncControls() {
  for (const k of ["q", "area", "from", "to", "sort"]) $(`#${k}`).value = state[k];
  renderCategoryOptions();
  document.querySelectorAll(".chip").forEach((b) =>
    b.setAttribute("aria-pressed", String(state.features.has(b.dataset.f))));
}

function matches(e) {
  if (state.area && e.area !== state.area) return false;
  if (state.category && !(e.categories || []).some((c) => c === state.category || c.startsWith(`${state.category}/`))) return false;
  if (state.from && e.year < Number(state.from)) return false;
  if (state.to && e.year > Number(state.to)) return false;
  for (const f of FEATURES) if (state.features.has(f.id) && !f.test(e)) return false;
  if (state.q) {
    const hay = [e.name, e.title, e.venue, e.backbone, ...(e.authors || []), ...(e.category_names || [])]
      .join(" ").toLowerCase();
    if (!state.q.toLowerCase().split(/\s+/).every((w) => hay.includes(w))) return false;
  }
  return true;
}

function row(e) {
  const tags = FEATURES.filter((f) => f.id !== "code" && f.id !== "beyond" && f.test(e))
    .map((f) => `<span class="tag">${f.label}</span>`);
  if (!e.in_survey) tags.unshift(`<span class="tag new">new</span>`);
  if (e.backbone) tags.push(`<span class="tag">${esc(e.backbone)}</span>`);
  const cats = (e.category_names || []).map((c) => `<span class="cat ${e.area}">${esc(c)}</span>`).join("") ||
    `<span class="cat ${e.area}">${AREA_NAMES[e.area]}</span>`;
  const links = Object.entries(e.links || {}).map(([k, u]) =>
    `<a href="${esc(u)}" target="_blank" rel="noopener">${LINK_LABELS[k] || k}</a>`).join("");
  const authors = e.authors.length > 3 ? `${e.authors.slice(0, 3).join(", ")}, et al.` : e.authors.join(", ");
  const name = e.name && !e.title.toLowerCase().includes(e.name.toLowerCase()) ? `<span class="name">${esc(e.name)}</span>` : "";
  return `<tr><td class="year">${e.year}</td>
    <td>${name}<span class="title">${esc(e.title)}</span><div class="authors">${esc(authors)}</div></td>
    <td>${esc(e.venue)}</td><td>${cats}</td><td>${tags.join("")}</td><td class="links">${links}</td></tr>`;
}

function renderTable() {
  const order = {
    new: (a, b) => b.year - a.year || a.title.localeCompare(b.title),
    old: (a, b) => a.year - b.year || a.title.localeCompare(b.title),
    title: (a, b) => a.title.localeCompare(b.title),
  }[state.sort];
  const rows = DATA.entries.filter(matches).sort(order);
  $("#count").textContent = `Showing ${rows.length} of ${DATA.entries.length} entries`;
  $("#papers tbody").innerHTML = rows.map(row).join("");
  writeHash();
}

function renderMetrics() {
  const arrow = { lower: "↓", higher: "↑", "n/a": "–" };
  $("#metric-table").innerHTML = "<thead><tr><th>Group</th><th>Category</th><th>Metric</th><th>Better</th>" +
    "<th>Description</th><th>Reference</th></tr></thead><tbody>" + DATA.metrics.map((m) => {
      const refs = (m.references || []).map((r) => r.url
        ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">${esc(r.year)}</a>` : esc(r.year)).join(", ");
      return `<tr><td>${esc(m.group)}</td><td>${esc(m.subgroup)}</td><td><b>${esc(m.name)}</b></td>` +
        `<td>${arrow[m.direction]}</td><td>${esc(m.description)}</td><td>${refs}</td></tr>`;
    }).join("") + "</tbody>";
  const steg = DATA.entries.filter((e) => e.area === "steganalysis");
  $("#dataset-table").innerHTML = "<thead><tr><th>Dataset</th><th>Description</th><th>Used by steganalysis papers</th>" +
    "<th>Links</th></tr></thead><tbody>" + DATA.datasets.map((d) => {
      const used = steg.filter((e) => (e.datasets || []).includes(d.id)).length;
      const links = Object.entries(d.links || {}).map(([k, u]) =>
        `<a href="${esc(u)}" target="_blank" rel="noopener">${LINK_LABELS[k] || k}</a>`).join(" ");
      return `<tr><td><b>${esc(d.name)}</b></td><td>${esc(d.description)}</td><td>${used} / ${steg.length}</td>` +
        `<td>${links}</td></tr>`;
    }).join("") + "</tbody>";
}

function bind() {
  for (const k of ["q", "from", "to"]) $(`#${k}`).addEventListener("input", (ev) => { state[k] = ev.target.value; renderTable(); });
  $("#area").addEventListener("change", (ev) => { state.area = ev.target.value; renderCategoryOptions(); renderTable(); });
  $("#category").addEventListener("change", (ev) => { state.category = ev.target.value; renderTable(); });
  $("#sort").addEventListener("change", (ev) => { state.sort = ev.target.value; renderTable(); });
  $("#chips").addEventListener("click", (ev) => {
    const b = ev.target.closest(".chip");
    if (!b) return;
    const on = !state.features.has(b.dataset.f);
    if (on) state.features.add(b.dataset.f); else state.features.delete(b.dataset.f);
    b.setAttribute("aria-pressed", String(on));
    renderTable();
  });
}

fetch("data.json")
  .then((r) => r.json())
  .then((data) => {
    DATA = data;
    const repo = `https://github.com/${data.repo}`;
    $("#repo-link").href = repo;
    $("#contribute-link").href = `${repo}/blob/main/CONTRIBUTING.md`;
    $("#issue-link").href = `${repo}/issues/new/choose`;
    readHash();
    renderStats();
    renderControls();
    syncControls();
    bind();
    renderTable();
    renderMetrics();
  })
  .catch((err) => {
    $("#count").textContent = `Could not load data.json (${err}). Serve the docs/ folder over HTTP.`;
  });
