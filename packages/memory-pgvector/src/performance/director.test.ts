import { describe, expect, it, vi } from 'vitest'

import { createPerformanceDirector, PerformanceDirector } from './director'

describe('performanceDirector', () => {
  it('starts in the listen state', () => {
    const d = new PerformanceDirector()
    expect(d.snapshot().state).toBe('listen')
  })

  it('flips to speak on the first streamed token (closes the silence gap)', () => {
    const d = new PerformanceDirector()
    d.enterListen()
    d.onToken('Hello')
    expect(d.snapshot().state).toBe('speak')
  })

  it('moves to silence once the turn ends', () => {
    const d = new PerformanceDirector()
    d.onToken('hi')
    d.onTurnEnd()
    expect(d.snapshot().state).toBe('silence')
  })

  it('guesses emotion from the lexicon but only until an explicit marker locks it', () => {
    const d = new PerformanceDirector()
    d.onToken('hahaha that is great!')
    expect(d.snapshot().emotion).toBe('happy')

    d.applyMarker({ key: 'emotion', value: 'sad' })
    expect(d.snapshot().emotion).toBe('sad')

    // locked: lexicon no longer overrides
    d.onToken('this is awesome and I love it')
    expect(d.snapshot().emotion).toBe('sad')
  })

  it('captures structured cues from markers', () => {
    const d = new PerformanceDirector()
    d.applyMarker({ key: 'gesture', value: 'wave' })
    d.applyMarker({ key: 'gaze', value: 'user' })
    d.applyMarker({ key: 'music', value: 'calm' })
    const s = d.snapshot()
    expect(s.gesture).toBe('wave')
    expect(s.gaze).toBe('user')
    expect(s.music).toBe('calm')
  })

  it('accumulates the relationship delta', () => {
    const d = new PerformanceDirector()
    d.applyMarker({ key: 'relation', value: '+1' })
    d.applyMarker({ key: 'relation', value: '+2' })
    d.applyMarker({ key: 'relation', value: '-1' })
    expect(d.snapshot().relationDelta).toBe(2)
  })

  it('respects an explicit state marker', () => {
    const d = new PerformanceDirector()
    d.onToken('hi')
    d.applyMarker({ key: 'state', value: 'listen' })
    expect(d.snapshot().state).toBe('listen')
  })

  it('emits the state on every change via onState', () => {
    const onState = vi.fn()
    const d = createPerformanceDirector({ onState })
    d.onToken('hello')
    d.applyMarker({ key: 'emotion', value: 'happy' })
    d.onTurnEnd()
    expect(onState).toHaveBeenCalledTimes(3)
    expect(onState).toHaveBeenLastCalledWith(expect.objectContaining({ state: 'silence' }))
  })

  describe('lPM-grounded deep optimization', () => {
    it('dual-stream feedUserAudio clamps level and updates listenArousal via EMA', () => {
      const d = new PerformanceDirector()
      // level > 1 is clamped to 1 → arousal = 0.3 after one frame
      d.feedUserAudio(2)
      expect(d.listenArousal).toBeCloseTo(0.3, 5)
      // second frame: 0.7*0.3 + 0.3*1 ≈ 0.51
      d.feedUserAudio(1)
      expect(d.listenArousal).toBeCloseTo(0.51, 5)
    })

    it('listening reactions fire on tick while in listen (LPM: listening is half of conversation)', () => {
      vi.spyOn(Math, 'random').mockReturnValue(0) // always pick LISTEN_REACTIONS[0] = nod
      const d = new PerformanceDirector()
      d.enterListen()
      // far-future "now" guarantees the scheduled reaction has elapsed
      d.tick(1e9)
      expect(d.snapshot().gesture).toBe('nod')
      vi.restoreAllMocks()
    })

    it('feedUserAudio emotion hint drives an empathic lean during listening', () => {
      vi.spyOn(Math, 'random').mockReturnValue(0)
      const d = new PerformanceDirector()
      d.feedUserAudio(1, 'worried') // user sounds worried → avatar mirrors it
      d.enterListen()
      d.tick(1e9)
      expect(d.snapshot().emotion).toBe('worried')
      vi.restoreAllMocks()
    })

    it('high-intimacy persona yields a loving lean while listening (relationship-aware)', () => {
      vi.spyOn(Math, 'random').mockReturnValue(0)
      const d = new PerformanceDirector()
      d.setPersona({ intimacy: { warmth: 1, trust: 1, familiarity: 1 } })
      d.enterListen()
      d.tick(1e9)
      expect(d.snapshot().emotion).toBe('loving')
      vi.restoreAllMocks()
    })

    it('anti-drift relaxes a locked-in mood back to neutral during silence (LPM long-horizon stability)', () => {
      const d = new PerformanceDirector()
      d.onToken('this makes me so angry') // guesses angry (unlocked)
      expect(d.snapshot().emotion).toBe('angry')
      d.onTurnEnd() // → silence
      d.tick(1000) // _silenceRelaxAt starts at 0 → relaxes immediately
      expect(d.snapshot().emotion).toBe('worried')
      d.tick(5000)
      expect(d.snapshot().emotion).toBe('calm')
      d.tick(9000)
      expect(d.snapshot().emotion).toBe('neutral')
    })

    it('relationDelta is bounded so a long session cannot drift unboundedly', () => {
      const d = new PerformanceDirector()
      d.applyMarker({ key: 'relation', value: '+100' })
      expect(d.snapshot().relationDelta).toBe(10)
      d.applyMarker({ key: 'relation', value: '-100' })
      expect(d.snapshot().relationDelta).toBe(-10)
    })

    it('accepts the enriched LPM-aligned emotion taxonomy', () => {
      const d = new PerformanceDirector()
      d.applyMarker({ key: 'emotion', value: 'curious' })
      expect(d.snapshot().emotion).toBe('curious')
      d.applyMarker({ key: 'emotion', value: 'grateful' })
      expect(d.snapshot().emotion).toBe('grateful')
      // alias resolution
      d.applyMarker({ key: 'emotion', value: 'bashful' })
      expect(d.snapshot().emotion).toBe('embarrassed')
    })
  })
})
