/**
 * Animation State Machine — MMO-grade avatar animation control
 *
 * Adapted from nirholas/three.ws (MIT License)
 * Integrated into AIJADE for VRM/GLB avatar animation management.
 *
 * States: idle → talk → walk → react → emote → listen → think
 * Gestures: wave, dance, sit, point, cheer, agree, disagree, talking, nod, shrug, jog, celebrate
 *
 * This module is pure: no Three.js, no DOM, no async.
 * Playback is driven through onTransition / onGesture callbacks.
 */

// ── Types ───────────────────────────────────────────────────────────────────

export interface StateDef {
  clip: string
  loop: boolean
  crossfade: number
  oneShot: boolean
  returnTo?: string | null
}

export interface GestureDef {
  clip: string
  label: string
  loop: boolean
  layer: 'upper' | 'full'
  crossfade: number
  exitOnMove?: boolean
}

export interface AnimationGraph {
  states?: Record<string, Partial<StateDef>>
  transitions?: Record<string, string>
  initial?: string
}

export interface TransitionPayload {
  state: string
  def: StateDef
  clip: string
  crossfade: number
}

export interface GesturePayload {
  gesture: string | null
  def: (GestureDef & { name: string }) | null
  active: boolean
  prev: string | null
}

// ── Default animation states ───────────────────────────────────────────────

const DEFAULT_STATES: Record<string, StateDef> = Object.freeze({
  idle: { clip: 'idle', loop: true, crossfade: 0.5, oneShot: false },
  talk: { clip: 'idle', loop: true, crossfade: 0.35, oneShot: false },
  walk: { clip: 'walk', loop: true, crossfade: 0.3, oneShot: false },
  react: { clip: 'reaction', loop: false, crossfade: 0.25, oneShot: true, returnTo: 'idle' },
  emote: { clip: 'wave', loop: false, crossfade: 0.25, oneShot: true, returnTo: 'idle' },
  listen: { clip: 'av-listening-music', loop: true, crossfade: 0.4, oneShot: false },
  think: { clip: 'av-waiting', loop: true, crossfade: 0.4, oneShot: false },
})

// ── Default transition table ────────────────────────────────────────────────

const DEFAULT_TRANSITIONS: Record<string, string> = Object.freeze({
  'speak': 'talk',
  'speak-end': 'idle',
  'walk': 'walk',
  'walk-end': 'idle',
  'react': 'react',
  'react-end': 'idle',
  'emote': 'emote',
  'emote-end': 'idle',
  'listen': 'listen',
  'listen-end': 'idle',
  'think': 'think',
  'think-end': 'idle',
})

const STATE_NAMES = Object.freeze(Object.keys(DEFAULT_STATES))

// ── Gesture library (upper-body overlays + full-body takeovers) ────────────

const GESTURES: Record<string, GestureDef> = Object.freeze({
  wave: { clip: 'wave', label: 'Wave', loop: false, layer: 'upper', crossfade: 0.25 },
  dance: { clip: 'dance', label: 'Dance', loop: true, layer: 'full', crossfade: 0.3 },
  sit: { clip: 'sitidle', label: 'Sit', loop: true, layer: 'full', crossfade: 0.35, exitOnMove: true },
  point: { clip: 'reaction', label: 'Point', loop: false, layer: 'upper', crossfade: 0.25 },
  cheer: { clip: 'av-cheering', label: 'Cheer', loop: false, layer: 'upper', crossfade: 0.25 },
  agree: { clip: 'xbot-agree', label: 'Agree', loop: false, layer: 'upper', crossfade: 0.2 },
  disagree: { clip: 'xbot-head-shake', label: 'Disagree', loop: false, layer: 'upper', crossfade: 0.2 },
  talking: { clip: 'av-vtubing', label: 'Talking', loop: true, layer: 'upper', crossfade: 0.3 },
  nod: { clip: 'xbot-agree', label: 'Nod', loop: false, layer: 'upper', crossfade: 0.2 },
  shrug: { clip: 'defeated', label: 'Shrug', loop: false, layer: 'full', crossfade: 0.3 },
  jog: { clip: 'xbot-run', label: 'Jog', loop: true, layer: 'full', crossfade: 0.3 },
  celebrate: { clip: 'av-celebrating', label: 'Celebrate', loop: false, layer: 'full', crossfade: 0.3 },
})

const GESTURE_NAMES = Object.freeze(Object.keys(GESTURES))

// ── State Machine ───────────────────────────────────────────────────────────

export class AnimationStateMachine {
  states: Record<string, StateDef>
  transitions: Record<string, string>
  initial: string
  current: string
  onTransition: ((p: TransitionPayload) => void) | null = null
  onGesture: ((p: GesturePayload) => void) | null = null
  gesture: string | null = null
  private _returnStack: string[] = []

  constructor(graph: AnimationGraph = {}) {
    this.states = mergeStates(graph.states)
    this.transitions = mergeTransitions(graph.transitions)
    this.initial = graph.initial && this.states[graph.initial] ? graph.initial : 'idle'
    this.current = this.initial
  }

  getCurrent(): string {
    return this.current
  }

  getCurrentClip(): string | null {
    return this.states[this.current]?.clip ?? null
  }

  getGesture(): string | null {
    return this.gesture
  }

  getGestureNames(): readonly string[] {
    return GESTURE_NAMES
  }

  getStateNames(): readonly string[] {
    return STATE_NAMES
  }

  getGestureDef(name: string): (GestureDef & { name: string }) | null {
    const def = GESTURES[name]
    return def ? { name, ...def } : null
  }

  fire(event: string): string | null {
    if (!event || typeof event !== 'string')
      return null
    const target = this.transitions[event] || (this.states[event] ? event : null)
    if (!target)
      return null

    const targetDef = this.states[target]
    if (!targetDef || !targetDef.clip)
      return null

    const fromDef = this.states[this.current]
    if (targetDef.oneShot && fromDef && !fromDef.oneShot)
      this._returnStack.push(this.current)

    const isEndEvent = event.endsWith('-end')
    let resolvedTarget = target
    if (isEndEvent && this._returnStack.length > 0) {
      const popped = this._returnStack.pop()
      if (popped && this.states[popped])
        resolvedTarget = popped
    }

    if (resolvedTarget === this.current)
      return this.current

    const def = this.states[resolvedTarget]
    this.current = resolvedTarget
    if (this.onTransition) {
      this.onTransition({
        state: resolvedTarget,
        def,
        clip: def.clip,
        crossfade: def.crossfade,
      })
    }
    return resolvedTarget
  }

  playGesture(name: string): string | null {
    const def = GESTURES[name]
    if (!def)
      return null
    if (this.gesture === name)
      return name
    const prev = this.gesture
    this.gesture = name
    if (this.onGesture) {
      this.onGesture({
        gesture: name,
        def: { name, ...def },
        active: true,
        prev,
      })
    }
    return name
  }

  endGesture(): string | null {
    if (!this.gesture)
      return null
    const prev = this.gesture
    this.gesture = null
    if (this.onGesture) {
      this.onGesture({
        gesture: null,
        def: null,
        active: false,
        prev,
      })
    }
    return prev
  }

  reset(): void {
    this._returnStack.length = 0
    this.current = this.initial
    this.endGesture()
  }
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function mergeStates(overrides?: Record<string, Partial<StateDef>>): Record<string, StateDef> {
  const out: Record<string, StateDef> = {}
  for (const name of STATE_NAMES) {
    const def: StateDef = { ...DEFAULT_STATES[name] }
    const o = overrides?.[name]
    if (o && typeof o === 'object') {
      if (typeof o.clip === 'string' && o.clip.length > 0)
        def.clip = o.clip
      if (typeof o.loop === 'boolean')
        def.loop = o.loop
      if (typeof o.crossfade === 'number' && Number.isFinite(o.crossfade))
        def.crossfade = Math.max(0, Math.min(5, o.crossfade))
      if (typeof o.oneShot === 'boolean')
        def.oneShot = o.oneShot
      if (typeof o.returnTo === 'string' || o.returnTo === null)
        def.returnTo = o.returnTo
    }
    out[name] = def
  }
  if (overrides && typeof overrides === 'object') {
    for (const [name, o] of Object.entries(overrides)) {
      if (out[name] || !o || typeof o !== 'object' || typeof o.clip !== 'string' || !o.clip)
        continue
      out[name] = {
        clip: o.clip,
        loop: o.loop ?? false,
        crossfade: typeof o.crossfade === 'number' ? Math.max(0, Math.min(5, o.crossfade)) : 0.25,
        oneShot: o.oneShot ?? true,
        returnTo: typeof o.returnTo === 'string' ? o.returnTo : 'idle',
      }
    }
  }
  return out
}

function mergeTransitions(overrides?: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = { ...DEFAULT_TRANSITIONS }
  if (overrides && typeof overrides === 'object') {
    for (const [event, target] of Object.entries(overrides)) {
      if (typeof event === 'string' && typeof target === 'string')
        out[event] = target
    }
  }
  return out
}
