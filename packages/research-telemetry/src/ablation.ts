/**
 * Ablation switches + deterministic config fingerprinting.
 *
 * Why this exists: the single most-cited reason systems papers get rejected is
 * "insufficient evaluation" — reviewers want to know *which component* produced
 * the effect. Ablation is how a system becomes an experiment
 * (see Park et al., Generative Agents, UIST 2023, for the canonical example).
 *
 * The fingerprint lets you group sessions across participants, reruns and
 * machines without relying on a hand-maintained naming convention.
 */

import type { AblationCondition, AblationConfig } from './types'

import {

  FULL_ABLATION,
} from './types'

/**
 * Stable, order-independent string fingerprint of an ablation config.
 *
 * Uses a sorted key:value join rather than JSON.stringify so that key insertion
 * order differences never produce two fingerprints for the same condition.
 */
export function fingerprintConfig(config: AblationConfig): string {
  const entries = Object.entries(config)
    // Sort for determinism regardless of property insertion order.
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([k, v]) => `${k}:${v === true ? '1' : '0'}`)
  return entries.join('|')
}

/** Parse an ablation config from environment variables. */
export function ablationFromEnv(
  env: Record<string, string | undefined> = typeof process !== 'undefined' ? process.env : {},
): AblationConfig {
  const read = (key: string, fallback: boolean): boolean => {
    const raw = env[key]
    if (raw === undefined || raw === '')
      return fallback
    const v = raw.trim().toLowerCase()
    return v === '1' || v === 'true' || v === 'on' || v === 'yes'
  }

  return {
    personaDynamics: read('AIJADE_ABLATION_PERSONA_DYNAMICS', FULL_ABLATION.personaDynamics),
    hormoneCoupling: read('AIJADE_ABLATION_HORMONE_COUPLING', FULL_ABLATION.hormoneCoupling),
    memoryRetrieval: read('AIJADE_ABLATION_MEMORY_RETRIEVAL', FULL_ABLATION.memoryRetrieval),
    skillForge: read('AIJADE_ABLATION_SKILL_FORGE', FULL_ABLATION.skillForge),
    discourseMemory: read('AIJADE_ABLATION_DISCOURSE_MEMORY', FULL_ABLATION.discourseMemory),
  }
}

/** Environment variable names, exported so docs/CLIs stay in sync. */
export const ABLATION_ENV_KEYS = {
  personaDynamics: 'AIJADE_ABLATION_PERSONA_DYNAMICS',
  hormoneCoupling: 'AIJADE_ABLATION_HORMONE_COUPLING',
  memoryRetrieval: 'AIJADE_ABLATION_MEMORY_RETRIEVAL',
  skillForge: 'AIJADE_ABLATION_SKILL_FORGE',
  discourseMemory: 'AIJADE_ABLATION_DISCOURSE_MEMORY',
} as const satisfies Record<keyof AblationConfig, string>

/**
 * The standard condition set for the first ablation study.
 *
 * Each condition disables exactly one component relative to baseline, so any
 * delta is attributable. `baseline` keeps everything on.
 */
export const DEFAULT_CONDITIONS: readonly AblationCondition[] = Object.freeze([
  {
    name: 'baseline',
    config: { ...FULL_ABLATION },
    description: 'All components enabled. Reference condition.',
  },
  {
    name: 'no-persona-dynamics',
    config: { ...FULL_ABLATION, personaDynamics: false },
    description: 'Isolates the contribution of any affective dynamics at all.',
  },
  {
    name: 'no-hormone-coupling',
    config: { ...FULL_ABLATION, hormoneCoupling: false },
    description:
      'Isolates the endocrine→persona coupling term inside drift. Directly probes Gap #2 '
      + '(which dynamics parameters actually matter when they drive generation).',
  },
  {
    name: 'no-memory-retrieval',
    config: { ...FULL_ABLATION, memoryRetrieval: false },
    description: 'Isolates memory retrieval; also yields its latency/token cost for Gap #3.',
  },
  {
    name: 'no-skill-forge',
    config: { ...FULL_ABLATION, skillForge: false },
    description: 'Isolates automatic skill creation (RQ-C).',
  },
  {
    name: 'no-discourse-memory',
    config: { ...FULL_ABLATION, discourseMemory: false },
    description: 'Isolates the bounded recent-turn buffer.',
  },
])

/** Look up a condition by name; falls back to `baseline`. */
export function resolveCondition(
  name: string,
  conditions: readonly AblationCondition[] = DEFAULT_CONDITIONS,
): AblationCondition {
  const found = conditions.find(c => c.name === name)
  if (found)
    return found
  const baseline = conditions.find(c => c.name === 'baseline')
  if (baseline)
    return baseline
  return { name: 'baseline', config: { ...FULL_ABLATION } }
}

/** Human-readable diff between a config and the full baseline. */
export function describeAblation(config: AblationConfig): string {
  const off = (Object.keys(config) as (keyof AblationConfig)[])
    .filter(k => config[k] === false)
  return off.length === 0 ? 'baseline (all on)' : `disabled: ${off.join(', ')}`
}
