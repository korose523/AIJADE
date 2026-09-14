// REORG Phase 2 — chunker dedup (compat shim).
//
// The legacy stage-ui chunker implementation (originally ~265 lines of
// Intl.Segmenter-based logic in this file) was a duplicate of
// `@proj-aijade/pipelines-audio`'s canonical `processors/tts-chunker`. That logic
// now lives solely in pipelines-audio. This file is a thin COMPAT SHIM that
// re-exports the canonical implementation under the legacy names so existing
// call sites (and the `./utils/tts` subpath export) keep working during the
// migration. See services/speech/REORG_PLAN.md (Phase 2).

import type {
  TtsChunkItem,
  TtsInputChunk,
  TtsInputChunkOptions,
} from '@proj-aijade/pipelines-audio'
import type { ReaderLike } from 'clustr'

import {
  chunkEmitter as _chunkEmitter,
  chunkTtsInput,
  TTS_FLUSH_INSTRUCTION,
  TTS_SPECIAL_TOKEN,
} from '@proj-aijade/pipelines-audio'

export { chunkTtsInput as chunkTTSInput, TTS_FLUSH_INSTRUCTION, TTS_SPECIAL_TOKEN }

export type {
  TtsChunkItem as TTSChunkItem,
  TtsInputChunk as TTSInputChunk,
  TtsInputChunkOptions as TTSInputChunkOptions,
}

/**
 * Legacy 3-arg signature preserved for backward compatibility:
 * `chunkEmitter(reader, pendingSpecials, handler)`.
 * The canonical pipelines-audio API added an `options` parameter; we pass
 * `undefined` for it so any old call sites keep working unchanged.
 */
export function chunkEmitter(
  reader: ReaderLike,
  pendingSpecials: string[],
  handler: (ttsSegment: TtsChunkItem) => Promise<void> | void,
): Promise<void> {
  return _chunkEmitter(reader, pendingSpecials, undefined, handler)
}
