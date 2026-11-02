// Microphone capture for AIJADE: device listing, voice-activity detection (RMS energy with hangover) or push-to-talk,
// and recognition through the Web Speech API where the browser provides it. Errors are reported to .NET, not swallowed.
let state = null;

/**
 * Tell the stage that the user started or stopped speaking (it nods after a finished utterance). On the end, spokeMs is
 * how long the voice was active and quietMs how long it has already been quiet (the VAD waits for a hangover).
 */
function announce(speaking, spokeMs = 0, quietMs = 0) { window.dispatchEvent(new CustomEvent('aijade-user-speech', { detail: { speaking, spokeMs, quietMs } })); }

/**
 * 16-bit PCM WAV of mono samples in -1..1. The server's local recognizer (MOSAIC's Qwen3-ASR service, ADR-003) takes WAV only;
 * OpenAI-compatible recognizers take it too.
 */
export function encodeWav(samples, rate) {
  const bytes = new Uint8Array(44 + samples.length * 2);
  const view = new DataView(bytes.buffer);
  const text = (at, s) => { for (let i = 0; i < s.length; i++) view.setUint8(at + i, s.charCodeAt(i)); };
  text(0, 'RIFF'); view.setUint32(4, 36 + samples.length * 2, true); text(8, 'WAVE');
  text(12, 'fmt '); view.setUint32(16, 16, true); view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, rate, true); view.setUint32(28, rate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  text(36, 'data'); view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return bytes;
}

/** A recorded utterance as 16 kHz mono WAV, or null when this browser cannot decode its own recording. */
async function toWav(blob) {
  try {
    const rate = 16000;
    const decoded = await new OfflineAudioContext(1, rate, rate).decodeAudioData(await blob.arrayBuffer());
    const offline = new OfflineAudioContext(1, Math.max(1, Math.ceil(decoded.duration * rate)), rate);
    const source = offline.createBufferSource();
    source.buffer = decoded;
    source.connect(offline.destination);
    source.start();
    return encodeWav((await offline.startRendering()).getChannelData(0), rate);
  } catch {
    return null;
  }
}

export async function devices() {
  try {
    const all = await navigator.mediaDevices.enumerateDevices();
    return all.filter(d => d.kind === 'audioinput').map((d, i) => ({ id: d.deviceId, label: d.label || `Microphone ${i + 1}` }));
  } catch {
    return [];
  }
}

function recognizer(lang, dotnet) {
  const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Ctor) return null;
  const r = new Ctor();
  r.lang = lang; r.continuous = true; r.interimResults = true;
  r.onresult = (e) => {
    for (let i = e.resultIndex; i < e.results.length; i++) {
      const res = e.results[i];
      dotnet.invokeMethodAsync('OnTranscript', res[0].transcript, res.isFinal);
    }
  };
  r.onerror = (e) => { if (e.error !== 'no-speech' && e.error !== 'aborted') dotnet.invokeMethodAsync('OnError', `recognition: ${e.error}`); };
  r.onend = () => { if (state && state.listening) { try { r.start(); } catch { /* already started */ } } };
  return r;
}

export async function start(dotnet, options) {
  await stop();
  if (!navigator.mediaDevices?.getUserMedia) { dotnet.invokeMethodAsync('OnError', 'this browser cannot access a microphone'); return; }
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: options.deviceId ? { deviceId: { exact: options.deviceId } } : true });
  } catch (e) {
    dotnet.invokeMethodAsync('OnError', e?.name === 'NotAllowedError' ? 'microphone permission denied' : `microphone unavailable (${e?.name ?? e})`);
    return;
  }
  const ctx = new AudioContext();
  const source = ctx.createMediaStreamSource(stream);
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  source.connect(analyser);
  const hasBrowserRecognition = !!(window.SpeechRecognition || window.webkitSpeechRecognition);
  const useServer = options.recognition === 'server' || (options.recognition !== 'browser' && !hasBrowserRecognition);
  const rec = useServer ? null : recognizer(options.lang, dotnet);
  if (!useServer && !rec) dotnet.invokeMethodAsync('OnError', 'speech recognition is not supported in this browser; choose the server recognizer in Settings');
  if (useServer && typeof MediaRecorder === 'undefined') dotnet.invokeMethodAsync('OnError', 'this browser cannot record audio for the server recognizer');
  state = { stream, ctx, analyser, rec, recorder: null, listening: false, speaking: false, quietSince: 0, timer: 0, keys: null };
  const buf = new Float32Array(analyser.fftSize);
  // Server recognition: each utterance (VAD or push-to-talk) is recorded and handed to .NET, which has it transcribed.
  const record = (on) => {
    if (on) {
      const chunks = [];
      const recorder = new MediaRecorder(stream);
      const started = performance.now();
      recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
      recorder.onstop = async () => {
        const seconds = (performance.now() - started) / 1000;
        if (seconds < 0.3 || !chunks.length) return; // a click or a breath, not speech
        const blob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' });
        const wav = await toWav(blob);
        if (wav) dotnet.invokeMethodAsync('OnUtterance', wav, 'audio/wav', seconds);
        else dotnet.invokeMethodAsync('OnUtterance', new Uint8Array(await blob.arrayBuffer()), blob.type, seconds);
      };
      recorder.start();
      state.recorder = recorder;
    } else if (state.recorder) {
      if (state.recorder.state !== 'inactive') state.recorder.stop();
      state.recorder = null;
    }
  };
  const setListening = (on) => {
    if (on === state.listening) return;
    if (useServer) {
      if (typeof MediaRecorder === 'undefined') return;
      state.listening = on;
      record(on);
      return;
    }
    if (!rec) return;
    state.listening = on;
    try { on ? rec.start() : rec.stop(); } catch { /* ignore double start/stop */ }
  };
  state.timer = setInterval(() => {
    analyser.getFloatTimeDomainData(buf);
    let sum = 0; for (const v of buf) sum += v * v;
    const rms = Math.sqrt(sum / buf.length);
    dotnet.invokeMethodAsync('OnLevel', rms);
    if (!options.vad) return;
    const now = performance.now();
    if (rms >= options.threshold) {
      state.quietSince = 0;
      if (!state.speaking) { state.speaking = true; state.speakStart = now; announce(true); dotnet.invokeMethodAsync('OnSpeaking', true); setListening(true); }
    } else if (state.speaking) {
      state.quietSince ||= now;
      if (now - state.quietSince > 900) { state.speaking = false; announce(false, state.quietSince - state.speakStart, now - state.quietSince); dotnet.invokeMethodAsync('OnSpeaking', false); setListening(false); }
    }
  }, 50);
  if (!options.vad) {
    const down = (e) => { if (e.code === options.pushToTalkKey && !e.repeat && !(e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement)) { state.speakStart = performance.now(); announce(true); dotnet.invokeMethodAsync('OnSpeaking', true); setListening(true); } };
    const up = (e) => { if (e.code === options.pushToTalkKey) { announce(false, performance.now() - (state.speakStart || performance.now())); dotnet.invokeMethodAsync('OnSpeaking', false); setListening(false); } };
    window.addEventListener('keydown', down); window.addEventListener('keyup', up);
    state.keys = { down, up };
  }
}

export async function stop() {
  if (!state) return;
  clearInterval(state.timer);
  state.listening = false;
  try { state.rec?.stop(); } catch { /* ignore */ }
  try { if (state.recorder && state.recorder.state !== 'inactive') state.recorder.stop(); } catch { /* ignore */ }
  if (state.keys) { window.removeEventListener('keydown', state.keys.down); window.removeEventListener('keyup', state.keys.up); }
  state.stream.getTracks().forEach(t => t.stop());
  await state.ctx.close();
  state = null;
}
