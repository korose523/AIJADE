import type { PgcStateRow, V9RuntimeArtifact, V9RuntimeStore } from '@proj-aijade/memory-biomimetic'

import type { Database } from '../../libs/db'

import { desc, eq } from 'drizzle-orm'

import * as schema from '../../schemas/memory-v9'

/**
 * Durable adapter for the kernel runtime. The artifact is persisted as one
 * database transaction; a failure rolls back every stage of the causal chain.
 */
export function createV9RuntimeStore(db: Database): V9RuntimeStore {
  return {
    async readLatestPgcState(sessionId) {
      const [row] = await db.select()
        .from(schema.v9PgcStates)
        .where(eq(schema.v9PgcStates.sessionId, sessionId))
        .orderBy(desc(schema.v9PgcStates.createdAt))
        .limit(1)
      if (!row)
        return undefined
      return {
        id: row.id,
        sessionId: row.sessionId,
        traceId: row.traceId,
        policyVersion: row.policyVersion,
        components: row.components as PgcStateRow['components'],
        v6State: row.v6State as PgcStateRow['v6State'],
        createdAt: row.createdAt.getTime(),
      }
    },
    async persist(artifact: V9RuntimeArtifact) {
      if (artifact.memoryTx.status !== 'committed' && artifact.memoryVersions.length > 0)
        throw new Error('v9 runtime invariant violated: non-committed transaction has versions')
      const [existingTx] = await db.select({ id: schema.v9MemoryTxs.id })
        .from(schema.v9MemoryTxs)
        .where(eq(schema.v9MemoryTxs.id, artifact.memoryTx.id))
        .limit(1)
      if (existingTx)
        return

      await db.transaction(async (tx) => {
        await tx.insert(schema.v9EvidencePacks).values({
          id: artifact.evidencePack.id,
          sessionId: artifact.evidencePack.sessionId,
          source: artifact.evidencePack.source,
          createdAt: new Date(artifact.evidencePack.createdAt),
          note: artifact.evidencePack.note,
        })
        await tx.insert(schema.v9EvidenceChunks).values({
          id: artifact.evidenceChunk.id,
          packId: artifact.evidenceChunk.packId,
          idx: String(artifact.evidenceChunk.idx),
          content: artifact.evidenceChunk.content,
          createdAt: new Date(artifact.evidenceChunk.createdAt),
        })
        await tx.insert(schema.v9PgcStates).values({
          id: artifact.pgcState.id,
          sessionId: artifact.pgcState.sessionId,
          traceId: artifact.pgcState.traceId,
          policyVersion: artifact.pgcState.policyVersion,
          components: artifact.pgcState.components,
          v6State: artifact.pgcState.v6State,
          createdAt: new Date(artifact.pgcState.createdAt),
        })
        await tx.insert(schema.v9PgcWritePlans).values({
          id: artifact.pgcWritePlan.id,
          pgcStateId: artifact.pgcWritePlan.pgcStateId,
          sessionId: artifact.pgcWritePlan.sessionId,
          traceId: artifact.pgcWritePlan.traceId,
          policyVersion: artifact.pgcWritePlan.policyVersion,
          writePlan: artifact.pgcWritePlan.writePlan,
          contradictionReport: artifact.pgcWritePlan.contradictionReport,
          createdAt: new Date(artifact.pgcWritePlan.createdAt),
        })
        await tx.insert(schema.v9MemoryTxs).values({
          id: artifact.memoryTx.id,
          sessionId: artifact.memoryTx.sessionId,
          traceId: artifact.memoryTx.traceId,
          atomicity: artifact.memoryTx.atomicity,
          maxWrites: String(artifact.memoryTx.maxWrites),
          status: artifact.memoryTx.status,
          createdAt: new Date(artifact.memoryTx.createdAt),
        })
        if (artifact.memoryVersions.length > 0) {
          await tx.insert(schema.v9MemoryVersions).values(artifact.memoryVersions.map(version => ({
            id: version.id,
            memoryTxId: version.memoryTxId,
            memoryItemId: version.memoryItemId,
            memoryWriteId: version.memoryWriteId,
            memoryKind: version.memoryKind,
            contentHashSha256: version.contentHashSha256,
            evidencePackId: version.evidencePackId,
            evidenceIds: version.evidenceIds,
            pgcStateId: version.pgcStateId,
            intensity: String(version.intensity),
            durability: String(version.durability),
            riskLevel: version.riskLevel,
            createdAt: new Date(version.createdAt),
          })))
        }
        await tx.insert(schema.v9EvidenceWeaves).values({
          id: artifact.evidenceWeave.id,
          txId: artifact.evidenceWeave.txId,
          graphHash: artifact.evidenceWeave.graphHash,
          spec: artifact.evidenceWeave.spec,
          links: artifact.evidenceWeave.links,
          createdAt: new Date(artifact.evidenceWeave.createdAt),
        })
        if (artifact.events.length > 0) {
          const eventIds = new Set<string>()
          await tx.insert(schema.v9Events).values(artifact.events.map((event, index) => {
            const baseId = event.event_id
            let eventId = baseId
            let suffix = 1
            while (eventIds.has(eventId)) {
              eventId = `${baseId}:${index}:${suffix++}`
            }
            eventIds.add(eventId)
            return {
              id: eventId,
              eventId,
              traceId: event.trace_id,
              correlationId: event.correlation_id,
              timestamp: new Date(event.timestamp),
              producer: event.producer,
              // 观察/传输上下文**来自内核信封**，不在这里合成。
              //
              // 这里原本写死 `originDevice: 'v9-runtime'`、`privacyLevel: 1`、`evidenceRefs: []`、
              // 并用 `risk_level` 的 3 级带宽反推 `riskScore`（high→1 / medium→0.5 / low→0）。
              // 后果是**真实信息在落库时被丢弃并替换成近似值**：运行时的真实设备名没了，
              // 连续的 riskScore（例如 0.42）被压回 0/0.5/1。这正是 v10 §14.1 禁止清单里
              // 「伪造因果关键字段」的同型问题。内核现在把 13 个信封字段全部给出，落库直接采用。
              originDevice: event.origin_device,
              privacyLevel: event.privacy_level,
              evidenceRefs: event.evidence_refs,
              causalContextRefs: event.causal_context_refs,
              riskScore: event.risk_score,
              topic: event.topic,
              payload: event.payload,
              idempotencyKey: event.idempotency_key,
              replayMode: event.replay_mode,
              riskLevel: event.risk_level,
            }
          }))
        }
      })
    },
  }
}
