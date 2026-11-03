// Where her phone's front camera is when she takes a selfie (ADR-003, migration batch 2): AIJADE's port of MOSAIC's
// host-dotnet/Mosaic.Scene.Core/SelfieShot.cs (r596, MIT), checked case by case against vectors made by MOSAIC's own class
// (configs/companion/selfie-vectors.json). At arm's length in front of her face, a little above it and to her right (the
// hand that holds it), looking at her face; a portrait picture with a phone's wide front lens. Her face is between her
// eyes and she faces where they look; without eyes, the head bone and the way her body faces. When she lies or reclines
// more than 35°, the frame is her head's own (up from neck to head), so that the picture is upright for her face.
//
// MOSAIC's world: metres, y up, right-handed. The stage converts its positions in and out (see mmd-backend.src.js).

export const ARM = .48, ABOVE = .12, ASIDE = .10, FOV_DEGREES = 68, FACE_DROP = .02, UPRIGHT_DEGREES = 35;
export const WIDTH = 720, HEIGHT = 1280;

const vec = (x, y, z) => ({ x, y, z });
const add = (a, b) => vec(a.x + b.x, a.y + b.y, a.z + b.z);
const sub = (a, b) => vec(a.x - b.x, a.y - b.y, a.z - b.z);
const scale = (a, k) => vec(a.x * k, a.y * k, a.z * k);
const dot = (a, b) => a.x * b.x + a.y * b.y + a.z * b.z;
const cross = (a, b) => vec(a.y * b.z - a.z * b.y, a.z * b.x - a.x * b.z, a.x * b.y - a.y * b.x);
const length = (a) => Math.sqrt(dot(a, a));
const normalize = (a) => scale(a, 1 / length(a));
const UP = vec(0, 1, 0);

function horizontal(v) {
  const h = vec(v.x, 0, v.z);
  if (dot(h, h) < 1e-8) throw new Error('A horizontal facing is needed');
  return normalize(h);
}

/** {camera, look, facing, up} for her head, her eyes (either may be null), the way her body faces and her neck (or null). */
export function frame(head, leftEye, rightEye, bodyFacing, neck = null) {
  let up = UP, upright = true, face, facing;
  const eyes = leftEye && rightEye && length(sub(leftEye, rightEye)) > 1e-3;
  if (eyes && neck && length(sub(head, neck)) > 1e-3) {
    const along = normalize(sub(head, neck));
    if (dot(along, UP) < Math.cos(UPRIGHT_DEGREES * Math.PI / 180)) { up = along; upright = false; } // lying or reclined: her head's own up
  }
  if (eyes) {
    face = scale(add(leftEye, rightEye), 0.5);
    let f = cross(sub(leftEye, rightEye), up);
    if (upright) f = vec(f.x, 0, f.z); // upright: level
    facing = dot(f, f) > 1e-8 ? normalize(f) : horizontal(bodyFacing);
  } else {
    face = add(head, scale(up, .05));
    facing = horizontal(bodyFacing);
  }
  const right = normalize(cross(facing, up));
  return { camera: add(add(add(face, scale(facing, ARM)), scale(up, ABOVE)), scale(right, ASIDE)), look: sub(face, scale(up, FACE_DROP)), facing, up };
}
