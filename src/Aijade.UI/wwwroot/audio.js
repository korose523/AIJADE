// Speech playback with a lip-sync level: the output RMS is mapped to a mouth-open value 0..1 and sent to .NET. With a plan
// from the aligned text (ADR-003: per frame of plan.frameHz the vowel shape a/i/u/e/o, null between characters, and lip
// closures), the vowel shape and closure at the moment of the audio go with it; frame k takes effect at (k + 1) / frameHz,
// and a shape stays until the next one, as in MOSAIC's behaviour plan.
let ctx = null;
export async function play(bytes, sink, plan) {
  ctx ??= new AudioContext();
  const data = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  const buffer = await ctx.decodeAudioData(data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength));
  const src = ctx.createBufferSource();
  src.buffer = buffer;
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 512;
  src.connect(analyser); analyser.connect(ctx.destination);
  const buf = new Float32Array(analyser.fftSize);
  let timer = 0, started = 0, vowels = null, lips = 0, next = 0;
  if (sink) {
    timer = setInterval(() => {
      analyser.getFloatTimeDomainData(buf);
      let sum = 0; for (const v of buf) sum += v * v;
      if (plan) {
        const k = Math.floor((ctx.currentTime - started) * plan.frameHz) - 1;
        if (k >= 0 && k < plan.vowels.length && plan.vowels[k]) vowels = plan.vowels[k];
        while (next < plan.lips.length && plan.lips[next].frame <= k) lips = plan.lips[next++].value;
      }
      sink.invokeMethodAsync('OnMouth', Math.min(1, Math.sqrt(sum / buf.length) * 6), vowels, lips);
    }, 40);
  }
  await new Promise(resolve => { src.onended = resolve; src.start(); started = ctx.currentTime; });
  clearInterval(timer);
  sink?.invokeMethodAsync('OnMouth', 0, null, 0);
}
