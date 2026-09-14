/**
 * §50.1 — SharingPolicy.
 *
 * Computes a deterministic V_share score from the eight utility components
 * (relevance / novelty / relationalValue / timeliness / uncertainty lift the
 * score; interruption / privacyRisk / repetition lower it), then selects one of
 * the four delivery channels. A `full_share` is only emitted when the score clears
 * the high threshold AND it is not a quiet hour; otherwise the decision is
 * downgraded (light_hint / next_chat / diary) so the agent never over-shares.
 */

import type { ShareCandidate } from '@proj-aijade/memory-biomimetic'

import type { SchedulerPort, StoragePort } from './ports'

import { validateShareCandidate } from '@proj-aijade/memory-biomimetic'

import { genId } from './util'

const KIND = 'share_candidate'

/** Positive (value) weights — sum to 1.0 so the positive sub-score ∈ [0,1]. */
const POS_WEIGHTS = {
  relevance: 0.25,
  novelty: 0.2,
  relationalValue: 0.2,
  timeliness: 0.15,
  uncertainty: 0.2,
}
/** Negative (cost) weights — sum to 1.0 so the cost sub-score ∈ [0,1]. */
const NEG_WEIGHTS = {
  interruption: 0.4,
  privacyRisk: 0.4,
  repetition: 0.2,
}

const THRESHOLDS = {
  fullShare: 0.6,
  lightHint: 0.35,
  nextChat: 0.15,
}

/** Deterministic V_share computation (pure, exported for testing / reuse). */
export function computeShareScore(u: ShareCandidate['utility']): number {
  const pos
    = POS_WEIGHTS.relevance * u.relevance
      + POS_WEIGHTS.novelty * u.novelty
      + POS_WEIGHTS.relationalValue * u.relationalValue
      + POS_WEIGHTS.timeliness * u.timeliness
      + POS_WEIGHTS.uncertainty * u.uncertainty
  const neg
    = NEG_WEIGHTS.interruption * u.interruption
      + NEG_WEIGHTS.privacyRisk * u.privacyRisk
      + NEG_WEIGHTS.repetition * u.repetition
  return Math.min(1, Math.max(0, pos - neg))
}

/** Quiet hours: 23:00–07:00 local (the agent should not actively broadcast). */
export function isQuietHour(now: number): boolean {
  const hour = new Date(now).getHours()
  return hour >= 23 || hour < 7
}

export interface ShareUtility {
  relevance: number
  novelty: number
  relationalValue: number
  timeliness: number
  uncertainty: number
  interruption: number
  privacyRisk: number
  repetition: number
}

export interface ScoreShareInput {
  contentRef: string
  utility: ShareUtility
}

export interface ShareDecision {
  candidate: ShareCandidate
  quiet: boolean
}

export interface SharingPolicyDeps {
  storage: StoragePort
  scheduler: SchedulerPort
}

export class SharingPolicy {
  constructor(
    private readonly deps: SharingPolicyDeps,
    private readonly agentId: string,
    private readonly userScope: string,
  ) {}

  async scoreShare(input: ScoreShareInput): Promise<ShareDecision> {
    const score = computeShareScore(input.utility)
    const now = this.deps.scheduler.now()
    const quiet = isQuietHour(now)

    let channel: ShareCandidate['channel']
    if (score >= THRESHOLDS.fullShare && !quiet)
      channel = 'full_share'
    else if (score >= THRESHOLDS.lightHint && !quiet)
      channel = 'light_hint'
    else if (score >= THRESHOLDS.nextChat)
      channel = 'next_chat'
    else channel = 'diary'

    const candidate: ShareCandidate = {
      id: genId('sc'),
      schema: 'aijade.share_candidate@1',
      agentId: this.agentId,
      userScope: this.userScope,
      contentRef: input.contentRef,
      utility: input.utility,
      score,
      channel,
      decidedAt: now,
    }
    const check = validateShareCandidate(candidate)
    if (!check.ok)
      throw new Error(`ShareCandidate rejected: ${check.reason}`)
    await this.deps.storage.put(KIND, candidate.id, candidate)
    return { candidate, quiet }
  }
}
