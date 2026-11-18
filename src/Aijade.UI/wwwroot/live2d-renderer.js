const packagePath = '/_aijade/live2d/';
const runtimePath = packagePath + 'runtime/';
let runtime;

function isLoopback() {
  return /^https?:$/.test(location.protocol) &&
    /^(localhost|127\.\d{1,3}\.\d{1,3}\.\d{1,3}|\[::1\])$/i.test(location.hostname);
}

export function isLive2DModel(url) {
  if (!url) return false;
  try { return new URL(url, location.href).pathname.toLowerCase().endsWith('.model3.json'); }
  catch { return false; }
}

function localModelUrl(url, base = location.href) {
  const model = new URL(url, base);
  if (!isLoopback() || model.origin !== location.origin ||
      !model.pathname.startsWith(packagePath + 'model/') || !isLive2DModel(model.href))
    throw new Error('Live2D model must be in the installed package on this local server.');
  return model.href;
}

export async function installedLive2DModel(signal) {
  if (!isLoopback()) return null;
  const response = await fetch(packagePath + 'active.json', { signal, cache: 'no-store' });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error('Unable to read the installed Live2D package.');
  const preset = await response.json();
  if (typeof preset.modelUrl !== 'string') throw new Error('The Live2D package has no model URL.');
  return localModelUrl(preset.modelUrl, new URL(packagePath + 'active.json', location.href));
}

function loadScript(url) {
  const script = document.createElement('script');
  script.src = url;
  return new Promise((resolve, reject) => {
    script.onload = resolve;
    script.onerror = () => {
      script.remove();
      reject(new Error('Install the Live2D Cubism Core in the local runtime directory.'));
    };
    document.head.appendChild(script);
  });
}

async function initialize() {
  if (!globalThis.Live2DCubismCore) await loadScript(runtimePath + 'live2dcubismcore.min.js');
  const deadline = performance.now() + 5000;
  while (true) {
    try {
      if (globalThis.Live2DCubismCore?.Version?.csmGetVersion()) break;
    } catch {
      // The core's WebAssembly runtime may finish initialization after the script's load event.
    }
    if (performance.now() >= deadline) throw new Error('The installed Cubism Core did not initialize.');
    await new Promise(resolve => setTimeout(resolve, 30));
  }
  return import(runtimePath + 'live2d-backend.js');
}

export async function mountLive2D(canvas, options, signal) {
  const modelUrl = localModelUrl(options.modelUrl);
  const loading = document.createElement('div');
  loading.className = 'stage-loading';
  loading.setAttribute('role', 'progressbar');
  loading.setAttribute('aria-label', 'Live2D');
  const ring = document.createElement('span');
  ring.className = 'stage-loading-ring';
  loading.appendChild(ring);
  const stage = canvas.parentElement;
  (stage?.querySelector('.stage-overlay') || stage)?.appendChild(loading);
  try {
    runtime ??= initialize().catch(error => { runtime = undefined; throw error; });
    const backend = await runtime;
    signal.throwIfAborted();
    return await backend.createLive2D(canvas, { ...options, modelUrl }, runtimePath, signal);
  } finally {
    loading.remove();
  }
}
