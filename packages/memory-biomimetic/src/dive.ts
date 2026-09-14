import type { InterestThread } from './contracts-v8'

/**
 * v8 §47 — DIVE: Developmental Intrinsic Value Engine.
 *
 * DIVE makes interest *developmental*: it emerges from novelty, knowledge gaps,
 * capability-boundary challenge, identity relevance, user relevance and future
 * utility — and is actively *suppressed* by cost, safety/source risk and
 * repetitive/addictive narrowing. Interest is never a bare topic list (§47.1):
 * only-maximising novelty degrades to random browsing, only-maximising user
 * relevance degrades to sycophancy, only-maximising utility is just a tool.
 *
 * This module is pure and deterministic. Runtime opt-in (whether DIVE gates
 * exploration at all) is handled by the store/config layer, exactly like the
 * v7 HAC/CDI/CBR modules; here we only expose the verifiable mathematics.
 */

/** Candidate interest signal components. Attraction and inhibition both ∈ [0,1]. */
export interface InterestComponents {
  /** N_q — novelty. */
  novelty: number
  /** G_q — closable knowledge gap. */
  knowledgeGap: number
  /** I_q — relevance to developmental identity / stable preferences. */
  identityRelevance: number
  /** C_q — challenge near the capability boundary. */
  challenge: number
  /** R_q — relevance to the user, shared history or shared goals. */
  userRelevance: number
  /** U_q — expected future task utility. */
  futureUtility: number
  /** K_q — cost (compute/time/network/money). Inhibitory. */
  cost: number
  /** S_q — safety / copyright / source risk. Inhibitory. */
  risk: number
  /** P_q — repetition / addictive-loop / narrowing penalty. Inhibitory. */
  repetitionPenalty: number
}

/** Per-dimension weights; defaults give a balanced, non-degenerate engine. */
export interface InterestWeights {
  wNovelty: number
  wGap: number
  wIdentity: number
  wChallenge: number
  wUser: number
  wUtility: number
  wCost: number
  wRisk: number
  wRepetition: number
}

export const DEFAULT_INTEREST_WEIGHTS: InterestWeights = {
  wNovelty: 1,
  wGap: 1.2,
  wIdentity: 1.2,
  wChallenge: 0.8,
  wUser: 1,
  wUtility: 0.8,
  wCost: 1,
  wRisk: 1.5,
  wRepetition: 1,
}

function clamp01(x: number): number {
  return Math.min(1, Math.max(0, x))
}

/**
 * §47.1 — intrinsic value of a candidate question/topic.
 *
 * V_interest(q,t) = w_n·N + w_g·G + w_i·I + w_c·C + w_r·R + w_u·U
 *                 − w_k·K − w_s·S − w_p·P
 *
 * Attraction and inhibition terms are both mandatory: the value is the signed
 * sum, clamped to [0,1] so it can be stored on an `InterestThread`.
 */
export function intrinsicValue(
  c: InterestComponents,
  w: InterestWeights = DEFAULT_INTEREST_WEIGHTS,
): number {
  const attraction
    = w.wNovelty * clamp01(c.novelty)
      + w.wGap * clamp01(c.knowledgeGap)
      + w.wIdentity * clamp01(c.identityRelevance)
      + w.wChallenge * clamp01(c.challenge)
      + w.wUser * clamp01(c.userRelevance)
      + w.wUtility * clamp01(c.futureUtility)
  const inhibition
    = w.wCost * clamp01(c.cost)
      + w.wRisk * clamp01(c.risk)
      + w.wRepetition * clamp01(c.repetitionPenalty)
  return clamp01(attraction - inhibition)
}

/** Lifecycle signals that drive an InterestThread between states. */
export type InterestSignal
  = | 'seed' // a new thread is created → latent
    | 'probe' // curiosity probe → active
    | 'deepen' // sustained inquiry → stays active
    | 'incubate' // park it to revisit later → incubating
    | 'revisit' // come back from incubation → active
    | 'satisfy' // questions answered → satisfied
    | 'saturate' // novelty frontier exhausted → satisfied
    | 'abandon' // deliberately drop → abandoned (reason recorded)

/**
 * §47.2 — InterestThread lifecycle state machine.
 *
 * Seed → (latent) → Curiosity Probe → Active Inquiry → Deepening → Incubation
 * → Revisit → Satisfied / Abandoned / Identity-linked. Returns the next status,
 * or null if the signal is not a legal transition from the current status — so
 * callers can detect and record invalid lifecycle jumps rather than silently
 * corrupting the thread.
 */
export function nextInterestStatus(
  current: InterestThread['status'],
  signal: InterestSignal,
): InterestThread['status'] | null {
  switch (signal) {
    case 'seed':
      return 'latent'
    case 'probe':
    case 'deepen':
    case 'revisit':
      // probing/deepening/revisiting is only meaningful from a non-terminal state
      return (current === 'satisfied' || current === 'abandoned') ? null : 'active'
    case 'incubate':
      return current === 'active' ? 'incubating' : null
    case 'satisfy':
    case 'saturate':
      return (current === 'active' || current === 'incubating') ? 'satisfied' : null
    case 'abandon':
      // any non-terminal state may be abandoned
      return (current === 'satisfied' || current === 'abandoned') ? null : 'abandoned'
  }
}

/** A candidate for portfolio selection: a thread plus its computed value. */
export interface PortfolioCandidate {
  thread: Pick<InterestThread, 'id' | 'subject' | 'intrinsicValue' | 'identityRelevance' | 'userRelevance'>
}

/** Options for portfolio selection (§47.4). */
export interface PortfolioOptions {
  /** Max threads to select (the daily exploration budget). */
  budget: number
  /** Diversity bonus weight (λ). */
  diversityWeight?: number
  /** Redundancy penalty weight (ρ). */
  redundancyWeight?: number
  /**
   * Fraction (0..1) of the budget reserved for identity-linked exploration —
   * non-user-utilitarian but role/identity-aligned — so the agent forms
   * perceptible individual interests rather than only serving the user (§47.4).
   */
  identityReserve?: number
  /** Subjects that must never be auto-promoted to a sustained interest. */
  forbiddenSubjects?: string[]
}

export interface PortfolioSelection {
  /** Selected thread ids, in selection order. */
  selected: string[]
  /** Ids reserved for identity-linked exploration. */
  identityReserved: string[]
  /** Ids excluded because their subject is forbidden. */
  forbidden: string[]
}

function sharesSubject(a: string, b: string): boolean {
  return a.trim().toLowerCase() === b.trim().toLowerCase()
}

/**
 * §47.4 — select an exploration *portfolio*, not a single greedy point.
 *
 * Greedy marginal-gain selection: repeatedly pick the candidate that maximises
 *   value + λ·(novel subject?) − ρ·(redundant subject?)
 * until the budget is exhausted. A fraction of the budget is reserved for
 * identity-linked (high identity relevance, low user relevance) threads so the
 * portfolio always contains non-sycophantic exploration; forbidden subjects are
 * hard-excluded regardless of value.
 */
export function selectPortfolio(
  candidates: PortfolioCandidate[],
  opts: PortfolioOptions,
): PortfolioSelection {
  const λ = opts.diversityWeight ?? 0.2
  const ρ = opts.redundancyWeight ?? 0.3
  const reserve = clamp01(opts.identityReserve ?? 0.2)
  const forbiddenSubjects = opts.forbiddenSubjects ?? []

  const allowed = candidates.filter(c => !forbiddenSubjects.some(f => sharesSubject(f, c.thread.subject)))
  const forbidden = candidates
    .filter(c => forbiddenSubjects.some(f => sharesSubject(f, c.thread.subject)))
    .map(c => c.thread.id)

  const reserveCount = Math.max(0, Math.floor(opts.budget * reserve))
  // identity-linked: strongly identity-relevant but weakly user-relevant
  const identityPool = allowed
    .filter(c => c.thread.identityRelevance >= 0.6 && c.thread.userRelevance <= 0.4)
    .sort((a, b) => b.thread.intrinsicValue - a.thread.intrinsicValue)
  const identityReserved = identityPool.slice(0, reserveCount).map(c => c.thread.id)

  const chosen = new Set<string>(identityReserved)
  const chosenSubjects = new Set<string>(identityPool.slice(0, reserveCount).map(c => c.thread.subject))
  const pool = allowed.filter(c => !chosen.has(c.thread.id))

  while (chosen.size < opts.budget && pool.length > 0) {
    let bestIdx = -1
    let bestScore = -Infinity
    for (let i = 0; i < pool.length; i++) {
      const c = pool[i]
      const isNovelSubject = ![...chosenSubjects].some(s => sharesSubject(s, c.thread.subject))
      const score = c.thread.intrinsicValue + (isNovelSubject ? λ : -ρ)
      if (score > bestScore) {
        bestScore = score
        bestIdx = i
      }
    }
    const picked = pool.splice(bestIdx, 1)[0]
    chosen.add(picked.thread.id)
    chosenSubjects.add(picked.thread.subject)
  }

  return {
    selected: [...chosen],
    identityReserved,
    forbidden,
  }
}
