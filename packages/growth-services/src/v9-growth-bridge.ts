import type {
  V9CausalRuntime,
  V9RuntimeResult,
} from '@proj-aijade/memory-biomimetic'

import type {
  GrowthLoop,
  GrowthLoopSummary,
  RunOnceInput,
} from './growth-loop'

export interface GrowthV9Input extends RunOnceInput {
  eventId: string
  sessionId: string
  traceId: string
  correlationId?: string
  originDevice: string
  privacyLevel: 0 | 1 | 2 | 3
  riskScore: number
}

/**
 * Product-layer bridge: a completed GrowthLoop is admitted through the same
 * evidence/PGC/MemoryTx gate as perception data instead of writing a parallel
 * growth-only memory record.
 */
export async function runGrowthThroughV9(
  loop: GrowthLoop,
  runtime: V9CausalRuntime,
  input: GrowthV9Input,
): Promise<{ summary: GrowthLoopSummary, runtime?: V9RuntimeResult }> {
  const summary = await loop.runOnce(input)
  if (summary.skipped)
    return { summary }

  const content = JSON.stringify({
    subject: input.subject,
    researchQuestion: input.researchQuestion,
    sourceCount: summary.sourceCount,
    claimMapId: summary.claimMapId,
    artifactId: summary.artifactId,
    journalId: summary.journalId,
  })
  const result = await runtime.processPerception({
    eventId: input.eventId,
    sessionId: input.sessionId,
    traceId: input.traceId,
    correlationId: input.correlationId ?? input.traceId,
    timestamp: Date.now(),
    originDevice: input.originDevice,
    privacyLevel: input.privacyLevel,
    riskScore: input.riskScore,
    source: 'growth-loop',
    content,
    riskLevel: input.riskScore >= 0.7 ? 'high' : input.riskScore >= 0.35 ? 'medium' : 'low',
  })
  return { summary, runtime: result }
}
