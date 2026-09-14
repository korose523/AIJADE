/**
 * Bridge from the live persona state to `@proj-aijade/research-telemetry`'s
 * snapshot shape.
 *
 * `research-telemetry` deliberately clones the persona types rather than import
 * them, so it can be loaded from any runtime without dragging in the whole agent
 * stack. That means the *values* must be projected here, where the derivation
 * maths (PAD / Big-Five / mood) already lives. The result is structurally
 * identical to `PersonaSnapshot`, so it drops straight into a {@link TurnRecord}.
 */

import type { PersonaSnapshot } from '@proj-aijade/research-telemetry'

import type { PersonaState } from './persona'

import { toBigFive, toMoodProfile, toPAD } from './persona'

/** Project a live persona into a telemetry-compatible snapshot. */
export function toPersonaSnapshot(state: PersonaState): PersonaSnapshot {
  const pad = toPAD(state)
  const bigFive = toBigFive(state.vector)
  const mood = toMoodProfile(state)
  return {
    vector: { ...state.vector },
    endocrine: { ...state.endocrine },
    pad,
    bigFive,
    intimacy: { ...state.intimacy },
    moodLabel: mood.label,
    moodEmoji: mood.emoji,
  }
}
