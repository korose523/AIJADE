import type { SourceRecord } from '@proj-aijade/memory-biomimetic'

import { validateKnowledgeArtifact } from '@proj-aijade/memory-biomimetic'
import { describe, expect, it } from 'vitest'

import { InMemoryStorage } from './in-memory'
import { SynthesisWorkbench } from './synthesis-workbench'
import { FixedScheduler } from './test-helpers'

const SRC: SourceRecord = {
  id: 'src-1',
  schema: 'aijade.source_record@1',
  locator: 'https://example.com/1',
  sourceType: 'web',
  quality: { reliability: 0.7, independence: 0.8, directness: 0.6, recency: 0.7, reproducibility: 0.6 },
  upstreamRefs: [],
  contentHash: 'h_1',
  fetchedAt: 1_700_000_000_000,
}

function makeService() {
  return new SynthesisWorkbench(
    { storage: new InMemoryStorage(), scheduler: new FixedScheduler(1_700_000_000_000) },
    'agent-1',
    'scope-1',
  )
}

describe('synthesisWorkbench', () => {
  it('emits a KnowledgeArtifact that passes validateKnowledgeArtifact', async () => {
    const svc = makeService()
    const artifact = await svc.synthesize({
      questRef: 'q-1',
      kind: 'learning_note',
      payload: { summary: 'birds migrate' },
      sourceRecords: [SRC],
    })
    expect(validateKnowledgeArtifact(artifact).ok).toBe(true)
    expect(artifact.sources.length).toBe(1)
    expect(artifact.evidenceGraphRef).toContain('indep=1')
  })

  it('refuses to synthesise with no sources (boundary: §6)', async () => {
    const svc = makeService()
    await expect(
      svc.synthesize({ questRef: 'q-1', kind: 'learning_note', payload: {}, sourceRecords: [] }),
    ).rejects.toThrow(/requires ≥1 source/)
  })
})
