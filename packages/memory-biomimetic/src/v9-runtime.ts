/**
 * Production-neutral v9 write runtime.
 *
 * This is the single executable path for the causal core:
 * perception evidence -> PGC state transition -> write plan -> MemoryTx ->
 * EvidenceWeave.  Storage is deliberately a port so the research kernel stays
 * independent of Drizzle, browser storage, and any particular deployment.
 */

import type { AijadeEvent, RiskLevel } from './events'
import type { MemoryPayload, MemoryTxInput, TxResult } from './memory-tx'
import type { StimulusFeature } from './pgc-state'
import type {
  EvidenceChunkRow,
  EvidencePackRow,
  EvidenceWeaveRow,
  MemoryTxRow,
  MemoryVersionRow,
  PgcStateRow,
  PgcWritePlanRow,
} from './v9-schema'

import { MemoryTxEngine } from './memory-tx'
import { buildPgcWritePlanReadyEvent, decidePgc } from './pgc'
import { createPgcStateIntegrator, evaluateStimulus } from './pgc-state'
import { buildEvidenceWeaveCandidateReadyEvent, buildWeave, toWeaveRow } from './weave'

export interface V9PerceptionInput {
  eventId: string
  sessionId: string
  traceId: string
  correlationId: string
  timestamp: number
  originDevice: string
  privacyLevel: 0 | 1 | 2 | 3
  riskScore: number
  source: string
  content: string
  /** A feature vector is evidence, not a hidden heuristic: it is persisted in the state snapshot. */
  stimulusFeatures?: Partial<Record<StimulusFeature, number>>
  riskLevel?: RiskLevel
}

/** Minimal repository required to make the runtime durable. */
export interface V9RuntimeStore {
  readLatestPgcState: (sessionId: string) => Promise<PgcStateRow | undefined>
  persist: (artifact: V9RuntimeArtifact) => Promise<void>
}

/** All rows are exposed together so an adapter can commit them atomically. */
export interface V9RuntimeArtifact {
  evidencePack: EvidencePackRow
  evidenceChunk: EvidenceChunkRow
  pgcState: PgcStateRow
  pgcWritePlan: PgcWritePlanRow
  memoryTx: MemoryTxRow
  memoryVersions: MemoryVersionRow[]
  evidenceWeave: EvidenceWeaveRow
  events: AijadeEvent[]
}

export interface V9RuntimeResult {
  artifact: V9RuntimeArtifact
  tx: TxResult
}

function id(prefix: string, eventId: string): string {
  return `${prefix}_${eventId}`
}

function clampRisk(value: number): number {
  if (!Number.isFinite(value))
    return 1
  return Math.max(0, Math.min(1, value))
}

function deriveStimulus(input: V9PerceptionInput): Partial<Record<StimulusFeature, number>> {
  const lengthSignal = Math.min(1, input.content.length / 800)
  const risk = clampRisk(input.riskScore)
  return {
    stim_arousal_score: lengthSignal,
    uncertainty_load_score: risk,
    stim_drive_score: Math.max(0.15, lengthSignal * 0.5),
    stim_fatigue_score: risk * 0.2,
    ...input.stimulusFeatures,
  }
}

/**
 * Stateful PGC runtime.  One instance may serve many sessions because the
 * previous state is always read from the port before an event is processed.
 */
export class V9CausalRuntime {
  constructor(private readonly store: V9RuntimeStore) {}

  async processPerception(input: V9PerceptionInput): Promise<V9RuntimeResult> {
    if (!input.content.trim())
      throw new Error('v9 perception requires non-empty content')

    const previous = await this.store.readLatestPgcState(input.sessionId)
    const integrator = createPgcStateIntegrator(previous?.v6State)
    const stimulusFeatures = deriveStimulus(input)
    const state = integrator.step(evaluateStimulus(stimulusFeatures))

    const packId = id('ep', input.eventId)
    const chunkId = id('ec', input.eventId)
    const writeId = id('mw', input.eventId)
    const evidencePack: EvidencePackRow = {
      id: packId,
      sessionId: input.sessionId,
      source: input.source,
      createdAt: input.timestamp,
      note: `origin_device=${input.originDevice};privacy=${input.privacyLevel};risk=${clampRisk(input.riskScore)}`,
    }
    const evidenceChunk: EvidenceChunkRow = {
      id: chunkId,
      packId,
      idx: 0,
      content: input.content,
      createdAt: input.timestamp,
    }

    const decision = decidePgc({
      session_id: input.sessionId,
      trace_id: input.traceId,
      pgc_policy_version: 'pgc_policy_v1',
      candidate_memory_writes: [{
        memory_write_id: writeId,
        memory_kind: 'episodic',
        candidate_payload: { content: input.content, source: input.source },
        evidence_ids: [chunkId],
        proposed_intensity: 1,
        salience: { salience: 0.5, socialSalience: 0.2, novelty: 0.5 },
      }],
      pgc_read_context: {
        now: input.timestamp,
        last_n_events: [{ topic: 'perception_event' }],
        evidence_records: [{ id: chunkId, reliability: 1, likelihood: 1 }],
        pgc_v6_state: state,
        pgc_v6_stimulus_features: stimulusFeatures,
      },
    })

    const stateId = decision.write_plan[0]!.pgc_state_snapshot.pgc_state_id
    const pgcState: PgcStateRow = {
      id: stateId,
      sessionId: input.sessionId,
      traceId: input.traceId,
      policyVersion: 'pgc_policy_v1',
      components: decision.write_plan[0]!.pgc_state_snapshot.components,
      v6State: state,
      createdAt: input.timestamp,
    }
    const pgcWritePlan: PgcWritePlanRow = {
      id: id('pwp', input.eventId),
      pgcStateId: stateId,
      sessionId: input.sessionId,
      traceId: input.traceId,
      policyVersion: 'pgc_policy_v1',
      writePlan: decision.write_plan.map(entry => ({
        memoryWriteId: entry.memory_write_id,
        decision: entry.decision,
        finalIntensity: entry.final_intensity,
        reasonCodes: entry.reason_codes,
        expectedTests: entry.expected_tests,
        pgcStateId: entry.pgc_state_snapshot.pgc_state_id,
      })),
      contradictionReport: {
        conflictingEvidenceIds: decision.contradiction_report.conflicting_evidence_ids,
        severity: decision.contradiction_report.severity,
      },
      createdAt: input.timestamp,
    }

    const payload: MemoryPayload = {
      memory_write_id: writeId,
      normalized_payload: {
        memory_kind: 'episodic',
        content_object: { content: input.content, source: input.source },
        embedding_input_text: input.content,
        attributes: {
          tags: ['perception', input.source],
          source_claim_ids: [],
          risk_level: input.riskLevel ?? (input.riskScore >= 0.7 ? 'high' : input.riskScore >= 0.35 ? 'medium' : 'low'),
          salience: { salience: 0.5, socialSalience: 0.2, novelty: 0.5 },
        },
      },
      evidence_pack_id: packId,
      evidence_ids: [chunkId],
      provenance: { source: input.source, actor: input.originDevice },
    }
    const txInput: MemoryTxInput = {
      session_id: input.sessionId,
      trace_id: input.traceId,
      tx_id: id('tx', input.eventId),
      pgc_write_plan: decision.write_plan,
      memory_payloads: [payload],
      tx_policy: { atomicity: 'per_write', max_writes: 1 },
    }
    const engine = new MemoryTxEngine()
    const tx = engine.commit(txInput)
    const weave = buildWeave(engine, tx.tx_id, { include_pgc_snapshot: true, include_claim_ids: true })

    const envelope = {
      event_id: id('evt', input.eventId),
      trace_id: input.traceId,
      correlation_id: input.correlationId,
      timestamp: input.timestamp,
      producer: 'v9-causal-runtime',
      idempotency_key: id('runtime', input.eventId),
      replay_mode: 'live' as const,
      risk_level: payload.normalized_payload.attributes.risk_level ?? 'low',
    }
    const artifact: V9RuntimeArtifact = {
      evidencePack,
      evidenceChunk,
      pgcState,
      pgcWritePlan,
      memoryTx: engine.toMemoryTxRow(txInput, tx),
      memoryVersions: engine.getVersionsForTx(tx.tx_id),
      evidenceWeave: toWeaveRow(weave, input.timestamp),
      events: [
        buildPgcWritePlanReadyEvent(decision, { ...envelope, idempotency_key: `${envelope.idempotency_key}:pgc` }),
        ...tx.events,
        buildEvidenceWeaveCandidateReadyEvent(weave, { ...envelope, idempotency_key: `${envelope.idempotency_key}:weave` }),
      ],
    }
    await this.store.persist(artifact)
    return { artifact, tx }
  }
}
