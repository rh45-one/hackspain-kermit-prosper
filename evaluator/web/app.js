// Developer console for the local evaluator.
//
// Read-only over runs: it renders the JSON the API exposes and never invents a
// number. Where a metric has no data the API says `n/d` and the console shows
// `n/d`; a missing measurement must not look like a zero.
//
// The one live surface is the chat tab, which opens a real call through the
// evaluator's own API.

const $ = (id) => document.getElementById(id);
let runs = [];
let current = null;
let chatSession = null;

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

function table(headers, rows, cls = "") {
  const head = headers.map((h) => `<th>${esc(h)}</th>`).join("");
  const body = rows
    .map((row) => `<tr>${row.map((cell) => `<td>${cell}</td>`).join("")}</tr>`)
    .join("");
  return `<table class="${cls}"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table>`;
}

// ---- tabs ------------------------------------------------------------------
$("tabs").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-tab]");
  if (!button) return;
  for (const tab of $("tabs").querySelectorAll("button")) {
    tab.classList.toggle("on", tab === button);
  }
  for (const panel of ["bench", "metrics", "compare", "chat"]) {
    $(`tab-${panel}`).hidden = panel !== button.dataset.tab;
  }
});

// ---- runs ------------------------------------------------------------------
async function loadRuns() {
  runs = await api("/api/runs");
  const options = runs
    .map(
      (run) =>
        `<option value="${esc(run.run_id)}">${esc(run.run_id)} · ${esc(run.experiment)} · ${run.cases} casos</option>`,
    )
    .join("");
  $("run").innerHTML = options || '<option value="">sin corridas</option>';
  $("diff-a").innerHTML = options;
  $("diff-b").innerHTML = options;
  if (runs.length > 1) $("diff-b").selectedIndex = 1;
  if (runs.length) await selectRun(runs[0].run_id);
}

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
}

function metricRows(metrics) {
  const keys = Object.keys(metrics);
  return keys.map((key) => {
    const metric = metrics[key];
    const ratio =
      metric.numerator == null || metric.denominator == null
        ? ""
        : `${metric.numerator}/${metric.denominator}`;
    return [esc(key), `<strong>${esc(metric.value)}</strong>`, `<span class="muted">${esc(ratio)}</span>`];
  });
}

function renderBench(detail) {
  const candidates = Object.keys(detail.metrics.candidates);
  $("bench-cards").innerHTML = candidates
    .map((name) => {
      const metrics = detail.metrics.candidates[name];
      const rejections = Object.entries(metrics.submissions_rejected || {})
        .map(([status, count]) => `${status}×${count}`)
        .join(" ");
      return `<article class="card">
        <h3>${esc(name)}</h3>
        <p class="big">${esc(metrics.pass_rate.value)}</p>
        <p class="muted">inválidas: ${esc(metrics.invalid.value)} · errores: ${esc(
          metrics.without_errors.value,
        )}</p>
        <p class="muted">primera respuesta p50/p95: ${esc(metrics.first_audio_p50.value)} / ${esc(
          metrics.first_audio_p95.value,
        )}</p>
        <p class="muted">turnos (mediana): ${esc(metrics.turns_median.value)} · coste: ${esc(
          metrics.cost_total.value,
        )}</p>
        <p class="muted">submissions: ${esc(metrics.submissions_accepted.value)} aceptadas${
          rejections ? ` · rechazos ${esc(rejections)}` : ""
        }</p>
        <p class="muted">estabilidad: ${esc(metrics.stability.value)}</p>
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
      const invalid = cell.invalid ? ` <span class="muted">+${cell.invalid} inv</span>` : "";
      cells.push(`<span class="${cls}">${cell.passed}/${cell.valid}</span>${invalid}`);
    }
    return cells;
  });
  $("matrix").innerHTML = table(headers, rows);
}

function renderMetrics(detail) {
  const candidates = Object.keys(detail.metrics.candidates);
  $("metrics").innerHTML = candidates
    .map(
      (name) =>
        `<h3>${esc(name)}</h3>` +
        table(["métrica", "valor", "n/d"], metricRows(detail.metrics.candidates[name])),
    )
    .join("");
  const errors = detail.metrics.errors;
  $("metrics-errors").textContent = errors.length ? errors.join("\n") : "sin errores registrados";
}

function renderCompare(compare) {
  const candidates = compare.summary.candidates;
  const headers = ["escenario", "rep", ...candidates];
  const rows = compare.rows.map((row) => {
    const cells = [esc(row.scenario_id), esc(row.repetition)];
    for (const candidate of candidates) {
      cells.push(esc(row.cells[candidate] ?? "—"));
    }
    const marker = row.disagrees ? ' <span class="star">✱</span>' : "";
    cells[0] = esc(row.scenario_id) + marker;
    return cells;
  });
  const totals = candidates
    .map((name) => {
      const bucket = compare.summary.per_candidate[name] || {};
      return `<article class="card"><h3>${esc(name)}</h3>
        <p class="big">${bucket.pass ?? 0} / ${(bucket.pass ?? 0) + (bucket.fail ?? 0)}</p>
        <p class="muted">inválidas: ${bucket.invalid_evaluation ?? 0} · con errores: ${
          bucket.with_errors ?? 0
        }</p></article>`;
    })
    .join("");
  $("side").innerHTML = table(headers, rows) + `<div class="cards">${totals}</div>`;
}

$("diff-run").addEventListener("click", async () => {
  clearError();
  try {
    const a = $("diff-a").value;
    const b = $("diff-b").value;
    const diff = await api(`/api/diff?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);
    $("diff").innerHTML = Object.entries(diff.summary)
      .map(
        ([key, value]) =>
          `<article class="card"><h4>${esc(key)}</h4><p class="big">${esc(value)}</p></article>`,
      )
      .join("");
  } catch (error) {
    fail(error);
  }
});

// ---- chat ------------------------------------------------------------------
function chatLog(entry) {
  const box = $("chat-log");
  const line = document.createElement("div");
  line.className = `line ${entry.role}`;
  const audio = entry.wav
    ? `<audio controls preload="none" src="/api/chat/${chatSession}/audio/${encodeURIComponent(entry.wav)}"></audio>`
    : "";
  line.innerHTML = `<span class="who">${esc(entry.role)}</span>
    <span class="what">${esc(entry.text || "(sin texto)")}</span>
    <span class="muted">${esc(entry.seconds)}s${
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
    const body = {
      ws_url: $("ws").value,
      clinic_url: $("clinic").value,
      tts: $("tts").value,
      stt: $("stt").value,
      scenario: $("scenario").value || null,
      agent_audit_dir: $("audit").value || null,
    };
    const opened = await api("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    chatSession = opened.session_id;
    $("chat-log").innerHTML = "";
    $("chat-state").textContent = `${opened.call_id} · STT ${opened.stt}`;
    if (opened.greeting) chatLog(opened.greeting);
    $("chat-form").hidden = false;
    $("chat-close").disabled = false;
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
  try {
    const result = await api(`/api/chat/${chatSession}/close`, { method: "POST" });
    const diagnosis = result.diagnosis
      ? `<p class="bad"><strong>${esc(result.diagnosis.kind)}</strong>: ${esc(
          result.diagnosis.message,
        )}${result.diagnosis.blocks_model_scoring ? " · veredicto NO atribuible al modelo" : ""}</p>`
      : '<p class="muted">sin diagnóstico: el caller envió poco audio o el agente sí lo registró</p>';
    const scenario = result.scenario
      ? `<p>veredicto ${esc(result.scenario.id)}: <strong>${
          result.scenario.passed ? "PASA" : "FALLA"
        }</strong> ${esc(result.scenario.failure_signal || "ok")}</p>`
      : "";
    $("chat-result").innerHTML = `<article class="card">
      <h3>${esc(result.call_id)}</h3>
      <p class="muted">frames caller/agente: ${esc(result.frames_sent)} / ${esc(
        result.frames_received,
      )} · voz enviada: ${esc(result.caller_seconds)}s · primera respuesta: ${esc(
        result.first_audio_ms,
      )}ms</p>
      <p class="muted">caracteres de transcript del caller: ${esc(result.transcript_chars ?? "n/d")}${
        result.transport_error ? ` · error de transporte: ${esc(result.transport_error)}` : ""
      }</p>
      ${diagnosis}${scenario}
      <p class="muted">submissions aceptadas: ${result.submissions.length} · rechazadas: ${
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

loadRuns().catch(fail);
