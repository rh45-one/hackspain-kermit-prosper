// Microphone capture for the evaluator console: 8 kHz µ-law, 160-byte frames.
//
// This is the same AudioWorklet the backend's own browser demo uses
// (backend/serverwebsock/mic-worklet.js),
// keep as a copy on purpose: nothing here imports from backend/ (see PLAN.md), and the
// two must stay wire-compatible: Twilio Media Streams, µ-law 8 kHz, one 20 ms
// frame per port message.
//
const FRAME_SAMPLES = 160;
const TARGET_SAMPLE_RATE = 8000;
const MULAW_BIAS = 33;
const MULAW_CLIP = 8159;
const MULAW_SEGMENT_ENDS = [63, 127, 255, 511, 1023, 2047, 4095, 8191];

function encodeMuLaw(value) {
  let sample = Math.round(Math.max(-1, Math.min(1, value)) * 32768);
  sample = Math.max(-32768, Math.min(32767, sample)) >> 2;
  let mask = 0xff;
  if (sample < 0) {
    sample = -sample;
    mask = 0x7f;
  }
  sample = Math.min(sample, MULAW_CLIP) + MULAW_BIAS;
  let exponent = 0;
  while (exponent < MULAW_SEGMENT_ENDS.length && sample > MULAW_SEGMENT_ENDS[exponent]) {
    exponent += 1;
  }
  if (exponent >= 8) {
    return 0x7f ^ mask;
  }
  const mantissa = (sample >> (exponent + 1)) & 0x0f;
  return ((exponent << 4) | mantissa) ^ mask;
}

class MuLawCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const config = options.processorOptions || {};
    this.targetSampleRate = config.targetSampleRate || TARGET_SAMPLE_RATE;
    this.frameSamples = config.frameSamples || FRAME_SAMPLES;
    this.sourceSamplesPerOutput = sampleRate / this.targetSampleRate;
    this.nextOutputPosition = 0;
    this.inputPosition = 0;
    this.previousSample = 0;
    this.frame = new Uint8Array(this.frameSamples);
    this.frameOffset = 0;
  }

  emit(sample) {
    this.frame[this.frameOffset] = encodeMuLaw(sample);
    this.frameOffset += 1;
    if (this.frameOffset === this.frameSamples) {
      const completed = this.frame;
      this.frame = new Uint8Array(this.frameSamples);
      this.frameOffset = 0;
      this.port.postMessage(completed.buffer, [completed.buffer]);
    }
  }

  process(inputs, outputs) {
    const channels = inputs[0];
    for (const output of outputs[0] || []) {
      output.fill(0);
    }
    if (!channels || channels.length === 0 || channels[0].length === 0) {
      return true;
    }

    const sampleCount = channels[0].length;
    for (let offset = 0; offset < sampleCount; offset += 1) {
      let currentSample = 0;
      for (const channel of channels) {
        currentSample += channel[offset] || 0;
      }
      currentSample /= channels.length;

      while (this.nextOutputPosition <= this.inputPosition) {
        const previousPosition = this.inputPosition - 1;
        const fraction = this.inputPosition === 0
          ? 1
          : this.nextOutputPosition - previousPosition;
        const interpolated = this.previousSample
          + (currentSample - this.previousSample) * Math.max(0, Math.min(1, fraction));
        this.emit(interpolated);
        this.nextOutputPosition += this.sourceSamplesPerOutput;
      }

      this.previousSample = currentSample;
      this.inputPosition += 1;
    }
    return true;
  }
}

registerProcessor("mulaw-capture", MuLawCaptureProcessor);
