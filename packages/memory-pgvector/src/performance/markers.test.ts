import { describe, expect, it } from 'vitest'

import { authorPerformanceMarkers, parsePerformanceMarkers } from './markers'

describe('performance markers', () => {
  it('parses inline markers from model text', () => {
    const text = 'hi there <|emotion:happy|> let\'s go <|gesture:wave|> bye'
    const markers = parsePerformanceMarkers(text)
    expect(markers).toHaveLength(2)
    expect(markers[0]).toEqual({ key: 'emotion', value: 'happy' })
    expect(markers[1]).toEqual({ key: 'gesture', value: 'wave' })
  })

  it('returns an empty array when there are no markers', () => {
    expect(parsePerformanceMarkers('just plain speech')).toEqual([])
  })

  it('serialises a partial state into authorable markers', () => {
    const out = authorPerformanceMarkers({ emotion: 'happy', gaze: 'user' })
    expect(out).toBe('<|emotion:happy|> <|gaze:user|>')
  })

  it('skips empty values when authoring', () => {
    expect(authorPerformanceMarkers({ emotion: 'calm', gesture: '' })).toBe('<|emotion:calm|>')
  })
})
