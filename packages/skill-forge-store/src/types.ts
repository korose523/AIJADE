/**
 * Enriched skill schema — the fix for the "precision is uncomputable" defect.
 *
 * ## The problem this schema solves
 *
 * The existing `createSkillRegistry` in
 * `packages/agent-skill-forge/src/registry.ts` is a `Map<string, SkillPackage>`
 * with an add-only lifecycle. Two consequences make it unusable as a
 * measurement instrument:
 *
 * 1. **Nothing is ever removed or rejected**, so the library only grows. A
 *    library that only grows can yield a recall-like quantity ("how many
 *    skills were produced") but never a precision-like one ("how many of the
 *    produced skills were actually good").
 * 2. **Registration is equated with success.** `register()` returns
 *    `{ registered: true }` and that is the only outcome ever recorded. There
 *    is no field capturing whether the skill was ever *used*, and none
 *    capturing whether it *worked* when used.
 *
 * Therefore the headline metric for RQ-C — the self-verification hallucination
 * rate, i.e. "of the skills the LLM judged correct, how many actually failed
 * when executed?" — cannot be computed from the current data at all.
 *
 * ## The fix
 *
 * Split every skill's life into three independently recorded events:
 *
 * ```
 *   created  ──▶  selfVerified(pass/fail, score)  ──▶  executed(success/failure)
 * ```
 *
 * With those three events recorded per skill, the following become derivable:
 *
 * - **precision**          = successCount / callCount
 * - **self-verification hallucination rate**
 *                          = |selfPass ∧ execFail| / |selfPass|
 * - **self-verification miss rate**
 *                          = |selfFail ∧ execSuccess| / |selfFail|
 * - **library utility curve**
 *                          = cumulative successCount over time (the learning
 *                            curve that nothing in the project can currently
 *                            draw)
 *
 * The `domain` field is what makes the 2×2 possible:
 * `(game | conversation) × (selfVerification on | off)`.
 * A skill created in the game domain has an environmental verdict available;
 * one created in open conversation does not. That asymmetry is the experiment.
 */

/**
 * Where the skill was produced. Drives which cells of an experiment can carry
 * an environmental verdict.
 *
 * Only `executable` and `game` have an oracle (see {@link hasEnvironmentalOracle}).
 * `conversation` is retained as the *oracle-free* contrast condition: it exists
 * to show that self-reported verdicts cannot be audited without ground truth,
 * which is an argument for the design, not a 2×2 cell.
 */
export type SkillDomain = 'executable' | 'game' | 'conversation' | 'synthetic'

/**
 * Whether the creation environment can supply an objective verdict.
 *
 * `executable` is the domain used by `@proj-aijade/skill-bench-env`: a generated
 * skill is run against a deterministic test suite, so pass/fail is ground truth
 * that is reproducible offline. `game` (Minecraft via mineflayer) has the same
 * property when a live server is available, but no game environment ships with
 * this repository, so `executable` is the domain that actually produces data.
 *
 * Open conversation has no such oracle, which is exactly why self-verification
 * bias can be measured by comparing the two.
 */
export function hasEnvironmentalOracle(domain: SkillDomain): boolean {
  return domain === 'executable' || domain === 'game'
}

/** Lifecycle state. `retired` is essential: it stops the library being add-only. */
export type SkillLifecycle = 'active' | 'retired' | 'rejected'

/** The verdict returned by actually running the skill. */
export interface ExecutionOutcome {
  ok: boolean
  /** Free-form error or status from the environment. */
  detail?: string
  /** Wall-clock ms. */
  durationMs?: number
}

/**
 * A persisted skill record.
 *
 * Every field beyond the identity triple exists because some downstream metric
 * needs it. Removing one silently breaks a metric — see `computeMetrics`.
 */
export interface SkillRecord {
  // ---- identity -----------------------------------------------------------
  skillId: string
  name: string
  /** Creation wall-clock (epoch ms). */
  createdAt: number
  domain: SkillDomain

  // ---- provenance (what triggered creation) ------------------------------
  /**
   * Why the teachable-moment detector fired.
   * Without this you cannot audit *which* moments were considered teachable.
   */
  trigger?: {
    /** The detector's own reasoning, verbatim. */
    rationale?: string
    /** Detector confidence, if it emits one. */
    confidence?: number
    /** Session this came from, for grouping. */
    sessionId?: string
    /** Turn index within the session. */
    turnIndex?: number
  }

  // ---- event 1: LLM self-verification -------------------------------------
  /**
   * The LLM's own judgement of the skill it just generated.
   * This is the *predictor* whose validity RQ-C puts on trial.
   */
  selfVerification?: {
    verdict: 'pass' | 'fail'
    score?: number
    rationale?: string
    /** Which model produced the verdict — self-bias is model dependent. */
    model?: string
    /** Whether self-verification was enabled for this trial (2×2 axis). */
    enabled: boolean
  }

  // ---- event 2: environmental execution -----------------------------------
  /**
   * Ground truth, when the domain provides one.
   * `undefined` means "never executed" — which is NOT the same as "failed".
   * Every metric below distinguishes the two.
   */
  execution?: ExecutionOutcome & {
    executedAt: number
    /** How many times the skill was actually invoked. */
    attempt: number
  }

  // ---- event 3: environmental feedback loop ------------------------------
  /**
   * Whether the environment's verdicts were fed back into this skill's
   * lifecycle (driving retirement / pruning).
   *
   * This is the *second* factor of the learning-loop 2×2 (the first being
   * `selfVerification.enabled`). It is optional so that existing callers — and
   * the package's 9 existing tests — keep working without supplying it. When
   * `undefined` every downstream function treats it as disabled, i.e.
   * `(r.envFeedback?.enabled ?? false)`.
   */
  envFeedback?: {
    enabled: boolean
    /** When the feedback loop was closed for this skill. */
    appliedAt?: number
  }

  // ---- counters (the reason precision is computable) ----------------------
  callCount: number
  successCount: number
  failureCount: number
  lastUsedAt?: number

  // ---- lifecycle ----------------------------------------------------------
  status: SkillLifecycle
  retiredAt?: number
  /** Why it was retired/rejected — needed to separate "bad" from "obsolete". */
  retirementReason?: 'low-precision' | 'superseded' | 'self-rejected' | 'manual'

  /** The serialised skill body (markdown or code), for reproduction. */
  body?: string
  /** Anything else the experiment needs. */
  metadata?: Record<string, unknown>
}

// ---------------------------------------------------------------------------
// Derived metrics
// ---------------------------------------------------------------------------

export interface SkillLibraryMetrics {
  total: number
  active: number
  retired: number
  rejected: number

  /** Skills that were self-verified as passing. */
  selfPass: number
  selfFail: number
  /** Skills where self-verification was disabled (the 2×2 control cell). */
  selfVerificationDisabled: number

  /** Skills with an environmental verdict. */
  executed: number
  execSuccess: number
  execFail: number

  /**
   * successCount / callCount over the whole library.
   * NaN when nothing was ever called — deliberately not zero, so that
   * "not measured" is never mistaken for "measured as bad".
   */
  precision: number
  /** Mean calls per skill; a proxy for whether the library is actually used. */
  meanCallsPerSkill: number

  /**
   * |selfPass ∧ execFail| / |selfPass ∧ executed| — the headline RQ-C number.
   *
   * The denominator is **self-passed AND actually executed**, not merely
   * self-passed. This matters: if a skill self-passed but was never run, it
   * carries no information about whether the self-assessment was right, so
   * counting it would dilute the rate toward zero and let a study that
   * executed nothing report "0% hallucination". NaN when empty.
   */
  selfVerificationHallucinationRate: number
  /**
   * |selfFail ∧ execSuccess| / |selfFail ∧ executed| — the conservative error:
   * good skills the model threw away. NaN when empty.
   */
  selfVerificationMissRate: number
  /**
   * Agreement between the LLM's verdict and the environment's verdict.
   * NaN when there is no overlap.
   */
  selfEnvironmentAgreement: number

  /** Skills created per domain, for the 2×2 cells. */
  byDomain: Record<SkillDomain, number>
}

function ratio(numerator: number, denominator: number): number {
  return denominator === 0 ? Number.NaN : numerator / denominator
}

/**
 * Compute the library-level metrics.
 *
 * Every rate is `NaN` (not `0`) when its denominator is empty. This is a
 * deliberate choice: a study that ran no executions must not be able to report
 * "0% hallucination rate".
 */
export function computeMetrics(records: readonly SkillRecord[]): SkillLibraryMetrics {
  const byDomain: Record<SkillDomain, number> = { executable: 0, game: 0, conversation: 0, synthetic: 0 }

  let active = 0
  let retired = 0
  let rejected = 0
  let selfPass = 0
  let selfFail = 0
  let selfVerificationDisabled = 0
  let executed = 0
  let execSuccess = 0
  let execFail = 0
  let selfPassExecFail = 0
  let selfFailExecSuccess = 0
  // Denominators must count only skills that were actually executed — see the
  // note on `selfVerificationHallucinationRate` above.
  let selfPassExecuted = 0
  let selfFailExecuted = 0
  let agreementNumerator = 0
  let agreementDenominator = 0
  let totalCalls = 0

  for (const r of records) {
    byDomain[r.domain] = (byDomain[r.domain] ?? 0) + 1

    if (r.status === 'active')
      active++
    else if (r.status === 'retired')
      retired++
    else rejected++

    const sv = r.selfVerification
    if (!sv || !sv.enabled)
      selfVerificationDisabled++
    else if (sv.verdict === 'pass')
      selfPass++
    else selfFail++

    totalCalls += r.callCount

    if (r.execution) {
      executed++
      if (r.execution.ok)
        execSuccess++
      else execFail++

      if (sv && sv.enabled) {
        agreementDenominator++
        if ((sv.verdict === 'pass') === r.execution.ok)
          agreementNumerator++

        if (sv.verdict === 'pass') {
          selfPassExecuted++
          if (!r.execution.ok)
            selfPassExecFail++
        }
        else {
          selfFailExecuted++
          if (r.execution.ok)
            selfFailExecSuccess++
        }
      }
    }
  }

  return {
    total: records.length,
    active,
    retired,
    rejected,
    selfPass,
    selfFail,
    selfVerificationDisabled,
    executed,
    execSuccess,
    execFail,
    precision: ratio(
      records.reduce((a, r) => a + r.successCount, 0),
      totalCalls,
    ),
    meanCallsPerSkill: ratio(totalCalls, records.length),
    selfVerificationHallucinationRate: ratio(selfPassExecFail, selfPassExecuted),
    selfVerificationMissRate: ratio(selfFailExecSuccess, selfFailExecuted),
    selfEnvironmentAgreement: ratio(agreementNumerator, agreementDenominator),
    byDomain,
  }
}

/**
 * @deprecated
 *
 * **This table cannot carry a headline rate and must not be used for the
 * interaction-effect test.** It is kept only for backward compatibility
 * (existing tests and `agent-skill-forge`).
 *
 * The original design used `domain` (game | conversation) as one axis and
 * `selfVerification` as the other. That is methodologically broken:
 *
 * - `assertOracleAvailable` (registry.ts) throws for any non-`game` domain, so
 *   `conversation`-domain skills can never `recordExecution`. They therefore
 *   have no environmental verdict.
 * - Consequently `selfVerificationHallucinationRate` (which needs *both* a self
 *   verdict and an execution verdict) is `NaN` for every `(conversation, ·)`
 *   cell, and for the `(game, selfVerification OFF)` cell (no self verdict).
 * - 3 of the 4 cells are `NaN`, so no interaction effect can be estimated. A
 *   reviewer rejects a 2×2 that is 75% empty.
 *
 * **Replacement:** `computeLearningLoopTable`, whose two factors are
 * `selfVerification.enabled` and `envFeedback.enabled` — both of which vary
 * inside* the oracle domain, so every cell's `precision` (the new headline
 * rate) is well defined. The cross-domain comparison that `domain` used to
 * provide is now carried by `SkillLibraryMetrics.byDomain` plus
 * `computeSelfVerificationDiagnostics`.
 *
 * This function is frozen: do not change its output shape.
 */
export interface TwoByTwoCell {
  domain: SkillDomain
  selfVerificationEnabled: boolean
  count: number
  hallucinationRate: number
  precision: number
}

export function computeTwoByTwo(records: readonly SkillRecord[]): TwoByTwoCell[] {
  const cells: TwoByTwoCell[] = []
  const domains: SkillDomain[] = ['game', 'conversation']
  const flags = [true, false]

  for (const domain of domains) {
    for (const enabled of flags) {
      const subset = records.filter(
        r => r.domain === domain && (r.selfVerification?.enabled ?? false) === enabled,
      )
      const m = computeMetrics(subset)
      cells.push({
        domain,
        selfVerificationEnabled: enabled,
        count: subset.length,
        hallucinationRate: m.selfVerificationHallucinationRate,
        precision: m.precision,
      })
    }
  }

  return cells
}

// ---------------------------------------------------------------------------
// Redesigned 2×2: selfVerification × envFeedback
//
// Both factors vary *inside* the oracle domain, so every cell has a well
// defined `precision`. See the `@deprecated` note on `computeTwoByTwo` for why
// `domain` could not serve as a 2×2 axis.
// ---------------------------------------------------------------------------

/**
 * One cell of the learning-loop 2×2.
 *
 * The two factors are `selfVerification.enabled` (does the LLM rate its own
 * skill?) and `envFeedback.enabled` (are environment verdicts fed back into the
 * skill's lifecycle?). `precision` — cumulative success rate — is the headline
 * metric and is defined for all four cells, which is what makes an interaction
 * effect estimable.
 *
 * | | envFeedback OFF | envFeedback ON |
 * |---|---|---|
 * | selfVerification OFF | naïve accumulation baseline | env-feedback only |
 * | selfVerification ON | naïve self-report (no environment feedback) | full loop |
 *
 * Positioning note (measurement study, not a method-comparison): Voyager
 * (Wang et al., arXiv:2305.16291) demonstrated a *causal* contribution of
 * self-verification to downstream performance — removing the self-verification
 * module dropped the count of uniquely discovered items by 73% (vs −93% for
 * removing the auto-curriculum and −46% for removing the skill library), and it
 * ran that ablation at temperature 0. Voyager therefore PROVED that
 * self-verification helps; it did NOT measure how *reliable the self-assessment
 * itself* is (how often the critic judges a skill correct when it is in fact
 * wrong, or vice versa). Measuring that self-assessment accuracy — against a
 * deterministic oracle — is precisely the gap this work fills, and it is what
 * distinguishes the two contributions. We make no claim that our method
 * "beats" Voyager; we measure a quantity Voyager left unmeasured.
 */
export interface LearningLoopCell {
  selfVerificationEnabled: boolean
  envFeedbackEnabled: boolean
  /** Number of skills in this cell. */
  count: number
  /** Headline metric — successCount / callCount. Finite for every cell. */
  precision: number
  /** retired / count within the cell. */
  retiredRate: number
  /** Mean invocations per skill in the cell. */
  meanCallsPerSkill: number
}

/**
 * Build the learning-loop 2×2.
 *
 * Records are grouped by `(selfVerification?.enabled ?? false)` ×
 * `(envFeedback?.enabled ?? false)`. Each cell is summarised with
 * `computeMetrics`, so `precision` (and therefore the interaction effect) is
 * defined for all four cells.
 *
 * By default every oracle-bearing domain is pooled (`executable` and `game`),
 * because the experiment must live inside domains that can supply ground
 * truth. Pass `options.domain` to restrict to one. Cross-domain comparison is
 * handled separately by `byDomain` and `computeSelfVerificationDiagnostics`.
 */
export function computeLearningLoopTable(
  records: readonly SkillRecord[],
  options?: { domain?: SkillDomain },
): LearningLoopCell[] {
  // Default = all oracle-bearing domains pooled (executable + game), matching
  // the docstring above. Callers that omit `domain` must NOT get an empty
  // table, which is what a hardcoded 'game' default would silently produce.
  const targetDomains: SkillDomain[] = options?.domain
    ? [options.domain]
    : (['executable', 'game'] as SkillDomain[])
  const filtered = records.filter(r => targetDomains.includes(r.domain))

  const cells: LearningLoopCell[] = []
  for (const sv of [false, true] as const) {
    for (const ef of [false, true] as const) {
      const subset = filtered.filter(
        r => (r.selfVerification?.enabled ?? false) === sv
          && (r.envFeedback?.enabled ?? false) === ef,
      )
      const m = computeMetrics(subset)
      cells.push({
        selfVerificationEnabled: sv,
        envFeedbackEnabled: ef,
        count: subset.length,
        precision: m.precision,
        retiredRate: ratio(m.retired, subset.length),
        meanCallsPerSkill: m.meanCallsPerSkill,
      })
    }
  }

  return cells
}

/**
 * Independent diagnostic for the self-verification term.
 *
 * **This is NOT a 2×2 dimension.** It is reported only for the
 * `selfVerification = ON` row, because without a self-verdict there is nothing
 * to diagnose: "self-verification hallucination" is undefined when the LLM
 * never rated its own skill. It therefore complements `computeLearningLoopTable`
 * (which spans all four cells with `precision`) rather than being one of its
 * axes.
 *
 * Counts only records that have BOTH a self-verification verdict AND an
 * execution verdict, so its rates are defined on the overlap where they can
 * actually be measured.
 */
export interface SelfVerificationDiagnostic {
  /** Records with both a self-verdict and an execution. */
  n: number
  /** |selfPass ∧ execFail| / |selfPass ∧ executed|. */
  hallucinationRate: number
  /** |selfFail ∧ execSuccess| / |selfFail ∧ executed|. */
  missRate: number
  /** Agreement between the LLM verdict and the environment verdict. */
  agreement: number
}

/**
 * Compute the self-verification diagnostic table.
 *
 * Only records with `selfVerification.enabled` and an `execution` contribute;
 * the result's rates are then taken from `computeMetrics` restricted to that
 * overlap. When no record qualifies, `n` is 0 and the rates are `NaN` — which
 * correctly signals "self-verification was never measured", not "it was
 * perfect".
 */
export function computeSelfVerificationDiagnostics(
  records: readonly SkillRecord[],
): SelfVerificationDiagnostic {
  const subset = records.filter(r => r.selfVerification?.enabled && r.execution)
  const m = computeMetrics(subset)
  return {
    n: subset.length,
    hallucinationRate: m.selfVerificationHallucinationRate,
    missRate: m.selfVerificationMissRate,
    agreement: m.selfEnvironmentAgreement,
  }
}
