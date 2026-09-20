(() => {
  let data = null;
  let loading = false;
  const fmt = (n, digits = 0) => n == null ? '—' : Number(n).toLocaleString('es-ES', { maximumFractionDigits: digits });
  const ms = (n) => n == null ? '—' : `${fmt(n / 1000, 2)} s`;
  const pct = (n) => n == null ? '—' : `${fmt(n * 100, 1)} %`;
  const blank = (title, reason) => `<div class="empty-chart"><h3>${esc(title)}</h3><p>${esc(reason)}</p></div>`;
  // Below this many observations the KPI keeps its exact value but is labelled
  // and de-emphasised: an honest zero from a sample of two is not a headline.
  const SMALL_SAMPLE = 5;
  function metric(label, value, note, sample) {
    const thin = sample != null && sample < SMALL_SAMPLE;
    const badge = thin ? `<span class="metric-sample">n=${fmt(sample)}</span>` : '';
    return `<div class="metric${thin ? ' is-thin' : ''}"><dl><dt>${esc(label)}</dt><dd><span class="metric-value">${esc(value)}</span>${badge}</dd></dl><small>${esc(note)}</small></div>`;
  }
  function coverage(label, value, total) {
    return `<div class="coverage-row"><div class="coverage-label"><span>${esc(label)}</span><b>${fmt(value)} / ${fmt(total)}</b></div><progress aria-label="${esc(label)}" value="${value}" max="${total || 1}"></progress></div>`;
  }
  function renderTrend() {
    if (!data) return;
    const key = $('trend-metric').value;
    const rows = data.daily;
    const values = rows.filter(r => r[key] != null);
    if (!values.length) {
      $('trend-chart').innerHTML = blank('Aún no hay mediciones', key === 'calls' ? 'Las llamadas con fecha aparecerán aquí al sincronizar el historial.' : 'Esta métrica necesita evidencia registrada o evaluaciones del juez. Cambia de métrica para explorar la actividad.');
      return;
    }
    const isRate = key === 'pass_rate';
    const max = isRate ? 1 : key === 'quality' ? 5 : Math.max(1, ...values.map(r => r[key]));
    const x0 = 48, width = 560, top = 16, height = 150;
    const label = value => key.endsWith('_ms') ? ms(value) : isRate ? pct(value) : fmt(value, 1);
    const y = value => top + height * (1 - value / max);
    const x = index => x0 + width * (index + .5) / rows.length;
    const grid = [0, .5, 1].map(t => `<line class="gridline" x1="${x0}" x2="620" y1="${y(max * t)}" y2="${y(max * t)}"/><text x="40" y="${y(max * t) + 4}" text-anchor="end">${esc(label(max * t))}</text>`).join('');
    const bars = rows.map((r, i) => {
      if (r[key] == null) return '';
      const value = r[key], barWidth = Math.min(40, width / rows.length * .6);
      const title = `${r.date}: ${label(value)} · ${r.calls} llamadas · ${r.evaluated} evaluadas`;
      return key === 'calls'
        ? `<rect class="bar-value" x="${x(i) - barWidth / 2}" y="${y(value)}" width="${barWidth}" height="${height * value / max}" rx="2"><title>${esc(title)}</title></rect>`
        : `<circle class="point" cx="${x(i)}" cy="${y(value)}" r="5"><title>${esc(title)}</title></circle>`;
    }).join('');
    const labels = rows.map((r, i) => (i === 0 || i === rows.length - 1 || (rows.length > 2 && i % Math.ceil(rows.length / 6) === 0)) ? `<text x="${x(i)}" y="192" text-anchor="middle">${esc(r.date.slice(5).split('-').reverse().join('/'))}</text>` : '').join('');
    const title = $('trend-metric').selectedOptions[0].textContent;
    $('trend-chart').innerHTML = `<svg class="trend" role="img" aria-label="${esc(title)} por día" viewBox="0 0 640 205">${grid}${bars}${labels}</svg><p class="chart-caption">${fmt(values.length)} días con evidencia · ${fmt(data.summary.calls)} llamadas${data.undated ? ` · ${fmt(data.undated)} sin fecha` : ''}</p><details><summary>Ver valores del gráfico</summary>${table(['Fecha', title, 'Muestra'], values.map(r => [esc(r.date), esc(label(r[key])), fmt(r.calls)]))}</details>`;
  }
  function render() {
    const s = data.summary;
    $('source-status').dataset.ready = String(data.source.available);
    $('source-status').textContent = data.source.available
      ? `Historial sincronizado · ${fmt(s.calls)} llamadas en esta selección · ${new Date(data.source.updated_at).toLocaleTimeString('es-ES')}`
      : 'Fuente de llamadas no disponible. Arranca el laboratorio con --audit-data apuntando al DATA_DIR del backend.';
    $('analytics-metrics').innerHTML = [
      metric('Llamadas registradas', fmt(s.calls), `${fmt(s.completed)} con cierre registrado`),
      metric('Acierto · juez LLM', pct(s.pass_rate), `${fmt(s.passed)} correctas / ${fmt(s.evaluated)} evaluables`, s.evaluated),
      metric('Primer audio · p50', ms(s.first_audio_p50_ms), `Conexión → emisión · ${fmt(s.first_audio_n)} llamadas`),
      metric('Calidad conversacional', s.quality == null ? '—' : `${fmt(s.quality, 1)} / 5`, `${fmt(s.quality_n)} valoraciones LLM`, s.quality_n),
      metric('Recuperación de voz', s.recovered == null ? '—' : `${s.recovered} / ${s.recovery_observed}`, `${fmt(s.interruptions)} interrupciones registradas${s.recovered == null ? ' · recuperación sin medir' : ''}`, s.recovery_observed),
    ].join('');
    $('coverage-chart').innerHTML = coverage('Transcripción', s.transcripts, s.calls) + coverage('Primer audio', s.first_audio_n, s.calls) + coverage('Latencia por respuesta', s.response_calls, s.calls) + coverage('Evaluación LLM', s.judged, s.calls) + `<p class="chart-caption">${s.transcript_gap_n ? `Intervalo entre transcripciones: ${ms(s.transcript_gap_p50_ms)} p50 (${fmt(s.transcript_gap_n)} pares). No mide la latencia audible.` : 'Los datos ausentes se muestran como —, nunca como cero.'}</p>`;
    $('model-benchmark').innerHTML = data.models.length ? `<div class="tablewrap">${table(['Motor / modelo', 'Versión', 'Llamadas', 'Acierto LLM', 'Calidad / 5', 'Primer audio p50', 'Latencia p95'], data.models.map(m => [
      `<strong>${esc(m.model || m.engine)}</strong><br><span class="meta">${esc(m.model ? m.engine : 'Modelo no registrado')}</span>`,
      esc(m.version || 'No registrada'), fmt(m.calls), `${pct(m.pass_rate)}<br><span class="meta">n=${fmt(m.evaluated)}</span>`,
      `${fmt(m.quality, 1)}<br><span class="meta">n=${fmt(m.quality_n)}</span>`, `${ms(m.first_audio_p50_ms)}<br><span class="meta">n=${fmt(m.first_audio_n)}</span>`, `${ms(m.response_p95_ms)}<br><span class="meta">n=${fmt(m.response_n)} respuestas</span>`,
    ]))}</div>` : blank('Sin llamadas en esta selección', 'Amplía el periodo o comprueba la fuente del backend.');
    $('comparison-note').textContent = data.comparison_note;
    $('latency-chart').innerHTML = s.response_n ? `<div class="histogram">${s.response_distribution.map(b => `<div class="hist-bin"><b>${fmt(b.count)}</b><i style="height:${120 * b.count / Math.max(1, ...s.response_distribution.map(x => x.count))}px"></i><span>${esc(b.label)}</span></div>`).join('')}</div><p class="chart-caption">p50 ${ms(s.response_p50_ms)} · p95 ${ms(s.response_p95_ms)} · ${fmt(s.response_n)} respuestas</p>` : blank('Latencia por turno no registrada', 'Estas llamadas no contienen marcas de fin de habla y primer audio de respuesta. El primer audio de la llamada sí se muestra cuando está disponible.');
    $('judge-status').innerHTML = `<p><strong>${esc(data.judge.model)}</strong> <span class="badge ${data.judge.configured ? 'ok' : 'neutral'}">${data.judge.configured ? 'Configurado' : 'Sin configurar'}</span></p><p>${fmt(s.judged)} llamadas valoradas de ${fmt(s.calls)}.</p>${!data.judge.configured ? `<p class="hint">Configura <code>${esc((data.judge.key_env || ['EVALUATOR_JUDGE_API_KEY'])[0])}</code> en el entorno del servidor, y <code>EVALUATOR_JUDGE_BASE_URL</code>/<code>EVALUATOR_JUDGE_MODEL</code> si el proveedor no es ${esc(data.judge.provider)}. Reinicia el laboratorio después.</p>` : ''}`;
    renderTrend();
  }
  window.refreshAnalytics = async () => {
    if (loading) return;
    loading = true;
    $('analytics-filters').setAttribute('aria-busy', 'true');
    try {
      const query = new URLSearchParams({ origin: $('analytics-origin').value });
      if ($('analytics-model').value) query.set('candidate', $('analytics-model').value);
      if ($('analytics-from').value) query.set('from', $('analytics-from').value);
      if ($('analytics-to').value) query.set('to', `${$('analytics-to').value}T23:59:59.999999Z`);
      if ($('analytics-from').value && $('analytics-to').value && $('analytics-from').value > $('analytics-to').value) throw new Error('La fecha inicial debe ser anterior a la final.');
      data = await api.getAnalytics(query);
      const currentModel = $('analytics-model').value;
      if (!currentModel) $('analytics-model').innerHTML = '<option value="">Todos los motores</option>' + [...new Set(data.models.map(m => m.engine))].map(m => `<option value="${esc(m)}">${esc(m)}</option>`).join('');
      render();
    } catch (error) { showError(error); $('source-status').textContent = 'No se pudo actualizar el historial. Pulsa Recargar para reintentar.'; }
    finally { loading = false; $('analytics-filters').removeAttribute('aria-busy'); }
  };
  $('analytics-filters').addEventListener('submit', event => { event.preventDefault(); clearError(); window.refreshAnalytics(); });
  $('trend-metric').addEventListener('change', renderTrend);
  for (const id of ['open-history', 'judge-history']) $(id).addEventListener('click', () => {
    $('call-origin').value = $('analytics-origin').value;
    document.querySelector('[data-tab="calls"]').click();
  });
  $('reload').addEventListener('click', () => { window.refreshAnalytics(); if (!$('tab-calls').hidden) loadCalls().catch(showError); });
  window.refreshAnalytics();
})();
