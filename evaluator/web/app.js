// Developer console for the local evaluator. Views only use LabApi so the
// browser never creates an undocumented route or substitutes fake evidence.
const $ = (id) => document.getElementById(id);
const api = window.LabApi;
const TABS = ["overview", "calls", "experiments", "compare", "chat"];
const PAGE_SIZE = 15;

let runs = [];
let profiles = [];
let scenarios = [];
let current = null;
let calls = [];
let manualCalls = [];
let callsPage = 0;
let callsLoaded = false;
let chatSession = null;
let chatTurns = [];
let mic = null;

function esc(value) {
  const node = document.createElement("div");
  node.textContent = value == null ? "" : String(value);
  return node.innerHTML;
}

function table(headers, rows) {
  const head = headers.map((value) => `<th>${esc(value)}</th>`).join("");
  const body = rows.map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`).join("");
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

function showError(error) {
  $("error").textContent = error.message || String(error);
  $("error").hidden = false;
}

function clearError() {
  $("error").hidden = true;
}

function verdictBadge(verdict) {
  const labels = {
    pass: ["correcta", "ok"],
    fail: ["incorrecta", "fail"],
    invalid_evaluation: ["no evaluable", "invalid"],
    informative: ["informativa", "neutral"],
  };
  const [label, style] = labels[verdict] || [verdict || "sin resultado", "neutral"];
  return `<span class="badge ${style}">${esc(label)}</span>`;
}

function originBadge(origin) {
  const labels = { real: "real", simulated: "simulada", manual: "manual" };
  return `<span class="origin origin-${esc(origin)}">${esc(labels[origin] || origin || "desconocido")}</span>`;
}

function evidenceText(evidence = {}) {
  return ["audio", "transcript", "cost", "outcome"]
    .map((key) => `${key}: ${evidence[key] || "unknown"}`)
    .join(" · ");
}

function formatDate(value) {
  if (!value) return "sin fecha";
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? value : date.toLocaleString("es-ES", { dateStyle: "medium", timeStyle: "short" });
}

// ---- navigation ------------------------------------------------------------

$("tabs").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-tab]");
  if (!button) return;
  const tab = button.dataset.tab;
  $("tabs").querySelectorAll("button").forEach((item) => item.classList.toggle("on", item === button));
  TABS.forEach((name) => ($(`tab-${name}`).hidden = name !== tab));
  if (tab === "calls") loadCalls().catch(showError);
  if (tab === "experiments") renderExperimentRuns().catch(showError);
  window.scrollTo({ top: 0, behavior: "auto" });
});

// ---- overview and shared run selection ------------------------------------

function runOptions() {
  return runs
    .map((run) => `<option value="${esc(run.run_id)}">${esc(run.experiment)} · ${esc(run.run_id)} · ${esc(run.cases)} casos</option>`)
    .join("");
}

function candidatesFor(runId) {
  return runs.find((run) => run.run_id === runId)?.candidates || [];
}

function syncCandidateSelect(side) {
  const runId = $(`diff-${side}`).value;
  const candidates = candidatesFor(runId);
  $(`diff-cand-${side}`).innerHTML = `${candidates.length > 1 ? '<option value="">elegir</option>' : ""}${candidates.map((candidate) => `<option value="${esc(candidate)}">${esc(candidate)}</option>`).join("")}`;
}

async function loadRuns() {
  runs = await api.getRuns();
  const options = runOptions() || '<option value="">sin corridas</option>';
  $("run").innerHTML = options;
  $("diff-a").innerHTML = options;
  $("diff-b").innerHTML = options;
  if (runs.length > 1) $("diff-b").selectedIndex = 1;
  syncCandidateSelect("a");
  syncCandidateSelect("b");
  await renderExperimentRuns();
  if (runs.length) await selectRun(runs[0].run_id);
  else renderEmptyOverview();
}

async function selectRun(runId) {
  if (!runId) return;
  clearError();
  $("run").value = runId;
  $("report").href = `/api/runs/${encodeURIComponent(runId)}/report`;
  const [detail, comparison] = await Promise.all([api.getRun(runId), api.getComparison(runId)]);
  current = detail;
  renderOverview(detail);
  renderComparison(comparison);
}

function renderEmptyOverview() {
  $("bench-title").textContent = "Sin corridas todavía";
  $("bench-facts").textContent = "El laboratorio mostrará aquí la población evaluada cuando exista evidencia.";
  $("bench-cards").innerHTML = '<div class="empty"><h3>No hay resultados</h3><p>Creá una corrida desde la API del evaluador o ejecutá un experimento por CLI. La consola no inventa métricas.</p></div>';
  $("matrix").innerHTML = "";
}

function renderOverview(detail) {
  const manifest = detail.manifest || {};
  const metrics = detail.metrics || {};
  const candidates = metrics.candidates || {};
  $("bench-title").textContent = manifest.experiment || detail.run_id;
  $("bench-facts").innerHTML = [
    ["corrida", detail.run_id],
    ["dataset", manifest.dataset || "n/d"],
    ["reglas", manifest.rules_version || "n/d"],
    ["repeticiones", manifest.repetitions ?? "n/d"],
  ].map(([label, value]) => `<span>${esc(label)}: <b>${esc(value)}</b></span>`).join("");

  const names = Object.keys(candidates);
  $("bench-cards").innerHTML = names.length
    ? names.map((name) => {
      const value = (key) => candidates[name]?.[key]?.value ?? "n/d";
      return `<article class="card"><h3>${esc(name)}</h3><p class="big">${esc(value("pass_rate"))}</p><p class="meta">aciertos sobre casos evaluables</p><dl>
        <div><dt>casos</dt><dd>${esc(value("cases"))}</dd></div>
        <div><dt>estabilidad</dt><dd>${esc(value("stability"))}</dd></div>
        <div><dt>primera respuesta p50</dt><dd>${esc(value("first_audio_p50"))}</dd></div>
        <div><dt>coste</dt><dd>${esc(value("cost_total"))}</dd></div>
      </dl></article>`;
    }).join("")
    : '<div class="empty"><h3>La corrida no tiene agregados</h3><p>La evidencia permanece disponible en Llamadas si el artefacto contiene casos.</p></div>';

  const problems = metrics.problems || [];
  $("matrix").innerHTML = problems.length
    ? table(["problema", ...names], problems.map((problem) => [
      esc(problem),
      ...names.map((name) => {
        const cell = metrics.matrix?.[problem]?.[name];
        return cell ? `${esc(cell.passed)}/${esc(cell.valid)}${cell.invalid ? ` <span class="meta">+${esc(cell.invalid)} inv.</span>` : ""}` : "—";
      }),
    ]))
    : "";
}

$("run").addEventListener("change", (event) => selectRun(event.target.value).catch(showError));
$("reload").addEventListener("click", () => {
  callsLoaded = false;
  loadRuns().catch(showError);
});
$("diff-a").addEventListener("change", () => syncCandidateSelect("a"));
$("diff-b").addEventListener("change", () => syncCandidateSelect("b"));

// ---- historical calls ------------------------------------------------------

function toCallRecord(caseResult) {
  return {
    ...caseResult,
    id: caseResult.id || `${caseResult.run_id || "run"}:${caseResult.case_id || caseResult.call_id}`,
    origin: caseResult.origin || "simulated",
    profile: caseResult.candidate || caseResult.profile_id || "n/d",
    scenario: caseResult.scenario_id || "—",
    actions: caseResult.submitted || caseResult.actions || [],
  };
}

async function loadCalls() {
  if (callsLoaded) return renderCalls();
  $("calls-status").textContent = "Reconstruyendo el historial local…";
  await api.importHistory();
  const rows = [];
  let page = 1;
  do {
    const result = await api.getHistoryCalls(new URLSearchParams({ page, page_size: 100 }));
    rows.push(...result.items);
    page = result.next_page;
  } while (page);
  calls = rows.map(toCallRecord);
  callsLoaded = true;
  renderCalls();
}

function filteredCalls() {
  const origin = $("call-origin").value;
  const result = $("call-result").value;
  const profile = $("call-profile").value.trim().toLocaleLowerCase();
  const scenario = $("call-scenario").value.trim().toLocaleLowerCase();
  return calls.filter((call) =>
    (!origin || call.origin === origin) &&
    (!result || (result === "informative" ? !call.verdict : call.verdict === result)) &&
    (!profile || String(call.profile).toLocaleLowerCase().includes(profile)) &&
    (!scenario || String(call.scenario).toLocaleLowerCase().includes(scenario)),
  );
}

function renderCalls() {
  const filtered = filteredCalls();
  const pages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  callsPage = Math.min(callsPage, pages - 1);
  const page = filtered.slice(callsPage * PAGE_SIZE, (callsPage + 1) * PAGE_SIZE);
  $("calls-status").textContent = filtered.length
    ? `${filtered.length} llamada(s) en la población filtrada. Evidencia parcial sigue indicada por llamada.`
    : "No hay llamadas que coincidan con estos filtros.";
  $("calls-list").innerHTML = page.length ? `<div class="tablewrap">${table(
    ["origen", "inicio", "perfil", "escenario", "resultado", "evidencia", ""],
    page.map((call) => [
      originBadge(call.origin),
      esc(formatDate(call.started_at)),
      esc(call.profile),
      `<code>${esc(call.scenario)}</code>`,
      verdictBadge(call.verdict || "informative"),
      `<span class="meta">${esc(evidenceText(call.evidence))}</span>`,
      `<button class="small" data-call-detail="${esc(call.id)}" type="button">Ver detalle</button>`,
    ]),
  )}</div>` : '<div class="empty"><h3>Sin evidencia para mostrar</h3><p>Probá otro filtro o recargá las corridas. Una respuesta de API vacía no se rellena con ejemplos ficticios.</p></div>';
  $("call-pagination").hidden = filtered.length <= PAGE_SIZE;
  $("calls-page").textContent = `Página ${callsPage + 1} de ${pages}`;
  $("calls-prev").disabled = callsPage === 0;
  $("calls-next").disabled = callsPage >= pages - 1;
}

function actionHtml(action) {
  const fields = Object.entries(action || {}).map(([key, value]) => `<div><span>${esc(key)}</span><code>${esc(typeof value === "object" ? JSON.stringify(value) : value)}</code></div>`).join("");
  return `<article class="action-card">${fields || "sin acciones registradas"}</article>`;
}

function renderCallDetail(call) {
  const events = call.transcript_events || call.transcript_fragments || [];
  const audio = Object.entries(call.audio || {}).map(([stream]) => {
    if (!call.run_id || !call.case_id) return "";
    const url = `/api/runs/${encodeURIComponent(call.run_id)}/evidence/${encodeURIComponent(stream)}?case_id=${encodeURIComponent(call.case_id)}`;
    return `<label>${esc(stream)}<audio controls preload="none" src="${url}"></audio></label>`;
  }).join("") || '<p class="meta">Audio no disponible para esta llamada.</p>';
  const transcript = events.length
    ? events.map((event) => `<li class="transcript-${esc(event.role)}"><span>${esc(event.role)}</span><p>${esc(event.text)}</p><small>${esc(event.timestamp || (event.offset_s != null ? `${event.offset_s}s` : "sin marca"))}${event.fragment ? " · fragmento" : ""}</small></li>`).join("")
    : '<li class="empty-line">Transcripción no disponible. La ausencia de texto no implica silencio.</li>';
  const actions = call.actions.length ? call.actions.map(actionHtml).join("") : '<p class="meta">No hay acciones registradas.</p>';
  const result = call.verdict
    ? `${verdictBadge(call.verdict)} ${esc(call.failure_signal || "")}`
    : verdictBadge("informative");
  $("call-detail").hidden = false;
  $("call-detail").innerHTML = `<div class="detail-head"><div><p class="kicker">${originBadge(call.origin)} detalle</p><h2>${esc(call.call_id || call.case_id)}</h2><p class="meta">${esc(call.profile)} · ${esc(call.scenario)} · ${esc(formatDate(call.started_at))}</p></div><button id="call-detail-close" type="button" aria-label="Cerrar detalle">Cerrar</button></div>
    <div class="detail-grid"><section><h3>Resultado</h3><p>${result}</p><p class="meta">${esc(evidenceText(call.evidence))}</p></section><section><h3>Audio</h3>${audio}</section></div>
    <h3>Conversación registrada</h3><ol class="transcript">${transcript}</ol>
    <h3>Acciones y submissions</h3><div class="actions">${actions}</div>
    ${call.errors?.length ? `<h3>Errores del rig</h3><pre class="log">${esc(call.errors.join("\n"))}</pre>` : ""}`;
  $("call-detail-close").addEventListener("click", () => ($("call-detail").hidden = true));
  $("call-detail").scrollIntoView({ behavior: "smooth", block: "start" });
}

$("call-filters").addEventListener("input", () => { callsPage = 0; renderCalls(); });
$("call-filters").addEventListener("reset", () => setTimeout(() => { callsPage = 0; renderCalls(); }));
$("calls-prev").addEventListener("click", () => { callsPage -= 1; renderCalls(); });
$("calls-next").addEventListener("click", () => { callsPage += 1; renderCalls(); });
$("calls-list").addEventListener("click", (event) => {
  const button = event.target.closest("[data-call-detail]");
  if (!button) return;
  api.getHistoryCall(button.dataset.callDetail)
    .then((call) => renderCallDetail(toCallRecord(call)))
    .catch(showError);
});

// ---- experiments -----------------------------------------------------------

async function renderExperimentRuns() {
  const jobs = await api.getJobs();
  const historical = runs.length
    ? `<div class="tablewrap">${table(["corrida", "inicio", "casos", "resultado", "estado"], runs.map((run) => [
      `<code>${esc(run.run_id)}</code>`, esc(formatDate(run.started_at)), esc(run.cases),
      `${esc(run.passed)} correctas · ${esc(run.failed)} incorrectas · ${esc(run.invalid)} no evaluables`,
      '<span class="badge neutral">histórica</span>',
    ]))}</div>`
    : '<div class="empty"><h3>No hay ejecuciones registradas</h3><p>Creá una ejecución con perfiles y escenarios declarados en el servidor.</p></div>';
  const active = jobs.length ? `<h2>Trabajos</h2><div class="tablewrap">${table(["id", "estado", "progreso", "acción"], jobs.map((job) => [
    `<code>${esc(job.id)}</code>`, verdictBadge(job.status), `${esc(job.progress?.completed || 0)} / ${esc(job.progress?.total || "n/d")}`,
    ["pending", "preparing", "running", "cancelling"].includes(job.status) ? `<button class="small" data-job-cancel="${esc(job.id)}">Cancelar</button>` : "—",
  ]))}</div>` : "";
  $("experiment-runs").innerHTML = active + '<h2>Corridas disponibles</h2>' + historical;
}

// ---- comparison ------------------------------------------------------------

function renderComparison(comparison) {
  const summary = comparison.summary || {};
  const candidates = summary.candidates || [];
  const rows = comparison.rows || [];
  $("side").innerHTML = rows.length
    ? `<div class="tablewrap">${table(["escenario", "rep.", ...candidates], rows.map((row) => [
      `${esc(row.scenario_id)}${row.disagrees ? ' <span class="star">*</span>' : ""}`,
      esc(row.repetition),
      ...candidates.map((candidate) => esc(row.cells?.[candidate] || "—")),
    ]))}</div>`
    : '<div class="empty"><h3>Sin comparación lado a lado</h3><p>Se necesitan alternativas que compartan escenario y repetición.</p></div>';
}

$("diff-run").addEventListener("click", async () => {
  try {
    const query = new URLSearchParams({ a: $("diff-a").value, b: $("diff-b").value });
    if ($("diff-cand-a").value) query.set("candidate_a", $("diff-cand-a").value);
    if ($("diff-cand-b").value) query.set("candidate_b", $("diff-cand-b").value);
    const diff = await api.getDiff(query);
    const summary = diff.summary || {};
    const metrics = Object.values(diff.metrics || {});
    $("diff").innerHTML = `<div class="strip">
      <div class="cell"><span>muestra pareada</span><strong>${esc(summary.cases_compared ?? "n/d")}</strong></div>
      <div class="cell"><span>nuevos aciertos</span><strong>${esc(summary.newly_passing ?? "n/d")}</strong></div>
      <div class="cell"><span>nuevos fallos</span><strong>${esc(summary.newly_failing ?? "n/d")}</strong></div>
      <div class="cell"><span>cambios</span><strong>${esc(summary.verdict_changed ?? "n/d")}</strong></div>
    </div>${metrics.length ? `<div class="tablewrap">${table(["métrica", "A", "B", "delta"], metrics.map((row) => [esc(row.label), esc(row.a_text), esc(row.b_text), esc(row.delta ?? "n/d")]))}</div>` : ""}
    <div class="banner">El tamaño de muestra y la estabilidad condicionan cualquier conclusión. Una sola repetición no declara un ganador.</div>`;
  } catch (error) { showError(error); }
});

// ---- live manual conversation ---------------------------------------------

function selectedProfile() {
  return profiles.find((profile) => profile.id === $("profile").value);
}

function profileHint() {
  const profile = selectedProfile();
  const canOpen = profile && !(profile.refusals || []).length;
  $("chat-open").disabled = !canOpen || Boolean(chatSession);
  if (!profile) {
    $("profile-hint").textContent = "No hay perfiles disponibles en el servidor.";
    return;
  }
  const capabilities = Object.entries(profile.capabilities || {}).filter(([, enabled]) => enabled).map(([name]) => name).join(", ") || "ninguna declarada";
  $("profile-hint").innerHTML = `<b>${esc(profile.id)}</b> · ${esc(profile.engine)} ${esc(profile.version)} · capacidades: ${esc(capabilities)}${profile.refusals?.length ? ` · <span class="bad">no disponible: ${esc(profile.refusals.join("; "))}</span>` : ""}`;
}

async function loadProfiles() {
  profiles = await api.getProfiles();
  scenarios = await api.getScenarios();
  $("profile").innerHTML = profiles.map((profile) => `<option value="${esc(profile.id)}">${esc(profile.id)} · ${esc(profile.engine)}</option>`).join("");
  $("experiment-profiles").innerHTML = profiles.map((profile) => `<option value="${esc(profile.id)}">${esc(profile.id)}</option>`).join("");
  $("experiment-scenarios").innerHTML = scenarios.map((scenario) => `<option value="${esc(scenario.id)}">${esc(scenario.id)} · ${esc(scenario.problem_id)}</option>`).join("");
  ["experiment-profiles", "experiment-scenarios", "experiment-mode", "experiment-repetitions", "experiment-create"].forEach((id) => ($(id).disabled = false));
  $("experiment-contract").textContent = "El servidor valida perfiles y escenarios declarados; no se envían rutas, comandos ni destinos desde el navegador.";
  profileHint();
}

$("experiment-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const profileIds = [...$("experiment-profiles").selectedOptions].map((option) => option.value);
  const scenarioIds = [...$("experiment-scenarios").selectedOptions].map((option) => option.value);
  try {
    await api.createJob({
      profile_ids: profileIds,
      scenario_ids: scenarioIds,
      mode: $("experiment-mode").value === "voz" ? "voice" : "text",
      repetitions: Number($("experiment-repetitions").value),
    });
    await renderExperimentRuns();
  } catch (error) { showError(error); }
});

$("experiment-runs").addEventListener("click", async (event) => {
  const button = event.target.closest("[data-job-cancel]");
  if (!button) return;
  try {
    await api.cancelJob(button.dataset.jobCancel);
    await renderExperimentRuns();
  } catch (error) { showError(error); }
});

function chatLine(entry) {
  const line = document.createElement("div");
  line.className = `line ${entry.role}`;
  const audio = entry.wav ? `<audio controls preload="none" src="/api/chat/${encodeURIComponent(chatSession)}/audio/${encodeURIComponent(entry.wav)}"></audio>` : "";
  line.innerHTML = `<span class="who">${esc(entry.role)}</span><span class="what">${esc(entry.text || "(sin texto)")}</span><span class="stamp">${esc(entry.seconds ?? "n/d")}s${entry.latency_ms != null ? ` · ${esc(entry.latency_ms)}ms` : ""}</span>${audio}`;
  $("chat-log").append(line);
  $("chat-log").scrollTop = $("chat-log").scrollHeight;
  chatTurns.push(entry);
}

$("profile").addEventListener("change", profileHint);
$("chat-open").addEventListener("click", async () => {
  try {
    clearError();
    $("chat-open").disabled = true;
    $("chat-state").textContent = "comprobando perfil y abriendo…";
    const opened = await api.openChat({ profile_id: $("profile").value, tts: $("tts").value, stt: $("stt").value });
    chatSession = opened.session_id;
    chatTurns = [];
    $("chat-log").innerHTML = "";
    $("chat-state").textContent = `${opened.profile_id} · ${opened.call_id} · STT ${opened.stt}`;
    if (opened.greeting) chatLine(opened.greeting);
    $("chat-form").hidden = false;
    $("chat-close").disabled = false;
    mic?.enable();
  } catch (error) {
    $("chat-state").textContent = "no se pudo abrir la sesión";
    showError(error);
    profileHint();
  }
});

$("chat-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = $("chat-text").value.trim();
  if (!text || !chatSession) return;
  $("chat-text").value = "";
  try {
    const turn = await api.say(chatSession, { text });
    chatLine(turn.caller);
    chatLine(turn.agent);
  } catch (error) { showError(error); }
});

$("chat-close").addEventListener("click", async () => {
  if (!chatSession) return;
  $("chat-close").disabled = true;
  $("chat-form").hidden = true;
  mic?.disable();
  try {
    const result = await api.closeChat(chatSession);
    const manualCall = toCallRecord({
      ...result,
      case_id: result.call_id,
      candidate: selectedProfile()?.id,
      actions: result.submissions,
      transcript_events: chatTurns.map((turn) => ({
        role: turn.role,
        text: turn.text,
        source: "manual",
      })),
    });
    manualCalls.unshift(manualCall);
    calls.unshift(manualCall);
    $("chat-result").innerHTML = `<article class="card"><h3>Sesión cerrada</h3><p>${verdictBadge(result.scenario?.passed ? "pass" : "informative")}</p><p class="meta">frames caller/agente: ${esc(result.frames_sent)} / ${esc(result.frames_received)} · primera respuesta: ${esc(result.first_audio_ms ?? "n/d")}ms</p><p class="meta">submissions aceptadas: ${esc(result.submissions?.length || 0)} · rechazadas: ${esc(result.rejected?.length || 0)}</p>${result.transport_error ? `<p class="bad">${esc(result.transport_error)}</p>` : ""}</article>`;
  } catch (error) { showError(error); }
  finally {
    chatSession = null;
    $("chat-state").textContent = "sesión cerrada";
    profileHint();
  }
});

// Push-to-talk uses the evaluator's established 8 kHz mu-law browser wire.
// It is optional: text remains available if the browser cannot capture audio.
function createMic() {
  const button = $("mic");
  const state = $("mic-state");
  const supported = window.isSecureContext && navigator.mediaDevices?.getUserMedia && window.AudioWorkletNode;
  if (!supported) {
    if (!window.isSecureContext && location.hostname !== "localhost") state.textContent = "micrófono: requiere HTTPS o localhost";
    return null;
  }
  button.hidden = false;
  const capture = { enabled: false, recording: false, frames: [], context: null, stream: null, node: null };

  function release() {
    capture.node?.disconnect();
    capture.stream?.getTracks().forEach((track) => track.stop());
    capture.context?.close();
    capture.context = null;
    capture.stream = null;
    capture.node = null;
  }

  async function prepare() {
    if (capture.node) return;
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    capture.context = new AudioContextClass({ latencyHint: "interactive" });
    await capture.context.resume();
    capture.stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }, video: false });
    await capture.context.audioWorklet.addModule("/static/mic-worklet.js");
    const source = capture.context.createMediaStreamSource(capture.stream);
    capture.node = new AudioWorkletNode(capture.context, "mulaw-capture", {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      outputChannelCount: [1],
      processorOptions: { targetSampleRate: 8000, frameSamples: 160 },
    });
    capture.node.port.onmessage = (event) => {
      if (capture.recording) capture.frames.push(new Uint8Array(event.data));
    };
    const silence = capture.context.createGain();
    silence.gain.value = 0;
    source.connect(capture.node);
    capture.node.connect(silence);
    silence.connect(capture.context.destination);
  }

  async function send() {
    if (!chatSession || !capture.frames.length) {
      state.textContent = "no se capturó audio";
      return;
    }
    const size = capture.frames.reduce((total, frame) => total + frame.length, 0);
    const bytes = new Uint8Array(size);
    let offset = 0;
    capture.frames.forEach((frame) => { bytes.set(frame, offset); offset += frame.length; });
    let binary = "";
    bytes.forEach((byte) => { binary += String.fromCharCode(byte); });
    state.textContent = `enviando ${(size / 8000).toFixed(1)}s…`;
    try {
      const turn = await api.sayAudio(chatSession, { mulaw_base64: window.btoa(binary) });
      chatLine(turn.caller);
      chatLine(turn.agent);
      state.textContent = "listo";
    } catch (error) {
      state.textContent = "error al enviar";
      showError(error);
    }
  }

  button.addEventListener("pointerdown", async (event) => {
    event.preventDefault();
    if (!capture.enabled || !chatSession) return;
    try {
      await prepare();
      capture.frames = [];
      capture.recording = true;
      button.dataset.live = "true";
      state.textContent = "grabando…";
    } catch (error) {
      release();
      showError(error);
    }
  });
  const stop = async () => {
    if (!capture.recording) return;
    capture.recording = false;
    button.dataset.live = "false";
    await send();
  };
  button.addEventListener("pointerup", stop);
  button.addEventListener("pointerleave", stop);
  button.addEventListener("pointercancel", stop);
  return {
    enable() { capture.enabled = true; button.disabled = false; state.textContent = "micrófono: mantené pulsado para hablar"; },
    disable() { capture.enabled = false; capture.recording = false; capture.frames = []; button.disabled = true; button.dataset.live = "false"; state.textContent = ""; release(); },
  };
}

mic = createMic();
loadProfiles().catch(showError);
loadRuns().catch(showError);
