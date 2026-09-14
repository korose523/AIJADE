import type { WebSocketEvent } from '@proj-aijade/server-shared/types'

import { stringify } from 'superjson'
import { describe, expect, it } from 'vitest'

import {
  AijadeWebSocketEventFormatError,
  heartbeatFrameFrom,
  parseEvent,
} from '.'

describe('aijade websocket protocol codec', () => {
  it('parses superjson encoded events', () => {
    const event: WebSocketEvent = {
      type: 'module:authenticate',
      data: { token: 'secret' },
      metadata: {
        source: {
          kind: 'plugin',
          id: 'test-plugin-1',
          plugin: { id: 'test-plugin' },
        },
        event: { id: 'event-1' },
      },
    }

    expect(parseEvent(stringify(event))).toEqual(event)
  })

  it('falls back to plain JSON events', () => {
    const event: WebSocketEvent = {
      type: 'module:authenticate',
      data: { token: 'secret' },
      metadata: {
        source: {
          kind: 'plugin',
          id: 'test-plugin-1',
          plugin: { id: 'test-plugin' },
        },
        event: { id: 'event-1' },
      },
    }

    expect(parseEvent(JSON.stringify(event))).toEqual(event)
  })

  it('rejects payloads without event type', () => {
    expect(() => parseEvent('null'))
      .toThrow(AijadeWebSocketEventFormatError)
    expect(() => parseEvent(JSON.stringify({ data: {} })))
      .toThrow(AijadeWebSocketEventFormatError)
  })

  it('rejects payloads with non-string event type', () => {
    expect(() => parseEvent(JSON.stringify({ type: 0, data: {} })))
      .toThrow(AijadeWebSocketEventFormatError)
  })

  it('rejects payloads without object event data', () => {
    expect(() => parseEvent(JSON.stringify({ type: 'module:authenticate' })))
      .toThrow(AijadeWebSocketEventFormatError)
    expect(() => parseEvent(JSON.stringify({ type: 'module:authenticate', data: null })))
      .toThrow(AijadeWebSocketEventFormatError)
    expect(() => parseEvent(JSON.stringify({ type: 'module:authenticate', data: 'secret' })))
      .toThrow(AijadeWebSocketEventFormatError)
  })

  it('rejects payloads with array event data', () => {
    expect(() => parseEvent(JSON.stringify({ type: 'module:authenticate', data: [] })))
      .toThrow(AijadeWebSocketEventFormatError)
  })

  it('classifies raw ping and pong control frames', () => {
    expect(heartbeatFrameFrom('ping')).toBe('ping')
    expect(heartbeatFrameFrom('pong')).toBe('pong')
    expect(heartbeatFrameFrom('{"type":"ping"}')).toBeUndefined()
  })
})
