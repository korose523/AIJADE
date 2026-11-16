// Speech playback with a lip-sync level: the output RMS is mapped to a mouth-open value 0..1 and sent to .NET. With a plan
// from the aligned text (ADR-003: per frame of plan.frameHz the vowel shape a/i/u/e/o, null between characters, and lip
// closures), the vowel shape and closure at the moment of the audio go with it; frame k takes effect at (k + 1) / frameHz,
// and a shape stays until the next one, as in MOSAIC's behaviour plan.
//
// Browsers let a page's audio start only after, or during, a click or key press on the page (their autoplay rules). A line
// said before that, such as a reminder that comes due after a reload, is shown but not heard; the next click or key press
// lets later lines be heard. The turn never waits on audio that cannot play.
let ctx = null;
let waking = false;
export async function play(bytes, sink, plan) {
  ctx ??= new AudioContext();
  if (ctx.state !== 'running' && !(await resume())) {
    wakeOnNextGesture();
    return;
  }
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
  // At most the audio's own length and a little more, also when the browser stops the audio while it plays.
  let limit = 0;
  await new Promise(resolve => { src.onended = resolve; src.start(); started = ctx.currentTime; limit = setTimeout(resolve, buffer.duration * 1000 + 1500); });
  clearTimeout(limit);
  clearInterval(timer);
  sink?.invokeMethodAsync('OnMouth', 0, null, 0);
}

// Whether the context runs within a second: where the browser does not allow audio yet, resume() stays pending or is refused.
async function resume() {
  await Promise.race([ctx.resume().catch(() => {}), new Promise(resolve => setTimeout(resolve, 1000))]);
  return ctx.state === 'running';
}

// The next click or key press anywhere on the page lets the context run (within the gesture, as the stricter browsers ask).
function wakeOnNextGesture() {
  if (waking) return;
  waking = true;
  const wake = () => {
    waking = false;
    document.removeEventListener('click', wake, true);
    document.removeEventListener('keydown', wake, true);
    ctx.resume().catch(() => {});
  };
  document.addEventListener('click', wake, true);
  document.addEventListener('keydown', wake, true);
}
