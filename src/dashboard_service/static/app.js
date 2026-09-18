"use strict";


const $ = (id) => document.getElementById(id);
const state = { mode: null, drones: [], mission: null, reform: null, move: null };
let configPlan = null;
const busy = new Set();

// ------------------------------------------------------------------ helpers

function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = value;
    else node.setAttribute(key, value);
  }
  node.append(...children);
  return node;
}

function svgEl(tag, attrs, text) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  if (text !== undefined) node.textContent = text;
  return node;
}

const fmt = (v, digits = 2) => (typeof v === "number" && isFinite(v) ? v.toFixed(digits) : "—");
const list = (xs) => (Array.isArray(xs) && xs.length ? xs.join(", ") : "none");
const pill = (value) => el("span", { class: `pill pill-${value}`, text: value });
const time = (seconds) => new Date(seconds * 1000).toLocaleTimeString();

function battery(drone) {
  for (const [key, value] of Object.entries(drone.crazyflie_status || {})) {
    if (/batt/i.test(key) && typeof value === "number") {
      return /volt/i.test(key) ? `${value.toFixed(2)} V` : String(value);
    }
  }
  return "—";
}

async function api(method, service, path, body) {
  const options = { method, headers: {} };
  if (method === "POST") {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body ?? {});
  }
  let response;
  try {
    response = await fetch(`/api/${service}${path}`, options);
  } catch (err) {
    throw new Error(`dashboard is unreachable (${err.message})`);
  }
  let data = null;
  try { data = await response.json(); } catch { data = null; }
  if (!response.ok) {
    const detail = data && data.detail !== undefined
      ? (typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail))
      : response.statusText;
    throw new Error(`${response.status}: ${detail}`);
  }
  return data;
}

function setLight(name, ok, message) {
  const node = $(`light-${name}`);
  node.className = `light ${ok ? "ok" : "bad"}`;
  node.title = ok ? "reachable" : message;
}

function log(message, kind = "") {
  const box = $("log");
  box.prepend(el("li", { class: kind }, el("time", { text: new Date().toLocaleTimeString() }),
                                        el("span", { text: message })));
  while (box.children.length > 80) box.lastChild.remove();
}

// ------------------------------------------------------------------ actions

const actions = {
  "btn-start": {
    run: () => api("POST", "mission", "/start", { setup_hover: true }),
    confirm: () => state.mode === "mock"
      ? "Start the mission in mock mode (no real drones)?"
      : `Start the mission?\n\nMode: ${state.mode || "unknown"}.\n` +
        "This arms and takes off every configured drone, then flies the first formation.",
  },
  "btn-stop": {
    run: () => api("POST", "mission", "/stop"),
  },
  "btn-reform": {
    run: () => api("POST", "mission", "/reform_now"),
    confirm: () => "Rebuild the formation around the drones that are not down, and fly them there now?",
  },
  "btn-land": {
    run: () => api("POST", "mission", "/shutdown", { land: true, disarm: true, release_api_control: true }),
    confirm: () => "Land and disarm every drone, and stop the mission loop?",
  },
  "btn-config-check": {
    run: () => checkConfig(),
  },
  "btn-config-apply": {
    run: () => applyConfig(),
    enabled: () => Boolean(configPlan && configPlan.changed),
    confirm: () => "Write these drone IDs into config.yaml?\n\n" +
      "A backup is saved first. Services keep running with the old settings until you restart them.",
  },
  "btn-random": {
    run: () => {
      const count = parseInt($("random-count").value, 10);
      if (!(count >= 1)) throw new Error("enter how many drones to down (1 or more)");
      return api("POST", "simulator", "/down", { count, disarm: true });
    },
    confirm: () => `Down ${$("random-count").value} random drone(s)? They land and disarm.`,
  },
};

async function checkConfig() {
  const plan = await api("GET", "config", "/drones");
  renderConfig(plan);
  return plan;
}

async function applyConfig() {
  const typed = $("config-formation").value.trim();
  const plan = await api("POST", "config", "/drones", { formation: typed || null });
  renderConfig(plan);
  return plan;
}

function renderConfig(plan) {
  configPlan = plan;
  const error = $("config-error");
  error.hidden = true;
  $("config-result").hidden = false;

  const warning = $("config-warning");
  warning.hidden = !(plan.warnings && plan.warnings.length);
  warning.textContent = (plan.warnings || []).join(" ");

  const summary = $("config-summary");
  summary.replaceChildren(
    fact("Enabled in CrazySwarm", list(plan.drones.map((d) => d.id))),
    fact("In config.yaml now", list(plan.current.ids)),
    fact("Change needed", plan.changed ? "yes" : "no, already matching"));
  if (plan.backup) summary.append(fact("Backup saved", plan.backup));
  if (plan.backup) summary.append(fact("Now restart", plan.restart));

  const note = $("config-formation-note");
  const source = plan.proposed.formation_source;
  note.textContent = source === "suggested"
    ? `suggested for ${plan.proposed.ids.length} drones; edit if you want a different shape`
    : source === "unchanged" ? "unchanged: your current rows already fit" : "your rows";
  if (document.activeElement !== $("config-formation")) {
    $("config-formation").value = plan.proposed.formation.join(", ");
  }

  const body = $("config-body");
  body.replaceChildren();
  for (const drone of plan.drones) {
    body.append(el("tr", {},
      el("td", { text: drone.name }),
      el("td", { text: drone.uri }),
      el("td", { class: "num", text: String(drone.id) }),
      el("td", { text: drone.initial_position || "—" })));
  }
  $("config-diff").textContent = plan.diff || "No changes needed.";
  syncButtons();
}

function summarise(result) {
  if (!result || typeof result !== "object") return "done";
  if (Array.isArray(result.drones) && result.proposed) {
    return result.backup ? `config.yaml updated (backup ${result.backup})`
         : result.changed ? `${result.drones.length} drones found; press Apply to write`
         : "config.yaml already matches";
  }
  if (Array.isArray(result.requested_downed_ids)) return `downed ${list(result.requested_downed_ids)}`;
  if (result.move && Array.isArray(result.move.move_results)) {
    const moves = result.move.move_results;
    return `${moves.filter((m) => m.status === "arrived").length} of ${moves.length} drones arrived`;
  }
  if (typeof result.status === "string") return result.status;
  return "done";
}

async function runAction(key, label, run, confirmText) {
  if (busy.has(key)) return;
  if (confirmText && !window.confirm(confirmText)) return;
  busy.add(key);
  syncButtons();
  renderDrones();
  log(`${label}…`);
  try {
    log(`${label}: ${summarise(await run())}`, "ok");
  } catch (err) {
    log(`${label} failed: ${err.message}`, "bad");
    if (key.startsWith("btn-config")) {
      configPlan = null;
      const error = $("config-error");
      error.hidden = false;
      error.textContent = err.message;
    }
  } finally {
    busy.delete(key);
    syncButtons();
    renderDrones();
  }
}

function syncButtons() {
  for (const [id, action] of Object.entries(actions)) {
    const button = $(id);
    button.disabled = busy.has(id) || (action.enabled ? !action.enabled() : false);
    button.textContent = busy.has(id) ? "Working…" : action.text;
  }
}

for (const [id, action] of Object.entries(actions)) {
  const button = $(id);
  action.text = button.textContent;
  button.addEventListener("click", () =>
    runAction(id, action.text, action.run, action.confirm ? action.confirm() : null));
}

// ------------------------------------------------------------------ rendering

function renderMode() {
  // Never show a remembered mode: if the latest reply didn't say, we don't know.
  const mode = state.mode;
  const badge = $("mode");
  badge.textContent = mode === "mock" ? "MOCK: no real drones"
                    : mode === "crazyswarm" ? "CRAZYSWARM: real drones"
                    : mode ? `mode: ${mode}` : "mode unknown";
  badge.className = `badge ${mode === "mock" ? "mock" : mode === "crazyswarm" ? "real" : ""}`;
}

function renderHealth(health) {
  state.mode = health.mode || null;
  renderMode();

  const backend = $("m-backend");
  if (health.status === "ok") {
    backend.replaceChildren(pill("ok"));
  } else {
    backend.replaceChildren(pill("degraded"), ` ${health.backend_error || ""}`);
  }
}

function renderMission() {
  const m = state.mission;
  if (!m) return;
  $("m-running").replaceChildren(pill(m.running ? "running" : "stopped"));
  $("m-setup").textContent = m.setup_done ? "yes" : "no";
  $("m-initial").textContent = m.initial_formation_done ? "yes" : "no";
  $("m-downed").textContent = list(m.last_downed);
  const error = $("mission-error");
  error.hidden = !m.last_error;
  error.textContent = m.last_error ? `last_error: ${m.last_error}` : "";
}

function renderDrones() {
  const body = $("drones-body");
  body.replaceChildren();
  for (const drone of state.drones) {
    const key = `down-${drone.drone_id}`;
    const button = el("button", { class: "small danger", text: busy.has(key) ? "Working…" : "Down" });
    button.disabled = drone.status === "down" || busy.has(key);
    button.addEventListener("click", () => runAction(
      key, `Down drone ${drone.drone_id}`,
      () => api("POST", "simulator", "/down", { drone_ids: [drone.drone_id], disarm: true }),
      `Down drone ${drone.drone_id}? It lands and disarms, and mission rebuilds the formation.`));

    const noPose = drone.position_received === false;
    body.append(el("tr", {},
      el("td", { text: drone.name ? `${drone.drone_id} (${drone.name})` : String(drone.drone_id) }),
      el("td", {}, pill(drone.status || "unknown")),
      el("td", { class: "num", text: fmt(drone.x) }),
      el("td", { class: "num", text: fmt(drone.y) }),
      el("td", { class: "num", text: fmt(drone.z) }),
      noPose ? el("td", {}, pill("down"), " none") : el("td", { text: "ok" }),
      el("td", { class: "num", text: battery(drone) }),
      el("td", {}, button)));
  }
}

function renderMap() {
  const svg = $("map");
  svg.replaceChildren();
  const size = 400, margin = 28;
  const drones = state.drones;
  const targets = state.reform && Array.isArray(state.reform.target_positions_world)
    ? state.reform.target_positions_world : [];

  const xs = [...drones.map((d) => d.x), ...targets.map((t) => t[0])];
  const ys = [...drones.map((d) => d.y), ...targets.map((t) => t[1])];
  if (!xs.length) {
    svg.append(svgEl("text", { x: size / 2, y: size / 2, "text-anchor": "middle", class: "map-text" },
                     "No drone positions yet"));
    return;
  }

  const minX = Math.min(...xs) - 0.5, maxX = Math.max(...xs) + 0.5;
  const minY = Math.min(...ys) - 0.5, maxY = Math.max(...ys) + 0.5;
  const span = Math.max(maxX - minX, maxY - minY, 1);
  const scale = (size - 2 * margin) / span;
  const midX = (minX + maxX) / 2, midY = (minY + maxY) / 2;
  const px = (x) => size / 2 + (x - midX) * scale;
  const py = (y) => size / 2 - (y - midY) * scale;

  // Grid every 0.5 m; the x=0 and y=0 lines are drawn darker.
  const step = 0.5;
  const lo = (mid) => Math.ceil((mid - span / 2) / step);
  const hi = (mid) => Math.floor((mid + span / 2) / step);
  for (let i = lo(midX); i <= hi(midX); i++) {
    const x = px(i * step);
    svg.append(svgEl("line", { x1: x, y1: 0, x2: x, y2: size, class: i === 0 ? "axis" : "grid" }));
  }
  for (let i = lo(midY); i <= hi(midY); i++) {
    const y = py(i * step);
    svg.append(svgEl("line", { x1: 0, y1: y, x2: size, y2: y, class: i === 0 ? "axis" : "grid" }));
  }
  svg.append(svgEl("text", { x: size / 2, y: 14, "text-anchor": "middle", class: "map-text" }, "+y (front)"));
  svg.append(svgEl("text", { x: size - 6, y: size / 2 - 6, "text-anchor": "end", class: "map-text" }, "+x"));
  svg.append(svgEl("text", { x: 6, y: size - 8, class: "map-text" }, "grid: 0.5 m"));

  for (const [x, y] of targets) {
    svg.append(svgEl("circle", { cx: px(x), cy: py(y), r: 11, class: "target" }));
  }
  // Downed drones sit on the floor, and the mission is allowed to fly another drone
  // over the same spot. Draw them last, as a cross with the label below, so a
  // drone hovering above can't hide them.
  const flying = drones.filter((d) => d.status !== "down");
  const downed = drones.filter((d) => d.status === "down");
  for (const drone of flying) {
    const x = px(drone.x), y = py(drone.y);
    svg.append(svgEl("circle", { cx: x, cy: y, r: 8, class: `dot dot-${drone.status}` }));
    svg.append(svgEl("text", { x: x + 11, y: y - 9, class: "dot-label" }, String(drone.drone_id)));
  }
  for (const drone of downed) {
    const x = px(drone.x), y = py(drone.y), r = 7;
    svg.append(svgEl("line", { x1: x - r, y1: y - r, x2: x + r, y2: y + r, class: "down-mark" }));
    svg.append(svgEl("line", { x1: x - r, y1: y + r, x2: x + r, y2: y - r, class: "down-mark" }));
    svg.append(svgEl("text", { x: x + 11, y: y + 20, class: "down-label" }, `${drone.drone_id} down`));
  }
}

function fact(label, value) {
  return el("span", {}, el("span", { class: "k", text: label }), el("span", { text: value }));
}

function renderReform() {
  const r = state.reform;
  const summary = $("reform-summary"), body = $("assign-body");
  body.replaceChildren();
  if (!r || r.status === "no_reform_yet") {
    summary.textContent = "No reform yet. The first one happens when the mission flies the first formation.";
    return;
  }
  if (r.status === "no_active_drones") {
    summary.textContent = `No drones left to fly (downed: ${list(r.downed)}).`;
    return;
  }
  const rows = r.formation && Array.isArray(r.formation.new_formation)
    ? `[${r.formation.new_formation.join(", ")}]` : "—";
  const total = r.hungarian && r.hungarian.summary
    ? `${fmt(r.hungarian.summary.total_travel_distance)} m` : "—";
  summary.replaceChildren(
    fact("At", r.at ? time(r.at) : "—"),
    fact("Downed", list(r.downed)),
    fact("Flying", list(r.active_ids)),
    fact("Rows, front first", rows),
    fact("Total distance", total));

  const assignment = ((r.hungarian && r.hungarian.assignment) || [])
    .slice().sort((a, b) => (a.cascade_rank ?? 0) - (b.cascade_rank ?? 0));
  for (const item of assignment) {
    const [tx, ty] = item.target_position || [];
    body.append(el("tr", {},
      el("td", { class: "num", text: String(item.cascade_rank ?? "—") }),
      el("td", { text: String(item.drone_id) }),
      el("td", { class: "num", text: String(item.slot_idx) }),
      el("td", { class: "num", text: fmt(tx) }),
      el("td", { class: "num", text: fmt(ty) }),
      el("td", { class: "num", text: `${fmt(item.travel_distance)} m` })));
  }
}

function renderMove() {
  const m = state.move;
  const note = $("move-note"), body = $("move-body");
  body.replaceChildren();
  if (!m || m.status === "no_move_yet") {
    note.textContent = "No moves yet. This fills in once every drone in a reform has finished moving.";
    return;
  }
  if (!Array.isArray(m.move_results)) {
    note.textContent = m.status ? `Status: ${m.status}` : "";
    return;
  }
  note.textContent = m.at ? `Finished at ${time(m.at)}.` : "";
  for (const result of m.move_results) {
    body.append(el("tr", {},
      el("td", { text: String(result.drone_id) }),
      el("td", {}, pill(result.status)),
      el("td", { class: "num", text: String(result.steps ?? "—") }),
      el("td", { class: "num", text: String(result.blocked_count ?? "—") }),
      el("td", { class: "num", text: typeof result.elapsed_seconds === "number" ? `${fmt(result.elapsed_seconds, 1)} s` : "—" }),
      el("td", { text: result.reason || result.last_block_reason || "" })));
  }
}

// ------------------------------------------------------------------ polling

async function pollDrones() {
  const error = $("drones-error");
  try {
    const data = await api("GET", "control", "/drones/status");
    state.drones = (data.drones || []).slice().sort((a, b) => a.drone_id - b.drone_id);
    error.hidden = true;
  } catch (err) {
    error.hidden = false;
    error.textContent = `Can't read drone status: ${err.message}`;
  }
  renderDrones();
  renderMap();
}

async function pollMission() {
  try {
    state.mission = await api("GET", "mission", "/status");
    setLight("mission", true);
    renderMission();
  } catch (err) {
    setLight("mission", false, err.message);
  }
}

async function pollResults() {
  try {
    const [reform, move] = await Promise.all([
      api("GET", "mission", "/last_reform"),
      api("GET", "mission", "/last_move"),
    ]);
    state.reform = reform;
    state.move = move;
    renderReform();
    renderMove();
    renderMap();
  } catch {
    // pollMission already shows mission as unreachable.
  }
}

async function pollHealth() {
  try {
    renderHealth(await api("GET", "control", "/health"));
    setLight("control", true);
  } catch (err) {
    setLight("control", false, err.message);
    state.mode = null;
    renderMode();
    $("m-backend").textContent = "unknown (Docker 1 unreachable)";
  }
  try {
    await api("GET", "simulator", "/health");
    setLight("simulator", true);
  } catch (err) {
    setLight("simulator", false, err.message);
  }
}

function every(ms, fn) {
  let running = false;
  const tick = async () => {
    if (running) return;
    running = true;
    try { await fn(); } finally { running = false; }
  };
  tick();
  setInterval(tick, ms);
}

syncButtons();   // Apply starts disabled until Check has shown what would change.
every(1000, pollDrones);
every(1000, pollMission);
every(2000, pollResults);
every(3000, pollHealth);
log("Dashboard opened. Status refreshes every second.");

// ------------------------------------------------------------------ tabs

function showTab(name) {
  for (const button of document.querySelectorAll(".tabs button")) {
    button.classList.toggle("active", button.dataset.tab === name);
  }
  for (const section of document.querySelectorAll("main .tab")) {
    section.classList.toggle("active", section.id === `tab-${name}`);
  }
  if (name === "config" && !configLoaded) {
    configLoaded = true;
    runAction("btn-params-reload", "Load settings", loadParameters, null);
    loadFile("config");
    loadFile("crazyflies");
  }
}

for (const button of document.querySelectorAll(".tabs button")) {
  button.addEventListener("click", () => showTab(button.dataset.tab));
}

// ------------------------------------------------------- config: settings

let configLoaded = false;
let parameters = [];

function wire(id, spec) {
  const button = $(id);
  spec.text = button.textContent;
  actions[id] = spec;
  button.addEventListener("click", () =>
    runAction(id, spec.text, spec.run, spec.confirm ? spec.confirm() : null));
}

function paramInput(item) {
  if (item.type === "choice") {
    const select = el("select", { id: `p-${item.id}` });
    for (const choice of item.choices || []) {
      const option = el("option", { value: choice, text: choice });
      if (choice === item.value) option.selected = true;
      select.append(option);
    }
    return select;
  }
  if (item.type === "bool") {
    const select = el("select", { id: `p-${item.id}` });
    for (const choice of ["true", "false"]) {
      const option = el("option", { value: choice, text: choice });
      if (choice === String(item.value)) option.selected = true;
      select.append(option);
    }
    return select;
  }
  const input = el("input", { id: `p-${item.id}`, type: "text", inputmode: "decimal" });
  input.value = item.value === null ? "" : item.value;
  return input;
}

function renderParameters(data) {
  parameters = data.parameters;
  const box = $("params-box");
  box.replaceChildren();
  $("params-path").textContent = data.path;
  renderWarnings("params-warning", data.warnings);

  for (const section of ["drones", "mission"]) {
    const items = parameters.filter((p) => p.section === section);
    if (!items.length) continue;
    box.append(el("div", { class: "section-title", text: section === "drones"
      ? "drones: how each drone is flown" : "mission: how the formation is rebuilt" }));
    for (const item of items) {
      const field = el("div", { class: `param${item.present ? "" : " missing"}`, id: `wrap-${item.id}` });
      field.append(el("label", { for: `p-${item.id}`, text: item.unit ? `${item.label} (${item.unit})` : item.label }));
      field.append(paramInput(item));
      field.append(el("div", { class: "meta", text: item.present
        ? `${item.help} Read by ${item.read_by}.` : `Not in config.yaml. ${item.help}` }));
      box.append(field);
    }
  }
  for (const item of parameters) {
    const input = $(`p-${item.id}`);
    if (input) input.addEventListener("input", markChanged);
    if (input) input.addEventListener("change", markChanged);
  }
  markChanged();
}

function changedParameters() {
  return parameters.filter((item) => {
    const input = $(`p-${item.id}`);
    return input && item.present && input.value.trim() !== String(item.value ?? "").trim();
  });
}

function markChanged() {
  const changed = new Set(changedParameters().map((item) => item.id));
  for (const item of parameters) {
    const wrap = $(`wrap-${item.id}`);
    if (wrap) wrap.classList.toggle("changed", changed.has(item.id));
  }
  $("params-count").textContent = changed.size
    ? `${changed.size} setting${changed.size > 1 ? "s" : ""} changed` : "no changes yet";
  syncButtons();
}

async function loadParameters() {
  const data = await api("GET", "config", "/parameters");
  renderParameters(data);
  return data;
}

function edits() {
  return changedParameters().map((item) => ({ id: item.id, value: $(`p-${item.id}`).value.trim() }));
}

async function saveParameters() {
  const result = await api("POST", "config", "/parameters", { edits: edits() });
  renderResult("params-result", result);
  await loadParameters();
  await loadFile("config");
  return result;
}

// ----------------------------------------------------------- config: files

async function loadFile(key) {
  try {
    const data = await api("GET", "config", `/file/${key}`);
    if (key === "config") {
      $("raw-text").value = data.text;
      $("raw-path").textContent = `${data.path} — ${data.blurb}`;
      renderWarnings("raw-warning", data.parse_error ? [data.parse_error] : data.warnings);
    } else {
      $("cf-text").textContent = data.text;
      $("cf-path").textContent = `${data.path} — ${data.blurb}`;
    }
  } catch (err) {
    if (key === "config") renderWarnings("raw-warning", [err.message]);
    else $("cf-text").textContent = err.message;
  }
}

async function saveRaw() {
  const result = await api("POST", "config", "/raw", { text: $("raw-text").value });
  renderResult("raw-result", result);
  await loadFile("config");
  await loadParameters();
  return result;
}

// ------------------------------------------------------------------ shared

function renderWarnings(id, messages) {
  const box = $(id);
  const list = (messages || []).filter(Boolean);
  box.hidden = !list.length;
  box.textContent = list.join("\n");
}

function renderResult(id, result) {
  const box = $(id);
  box.hidden = false;
  box.replaceChildren();
  if (!result.changed) {
    box.append(el("p", { class: "hint", text: "No change: the file already says that." }));
    return;
  }
  box.append(el("div", { class: "summary" },
    fact("Saved", "yes"),
    fact("Backup", result.backup || "—"),
    fact("Now restart", result.restart)));
  box.append(el("pre", { class: "diff", text: result.diff }));
}

wire("btn-params-reload", { run: loadParameters });
wire("btn-params-save", {
  run: saveParameters,
  enabled: () => changedParameters().length > 0,
  confirm: () => `Save ${changedParameters().length} changed setting(s) to config.yaml?\n\n` +
    "A backup is kept. Services keep running with the old values until you restart them.",
});
wire("btn-raw-reload", { run: () => loadFile("config") });
wire("btn-raw-save", {
  run: saveRaw,
  confirm: () => "Save config.yaml as shown?\n\nIt is checked for valid YAML first, and a backup is kept.",
});
syncButtons();
