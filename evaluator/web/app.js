// Developer console for the local evaluator.
//
// Read-only over runs: it renders the JSON the API exposes and never invents a
// number. Where a metric has no data the API says `n/d` and the console shows
// `n/d`; a missing measurement must not look like a zero.
//
// Two live surfaces: the chat tab (a real call through the evaluator's API)
// and the real-calls tab, which shows what the observer read from the
// backend's own audit.

const $ = (id) => document.getElementById(id);
let runs = [];
let current = null;
let chatSession = null;
let mic = null;

async function api(path, options) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body.detail || `${response.status} ${response.statusText}`);
  }
  return body;
}

function fail(error) {
  const box = $("error");
  box.textContent = error.message || String(error);
  box.hidden = false;
}

function clearError() {
  $("error").hidden = true;
}

function esc(value) {
  const div = document.createElement("div");
  div.textContent = value == null ? "" : String(value);
  return div.innerHTML;
}

function table(headers, rows) {
  const head = headers.map((h) => `<th>${esc(h)}</th>`).join("");
  const body = rows
    .map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`)
    .join("");
  return `<table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

// Metric keys are English identifiers; the console speaks Spanish.
const METRIC_LABELS = {
  cases: "casos",
  without_errors: "casos sin errores",
  invalid: "no evaluables",
  model_failures: "fallos del modelo",
  pass_rate: "aciertos",
  turns_median: "turnos (mediana)",
  first_audio_p50: "primera respuesta p50",
  first_audio_p95: "primera respuesta p95",
  turn_latency_p50: "latencia por turno p50",
  turn_latency_p95: "latencia por turno p95",
  submissions_accepted: "submissions aceptadas",
  submissions_rejected: "submissions rechazadas",
  cost_total: "coste total",
  duration_p50: "duración p50",
  errors_by_type: "errores por tipo",
  audio_caller_s: "audio del caller",
  audio_agent_s: "audio del agente",
  audio_ratio: "caller/agente",
  interrupts_total: "barge-ins",
  calls_with_interrupts: "llamadas con barge-in",
  stability: "estabilidad",
};

const VERDICTS = {
  pass: ["CORRECTA", "ok"],
  fail: ["INCORRECTA", "fail"],
  invalid_evaluation: ["NO EVALUABLE", "invalid"],
};

function verdictBadge(verdict) {
  if (!verdict) return '<span class="badge neutral">informativa</span>';
  const [label, cls] = VERDICTS[verdict] || [verdict.toUpperCase(), "neutral"];
  return `<span class="badge ${cls}">${esc(label)}</span>`;
}

function metricCell(metric) {
  if (!metric) return "—";
  const ratio =
    metric.kind === "count" && metric.denominator ? ` <span class="meta">de ${metric.denominator}</span>` : "";
  return `<strong>${esc(metric.value)}</strong>${ratio}`;
}

// Motion: reveal section groups once, when the parent enters the viewport.
const revealObserver = new IntersectionObserver(
  (entries, observer) => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      entry.target.dataset.shown = "true";
      observer.unobserve(entry.target);
    }
  },
  { threshold: 0.08, rootMargin: "0% 0% -8% 0%" },
);

function reveal(container) {
  const groups = container.querySelectorAll("h2");
  groups.forEach((heading, index) => {
    if (heading.dataset.reveal) return;
    heading.dataset.reveal = "true";
    heading.style.setProperty("--reveal-delay", `${(index % 4) * 70}ms`);
    revealObserver.observe(heading);
  });
}

// ---- tabs ------------------------------------------------------------------

const TABS = ["bench", "metrics", "compare", "real", "chat"];

$("tabs").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-tab]");
  if (!button) return;
  for (const tab of $("tabs").querySelectorAll("button")) {
    tab.classList.toggle("on", tab === button);
  }
  for (const panel of TABS) {
    $(`tab-${panel}`).hidden = panel !== button.dataset.tab;
  }
  window.scrollTo({ top: 0, behavior: "instant" in window ? "instant" : "auto" });
  if (button.dataset.tab === "real") loadRealCalls().catch(fail);
});

const bar = $("bar");
const onScroll = () => {
  bar.dataset.scrolled = String(window.scrollY > 8);
};
window.addEventListener("scroll", onScroll, { passive: true });
onScroll();

// ---- runs ------------------------------------------------------------------

function optionsHtml(entries, formatter) {
  return entries.map(formatter).join("");
}

function runOptions() {
  return runs
    .map(
      (run) =>
        `<option value="${esc(run.run_id)}">${esc(run.run_id)} · ${esc(run.experiment)} · ${run.cases} casos</option>`,
    )
    .join("");
}

async function loadRuns() {
  runs = await api("/api/runs");
  const options = runOptions();
  $("run").innerHTML = options || '<option value="">sin corridas</option>';
  $("diff-a").innerHTML = options;
  $("diff-b").innerHTML = options;
  if (runs.length > 1) $("diff-b").selectedIndex = 1;
  syncCandidateSelects("a");
  syncCandidateSelects("b");
  if (runs.length) await selectRun(runs[0].run_id);
}

function runById(runId) {
  return runs.find((run) => run.run_id === runId);
}

function candidateOptions(runId) {
  const run = runById(runId);
  const candidates = run?.candidates?.length ? run.candidates : [""];
  const entries = candidates.map((name) => `<option value="${esc(name)}">${esc(name || "—")}</option>`);
  return (candidates.length > 1 ? '<option value="">(elegir)</option>' : "") + entries.join("");
}

function syncCandidateSelects(side) {
  const runSelect = $(`diff-${side}`);
  const candidateSelect = $(`diff-cand-${side}`);
  candidateSelect.innerHTML = candidateOptions(runSelect.value);
}

$("diff-a").addEventListener("change", () => syncCandidateSelects("a"));
$("diff-b").addEventListener("change", () => syncCandidateSelects("b"));

async function selectRun(runId) {
  clearError();
  $("run").value = runId;
  $("report").href = `/api/runs/${encodeURIComponent(runId)}/report`;
  const [detail, compare] = await Promise.all([
    api(`/api/runs/${encodeURIComponent(runId)}`),
    api(`/api/runs/${encodeURIComponent(runId)}/compare`),
  ]);
  current = detail;
  renderBench(detail);
  renderMetrics(detail);
  renderCompare(compare);
  if (!$("tab-real").hidden) await loadRealCalls();
}

function renderBench(detail) {
  const manifest = detail.manifest || {};
  const run = runById(detail.run_id) || {};
  $("bench-title").textContent = manifest.experiment || detail.run_id;

  const profile = manifest.dataset_profile || {};
  const facts = [
    ["corrida", `<code>${esc(detail.run_id)}</code>`],
    ["reglas", esc(manifest.rules_version || "n/d")],
    ["dataset", `<code>${esc(manifest.dataset || "n/d")}</code>`],
    ["casos", esc(run.cases ?? "n/d")],
    ["repeticiones", esc(manifest.repetitions ?? "n/d")],
    ["candidatos", esc((manifest.candidates || []).map((c) => c.name).join(", ") || "n/d")],
  ];
  if (profile.name) facts.push(["perfil", esc(profile.name)]);
  $("bench-facts").innerHTML = facts.map(([k, v]) => `<span>${esc(k)}: <b>${v}</b></span>`).join("");

  const candidates = Object.keys(detail.metrics.candidates);
  $("bench-cards").innerHTML = candidates
    .map((name) => {
      const metrics = detail.metrics.candidates[name];
      const rejections = Object.entries(metrics.submissions_rejected || {})
        .map(([status, count]) => `${status}×${count}`)
        .join(" ");
      const rows = [
        ["inválidas", metrics.invalid.value],
        ["casos con errores", metrics.without_errors.value],
        ["primera respuesta p50/p95", `${metrics.first_audio_p50.value} / ${metrics.first_audio_p95.value}`],
        ["turnos (mediana)", metrics.turns_median.value],
        ["submissions", `${metrics.submissions_accepted.value}${rejections ? ` · ${rejections}` : ""}`],
        ["audio caller/agente", `${metrics.audio_caller_s.value} / ${metrics.audio_agent_s.value}`],
        ["barge-ins", metrics.interrupts_total.value],
        ["coste", metrics.cost_total.value],
        ["estabilidad", metrics.stability.value],
      ];
      return `<article class="card">
        <h3>${esc(name)}</h3>
        <p class="big">${esc(metrics.pass_rate.value)}</p>
        <p class="meta">aciertos sobre casos evaluables</p>
        <dl>${rows
          .map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`)
          .join("")}</dl>
      </article>`;
    })
    .join("");

  const problems = detail.metrics.problems;
  const headers = ["problema", ...candidates];
  const rows = problems.map((problem) => {
    const cells = [esc(problem)];
    for (const candidate of candidates) {
      const cell = detail.metrics.matrix[problem]?.[candidate];
      if (!cell) {
        cells.push('<span class="muted">—</span>');
        continue;
      }
      const cls = cell.passed === cell.valid && cell.valid > 0 ? "good" : cell.passed ? "warn" : "bad";
      const invalid = cell.invalid ? ` <span class="meta">+${cell.invalid} inv</span>` : "";
      cells.push(`<span class="${cls}">${cell.passed}/${cell.valid}</span>${invalid}`);
    }
    return cells;
  });
  $("matrix").innerHTML = table(headers, rows);
  reveal($("tab-bench"));
}

function renderMetrics(detail) {
  const candidates = Object.keys(detail.metrics.candidates);
  $("metrics").innerHTML = candidates
    .map((name) => {
      const metrics = detail.metrics.candidates[name];
      const rows = Object.entries(metrics).map(([key, metric]) => [
        esc(METRIC_LABELS[key] || key),
        metricCell(metric),
        metric.kind === "value" ? "" : `<span class="meta">${esc(key)}</span>`,
      ]);
      const counts = metrics.errors_by_type?.counts || {};
      const breakdown = Object.entries(counts)
        .map(([kind, n]) => `<span class="badge neutral">${esc(kind)} × ${n}</span>`)
        .join(" ");
      return (
        `<h3 style="margin-top:26px">${esc(name)}</h3>` +
        `<div class="tablewrap">${table(["métrica", "valor", "clave"], rows)}</div>` +
        (breakdown ? `<div class="row">${breakdown}</div>` : "")
      );
    })
    .join("");
  const errors = detail.metrics.errors;
  $("metrics-errors").textContent = errors.length ? errors.join("\n") : "sin errores registrados";
  reveal($("tab-metrics"));
}

function renderCompare(compare) {
  const candidates = compare.summary.candidates;
  const headers = ["escenario", "rep", ...candidates];
  const rows = compare.rows.map((row) => {
    const cells = [esc(row.scenario_id), esc(row.repetition)];
    for (const candidate of candidates) {
      cells.push(esc(row.cells[candidate] ?? "—"));
    }
    if (row.disagrees) cells[0] = `${cells[0]} <span class="star">✱</span>`;
    return cells;
  });
  const totals = candidates
    .map((name) => {
      const bucket = compare.summary.per_candidate[name] || {};
      const passed = bucket.pass ?? 0;
      const valid = passed + (bucket.fail ?? 0);
      return `<article class="card"><h3>${esc(name)}</h3>
        <p class="big">${passed} / ${valid}</p>
        <p class="meta">inválidas: ${bucket.invalid_evaluation ?? 0} · con errores: ${
          bucket.with_errors ?? 0
        }</p></article>`;
    })
    .join("");
  $("side").innerHTML =
    (rows.length ? `<div class="tablewrap">${table(headers, rows)}</div>` : "") +
    `<div class="cards">${totals}</div>`;
  reveal($("tab-compare"));
}

$("diff-run").addEventListener("click", async () => {
  clearError();
  const a = $("diff-a").value;
  const b = $("diff-b").value;
  const candidateA = $("diff-cand-a").value;
  const candidateB = $("diff-cand-b").value;
  const query = new URLSearchParams({ a, b });
  if (candidateA) query.set("candidate_a", candidateA);
  if (candidateB) query.set("candidate_b", candidateB);
  try {
    const diff = await api(`/api/diff?${query}`);
    const summary = diff.summary;
    const pairing =
      summary.candidate_a || summary.candidate_b
        ? `<p class="meta">pareo: ${esc(summary.candidate_a || "?")} → ${esc(summary.candidate_b || "?")}</p>`
        : "";
    const cells = [
      ["comparados", summary.cases_compared],
      ["aciertos A", summary.passes_a],
      ["aciertos B", summary.passes_b],
      ["nuevos aciertos", summary.newly_passing],
      ["nuevos fallos", summary.newly_failing],
      ["cambio de veredicto", summary.verdict_changed],
      ["fallo cambiado", summary.changed_failure],
      ["sin cambio", summary.unchanged],
      ["solo en A / solo en B", `${summary.only_in_a} / ${summary.only_in_b}`],
    ];
    const strip = `<div class="strip">${cells
      .map(([k, v]) => `<div class="cell"><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`)
      .join("")}</div>`;
    const metricRows = Object.entries(diff.metrics || {}).map(([, row]) => [
      esc(row.label),
      esc(row.a_text),
      esc(row.b_text),
      row.delta == null
        ? '<span class="meta">n/d</span>'
        : `<strong class="${row.delta > 0 ? "good" : row.delta < 0 ? "bad" : ""}">${row.delta > 0 ? "+" : ""}${row.delta}</strong>`,
    ]);
    const metricsTable = metricRows.length
      ? `<div class="tablewrap">${table(["métrica", "A", "B", "delta"], metricRows)}</div>`
      : "";
    const moved = summary.newly_passing + summary.newly_failing + summary.verdict_changed;
    const warning = moved
      ? `<div class="banner"><strong>${moved} caso(s) cambiaron de veredicto.</strong>
         El agente no es determinista: dos ejecuciones del mismo código mueven casos en
         las dos direcciones. Mirá la estabilidad del informe (necesita
         <code>repetitions &gt; 1</code>) antes de leer esto como una mejora.</div>`
      : "";
    $("diff").innerHTML = `${strip}${pairing}${metricsTable}${warning}`;
    reveal($("tab-compare"));
  } catch (error) {
    fail(error);
  }
});

// ---- real calls (observer) -------------------------------------------------

function actionText(action) {
  const verb = (action.action || "").toLowerCase();
  const fields = Object.entries(action)
    .filter(([key]) => key !== "action")
    .map(([key, value]) => `${esc(key)}=${esc(value)}`)
    .join(", ");
  return `<b>${esc(verb)}</b>${fields ? ` <span class="meta">${fields}</span>` : ""}`;
}

function renderRealCalls(rows) {
  const tagged = rows.filter((row) => row.tagged_scenario);
  const leaks = rows.filter((row) => (row.leaks || []).length);
  const engines = [...new Set(rows.map((row) => row.engine || "n/d"))];
  const strip = `<div class="strip">
    <div class="cell"><span>llamadas observadas</span><strong>${rows.length}</strong></div>
    <div class="cell"><span>puntuadas con oráculo</span><strong>${tagged.length}</strong></div>
    <div class="cell"><span>informativas</span><strong>${rows.length - tagged.length}</strong></div>
    <div class="cell"><span>fugas detectadas</span><strong class="${leaks.length ? "bad" : ""}">${leaks.length}</strong></div>
  </div>`;
  const rowsHtml = rows.map((row) => {
    const actions = (row.actions || []).map(actionText).join("<br>") || '<span class="meta">ninguna</span>';
    const leaksHtml = (row.leaks || [])
      .map((field) => ` <span class="bad">fuga: ${esc(field)}</span>`)
      .join("");
    const problems = (row.problems || [])
      .map((problem) => `<br><span class="warn">${esc(problem)}</span>`)
      .join("");
    const transcript = row.transcript || {};
    const evidence = `
      <details>
        <summary>transcript (${esc(row.caller_chars)} + ${esc(row.assistant_chars)} car.)</summary>
        <p><b>caller</b>: ${esc(transcript.caller) || "—"}</p>
        <p><b>agente</b>: ${esc(transcript.assistant) || "—"}</p>
      </details>`;
    return [
      `<code>${esc(String(row.call_id).slice(0, 8))}</code><br><span class="meta">${esc(row.started_at || "—")}</span>`,
      esc(row.engine || "n/d"),
      row.identity_patient_id
        ? `<code>${esc(row.identity_patient_id)}</code>`
        : '<span class="meta">no confirmada</span>',
      `${actions}${problems}`,
      `${verdictBadge(row.verdict)}${leaksHtml}`,
      row.tagged_scenario ? `<code>${esc(row.tagged_scenario)}</code>` : '<span class="meta">—</span>',
      `<span class="meta">${esc(row.ended ? "cerrada" : "SIN CIERRE")} · ${esc(row.elapsed_s ?? "n/d")}s</span><br><span class="meta">submissions: ${(row.submissions || []).length}</span>`,
      evidence,
    ];
  });
  return `${strip}
    <div class="banner quiet">
      Fuente: el audit del propio backend (<code>DATA_DIR/calls/*.jsonl</code>), leído
      post-hoc. El motor observado fue <b>${esc(engines.join(", "))}</b>. Sin oráculo no
      hay veredicto: una llamada informativa muestra qué se envió y qué se dijo, no si
      era lo correcto. Los transcripts quedan solo en <code>results/</code>, que Git
      ignora. ${leaks.length ? `<b>${leaks.length} llamada(s) filtraron un dato protegido.</b>` : ""}
    </div>
    <div class="tablewrap">${table(
      ["llamada", "motor", "identidad", "acción enviada", "veredicto", "escenario", "cierre", "evidencia"],
      rowsHtml,
    )}</div>`;
}

function realCallsEmptyState() {
  return `<div class="empty">
    <h3>Esta corrida no observó llamadas reales</h3>
    <p class="meta">
      El observador post-hoc convierte el audit del backend en una corrida puntuable: lee
      <code>backend/data/calls/*.jsonl</code> (transcripts, acciones encoladas con su
      payload completo, submissions) sin tocar el backend.
    </p>
    <p class="meta">Generá una corrida observada con:</p>
    <code>uv run --project evaluator python -m evaluator.cli observe --data-dir backend/data --map evaluator/experiments/oracle-map.yaml</code>
    <p class="meta">
      Sin <code>--map</code> las llamadas quedan informativas. Con un mapa
      <code>call_id: escenario.yaml</code> se puntúan contra el oráculo de ese escenario,
      reutilizando el mismo comparador y la comprobación de fuga del resto del banco.
    </p>
  </div>`;
}

async function loadRealCalls() {
  if (!current) return;
  const rows = await api(`/api/runs/${encodeURIComponent(current.run_id)}/real-calls`);
  $("real").innerHTML = rows.length ? renderRealCalls(rows) : realCallsEmptyState();
  reveal($("tab-real"));
}

// ---- chat ------------------------------------------------------------------

// The server declares the profiles; the browser only picks one. The list comes
// from /api/profiles, which never carries a credential value, a filesystem path
// or a command line.
let profiles = [];

function profileHint() {
  const profile = profiles.find((entry) => entry.id === $("profile").value);
  if (!profile) {
    $("profile-hint").textContent =
      "No hay perfiles declarados en el servidor: nada que probar sin destino ni ruta inventados.";
    return;
  }
  const capabilities = Object.entries(profile.capabilities || {})
    .filter(([, value]) => value === true)
    .map(([name]) => name)
    .join(", ");
  const refused = (profile.refusals || []).length;
  $("profile-hint").innerHTML =
    `<b>${esc(profile.id)}</b> · motor ${esc(profile.engine)} (${esc(profile.version)}) · ` +
    `${esc(profile.providers?.name || "proveedor sin declarar")} · capacidades: ${esc(capabilities)}` +
    (refused
      ? ` · <span class="bad">rechazado por la guarda del laboratorio: ${esc(
          profile.refusals.join("; "),
        )}</span>`
      : "");
}

async function loadProfiles() {
  profiles = await api("/api/profiles");
  $("profile").innerHTML = profiles
    .map((entry) => `<option value="${esc(entry.id)}">${esc(entry.id)} · ${esc(entry.engine)}</option>`)
    .join("");
  profileHint();
}

$("profile").addEventListener("change", profileHint);

function chatLog(entry) {
  const box = $("chat-log");
  const line = document.createElement("div");
  line.className = `line ${entry.role}`;
  const audio = entry.wav
    ? `<audio controls preload="none" src="/api/chat/${chatSession}/audio/${encodeURIComponent(entry.wav)}"></audio>`
    : "";
  line.innerHTML = `<span class="who">${esc(entry.role)}</span>
    <span class="what">${esc(entry.text || "(sin texto)")}</span>
    <span class="stamp">${esc(entry.seconds)}s${
      entry.latency_ms != null ? ` · ${esc(entry.latency_ms)}ms` : ""
    }</span>${audio}`;
  box.appendChild(line);
  box.scrollTop = box.scrollHeight;
}

$("chat-open").addEventListener("click", async () => {
  clearError();
  try {
    $("chat-open").disabled = true;
    $("chat-state").textContent = "abriendo…";
    const opened = await api("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // A profile id and nothing else: the server resolves the destination,
      // the clinic, the scenario and the audit directory.
      body: JSON.stringify({
        profile_id: $("profile").value,
        tts: $("tts").value,
        stt: $("stt").value,
      }),
    });
    chatSession = opened.session_id;
    $("chat-log").innerHTML = "";
    $("chat-state").textContent = `${opened.profile_id} · ${opened.call_id} · STT ${opened.stt}`;
    if (opened.greeting) chatLog(opened.greeting);
    $("chat-form").hidden = false;
    $("chat-close").disabled = false;
    if (mic) mic.enable();
  } catch (error) {
    fail(error);
    $("chat-open").disabled = false;
    $("chat-state").textContent = "sin sesión";
  }
});

$("chat-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const text = $("chat-text").value.trim();
  if (!text || !chatSession) return;
  $("chat-text").value = "";
  chatLog({ role: "caller", text, seconds: 0 });
  try {
    const turn = await api(`/api/chat/${chatSession}/say`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    // Replace the optimistic line with the audio the rig really sent.
    $("chat-log").lastElementChild?.remove();
    chatLog(turn.caller);
    chatLog(turn.agent);
  } catch (error) {
    fail(error);
  }
});

$("chat-close").addEventListener("click", async () => {
  if (!chatSession) return;
  clearError();
  $("chat-close").disabled = true;
  $("chat-form").hidden = true;
  mic?.disable();
  try {
    const result = await api(`/api/chat/${chatSession}/close`, { method: "POST" });
    const diagnosis = result.diagnosis
      ? `<p class="bad"><strong>${esc(result.diagnosis.kind)}</strong>: ${esc(
          result.diagnosis.message,
        )}${result.diagnosis.blocks_model_scoring ? " · veredicto NO atribuible al modelo" : ""}</p>`
      : '<p class="meta">sin diagnóstico: el caller envió poco audio o el agente sí lo registró</p>';
    const scenario = result.scenario
      ? `<p>veredicto ${esc(result.scenario.id)}: ${verdictBadge(
          result.scenario.passed ? "pass" : "fail",
        )} ${esc(result.scenario.failure_signal || "ok")}</p>`
      : "";
    $("chat-result").innerHTML = `<article class="card">
      <h3>${esc(result.call_id)}</h3>
      <p class="meta">frames caller/agente: ${esc(result.frames_sent)} / ${esc(
        result.frames_received,
      )} · voz enviada: ${esc(result.caller_seconds)}s · primera respuesta: ${esc(
        result.first_audio_ms,
      )}ms</p>
      <p class="meta">caracteres de transcript del caller: ${esc(result.transcript_chars ?? "n/d")}${
        result.transport_error ? ` · error de transporte: ${esc(result.transport_error)}` : ""
      }</p>
      ${diagnosis}${scenario}
      <p class="meta">submissions aceptadas: ${result.submissions.length} · rechazadas: ${
        result.rejected.length
      }</p>
      <pre class="log">${esc(JSON.stringify(result.submissions, null, 2))}</pre>
    </article>`;
  } catch (error) {
    fail(error);
  } finally {
    chatSession = null;
    $("chat-open").disabled = false;
    $("chat-state").textContent = "sin sesión";
  }
});

$("run").addEventListener("change", (event) => selectRun(event.target.value).catch(fail));
$("reload").addEventListener("click", () => loadRuns().catch(fail));

// ---- push-to-talk (enabled only when the browser can capture µ-law) --------

// The backend's own browser demo (backend/serverwebsock) is the reference for
// this wire: AudioWorklet → 8 kHz µ-law → 160-byte frames every 20 ms. The
// console reuses that pattern so a real call can be driven by voice instead of
// typing. `say-audio` on the evaluator side speaks the frames into the session.
function createMic() {
  const button = $("mic");
  const state = $("mic-state");
  const supported =
    window.isSecureContext && navigator.mediaDevices?.getUserMedia && window.AudioWorkletNode;
  if (!supported) {
    button.hidden = true;
    if (!window.isSecureContext && location.hostname !== "localhost") {
      state.textContent = "micrófono: requiere HTTPS o localhost";
    }
    return null;
  }
  button.hidden = false;
  const instance = {
    enabled: false,
    hold: false,
    buffer: [],
    worklet: null,
    context: null,
    stream: null,
    enable() {
      instance.enabled = true;
      button.disabled = false;
      state.textContent = "micrófono: apretá y hablá";
    },
    disable() {
      instance.enabled = false;
      instance.hold = false;
      button.disabled = true;
      state.textContent = "";
    },
  };

  async function prepare() {
    if (instance.worklet) return;
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    instance.context = new AudioContextClass({ latencyHint: "interactive" });
    await instance.context.resume();
    instance.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
      video: false,
    });
    await instance.context.audioWorklet.addModule("/static/mic-worklet.js");
    const source = instance.context.createMediaStreamSource(instance.stream);
    instance.worklet = new AudioWorkletNode(instance.context, "mulaw-capture", {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      outputChannelCount: [1],
      processorOptions: { targetSampleRate: 8000, frameSamples: 160 },
    });
    instance.worklet.port.onmessage = (event) => {
      if (instance.hold) {
        instance.buffer.push(new Uint8Array(event.data));
      }
    };
    const silent = instance.context.createGain();
    silent.gain.value = 0;
    source.connect(instance.worklet);
    instance.worklet.connect(silent);
    silent.connect(instance.context.destination);
  }

  async function send() {
    if (!chatSession || !instance.buffer.length) {
      state.textContent = "no se capturó audio";
      return;
    }
    const frames = instance.buffer.splice(0);
    const total = frames.reduce((sum, frame) => sum + frame.length, 0);
    const payload = new Uint8Array(total);
    let offset = 0;
    for (const frame of frames) {
      payload.set(frame, offset);
      offset += frame.length;
    }
    let binary = "";
    for (const byte of payload) binary += String.fromCharCode(byte);
    state.textContent = `enviando ${(total / 8000).toFixed(1)}s…`;
    try {
      const turn = await api(`/api/chat/${chatSession}/say-audio`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mulaw_base64: window.btoa(binary) }),
      });
      chatLog(turn.caller);
      chatLog(turn.agent);
      state.textContent = "listo";
    } catch (error) {
      fail(error);
      state.textContent = "error al enviar";
    }
  }

  button.addEventListener("pointerdown", async (event) => {
    event.preventDefault();
    if (!instance.enabled || !chatSession) return;
    try {
      await prepare();
    } catch (error) {
      fail(error);
      return;
    }
    instance.buffer = [];
    instance.hold = true;
    button.dataset.live = "true";
    state.textContent = "grabando…";
  });

  const stop = async () => {
    if (!instance.hold) return;
    instance.hold = false;
    button.dataset.live = "false";
    await send();
  };
  button.addEventListener("pointerup", stop);
  button.addEventListener("pointerleave", stop);
  button.addEventListener("pointercancel", stop);
  return instance;
}

mic = createMic();

loadProfiles().catch(fail);
loadRuns().catch(fail);
