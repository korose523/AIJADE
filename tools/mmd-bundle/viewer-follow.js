// The camera as a viewer standing in the room (ADR-003, migration batch 2): AIJADE's port of MOSAIC's
// host-dotnet/Mosaic.Scene.Core/ViewerFollow.cs (r582, MIT), checked case by case against vectors made by MOSAIC's own
// class (configs/companion/viewer-follow-vectors.json). It keeps the framed view direction and height and follows her
// sideways so that she stays centred, but lets her come closer or move away inside a depth band (Near…Far, fractions of
// the framed distance) and moves along the view only when she leaves it. A dead zone ignores the few centimetres her root
// sways while she stands; while she walks the camera follows at once and looks a little ahead of her; walking away from
// the camera for a while turns the view toward her side, and it stays turned when she stops.
//
// Vectors are {x, y, z} with y up. MOSAIC's world is in metres; `metre` says how many world units make one (an MMD scene,
// 8 cm to the unit, uses 12.5), so the dead zone, the walking speed and the lead keep their sizes.

export const NEAR_FRACTION = .55, APPROACH_FRACTION = .65, FAR_FRACTION = 1.7;
export const DEAD_ZONE = .12, MOVING_SPEED = .25, LOOK_AHEAD = .35, MAX_LEAD = .6, VELOCITY_TAU = .4;
export const AWAY_COSINE = .5, AWAY_AFTER_S = 1.2, TURN_DEGREES_PER_S = 15, SIDE_DEGREES = 75;

const vec = (x, y, z) => ({ x, y, z });
const flat = (p) => vec(p.x, 0, p.z);
const add = (a, b) => vec(a.x + b.x, a.y + b.y, a.z + b.z);
const sub = (a, b) => vec(a.x - b.x, a.y - b.y, a.z - b.z);
const scale = (a, k) => vec(a.x * k, a.y * k, a.z * k);
const dot = (a, b) => a.x * b.x + a.y * b.y + a.z * b.z;
const length = (a) => Math.sqrt(dot(a, a));
const normalize = (a) => scale(a, 1 / length(a));
const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));

export class ViewerFollow {
  /**
   * `camera` and `look` as framed, `root` her root at that moment; `clock` gives seconds (tests), by default the page's
   * clock, as the viewer is in real time.
   */
  constructor(camera, look, root, { clock = () => performance.now() / 1000, metre = 1 } = {}) {
    let f = vec(look.x - camera.x, 0, look.z - camera.z);
    if (dot(f, f) < 1e-10) f = vec(root.x - camera.x, 0, root.z - camera.z);
    if (dot(f, f) < 1e-10) throw new Error('Camera must look horizontally somewhere');
    this.forward = normalize(f);
    this.side = vec(-this.forward.z, 0, this.forward.x);
    const r = vec(root.x - camera.x, 0, root.z - camera.z);
    this.framed = dot(r, this.forward);
    this.lateral = dot(r, this.side);
    this.height = camera.y;
    if (!(this.framed > 0)) throw new Error('Character must be in front of the camera');
    this.lookOffset = sub(look, flat(root));
    this.clock = clock;
    this.metre = metre;
    this.lastTime = null;
    this.lastRoot = vec(0, 0, 0);
    this.velocity = vec(0, 0, 0);
    this.held = null;
    this.awayFor = 0;
  }

  get near() { return NEAR_FRACTION * this.framed; }
  get approach() { return APPROACH_FRACTION * this.framed; }
  get far() { return FAR_FRACTION * this.framed; }

  /** Where the camera should be and look for her root at `root`, from the camera now at `camera`. */
  desired(camera, root) {
    const here = flat(root), now = this.clock(), m = this.metre;
    if (this.lastTime !== null && now > this.lastTime) {
      const dt = now - this.lastTime, k = 1 - Math.exp(-dt / VELOCITY_TAU);
      this.velocity = add(this.velocity, scale(sub(scale(sub(here, this.lastRoot), 1 / dt), this.velocity), k));
      const away = length(this.velocity) > MOVING_SPEED * m && dot(normalize(this.velocity), this.forward) > AWAY_COSINE;
      this.awayFor = away ? this.awayFor + dt : 0;
      if (this.awayFor > AWAY_AFTER_S) this.turn(dt);
    }
    this.lastTime = now;
    this.lastRoot = here;
    const moving = length(this.velocity) > MOVING_SPEED * m;
    if (moving || this.held === null || length(sub(this.held, here)) > DEAD_ZONE * m) this.held = here; // idle sway inside the dead zone: hold
    const anchor = this.held;
    const depth = clamp(dot(sub(anchor, vec(camera.x, 0, camera.z)), this.forward), this.near, this.far);
    const at = sub(sub(anchor, scale(this.forward, depth)), scale(this.side, this.lateral));
    let lead = moving ? scale(this.velocity, LOOK_AHEAD) : vec(0, 0, 0);
    if (length(lead) > MAX_LEAD * m) lead = scale(normalize(lead), MAX_LEAD * m);
    return { camera: vec(at.x, this.height, at.z), look: add(add(anchor, this.lookOffset), lead) };
  }

  /** Turn the view direction toward SIDE_DEGREES from her way, on the nearer side, at most TURN_DEGREES_PER_S. */
  turn(dt) {
    const way = normalize(vec(this.velocity.x, 0, this.velocity.z));
    const a = SIDE_DEGREES * Math.PI / 180;
    const rotate = (angle) => vec(way.x * Math.cos(angle) - way.z * Math.sin(angle), 0, way.x * Math.sin(angle) + way.z * Math.cos(angle));
    const left = rotate(a), right = rotate(-a);
    const goal = dot(left, this.forward) >= dot(right, this.forward) ? left : right;
    const between = Math.acos(clamp(dot(this.forward, goal), -1, 1)), step = Math.min(between, TURN_DEGREES_PER_S * Math.PI / 180 * dt);
    if (between < 1e-4) return;
    const sign = Math.sign(this.forward.x * goal.z - this.forward.z * goal.x);
    const c = Math.cos(sign * step), s = Math.sin(sign * step);
    this.forward = normalize(vec(this.forward.x * c - this.forward.z * s, 0, this.forward.x * s + this.forward.z * c));
    this.side = vec(-this.forward.z, 0, this.forward.x);
  }
}
