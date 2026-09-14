import type {
  PlaybackEndEvent,
  PlaybackInterruptEvent,
  PlaybackRejectEvent,
  PlaybackStartEvent,
  TextSegment,
  TtsRequest,
  TtsResult,
} from './types'

import { defineEventa } from '@moeru/eventa'

export const speechSegmentEvent = defineEventa<TextSegment>('proj-aijade:pipelines:output:speech:segment')
export const speechSpecialEvent = defineEventa<TextSegment>('proj-aijade:pipelines:output:speech:special')

export const speechTtsRequestEvent = defineEventa<TtsRequest>('proj-aijade:pipelines:output:speech:tts-request')
export const speechTtsResultEvent = defineEventa<TtsResult<any>>('proj-aijade:pipelines:output:speech:tts-result')

export const speechPlaybackStartEvent = defineEventa<PlaybackStartEvent<any>>('proj-aijade:pipelines:output:speech:playback-start')
export const speechPlaybackEndEvent = defineEventa<PlaybackEndEvent<any>>('proj-aijade:pipelines:output:speech:playback-end')
export const speechPlaybackInterruptEvent = defineEventa<PlaybackInterruptEvent<any>>('proj-aijade:pipelines:output:speech:playback-interrupt')
export const speechPlaybackRejectEvent = defineEventa<PlaybackRejectEvent<any>>('proj-aijade:pipelines:output:speech:playback-reject')

export const speechIntentStartEvent = defineEventa<string>('proj-aijade:pipelines:output:speech:intent-start')
export const speechIntentEndEvent = defineEventa<string>('proj-aijade:pipelines:output:speech:intent-end')
export const speechIntentCancelEvent = defineEventa<{ intentId: string, reason?: string }>('proj-aijade:pipelines:output:speech:intent-cancel')

export const speechTurnStartEvent = defineEventa<string>('proj-aijade:pipelines:output:speech:turn-start')
export const speechTurnEndEvent = defineEventa<string>('proj-aijade:pipelines:output:speech:turn-end')
export const speechTurnCancelEvent = defineEventa<{ turnId: string, reason?: string }>('proj-aijade:pipelines:output:speech:turn-cancel')

export const speechPipelineEventMap = {
  onSegment: speechSegmentEvent,
  onSpecial: speechSpecialEvent,
  onTtsRequest: speechTtsRequestEvent,
  onTtsResult: speechTtsResultEvent,
  onPlaybackStart: speechPlaybackStartEvent,
  onPlaybackEnd: speechPlaybackEndEvent,
  onPlaybackInterrupt: speechPlaybackInterruptEvent,
  onPlaybackReject: speechPlaybackRejectEvent,
  onIntentStart: speechIntentStartEvent,
  onIntentEnd: speechIntentEndEvent,
  onIntentCancel: speechIntentCancelEvent,
  onTurnStart: speechTurnStartEvent,
  onTurnEnd: speechTurnEndEvent,
  onTurnCancel: speechTurnCancelEvent,
} as const

export type SpeechPipelineEventName = keyof typeof speechPipelineEventMap
