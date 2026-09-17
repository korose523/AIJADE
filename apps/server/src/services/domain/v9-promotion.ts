/**
 * v10 §3 — Shadow-param promotion service.
 *
 * A candidate shadow parameter may only be promoted (i.e. written as an evolution
 * spec / eval report that can influence the system) when it clears TWO gates:
 *
 *   1. EvidenceGate  — `canPromote(evaluationPack)` must return `{ ok: true }`.
 *      The core unit/contract/property-test gate is mandatory; any optional gate
 *      present in the pack that fails also blocks promotion.
 *
 *   2. PGC write gate — the proposal is reduced to a `PgcCandidateWrite` via
 *      `shadowProposalAsPgcCandidate` and adjudicated by `decidePgc`. Only when
 *      `commit_possible === true` may the candidate be promoted.
 *
 * Both gates are fail-closed: a refusal (either gate) returns a structured
 * result and writes NOTHING to the database. No row is fabricated, no
 * `memory_version_id` is invented (v10 §14.1 forbidden list).
 *
 * The two landing tables are:
 *   - `evolution_specs` (v9EvolutionSpecs) — the promotion record (proposal + decision summary).
 *   - `eval_reports`     (v9EvalReports)     — the evaluation report (gate summary + conclusion).
 */

import type { EvaluationEvidencePack, ShadowParamsProposal } from '@proj-aijade/memory-biomimetic'

import type { Database } from '../../libs/db'
import type { V9PromotionJob } from './v9-jobs'

import {
  canPromote,
  decidePgc,
  NEUTRAL_PGC_POLICY,
  selectCandidateVersion,
  shadowProposalAsPgcCandidate,
  verifyShadowParamsProposalAnchor,
} from '@proj-aijade/memory-biomimetic'

import * as schema from '../../schemas/memory-v9'

export type PromotionStage = 'integrity_gate' | 'evidence_gate' | 'pgc_gate' | 'promoted'

export interface V9PromotionResult {
  ok: boolean
  /** Which gate rejected the promotion (absent on success). */
  stage?: PromotionStage
  /** Human-readable refusal reason (absent on success). */
  reason?: string
  evolutionSpecId?: string
  evalReportId?: string
}

export interface V9PromotionService {
  process: (job: V9PromotionJob) => Promise<V9PromotionResult>
}

export function createV9PromotionService(deps: { db: Database }): V9PromotionService {
  const { db } = deps

  return {
    async process(job: V9PromotionJob): Promise<V9PromotionResult> {
      const {
        proposalId,
        sessionId,
        traceId,
        tick,
        inputHash,
        evaluationPack,
        proposal,
        candidateVersion,
        pgcV6State,
      } = job.input

      // ---- Door 0: re-verify the proposal's integrity anchor --------------
      // Why this gate has to be redone here rather than trusted from reduction:
      // `proposal` arrives as JSON deserialised out of the Redis queue. Checking it
      // once during reduction says nothing about the copy in the queue - trusting the
      // deserialised object means "whatever is in the queue gets promoted". We
      // recompute input_hash from the proposal's own fields and compare.
      //
      // This also closes a real asymmetry: the `evidence` branch of the reducer has no
      // producer-declared input_hash to compare against (the v10 contract has no such
      // field on that topic), so its hash is *derived* and therefore trivially
      // self-consistent. It is only here, at the point of acting on the proposal, that
      // the anchor becomes an actual check - and it covers both branches.
      const anchor = verifyShadowParamsProposalAnchor(proposal)
      if (!anchor.ok) {
        return { ok: false, stage: 'integrity_gate', reason: anchor.reason }
      }

      // The job header and the proposal body must describe the same input snapshot.
      if (inputHash !== proposal.inputHash) {
        return {
          ok: false,
          stage: 'integrity_gate',
          reason: `job inputHash disagrees with proposal: job=${inputHash} proposal=${proposal.inputHash}`,
        }
      }

      // ---- Door 1: EvidenceGate -------------------------------------------
      const evidenceGate = canPromote(evaluationPack)
      if (!evidenceGate.ok) {
        return { ok: false, stage: 'evidence_gate', reason: evidenceGate.reason }
      }

      // ---- Door 2: PGC write gate ----------------------------------------
      // The reduced proposal becomes a PGC candidate write; the v6 endogenous
      // state (if supplied) drives the commit verdict. We use the NEUTRAL
      // policy for the evidence-sufficiency sub-check so that the decisive gate
      // is the v6 `commit_possible` verdict (which always uses DEFAULT_PGC_V6_POLICY
      // internally), not a counting threshold.
      const candidate = shadowProposalAsPgcCandidate(proposal)
      const decision = decidePgc({
        session_id: sessionId,
        trace_id: traceId,
        candidate_memory_writes: [candidate],
        pgc_read_context: {
          now: Date.now(),
          last_n_events: [],
          pgc_v6_state: pgcV6State,
        },
        pgc_policy_version: NEUTRAL_PGC_POLICY.version,
      })
      const entry = decision.write_plan[0]
      const v6 = entry?.pgc_state_snapshot.v6
      const commitPossible = v6 ? v6.commit_possible : entry?.decision === 'commit'
      const commitReason = v6?.commit_reason ?? entry?.decision ?? 'unknown'
      if (!commitPossible) {
        return { ok: false, stage: 'pgc_gate', reason: `pgc commit rejected: ${commitReason}` }
      }

      // ---- Optional candidate version selection (metadata only) ----------
      // v8 §51.4: pick the best feasible candidate version. With a single
      // supplied candidate this validates feasibility and records the winner's
      // id; it is NOT a third gate — the two gates above are authoritative.
      const selected = candidateVersion ? selectCandidateVersion([candidateVersion]) : null

      // ---- Success: persist exactly two rows, no fabricated evidence ------
      const evolutionSpecId = `evospec_${proposalId}`
      const evalReportId = `evalrep_${proposalId}`
      const gates = gateSummary(evaluationPack)
      const pgcSummary = { commit_possible: true, commit_reason: commitReason }

      await db.insert(schema.v9EvolutionSpecs).values({
        id: evolutionSpecId,
        name: `shadow-promotion:${proposalId}`,
        spec: {
          proposalId,
          sessionId,
          traceId,
          tick,
          inputHash,
          proposal: proposal as ShadowParamsProposal,
          candidateVersion: candidateVersion ?? null,
          selectedCandidateVersionId: selected?.id ?? null,
          gates,
          pgc: pgcSummary,
        } satisfies Record<string, unknown>,
        createdAt: new Date(),
      })

      await db.insert(schema.v9EvalReports).values({
        id: evalReportId,
        name: `shadow-eval:${proposalId}`,
        metric: { gates, pgc: pgcSummary } satisfies Record<string, unknown>,
        result: { promoted: true, evolutionSpecId, evalReportId } satisfies Record<string, unknown>,
        createdAt: new Date(),
      })

      return {
        ok: true,
        stage: 'promoted',
        reason: 'promoted',
        evolutionSpecId,
        evalReportId,
      }
    },
  }
}

function gateSummary(pack: EvaluationEvidencePack) {
  return {
    unitContractPropertyTests: pack.unitContractPropertyTests.passed,
    staticAnalysis: pack.staticAnalysis?.passed ?? null,
    dependencyLicenseScan: pack.dependencyLicenseScan?.passed ?? null,
    securitySandbox: pack.securitySandbox?.passed ?? null,
    historicalReplay: pack.historicalReplay?.passed ?? null,
    adversarialEval: pack.adversarialEval?.passed ?? null,
  }
}
