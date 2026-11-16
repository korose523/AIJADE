// Frame capture for AIJADE's vision module: the user's shared screen or camera, or an image they pick. Frames are scaled
// down on the device and returned as JPEG data URLs; nothing is captured until start() is called by a user action.
let state = null;

function frameToDataUrl(source, width, height, maxWidth) {
  const scale = Math.min(1, maxWidth / width);
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(width * scale));
  canvas.height = Math.max(1, Math.round(height * scale));
  canvas.getContext('2d').drawImage(source, 0, 0, canvas.width, canvas.height);
  return canvas.toDataURL('image/jpeg', 0.8);
}

/** Start sharing ('screen' or 'camera'). Resolves to null on success or an error string; never throws. */
export async function start(dotnet, kind) {
  stop();
  if (!navigator.mediaDevices) return 'this browser cannot capture video';
  let stream;
  try {
    stream = kind === 'screen'
      ? await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 1 }, audio: false })
      : await navigator.mediaDevices.getUserMedia({ video: { width: { ideal: 1280 } }, audio: false });
  } catch (e) {
    return e?.name === 'NotAllowedError' ? 'permission denied' : `capture unavailable (${e?.name ?? e})`;
  }
  const video = Object.assign(document.createElement('video'), { muted: true, playsInline: true });
  video.srcObject = stream;
  await video.play().catch(() => {});
  // Ending the share from the browser's own controls stops AIJADE too.
  for (const track of stream.getVideoTracks()) track.addEventListener('ended', () => { if (state?.stream === stream) { stop(); dotnet.invokeMethodAsync('OnEnded'); } });
  state = { stream, video };
  return null;
}

/** The current frame as a JPEG data URL, or null when not sharing / no frame yet. */
export function grab(maxWidth) {
  const v = state?.video;
  if (!v || !v.videoWidth) return null;
  return frameToDataUrl(v, v.videoWidth, v.videoHeight, maxWidth);
}

export function stop() {
  state?.stream.getTracks().forEach(t => t.stop());
  state = null;
}

/** An image file's bytes, scaled down, as a JPEG data URL (null when it is not a decodable image). */
export async function downscale(bytes, mime, maxWidth) {
  try {
    const bitmap = await createImageBitmap(new Blob([bytes], { type: mime }));
    const url = frameToDataUrl(bitmap, bitmap.width, bitmap.height, maxWidth);
    bitmap.close();
    return url;
  } catch {
    return null;
  }
}
