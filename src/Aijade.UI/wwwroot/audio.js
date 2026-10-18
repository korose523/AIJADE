// Speech playback with a lip-sync level: the output RMS is mapped to a mouth-open value 0..1 and sent to .NET.
let ctx = null;
export async function play(bytes, sink) {
  ctx ??= new AudioContext();
  const data = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  const buffer = await ctx.decodeAudioData(data.buffer.slice(data.byteOffset, data.byteOffset + data.byteLength));
  const src = ctx.createBufferSource();
  src.buffer = buffer;
  const analyser = ctx.createAnalyser();
  analyser.fftSize = 512;
  src.connect(analyser); analyser.connect(ctx.destination);
  const buf = new Float32Array(analyser.fftSize);
  let timer = 0;
  if (sink) {
    timer = setInterval(() => {
      analyser.getFloatTimeDomainData(buf);
      let sum = 0; for (const v of buf) sum += v * v;
      sink.invokeMethodAsync('OnMouth', Math.min(1, Math.sqrt(sum / buf.length) * 6));
    }, 40);
  }
  await new Promise(resolve => { src.onended = resolve; src.start(); });
  clearInterval(timer);
  sink?.invokeMethodAsync('OnMouth', 0);
}
