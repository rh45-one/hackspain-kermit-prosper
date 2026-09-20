const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const web = path.join(__dirname, '../web');

function consoleContext(api = {}) {
  const elements = new Map();
  const listeners = {};
  const element = id => {
    if (!elements.has(id)) elements.set(id, {
      value: '', hidden: false, selectedOptions: [], listeners: {}, dataset: {},
      classList: { toggle() {} }, setAttribute() {}, focus() {}, scrollIntoView() {},
      addEventListener(event, handler) { this.listeners[event] = handler; },
      querySelectorAll() { return []; },
    });
    return elements.get(id);
  };
  const never = () => new Promise(() => {});
  const location = { href: 'http://localhost/', hostname: 'localhost', host: 'localhost', protocol: 'http:' };
  const window = { isSecureContext: false, scrollTo() {},
    addEventListener(event, handler) { listeners[event] = handler; },
    history: { pushState(_, __, url) { location.href = String(url); }, replaceState(_, __, url) { location.href = String(url); } },
    LabApi: { getProfiles: never, getRuns: never, getJobs: async () => [], ...api },
  };
  const document = {
    getElementById: element,
    querySelectorAll: () => [],
    querySelector: selector => element(selector),
    createElement() {
      return { textContent: '', get innerHTML() { return this.textContent.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;'); } };
    },
  };
  const context = vm.createContext({ document, window, location, navigator: {}, URL, URLSearchParams,
    console, CSS: { escape: value => value }, setTimeout, clearTimeout, setInterval, clearInterval });
  vm.runInContext(fs.readFileSync(path.join(web, 'app.js'), 'utf8'), context);
  return { context, element, window, location, listeners };
}

test('voice selection posts voice and reenables the submit button', async () => {
  let posted;
  const { element } = consoleContext({ createJob: async body => { posted = body; } });
  element('experiment-profiles').selectedOptions = [{ value: 'cascade' }];
  element('experiment-scenarios').selectedOptions = [{ value: 'sb-001' }];
  element('experiment-mode').value = 'voice';
  element('experiment-repetitions').value = '3';
  await element('experiment-form').listeners.submit({ preventDefault() {} });
  assert.equal(posted.mode, 'voice');
  assert.equal(posted.repetitions, 3);
  assert.equal(element('experiment-create').disabled, false);
});

test('history fetches only the selected server page with its filters', async () => {
  const requests = [];
  const { context, element } = consoleContext({ getHistoryCalls: async query => {
    requests.push(new URLSearchParams(query));
    return { items: [], total: 1000, next_page: 2 };
  } });
  element('call-origin').value = 'tests';
  element('call-profile').value = 'cascade';
  element('call-scenario').value = 'mic-example';
  await context.loadCalls();
  assert.equal(requests.length, 1);
  assert.equal(requests[0].get('page_size'), '15');
  assert.equal(requests[0].get('source'), 'tests');
  assert.equal(requests[0].get('candidate_query'), 'cascade');
  assert.equal(requests[0].get('search'), 'mic-example');
});

test('deep links restore cohort, filters and page', async () => {
  const requests = [];
  const { context, element, location } = consoleContext({ getHistoryCalls: async query => {
    requests.push(new URLSearchParams(query));
    return { items: [], total: 1000 };
  } });
  location.href = 'http://localhost/?tab=calls&source=tests&page=3&search=mic-example&candidate=cascade';
  await context.applyRoute();
  assert.equal(element('call-origin').value, 'tests');
  assert.equal(element('call-scenario').value, 'mic-example');
  assert.equal(requests[0].get('page'), '3');
});

test('mu-law worklet emits paced non-silent frames at supported input rates', () => {
  for (const rate of [8000, 16000, 44100, 48000]) {
    let Capture;
    const context = vm.createContext({ sampleRate: rate, Uint8Array,
      AudioWorkletProcessor: class {
        constructor() { this.frames = []; this.port = { postMessage: buffer => this.frames.push(new Uint8Array(buffer)) }; }
      },
      registerProcessor(_, processor) { Capture = processor; },
    });
    vm.runInContext(fs.readFileSync(path.join(web, 'mic-worklet.js'), 'utf8'), context);
    const capture = new Capture({ processorOptions: {} });
    for (let offset = 0; offset < rate; offset += 128) {
      const input = Float32Array.from({ length: Math.min(128, rate - offset) }, (_, i) => .3 * Math.sin(2 * Math.PI * 440 * (offset + i) / rate));
      capture.process([[input]], [[new Float32Array(input.length)]]);
    }
    assert.equal(capture.frames.length, 50);
    assert.ok(capture.frames.every(frame => frame.length === 160));
    assert.ok(capture.frames.some(frame => frame.some(value => value !== 255 && value !== 127)));
  }
});

async function liveContext() {
  const state = consoleContext({ getProfileStatus: async () => ({ ready: true, verified: true, engine: 'cascade', model: 'test' }) });
  const { context, element, window } = state;
  const track = { stopped: false, stop() { this.stopped = true; } };
  const graphNode = () => ({ connect() {}, disconnect() {}, gain: { value: 1 } });
  window.isSecureContext = true;
  window.AudioContext = class {
    constructor() { this.state = 'running'; this.currentTime = 0; this.audioWorklet = { addModule: async () => {} }; }
    async resume() {}
    async close() { this.state = 'closed'; }
    createMediaStreamSource() { return graphNode(); }
    createGain() { return graphNode(); }
  };
  window.AudioWorkletNode = context.AudioWorkletNode = class {
    constructor() { state.node = this; this.port = {}; }
    connect() {}
    disconnect() {}
  };
  context.WebSocket = class {
    static OPEN = 1;
    static CLOSING = 2;
    constructor() { state.socket = this; this.readyState = 1; this.bufferedAmount = 0; this.sent = []; }
    send(value) { this.sent.push(value); }
    close() { this.readyState = 3; }
  };
  context.navigator.mediaDevices = {
    enumerateDevices: async () => [],
    getUserMedia: async () => ({ getTracks: () => [track], getAudioTracks: () => [track] }),
  };
  element('live-profile').value = 'cascade';
  vm.runInContext(fs.readFileSync(path.join(web, 'live.js'), 'utf8'), context);
  await element('live-start').listeners.click();
  state.socket.onmessage({ data: JSON.stringify({ event: 'ready', call_id: 'mic-test' }) });
  return { ...state, track };
}

test('live capture sends audio, mute sends silence, and hangup releases the device', async () => {
  const { element, node, socket, track } = await liveContext();
  try {
    node.port.onmessage({ data: new Uint8Array(160).fill(128).buffer });
    assert.equal(socket.sent[0].byteLength, 160);
    assert.ok(element('live-level').value > 0);
    element('live-mute').listeners.click();
    node.port.onmessage({ data: new Uint8Array(160).fill(128).buffer });
    assert.ok([...socket.sent[1]].every(value => value === 255));
    socket.onmessage({ data: JSON.stringify({ event: 'telemetry', frames_sent: 2, frames_received: 1, caller_text: 'Hola' }) });
    assert.equal(element('live-transcript').textContent, 'Hola');
    element('live-stop').listeners.click();
    assert.equal(socket.sent.at(-1), 'stop');
    socket.onmessage({ data: JSON.stringify({ event: 'finished', error: null }) });
    await Promise.resolve();
    assert.equal(track.stopped, true);
    assert.equal(element('live-history').hidden, false);
    assert.match(element('live-history').href, /search=mic-test/);
  } finally {
    if (node.onprocessorerror) await node.onprocessorerror();
  }
});

test('worklet errors stop the call instead of leaving a deaf session online', async () => {
  const { element, node, track } = await liveContext();
  await node.onprocessorerror();
  assert.equal(track.stopped, true);
  assert.equal(element('live-start').disabled, false);
  assert.match(element('live-state').textContent, /captura de audio/);
});

test('live preflight rejects an unverified motor before microphone permission', async () => {
  let captured = false;
  const { context, element, window } = consoleContext({ getProfileStatus: async () => ({ ready: false, reason: 'Motor distinto' }) });
  window.isSecureContext = true;
  window.AudioWorkletNode = class {};
  context.navigator.mediaDevices = { getUserMedia: async () => { captured = true; }, enumerateDevices: async () => [] };
  element('live-profile').value = 'gemini_live';
  vm.runInContext(fs.readFileSync(path.join(web, 'live.js'), 'utf8'), context);
  await element('live-start').listeners.click();
  assert.equal(captured, false);
  assert.equal(element('live-state').textContent, 'Motor distinto');
  assert.equal(element('live-start').disabled, false);
});
