import { mulberry32 } from '../../../libs/determinism'

const EYE_SACCADE_INT_STEP = 400
const EYE_SACCADE_INT_P = [
  [0.075, 800],
  [0.110, 0],
  [0.125, 0],
  [0.140, 0],
  [0.125, 0],
  [0.050, 0],
  [0.040, 0],
  [0.030, 0],
  [0.020, 0],
  [1.000, 0],
]
for (let i = 1; i < EYE_SACCADE_INT_P.length; i++) {
  EYE_SACCADE_INT_P[i][0] += EYE_SACCADE_INT_P[i - 1][0]
  EYE_SACCADE_INT_P[i][1] = EYE_SACCADE_INT_P[i - 1][1] + EYE_SACCADE_INT_STEP
}

/**
 * Fixed default seed for {@link randomSaccadeInterval}.
 *
 * A *constant* (not time/entropy derived) so the saccade stream replays
 * bit-identically. Callers that want per-session variation pass an explicit
 * `rng`. The default RNG instance is shared across calls so a single session
 * consumes the stream monotonically (same timeline -> same saccade sequence).
 */
const EYE_SACCADE_DEFAULT_SEED = 0x5ACCADE5
const defaultSaccadeRng = mulberry32(EYE_SACCADE_DEFAULT_SEED)

/**
 * This is a simple function to generate a random interval between eye saccades.
 *
 * Behavior shape is unchanged from the old `Math.random()` version: a
 * cumulative-probability draw picks a bucket, then a uniform draw jitters
 * within that bucket by `EYE_SACCADE_INT_STEP`. The only difference is the RNG
 * is now deterministic and injectable.
 *
 * @param rng  source of randomness (floats in [0, 1)). Defaults to a fixed
 *             module-seeded stream so replay is bit-identical.
 * @returns    Interval in milliseconds.
 */
export function randomSaccadeInterval(rng: () => number = defaultSaccadeRng): number {
  const r = rng()
  for (let i = 0; i < EYE_SACCADE_INT_P.length; i++) {
    if (r <= EYE_SACCADE_INT_P[i][0]) {
      return EYE_SACCADE_INT_P[i][1] + rng() * EYE_SACCADE_INT_STEP
    }
  }
  return EYE_SACCADE_INT_P.at(-1)![1] + rng() * EYE_SACCADE_INT_STEP
}
