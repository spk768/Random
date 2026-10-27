"use strict";

// ------------------------------------------------------------------ util
const TOKEN = (() => {
  const m = location.hash.match(/t=([\w-]+)/);
  if (m) {
    sessionStorage.setItem("token", m[1]);
    history.replaceState(null, "", location.pathname);
  }
  return sessionStorage.getItem("token") || "";
})();

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
// Usado dentro de atributos style="..." — por isso aspas simples e sem aspas na URL.
const cssUrl = (u) => `url('${String(u).replace(/["'\\\n<>]/g, (c) => encodeURIComponent(c))}')`;

async function api(path, { method = "GET", body, raw, headers = {} } = {}) {
  const opts = { method, headers: { "X-Token": TOKEN, ...headers } };
  if (raw !== undefined) opts.body = raw;
  else if (body !== undefined) {
    opts.body = JSON.stringify(body);
    opts.headers["Content-Type"] = "application/json";
  }
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Erro ${res.status}`);
  return data;
}

function fmtNum(n) {
  if (n >= 1e6) return (n / 1e6).toFixed(n >= 1e7 ? 0 : 1).replace(".0", "") + "M";
  if (n >= 1e3) return (n / 1e3).toFixed(n >= 1e4 ? 0 : 1).replace(".0", "") + "K";
  return String(n);
}
function fmtPlaytime(sec) {
  if (!sec || sec < 60) return "0 min";
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
  return h ? `${h} h ${m} min` : `${m} min`;
}
function timeAgo(ts) {
  if (!ts) return "Nunca";
  const d = (Date.now() / 1000 - ts);
  if (d < 60) return "Agora";
  if (d < 3600) return `Há ${Math.floor(d / 60)} min`;
  if (d < 86400) return `Há ${Math.floor(d / 3600)} h`;
  if (d < 86400 * 30) return `Há ${Math.floor(d / 86400)} dia(s)`;
  return new Date(ts * 1000).toLocaleDateString("pt-BR");
}
function fmtSize(b) {
  if (b >= 1048576) return (b / 1048576).toFixed(1) + " MB";
  return Math.max(1, Math.round(b / 1024)) + " KB";
}
function hashHue(s) {
  let h = 0;
  for (const c of String(s)) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  return h % 360;
}
function initials(name) {
  return String(name).split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase() || "?";
}
/** Estilo de fundo para a arte de uma instância/projeto (imagem ou gradiente). */
function artStyle(name, url) {
  if (url) return `background-image:${cssUrl(url)}`;
  const h = hashHue(name);
  return `background-image:linear-gradient(135deg,hsl(${h} 65% 45%),hsl(${(h + 50) % 360} 70% 28%))`;
}
function art(name, url, cls = "thumb") {
  return `<div class="${cls}" style="${artStyle(name, url)}">${url ? "" : esc(initials(name))}</div>`;
}

// ------------------------------------------------------------------ ícones
const I = {
  play: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.5-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z"/></svg>',
  stop: '<svg viewBox="0 0 24 24" fill="currentColor"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>',
  plus: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>',
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
  gear: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>',
  folder: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
  more: '<svg viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="2"/><circle cx="12" cy="12" r="2"/><circle cx="19" cy="12" r="2"/></svg>',
  download: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 4v11m0 0-4-4m4 4 4-4M5 20h14"/></svg>',
  upload: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 16V5m0 0-4 4m4-4 4 4M5 20h14"/></svg>',
  heart: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1-1.1a5.5 5.5 0 0 0-7.8 7.8l1 1.1L12 21l7.8-7.5 1-1.1a5.5 5.5 0 0 0 0-7.8z"/></svg>',
  clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
  trash: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>',
  refresh: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 11a8 8 0 0 0-14.9-3M4 4v4h4M4 13a8 8 0 0 0 14.9 3M20 20v-4h-4"/></svg>',
  x: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>',
  external: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>',
  copy: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a1 1 0 0 1 1-1h10"/></svg>',
  cube: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"><path d="M12 2 3 7v10l9 5 9-5V7z"/><path d="m3 7 9 5 9-5M12 12v10"/></svg>',
  user: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg>',
  calendar: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>',
};

// ------------------------------------------------------------------ estado
const S = {
  data: null,
  view: "library",
  instanceId: null,
  instTab: "overview",
  detail: null,
  sidebarFilter: "",
  tasks: {},
  explore: { source: localStorage.getItem("source") || "modrinth", q: "", mc: "", loader: "", type: "modpack", target: null, hits: [], total: 0, offset: 0, loading: false, seq: 0 },
  mcVersions: null,
};
const LOADER_LABEL = { vanilla: "Vanilla", fabric: "Fabric", quilt: "Quilt", forge: "Forge", neoforge: "NeoForge" };
const TYPE_LABEL = { modpack: "Modpacks", mod: "Mods", resourcepack: "Resource packs", shader: "Shaders" };

function inst(id) { return S.data?.instances.find((i) => i.id === id); }
function runningTask(id) { return Object.values(S.tasks).find((t) => t.instance === id && t.status === "running"); }

async function refresh() {
  S.data = await api("/api/state");
  for (const t of S.data.tasks) S.tasks[t.id] = t;
  renderChrome();
  if (S.view === "instance") {
    if (!inst(S.instanceId)) return go("library");
    await loadDetail();
  }
  if (S.view !== "explore") renderView();
}

async function loadDetail() {
  try {
    S.detail = await api(`/api/instances/${S.instanceId}`);
  } catch (e) {
    S.detail = null;
  }
}

function go(view, opts = {}) {
  S.view = view;
  if (view === "instance") {
    S.instanceId = opts.id;
    S.instTab = opts.tab || "overview";
    S.detail = null;
    renderChrome();
    renderView();
    loadDetail().then(renderView);
    return;
  }
  if (view === "explore") {
    const ex = S.explore;
    const target = opts.target ? inst(opts.target) : null;
    ex.target = target ? target.id : null;
    ex.type = target ? (opts.type || "mod") : "modpack";
    if (target && target.pack.source === "curseforge") ex.source = "curseforge";
    if (target) { ex.mc = target.minecraft; ex.loader = target.loader === "vanilla" ? "" : target.loader; }
    else if (opts.reset !== false) { ex.mc = ""; ex.loader = ""; }
    renderChrome();
    renderView();
    search(true);
    return;
  }
  renderChrome();
  renderView();
  $("#view").scrollTop = 0;
}

// ------------------------------------------------------------------ chrome
function renderChrome() {
  const d = S.data;
  if (!d) return;
  document.querySelectorAll("#nav button").forEach((b) => {
    const active = b.dataset.nav === S.view || (b.dataset.nav === "library" && S.view === "instance");
    b.classList.toggle("active", active && !(S.view === "explore" && S.explore.target));
  });
  // conta
  const acc = d.accounts.find((a) => a.uuid === d.default_account);
  $("#btn-account").innerHTML = acc
    ? `${avatar(acc)}<span>${esc(acc.name)}</span>`
    : `<span class="avatar" style="background:var(--surface-3)">${I.user}</span><span>Adicionar conta</span>`;
  // sidebar
  const f = S.sidebarFilter.toLowerCase();
  const list = d.instances.filter((i) => i.name.toLowerCase().includes(f));
  const item = (i) => `
    <div class="side-item ${S.view === "instance" && S.instanceId === i.id ? "active" : ""}" data-act="open-instance" data-id="${esc(i.id)}">
      ${art(i.name, i.pack.icon_url)}
      <div class="info"><div class="name">${esc(i.name)}</div><div class="meta">${esc(i.minecraft)} · ${esc(i.loader_label)}</div></div>
      ${i.running ? '<span class="dot" title="Em execução"></span>' : `<button class="quick-play" data-act="play" data-id="${esc(i.id)}" title="Jogar">${I.play}</button>`}
    </div>`;
  const recent = list.filter((i) => i.last_played).slice(0, 3);
  let html = "";
  if (recent.length && !f) html += `<div class="sidebar-group">Recentes</div>${recent.map(item).join("")}`;
  html += `<div class="sidebar-group">Instâncias (${list.length})</div>${list.map(item).join("")}`;
  if (!d.instances.length) html += `<div class="faint" style="padding:8px">Nenhuma instância ainda.</div>`;
  $("#sidebar-list").innerHTML = html;
  renderTasks();
}

function avatar(acc, size = "") {
  const h = hashHue(acc.name);
  const fallback = `<span class="avatar ${size}" style="background:hsl(${h} 55% 40%)">${esc(acc.name[0].toUpperCase())}</span>`;
  if (acc.type !== "msa") return fallback;
  return `<span class="avatar ${size}" style="background:hsl(${h} 55% 40%)"><img src="https://mc-heads.net/avatar/${esc(acc.uuid)}/64" alt="" onerror="this.replaceWith(document.createTextNode('${esc(acc.name[0].toUpperCase())}'))"></span>`;
}

function renderTasks() {
  const tasks = Object.values(S.tasks).filter((t) => t.status === "running" || t.status === "error").slice(-4);
  $("#tasks").innerHTML = tasks.map((t) => {
    const pct = t.total ? Math.round((t.done / t.total) * 100) : 0;
    return `<div class="task ${t.status}">
      <div class="task-title"><span>${esc(t.title)}</span>${t.status === "error" ? `<button class="icon-btn" style="width:20px;height:20px" data-act="dismiss-task" data-id="${t.id}">${I.x}</button>` : t.total ? `<span>${pct}%</span>` : ""}</div>
      <div class="task-msg" title="${esc(t.message)}">${esc(t.message || "Aguarde...")}</div>
      ${t.status === "running" ? `<div class="bar ${t.total ? "" : "indeterminate"}"><i style="width:${t.total ? pct : 35}%"></i></div>` : ""}
    </div>`;
  }).join("");
}

// ------------------------------------------------------------------ views
function renderView() {
  const v = $("#view");
  if (!S.data) { v.innerHTML = `<div class="center"><span class="spin"></span></div>`; return; }
  if (S.view === "library") v.innerHTML = viewLibrary();
  else if (S.view === "instance") v.innerHTML = viewInstance();
  else if (S.view === "explore") v.innerHTML = viewExplore();
  if (S.view === "instance" && S.instTab === "logs") {
    const c = $("#console");
    if (c) c.scrollTop = c.scrollHeight;
  }
}

function card(i) {
  const task = runningTask(i.id);
  const pct = task && task.total ? Math.round((task.done / task.total) * 100) : null;
  return `<div class="card ${i.running ? "running" : ""}" data-act="open-instance" data-id="${esc(i.id)}">
    <div class="card-img" style="${artStyle(i.name, i.pack.icon_url)}">
      ${i.pack.icon_url ? "" : `<span style="position:relative;z-index:1;font-weight:800">${esc(initials(i.name))}</span>`}
      ${task ? `<div class="card-progress"><div class="bar ${pct === null ? "indeterminate" : ""}"><i style="width:${pct ?? 35}%"></i></div></div>` : ""}
      <button class="play" data-act="${i.running ? "stop" : "play"}" data-id="${esc(i.id)}" title="${i.running ? "Fechar" : "Jogar"}">${i.running ? I.stop : I.play}</button>
      <div class="card-badge">${i.running ? '<span class="pill green">Jogando</span>' : ""}<span class="pill">${esc(i.loader_label)}</span></div>
    </div>
    <div class="card-name" title="${esc(i.name)}">${esc(i.name)}</div>
    <div class="card-meta">Minecraft ${esc(i.minecraft)}${i.pack.version_number ? " · v" + esc(i.pack.version_number) : ""}</div>
  </div>`;
}

function viewLibrary() {
  const list = S.data.instances;
  if (!list.length) {
    return `<div class="page"><div class="page-head"><h1>Biblioteca</h1></div>
      <div class="empty">${I.cube.replace("<svg", '<svg style="width:54px;height:54px;color:var(--text-3)"')}
        <h2>Sua biblioteca está vazia</h2>
        <div>Instale um modpack do Modrinth com um clique ou crie sua própria instância.</div>
        <button class="btn primary big" data-act="nav" data-nav="explore">${I.search} Explorar modpacks</button>
        <button class="btn big" data-act="add-instance">${I.plus} Criar instância</button>
      </div></div>`;
  }
  const recent = [...list].filter((i) => i.last_played).sort((a, b) => b.last_played - a.last_played).slice(0, 6);
  const all = [...list].sort((a, b) => a.name.localeCompare(b.name));
  return `<div class="page">
    <div class="page-head"><h1>Biblioteca</h1><div class="grow"></div>
      <button class="btn" data-act="import">${I.upload} Importar .mrpack</button>
      <button class="btn primary" data-act="nav" data-nav="explore">${I.search} Explorar modpacks</button>
    </div>
    ${recent.length ? `<h2 class="section">Jogados recentemente</h2><div class="grid">${recent.map(card).join("")}</div>` : ""}
    <h2 class="section">Todas as instâncias</h2>
    <div class="grid">${all.map(card).join("")}
      <div class="card add" data-act="add-instance"><div class="card-img">${I.plus}</div><div class="card-name faint">Adicionar instância</div></div>
    </div>
  </div>`;
}

function viewInstance() {
  const i = inst(S.instanceId);
  if (!i) return "";
  const d = S.detail;
  const task = runningTask(i.id);
  const tabs = [["overview", "Visão geral"], ["mods", `Mods <span class="count">${i.mods_total}</span>`], ["logs", "Logs"], ["settings", "Configurações"]];
  const playBtn = i.running
    ? `<button class="btn red big" data-act="stop" data-id="${esc(i.id)}">${I.stop} Fechar</button>`
    : task
      ? `<button class="btn big" disabled><span class="spin"></span> ${task.total ? Math.round(task.done / task.total * 100) + "%" : "Preparando"}</button>`
      : `<button class="btn green big" data-act="play" data-id="${esc(i.id)}">${I.play} Jogar</button>`;
  let body = `<div class="center"><span class="spin"></span></div>`;
  if (d) {
    if (S.instTab === "overview") body = tabOverview(i, d);
    if (S.instTab === "mods") body = tabMods(i, d);
    if (S.instTab === "logs") body = tabLogs(d);
    if (S.instTab === "settings") body = tabSettings(i);
  }
  return `<div class="hero">
      <div class="hero-bg" style="${artStyle(i.name, i.pack.banner_url || i.pack.icon_url)}"></div>
      <div class="hero-inner">
        ${art(i.name, i.pack.icon_url)}
        <div class="grow">
          <h1>${esc(i.name)}</h1>
          <div class="badges">
            <span class="badge">${I.cube} Minecraft ${esc(i.minecraft)}</span>
            <span class="badge">${esc(i.loader_label)}${i.loader_version ? " " + esc(i.loader_version) : ""}</span>
            ${i.pack.title ? `<span class="badge">${I.download} ${esc(i.pack.title)} ${esc(i.pack.version_number || "")}</span>` : ""}
            ${i.running ? '<span class="badge" style="color:var(--green)"><span class="dot"></span> Em execução</span>' : ""}
          </div>
        </div>
        <div class="hero-actions">
          <button class="icon-btn" data-act="open-folder" data-id="${esc(i.id)}" title="Abrir pasta">${I.folder}</button>
          <button class="icon-btn" data-act="instance-menu" data-id="${esc(i.id)}" title="Mais">${I.more}</button>
          ${playBtn}
        </div>
      </div>
    </div>
    <div class="subtabs">${tabs.map(([k, l]) => `<button class="${S.instTab === k ? "active" : ""}" data-act="inst-tab" data-tab="${k}">${l}</button>`).join("")}</div>
    <div class="page">${body}</div>`;
}

function tabOverview(i, d) {
  const cf = i.pack.source === "curseforge";
  const missing = (i.pack.missing || []).length ? `<div class="panel" style="margin-top:10px;border-color:rgba(245,158,11,.5)">
      <b style="color:var(--yellow)">${i.pack.missing.length} arquivo(s) precisam ser baixados manualmente</b>
      <div class="faint" style="margin:4px 0 8px">O autor desses mods não permite download por launchers. Baixe-os no CurseForge e coloque na pasta mods.</div>
      ${i.pack.missing.map((m) => `<div style="display:flex;gap:8px;align-items:center;padding:3px 0"><span style="flex:1">${esc(m.name)} <span class="faint">${esc(m.file || "")}</span></span>${m.url ? `<button class="btn ghost" data-act="open-url" data-url="${esc(m.url)}">${I.external} Abrir</button>` : ""}</div>`).join("")}
      <button class="btn" style="margin-top:8px" data-act="open-folder" data-id="${esc(i.id)}" data-sub="mods">${I.folder} Abrir pasta mods</button></div>` : "";
  const pack = (i.pack.source === "modrinth" || cf) ? `
    <h2 class="section">Modpack</h2>
    <div class="panel"><div class="panel-row">
      ${art(i.pack.title || i.name, i.pack.icon_url)}
      <div style="flex:1;min-width:0">
        <div style="font-weight:700;font-size:16px">${esc(i.pack.title || i.name)}</div>
        <div class="muted">Versão instalada: <b>${esc(i.pack.version_number || "?")}</b></div>
        <div class="faint" id="update-status"></div>
      </div>
      <button class="btn ghost" data-act="open-url" data-url="${esc(cf ? (i.pack.url || "https://www.curseforge.com/minecraft/modpacks/" + (i.pack.slug || "")) : "https://modrinth.com/modpack/" + (i.pack.slug || i.pack.project_id))}">${I.external} ${cf ? "CurseForge" : "Modrinth"}</button>
      <button class="btn" data-act="check-update" data-id="${esc(i.id)}">${I.refresh} Verificar atualização</button>
    </div></div>${missing}` : i.pack.source === "file" ? `
    <h2 class="section">Modpack</h2><div class="panel muted">Importado de arquivo ${i.pack.format === "curseforge" ? ".zip do CurseForge" : ".mrpack"}${i.pack.title ? ` — <b>${esc(i.pack.title)}</b> ${esc(i.pack.version_number || "")}` : ""}.</div>${missing}` : "";
  const folders = [["", "Pasta do jogo"], ["mods", "Mods"], ["config", "Config"], ["saves", "Mundos"], ["resourcepacks", "Resource packs"], ["shaderpacks", "Shaders"], ["screenshots", "Screenshots"]];
  return `<div class="stats">
      <div class="stat"><div class="label">Tempo de jogo</div><div class="value">${fmtPlaytime(i.playtime)}</div></div>
      <div class="stat"><div class="label">Última vez</div><div class="value">${timeAgo(i.last_played)}</div></div>
      <div class="stat"><div class="label">Mods ativos</div><div class="value">${i.mods_enabled} <span class="faint" style="font-size:14px">/ ${i.mods_total}</span></div></div>
      <div class="stat"><div class="label">Memória</div><div class="value">${(i.effective_memory / 1024).toFixed(1).replace(".0", "")} GB</div></div>
    </div>
    ${pack}
    <h2 class="section">Pastas</h2>
    <div class="folder-grid">${folders.map(([sub, l]) => `<button class="btn" data-act="open-folder" data-id="${esc(i.id)}" data-sub="${sub}">${I.folder} ${l}</button>`).join("")}</div>
    <h2 class="section">Conteúdo</h2>
    <div class="folder-grid">
      <button class="btn" data-act="browse-for" data-id="${esc(i.id)}" data-type="mod" ${i.loader === "vanilla" ? "disabled" : ""}>${I.plus} Adicionar mods</button>
      <button class="btn" data-act="browse-for" data-id="${esc(i.id)}" data-type="resourcepack">${I.plus} Resource packs</button>
      <button class="btn" data-act="browse-for" data-id="${esc(i.id)}" data-type="shader">${I.plus} Shaders</button>
    </div>`;
}

function tabMods(i, d) {
  const f = (S.modFilter || "").toLowerCase();
  const mods = d.mods.filter((m) => m.file.toLowerCase().includes(f));
  const rows = mods.map((m) => `<div class="row ${m.enabled ? "" : "disabled"}">
      <label class="switch"><input type="checkbox" ${m.enabled ? "checked" : ""} data-act="toggle-mod" data-file="${esc(m.file)}"><span></span></label>
      <div class="file" title="${esc(m.file)}">${esc(m.file.replace(/\.disabled$/, ""))}</div>
      <span class="tag ${m.from_pack ? "pack" : ""}">${m.from_pack ? "Modpack" : "Manual"}</span>
      <span class="size">${fmtSize(m.size)}</span>
      <button class="icon-btn" data-act="delete-mod" data-file="${esc(m.file)}" title="Remover">${I.trash}</button>
    </div>`).join("");
  return `<div class="toolbar">
      <label class="search"><span class="search-icon">${I.search}</span><input id="mod-filter" placeholder="Buscar nos ${d.mods.length} mods" value="${esc(S.modFilter || "")}"></label>
      <button class="btn" data-act="open-folder" data-id="${esc(i.id)}" data-sub="mods">${I.folder} Pasta</button>
      <button class="btn primary" data-act="browse-for" data-id="${esc(i.id)}" data-type="mod" ${i.loader === "vanilla" ? "disabled title='Instâncias vanilla não usam mods'" : ""}>${I.plus} Adicionar mods</button>
    </div>
    ${d.mods.length ? `<div class="table">${rows || '<div class="row faint">Nenhum mod corresponde à busca.</div>'}</div>`
      : `<div class="empty"><h2>Nenhum mod</h2><div>Adicione mods do Modrinth ou coloque arquivos .jar na pasta mods.</div></div>`}
    <div class="faint" style="margin-top:10px">Mods desativados continuam desativados quando o modpack é atualizado.</div>`;
}

function logClass(line) {
  if (/\b(ERROR|FATAL|Exception|Erro)\b/.test(line)) return "err";
  if (/\bWARN\b/.test(line)) return "warn";
  if (/^(Preparando|Verificando|Iniciando|Baixando|Instalando)/.test(line)) return "info";
  return "";
}
function tabLogs(d) {
  return `<div class="toolbar"><div class="grow muted" style="flex:1">Saída do jogo e do launcher</div>
      <button class="btn" data-act="copy-logs">${I.copy} Copiar</button>
      <button class="btn" data-act="open-folder" data-id="${esc(S.instanceId)}" data-sub="logs">${I.folder} Logs do jogo</button></div>
    <div class="console" id="console">${d.logs.map((l) => `<div class="${logClass(l)}">${esc(l)}</div>`).join("") || '<span class="faint">Nenhum log ainda. Inicie o jogo para ver a saída aqui.</span>'}</div>`;
}

function tabSettings(i) {
  const mem = i.memory_mb || S.data.settings.default_memory_mb;
  return `<form class="form" id="inst-settings">
    <div class="field"><label>Nome</label><input class="input" name="name" value="${esc(i.name)}"></div>
    <div class="field"><label>Memória</label>
      <div class="range-row"><input type="range" name="memory_mb" min="1024" max="32768" step="512" value="${mem}" data-act="mem-range">
      <span class="value" id="mem-value">${(mem / 1024).toFixed(1)} GB</span></div>
      <div class="hint">Padrão global: ${(S.data.settings.default_memory_mb / 1024).toFixed(1)} GB. Modpacks grandes costumam precisar de 6–8 GB.</div></div>
    <div class="field"><label>Java</label><input class="input" name="java_path" value="${esc(i.java_path)}" placeholder="Automático (recomendado)">
      <div class="hint">Deixe vazio para o launcher escolher/baixar a versão certa do Java.</div></div>
    <div class="field"><label>Argumentos JVM extras</label><input class="input" name="jvm_args" value="${esc(i.jvm_args)}" placeholder="-XX:+UseG1GC"></div>
    <div class="field"><label>Resolução da janela</label><div class="row2">
      <input class="input" name="width" type="number" min="0" value="${i.width || ""}" placeholder="Largura (padrão)">
      <input class="input" name="height" type="number" min="0" value="${i.height || ""}" placeholder="Altura (padrão)"></div></div>
    <div><button class="btn primary" type="submit">Salvar alterações</button></div>
  </form>`;
}

function viewExplore() {
  const ex = S.explore;
  const target = ex.target ? inst(ex.target) : null;
  const loaders = ["", "fabric", "quilt", "forge", "neoforge"];
  const versions = S.mcVersions || [];
  const results = ex.hits.map(resultCard).join("");
  const skeletons = ex.loading && !ex.hits.length ? Array(8).fill('<div class="skeleton"></div>').join("") : "";
  return `<div class="page">
    ${target ? `<div class="target-banner">${art(target.name, target.pack.icon_url)}<div class="grow">Adicionando conteúdo a <b>${esc(target.name)}</b> <span class="faint">(${esc(target.minecraft)} · ${esc(target.loader_label)})</span></div>
      <button class="btn" data-act="open-instance" data-id="${esc(target.id)}">Voltar à instância</button></div>` : ""}
    <div class="page-head"><h1>${target ? "Explorar " + TYPE_LABEL[ex.type].toLowerCase() : "Explorar modpacks"}</h1><div class="grow"></div>
      <div class="seg" style="margin:0;width:280px">${[["modrinth", "Modrinth"], ["curseforge", "CurseForge"]].map(([k, l]) => `<button class="${ex.source === k ? "active" : ""}" data-act="explore-source" data-source="${k}">${l}</button>`).join("")}</div></div>
    ${target ? `<div class="seg" style="max-width:520px">${["mod", "resourcepack", "shader"].map((t) => `<button class="${ex.type === t ? "active" : ""}" data-act="explore-type" data-type="${t}">${TYPE_LABEL[t]}</button>`).join("")}</div>` : ""}
    <div class="filters">
      <label class="search big"><span class="search-icon">${I.search}</span><input id="explore-q" placeholder="Buscar ${TYPE_LABEL[ex.type].toLowerCase()} no ${ex.source === "curseforge" ? "CurseForge" : "Modrinth"}..." value="${esc(ex.q)}" autofocus></label>
      <select class="input" id="explore-mc" ${target ? "disabled" : ""}><option value="">Todas as versões</option>
        ${(ex.mc && !versions.includes(ex.mc) ? [ex.mc] : []).concat(versions).map((v) => `<option ${v === ex.mc ? "selected" : ""}>${esc(v)}</option>`).join("")}</select>
      <select class="input" id="explore-loader" ${target && ex.type === "mod" ? "disabled" : ""}>${loaders.map((l) => `<option value="${l}" ${l === ex.loader ? "selected" : ""}>${l ? LOADER_LABEL[l] : "Todos os loaders"}</option>`).join("")}</select>
    </div>
    <div class="faint" style="margin:-6px 0 12px">${ex.loading && !ex.hits.length ? "Buscando..." : `${fmtNum(ex.total)} resultados`}</div>
    <div class="results">${results}${skeletons}</div>
    ${ex.error ? `<div class="empty"><h2>Não foi possível buscar</h2><div>${esc(ex.error)}</div><button class="btn" data-act="retry-search">${I.refresh} Tentar novamente</button>${ex.source === "curseforge" ? `<button class="btn primary" data-act="open-settings">${I.gear} Configurar API do CurseForge</button>` : ""}</div>` : ""}
    ${!ex.loading && !ex.error && !ex.hits.length ? `<div class="empty"><h2>Nada encontrado</h2><div>Tente outros termos ou remova os filtros.</div></div>` : ""}
    ${ex.hits.length < ex.total ? `<div class="load-more"><button class="btn" data-act="load-more" ${ex.loading ? "disabled" : ""}>${ex.loading ? '<span class="spin"></span>' : "Carregar mais"}</button></div>` : ""}
  </div>`;
}

function resultCard(h) {
  const cats = (h.display_categories || h.categories || []).filter((c) => !LOADER_LABEL[c]).slice(0, 3);
  const loaders = (h.categories || []).filter((c) => LOADER_LABEL[c]).map((c) => LOADER_LABEL[c]);
  const mc = h.versions && h.versions.length ? h.versions[h.versions.length - 1] : "";
  return `<div class="result" data-act="open-project" data-id="${esc(h.project_id)}">
    ${art(h.title, h.icon_url)}
    <div class="info">
      <div class="title">${esc(h.title)}</div>
      <div class="author">por ${esc(h.author)}</div>
      <div class="desc">${esc(h.description)}</div>
      <div class="foot">
        <span>${I.download} ${fmtNum(h.downloads)}</span>
        <span>${I.heart} ${fmtNum(h.follows || 0)}</span>
        ${mc ? `<span>${I.cube} ${esc(mc)}</span>` : ""}
        ${loaders.length ? `<span>${esc(loaders.join(", "))}</span>` : ""}
        <span class="cats">${cats.map((c) => `<span class="cat">${esc(c)}</span>`).join("")}</span>
      </div>
    </div>
    <button class="btn primary install-btn" data-act="quick-install" data-id="${esc(h.project_id)}">${I.download} ${S.explore.target ? "Adicionar" : "Instalar"}</button>
  </div>`;
}

// ------------------------------------------------------------------ busca
let searchTimer;
async function search(reset) {
  const ex = S.explore;
  if (reset) { ex.offset = 0; ex.hits = []; ex.total = 0; }
  ex.loading = true;
  ex.error = null;
  const seq = ++ex.seq;
  renderExplore();
  const params = new URLSearchParams({ source: ex.source, q: ex.q, type: ex.type, mc: ex.mc, loader: ex.type === "modpack" || ex.type === "mod" ? ex.loader : "", offset: ex.offset, limit: 24 });
  try {
    const res = await api(`/api/search?${params}`);
    if (seq !== ex.seq) return;
    ex.hits = ex.hits.concat(res.hits);
    ex.total = res.total_hits;
  } catch (e) {
    if (seq !== ex.seq) return;
    ex.error = e.message;
  }
  ex.loading = false;
  renderExplore();
}

/** Redesenha o explorador sem tirar o foco/cursor do campo de busca. */
function renderExplore() {
  if (S.view !== "explore") return;
  const active = document.activeElement;
  const typing = active?.id === "explore-q";
  const start = typing ? active.selectionStart : 0;
  const end = typing ? active.selectionEnd : 0;
  const scroll = $("#view").scrollTop;
  renderView();
  $("#view").scrollTop = scroll;
  if (typing) {
    const el = $("#explore-q");
    el.value = S.explore.q;
    el.focus();
    el.setSelectionRange(start, end);
  }
}

async function loadMcVersions() {
  if (S.mcVersions) return S.mcVersions;
  try { S.mcVersions = await api("/api/mc-versions"); } catch { S.mcVersions = []; }
  return S.mcVersions;
}

// ------------------------------------------------------------------ modais
function modal(html, { wide = false, onClose } = {}) {
  const root = document.createElement("div");
  root.className = "overlay";
  root.innerHTML = `<div class="modal ${wide ? "wide" : ""}">${html}</div>`;
  const close = () => { root.remove(); onClose && onClose(); };
  root.addEventListener("mousedown", (e) => { if (e.target === root) close(); });
  root.querySelectorAll("[data-close]").forEach((b) => b.addEventListener("click", close));
  $("#modal-root").appendChild(root);
  root.close = close;
  return root;
}
const head = (title) => `<div class="modal-head"><h3>${title}</h3><button class="icon-btn" data-close>${I.x}</button></div>`;

function toast(msg, type = "", ms = 4500) {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.innerHTML = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), ms);
}
const fail = (e) => toast(esc(e.message || e), "error", 7000);

function confirmDialog(title, text, okLabel = "Confirmar", danger = false) {
  return new Promise((resolve) => {
    const m = modal(`${head(esc(title))}<div class="modal-body muted">${text}</div>
      <div class="modal-foot"><button class="btn" data-close>Cancelar</button><button class="btn ${danger ? "red" : "primary"}" id="ok">${esc(okLabel)}</button></div>`,
      { onClose: () => resolve(false) });
    $("#ok", m).addEventListener("click", () => { resolve(true); m.remove(); });
  });
}

function promptDialog(title, label, value = "") {
  return new Promise((resolve) => {
    const m = modal(`${head(esc(title))}<form class="modal-body"><div class="field"><label>${esc(label)}</label><input class="input" id="pv" value="${esc(value)}"></div></form>
      <div class="modal-foot"><button class="btn" data-close>Cancelar</button><button class="btn primary" id="ok">OK</button></div>`,
      { onClose: () => resolve(null) });
    const input = $("#pv", m);
    input.focus();
    input.select();
    const ok = () => { resolve(input.value.trim() || null); m.remove(); };
    $("#ok", m).addEventListener("click", ok);
    $("form", m).addEventListener("submit", (e) => { e.preventDefault(); ok(); });
  });
}

// ---- nova instância
async function addInstanceModal(tab = "custom") {
  const m = modal(`${head("Adicionar instância")}
    <div class="modal-body">
      <div class="seg"><button data-tab="custom">Personalizada</button><button data-tab="import">Importar arquivo</button><button data-tab="explore">Modrinth / CurseForge</button></div>
      <div id="tab-custom">
        <div class="form">
          <div class="field"><label>Nome</label><input class="input" id="ni-name" value="Nova instância"></div>
          <div class="field"><label>Versão do Minecraft</label>
            <div class="row2"><select class="input" id="ni-mc"><option>Carregando...</option></select>
            <label class="muted" style="display:flex;gap:8px;align-items:center"><input type="checkbox" id="ni-snap"> Mostrar snapshots</label></div></div>
          <div class="field"><label>Mod loader</label><div class="loader-pick">${Object.entries(LOADER_LABEL).map(([k, l]) => `<button type="button" data-loader="${k}" class="${k === "fabric" ? "active" : ""}">${l}</button>`).join("")}</div></div>
          <div class="field" id="ni-lv-field"><label>Versão do loader</label><select class="input" id="ni-lv"></select></div>
        </div>
      </div>
      <div id="tab-import" hidden>
        <label class="dropzone" id="dz">${I.upload.replace("<svg", '<svg style="width:40px;height:40px"')}<div style="margin-top:8px;font-weight:600">Arraste um .mrpack (Modrinth) ou .zip (CurseForge) aqui</div><div class="faint">ou clique para escolher</div>
          <input type="file" accept=".mrpack,.zip" hidden id="ni-file"></label>
        <div class="faint" style="margin-top:10px">Dica: você também pode arrastar um .mrpack para qualquer lugar da janela.</div>
      </div>
    </div>
    <div class="modal-foot" id="ni-foot"><button class="btn" data-close>Cancelar</button><button class="btn primary" id="ni-create">Criar instância</button></div>`);
  let loader = "fabric";
  const setTab = (t) => {
    if (t === "explore") { m.close(); go("explore"); return; }
    m.querySelectorAll(".seg button").forEach((b) => b.classList.toggle("active", b.dataset.tab === t));
    $("#tab-custom", m).hidden = t !== "custom";
    $("#tab-import", m).hidden = t !== "import";
    $("#ni-foot", m).hidden = t !== "custom";
  };
  m.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));
  setTab(tab);

  const mcSel = $("#ni-mc", m), lvSel = $("#ni-lv", m);
  const loadLoaderVersions = async () => {
    $("#ni-lv-field", m).hidden = loader === "vanilla";
    if (loader === "vanilla") return;
    lvSel.innerHTML = "<option>Carregando...</option>";
    const want = [loader, mcSel.value];
    try {
      const vs = await api(`/api/loader-versions?loader=${loader}&mc=${encodeURIComponent(mcSel.value)}`);
      if (want[0] !== loader || want[1] !== mcSel.value) return;
      lvSel.innerHTML = vs.length ? vs.slice(0, 60).map((v) => `<option>${esc(v)}</option>`).join("") : `<option value="">Indisponível para esta versão</option>`;
    } catch (e) { lvSel.innerHTML = `<option value="">Erro: ${esc(e.message)}</option>`; }
  };
  const loadMc = async (snap) => {
    mcSel.innerHTML = "<option>Carregando...</option>";
    try {
      const vs = snap ? await api("/api/mc-versions?snapshots=1") : await loadMcVersions();
      mcSel.innerHTML = vs.map((v) => `<option>${esc(v)}</option>`).join("");
    } catch (e) { mcSel.innerHTML = `<option value="">Erro ao carregar</option>`; fail(e); }
    loadLoaderVersions();
  };
  $("#ni-snap", m).addEventListener("change", (e) => loadMc(e.target.checked));
  mcSel.addEventListener("change", loadLoaderVersions);
  m.querySelectorAll(".loader-pick button").forEach((b) => b.addEventListener("click", () => {
    loader = b.dataset.loader;
    m.querySelectorAll(".loader-pick button").forEach((x) => x.classList.toggle("active", x === b));
    loadLoaderVersions();
  }));
  loadMc(false);

  $("#ni-create", m).addEventListener("click", async () => {
    const name = $("#ni-name", m).value.trim();
    if (!name || !mcSel.value) return toast("Informe nome e versão", "error");
    if (loader !== "vanilla" && !lvSel.value) return toast("Nenhuma versão do loader disponível", "error");
    try {
      const r = await api("/api/instances", { method: "POST", body: { name, minecraft: mcSel.value, loader, loader_version: loader === "vanilla" ? null : lvSel.value } });
      m.close();
      await refresh();
      go("instance", { id: r.id });
      toast(`Instância <b>${esc(name)}</b> criada`, "success");
    } catch (e) { fail(e); }
  });
  const file = $("#ni-file", m), dz = $("#dz", m);
  file.addEventListener("change", () => { if (file.files[0]) { importFile(file.files[0]); m.close(); } });
  dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("over"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("over"));
  dz.addEventListener("drop", (e) => { e.preventDefault(); e.stopPropagation(); const f = e.dataTransfer.files[0]; if (f) { importFile(f); m.close(); } });
}

async function importFile(f) {
  if (!/\.(mrpack|zip)$/i.test(f.name)) return toast("Selecione um .mrpack (Modrinth) ou .zip (CurseForge)", "error");
  try {
    const buf = await f.arrayBuffer();
    await api("/api/import", { method: "POST", raw: buf, headers: { "X-Filename": encodeURIComponent(f.name), "Content-Type": "application/octet-stream" } });
    toast(`Importando <b>${esc(f.name)}</b>...`);
  } catch (e) { fail(e); }
}

// ---- projeto do Modrinth
async function projectModal(pid) {
  const ex = S.explore;
  const hit = ex.hits.find((h) => h.project_id === pid) || {};
  const target = ex.target ? inst(ex.target) : null;
  const banner = hit.featured_gallery || (hit.gallery || [])[0];
  const m = modal(`${head(esc(hit.title || "Projeto"))}
    <div class="modal-body" style="padding:0">
      <div class="project-banner" style="${banner ? `background-image:${cssUrl(banner)}` : artStyle(hit.title || pid)}"></div>
      <div style="padding:0 20px 20px">
        <div class="project-head">${art(hit.title || "?", hit.icon_url)}
          <div><div style="font-size:22px;font-weight:800">${esc(hit.title || "")}</div><div class="faint">por ${esc(hit.author || "")} · ${I.download.replace("<svg", '<svg style="width:13px;height:13px;vertical-align:-2px"')} ${fmtNum(hit.downloads || 0)}</div></div></div>
        <div class="muted" id="pm-desc">${esc(hit.description || "")}</div>
        <div class="gallery" id="pm-gallery"></div>
        <div class="field" style="margin-top:12px"><label>Versão</label><select class="input" id="pm-version"><option>Carregando versões...</option></select></div>
        ${!target && hit.project_type !== "mod" ? `<div class="field" style="margin-top:12px"><label>Nome da instância</label><input class="input" id="pm-name" value="${esc(hit.title || "")}"></div>` : ""}
      </div>
    </div>
    <div class="modal-foot">
      <button class="btn ghost" data-act="open-url" data-url="${esc(hit.url || `https://modrinth.com/${hit.project_type || "project"}/${hit.slug || pid}`)}">${I.external} Ver no ${hit.source === "curseforge" ? "CurseForge" : "Modrinth"}</button>
      <div style="flex:1"></div>
      <button class="btn" data-close>Cancelar</button>
      <button class="btn primary" id="pm-install" disabled>${I.download} ${target ? "Adicionar à instância" : "Instalar"}</button>
    </div>`, { wide: true });
  let versions = [];
  try {
    const q = target ? new URLSearchParams({ mc: target.minecraft, ...(ex.type === "mod" ? { loader: target.loader } : {}) }) : "";
    const [proj, vs] = await Promise.all([api(`/api/project/${pid}`), api(`/api/project/${pid}/versions${q ? "?" + q : ""}`)]);
    versions = vs;
    const gal = (proj.gallery || []).slice(0, 10);
    $("#pm-gallery", m).innerHTML = gal.map((g) => `<img src="${esc(g.url)}" alt="${esc(g.title || "")}" data-act="open-url" data-url="${esc(g.raw_url || g.url)}">`).join("");
    $("#pm-version", m).innerHTML = vs.length
      ? vs.map((v) => `<option value="${esc(v.id)}">${esc(v.version_number)} — MC ${esc(v.game_versions.slice(-3).join(", "))} · ${esc(v.loaders.map((l) => LOADER_LABEL[l] || l).join(", "))}${v.version_type !== "release" ? " · " + esc(v.version_type) : ""}</option>`).join("")
      : `<option value="">Nenhuma versão compatível</option>`;
    $("#pm-install", m).disabled = !vs.length;
  } catch (e) {
    $("#pm-version", m).innerHTML = `<option value="">Erro: ${esc(e.message)}</option>`;
  }
  $("#pm-install", m).addEventListener("click", async () => {
    const vid = $("#pm-version", m).value;
    try {
      if (target) {
        await api(`/api/instances/${target.id}/mods/add`, { method: "POST", body: { project: pid, title: hit.title } });
        toast(`Adicionando <b>${esc(hit.title)}</b> a ${esc(target.name)}...`);
      } else {
        const name = $("#pm-name", m)?.value.trim();
        await api("/api/install", { method: "POST", body: { project: pid, version_id: vid, name, title: hit.title } });
        toast(`Instalando <b>${esc(hit.title)}</b>... acompanhe na barra lateral.`);
      }
      m.close();
    } catch (e) { fail(e); }
  });
  return versions;
}

async function quickInstall(pid) {
  const ex = S.explore;
  const hit = ex.hits.find((h) => h.project_id === pid) || {};
  try {
    if (ex.target) {
      await api(`/api/instances/${ex.target}/mods/add`, { method: "POST", body: { project: pid, title: hit.title } });
      toast(`Adicionando <b>${esc(hit.title)}</b>...`);
    } else {
      await api("/api/install", { method: "POST", body: { project: pid, title: hit.title } });
      toast(`Instalando <b>${esc(hit.title)}</b>... acompanhe na barra lateral.`);
    }
  } catch (e) { fail(e); }
}

// ---- contas
let loginModal = null;
function accountsModal() {
  const d = S.data;
  const rows = d.accounts.map((a) => `<div class="acc-row ${a.uuid === d.default_account ? "active" : ""}">
      ${avatar(a)}<div class="grow"><div style="font-weight:700">${esc(a.name)}</div><div class="faint">${a.type === "msa" ? "Conta Microsoft" : "Offline"}</div></div>
      ${a.uuid === d.default_account ? '<span class="pill green">Em uso</span>' : `<button class="btn" data-acc="use" data-uuid="${esc(a.uuid)}">Usar</button>`}
      <button class="icon-btn" data-acc="remove" data-uuid="${esc(a.uuid)}" title="Remover">${I.trash}</button>
    </div>`).join("");
  const m = modal(`${head("Contas")}
    <div class="modal-body">
      ${rows || '<div class="faint" style="margin-bottom:12px">Nenhuma conta adicionada.</div>'}
      <button class="btn primary block" id="acc-ms" style="margin-top:6px">Entrar com conta Microsoft</button>
      <h2 class="section" style="margin-top:20px">Conta offline</h2>
      <form class="row2" id="acc-off" style="grid-template-columns:1fr auto"><input class="input" id="acc-name" placeholder="Nome de jogador" maxlength="16"><button class="btn">Adicionar</button></form>
      <div class="faint" style="margin-top:6px">Contas offline funcionam em singleplayer, LAN e servidores em modo offline.</div>
    </div>`);
  m.querySelectorAll("[data-acc]").forEach((b) => b.addEventListener("click", async () => {
    try {
      await api(`/api/accounts/${b.dataset.acc === "use" ? "default" : "remove"}`, { method: "POST", body: { uuid: b.dataset.uuid } });
      await refresh();
      m.close();
      accountsModal();
    } catch (e) { fail(e); }
  }));
  $("#acc-off", m).addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/api/accounts/offline", { method: "POST", body: { name: $("#acc-name", m).value } });
      await refresh();
      m.close();
      toast("Conta adicionada", "success");
    } catch (err) { fail(err); }
  });
  $("#acc-ms", m).addEventListener("click", async () => {
    try {
      await api("/api/accounts/microsoft", { method: "POST" });
      m.close();
      loginModal = modal(`${head("Entrar com Microsoft")}<div class="modal-body" id="login-body"><div class="center"><span class="spin"></span></div></div>`,
        { onClose: () => { api("/api/accounts/microsoft/cancel", { method: "POST" }); loginModal = null; } });
    } catch (e) { fail(e); }
  });
}

function onLoginEvent(data) {
  if (!loginModal) return;
  if (data.done) {
    const m = loginModal;
    loginModal = null;
    m.remove();
    toast(`Logado como <b>${esc(data.name)}</b>`, "success");
    return;
  }
  $("#login-body", loginModal).innerHTML = `<div class="muted">1. Abra <b>${esc(data.url)}</b><br>2. Digite o código abaixo e entre com sua conta Microsoft.</div>
    <div class="code-box">${esc(data.code)}</div>
    <button class="btn primary block" id="login-open">${I.copy} Copiar código e abrir navegador</button>
    <div class="faint" style="margin-top:12px;display:flex;gap:8px;align-items:center"><span class="spin"></span> Aguardando confirmação...</div>`;
  $("#login-open", loginModal).addEventListener("click", () => {
    navigator.clipboard?.writeText(data.code);
    window.open(data.url, "_blank");
  });
}

// ---- configurações
async function settingsModal() {
  const s = S.data.settings;
  const m = modal(`${head("Configurações")}
    <form class="modal-body form" id="set-form" style="max-width:none">
      <div class="field"><label>Memória padrão</label>
        <div class="range-row"><input type="range" name="default_memory_mb" min="1024" max="32768" step="512" value="${s.default_memory_mb}" data-act="mem-range">
        <span class="value" id="mem-value">${(s.default_memory_mb / 1024).toFixed(1)} GB</span></div></div>
      <div class="field"><label>Downloads simultâneos</label><input class="input" type="number" name="download_workers" min="1" max="32" value="${s.download_workers}"></div>
      <div class="field"><label style="display:flex;gap:8px;align-items:center;font-weight:600"><input type="checkbox" name="auto_download_java" ${s.auto_download_java ? "checked" : ""}> Baixar Java automaticamente</label>
        <div class="hint">Quando não houver o Java exigido pela versão, o launcher baixa o Eclipse Temurin.</div></div>
      <div class="field"><label>Java por versão <span class="faint" id="java-found"></span></label>
        <datalist id="java-list"></datalist>
        ${["8", "17", "21"].map((v) => `<div class="row2" style="grid-template-columns:70px 1fr;margin-bottom:6px;align-items:center"><span class="muted">Java ${v}</span><input class="input" list="java-list" name="java_${v}" value="${esc((s.java_paths || {})[v] || "")}" placeholder="Automático"></div>`).join("")}</div>
      <div class="field"><label>Client ID do Azure (login Microsoft)</label><input class="input" name="msa_client_id" value="${esc(s.msa_client_id || "")}" placeholder="00000000-0000-0000-0000-000000000000">
        <div class="hint">Necessário para contas Microsoft. Veja o README para criar um.</div></div>
      <h2 class="section" style="margin:6px 0 0">CurseForge</h2>
      <div class="field"><label>Chave da API do CurseForge</label><input class="input" type="password" name="curseforge_api_key" value="${esc(s.curseforge_api_key || "")}" placeholder="$2a$10$..." autocomplete="off">
        <div class="hint">Crie uma em <a href="#" data-act="open-url" data-url="https://console.curseforge.com/">console.curseforge.com</a>. Necessária para a API oficial.</div></div>
      <div class="field"><label>URL da API do CurseForge</label><input class="input" name="curseforge_api_url" value="${esc(s.curseforge_api_url || "https://api.curseforge.com")}" placeholder="https://api.curseforge.com">
        <div class="hint">Use uma URL customizada para apontar para um proxy compatível com a API oficial (a chave pode ser opcional nesse caso).</div></div>
      <div class="field"><label>Pasta de dados</label><div class="row2" style="grid-template-columns:1fr auto"><input class="input" value="${esc(S.data.data_dir)}" readonly><button type="button" class="btn" data-act="open-data-dir">${I.folder}</button></div></div>
    </form>
    <div class="modal-foot"><span class="faint" style="margin-right:auto;align-self:center">PackLauncher ${esc(S.data.version)}</span><button class="btn" data-close>Cancelar</button><button class="btn primary" id="set-save">Salvar</button></div>`);
  api("/api/java").then((list) => {
    if (!m.isConnected) return;
    $("#java-list", m).innerHTML = list.map((j) => `<option value="${esc(j.path)}">Java ${j.major}</option>`).join("");
    $("#java-found", m).textContent = list.length ? `(${list.length} encontrado(s) no sistema)` : "";
  }).catch(() => {});
  $("#set-save", m).addEventListener("click", async () => {
    const f = $("#set-form", m);
    const fd = new FormData(f);
    const body = {
      default_memory_mb: +fd.get("default_memory_mb"), download_workers: +fd.get("download_workers"),
      auto_download_java: f.auto_download_java.checked, msa_client_id: fd.get("msa_client_id"),
      curseforge_api_key: fd.get("curseforge_api_key"), curseforge_api_url: fd.get("curseforge_api_url"),
      java_paths: { 8: fd.get("java_8"), 17: fd.get("java_17"), 21: fd.get("java_21") },
    };
    try { await api("/api/settings", { method: "POST", body }); m.close(); toast("Configurações salvas", "success"); }
    catch (e) { fail(e); }
  });
}

// ---- menu de contexto
function menu(anchor, items) {
  document.querySelectorAll(".menu").forEach((x) => x.remove());
  const el = document.createElement("div");
  el.className = "menu";
  el.innerHTML = items.map((it) => it === "-" ? "<hr>" : `<button class="${it.danger ? "danger" : ""}">${it.icon || ""} ${esc(it.label)}</button>`).join("");
  const btns = [...el.querySelectorAll("button")];
  items.filter((it) => it !== "-").forEach((it, idx) => btns[idx].addEventListener("click", () => { el.remove(); it.run(); }));
  document.body.appendChild(el);
  const r = anchor.getBoundingClientRect();
  el.style.top = `${Math.min(r.bottom + 6, innerHeight - el.offsetHeight - 10)}px`;
  el.style.left = `${Math.max(10, r.right - el.offsetWidth)}px`;
  setTimeout(() => document.addEventListener("mousedown", function off(e) {
    if (!el.contains(e.target)) { el.remove(); document.removeEventListener("mousedown", off); }
  }), 0);
}

function instanceMenu(anchor, id) {
  const i = inst(id);
  menu(anchor, [
    { label: "Abrir pasta", icon: I.folder, run: () => act["open-folder"]({ dataset: { id } }) },
    { label: "Adicionar mods", icon: I.plus, run: () => go("explore", { target: id, type: "mod" }) },
    i.pack.source === "modrinth" || i.pack.source === "curseforge" ? { label: "Verificar atualização", icon: I.refresh, run: () => checkUpdate(id) } : null,
    { label: "Duplicar", icon: I.copy, run: async () => { try { const r = await api(`/api/instances/${id}/duplicate`, { method: "POST" }); await refresh(); go("instance", { id: r.id }); } catch (e) { fail(e); } } },
    { label: "Exportar .mrpack", icon: I.upload, run: async () => {
      const v = await promptDialog("Exportar modpack", "Versão do modpack", i.pack.version_number || "1.0.0");
      if (v) { location.href = `/api/instances/${id}/export?version=${encodeURIComponent(v)}&t=${TOKEN}`; toast("Exportando... o download começará em instantes."); }
    } },
    "-",
    { label: "Excluir instância", icon: I.trash, danger: true, run: async () => {
      if (!await confirmDialog("Excluir instância", `Excluir <b>${esc(i.name)}</b>? Mundos, configurações e mods desta instância serão apagados permanentemente.`, "Excluir", true)) return;
      try { await api(`/api/instances/${id}/delete`, { method: "POST" }); go("library"); await refresh(); toast("Instância excluída"); } catch (e) { fail(e); }
    } },
  ].filter(Boolean));
}

async function checkUpdate(id) {
  const status = $("#update-status");
  if (status) status.innerHTML = '<span class="spin" style="width:12px;height:12px;vertical-align:-1px"></span> Verificando...';
  try {
    const { latest } = await api(`/api/instances/${id}/update`);
    if (!latest) {
      if (status) status.textContent = "Você está na versão mais recente.";
      else toast("O modpack já está atualizado", "success");
      return;
    }
    if (status) status.innerHTML = `Nova versão disponível: <b style="color:var(--green)">${esc(latest.version_number)}</b>`;
    if (await confirmDialog("Atualização disponível", `Atualizar para a versão <b>${esc(latest.version_number)}</b>?<br><br>Seus mundos, configurações pessoais (options.txt) e mods desativados são preservados.`, "Atualizar")) {
      await api(`/api/instances/${id}/update`, { method: "POST", body: { version_id: latest.id } });
    }
  } catch (e) {
    if (status) status.textContent = "";
    fail(e);
  }
}

// ------------------------------------------------------------------ ações
const act = {
  nav: (el) => go(el.dataset.nav),
  "open-instance": (el) => go("instance", { id: el.dataset.id }),
  "inst-tab": (el) => { S.instTab = el.dataset.tab; renderView(); },
  "add-instance": () => addInstanceModal(),
  import: () => addInstanceModal("import"),
  play: async (el) => {
    if (!S.data.accounts.length) { toast("Adicione uma conta para jogar", "error"); return accountsModal(); }
    try { const t = await api(`/api/instances/${el.dataset.id}/launch`, { method: "POST" }); S.tasks[t.id] = t; renderChrome(); renderView(); }
    catch (e) { fail(e); }
  },
  stop: async (el) => {
    if (await confirmDialog("Fechar o jogo", "Forçar o fechamento do Minecraft? O progresso não salvo será perdido.", "Fechar", true))
      api(`/api/instances/${el.dataset.id}/stop`, { method: "POST" }).catch(fail);
  },
  "open-folder": (el) => api(`/api/instances/${el.dataset.id}/open-folder`, { method: "POST", body: { sub: el.dataset.sub || "" } }).catch(fail),
  "open-data-dir": () => api("/api/open-data-dir", { method: "POST" }).catch(fail),
  "instance-menu": (el) => instanceMenu(el, el.dataset.id),
  "check-update": (el) => checkUpdate(el.dataset.id),
  "browse-for": (el) => go("explore", { target: el.dataset.id, type: el.dataset.type }),
  "explore-type": (el) => { S.explore.type = el.dataset.type; search(true); },
  "explore-source": (el) => { S.explore.source = el.dataset.source; try { localStorage.setItem("source", el.dataset.source); } catch {} search(true); },
  "open-settings": () => settingsModal(),
  "open-project": (el) => projectModal(el.dataset.id),
  "quick-install": (el) => quickInstall(el.dataset.id),
  "load-more": () => { S.explore.offset = S.explore.hits.length; search(false); },
  "retry-search": () => search(true),
  "open-url": (el) => window.open(el.dataset.url, "_blank"),
  "dismiss-task": (el) => { delete S.tasks[el.dataset.id]; renderTasks(); },
  "delete-mod": async (el) => {
    if (!await confirmDialog("Remover mod", `Remover <b>${esc(el.dataset.file)}</b>?`, "Remover", true)) return;
    try { await api(`/api/instances/${S.instanceId}/mods/delete`, { method: "POST", body: { file: el.dataset.file } }); await refresh(); } catch (e) { fail(e); }
  },
  "copy-logs": () => { navigator.clipboard?.writeText((S.detail?.logs || []).join("\n")); toast("Logs copiados", "success"); },
};

document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-act]");
  if (!el || el.tagName === "INPUT" || el.tagName === "SELECT") return;
  const fn = act[el.dataset.act];
  if (!fn) return;
  e.preventDefault();
  e.stopPropagation();
  fn(el, e);
});

document.addEventListener("change", async (e) => {
  const el = e.target;
  if (el.dataset.act === "toggle-mod") {
    try {
      await api(`/api/instances/${S.instanceId}/mods/toggle`, { method: "POST", body: { file: el.dataset.file, enabled: el.checked } });
      await refresh();
    } catch (err) { fail(err); }
  }
  if (el.id === "explore-mc") { S.explore.mc = el.value; search(true); }
  if (el.id === "explore-loader") { S.explore.loader = el.value; search(true); }
});

document.addEventListener("input", (e) => {
  const el = e.target;
  if (el.id === "explore-q") {
    S.explore.q = el.value;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => search(true), 1000);  // busca 1s após parar de digitar
  }
  if (el.id === "mod-filter") {
    S.modFilter = el.value;
    const pos = el.selectionStart;
    renderView();
    const n = $("#mod-filter"); n.focus(); n.setSelectionRange(pos, pos);
  }
  if (el.id === "sidebar-filter") { S.sidebarFilter = el.value; renderChrome(); }
  if (el.dataset.act === "mem-range") $("#mem-value", el.closest("form")).textContent = (el.value / 1024).toFixed(1) + " GB";
});

document.addEventListener("submit", async (e) => {
  if (e.target.id !== "inst-settings") return;
  e.preventDefault();
  const fd = new FormData(e.target);
  const body = Object.fromEntries(fd.entries());
  try {
    await api(`/api/instances/${S.instanceId}/settings`, { method: "POST", body });
    toast("Configurações salvas", "success");
    await refresh();
  } catch (err) { fail(err); }
});

// arrastar .mrpack para a janela
document.addEventListener("dragover", (e) => e.preventDefault());
document.addEventListener("drop", (e) => {
  e.preventDefault();
  const f = e.dataTransfer?.files?.[0];
  if (f) importFile(f);
});

$("#btn-add-instance").innerHTML = `${I.plus} Adicionar instância`;
$("#btn-add-instance").addEventListener("click", () => addInstanceModal());
$("#btn-settings").innerHTML = I.gear;
$("#btn-settings").addEventListener("click", settingsModal);
$("#btn-account").addEventListener("click", accountsModal);
$(".search-icon").innerHTML = I.search;
document.querySelectorAll("#nav button").forEach((b) => b.addEventListener("click", () => go(b.dataset.nav)));

// ------------------------------------------------------------------ eventos do servidor
function connect() {
  const es = new EventSource(`/api/events?t=${TOKEN}`);
  let stateTimer;
  es.addEventListener("state", () => { clearTimeout(stateTimer); stateTimer = setTimeout(() => refresh().catch(() => {}), 120); });
  es.addEventListener("task", (ev) => {
    const t = JSON.parse(ev.data);
    const prev = S.tasks[t.id];
    S.tasks[t.id] = t;
    renderTasks();
    if (t.status !== "running" && prev?.status === "running") {
      if (t.status === "error") toast(`<b>${esc(t.title)}</b> falhou: ${esc(t.message)}`, "error", 9000);
      else if (/^(Instalando|Importando)/.test(t.title)) toast(`<b>${esc(t.title.replace(/^(Instalando|Importando) /, ""))}</b> pronto para jogar!`, "success");
      else if (/^(Atualizando|Adicionando)/.test(t.title)) toast(`${esc(t.title)} — concluído`, "success");
      if (t.status === "done") setTimeout(() => { delete S.tasks[t.id]; renderTasks(); }, 1500);
    }
    // atualiza barras de progresso nos cards sem re-renderizar a página inteira
    if (t.instance && (S.view === "library" || (S.view === "instance" && S.instanceId === t.instance))) {
      if (!prev || prev.status !== t.status || S.view === "library") renderView();
    }
  });
  es.addEventListener("log", (ev) => {
    const { instance, line } = JSON.parse(ev.data);
    if (S.view !== "instance" || S.instanceId !== instance || !S.detail) return;
    S.detail.logs.push(line);
    const c = $("#console");
    if (!c) return;
    if (c.querySelector(".faint")) c.innerHTML = "";
    const atBottom = c.scrollHeight - c.scrollTop - c.clientHeight < 40;
    const div = document.createElement("div");
    div.className = logClass(line);
    div.textContent = line;
    c.appendChild(div);
    while (c.childElementCount > 3000) c.firstChild.remove();
    if (atBottom) c.scrollTop = c.scrollHeight;
  });
  es.addEventListener("exit", (ev) => {
    const { instance, code } = JSON.parse(ev.data);
    const i = inst(instance);
    if (![0, 1, 130, 143, -15].includes(code)) toast(`<b>${esc(i?.name || "Minecraft")}</b> fechou com erro (código ${code}). Veja a aba Logs.`, "error", 10000);
  });
  es.addEventListener("login", (ev) => onLoginEvent(JSON.parse(ev.data)));
  es.onerror = () => {};
}

// ------------------------------------------------------------------ início
renderView();
refresh().then(() => { loadMcVersions(); }).catch((e) => {
  $("#view").innerHTML = `<div class="page"><div class="empty"><h2>Não foi possível conectar ao launcher</h2><div>${esc(e.message)}</div>
    <div class="faint" style="margin-top:8px">Abra o PackLauncher novamente pelo atalho ou com <code>python -m packlauncher</code>.</div></div></div>`;
});
connect();
