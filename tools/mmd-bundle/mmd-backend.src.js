// AIJADE MMD stage backend (bundled by esbuild into src/Aijade.UI/wwwroot/lib/mmd-backend.js).
// Loads a PMX / PMD model (and an optional VMD idle motion) with babylon-mmd and maps the PEF expression vector onto the
// conventional MMD morph names. Morphs a model does not define are simply not applied, and only what was actually applied
// is returned (the render receipt hashes exactly that).
import { Engine } from '@babylonjs/core/Engines/engine';
import { Scene } from '@babylonjs/core/scene';
import { ArcRotateCamera } from '@babylonjs/core/Cameras/arcRotateCamera';
import { HemisphericLight } from '@babylonjs/core/Lights/hemisphericLight';
import { DirectionalLight } from '@babylonjs/core/Lights/directionalLight';
import { Vector3, Quaternion } from '@babylonjs/core/Maths/math.vector';
import { Color3, Color4 } from '@babylonjs/core/Maths/math.color';
import { LoadAssetContainerAsync } from '@babylonjs/core/Loading/sceneLoader';
import '@babylonjs/core/Materials/Textures/Loaders/tgaTextureLoader';
// Registers the shared MMD standard material builder; without it the loader builds no materials or textures.
import 'babylon-mmd/esm/Loader/mmdModelLoader';
import 'babylon-mmd/esm/Loader/pmxLoader';
import 'babylon-mmd/esm/Loader/pmdLoader';
import 'babylon-mmd/esm/Runtime/Animation/mmdRuntimeModelAnimation';
import { SdefInjector } from 'babylon-mmd/esm/Loader/sdefInjector';
import { VmdLoader } from 'babylon-mmd/esm/Loader/vmdLoader';
import { MmdRuntime } from 'babylon-mmd/esm/Runtime/mmdRuntime';
import { MmdStandardMaterialProxy } from 'babylon-mmd/esm/Runtime/mmdStandardMaterialProxy';
import { GetMmdWasmInstance } from 'babylon-mmd/esm/Runtime/Optimized/mmdWasmInstance';
import { MmdWasmInstanceTypeSPR } from 'babylon-mmd/esm/Runtime/Optimized/InstanceType/singlePhysicsRelease';
import { MultiPhysicsRuntime } from 'babylon-mmd/esm/Runtime/Optimized/Physics/Bind/Impl/multiPhysicsRuntime';
import { MmdBulletPhysics } from 'babylon-mmd/esm/Runtime/Optimized/Physics/mmdBulletPhysics';

const clamp = (x, lo = 0, hi = 1) => Math.min(hi, Math.max(lo, x));
const round = (x) => Math.round(x * 1000) / 1000;

/**
 * Emotional posture from the PEF expression vector, in radians of forward pitch (negative = upright): negative valence
 * with low dominance slumps the upper body and neck forward, positive valence with high dominance straightens them. The
 * rule follows the author's MOSAIC native client (companion behaviour, 2026-10-13), kept small enough for any model.
 */
export function postureLean(e) {
  const v = e.valence ?? 0, d = e.dominance ?? 0.5;
  return round(clamp(-v) * (1 - d) * 0.15 - clamp(v) * d * 0.08);
}

/** PEF expression vector → weights of the conventional MMD morphs (eyes / brows); the mouth is driven by speech. */
export function morphWeights(e) {
  const v = e.valence ?? 0, a = e.arousal ?? 0.4, d = e.dominance ?? 0.5, c = e.curiosity ?? 0.5;
  return {
    '笑い': clamp(v * 0.9),
    'にこり': clamp(v * 0.7),
    '困る': clamp(-v * 0.8 * (1 - d)),
    '怒り': clamp(-v * d * a * 1.6),
    '上': clamp((a - 0.6) * 1.5 + (c - 0.6)),
    'びっくり': clamp((a - 0.75) * 3),
  };
}

async function assetVersion(url) {
  let tag = '';
  try {
    const head = await fetch(url, { method: 'HEAD' });
    tag = head.headers.get('etag') || head.headers.get('content-length') || '';
  } catch { /* offline: the URL alone */ }
  const bytes = new TextEncoder().encode(`mmd:${url}|${tag}`);
  const digest = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(digest)].map(b => b.toString(16).padStart(2, '0')).join('');
}

/**
 * Aim the camera at the head and shoulders, measured from the model's own bones (頭 head, 上半身 upper body) so any model
 * scale is framed the same way. Mesh bounding boxes are no use here: the loader pads them for skinning.
 */
function frameHead(camera, model, scale) {
  const at = (name) => {
    const bone = model.runtimeBones.find(b => b.name === name);
    return bone ? bone.getWorldTranslationToRef(new Vector3()) : null;
  };
  const head = at('頭'), chest = at('上半身');
  if (!head || (head.y === 0 && (!chest || chest.y === 0))) return false;
  const span = chest ? Math.max(0.5, head.y - chest.y) : head.y * 0.22;
  camera.setTarget(new Vector3(head.x, head.y - span * 0.15, head.z));
  camera.alpha = -Math.PI / 2;
  camera.beta = Math.PI / 2.05;
  camera.radius = (span * 2.6) / scale;
  camera.lowerRadiusLimit = span * 0.5; camera.upperRadiusLimit = span * 20;
  camera.minZ = span * 0.02;
  return true;
}

/**
 * A language-neutral loading badge over the stage: a ring and the download percentage of the model file, then a plain ring
 * while textures decode. Removed once the scene is ready to draw, or when loading fails.
 */
function loadingBadge(canvas) {
  const host = canvas.parentElement;
  if (!host) return { progress() {}, done() {} };
  const el = document.createElement('div');
  el.className = 'stage-loading';
  el.setAttribute('role', 'progressbar');
  el.innerHTML = '<span class="stage-loading-ring"></span><span class="stage-loading-pct"></span>';
  host.appendChild(el);
  const pct = el.querySelector('.stage-loading-pct');
  return {
    progress(fraction) {
      if (fraction == null) { pct.textContent = ''; el.removeAttribute('aria-valuenow'); return; }
      const v = Math.round(clamp(fraction) * 100);
      pct.textContent = `${v}%`;
      el.setAttribute('aria-valuenow', String(v));
    },
    done() { el.remove(); },
  };
}

export async function createMmdStage(canvas, options) {
  const badge = loadingBadge(canvas);
  try {
    return await createMmdStageCore(canvas, options, badge);
  } catch (e) {
    badge.done();
    throw e;
  }
}

async function createMmdStageCore(canvas, options, badge) {
  const engine = new Engine(canvas, true, { preserveDrawingBuffer: false, stencil: true });
  SdefInjector.OverrideEngineCreateEffect(engine);
  const scene = new Scene(engine);
  const bg = Color3.FromHexString(options.background || '#1e2230');
  // With a background picture the canvas is transparent and the stage container shows the picture behind the model.
  scene.clearColor = new Color4(bg.r, bg.g, bg.b, options.transparent ? 0 : 1);
  scene.ambientColor = new Color3(0.5, 0.5, 0.5);
  // A companion framing: head and shoulders of a ~20-unit-tall MMD model.
  const camera = new ArcRotateCamera('cam', -Math.PI / 2, Math.PI / 2.1, 14 / (options.scale || 1), new Vector3(0, 15, 0), scene);
  camera.lowerRadiusLimit = 4; camera.upperRadiusLimit = 60; camera.wheelPrecision = 20;
  camera.attachControl(canvas, true);
  new HemisphericLight('sky', new Vector3(0, 1, 0), scene).intensity = 0.55;
  const sun = new DirectionalLight('sun', new Vector3(0.5, -1, 1), scene);
  sun.intensity = 0.8;

  // Hair and skirt physics (Bullet, single-threaded WebAssembly: no cross-origin isolation needed). If WebAssembly cannot
  // start, the model still renders, just without physics; the reason is reported with the stage.
  let physics = null, physicsError = null;
  if (options.physics !== false) {
    try {
      const wasm = await GetMmdWasmInstance(new MmdWasmInstanceTypeSPR());
      const physicsRuntime = new MultiPhysicsRuntime(wasm);
      physicsRuntime.setGravity(new Vector3(0, -98, 0));
      physicsRuntime.register(scene);
      physics = new MmdBulletPhysics(physicsRuntime);
    } catch (e) {
      physicsError = String(e?.message ?? e);
    }
  }
  const runtime = new MmdRuntime(scene, physics);
  runtime.register(scene);
  const container = await LoadAssetContainerAsync(options.modelUrl, scene, {
    onProgress: (e) => badge.progress(e.lengthComputable && e.total > 0 ? e.loaded / e.total : null),
  });
  badge.progress(null);
  container.addAllToScene();
  const mesh = container.meshes.find(m => m.metadata?.isMmdModel) ?? container.meshes[0];
  // createMmdModel trims the loader metadata, so the morph names are read first.
  const available = new Set((mesh.metadata?.morphs ?? []).map(m => m.name));
  const model = runtime.createMmdModel(mesh, { materialProxyConstructor: MmdStandardMaterialProxy });
  // Bone world positions exist only once the runtime starts updating the model (after its textures are ready), so keep
  // the default framing until then and re-frame on the first frame that has them.
  const framingDeadline = performance.now() + 30000;
  const framing = scene.onAfterRenderObservable.add(() => {
    if (frameHead(camera, model, options.scale || 1) || performance.now() > framingDeadline) scene.onAfterRenderObservable.remove(framing);
  });
  const set = (name, w) => { if (available.has(name)) { model.morph.setMorphWeight(name, w); return true; } return false; };

  // An idle motion (VMD) loops; without one the model holds its rest pose (physics still settles hair and cloth).
  let motionError = null;
  if (options.motionUrl) {
    try {
      const motion = await new VmdLoader(scene).loadAsync('idle', options.motionUrl);
      model.setRuntimeAnimation(model.createRuntimeAnimation(motion));
      runtime.onAnimationTickObservable.add(() => {
        if (runtime.currentFrameTime >= runtime.animationFrameTimeDuration - 1) runtime.seekAnimation(0, true);
      });
      // At a low frame rate one tick can jump past the end; the runtime then pauses itself there before the tick hook
      // runs, and seeking alone would leave the motion stopped. The stage never pauses the idle motion on purpose, so
      // any pause is the end of a pass: start the next one.
      runtime.onPauseAnimationObservable.add(() => {
        runtime.seekAnimation(0, true);
        void runtime.playAnimation();
      });
    } catch (e) {
      motionError = String(e?.message ?? e);
    }
  }
  runtime.playAnimation();

  let blinkAt = performance.now() + 3000, blink = 0, mouth = 0, bob = 0, lookAt = null;
  // Beats nod the whole model slightly; the eye bones follow the pointer. Both are additive to any idle motion.
  const baseY = mesh.position.y;
  const eyeBones = ['左目', '右目'].map(n => model.runtimeBones.find(b => b.name === n)?.linkedBone).filter(Boolean);
  const eyeRest = eyeBones.map(b => (b.rotationQuaternion ?? Quaternion.Identity()).clone());
  const headBone = model.runtimeBones.find(b => b.name === '頭');
  // Companion behaviours adopted from the author's MOSAIC native client: emotional posture (upper body and neck, eased
  // with a 600 ms half-life), a listening backchannel (a nod 250 ms after the user finishes an utterance of at least
  // 1.2 s, never while the companion speaks) and conversational gaze (brief glances away while speaking). Each is a pitch
  // or eye offset on top of whatever the idle motion poses.
  const linked = (name) => model.runtimeBones.find(b => b.name === name)?.linkedBone ?? null;
  const upperBone = linked('上半身'), neckBone = linked('首'), headLinked = linked('頭');
  const behaviour = { lean: 0, leanTarget: 0, nods: 0, saccades: 0, nodAngle: 0, nodPeak: 0 };
  let userSpeechSince = 0, nodAt = 0, nodStart = 0, nodClock = 0, nodDouble = false, glanceUntil = 0, glanceNext = performance.now() + 2500, glance = { x: 0, y: 0 };
  const written = new Map();
  // Animated bones get their pose rewritten every frame, unanimated ones keep what was written last: offsets are applied to
  // the animated pose, or to the remembered base when the bone still holds the previous frame's result.
  // The runtime keeps its own reference to each bone's quaternion and writes the animation into it, so the offset is written
  // into that same object (assigning a new one would cut the bone off from its animation).
  const pitchBone = (bone, angle) => {
    if (!bone) return;
    if (!bone.rotationQuaternion) bone.rotationQuaternion = Quaternion.Identity();
    const now = bone.rotationQuaternion;
    const prev = written.get(bone);
    const base = prev && now.equalsWithEpsilon(prev.out, 1e-6) ? prev.base : now.clone();
    now.copyFrom(base.multiply(Quaternion.RotationAxis(Vector3.Right(), angle)));
    written.set(bone, { base, out: now.clone() });
  };
  let lastTick = performance.now();
  // Inspection hook for the stage harness and dev tools; not part of the renderer contract.
  canvas.__aijadeMmd = { scene, mesh, model, runtime, physics, behaviour, morphs: [...available], eyes: ['左目', '右目'].map(n => model.runtimeBones.find(b => b.name === n)).filter(Boolean) };
  scene.onBeforeAnimationsObservable.add(() => {
    const now = performance.now();
    const dt = Math.min(1, (now - lastTick) / 1000); // real elapsed time: at a low frame rate the posture still eases on schedule
    lastTick = now;
    const active = lookAt && now < lookAt.until ? lookAt : null;
    // conversational gaze: while speaking (and not following the pointer) glance away now and then
    const speaking = mouth > 0.08;
    if (!active && speaking && now > glanceNext) {
      glance = { x: (Math.random() < 0.5 ? -1 : 1) * (0.5 + Math.random() * 0.3), y: 0.3 };
      glanceUntil = now + 350 + Math.random() * 350;
      glanceNext = glanceUntil + 2500 + Math.random() * 2500;
      behaviour.saccades++;
    }
    const away = !active && now < glanceUntil ? glance : null;
    const gx = active ? active.x : away ? away.x : 0, gy = active ? active.y : away ? away.y : 0;
    eyeBones.forEach((bone, i) => {
      bone.rotationQuaternion = eyeRest[i].multiply(Quaternion.RotationYawPitchRoll(gx * 0.35, gy * 0.2, 0));
    });
    // posture eases towards its target
    behaviour.lean += (behaviour.leanTarget - behaviour.lean) * (1 - Math.exp(-dt * Math.LN2 / 0.6));
    pitchBone(upperBone, behaviour.lean * 0.6);
    pitchBone(neckBone, behaviour.lean * 0.4);
    // listening backchannel: one nod, or two for every third
    if (nodAt && now >= nodAt) {
      if (mouth < 0.05) { nodStart = now; nodClock = 0; nodDouble = behaviour.nods % 3 === 1; behaviour.nods++; behaviour.nodPeak = 0; }
      nodAt = 0;
    }
    // the nod's own clock advances at most 0.1 s per frame: at a low frame rate it plays slowly instead of being skipped
    if (nodStart) nodClock += Math.min(dt, 0.1);
    const span = nodDouble ? 1.0 : 0.5;
    behaviour.nodAngle = nodStart && nodClock < span ? 0.16 * Math.sin(Math.PI * (nodClock % 0.5) / 0.5) : 0;
    if (nodStart && nodClock >= span) nodStart = 0;
    behaviour.nodPeak = Math.max(behaviour.nodPeak, behaviour.nodAngle);
    pitchBone(headLinked, behaviour.nodAngle);
  });
  scene.onBeforeRenderObservable.add(() => {
    bob *= 0.88;
    const span = headBone ? Math.max(1, headBone.getWorldTranslationToRef(new Vector3()).y * 0.05) : 1;
    mesh.position.y = baseY - bob * span * 0.25;
    const t = performance.now();
    if (t > blinkAt) { blink = 1; blinkAt = t + 2500 + Math.random() * 3000; }
    blink = Math.max(0, blink - 0.12);
    set('まばたき', blink);
    set('あ', mouth);
  });
  engine.runRenderLoop(() => scene.render());
  scene.executeWhenReady(() => badge.done());
  const onResize = () => engine.resize();
  window.addEventListener('resize', onResize);
  const version = await assetVersion(options.modelUrl);

  return {
    kind: 'mmd',
    assetVersionHash: version,
    physics: physics !== null,
    notes: [physicsError && `physics off: ${physicsError}`, motionError && `idle motion not loaded: ${motionError}`].filter(Boolean),
    apply(p) {
      const applied = {};
      for (const [name, w] of Object.entries(morphWeights(p.expression || {}))) {
        if (set(name, w)) applied[`morph.${name}`] = round(w);
      }
      behaviour.leanTarget = postureLean(p.expression || {});
      if (upperBone || neckBone) applied['posture.lean'] = behaviour.leanTarget;
      if (p.face) applied.face = p.face;
      return applied;
    },
    mouth(level) { mouth = clamp(level); },
    beat(strength) { bob = Math.max(bob, 0.4 + 0.6 * clamp(strength)); },
    look(x, y) { lookAt = { x: Math.max(-1, Math.min(1, x)), y: Math.max(-1, Math.min(1, y)), until: performance.now() + 3000 }; },
    /** The user started (true) or stopped (false) speaking: a finished utterance of at least 1.2 s earns a nod. */
    userSpeech(on, spokeMs, quietMs = 0) {
      const now = performance.now();
      if (on) { userSpeechSince ||= now; return; }
      const spoke = spokeMs ?? (userSpeechSince ? now - userSpeechSince : 0);
      if (spoke >= 1200) nodAt = now + Math.max(0, 250 - quietMs);
      userSpeechSince = 0;
    },
    dispose() {
      badge.done();
      window.removeEventListener('resize', onResize);
      engine.stopRenderLoop();
      scene.dispose();
      engine.dispose();
    },
  };
}
