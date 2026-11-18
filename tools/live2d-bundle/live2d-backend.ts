import { CubismFramework } from 'cubism-framework/live2dcubismframework';
import { CubismMatrix44 } from 'cubism-framework/math/cubismmatrix44';
import { CubismUserModel } from 'cubism-framework/model/cubismusermodel';
import { CubismShaderManager_WebGL } from 'cubism-framework/rendering/cubismshader_webgl';

const modelDirectory = '/_aijade/live2d/model/';
const frameInterval = 1000 / 30;
const singleMaskBufferCapacity = 36; // Cubism 5-r.5 can use nine masks per channel in one buffer.
const dualMaskBufferCapacity = 64; // With multiple buffers Cubism uses at most eight masks per channel.
const dualMaskBufferSize = 768; // Maintain at least 256 pixels along each axis of a 3 × 3 cell.
const decoder = new TextDecoder();
let activeContexts = 0;

function bounded(value, low, high) {
  return Math.max(low, Math.min(high, Number.isFinite(value) ? value : 0));
}

function assetUrl(name, base) {
  if (typeof name !== 'string' || !name)
    throw new Error('The Live2D model references an empty file name.');
  const url = new URL(name, base);
  if (url.origin !== location.origin || !url.pathname.startsWith(modelDirectory))
    throw new Error('Live2D files must stay within the installed local model directory.');
  return url.href;
}

async function readBytes(url, signal, optional = false) {
  const response = await fetch(url, { signal, credentials: 'same-origin' });
  if (optional && response.status === 404) return null;
  if (!response.ok) throw new Error(`Live2D file could not be read (HTTP ${response.status}).`);
  return response.arrayBuffer();
}

async function digest(bytes) {
  const hash = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
  return Array.from(hash, byte => byte.toString(16).padStart(2, '0')).join('');
}

function countDrawableMaskGroups(model) {
  const masks = model.getDrawableMasks();
  const counts = model.getDrawableMaskCounts();
  const groups = new Set<string>();
  for (let index = 0; index < counts.length; index++) {
    if (counts[index] === 0) continue;
    // A shared set of mask drawables occupies one slot irrespective of its order.
    groups.add(masks[index].slice(0, counts[index]).sort().join(','));
  }
  return groups.size;
}

async function uploadTexture(gl, texture, bytes, limit) {
  const png = bytes.byteLength >= 24 && new DataView(bytes).getUint32(0) === 0x89504e47;
  const options: ImageBitmapOptions = { premultiplyAlpha: 'premultiply' };
  if (png) {
    const header = new DataView(bytes);
    const [width, height] = [header.getUint32(16), header.getUint32(20)];
    const ratio = Math.min(1, limit / Math.max(width, height));
    if (ratio < 1) {
      options.resizeWidth = Math.max(1, Math.round(width * ratio));
      options.resizeHeight = Math.max(1, Math.round(height * ratio));
      options.resizeQuality = 'high';
    }
  }
  const bitmap = await createImageBitmap(new Blob([bytes]), options);
  try {
    if (Math.max(bitmap.width, bitmap.height) > limit)
      throw new Error('The decoded Live2D texture exceeds the local size limit.');
    gl.bindTexture(gl.TEXTURE_2D, texture);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, bitmap);
    if (gl.getError() !== gl.NO_ERROR) throw new Error('The browser could not upload a Live2D texture.');
    return [bitmap.width, bitmap.height];
  } finally {
    bitmap.close();
    gl.bindTexture(gl.TEXTURE_2D, null);
  }
}

class StageModel extends CubismUserModel {
  startIdle(bytes, groups) {
    const motion = this.loadMotion(bytes, bytes.byteLength, 'idle');
    if (!motion) throw new Error('The Live2D idle motion could not be read.');
    // The Cubism motion evaluator requires both lists even if the manifest omits one group.
    const ids = name => (groups?.find(group => group.Target === 'Parameter' && group.Name === name)?.Ids ?? [])
      .map(id => CubismFramework.getIdManager().getId(id));
    motion.setEffectIds(ids('EyeBlink'), ids('LipSync'));
    motion.setLoop(true);
    this._motionManager.startMotionPriority(motion, true, 1);
  }

  advance(seconds) {
    const model = this.getModel();
    model.loadParameters();
    this._motionManager.updateMotion(model, seconds);
    model.saveParameters();
    this._expressionManager.updateMotion(model, seconds);
  }

  playExpression(bytes, name) {
    if (bytes === null) {
      this._expressionManager.stopAllMotions();
    } else {
      const motion = this.loadExpression(bytes, bytes.byteLength, name);
      if (!motion) throw new Error('The Live2D expression could not be read.');
      this._expressionManager.startMotion(motion, true);
    }
  }

  simulate(seconds) {
    this._physics?.evaluate(this.getModel(), seconds);
    this.getModel().update();
  }
}

export async function createLive2D(canvas, options, runtimePath, loadingSignal) {
  loadingSignal.throwIfAborted();
  const modelUrl = options.modelUrl;
  const profileUrl = assetUrl('aijade-live2d.json', modelUrl);
  const [manifestBytes, profileBytes] = await Promise.all([
    readBytes(modelUrl, loadingSignal),
    readBytes(profileUrl, loadingSignal, true),
  ]);
  const manifest = JSON.parse(decoder.decode(manifestBytes));
  const profile = profileBytes ? JSON.parse(decoder.decode(profileBytes)) : {};
  const attribution = typeof profile.attribution === 'string' ? profile.attribution.trim() : '';
  const references = manifest.FileReferences;
  if (manifest.Version !== 3 || !Array.isArray(references?.Textures) || !references.Textures.length)
    throw new Error('The installed file is not a Live2D model3 manifest with textures.');

  const mocUrl = assetUrl(references.Moc, modelUrl);
  const idle = options.motionUrl?.toLowerCase().includes('.motion3.json') ? options.motionUrl : profile.idleMotion;
  const idleUrl = idle ? assetUrl(idle, modelUrl) : null;
  const physicsUrl = options.physics && references.Physics ? assetUrl(references.Physics, modelUrl) : null;
  const [moc, idleBytes, physicsBytes] = await Promise.all([
    readBytes(mocUrl, loadingSignal),
    idleUrl ? readBytes(idleUrl, loadingSignal) : null,
    physicsUrl ? readBytes(physicsUrl, loadingSignal) : null,
  ]);
  loadingSignal.throwIfAborted();
  if (!CubismFramework.isStarted()) CubismFramework.startUp();
  if (!CubismFramework.isInitialized()) CubismFramework.initialize();

  // A separate WebGL surface leaves the visible canvas usable for either this renderer or the 2D fallback.
  const surface = document.createElement('canvas');
  const gl = surface.getContext('webgl', {
    alpha: true, premultipliedAlpha: true, antialias: false, preserveDrawingBuffer: false,
  });
  const display = canvas.getContext('2d');
  if (!gl || !display) throw new Error('Live2D requires WebGL and a 2D stage canvas.');
  activeContexts++;
  const model = new StageModel();
  const textures = [];
  const events = new AbortController();
  let frame = 0;
  let disposed = false;
  let measureFrame = null;
  function dispose() {
    if (disposed) return;
    disposed = true;
    cancelAnimationFrame(frame);
    measureFrame?.({});
    events.abort();
    model.release();
    for (const texture of textures) gl.deleteTexture(texture);
    if (--activeContexts === 0) CubismShaderManager_WebGL.deleteInstance();
    gl.getExtension('WEBGL_lose_context')?.loseContext();
  }

  try {
    // Let Cubism Core verify the moc before constructing the model.
    model.loadModel(moc, true);
    const core = model.getModel();
    if (!core) throw new Error('The installed Cubism Core cannot open this model.');
    if (idleBytes) model.startIdle(idleBytes, manifest.Groups);
    if (physicsBytes) model.loadPhysics(physicsBytes, physicsBytes.byteLength);

    const projection = new CubismMatrix44();
    const limit = Math.min(gl.getParameter(gl.MAX_TEXTURE_SIZE),
      bounded(profile.maxTextureSize ?? 2048, 512, 4096));
    const resize = () => {
      const dpr = Math.min(1.5, devicePixelRatio || 1);
      const width = Math.max(1, Math.round(canvas.clientWidth * dpr));
      const height = Math.max(1, Math.round(canvas.clientHeight * dpr));
      if (canvas.width !== width || canvas.height !== height) {
        canvas.width = width;
        canvas.height = height;
      }
      if (surface.width !== width || surface.height !== height) {
        surface.width = width;
        surface.height = height;
        model.setRenderTargetSize(width, height);
      }
    };
    resize();
    const maskGroups = countDrawableMaskGroups(core);
    const highMaskCount = maskGroups > singleMaskBufferCapacity;
    const useDualMasks = profile.maskMode === 'packed' && highMaskCount &&
      maskGroups <= dualMaskBufferCapacity && !core.isBlendModeEnabled() &&
      Math.min(gl.getParameter(gl.MAX_TEXTURE_SIZE), gl.getParameter(gl.MAX_RENDERBUFFER_SIZE)) >= dualMaskBufferSize;
    const maskBufferCount = useDualMasks ? 2 : 1;
    model.createRenderer(surface.width, surface.height, maskBufferCount);
    const renderer = model.getRenderer();
    if (useDualMasks) renderer.setClippingMaskBufferSize(dualMaskBufferSize);
    // Repaint masks one draw at a time when their groups do not fit a verified packed layout.
    else if (highMaskCount) renderer.useHighPrecisionMask(true);
    renderer.startUp(gl);
    renderer.setIsPremultipliedAlpha(true);

    const hashes = await Promise.all([manifestBytes, moc, profileBytes, idleBytes, physicsBytes].filter(Boolean).map(digest));
    const textureSizes = [];
    // Decode one image at a time and close the bitmap immediately so five large sources do not retain decoded memory.
    for (const [index, file] of references.Textures.entries()) {
      const bytes = await readBytes(assetUrl(file, modelUrl), loadingSignal);
      const texture = gl.createTexture();
      if (!texture) throw new Error('The browser could not allocate a Live2D texture.');
      textures.push(texture);
      textureSizes.push(await uploadTexture(gl, texture, bytes, limit));
      hashes.push(await digest(bytes));
      renderer.bindTexture(index, texture);
    }
    const version = await digest(new TextEncoder().encode(hashes.join('\n')));

    loadingSignal.throwIfAborted();
    renderer.loadShaders(runtimePath + 'shaders/');
    const shaderDeadline = performance.now() + 5000;
    while (!CubismShaderManager_WebGL.getInstance().getShader(gl)?._isShaderLoaded) {
      loadingSignal.throwIfAborted();
      if (performance.now() >= shaderDeadline) throw new Error('The local Live2D shaders failed to load.');
      await new Promise(resolve => setTimeout(resolve, 25));
    }
    loadingSignal.throwIfAborted();

    const param = Object.create(null);
    for (let index = 0; index < core.getParameterCount(); index++)
      param[core.getParameterId(index).getString()] = index;
    const set = (name, value, weight = 1) => {
      if (param[name] !== undefined) core.setParameterValueByIndex(param[name], value, weight);
    };
    const physicsInputs = new Map();
    for (const [output, input] of Object.entries(physicsBytes ? profile.physicsInputs || {} : {})) {
      if (typeof input !== 'string' || param[input] === undefined) continue;
      const index = param[input];
      physicsInputs.set(output, {
        index,
        neutral: core.getParameterDefaultValue(index),
        min: core.getParameterMinimumValue(index),
        max: core.getParameterMaximumValue(index),
      });
    }
    const drive = (name, degrees, weight) => {
      const input = physicsInputs.get(name);
      if (!input) {
        set(name, degrees, weight);
        return;
      }
      const fraction = bounded(degrees / 30, -1, 1);
      const span = fraction < 0 ? input.neutral - input.min : input.max - input.neutral;
      core.setParameterValueByIndex(input.index, input.neutral + fraction * span, weight);
    };
    const expressionCache = new Map();
    const target = { valence: 0, curiosity: 0 };
    const animated = { ...target, lookX: 0, lookY: 0, mouth: 0 };
    let selectedExpression = null;
    let latestApply = 0;
    let gaze = null;
    let attention = null;
    let open = 0;
    let pulse = 0;
    let last = performance.now();
    let elapsed = 0;
    let frames = 0;
    const measured = ['ParamAngleX', 'ParamAngleY', 'ParamEyeBallX', 'ParamEyeBallY',
      'ParamMouthForm', 'ParamMouthOpenY', 'ParamBodyAngleZ'].filter(name => param[name] !== undefined);
    function draw(now) {
      const dt = bounded((now - last) / 1000, 0, 0.05);
      last = now;
      elapsed += dt;
      pulse *= Math.exp(-dt * 6);
      const follow = 1 - Math.exp(-dt * 12);
      const looking = attention && attention.until > now ? attention :
        { x: gaze === 'briefly_averted_thinking' ? -0.42 : 0, y: 0 };
      const desired = { ...target, lookX: looking.x, lookY: looking.y, mouth: open };
      for (const name of Object.keys(animated))
        animated[name] += (desired[name] - animated[name]) * follow;
      model.advance(dt);
      const blinkClock = elapsed % 3.8;
      const blink = blinkClock > 3.56 ? Math.min(1, Math.abs(blinkClock - 3.68) / 0.12) : 1;
      if (blink < 1) {
        set('ParamEyeLOpen', blink, 0.95);
        set('ParamEyeROpen', blink, 0.95);
      }
      drive('ParamAngleX', animated.lookX * 15, 0.72);
      drive('ParamAngleY', animated.lookY * 12 - pulse * 7, 0.72);
      set('ParamEyeBallX', animated.lookX * 0.75, 0.78);
      set('ParamEyeBallY', animated.lookY * 0.75, 0.78);
      set('ParamMouthForm', animated.valence, 0.82);
      set('ParamMouthOpenY', animated.mouth);
      drive('ParamBodyAngleZ', animated.curiosity * 3 + pulse * 3, 0.45);
      model.simulate(dt);
      resize();
      const width = surface.width, height = surface.height;
      const pxPerUnit = Math.min(width / core.getCanvasWidth(), height / core.getCanvasHeight()) *
        0.94 * bounded(options.scale ?? 1, 0.5, 2);
      projection.loadIdentity();
      projection.scale(2 * pxPerUnit / width, 2 * pxPerUnit / height);
      gl.viewport(0, 0, width, height);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      renderer.setMvpMatrix(projection);
      renderer.setRenderState(null, [0, 0, width, height]);
      renderer.drawModel(runtimePath + 'shaders/');
      if (options.transparent) display.clearRect(0, 0, width, height);
      else {
        display.fillStyle = options.background || '#1e2230';
        display.fillRect(0, 0, width, height);
      }
      display.drawImage(surface, 0, 0);
      frames++;
      if (measureFrame) {
        const applied = Object.fromEntries(measured.map(name => ['live2d.' + name,
          Math.round(core.getParameterValueByIndex(param[name]) * 1000) / 1000]));
        if (selectedExpression) {
          applied['live2d.expression'] = selectedExpression.name;
          applied['live2d.expressionSha256'] = selectedExpression.hash;
        }
        measureFrame(applied);
      }
    }

    function tick(now) {
      if (disposed) return;
      if (!document.hidden && now - last >= frameInterval - 1.25) draw(now);
      frame = requestAnimationFrame(tick);
    }

    draw(last + frameInterval);
    frame = requestAnimationFrame(tick);
    return {
      kind: 'live2d',
      assetVersionHash: version,
      attribution: attribution || null,
      get diagnostics() { return { frameCount: frames, textureSizes, textureLimit: limit, maskGroups,
        maskBufferCount, maskBufferSize: maskGroups ? renderer.getClippingMaskBufferSize() : null,
        highPrecisionMask: renderer.isUsingHighPrecisionMask(), idleMotion: Boolean(idleBytes), physics: Boolean(physicsBytes) }; },
      async apply(params) {
        const sequence = ++latestApply;
        measureFrame?.({});
        for (const name of Object.keys(target)) {
          if (typeof params.expression?.[name] === 'number') target[name] = bounded(params.expression[name], -1, 1);
        }
        if (params.gaze) gaze = params.gaze;
        const face = typeof params.face === 'string' ? params.face : null;
        if (face && Object.hasOwn(profile.expressions || {}, face)) {
          const url = assetUrl(profile.expressions[face], modelUrl);
          if (!expressionCache.has(url)) {
            expressionCache.set(url, readBytes(url, events.signal)
              .then(async bytes => ({ bytes, hash: await digest(bytes) }))
              .catch(() => { expressionCache.delete(url); return null; }));
          }
          const expression = await expressionCache.get(url);
          if (!disposed && sequence === latestApply && selectedExpression?.name !== face) {
            model.playExpression(expression?.bytes ?? null, face);
            selectedExpression = expression ? { name: face, hash: expression.hash } : null;
          }
        } else if (face && selectedExpression !== null) {
          model.playExpression(null, face);
          selectedExpression = null;
        }
        if (disposed || sequence !== latestApply) return {};
        // Resolve only after a draw. A hidden, disposed, or superseded frame yields no measurement.
        return new Promise(resolve => {
          const timer = setTimeout(() => measureFrame?.({}), 1000);
          measureFrame = applied => {
            clearTimeout(timer);
            measureFrame = null;
            resolve(applied);
          };
        });
      },
      look(x, y) {
        attention = { x: bounded(x, -1, 1), y: -bounded(y, -1, 1), until: performance.now() + 3000 };
      },
      mouth(level, _vowels, lips) { open = bounded(level, 0, 1) * (1 - bounded(lips, 0, 1)); },
      beat(strength) { pulse = Math.max(pulse, bounded(strength, 0, 1)); },
      async selfie() {
        const output = document.createElement('canvas');
        output.width = 720;
        output.height = 1280;
        const ctx = output.getContext('2d');
        const crop = Math.min(canvas.width, Math.round(canvas.height * 9 / 16));
        ctx.fillStyle = options.background || '#1e2230';
        ctx.fillRect(0, 0, output.width, output.height);
        ctx.drawImage(canvas, (canvas.width - crop) / 2, 0, crop, canvas.height, 0, 0, output.width, output.height);
        if (attribution) {
          ctx.fillStyle = '#181b24d9';
          ctx.fillRect(0, output.height - 42, output.width, 42);
          ctx.fillStyle = '#fff';
          ctx.font = '20px sans-serif';
          ctx.fillText(attribution, 16, output.height - 14, output.width - 32);
        }
        return output.toDataURL('image/jpeg', 0.9);
      },
      dispose,
    };
  } catch (error) {
    dispose();
    throw error;
  }
}
