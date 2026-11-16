// Beat sync input: the low-frequency energy (kick drum and bass, below ~150 Hz) of music the user plays, measured once per
// animation frame and handed to .NET, where the beat detector runs. Sources: the microphone (music in the room) or a shared
// browser tab / system audio. Nothing is captured until start() is called by a user action.
let state = null;

export async function start(dotnet, source) {
  stop();
  let stream;
  try {
    if (source === 'tab') {
      stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: true });
      stream.getVideoTracks().forEach(t => t.stop()); // only the sound is needed
      if (stream.getAudioTracks().length === 0) return 'no audio was shared (tick "share audio")';
    } else {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } });
    }
  } catch (e) {
    return e?.name === 'NotAllowedError' ? 'permission denied' : `audio unavailable (${e?.name ?? e})`;
  }
  const ctx = new AudioContext();
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 1024;
  analyser.smoothingTimeConstant = 0.2;
  ctx.createMediaStreamSource(stream).connect(analyser);
  const bins = new Uint8Array(analyser.frequencyBinCount);
  const top = Math.max(1, Math.round(150 / (ctx.sampleRate / analyser.fftSize)));
  const s = { stream, ctx, raf: 0 };
  const tick = () => {
    analyser.getByteFrequencyData(bins);
    let sum = 0;
    for (let i = 1; i <= top; i++) sum += bins[i];
    dotnet.invokeMethodAsync('OnEnergy', performance.now(), sum / top);
    s.raf = requestAnimationFrame(tick);
  };
  for (const track of stream.getAudioTracks()) track.addEventListener('ended', () => { if (state === s) { stop(); dotnet.invokeMethodAsync('OnEnded'); } });
  s.raf = requestAnimationFrame(tick);
  state = s;
  return null;
}

export function stop() {
  if (!state) return;
  cancelAnimationFrame(state.raf);
  state.stream.getTracks().forEach(t => t.stop());
  state.ctx.close();
  state = null;
}
