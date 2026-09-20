(() => {
  let ws, context, stream, node, source, gain, timer;
  let active = false, starting = false, muted = false, cursor = 0, generation = 0;
  const playing = new Set();
  const start = $('live-start'), stop = $('live-stop'), mute = $('live-mute'), state = $('live-state');
  function clearPlayback() {
    for (const item of playing) { item.onended = null; try { item.stop(); } catch {} item.disconnect(); }
    playing.clear();
    cursor = context ? context.currentTime + .035 : 0;
  }
  function play(payload) {
    if (!context || context.state === 'closed') return;
    let bytes;
    try { bytes = atob(payload); } catch { return; }
    if (!bytes.length) return;
    if (cursor - context.currentTime > 3) clearPlayback();
    const buffer = context.createBuffer(1, bytes.length, 8000), samples = buffer.getChannelData(0);
    for (let i = 0; i < bytes.length; i++) {
      const value = (~bytes.charCodeAt(i)) & 255;
      const magnitude = (((value & 15) << 3) + 132) << ((value & 112) >> 4);
      samples[i] = ((value & 128) ? 132 - magnitude : magnitude - 132) / 32768;
    }
    const item = context.createBufferSource();
    item.buffer = buffer; item.connect(context.destination);
    const when = Math.max(context.currentTime + .035, cursor);
    cursor = when + buffer.duration; playing.add(item);
    item.onended = () => { playing.delete(item); item.disconnect(); };
    item.start(when);
  }
  async function release(message) {
    generation++; active = false; starting = false;
    clearInterval(timer); clearPlayback();
    if (node) node.port.onmessage = null;
    node?.disconnect(); source?.disconnect(); gain?.disconnect();
    stream?.getTracks().forEach(track => track.stop());
    const audio = context; context = null; node = null; source = null; gain = null; stream = null;
    if (ws) { ws.onclose = null; ws.onmessage = null; if (ws.readyState < WebSocket.CLOSING) ws.close(); ws = null; }
    if (audio && audio.state !== 'closed') await audio.close().catch(() => {});
    start.disabled = false; stop.disabled = true; mute.disabled = true;
    $('live-profile').disabled = false;
    mute.setAttribute('aria-pressed', 'false'); mute.textContent = 'Silenciar micrófono';
    state.textContent = message;
    callsLoaded = false;
    window.refreshAnalytics?.();
  }
  start.addEventListener('click', async () => {
    if (active || starting) return;
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.AudioWorkletNode) {
      state.textContent = 'El micrófono necesita HTTPS o localhost y un navegador compatible.'; return;
    }
    const profile = $('live-profile').value;
    if (!profile) { state.textContent = 'No hay perfiles de voz disponibles.'; return; }
    starting = true; start.disabled = true; stop.disabled = false; muted = false;
    $('live-profile').disabled = true;
    const token = ++generation;
    try {
      state.textContent = 'Autoriza el micrófono para conectar…';
      context = new (window.AudioContext || window.webkitAudioContext)({ latencyHint: 'interactive' });
      await context.resume();
      const captured = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }, video: false });
      if (token !== generation) { captured.getTracks().forEach(t => t.stop()); return; }
      stream = captured;
      await context.audioWorklet.addModule('/static/mic-worklet.js');
      if (token !== generation) return;
      source = context.createMediaStreamSource(stream);
      node = new AudioWorkletNode(context, 'mulaw-capture', { numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1], processorOptions: { targetSampleRate: 8000, frameSamples: 160 } });
      gain = context.createGain(); gain.gain.value = 0;
      source.connect(node); node.connect(gain); gain.connect(context.destination);
      node.port.onmessage = event => {
        if (!active || ws?.readyState !== WebSocket.OPEN) return;
        if (ws.bufferedAmount > 256 * 1024) { release('Conexión demasiado lenta. Vuelve a iniciar la llamada.'); return; }
        ws.send(muted ? new Uint8Array(160).fill(255) : event.data);
      };
      state.textContent = 'Conectando con el agente…';
      ws = new WebSocket(`${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}/api/live/${encodeURIComponent(profile)}`);
      const timeout = setTimeout(() => { if (token === generation && !active) release('No se pudo conectar. Comprueba el agente y la clínica local.'); }, 20000);
      ws.onmessage = event => {
        if (token !== generation) return;
        const message = JSON.parse(event.data);
        if (message.event === 'ready') {
          clearTimeout(timeout); active = true; starting = false; mute.disabled = false;
          state.textContent = 'En línea. Ya puedes hablar e interrumpir al agente.';
          const since = Date.now();
          timer = setInterval(() => { const seconds = Math.floor((Date.now() - since) / 1000); $('live-time').textContent = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`; }, 500);
        } else if (message.event === 'media') play(message.media?.payload);
        else if (message.event === 'clear') clearPlayback();
        else if (message.event === 'finished') { clearTimeout(timeout); release(message.error || 'Llamada guardada. Disponible en Historial → Manuales.'); }
      };
      ws.onerror = () => { clearTimeout(timeout); release('Error de conexión. Comprueba el servidor del laboratorio.'); };
      ws.onclose = () => { clearTimeout(timeout); release('El agente ha cerrado la conexión. Consulta el historial de pruebas manuales.'); };
    } catch (error) {
      if (token === generation) await release(error.name === 'NotAllowedError' ? 'Micrófono denegado. Activa el permiso en el navegador y vuelve a intentarlo.' : 'No se pudo iniciar el audio. Comprueba tu micrófono y vuelve a intentarlo.');
    }
  });
  stop.addEventListener('click', () => {
    if (ws?.readyState === WebSocket.OPEN) {
      active = false; stop.disabled = true; mute.disabled = true;
      stream?.getTracks().forEach(track => track.stop()); clearPlayback();
      state.textContent = 'Guardando llamada…'; ws.send('stop');
      setTimeout(() => { if (ws && !active) release('Llamada finalizada. Actualiza el historial para consultar la evidencia.'); }, 8000);
    } else release('Llamada cancelada.');
  });
  mute.addEventListener('click', () => { muted = !muted; mute.setAttribute('aria-pressed', String(muted)); mute.textContent = muted ? 'Activar micrófono' : 'Silenciar micrófono'; });
  window.addEventListener('pagehide', () => { if (ws?.readyState === WebSocket.OPEN) ws.send('stop'); release('Llamada finalizada.'); });
  // Context under the live card. It repeats only what /api/profiles declares:
  // an endpoint the server never announced stays absent instead of being filled in.
  const profileFacts = $('live-profile-facts');
  const profileEngine = $('live-profile-engine');
  const profileLaunch = $('live-profile-launch');
  let profileList = [];
  const chips = items => `<div class="chips">${items.map(item => `<span class="chip">${esc(item)}</span>`).join('')}</div>`;
  const fact = (label, value) => `<div class="brief-fact"><dt>${esc(label)}</dt><dd>${value}</dd></div>`;
  const absent = text => `<span class="meta">${esc(text)}</span>`;
  function renderProfileContext() {
    const selected = profileList.find(item => item.id === $('live-profile').value);
    if (!selected) {
      profileEngine.textContent = 'sin perfil';
      profileEngine.className = 'badge neutral';
      profileFacts.innerHTML = fact('Perfil', 'El servidor no declara ningún perfil de voz disponible para esta prueba.');
      profileLaunch.textContent = '';
      return;
    }
    const endpoints = selected.endpoints || {};
    const laboratory = selected.laboratory || {};
    const stack = selected.providers?.stack?.length ? selected.providers.stack : [selected.providers?.name].filter(Boolean);
    const enabled = Object.entries(selected.capabilities || {}).filter(([, on]) => on).map(([name]) => name);
    profileEngine.textContent = selected.engine || 'motor no declarado';
    profileEngine.className = 'badge neutral';
    profileFacts.innerHTML = [
      fact('Perfil', `<code>${esc(selected.id)}</code>`),
      fact('Motor', esc([selected.engine, selected.version].filter(Boolean).join(' · ') || 'no declarado')),
      fact('Proveedores', stack.length ? chips(stack) : absent('no declarados')),
      fact('Capacidades', enabled.length ? chips(enabled) : absent('ninguna declarada')),
      fact('WebSocket', endpoints.ws_url ? `<code>${esc(endpoints.ws_url)}</code>` : absent('no declarado')),
      fact('Texto', endpoints.text_url ? `<code>${esc(endpoints.text_url)}</code>` : absent('sin endpoint de texto')),
      fact('Laboratorio', `puerto ${esc(laboratory.voice_port ?? 'n/d')} · TTS ${esc(laboratory.tts || 'no declarado')}`),
    ].join('');
    profileLaunch.innerHTML = laboratory.has_start_command
      ? `El perfil declara comando de arranque: el runner del laboratorio puede levantar el proceso en el puerto ${esc(laboratory.voice_port ?? 'n/d')}.`
      : `Sin comando de arranque declarado: el agente tiene que estar escuchando en <code>${esc(endpoints.ws_url || 'el WebSocket declarado')}</code> antes de iniciar la llamada.`;
  }
  $('live-profile').addEventListener('change', renderProfileContext);
  $('brief-open-calls').addEventListener('click', () => document.querySelector('[data-tab="calls"]').click());
  api.getProfiles().then(items => {
    profileList = items;
    const usable = items.filter(p => p.capabilities?.voice && !p.refusals?.length);
    $('live-profile').innerHTML = usable.map(p => `<option value="${esc(p.id)}">${esc(p.id)} · ${esc(p.engine)}</option>`).join('');
    renderProfileContext();
    if (!usable.length) {
      start.disabled = true;
      state.textContent = items.length ? 'Ningún perfil declara voz disponible sin bloqueos. Revisa /api/profiles.' : 'Configura un perfil de voz local para probar el agente.';
    }
  }).catch(error => {
    state.textContent = error.message;
    start.disabled = true;
    profileEngine.textContent = 'sin datos';
    profileFacts.innerHTML = fact('Perfil', `<span class="bad">No se pudo leer /api/profiles: ${esc(error.message)}</span>`);
    profileLaunch.textContent = '';
  });
})();
