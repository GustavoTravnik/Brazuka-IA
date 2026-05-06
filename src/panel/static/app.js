// ═══════════════════════════════════════════════════════════════════
// COIA PANEL — app.js  (skills, crews, commands, prompts, sprints, execuções)
// ═══════════════════════════════════════════════════════════════════

const CRON_MODELS = ["gemini-1.5-flash", "gemini-1.5-pro"];

// ─── Estado global ───────────────────────────────────────────────
const State = {
  skills:    [],
  mcps:      [],
  crons:     [],
  crews:     [],
  commands:  [],
  prompts:   [],
  sprints:   [],
  executions:[],
  tools:     { native: [], mcp: [] },
  selectedSkills: new Set(),
  // new Set() vazio = nenhum MCP (comportamento padrão — use --mcps para selecionar)
  // null = todos os MCPs
  selectedMcps: new Set(),
  activeTab: "home",
  skillEditor:   { name: null, isNew: false },
  mcpEditor:     { name: null, isNew: false },
  cronEditor:    { name: null, isNew: false, selectedSkills: new Set(), mcpMode: "all", selectedMcps: new Set() },
  commandEditor: { name: null, isNew: false },
  promptEditor:  { name: null, isNew: false },
  crewEditor:    { name: null, isNew: false, agents: [] },
  sprintEditor:  { name: null, isNew: false, tasks: [] },
  currentExecId: null,
  execPollTimer: null,
  execLastLogIdx: 0,
};

// ─── API helper ──────────────────────────────────────────────────
async function api(method, path, body) {
  const opts = { method, headers: { "Content-Type": "application/json" } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch(path, opts);
  if (!r.ok) {
    const err = await r.json().catch(() => ({ error: r.statusText }));
    throw new Error(err.error || r.statusText);
  }
  return r.status === 204 ? null : r.json();
}

// ─── Toast ───────────────────────────────────────────────────────
function toast(msg, type = "ok") {
  const el = document.getElementById("toast");
  el.textContent = msg;
  el.className = "toast show " + type;
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("show"), 3500);
}

function copyCmd() {
  const val = document.getElementById("cmdline").value;
  navigator.clipboard.writeText(val).then(() => toast("Copiado!"));
}

async function launchSession() {
  const cmd = document.getElementById("cmdline").value.trim();
  if (!cmd) { toast("Nenhum comando para iniciar.", "err"); return; }
  try {
    await api("POST", "/api/session/start", { cmd });
    toast("✅ Sessão iniciada no terminal!");
  } catch (e) {
    toast(e.message || "Erro ao abrir terminal.", "err");
  }
}

async function launchSkillBuilder() {
  try {
    await api("POST", "/api/session/start-skill-builder", {});
    toast("🧠 Terminal Skill Builder aberto!");
  } catch (e) {
    toast(e.message || "Erro ao abrir terminal.", "err");
  }
}

async function launchSprintSession(sprintName) {
  try {
    await api("POST", "/api/session/start-sprint", { sprint: sprintName });
    toast(`✅ COIA aberto com contexto da sprint "${sprintName}"!`);
  } catch (e) {
    toast(e.message || "Erro ao abrir sessão.", "err");
  }
}

function launchSprintSessionFromModal() {
  const name = State.sprintEditor?.name;
  if (!name) { toast("Nenhuma sprint carregada.", "err"); return; }
  launchSprintSession(name);
}

function openRunWithCrewModal() {
  const sp = State.sprintEditor;
  if (!sp?.name) { toast("Nenhuma sprint carregada.", "err"); return; }

  // Info da sprint no topo do modal
  const info = document.getElementById("run-crew-sprint-info");
  info.innerHTML = `
    <div class="run-crew-sprint-badge">
      <span class="mgmt-card-icon">🏃</span>
      <span>${esc(sp.name)}</span>
    </div>
  `;

  // Popula select de crews
  const crewSel = document.getElementById("run-crew-select");
  if (!State.crews.length) {
    crewSel.innerHTML = '<option value="">Nenhuma crew disponível</option>';
  } else {
    crewSel.innerHTML = State.crews.map(c => {
      const label       = c.agents_count === 1 ? "1 agente" : `${c.agents_count} agentes`;
      const displayName = c.title || c.name;
      return `<option value="${esc(c.name)}">${esc(displayName)} — ${label}</option>`;
    }).join("");
  }

  // Título sugerido
  document.getElementById("run-crew-title").value = "";

  showModal("modal-run-crew");
}

async function runSprintWithCrew() {
  const sp       = State.sprintEditor;
  const crewName = document.getElementById("run-crew-select").value;
  const title    = document.getElementById("run-crew-title").value.trim();

  if (!sp?.name) { toast("Nenhuma sprint carregada.", "err"); return; }
  if (!crewName) { toast("Selecione uma crew.", "err"); return; }

  const execTitle = title || `${sp.name} × ${crewName}`;

  try {
    // 1. Cria a execução
    const result = await api("POST", "/api/executions", {
      title: execTitle,
      sprint: sp.name,
      crew: crewName,
    });

    toast(`✅ Execução criada — iniciando...`);
    closeModal("modal-run-crew");
    closeModal("modal-sprint");

    // 2. Atualiza estado
    State.executions = await api("GET", "/api/executions");
    if (State.activeTab === "executions") renderExecutionsList();

    // 3. Abre o console e inicia imediatamente
    await openExecConsole(result.id);
    await startExecution();

  } catch (e) {
    toast(e.message || "Erro ao criar execução.", "err");
  }
}

function buildCmd() {
  const skillArr = [...State.selectedSkills];
  const skills = skillArr.length ? ` --skills "[${skillArr.join(",")}]"` : "";

  let mcps = " --no-mcp";
  if (State.selectedMcps === null) {
    // null = todos os MCPs
    mcps = ' --mcps "[all]"';
  } else if (State.selectedMcps.size > 0) {
    // Set com itens = MCPs específicos selecionados
    mcps = ` --mcps "[${[...State.selectedMcps].join(",")}]"`;
  }
  // Set vazio = --no-mcp (default)

  document.getElementById("cmdline").value = `coia${skills}${mcps}`;
}

// ─── Mapeamento: aba → endpoints que ela consome ─────────────────
const TAB_DEPS = {
  home:       ["skills", "mcps"],
  skills:     ["skills"],
  mcps:       ["mcps", "tools"],
  crons:      ["crons", "skills", "mcps"],
  commands:   ["commands"],
  prompts:    ["prompts"],
  crews:      ["crews", "skills", "tools"],
  sprints:    ["sprints"],
  executions: ["executions"],
};

const FETCH_MAP = {
  skills:     () => api("GET", "/api/skills"),
  mcps:       () => api("GET", "/api/mcps"),
  crons:      () => api("GET", "/api/crons"),
  crews:      () => api("GET", "/api/crews"),
  commands:   () => api("GET", "/api/commands"),
  prompts:    () => api("GET", "/api/prompts"),
  sprints:    () => api("GET", "/api/sprints"),
  executions: () => api("GET", "/api/executions"),
  tools:      () => api("GET", "/api/tools"),
};

/** Recarrega do servidor apenas os recursos que a aba ativa consome. */
async function refreshTabData(tab) {
  const deps = TAB_DEPS[tab] || [];
  if (!deps.length) return;
  try {
    const results = await Promise.all(deps.map(d => FETCH_MAP[d]()));
    deps.forEach((d, i) => {
      if (d === "tools") {
        const tools = results[i];
        State.tools = (tools && tools.native) ? tools : { native: tools || [], mcp: [] };
      } else {
        State[d] = results[i];
      }
    });
  } catch (_) { /* falha silenciosa — dados em cache ficam intactos */ }
}

// ─── Tabs ─────────────────────────────────────────────────────────
const TAB_RENDER = {
  home:       renderHome,
  skills:     renderSkillsList,
  mcps:       renderMcpsList,
  crons:      renderCronsList,
  commands:   renderCommandsList,
  prompts:    renderPromptsList,
  crews:      renderCrewsList,
  sprints:    renderSprintsList,
  executions: renderExecutionsList,
};

async function showTab(tab) {
  State.activeTab = tab;
  location.hash = tab;
  document.querySelectorAll(".tab-btn").forEach(b =>
    b.classList.toggle("active", b.dataset.tab === tab)
  );
  document.querySelectorAll(".tab-panel").forEach(p =>
    p.classList.toggle("active", p.id === "tab-" + tab)
  );
  // Renderiza imediatamente com dados em cache, depois atualiza do servidor
  if (TAB_RENDER[tab]) TAB_RENDER[tab]();
  await refreshTabData(tab);
  if (TAB_RENDER[tab]) TAB_RENDER[tab]();
}

// ─── Escape HTML ──────────────────────────────────────────────────
function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

// ─── Modal helpers ────────────────────────────────────────────────
function showModal(id) { document.getElementById(id).classList.add("open"); }
function closeModal(id) { document.getElementById(id).classList.remove("open"); }

// ════════════════════════════════════════════════════════════════════
// TAB HOME
// ════════════════════════════════════════════════════════════════════
function renderHome() {
  // ── Skills ──────────────────────────────────────────────────────
  const grid = document.getElementById("skill-grid");
  grid.innerHTML = "";
  State.skills.forEach(({ name: sk, description }) => {
    const on = State.selectedSkills.has(sk);
    const card = document.createElement("div");
    card.className = "skill-card" + (on ? " selected" : "");
    card.innerHTML = `
      <div class="skill-card-header">
        <span class="skill-dot"></span>
        <span class="skill-name">${esc(sk)}</span>
        ${DEFAULT_SKILLS.includes(sk) ? '<span class="badge-default">padrão</span>' : ""}
      </div>
      ${description ? `<p class="skill-desc">${esc(description)}</p>` : ""}
    `;
    card.addEventListener("click", () => {
      if (State.selectedSkills.has(sk)) State.selectedSkills.delete(sk);
      else State.selectedSkills.add(sk);
      renderHome(); buildCmd();
    });
    grid.appendChild(card);
  });

  // ── MCPs ────────────────────────────────────────────────────────
  const mcpGrid = document.getElementById("mcp-grid");
  mcpGrid.innerHTML = "";

  // Cartão "Todos" — inicializa todos os MCP servers
  const allCard = document.createElement("div");
  const allOn = State.selectedMcps === null;
  allCard.className = "skill-card mcp-card" + (allOn ? " selected" : "");
  allCard.innerHTML = `
    <div class="skill-card-header">
      <span class="skill-dot"></span>
      <span class="skill-name">todos</span>
    </div>
    <p class="skill-desc">Inicializa todos os MCP servers disponíveis</p>
  `;
  allCard.addEventListener("click", () => {
    State.selectedMcps = null;
    renderHome(); buildCmd();
  });
  mcpGrid.appendChild(allCard);

  // Cartão "nenhum" — padrão, passa --no-mcp, ignora todos os servidores
  const noneCard = document.createElement("div");
  const noneOn = State.selectedMcps !== null && State.selectedMcps.size === 0;
  noneCard.className = "skill-card mcp-card mcp-card-none" + (noneOn ? " selected" : "");
  noneCard.innerHTML = `
    <div class="skill-card-header">
      <span class="skill-dot"></span>
      <span class="skill-name">nenhum</span>
      <span class="badge-none">--no-mcp</span>
      <span class="badge-default">padrão</span>
    </div>
    <p class="skill-desc">Inicia sem nenhum MCP server (padrão)</p>
  `;
  noneCard.addEventListener("click", () => {
    State.selectedMcps = new Set();
    renderHome(); buildCmd();
  });
  mcpGrid.appendChild(noneCard);

  State.mcps.forEach(({ name: mcp, description }) => {
    const on = State.selectedMcps !== null && State.selectedMcps.has(mcp);
    const card = document.createElement("div");
    card.className = "skill-card mcp-card" + (on ? " selected" : "");
    card.innerHTML = `
      <div class="skill-card-header">
        <span class="skill-dot"></span>
        <span class="skill-name">${esc(mcp)}</span>
      </div>
      ${description ? `<p class="skill-desc">${esc(description)}</p>` : ""}
    `;
    card.addEventListener("click", () => {
      // Primeiro clique em qualquer MCP específico abandona o modo "todos"
      if (State.selectedMcps === null) State.selectedMcps = new Set();
      if (State.selectedMcps.has(mcp)) State.selectedMcps.delete(mcp);
      else State.selectedMcps.add(mcp);
      // Set vazio = --no-mcp (não colapsa para null = todos)
      renderHome(); buildCmd();
    });
    mcpGrid.appendChild(card);
  });

  buildCmd();
}

// ════════════════════════════════════════════════════════════════════
// TAB SKILLS
// ════════════════════════════════════════════════════════════════════
function renderSkillsList() {
  const list = document.getElementById("skills-list");
  list.innerHTML = "";
  State.skills.forEach(({ name: sk, description }) => {
    const card = document.createElement("div");
    card.className = "mgmt-card";
    card.innerHTML = `
      <div class="mgmt-card-top">
        <span class="mgmt-card-icon">🧠</span>
        <span class="mgmt-card-name">${esc(sk)}</span>
      </div>
      ${description ? `<p class="mgmt-card-desc">${esc(description)}</p>` : ""}
      <span class="mgmt-card-hint">${sk}.md</span>
      <div class="mgmt-card-footer">
        <button class="btn-sm btn-edit" onclick="openSkillEditor('${esc(sk)}')">✏ Editar</button>
        <button class="btn-sm btn-danger" onclick="deleteSkill('${esc(sk)}')">✕ Remover</button>
      </div>
    `;
    list.appendChild(card);
  });
}

async function openSkillEditor(name) {
  State.skillEditor = { name, isNew: false };
  const data = await api("GET", `/api/skills/${name}`);
  document.getElementById("skill-editor-title").textContent = `Editando: ${name}.md`;
  document.getElementById("skill-editor-name").value = name;
  document.getElementById("skill-editor-name").disabled = true;
  document.getElementById("skill-editor-content").value = data.content;
  showModal("modal-skill");
}

function newSkillEditor() {
  State.skillEditor = { name: null, isNew: true };
  document.getElementById("skill-editor-title").textContent = "Nova Skill";
  document.getElementById("skill-editor-name").value = "";
  document.getElementById("skill-editor-name").disabled = false;
  document.getElementById("skill-editor-content").value = "# Skill: Nome\n\nDescrição da skill...";
  showModal("modal-skill");
}

async function saveSkill() {
  const name = document.getElementById("skill-editor-name").value.trim();
  const content = document.getElementById("skill-editor-content").value;
  try {
    if (State.skillEditor.isNew) {
      await api("POST", "/api/skills", { name, content });
      toast(`Skill '${name}' criada!`);
    } else {
      await api("PUT", `/api/skills/${State.skillEditor.name}`, { content });
      toast(`Skill salva!`);
    }
    closeModal("modal-skill");
    State.skills = await api("GET", "/api/skills");
    renderSkillsList();
    if (State.activeTab === "home") renderHome();
  } catch (e) { toast(e.message, "err"); }
}

async function deleteSkill(name) {
  if (!confirm(`Remover skill '${name}'?`)) return;
  try {
    await api("DELETE", `/api/skills/${name}`);
    toast(`Skill '${name}' removida.`);
    State.skills = await api("GET", "/api/skills");
    State.selectedSkills.delete(name);
    renderSkillsList();

    if (State.activeTab === "home") renderHome();
  } catch (e) { toast(e.message, "err"); }
}

// ════════════════════════════════════════════════════════════════════
// TAB CRONS
// ════════════════════════════════════════════════════════════════════
function _cronNextLabel(expression) {
  // Preview mínimo client-side — só para exibir na lista
  // O cálculo real é feito server-side
  return expression || "—";
}

async function renderCronsList() {
  // Atualiza badge do scheduler
  try {
    const st = await api("GET", "/api/crons/scheduler/status");
    const badge = document.getElementById("cron-scheduler-badge");
    if (badge) {
      if (st.running && st.croniter_ok) {
        badge.textContent = "✅ Scheduler ativo";
        badge.className = "cron-scheduler-badge cron-scheduler-ok";
      } else if (!st.croniter_ok) {
        badge.textContent = "⚠ croniter não instalado";
        badge.className = "cron-scheduler-badge cron-scheduler-warn";
      } else {
        badge.textContent = "⬛ Scheduler parado";
        badge.className = "cron-scheduler-badge cron-scheduler-err";
      }
    }
  } catch (_) {}

  const list = document.getElementById("crons-list");
  list.innerHTML = "";
  if (!State.crons.length) {
    list.innerHTML = '<div class="empty-state">Nenhuma cron cadastrada</div>';
    return;
  }
  State.crons.forEach(cr => {
    const card = document.createElement("div");
    card.className = "mgmt-card cron-card" + (cr.enabled ? "" : " cron-disabled");
    card.innerHTML = `
      <div class="mgmt-card-top">
        <span class="mgmt-card-icon">⏰</span>
        <span class="mgmt-card-name">${esc(cr.name)}</span>
        <span class="cron-status-badge ${cr.enabled ? "cron-on" : "cron-off"}">
          ${cr.enabled ? "ativa" : "pausada"}
        </span>
      </div>
      <code class="cron-expression">${esc(cr.expression)}</code>
      <p class="mgmt-card-desc" style="white-space:pre-wrap;-webkit-line-clamp:3">${esc((cr.prompt || "").slice(0, 120))}${cr.prompt && cr.prompt.length > 120 ? "…" : ""}</p>
      <div class="cron-meta">
        <span>🧠 ${cr.model || "flash"}</span>
        ${cr.skills && cr.skills.length ? `<span>📚 ${cr.skills.length} skill(s)</span>` : ""}
        <span>${cr.mcps === null ? "🔌 todos MCPs" : cr.mcps.length === 0 ? "🚫 sem MCP" : `🔌 ${cr.mcps.length} MCP(s)`}</span>
      </div>
      <div class="mgmt-card-footer">
        <button class="btn-sm ${cr.enabled ? "btn-toggle-off" : "btn-toggle-on"}"
          onclick="toggleCron('${esc(cr.name)}')">
          ${cr.enabled ? "⏸ Pausar" : "▶ Ativar"}
        </button>
        <button class="btn-sm btn-edit" onclick="openCronEditor('${esc(cr.name)}')">✏ Editar</button>
        <button class="btn-sm btn-add" onclick="confirmFireCron('${esc(cr.name)}')">▶ Disparar</button>
        <button class="btn-sm btn-danger" onclick="deleteCron('${esc(cr.name)}')">✕</button>
      </div>
    `;
    list.appendChild(card);
  });
}

function _buildCronSkillsGrid(selectedSkills) {
  const grid = document.getElementById("cron-skills-grid");
  grid.innerHTML = "";
  State.skills.forEach(({ name: sk }) => {
    const checked = selectedSkills.has(sk);
    const label = document.createElement("label");
    label.className = "checkbox-item" + (checked ? " cron-skill-checked" : "");
    label.innerHTML = `
      <input type="checkbox" ${checked ? "checked" : ""}
        onchange="cronToggleSkill('${esc(sk)}', this.checked)">
      <span>${esc(sk)}</span>
    `;
    grid.appendChild(label);
  });
}

function _buildCronMcpsGrid(selectedMcps) {
  const grid = document.getElementById("cron-mcps-grid");
  grid.innerHTML = "";
  State.mcps.forEach(({ name: mcp }) => {
    const checked = selectedMcps.has(mcp);
    const label = document.createElement("label");
    label.className = "checkbox-item tool-mcp" + (checked ? "" : "");
    label.innerHTML = `
      <input type="checkbox" ${checked ? "checked" : ""}
        onchange="cronToggleMcp('${esc(mcp)}', this.checked)">
      <span class="tool-name">${esc(mcp)}</span>
    `;
    grid.appendChild(label);
  });
}

function cronToggleSkill(sk, checked) {
  if (checked) State.cronEditor.selectedSkills.add(sk);
  else State.cronEditor.selectedSkills.delete(sk);
}

function cronToggleMcp(mcp, checked) {
  if (checked) State.cronEditor.selectedMcps.add(mcp);
  else State.cronEditor.selectedMcps.delete(mcp);
}

function cronMcpModeChange(mode) {
  State.cronEditor.mcpMode = mode;
  const grid = document.getElementById("cron-mcps-grid");
  grid.style.display = mode === "select" ? "" : "none";
}

async function previewCron() {
  const expr = document.getElementById("cron-editor-expression").value.trim();
  const el = document.getElementById("cron-preview");
  if (!expr) { el.innerHTML = ""; return; }
  try {
    const r = await api("POST", "/api/crons/preview", { expression: expr });
    if (r.next_runs && r.next_runs.length) {
      el.innerHTML = `<span class="cron-preview-label">Próximas:</span> ` +
        r.next_runs.map(d => `<code>${esc(d)}</code>`).join(" · ");
      el.className = "cron-preview cron-preview-ok";
    } else {
      el.textContent = r.next_runs[0] || "Expressão inválida";
      el.className = "cron-preview cron-preview-err";
    }
  } catch (_) {
    el.textContent = "Erro ao calcular";
    el.className = "cron-preview cron-preview-err";
  }
}

function _fillCronModal(cr, isNew) {
  State.cronEditor = {
    name:           isNew ? null : cr.name,
    isNew,
    selectedSkills: new Set(cr.skills || []),
    mcpMode:        cr.mcps === null ? "all" : cr.mcps.length === 0 ? "none" : "select",
    selectedMcps:   new Set(Array.isArray(cr.mcps) ? cr.mcps : []),
  };

  document.getElementById("cron-editor-title").textContent = isNew ? "Nova Cron" : `Editando: ${cr.name}`;
  document.getElementById("cron-editor-name").value        = cr.name || "";
  document.getElementById("cron-editor-name").disabled     = !isNew;
  document.getElementById("cron-editor-enabled").checked   = cr.enabled !== false;
  document.getElementById("cron-editor-expression").value  = cr.expression || "0 9 * * 1-5";
  document.getElementById("cron-editor-model").value       = cr.model || "gemini-1.5-flash";
  document.getElementById("cron-editor-prompt").value      = cr.prompt || "";

  // Radio MCP
  const mode = State.cronEditor.mcpMode;
  document.querySelectorAll("input[name='cron-mcp-mode']").forEach(r => r.checked = (r.value === mode));
  document.getElementById("cron-mcps-grid").style.display = mode === "select" ? "" : "none";

  // Botão disparar (só em edição)
  const fireBtn = document.getElementById("cron-fire-btn");
  fireBtn.style.display = isNew ? "none" : "";

  _buildCronSkillsGrid(State.cronEditor.selectedSkills);
  _buildCronMcpsGrid(State.cronEditor.selectedMcps);

  // Preview inicial
  document.getElementById("cron-preview").innerHTML = "";
  if (cr.expression) setTimeout(previewCron, 50);
}

function newCronEditor() {
  _fillCronModal({
    name: "", expression: "0 9 * * 1-5", prompt: "",
    model: "gemini-1.5-flash", skills: [], mcps: null, enabled: true,
  }, true);
  showModal("modal-cron");
}

async function openCronEditor(name) {
  const data = await api("GET", `/api/crons/${name}`);
  _fillCronModal(data, false);
  showModal("modal-cron");
}

async function saveCron() {
  const name       = document.getElementById("cron-editor-name").value.trim();
  const expression = document.getElementById("cron-editor-expression").value.trim();
  const model      = document.getElementById("cron-editor-model").value;
  const prompt     = document.getElementById("cron-editor-prompt").value;
  const enabled    = document.getElementById("cron-editor-enabled").checked;
  const skills     = [...State.cronEditor.selectedSkills];

  let mcps;
  const mode = State.cronEditor.mcpMode;
  if (mode === "all")    mcps = null;
  else if (mode === "none") mcps = [];
  else                   mcps = [...State.cronEditor.selectedMcps];

  if (!name)       { toast("Slug obrigatório.", "err"); return; }
  if (!expression) { toast("Cron expression obrigatória.", "err"); return; }
  if (!prompt.trim()) { toast("Prompt obrigatório.", "err"); return; }

  const body = { name, expression, prompt, model, skills, mcps, enabled };
  try {
    if (State.cronEditor.isNew) {
      await api("POST", "/api/crons", body);
      toast(`Cron '${name}' criada!`);
    } else {
      await api("PUT", `/api/crons/${State.cronEditor.name}`, body);
      toast("Cron salva!");
    }
    closeModal("modal-cron");
    State.crons = await api("GET", "/api/crons");
    if (State.activeTab === "crons") renderCronsList();
  } catch (e) { toast(e.message, "err"); }
}

async function deleteCron(name) {
  if (!confirm(`Remover cron '${name}'?`)) return;
  try {
    await api("DELETE", `/api/crons/${name}`);
    toast(`Cron '${name}' removida.`);
    State.crons = await api("GET", "/api/crons");
    renderCronsList();
  } catch (e) { toast(e.message, "err"); }
}

async function toggleCron(name) {
  try {
    const r = await api("POST", `/api/crons/${name}/toggle`);
    toast(r.enabled ? `Cron '${name}' ativada.` : `Cron '${name}' pausada.`);
    State.crons = await api("GET", "/api/crons");
    renderCronsList();
  } catch (e) { toast(e.message, "err"); }
}

async function confirmFireCron(name) {
  if (!confirm(`Disparar a cron '${name}' agora (fora do horário agendado)?`)) return;
  try {
    await api("POST", `/api/crons/${name}/fire`);
    toast(`⏰ Cron '${name}' disparada! Verifique Execuções.`);
    State.executions = await api("GET", "/api/executions");
    if (State.activeTab === "executions") renderExecutionsList();
  } catch (e) { toast(e.message, "err"); }
}

async function fireCron() {
  const name = State.cronEditor.name;
  if (!name) return;
  closeModal("modal-cron");
  await confirmFireCron(name);
}

// ════════════════════════════════════════════════════════════════════
// TAB MCPs
// ════════════════════════════════════════════════════════════════════
function renderMcpsList() {
  const list = document.getElementById("mcps-list");
  list.innerHTML = "";
  if (!State.mcps.length) {
    list.innerHTML = '<div class="empty-state">Nenhum MCP server cadastrado</div>';
    return;
  }
  State.mcps.forEach(({ name: mcp, description, requires_key }) => {
    const card = document.createElement("div");
    card.className = "mgmt-card";
    card.innerHTML = `
      <div class="mgmt-card-top">
        <span class="mgmt-card-icon">🔌</span>
        <span class="mgmt-card-name">${esc(mcp)}</span>
        ${requires_key ? '<span class="mcp-key-badge" title="Requer chave de API">🔑</span>' : ""}
      </div>
      ${description ? `<p class="mgmt-card-desc">${esc(description)}</p>` : ""}
      <span class="mgmt-card-hint">${mcp}.py</span>
      <div class="mgmt-card-footer">
        <button class="btn-sm btn-edit" onclick="openMcpEditor('${esc(mcp)}')">✏ Editar</button>
        <button class="btn-sm btn-danger" onclick="deleteMcp('${esc(mcp)}')">✕ Remover</button>
      </div>
    `;
    list.appendChild(card);
  });
}

async function openMcpEditor(name) {
  State.mcpEditor = { name, isNew: false };
  const data = await api("GET", `/api/mcps/${name}`);
  document.getElementById("mcp-editor-title").textContent = `Editando: ${name}.py`;
  document.getElementById("mcp-editor-name").value = name;
  document.getElementById("mcp-editor-name").disabled = true;
  document.getElementById("mcp-editor-content").value = data.content;
  showModal("modal-mcp");
}

function newMcpEditor() {
  State.mcpEditor = { name: null, isNew: true };
  document.getElementById("mcp-editor-title").textContent = "Novo MCP Server";
  document.getElementById("mcp-editor-name").value = "";
  document.getElementById("mcp-editor-name").disabled = false;
  document.getElementById("mcp-editor-content").value =
`import os

async def register(mcp_manager):
    token = os.getenv("MEU_TOKEN")
    if not token:
        print("[!] meu-mcp: MEU_TOKEN ausente no .env")
        return

    await mcp_manager.connect_server(
        name="meu-mcp",
        command="npx",
        args=["-y", "@exemplo/mcp-server@latest"],
        env={"MEU_TOKEN": token}
    )
`;
  showModal("modal-mcp");
}

async function saveMcp() {
  const name = document.getElementById("mcp-editor-name").value.trim();
  const content = document.getElementById("mcp-editor-content").value;
  try {
    if (State.mcpEditor.isNew) {
      await api("POST", "/api/mcps", { name, content });
      toast(`MCP '${name}' criado!`);
    } else {
      await api("PUT", `/api/mcps/${State.mcpEditor.name}`, { content });
      toast(`MCP salvo!`);
    }
    closeModal("modal-mcp");
    State.mcps = await api("GET", "/api/mcps");
    // Atualiza também State.tools.mcp para refletir nos crew editors
    const tools = await api("GET", "/api/tools");
    State.tools = (tools && tools.native) ? tools : { native: tools || [], mcp: [] };
    renderMcpsList();
    if (State.activeTab === "home") renderHome();
  } catch (e) { toast(e.message, "err"); }
}

async function deleteMcp(name) {
  if (!confirm(`Remover MCP '${name}'?`)) return;
  try {
    await api("DELETE", `/api/mcps/${name}`);
    toast(`MCP '${name}' removido.`);
    State.mcps = await api("GET", "/api/mcps");
    const tools = await api("GET", "/api/tools");
    State.tools = (tools && tools.native) ? tools : { native: tools || [], mcp: [] };
    // Remove do selectedMcps se estava selecionado
    if (State.selectedMcps !== null) {
      State.selectedMcps.delete(name);
      // mantém Set vazio (= --no-mcp) ao excluir o último — não colapsa para null (= todos)
    }
    renderMcpsList();
    if (State.activeTab === "home") renderHome();
  } catch (e) { toast(e.message, "err"); }
}

// ════════════════════════════════════════════════════════════════════
// TAB COMMANDS
// ════════════════════════════════════════════════════════════════════
function renderCommandsList() {
  const list = document.getElementById("commands-list");
  list.innerHTML = "";
  State.commands.forEach(cmd => {
    const card = document.createElement("div");
    card.className = "mgmt-card";
    card.innerHTML = `
      <div class="mgmt-card-top">
        <span class="mgmt-card-icon">⚡</span>
        <span class="mgmt-card-name">${esc(cmd)}</span>
      </div>
      <span class="mgmt-card-hint">→ /${esc(cmd)}</span>
      <div class="mgmt-card-footer">
        <button class="btn-sm btn-edit" onclick="openCommandEditor('${esc(cmd)}')">✏ Editar</button>
        <button class="btn-sm btn-danger" onclick="deleteCommand('${esc(cmd)}')">✕ Remover</button>
      </div>
    `;
    list.appendChild(card);
  });
}

async function openCommandEditor(name) {
  State.commandEditor = { name, isNew: false };
  const data = await api("GET", `/api/commands/${name}`);
  document.getElementById("cmd-editor-title").textContent = `Editando: /${name}`;
  document.getElementById("cmd-editor-name").value = name;
  document.getElementById("cmd-editor-name").disabled = true;
  document.getElementById("cmd-editor-content").value = data.content;
  showModal("modal-command");
}

function newCommandEditor() {
  State.commandEditor = { name: null, isNew: true };
  document.getElementById("cmd-editor-title").textContent = "Novo Command";
  document.getElementById("cmd-editor-name").value = "";
  document.getElementById("cmd-editor-name").disabled = false;
  document.getElementById("cmd-editor-content").value = "";
  showModal("modal-command");
}

async function saveCommand() {
  const name = document.getElementById("cmd-editor-name").value.trim();
  const content = document.getElementById("cmd-editor-content").value;
  try {
    if (State.commandEditor.isNew) {
      await api("POST", "/api/commands", { name, content });
      toast(`Command '/${name}' criado!`);
    } else {
      await api("PUT", `/api/commands/${State.commandEditor.name}`, { content });
      toast(`Command salvo!`);
    }
    closeModal("modal-command");
    State.commands = await api("GET", "/api/commands");
    renderCommandsList();
  } catch (e) { toast(e.message, "err"); }
}

async function deleteCommand(name) {
  if (!confirm(`Remover command '/${name}'?`)) return;
  try {
    await api("DELETE", `/api/commands/${name}`);
    toast(`Command removido.`);
    State.commands = await api("GET", "/api/commands");
    renderCommandsList();
  } catch (e) { toast(e.message, "err"); }
}

// ════════════════════════════════════════════════════════════════════
// TAB PROMPTS
// ════════════════════════════════════════════════════════════════════
function renderPromptsList() {
  const list = document.getElementById("prompts-list");
  list.innerHTML = "";
  State.prompts.forEach(p => {
    const card = document.createElement("div");
    card.className = "mgmt-card prompt-card";
    card.innerHTML = `
      <span class="mgmt-card-name">${esc(p)}</span>
      <div class="mgmt-card-top">
        <span class="mgmt-card-icon">📄</span>
        <span class="mgmt-card-hint">→ #prompt ${esc(p)}</span>
      </div>
      <div class="mgmt-card-footer">
        <button class="btn-sm btn-edit" onclick="openPromptEditor('${esc(p)}')">✏ Editar</button>
        <button class="btn-sm btn-danger" onclick="deletePrompt('${esc(p)}')">✕ Remover</button>
      </div>
    `;
    list.appendChild(card);
  });
}

async function openPromptEditor(name) {
  State.promptEditor = { name, isNew: false };
  const data = await api("GET", `/api/prompts/${name}`);
  document.getElementById("prompt-editor-title").textContent = `Editando: ${name}.md`;
  document.getElementById("prompt-editor-name").value = name;
  document.getElementById("prompt-editor-name").disabled = true;
  document.getElementById("prompt-editor-content").value = data.content;
  showModal("modal-prompt");
}

function newPromptEditor() {
  State.promptEditor = { name: null, isNew: true };
  document.getElementById("prompt-editor-title").textContent = "Novo Prompt";
  document.getElementById("prompt-editor-name").value = "";
  document.getElementById("prompt-editor-name").disabled = false;
  document.getElementById("prompt-editor-content").value = "";
  showModal("modal-prompt");
}

async function savePrompt() {
  const name = document.getElementById("prompt-editor-name").value.trim();
  const content = document.getElementById("prompt-editor-content").value;
  try {
    if (State.promptEditor.isNew) {
      await api("POST", "/api/prompts", { name, content });
      toast(`Prompt '${name}' criado!`);
    } else {
      await api("PUT", `/api/prompts/${State.promptEditor.name}`, { content });
      toast(`Prompt salvo!`);
    }
    closeModal("modal-prompt");
    State.prompts = await api("GET", "/api/prompts");
    renderPromptsList();
  } catch (e) { toast(e.message, "err"); }
}

async function deletePrompt(name) {
  if (!confirm(`Remover prompt '${name}'?`)) return;
  try {
    await api("DELETE", `/api/prompts/${name}`);
    toast(`Prompt removido.`);
    State.prompts = await api("GET", "/api/prompts");
    renderPromptsList();
  } catch (e) { toast(e.message, "err"); }
}


// ════════════════════════════════════════════════════════════════════
// TAB CREWS
// ════════════════════════════════════════════════════════════════════
function renderCrewsList() {
  const list = document.getElementById("crews-list");
  list.innerHTML = "";
  State.crews.forEach(cr => {
    const agentsLabel = cr.agents_count === 1 ? "1 agente" : `${cr.agents_count} agentes`;
    const displayName = cr.title || cr.name;
    const card = document.createElement("div");
    card.className = "mgmt-card crews-card";
    card.innerHTML = `
      <span class="mgmt-card-name">${esc(displayName)}</span>
      <div class="mgmt-card-top">
        <span class="mgmt-card-icon">🤖</span>
        <span class="mgmt-card-badge">${agentsLabel}</span>
      </div>
      ${cr.description ? `<p class="mgmt-card-desc">${esc(cr.description.trim())}</p>` : ""}
      <span class="mgmt-card-hint">${cr.name}.yaml</span>
      <div class="mgmt-card-footer">
        <button class="btn-sm btn-edit" onclick="openCrewEditor('${esc(cr.name)}')">✏ Editar</button>
        <button class="btn-sm btn-danger" onclick="deleteCrew('${esc(cr.name)}')">✕ Remover</button>
      </div>
    `;
    list.appendChild(card);
  });
}

function agentTemplate() {
  return {
    name: "",
    modelId: "gemini-1.5-flash",
    clean_context_after_run: true,
    skills: ["optimize-shell-execution", "rtk-gain"],
    persona: "",
    roles: [""],
    tools: ["shell_execute", "read_files", "write_file", "patch_file", "list_dir", "search_text"],
    output_flow: "",
    transitions: [{ condition: "", target: null }],
  };
}

async function openCrewEditor(name) {
  State.crewEditor = { name, isNew: false };
  const data = await api("GET", `/api/crews/${name}`);
  State.crewEditor.agents      = (data.data?.crew || []).map(a => JSON.parse(JSON.stringify(a)));
  State.crewEditor.description = data.data?.description || "";
  State.crewEditor.crewTitle   = data.data?.title || "";
  document.getElementById("crew-editor-title").textContent = `Editando: ${name}.yaml`;
  document.getElementById("crew-editor-name").value = name;
  document.getElementById("crew-editor-name").disabled = true;
  document.getElementById("crew-editor-crew-title").value = State.crewEditor.crewTitle;
  document.getElementById("crew-editor-description").value = State.crewEditor.description;
  renderCrewForm();
  showModal("modal-crew");
}

function newCrewEditor() {
  State.crewEditor = { name: null, isNew: true, agents: [agentTemplate()], description: "", crewTitle: "" };
  document.getElementById("crew-editor-title").textContent = "Nova Crew";
  document.getElementById("crew-editor-name").value = "";
  document.getElementById("crew-editor-name").disabled = false;
  document.getElementById("crew-editor-crew-title").value = "";
  document.getElementById("crew-editor-description").value = "";
  renderCrewForm();
  showModal("modal-crew");
}

function renderCrewForm() {
  const container = document.getElementById("crew-agents-container");
  container.innerHTML = "";
  State.crewEditor.agents.forEach((agent, idx) => {
    const section = document.createElement("div");
    section.className = "agent-section";

    // Skills checkboxes
    const agentSkills = agent.skills || [];
    const skillsCheckboxes = State.skills.map(({ name: sk }) => `
      <label class="checkbox-item">
        <input type="checkbox" ${agentSkills.includes(sk) ? "checked" : ""}
          onchange="toggleAgentSkill(${idx}, '${esc(sk)}', this.checked)">
        <span>${sk}</span>
      </label>`).join("");

    // Tools checkboxes — separadas em Nativas e MCP
    const agentTools = agent.tools || [];
    const nativeTools = State.tools.native || [];
    const mcpTools    = State.tools.mcp    || [];

    // Descrições curtas das tools nativas para tooltip
    const nativeDesc = {
      shell_execute: "Executa comandos no terminal",
      read_files:    "Lê arquivos em batch",
      write_file:    "Cria ou sobrescreve arquivo",
      patch_file:    "Edição cirúrgica (search/replace)",
      list_dir:      "Lista estrutura de diretório",
      search_text:   "Busca padrão/regex em arquivos",
    };

    const nativeCheckboxes = nativeTools.map(t => `
      <label class="checkbox-item tool-native" title="${esc(nativeDesc[t] || t)}">
        <input type="checkbox" ${agentTools.includes(t) ? "checked" : ""}
          onchange="toggleAgentTool(${idx}, '${esc(t)}', this.checked)">
        <span class="tool-name">${t}</span>
      </label>`).join("");

    const mcpCheckboxes = mcpTools.length ? mcpTools.map(t => `
      <label class="checkbox-item tool-mcp" title="MCP server: ${esc(t)}">
        <input type="checkbox" ${agentTools.includes(t) ? "checked" : ""}
          onchange="toggleAgentTool(${idx}, '${esc(t)}', this.checked)">
        <span class="tool-name">${t}</span>
      </label>`).join("") : '<span style="color:var(--text-dim);font-size:12px">Nenhum MCP server disponível.</span>';

    section.innerHTML = `
      <div class="agent-header">
        <span class="agent-badge">Agente ${idx + 1}</span>
        <button class="btn-sm btn-danger" onclick="removeAgent(${idx})">✕ Remover</button>
      </div>
      <div class="form-grid">
        <div class="form-group">
          <label>Nome do Agente</label>
          <input type="text" value="${esc(agent.name)}"
            oninput="updateAgent(${idx},'name',this.value)" placeholder="Ex: John">
        </div>
        <div class="form-group">
          <label>Modelo</label>
          <select onchange="updateAgent(${idx},'modelId',this.value)">
            ${["claude-opus-4-6","gemini-1.5-flash","claude-haiku-4-5"].map(m =>
              `<option ${agent.modelId===m?"selected":""}>${m}</option>`
            ).join("")}
          </select>
        </div>
        <div class="form-group form-group-full">
          <label>Persona</label>
          <textarea rows="2" oninput="updateAgent(${idx},'persona',this.value)"
            placeholder="Descreva a persona do agente...">${esc(agent.persona)}</textarea>
        </div>
        <div class="form-group">
          <label>Output Flow</label>
          <input type="text" value="${esc(agent.output_flow)}"
            oninput="updateAgent(${idx},'output_flow',this.value)"
            placeholder="Ex: Markdown detalhado...">
        </div>
        <div class="form-group" style="justify-content:flex-end;padding-top:18px">
          <label style="flex-direction:row;gap:6px;align-items:center;cursor:pointer">
            <input type="checkbox" ${agent.clean_context_after_run?"checked":""}
              onchange="updateAgent(${idx},'clean_context_after_run',this.checked)">
            Limpar contexto após execução
          </label>
        </div>
      </div>

      <div class="form-group">
        <label>Skills <small>(marque as skills que este agente deve usar)</small></label>
        <div class="checkbox-grid">${skillsCheckboxes}</div>
      </div>

      <div class="form-group">
        <label>Tools Nativas <small>(built-in — otimizadas para performance)</small></label>
        <div class="checkbox-grid">${nativeCheckboxes}</div>
      </div>

      <div class="form-group">
        <label>MCP Servers <small>(integrações externas — Jira, Bitbucket, Slack, AWS…)</small></label>
        <div class="checkbox-grid mcp-grid">${mcpCheckboxes}</div>
      </div>

      <div class="form-group">
        <label>Roles <small>(uma por linha)</small></label>
        <textarea rows="3" oninput="updateAgentList(${idx},'roles',this.value)"
          >${(agent.roles||[]).join("\n")}</textarea>
      </div>

      <div class="form-group">
        <label>Transições</label>
        <div class="transitions-list" id="transitions-${idx}">
          ${(agent.transitions||[]).map((t,ti) => renderTransitionRow(idx,ti,t)).join("")}
        </div>
        <button class="btn-sm btn-add" style="margin-top:6px" onclick="addTransition(${idx})">+ Transição</button>
      </div>
    `;
    container.appendChild(section);
  });
}

function toggleAgentSkill(idx, skill, checked) {
  const agent = State.crewEditor.agents[idx];
  if (!agent.skills) agent.skills = [];
  if (checked) { if (!agent.skills.includes(skill)) agent.skills.push(skill); }
  else { agent.skills = agent.skills.filter(s => s !== skill); }
}

function toggleAgentTool(idx, tool, checked) {
  const agent = State.crewEditor.agents[idx];
  if (!agent.tools) agent.tools = [];
  if (checked) { if (!agent.tools.includes(tool)) agent.tools.push(tool); }
  else { agent.tools = agent.tools.filter(t => t !== tool); }
}

function renderTransitionRow(agentIdx, transIdx, t) {
  const targetVal = t.target === null ? "" : (t.target || "");
  // Monta options de agentes para o target
  const agentOptions = State.crewEditor.agents.map((a, i) =>
    a.name && i !== agentIdx
      ? `<option value="${esc(a.name)}" ${targetVal === a.name ? "selected" : ""}>${a.name}</option>`
      : ""
  ).join("");
  
  return `
    <div class="transition-row" id="tr-${agentIdx}-${transIdx}">
      <input type="text" placeholder="Condição..." value="${esc(t.condition||"")}"
        oninput="updateTransition(${agentIdx},${transIdx},'condition',this.value)">
      <select onchange="updateTransition(${agentIdx},${transIdx},'target',this.value)">
        <option value="">— fim do fluxo —</option>
        ${agentOptions}
      </select>
      <button class="btn-sm btn-danger" onclick="removeTransition(${agentIdx},${transIdx})">✕</button>
    </div>`;
}

function updateAgent(idx, field, value) { State.crewEditor.agents[idx][field] = value; }
function updateAgentList(idx, field, value) {
  State.crewEditor.agents[idx][field] = value.split("\n").map(s => s.trim()).filter(Boolean);
}
function updateTransition(agentIdx, transIdx, field, value) {
  const t = State.crewEditor.agents[agentIdx].transitions[transIdx];
  if (field === "target") t.target = value === "" ? null : value;
  else t[field] = value;
}
function addTransition(agentIdx) {
  State.crewEditor.agents[agentIdx].transitions.push({ condition: "", target: null });
  renderCrewForm();
}
function removeTransition(agentIdx, transIdx) {
  State.crewEditor.agents[agentIdx].transitions.splice(transIdx, 1);
  renderCrewForm();
}
function addAgent() { State.crewEditor.agents.push(agentTemplate()); renderCrewForm(); }
function removeAgent(idx) {
  if (State.crewEditor.agents.length === 1) { toast("A crew precisa de ao menos um agente.", "err"); return; }
  State.crewEditor.agents.splice(idx, 1);
  renderCrewForm();
}

async function saveCrew() {
  const name        = document.getElementById("crew-editor-name").value.trim();
  const crewTitle   = document.getElementById("crew-editor-crew-title").value.trim();
  const description = document.getElementById("crew-editor-description").value;
  const data        = { crew: State.crewEditor.agents };
  try {
    if (State.crewEditor.isNew) {
      await api("POST", "/api/crews", { name, title: crewTitle, description, data });
      toast(`Crew '${name}' criada!`);
    } else {
      await api("PUT", `/api/crews/${State.crewEditor.name}`, { title: crewTitle, description, data });
      toast(`Crew salva!`);
    }
    closeModal("modal-crew");
    State.crews = await api("GET", "/api/crews");
    renderCrewsList();
  } catch (e) { toast(e.message, "err"); }
}

async function deleteCrew(name) {
  if (!confirm(`Remover crew '${name}'?`)) return;
  try {
    await api("DELETE", `/api/crews/${name}`);
    toast(`Crew '${name}' removida.`);
    State.crews = await api("GET", "/api/crews");
    renderCrewsList();
  } catch (e) { toast(e.message, "err"); }
}

// ─── Crew Builder (Nova Crew com COIA) ───────────────────────────
function openCrewBuilderModal() {
  document.getElementById("crew-builder-name").value = "";
  document.getElementById("crew-builder-type").value = "";
  document.getElementById("crew-builder-objective").value = "";
  document.getElementById("crew-builder-stack").value = "";
  showModal("modal-crew-builder");
}

async function launchCrewBuilder() {
  const name      = document.getElementById("crew-builder-name").value.trim().replace(/\s+/g, "-");
  const type      = document.getElementById("crew-builder-type").value;
  const objective = document.getElementById("crew-builder-objective").value.trim();
  const stack     = document.getElementById("crew-builder-stack").value.trim();

  if (!name) { toast("Nome da crew é obrigatório.", "err"); return; }
  if (!type && !objective) { toast("Selecione um tipo ou descreva o objetivo.", "err"); return; }

  try {
    await api("POST", "/api/session/start-crew-builder", {
      name, type, objective, stack
    });
    toast(`🤖 Terminal aberto — COIA está criando a crew "${name}"!`);
    closeModal("modal-crew-builder");
  } catch (e) {
    toast(e.message || "Erro ao iniciar Crew Builder.", "err");
  }
}


// ════════════════════════════════════════════════════════════════════
// TAB SPRINTS
// ════════════════════════════════════════════════════════════════════
function sprintStatusBadge(status) {
  const map = {
    open:        ["⬜ open",        "sprint-status-open"],
    in_progress: ["🔄 in_progress", "sprint-status-in-progress"],
    done:        ["✅ done",         "sprint-status-done"],
  };
  const [label, cls] = map[status] || ["⬜ open", "sprint-status-open"];
  return `<span class="sprint-status-badge ${cls}">${label}</span>`;
}

function sprintTaskCounter(sp) {
  const tasks = sp.tasks || [];
  const done  = tasks.filter(t => t.status === "done").length;
  const total = tasks.length;
  if (!total) return "";
  return `<span class="sprint-task-counter">${done}/${total} concluídas</span>`;
}

function renderSprintsList() {
  const list = document.getElementById("sprints-list");
  list.innerHTML = "";
  if (!State.sprints.length) {
    list.innerHTML = '<div class="empty-state">Nenhuma sprint cadastrada</div>';
    return;
  }
  State.sprints.forEach(sp => {
    const tasks     = sp.tasks || [];
    const done      = tasks.filter(t => t.status === "done").length;
    const total     = tasks.length;
    const pct       = total ? Math.round((done / total) * 100) : 0;
    const card      = document.createElement("div");
    card.className  = "mgmt-card sprint-card";
    card.innerHTML  = `
      <span class="mgmt-card-name sprint-card-name" onclick="viewSprint('${esc(sp.name)}')">${esc(sp.title || sp.name)}</span>
      <div class="mgmt-card-top">
        <span class="mgmt-card-icon">🏃</span>
        ${sprintStatusBadge(sp.status || "open")}
      </div>
      ${total ? `
        <div class="sprint-progress">
          <div class="sprint-progress-bar" style="width:${pct}%"></div>
        </div>
        <div class="sprint-progress-label">${done}/${total} tarefas concluídas</div>
      ` : '<span class="mgmt-card-hint">Sem tarefas</span>'}
      <span class="mgmt-card-hint">${sp.name}.yaml</span>
      <div class="mgmt-card-footer">
        <button class="btn-sm btn-coia" onclick="launchSprintSession('${esc(sp.name)}')">▶ COIA</button>
        <button class="btn-sm btn-edit" onclick="openSprintEditor('${esc(sp.name)}')">✏ Editar</button>
        <button class="btn-sm btn-danger" onclick="deleteSprint('${esc(sp.name)}')">✕</button>
      </div>
    `;
    list.appendChild(card);
  });
}

function taskTemplate() {
  return { title: "", description: "", priority: "normal", status: "open", updates: [] };
}

async function viewSprint(name) {
  await _loadSprintModal(name, true);
}

async function openSprintEditor(name) {
  await _loadSprintModal(name, false);
}

async function _loadSprintModal(name, readonly) {
  State.sprintEditor = { name, isNew: false, readonly };
  const data = await api("GET", `/api/sprints/${name}`);
  const tasks  = (data.data?.tasks || []).map(t => ({ ...taskTemplate(), ...t }));
  const done   = tasks.filter(t => t.status === "done").length;
  const total  = tasks.length;
  const counter = total ? ` — ${done}/${total} concluídas` : "";

  State.sprintEditor.tasks       = tasks;
  State.sprintEditor.description = data.data?.description || "";
  State.sprintEditor.status      = data.data?.status || "open";
  State.sprintEditor.updates     = data.data?.updates || [];

  document.getElementById("sprint-editor-title").textContent =
    readonly ? `${data.data?.title || name}${counter}` : `Editando: ${name}.yaml`;

  // Campos: readonly ou editáveis
  const fields = ["sprint-editor-name", "sprint-editor-title-input", "sprint-editor-description", "sprint-editor-status"];
  fields.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = readonly;
  });

  document.getElementById("sprint-editor-name").value        = name;
  document.getElementById("sprint-editor-title-input").value = data.data?.title || name;
  document.getElementById("sprint-editor-description").value = State.sprintEditor.description;
  document.getElementById("sprint-editor-status").value      = State.sprintEditor.status;

  // Botão salvar: visível só em modo edição
  const footer = document.querySelector("#modal-sprint .modal-footer");
  footer.querySelector(".btn-green").style.display = readonly ? "none" : "";

  // Botão "Executar com Crew": visível sempre (leitura e edição), nunca em isNew
  const execBtn = document.getElementById("sprint-modal-exec-btn");
  if (execBtn) execBtn.style.display = "";

  // Botão "+ Adicionar Tarefa": visível só em modo edição
  document.querySelector(".btn-sm.btn-add").style.display = readonly ? "none" : "";

  renderSprintUpdates(State.sprintEditor.updates, "sprint-updates-list");
  renderSprintTasksForm();
  showModal("modal-sprint");
}

function newSprintEditor() {
  State.sprintEditor = { name: null, isNew: true, tasks: [taskTemplate()], description: "", status: "open", updates: [] };
  document.getElementById("sprint-editor-title").textContent = "Nova Sprint";

  // Garante que todos os campos estejam habilitados (podem ter ficado disabled de um modal anterior)
  ["sprint-editor-name", "sprint-editor-title-input", "sprint-editor-description", "sprint-editor-status"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.disabled = false;
  });

  document.getElementById("sprint-editor-name").value = "";
  document.getElementById("sprint-editor-title-input").value = "";
  document.getElementById("sprint-editor-description").value = "";
  document.getElementById("sprint-editor-status").value = "open";

  // Garante visibilidade do botão salvar e do botão de adicionar tarefa
  const footer = document.querySelector("#modal-sprint .modal-footer");
  if (footer) footer.querySelector(".btn-green").style.display = "";
  document.querySelector(".btn-sm.btn-add").style.display = "";

  // Oculta "Executar com Crew" — sprint ainda não existe em disco
  const execBtn = document.getElementById("sprint-modal-exec-btn");
  if (execBtn) execBtn.style.display = "none";

  renderSprintUpdates([], "sprint-updates-list");
  renderSprintTasksForm();
  showModal("modal-sprint");
}

function renderSprintUpdates(updates, containerId) {
  const el = document.getElementById(containerId);
  if (!el) return;
  if (!updates || !updates.length) {
    el.innerHTML = '<span style="color:var(--text-dim);font-size:12px">Nenhum update registrado pela IA ainda.</span>';
    return;
  }
  el.innerHTML = updates.map((u, i) =>
    `<div class="update-item"><span class="update-idx">${i + 1}</span><span>${esc(u)}</span></div>`
  ).join("");
}

function renderSprintTasksForm() {
  const container = document.getElementById("sprint-tasks-container");
  container.innerHTML = "";
  State.sprintEditor.tasks.forEach((task, idx) => {
    const taskUpdates = task.updates || [];
    const updatesHtml = taskUpdates.length
      ? taskUpdates.map((u, i) =>
          `<div class="update-item"><span class="update-idx">${i + 1}</span><span>${esc(u)}</span></div>`
        ).join("")
      : '<span style="color:var(--text-dim);font-size:12px">Nenhum update registrado pela IA ainda.</span>';

    const statusClass = { done: "task-done", in_progress: "task-in-progress", open: "task-open" }[task.status] || "task-open";
    const readonly = State.sprintEditor?.readonly;

    const div = document.createElement("div");
    div.className = `task-section ${statusClass}`;
    div.innerHTML = `
      <div class="task-header">
        <span class="task-badge">Tarefa ${idx + 1}</span>
        ${readonly ? "" : `<button class="btn-sm btn-danger" onclick="removeSprintTask(${idx})">✕</button>`}
      </div>
      <div class="form-grid">
        <div class="form-group form-group-full">
          <label>Título da Tarefa</label>
          <input type="text" value="${esc(task.title)}"
            oninput="updateSprintTask(${idx},'title',this.value)"
            placeholder="Título da tarefa..." ${readonly ? "disabled" : ""}>
        </div>
        <div class="form-group form-group-full">
          <label>Descrição</label>
          <textarea rows="2" oninput="updateSprintTask(${idx},'description',this.value)"
            placeholder="Descrição detalhada..." ${readonly ? "disabled" : ""}>${esc(task.description)}</textarea>
        </div>
        <div class="form-group">
          <label>Prioridade</label>
          <select onchange="updateSprintTask(${idx},'priority',this.value)" ${readonly ? "disabled" : ""}>
            ${["low","normal","high","critical"].map(p =>
              `<option value="${p}" ${task.priority===p?"selected":""}>${p}</option>`
            ).join("")}
          </select>
        </div>
        <div class="form-group">
          <label>Status</label>
          <select onchange="updateSprintTask(${idx},'status',this.value)" ${readonly ? "disabled" : ""}>
            ${["open","in_progress","done"].map(s =>
              `<option value="${s}" ${task.status===s?"selected":""}>${s}</option>`
            ).join("")}
          </select>
        </div>
      </div>
      <div class="form-group">
        <label>Updates da IA <small>(somente leitura — preenchido automaticamente)</small></label>
        <div class="updates-list">${updatesHtml}</div>
      </div>`;
    container.appendChild(div);
  });
}

function addSprintTask() {
  State.sprintEditor.tasks.push(taskTemplate());
  renderSprintTasksForm();
}

function removeSprintTask(idx) {
  State.sprintEditor.tasks.splice(idx, 1);
  renderSprintTasksForm();
}

function updateSprintTask(idx, field, value) {
  State.sprintEditor.tasks[idx][field] = value;
}

async function saveSprint() {
  const name = document.getElementById("sprint-editor-name").value.trim();
  const title = document.getElementById("sprint-editor-title-input").value.trim() || name;
  const description = document.getElementById("sprint-editor-description").value;
  const status = document.getElementById("sprint-editor-status").value;
  const tasks = State.sprintEditor.tasks;
  const updates = State.sprintEditor.updates || [];
  try {
    if (State.sprintEditor.isNew) {
      await api("POST", "/api/sprints", { name, title, description, status, tasks, updates });
      toast(`Sprint '${title}' criada!`);
    } else {
      const existing = await api("GET", `/api/sprints/${State.sprintEditor.name}`);
      const data = {
        title,
        name: State.sprintEditor.name,
        description,
        status,
        tasks,
        updates,
        created_at: existing.data?.created_at || new Date().toISOString(),
      };
      await api("PUT", `/api/sprints/${State.sprintEditor.name}`, { data });
      toast(`Sprint salva!`);
    }
    closeModal("modal-sprint");
    State.sprints = await api("GET", "/api/sprints");
    renderSprintsList();
  } catch (e) { toast(e.message, "err"); }
}

async function deleteSprint(name) {
  if (!confirm(`Remover sprint '${name}'?`)) return;
  try {
    await api("DELETE", `/api/sprints/${name}`);
    toast(`Sprint removida.`);
    State.sprints = await api("GET", "/api/sprints");
    renderSprintsList();
  } catch (e) { toast(e.message, "err"); }
}

// ════════════════════════════════════════════════════════════════════
// TAB EXECUÇÕES
// ════════════════════════════════════════════════════════════════════
function statusBadge(status) {
  const map = {
    idle:    ["⏸ idle",    "status-idle"],
    running: ["⚙ running", "status-running"],
    success: ["✅ success", "status-success"],
    error:   ["❌ error",   "status-error"],
    stopped: ["⬛ stopped", "status-stopped"],
  };
  const [label, cls] = map[status] || ["? " + status, "status-idle"];
  return `<span class="status-badge ${cls}">${label}</span>`;
}

function renderExecutionsList() {
  const list = document.getElementById("executions-list");
  list.innerHTML = "";
  if (!State.executions.length) {
    list.innerHTML = '<div class="empty-state">Nenhuma execução cadastrada</div>';
    return;
  }
  State.executions.forEach(ex => {
    const dt         = ex.created_at ? new Date(ex.created_at).toLocaleString("pt-BR") : "";
    const startedAt  = ex.started_at ? new Date(ex.started_at).toLocaleString("pt-BR") : null;
    const finishedAt = ex.finished_at ? new Date(ex.finished_at).toLocaleString("pt-BR") : null;
    const card       = document.createElement("div");
    card.className   = "mgmt-card exec-card";
    card.innerHTML   = `
      <span class="mgmt-card-name" style="cursor:pointer" onclick="openExecConsole('${esc(ex.id)}')">${esc(ex.title || ex.id)}</span>
      <div class="mgmt-card-top">
        <span class="mgmt-card-icon">🚀</span>
        ${statusBadge(ex.status)}
      </div>
      <div class="exec-card-meta">
        <span>🏃 ${esc(ex.sprint)}</span>
        <span>🤖 ${esc(ex.crew)}</span>
        ${startedAt  ? `<span>▶ ${startedAt}</span>`  : `<span>📅 ${dt}</span>`}
        ${finishedAt ? `<span>⏹ ${finishedAt}</span>` : ""}
      </div>
      <div class="mgmt-card-footer">
        <button class="btn-sm btn-edit" onclick="openExecConsole('${esc(ex.id)}')">🖥 Abrir</button>
        <button class="btn-sm btn-danger" onclick="deleteExecution('${esc(ex.id)}')">✕ Remover</button>
      </div>
    `;
    list.appendChild(card);
  });
}

async function newExecutionEditor() {
  // popula selects
  const sprintSel = document.getElementById("exec-editor-sprint");
  const crewSel   = document.getElementById("exec-editor-crew");
  sprintSel.innerHTML = State.sprints.map(s =>
    `<option value="${esc(s.name)}">${esc(s.title || s.name)}</option>`).join("");
  crewSel.innerHTML = State.crews.map(c =>
    `<option value="${esc(c.name)}">${esc(c.name)}</option>`).join("");
  document.getElementById("exec-editor-title").value = "";
  showModal("modal-execution");
}

async function saveExecution() {
  const title   = document.getElementById("exec-editor-title").value.trim();
  const sprint  = document.getElementById("exec-editor-sprint").value;
  const crew    = document.getElementById("exec-editor-crew").value;
  if (!sprint || !crew) { toast("Sprint e Crew são obrigatórios", "err"); return; }
  try {
    const result = await api("POST", "/api/executions", {
      title: title || `${sprint} × ${crew}`, sprint, crew
    });
    toast(`Execução criada! ID: ${result.id}`);
    closeModal("modal-execution");
    State.executions = await api("GET", "/api/executions");
    renderExecutionsList();
    // Abre o console da execução
    openExecConsole(result.id);
  } catch (e) { toast(e.message, "err"); }
}

async function deleteExecution(execId) {
  if (!confirm("Remover esta execução?")) return;
  try {
    await api("DELETE", `/api/executions/${execId}`);
    toast("Execução removida.");
    State.executions = await api("GET", "/api/executions");
    renderExecutionsList();
  } catch (e) { toast(e.message, "err"); }
}

// ─── Console de Execução ─────────────────────────────────────────
async function openExecConsole(execId) {
  // para qualquer polling anterior
  if (State.execPollTimer) { clearInterval(State.execPollTimer); State.execPollTimer = null; }
  State.currentExecId = execId;
  State.execLastLogIdx = 0;

  const data = await api("GET", `/api/executions/${execId}`);
  
  document.getElementById("exec-console-title").textContent =
    data.title || `Execução ${execId}`;
  
  const infoParts = [
    `🏃 Sprint: <b>${esc(data.sprint)}</b>`,
    `🤖 Crew: <b>${esc(data.crew)}</b>`,
  ];
  if (data.started_at) infoParts.push(`▶ Iniciado: ${new Date(data.started_at).toLocaleString("pt-BR")}`);
  if (data.finished_at) infoParts.push(`⏹ Finalizado: ${new Date(data.finished_at).toLocaleString("pt-BR")}`);
  document.getElementById("exec-info-bar").innerHTML = infoParts.join("  ·  ");

  const badge = document.getElementById("exec-console-badge");
  badge.className = "status-badge status-" + data.status;
  badge.textContent = data.status;

  const startBtn = document.getElementById("exec-start-btn");
  const stopBtn  = document.getElementById("exec-stop-btn");

  if (data.status === "running") {
    startBtn.style.display = "none";
    stopBtn.style.display  = "";
  } else {
    startBtn.style.display = "";
    stopBtn.style.display  = "none";
  }

  // Carrega logs iniciais a partir do endpoint de logs (fonte atual),
  // evitando exibir snapshots antigos persistidos no JSON da execução.
  const output = document.getElementById("exec-console-output");
  output.innerHTML = "";
  State.execLastLogIdx = 0;
  try {
    const initial = await api("GET", `/api/executions/${execId}/logs?since=0`);
    initial.logs.forEach(l => appendConsoleLine(l));
    State.execLastLogIdx = initial.total || initial.logs.length;
  } catch (_) {
    // Fallback para compatibilidade com execuções antigas sem endpoint de logs disponível.
    if (data.logs && data.logs.length) {
      data.logs.forEach(l => appendConsoleLine(l));
      State.execLastLogIdx = data.logs.length;
    }
  }

  showModal("modal-exec-console");

  // Se running, inicia polling
  if (data.status === "running") {
    startPolling();
  }
}

function closeExecConsole() {
  if (State.execPollTimer) { clearInterval(State.execPollTimer); State.execPollTimer = null; }
  document.getElementById("exec-input-bar").style.display = "none";
  closeModal("modal-exec-console");
}

// Remove escape codes ANSI que o app.py emite (cores de terminal)
function stripAnsi(str) {
  return str.replace(/\x1b\[[0-9;]*m/g, "");
}

// Padrões que indicam que o processo está aguardando input do usuário (Y/N ou texto livre)
const CONFIRM_PATTERNS = [
  /\(Y\/n\)/i,
  /\(y\/N\)/i,
  /\[Y\/n\]/i,
  /\[y\/N\]/i,
  /Deseja retomar de onde parou\?/i,
  /Carregar AGENT\.md\?/i,
  /confirmar\?/i,
  /\[s\/n\]/i,
  /pressione qualquer tecla/i,
  /aguardando (input|confirmação|resposta)/i,
  /Você ➔\s*$/,          // prompt interativo do COIA aguardando input
];

function appendConsoleLine(raw) {
  const output = document.getElementById("exec-console-output");
  const line = stripAnsi(raw);
  if (!line) return;

  const p = document.createElement("div");
  p.className = "console-line";

  // Erros e falhas
  if (/\[ERRO|CRÍTICO\]|agent_fail|❌|Traceback|Exception|Error:/i.test(line))
    p.classList.add("console-err");
  // Sucesso / conclusão
  else if (/✅|sucesso|\[🚀\].*iniciando|concluído|done/i.test(line))
    p.classList.add("console-ok");
  // Ciclos do orquestrador e tool calls
  else if (/^\[🔄 Ciclo|^\[🔧 Ciclo|\[✅\]|\[EQUIPA\]|\[🚀\]/.test(line))
    p.classList.add("console-info");
  // Saída do agente (AI:) e tokens/custo
  else if (/^AI:|^\s*\[Tokens:|^\s*\[Acumulado:|^\s*\[Gasto/.test(line))
    p.classList.add("console-dim");
  // stdin enviado pelo painel
  else if (/^\[stdin\]/.test(line))
    p.classList.add("console-info");

  p.textContent = line;
  output.appendChild(p);
  output.scrollTop = output.scrollHeight;

  // Detecta prompt de confirmação — exibe barra Y/N
  const inputBar = document.getElementById("exec-input-bar");
  if (inputBar && CONFIRM_PATTERNS.some(r => r.test(line))) {
    inputBar.style.display = "flex";
  }
}

function startPolling() {
  State.execPollTimer = setInterval(async () => {
    if (!State.currentExecId) { clearInterval(State.execPollTimer); return; }
    try {
      // Uma única request traz logs novos + status atual
      const result = await api("GET", `/api/executions/${State.currentExecId}/logs?since=${State.execLastLogIdx}`);
      result.logs.forEach(l => appendConsoleLine(l));
      State.execLastLogIdx += result.logs.length;

      const badge = document.getElementById("exec-console-badge");
      if (badge) { badge.className = "status-badge status-" + result.status; badge.textContent = result.status; }

      if (result.status !== "running") {
        clearInterval(State.execPollTimer);
        State.execPollTimer = null;

        // Faz um último drain de logs para capturar traceback que pode chegar no fim.
        const tail = await api("GET", `/api/executions/${State.currentExecId}/logs?since=${State.execLastLogIdx}`);
        tail.logs.forEach(l => appendConsoleLine(l));
        State.execLastLogIdx += tail.logs.length;

        document.getElementById("exec-start-btn").style.display = "";
        document.getElementById("exec-stop-btn").style.display  = "none";

        // Atualiza info bar com timestamps finais
        const execData = await api("GET", `/api/executions/${State.currentExecId}`);
        const infoParts = [
          `🏃 Sprint: <b>${esc(execData.sprint)}</b>`,
          `🤖 Crew: <b>${esc(execData.crew)}</b>`,
        ];
        if (result.started_at)  infoParts.push(`▶ ${new Date(result.started_at).toLocaleString("pt-BR")}`);
        if (result.finished_at) infoParts.push(`⏹ ${new Date(result.finished_at).toLocaleString("pt-BR")}`);
        document.getElementById("exec-info-bar").innerHTML = infoParts.join("  ·  ");

        State.executions = await api("GET", "/api/executions");
        if (State.activeTab === "executions") renderExecutionsList();
      }
    } catch (_) {}
  }, 1500);
}

async function startExecution() {
  if (!State.currentExecId) return;
  try {
    await api("POST", `/api/executions/${State.currentExecId}/start`);
    toast("Execução iniciada!");
    document.getElementById("exec-start-btn").style.display = "none";
    document.getElementById("exec-stop-btn").style.display  = "";
    const badge = document.getElementById("exec-console-badge");
    badge.className = "status-badge status-running";
    badge.textContent = "running";
    // Limpa console e esconde input bar
    document.getElementById("exec-console-output").innerHTML = "";
    document.getElementById("exec-input-bar").style.display = "none";
    State.execLastLogIdx = 0;
    startPolling();
  } catch (e) { toast(e.message, "err"); }
}

async function stopExecution() {
  if (!State.currentExecId) return;

  // Feedback visual imediato — não espera o servidor
  if (State.execPollTimer) { clearInterval(State.execPollTimer); State.execPollTimer = null; }
  document.getElementById("exec-start-btn").style.display = "";
  document.getElementById("exec-stop-btn").style.display  = "none";
  document.getElementById("exec-input-bar").style.display = "none";
  const fi = document.getElementById("exec-free-input");
  if (fi) fi.value = "";
  const badge = document.getElementById("exec-console-badge");
  if (badge) { badge.className = "status-badge status-stopped"; badge.textContent = "stopped"; }

  try {
    await api("POST", `/api/executions/${State.currentExecId}/stop`);
    toast("Execução parada.");
  } catch (e) {
    toast("Stop enviado (pode haver atraso).", "ok");
  }

  // Faz um último drain de logs para capturar o que saiu antes do kill
  try {
    const tail = await api("GET", `/api/executions/${State.currentExecId}/logs?since=${State.execLastLogIdx}`);
    tail.logs.forEach(l => appendConsoleLine(l));
    State.execLastLogIdx += tail.logs.length;
  } catch (_) {}

  State.executions = await api("GET", "/api/executions");
  if (State.activeTab === "executions") renderExecutionsList();
}

async function sendInput(value) {
  if (!State.currentExecId) return;
  try {
    await api("POST", `/api/executions/${State.currentExecId}/input`, { text: value });
    document.getElementById("exec-input-bar").style.display = "none";
    const fi = document.getElementById("exec-free-input");
    if (fi) fi.value = "";
    toast(`Enviado: ${value}`);
  } catch (e) { toast(e.message, "err"); }
}

async function sendFreeInput() {
  const fi = document.getElementById("exec-free-input");
  const value = fi ? fi.value.trim() : "";
  if (!value) { toast("Digite algo antes de enviar.", "err"); return; }
  await sendInput(value);
}

// ─── INIT ─────────────────────────────────────────────────────────
async function init() {
  try {
    const [skills, mcps, crons, crews, commands, prompts, sprints, executions, tools, defaultSkills] =
      await Promise.all([
        api("GET", "/api/skills"),
        api("GET", "/api/mcps"),
        api("GET", "/api/crons"),
        api("GET", "/api/crews"),
        api("GET", "/api/commands"),
        api("GET", "/api/prompts"),
        api("GET", "/api/sprints"),
        api("GET", "/api/executions"),
        api("GET", "/api/tools"),
      ]);
    State.skills         = skills;
    State.mcps           = mcps;
    State.crons          = crons;
    State.crews          = crews;
    State.commands       = commands;
    State.prompts        = prompts;
    State.sprints        = sprints;
    State.executions     = executions;
    // /api/tools retorna { native: [...], mcp: [...] }
    State.tools = (tools && tools.native) ? tools : { native: tools || [], mcp: [] };
    renderHome();
  } catch (e) {
    toast("Erro ao carregar dados do servidor.", "err");
  }
}

document.addEventListener("DOMContentLoaded", () => {
  init().then(() => {
    const tab = location.hash.replace("#", "");
    if (tab && TAB_DEPS[tab]) showTab(tab);
  });
});

// Atualiza dados da aba ativa quando o usuário volta para esta aba do browser
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible") {
    refreshTabData(State.activeTab).then(() => {
      if (TAB_RENDER[State.activeTab]) TAB_RENDER[State.activeTab]();
    });
  }
});
