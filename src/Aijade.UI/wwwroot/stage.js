// The AIJADE stage. A renderer is chosen at mount: the MMD renderer (PMX/PMD models with VMD motions) when a model URL is
// configured and the MMD backend module is installed, otherwise the built-in avatar — a procedural face driven by the PEF
// expression vector, which is also the "controllable avatar" fallback of the identity-consistency check.
// Every apply() returns the parameter map that was actually applied: the client hashes it into the render receipt.

let current = null;

function clamp(x, lo = 0, hi = 1) { return Math.min(hi, Math.max(lo, x)); }
function round(x) { return Math.round(x * 1000) / 1000; }

class AvatarRenderer {
  constructor(canvas, options) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.background = options.background || '#1e2230';
    // With a background picture the canvas stays transparent and the stage container shows the picture behind it.
    this.transparent = !!options.transparent;
    this.target = { valence: 0, arousal: 0.4, dominance: 0.5, intimacy: 0.4, certainty: 0.6, curiosity: 0.5, playfulness: 0.3, reflection: 0.4, urgency: 0.2 };
    this.now = { ...this.target };
    this.mouthOpen = 0;
    this.blink = 0; this.nextBlink = performance.now() + 2500;
    this.gaze = 'natural_conversational';
    this.bob = 0; this.lookAt = null;
    this.running = true;
    const loop = (t) => { if (!this.running) return; this.step(t); this.draw(t); requestAnimationFrame(loop); };
    requestAnimationFrame(loop);
  }
  get kind() { return 'avatar'; }
  get assetVersionHash() { return 'builtin-avatar-aijade9-v2'; }
  apply(p) {
    const e = p.expression || {};
    for (const k of Object.keys(this.target)) if (typeof e[k] === 'number') this.target[k] = e[k];
    if (p.gaze) this.gaze = p.gaze;
    const applied = {};
    for (const [k, v] of Object.entries(this.target)) applied[`expr.${k}`] = round(v);
    if (p.face) applied.face = p.face;
    if (p.gaze) applied.gaze = p.gaze;
    if (p.gesture) applied.gesture = p.gesture;
    if (p.posture) applied.posture = p.posture;
    return applied;
  }
  mouth(v) { this.mouthOpen = clamp(v); }
  /** A beat from the music: a small nod whose size follows the beat's strength. */
  beat(strength) { this.bob = Math.max(this.bob, 0.4 + 0.6 * clamp(strength)); }
  /** Follow the pointer with the eyes (x, y in -1…1 across the stage); the look fades after a few seconds. */
  look(x, y) { this.lookAt = { x: Math.max(-1, Math.min(1, x)), y: Math.max(-1, Math.min(1, y)), until: performance.now() + 3000 }; }
  /** Listening backchannel: after the user finishes an utterance of at least 1.2 s, a small nod 250 ms later. */
  userSpeech(on, spokeMs, quietMs = 0) {
    const now = performance.now();
    if (on) { this.userSince ||= now; return; }
    const spoke = spokeMs ?? (this.userSince ? now - this.userSince : 0);
    if (spoke >= 1200) setTimeout(() => { if (this.mouthOpen < 0.05) { this.bob = Math.max(this.bob, 0.6); this.nods = (this.nods || 0) + 1; } }, Math.max(0, 250 - quietMs));
    this.userSince = 0;
  }
  step(t) {
    this.bob *= 0.88;
    for (const k of Object.keys(this.now)) this.now[k] += (this.target[k] - this.now[k]) * 0.08;
    if (t > this.nextBlink) { this.blink = 1; this.nextBlink = t + 2500 + Math.random() * 3000; }
    this.blink = Math.max(0, this.blink - 0.15);
  }
  // The built-in avatar draws Aijade-9 (艾娅德) as in brand/aijade-9/reference: long straight platinum-blonde hair with
  // bangs and an ahoge, a white frilled maid headdress, a black bow on one side, blue eyes, diamond earrings and a black
  // choker with a white frill and a ribbon.
  draw(t) {
    const { ctx, canvas } = this;
    const w = canvas.width = canvas.clientWidth * devicePixelRatio;
    const h = canvas.height = canvas.clientHeight * devicePixelRatio;
    if (this.transparent) ctx.clearRect(0, 0, w, h);
    else { ctx.fillStyle = this.background; ctx.fillRect(0, 0, w, h); }
    const e = this.now;
    const s = Math.min(w, h) * 0.24;
    const cx = w / 2, cy = h * 0.52 + Math.sin(t / 900) * s * 0.02 * (0.5 + e.arousal) + this.bob * s * 0.06;
    const HAIR = '#efe7d6', HAIR_SHADE = '#d9cdb5', SKIN = '#fbeee4', EYE = '#4f7fe6', EYE_DARK = '#2b4fae';
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate((e.curiosity - 0.5) * 0.25 + (this.gaze === 'briefly_averted_thinking' ? -0.08 : 0));
    // long hair behind the head, falling past the shoulders
    ctx.fillStyle = HAIR_SHADE;
    ctx.beginPath();
    ctx.moveTo(-s * 1.05, -s * 0.2);
    ctx.quadraticCurveTo(-s * 1.25, s * 1.4, -s * 1.0, s * 2.6);
    ctx.lineTo(s * 1.0, s * 2.6);
    ctx.quadraticCurveTo(s * 1.25, s * 1.4, s * 1.05, -s * 0.2);
    ctx.closePath(); ctx.fill();
    ctx.fillStyle = HAIR; ctx.beginPath(); ctx.ellipse(0, -s * 0.15, s * 1.08, s * 1.12, 0, 0, Math.PI * 2); ctx.fill();
    // neck and choker (black band, white frill, black ribbon)
    ctx.fillStyle = SKIN; ctx.fillRect(-s * 0.22, s * 0.85, s * 0.44, s * 0.45);
    ctx.fillStyle = '#ffffff';
    for (let i = -4; i <= 4; i++) { ctx.beginPath(); ctx.arc(i * s * 0.06, s * 1.02, s * 0.045, 0, Math.PI * 2); ctx.fill(); }
    ctx.fillStyle = '#1b1b22'; ctx.fillRect(-s * 0.26, s * 1.05, s * 0.52, s * 0.08);
    ctx.strokeStyle = '#1b1b22'; ctx.lineWidth = s * 0.025;
    ctx.beginPath(); ctx.moveTo(0, s * 1.13); ctx.lineTo(-s * 0.08, s * 1.32); ctx.moveTo(0, s * 1.13); ctx.lineTo(s * 0.08, s * 1.32); ctx.stroke();
    // face
    ctx.fillStyle = SKIN; ctx.beginPath(); ctx.ellipse(0, s * 0.05, s * 0.86, s * 0.95, 0, 0, Math.PI * 2); ctx.fill();
    // diamond earrings
    ctx.fillStyle = '#c9ced8'; ctx.strokeStyle = '#7d8494'; ctx.lineWidth = s * 0.012;
    for (const side of [-1, 1]) {
      const ex = side * s * 0.84, ey = s * 0.45 + Math.sin(t / 500 + side) * s * 0.01;
      ctx.beginPath(); ctx.moveTo(ex, ey); ctx.lineTo(ex + s * 0.07, ey + s * 0.11); ctx.lineTo(ex, ey + s * 0.22); ctx.lineTo(ex - s * 0.07, ey + s * 0.11); ctx.closePath(); ctx.fill(); ctx.stroke();
    }
    // blush
    ctx.fillStyle = `rgba(240,120,140,${0.15 + clamp(e.intimacy - 0.3) * 0.5})`;
    for (const side of [-1, 1]) { ctx.beginPath(); ctx.ellipse(side * s * 0.46, s * 0.3, s * 0.15, s * 0.07, 0, 0, Math.PI * 2); ctx.fill(); }
    // eyes: large blue irises with highlights; arousal opens, blinking closes
    const looking = this.lookAt && performance.now() < this.lookAt.until ? this.lookAt : null;
    const gx = looking ? looking.x * s * 0.05 : this.gaze === 'briefly_averted_thinking' ? -s * 0.06 : 0;
    const gy = looking ? looking.y * s * 0.04 : 0;
    const open = clamp(0.4 + e.arousal * 0.6) * (1 - this.blink);
    for (const side of [-1, 1]) {
      const ex = side * s * 0.34, ey = s * 0.02;
      ctx.fillStyle = '#ffffff'; ctx.beginPath(); ctx.ellipse(ex, ey, s * 0.17, s * 0.21 * open + 0.5, 0, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = EYE; ctx.beginPath(); ctx.ellipse(ex + gx, ey + gy + s * 0.01, s * 0.12, s * 0.17 * open + 0.5, 0, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = EYE_DARK; ctx.beginPath(); ctx.ellipse(ex + gx, ey + gy + s * 0.03, s * 0.06, s * 0.09 * open + 0.3, 0, 0, Math.PI * 2); ctx.fill();
      if (open > 0.2) { ctx.fillStyle = '#ffffff'; ctx.beginPath(); ctx.arc(ex + gx - s * 0.04, ey + gy - s * 0.06 * open, s * 0.035, 0, Math.PI * 2); ctx.fill(); }
      ctx.strokeStyle = '#3a2f2a'; ctx.lineWidth = s * 0.035; ctx.lineCap = 'round';
      ctx.beginPath(); ctx.ellipse(ex, ey, s * 0.18, s * 0.21 * open + 0.5, 0, Math.PI * 1.1, Math.PI * 1.9); ctx.stroke();
      // brows: valence lifts, low dominance tilts
      ctx.strokeStyle = '#c9b99c'; ctx.lineWidth = s * 0.03;
      const lift = s * (0.3 + e.valence * 0.06 + (e.arousal - 0.5) * 0.08);
      const tilt = (0.5 - e.dominance) * s * 0.12 * side;
      ctx.beginPath(); ctx.moveTo(side * s * 0.2, -lift + tilt); ctx.lineTo(side * s * 0.48, -lift - tilt); ctx.stroke();
    }
    // bangs over the forehead (clipped to the head), with an ahoge
    ctx.save();
    ctx.beginPath(); ctx.ellipse(0, -s * 0.15, s * 1.08, s * 1.12, 0, 0, Math.PI * 2); ctx.clip();
    ctx.fillStyle = HAIR;
    ctx.beginPath();
    ctx.moveTo(-s * 1.1, -s * 1.3);
    ctx.lineTo(-s * 1.1, s * 0.15);
    for (let i = 0; i < 9; i++) {
      const x0 = -s * 1.1 + i * s * 0.245, x1 = x0 + s * 0.245;
      const tip = i % 2 ? -s * 0.1 : -s * 0.2;
      ctx.quadraticCurveTo((x0 + x1) / 2, -s * 0.55, x1, tip);
    }
    ctx.lineTo(s * 1.1, -s * 1.3);
    ctx.closePath(); ctx.fill();
    ctx.strokeStyle = HAIR_SHADE; ctx.lineWidth = s * 0.02;
    for (let i = -3; i <= 3; i++) { ctx.beginPath(); ctx.moveTo(i * s * 0.22, -s * 1.0); ctx.quadraticCurveTo(i * s * 0.26, -s * 0.5, i * s * 0.27, -s * 0.2); ctx.stroke(); }
    ctx.restore();
    ctx.strokeStyle = HAIR_SHADE; ctx.lineWidth = s * 0.03;
    ctx.beginPath(); ctx.moveTo(s * 0.05, -s * 1.2); ctx.quadraticCurveTo(s * 0.45, -s * 1.5, s * 0.6, -s * 1.25); ctx.stroke();
    // white frilled maid headdress
    ctx.fillStyle = '#ffffff'; ctx.strokeStyle = '#d6d6de'; ctx.lineWidth = s * 0.015;
    for (let i = -4; i <= 4; i++) {
      const a = -Math.PI / 2 + i * 0.2;
      ctx.beginPath(); ctx.ellipse(Math.cos(a) * s * 1.02, -s * 0.15 + Math.sin(a) * s * 1.04, s * 0.13, s * 0.16, a + Math.PI / 2, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    }
    // black bow on one side
    ctx.fillStyle = '#1b1b22';
    const bx = -s * 0.98, by = -s * 0.38, k = 1.4;
    ctx.beginPath(); ctx.moveTo(bx, by); ctx.lineTo(bx - s * 0.22 * k, by - s * 0.16 * k); ctx.lineTo(bx - s * 0.2 * k, by + s * 0.16 * k); ctx.closePath(); ctx.fill();
    ctx.beginPath(); ctx.moveTo(bx, by); ctx.lineTo(bx + s * 0.2 * k, by - s * 0.18 * k); ctx.lineTo(bx + s * 0.18 * k, by + s * 0.14 * k); ctx.closePath(); ctx.fill();
    ctx.beginPath(); ctx.arc(bx, by, s * 0.06, 0, Math.PI * 2); ctx.fill();
    ctx.lineWidth = s * 0.03; ctx.strokeStyle = '#1b1b22';
    ctx.beginPath(); ctx.moveTo(bx, by); ctx.lineTo(bx - s * 0.08, by + s * 0.45); ctx.moveTo(bx, by); ctx.lineTo(bx + s * 0.06, by + s * 0.4); ctx.stroke();
    // mouth: curve by valence, opening by speech level
    const mw = s * (0.16 + e.playfulness * 0.06);
    const curve = e.valence * s * 0.14;
    const mo = this.mouthOpen * s * 0.2;
    ctx.fillStyle = '#c24f63'; ctx.strokeStyle = '#7d2e3d'; ctx.lineWidth = s * 0.025;
    ctx.beginPath();
    ctx.moveTo(-mw, s * 0.55);
    ctx.quadraticCurveTo(0, s * 0.55 + curve + mo, mw, s * 0.55);
    ctx.quadraticCurveTo(0, s * 0.55 + curve * 0.3 - mo * 0.2, -mw, s * 0.55);
    ctx.fill(); ctx.stroke();
    ctx.restore();
  }
  dispose() { this.running = false; }
}

let pointer = null;

/** The eyes follow the pointer (or a touch) over the stage. */
function followPointer(canvas) {
  const onMove = (e) => {
    const r = canvas.getBoundingClientRect();
    current?.look?.(((e.clientX - r.left) / r.width) * 2 - 1, ((e.clientY - r.top) / r.height) * 2 - 1);
  };
  canvas.addEventListener('pointermove', onMove);
  pointer = { canvas, onMove };
}

/** Mount the stage on a canvas. Returns { renderer, assetVersionHash, fallbackReason?, notes? }. */
export async function mount(canvasId, options) {
  unmount();
  const canvas = document.getElementById(canvasId);
  if (!canvas) throw new Error(`no canvas #${canvasId}`);
  followPointer(canvas);
  if (options.modelUrl) {
    try {
      const { MmdRenderer } = await import('./mmd-renderer.js');
      current = await MmdRenderer.create(canvas, options);
      return { renderer: current.kind, assetVersionHash: current.assetVersionHash, notes: current.notes ?? [] };
    } catch (e) {
      current = new AvatarRenderer(canvas, options);
      return { renderer: current.kind, assetVersionHash: current.assetVersionHash, fallbackReason: String(e?.message ?? e) };
    }
  }
  current = new AvatarRenderer(canvas, options);
  return { renderer: current.kind, assetVersionHash: current.assetVersionHash };
}

/**
 * Shrink an uploaded picture so that it fits in maxSide × maxSide and return it as a JPEG data: URL (settings live in
 * browser storage, so a photo straight from a camera would not fit).
 */
export async function fitImage(bytes, mime, maxSide) {
  const blob = new Blob([bytes], { type: mime || 'image/png' });
  const bitmap = await createImageBitmap(blob);
  const k = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(bitmap.width * k));
  canvas.height = Math.max(1, Math.round(bitmap.height * k));
  canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close?.();
  return canvas.toDataURL('image/jpeg', 0.85);
}

export function apply(params) { return current ? current.apply(params) : {}; }
export function mouth(level) { current?.mouth(level); }
export function beat(strength) { current?.beat?.(strength); }
export function look(x, y) { current?.look?.(x, y); }
export function userSpeech(on, spokeMs, quietMs) { current?.userSpeech?.(on, spokeMs, quietMs); }
// The microphone module announces the user's speech (voice activity) on the window; the stage listens without a round trip through .NET.
window.addEventListener('aijade-user-speech', (e) => userSpeech(!!e.detail?.speaking, e.detail?.spokeMs, e.detail?.quietMs));
export function unmount() {
  if (pointer) { pointer.canvas.removeEventListener('pointermove', pointer.onMove); pointer = null; }
  current?.dispose(); current = null;
}
