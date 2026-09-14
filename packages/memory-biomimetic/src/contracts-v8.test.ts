import type {
  AssociationPath,
  ClaimMap,
  EvaluationEvidencePack,
  EvolutionProposal,
  InterestThread,
  KnowledgeArtifact,
  LearningQuest,
  LifeJournalEntry,
  PerformanceIntent,
  ShareCandidate,
  SignedRelease,
  SourceRecord,
  TransferRecord,
} from './contracts-v8'

import { describe, expect, it } from 'vitest'

import {
  validateAssociationPath,
  validateClaimMap,
  validateEvaluationEvidencePack,
  validateEvolutionProposal,
  validateInterestThread,
  validateKnowledgeArtifact,
  validateLearningQuest,
  validateLifeJournalEntry,
  validatePerformanceIntent,
  validateShareCandidate,
  validateSignedRelease,
  validateSourceRecord,
  validateTransferRecord,
} from './contracts-v8'

const SRC = [{ ref: 'src-1', trusted: true }]

function interest(over: Partial<InterestThread> = {}): InterestThread {
  return {
    id: 'it-1',
    schema: 'aijade.interest_thread@1',
    agentId: 'a1',
    userScope: 'u1',
    subject: 'BCI signal processing',
    originEventIds: ['e-1'],
    motivatingQuestions: ['how to denoise EEG?'],
    intrinsicValue: 0.7,
    identityRelevance: 0.6,
    userRelevance: 0.5,
    noveltyFrontier: 0.8,
    knowledgeGaps: ['artifact removal'],
    currentHypotheses: ['ICA works'],
    progress: 0.3,
    attentionBudget: { allocated: 60, spent: 10, unit: 'minutes' },
    status: 'active',
    lastReflectedAt: 1000,
    ...over,
  }
}

function quest(over: Partial<LearningQuest> = {}): LearningQuest {
  return {
    id: 'lq-1',
    schema: 'aijade.learning_quest@1',
    agentId: 'a1',
    userScope: 'u1',
    interestThreadRef: 'it-1',
    researchQuestion: 'does ICA improve BCI SNR?',
    operationalDefinition: 'compare SNR before/after ICA on dataset X',
    priorBeliefs: ['b-1'],
    expectedInformationGain: 0.5,
    sourcePlan: { questionType: 'technical', sourceTypes: ['paper', 'code'], maxSources: 5 },
    resourceBudget: { allocated: 20, spent: 2, unit: 'queries' },
    privacyClass: 'private',
    stopConditions: ['marginal gain < 0.05'],
    successCriteria: ['SNR delta quantified'],
    deliverables: ['claim_map'],
    experimentManifestRef: 'em-1',
    status: 'active',
    createdAt: 1000,
    ...over,
  }
}

function source(over: Partial<SourceRecord> = {}): SourceRecord {
  return {
    id: 'sr-1',
    schema: 'aijade.source_record@1',
    locator: 'https://example.com/paper',
    sourceType: 'paper',
    quality: { reliability: 0.9, independence: 0.8, directness: 0.7, recency: 0.6, reproducibility: 0.5 },
    upstreamRefs: [],
    contentHash: 'sha256:abc',
    fetchedAt: 1000,
    ...over,
  }
}

describe('v8 contracts — InterestThread (#16)', () => {
  it('accepts a valid thread', () => {
    expect(validateInterestThread(interest())).toEqual({ ok: true })
  })
  it('accepts abandoned with reason', () => {
    expect(validateInterestThread(interest({ status: 'abandoned', abandonedReason: 'saturated' }))).toEqual({ ok: true })
  })
  it('rejects empty subject', () => {
    const r = validateInterestThread(interest({ subject: '' }))
    expect(r.ok).toBe(false)
  })
  it('rejects no origin events (no history)', () => {
    const r = validateInterestThread(interest({ originEventIds: [] }))
    expect(r.ok).toBe(false)
  })
  it('rejects out-of-range intrinsic value', () => {
    const r = validateInterestThread(interest({ intrinsicValue: 1.5 }))
    expect(r.ok).toBe(false)
  })
  it('rejects overspent attention budget', () => {
    const r = validateInterestThread(interest({ attentionBudget: { allocated: 10, spent: 20, unit: 'minutes' } }))
    expect(r.ok).toBe(false)
  })
  it('rejects abandoned without reason', () => {
    const r = validateInterestThread(interest({ status: 'abandoned' }))
    expect(r.ok).toBe(false)
  })
  it('rejects invalid status', () => {
    const r = validateInterestThread(interest({ status: 'nope' as any }))
    expect(r.ok).toBe(false)
  })
})

describe('v8 contracts — LearningQuest (#17)', () => {
  it('accepts a valid quest', () => {
    expect(validateLearningQuest(quest())).toEqual({ ok: true })
  })
  it('rejects missing interest thread ref', () => {
    const r = validateLearningQuest(quest({ interestThreadRef: '' }))
    expect(r.ok).toBe(false)
  })
  it('rejects empty research question', () => {
    const r = validateLearningQuest(quest({ researchQuestion: '' }))
    expect(r.ok).toBe(false)
  })
  it('rejects no stop conditions (endless browsing)', () => {
    const r = validateLearningQuest(quest({ stopConditions: [] }))
    expect(r.ok).toBe(false)
  })
  it('rejects overspent resource budget', () => {
    const r = validateLearningQuest(quest({ resourceBudget: { allocated: 5, spent: 9, unit: 'queries' } }))
    expect(r.ok).toBe(false)
  })
  it('rejects missing experiment manifest ref', () => {
    const r = validateLearningQuest(quest({ experimentManifestRef: '' }))
    expect(r.ok).toBe(false)
  })
  it('rejects out-of-range expected info gain', () => {
    const r = validateLearningQuest(quest({ expectedInformationGain: 2 }))
    expect(r.ok).toBe(false)
  })
})

describe('v8 contracts — SourceRecord (#18)', () => {
  it('accepts a valid source', () => {
    expect(validateSourceRecord(source())).toEqual({ ok: true })
  })
  it('rejects empty locator', () => {
    const r = validateSourceRecord(source({ locator: '' }))
    expect(r.ok).toBe(false)
  })
  it('rejects out-of-range quality', () => {
    const r = validateSourceRecord(source({ quality: { reliability: 1.2, independence: 0.5, directness: 0.5, recency: 0.5, reproducibility: 0.5 } }))
    expect(r.ok).toBe(false)
  })
  it('rejects empty content hash', () => {
    const r = validateSourceRecord(source({ contentHash: '' }))
    expect(r.ok).toBe(false)
  })
})

describe('v8 contracts — ClaimMap (#19)', () => {
  function map(over: Partial<ClaimMap> = {}): ClaimMap {
    return {
      id: 'cm-1',
      schema: 'aijade.claim_map@1',
      agentId: 'a1',
      userScope: 'u1',
      questRef: 'lq-1',
      claims: [{ proposition: 'ICA improves SNR', epistemicStatus: 'observed', supportSourceRefs: ['sr-1'], counterSourceRefs: [], confidence: 0.8 }],
      createdAt: 1000,
      ...over,
    }
  }
  it('accepts a valid claim map', () => {
    expect(validateClaimMap(map())).toEqual({ ok: true })
  })
  it('rejects claim without support source (§6)', () => {
    const r = validateClaimMap(map({ claims: [{ proposition: 'x', epistemicStatus: 'observed', supportSourceRefs: [], counterSourceRefs: [], confidence: 0.5 }] }))
    expect(r.ok).toBe(false)
  })
  it('rejects invalid epistemic status', () => {
    const r = validateClaimMap(map({ claims: [{ proposition: 'x', epistemicStatus: 'fact' as any, supportSourceRefs: ['sr-1'], counterSourceRefs: [], confidence: 0.5 }] }))
    expect(r.ok).toBe(false)
  })
  it('rejects out-of-range confidence', () => {
    const r = validateClaimMap(map({ claims: [{ proposition: 'x', epistemicStatus: 'observed', supportSourceRefs: ['sr-1'], counterSourceRefs: [], confidence: 1.4 }] }))
    expect(r.ok).toBe(false)
  })
})

describe('v8 contracts — KnowledgeArtifact (#20)', () => {
  function art(over: Partial<KnowledgeArtifact> = {}): KnowledgeArtifact {
    return {
      id: 'ka-1',
      schema: 'aijade.knowledge_artifact@1',
      agentId: 'a1',
      userScope: 'u1',
      kind: 'claim_map',
      questRef: 'lq-1',
      payload: {},
      evidenceGraphRef: 'eg-1',
      sources: SRC,
      createdAt: 1000,
      ...over,
    }
  }
  it('accepts a valid artefact', () => {
    expect(validateKnowledgeArtifact(art())).toEqual({ ok: true })
  })
  it('rejects invalid kind', () => {
    const r = validateKnowledgeArtifact(art({ kind: 'summary' as any }))
    expect(r.ok).toBe(false)
  })
  it('rejects missing evidence graph ref', () => {
    const r = validateKnowledgeArtifact(art({ evidenceGraphRef: '' }))
    expect(r.ok).toBe(false)
  })
  it('rejects no sources (§6)', () => {
    const r = validateKnowledgeArtifact(art({ sources: [] }))
    expect(r.ok).toBe(false)
  })
})

describe('v8 contracts — AssociationPath (#21)', () => {
  function path(over: Partial<AssociationPath> = {}): AssociationPath {
    return {
      id: 'ap-1',
      schema: 'aijade.association_path@1',
      agentId: 'a1',
      userScope: 'u1',
      fromConcept: 'EEG',
      toConcept: 'ICA',
      kind: 'structural',
      path: ['EEG is multichannel', 'ICA separates channels'],
      score: 0.6,
      evidenceRefs: ['e-1'],
      createdAt: 1000,
      ...over,
    }
  }
  it('accepts a valid association', () => {
    expect(validateAssociationPath(path())).toEqual({ ok: true })
  })
  it('rejects pathless association (no why-path)', () => {
    const r = validateAssociationPath(path({ path: [] }))
    expect(r.ok).toBe(false)
  })
  it('rejects invalid kind', () => {
    const r = validateAssociationPath(path({ kind: 'random' as any }))
    expect(r.ok).toBe(false)
  })
})

describe('v8 contracts — TransferRecord (#22)', () => {
  function rec(over: Partial<TransferRecord> = {}): TransferRecord {
    return {
      id: 'tr-1',
      schema: 'aijade.transfer_record@1',
      agentId: 'a1',
      userScope: 'u1',
      sourceDomain: 'EEG',
      targetDomain: 'ECG',
      invariantsPreserved: ['channel independence'],
      brokenConditions: [],
      predictedOutcome: 'works',
      measuredOutcome: 'works',
      negativeTransferSignal: 0.1,
      tier: 'T2',
      validated: true,
      createdAt: 1000,
      ...over,
    }
  }
  it('accepts a validated T2 transfer', () => {
    expect(validateTransferRecord(rec())).toEqual({ ok: true })
  })
  it('rejects unvalidated T2+ transfer', () => {
    const r = validateTransferRecord(rec({ tier: 'T3', validated: false }))
    expect(r.ok).toBe(false)
  })
  it('accepts unvalidated T1 transfer', () => {
    expect(validateTransferRecord(rec({ tier: 'T1', validated: false }))).toEqual({ ok: true })
  })
  it('rejects invalid tier', () => {
    const r = validateTransferRecord(rec({ tier: 'T9' as any }))
    expect(r.ok).toBe(false)
  })
})

describe('v8 contracts — LifeJournalEntry (#23)', () => {
  function entry(over: Partial<LifeJournalEntry> = {}): LifeJournalEntry {
    return {
      id: 'lj-1',
      schema: 'aijade.life_journal_entry@1',
      agentId: 'a1',
      userScope: 'u1',
      date: '2026-09-10',
      experiencedEvents: ['e-1'],
      activeInterests: ['it-1'],
      learnedClaims: ['cm-1'],
      changedBeliefs: [],
      practicedSkills: [],
      unresolvedQuestions: ['q-1'],
      identityReflections: ['grew curious about BCI'],
      sharePolicy: 'diary_only',
      evidenceRefs: ['e-1'],
      createdAt: 1000,
      ...over,
    }
  }
  it('accepts a valid entry', () => {
    expect(validateLifeJournalEntry(entry())).toEqual({ ok: true })
  })
  it('rejects non-ISO date', () => {
    const r = validateLifeJournalEntry(entry({ date: 'Sep 10' }))
    expect(r.ok).toBe(false)
  })
  it('rejects invalid share policy', () => {
    const r = validateLifeJournalEntry(entry({ sharePolicy: 'public' as any }))
    expect(r.ok).toBe(false)
  })
})

describe('v8 contracts — ShareCandidate (#24)', () => {
  function cand(over: Partial<ShareCandidate> = {}): ShareCandidate {
    return {
      id: 'sc-1',
      schema: 'aijade.share_candidate@1',
      agentId: 'a1',
      userScope: 'u1',
      contentRef: 'lj-1',
      utility: { relevance: 0.7, novelty: 0.6, relationalValue: 0.5, timeliness: 0.4, uncertainty: 0.2, interruption: 0.3, privacyRisk: 0.1, repetition: 0.2 },
      score: 0.5,
      channel: 'light_hint',
      decidedAt: 1000,
      ...over,
    }
  }
  it('accepts a valid candidate', () => {
    expect(validateShareCandidate(cand())).toEqual({ ok: true })
  })
  it('rejects invalid channel', () => {
    const r = validateShareCandidate(cand({ channel: 'broadcast' as any }))
    expect(r.ok).toBe(false)
  })
  it('rejects out-of-range utility', () => {
    const r = validateShareCandidate(cand({ utility: { relevance: 1.3, novelty: 0.5, relationalValue: 0.5, timeliness: 0.5, uncertainty: 0.5, interruption: 0.5, privacyRisk: 0.5, repetition: 0.5 } }))
    expect(r.ok).toBe(false)
  })
})

describe('v8 contracts — EvolutionProposal (#25)', () => {
  function prop(over: Partial<EvolutionProposal> = {}): EvolutionProposal {
    return {
      id: 'ep-1',
      schema: 'aijade.evolution_proposal@1',
      agentId: 'a1',
      triggerEvidence: ['t-1'],
      affectedComponents: ['retrieval'],
      grade: 'E2',
      baselineVersion: '1.0.0',
      changeSpec: 'switch reranker',
      sourceDiff: 'diff-1',
      generatedBy: 'evolution-lab',
      tests: [{ kind: 'unit', passed: true }],
      rollbackPlan: 'revert to 1.0.0',
      approvalPolicy: 'sandbox+sign',
      signature: 'sig-1',
      createdAt: 1000,
      ...over,
    }
  }
  it('accepts a valid proposal', () => {
    expect(validateEvolutionProposal(prop())).toEqual({ ok: true })
  })
  it('rejects missing rollback plan', () => {
    const r = validateEvolutionProposal(prop({ rollbackPlan: '' }))
    expect(r.ok).toBe(false)
  })
  it('rejects no tests', () => {
    const r = validateEvolutionProposal(prop({ tests: [] }))
    expect(r.ok).toBe(false)
  })
  it('rejects missing signature', () => {
    const r = validateEvolutionProposal(prop({ signature: '' }))
    expect(r.ok).toBe(false)
  })
  it('rejects invalid grade', () => {
    const r = validateEvolutionProposal(prop({ grade: 'E9' as any }))
    expect(r.ok).toBe(false)
  })
})

describe('v8 contracts — EvaluationEvidencePack (#26)', () => {
  function pack(over: Partial<EvaluationEvidencePack> = {}): EvaluationEvidencePack {
    return {
      id: 'eep-1',
      schema: 'aijade.evaluation_evidence_pack@1',
      proposalRef: 'ep-1',
      unitContractPropertyTests: { passed: true, total: 10, failed: 0 },
      createdAt: 1000,
      ...over,
    }
  }
  it('accepts a valid pack', () => {
    expect(validateEvaluationEvidencePack(pack())).toEqual({ ok: true })
  })
  it('rejects pass-with-failures contradiction', () => {
    const r = validateEvaluationEvidencePack(pack({ unitContractPropertyTests: { passed: true, total: 10, failed: 2 } }))
    expect(r.ok).toBe(false)
  })
  it('rejects failed exceeding total', () => {
    const r = validateEvaluationEvidencePack(pack({ unitContractPropertyTests: { passed: false, total: 5, failed: 9 } }))
    expect(r.ok).toBe(false)
  })
})

describe('v8 contracts — SignedRelease (#27)', () => {
  function rel(over: Partial<SignedRelease> = {}): SignedRelease {
    return {
      id: 'srl-1',
      schema: 'aijade.signed_release@1',
      version: '1.1.0',
      proposalRef: 'ep-1',
      evidencePackRef: 'eep-1',
      approvedBy: 'user',
      signedAt: 1000,
      signature: 'sig-1',
      canaryRatio: 0.1,
      rollbackAvailable: true,
      ...over,
    }
  }
  it('accepts a valid release', () => {
    expect(validateSignedRelease(rel())).toEqual({ ok: true })
  })
  it('rejects rollback unavailable', () => {
    const r = validateSignedRelease(rel({ rollbackAvailable: false }))
    expect(r.ok).toBe(false)
  })
  it('rejects out-of-range canary ratio', () => {
    const r = validateSignedRelease(rel({ canaryRatio: 1.5 }))
    expect(r.ok).toBe(false)
  })
})

describe('v8 contracts — PerformanceIntent (#28)', () => {
  function intent(over: Partial<PerformanceIntent> = {}): PerformanceIntent {
    return {
      id: 'pi-1',
      schema: 'aijade.performance_intent@1',
      agentId: 'a1',
      userScope: 'u1',
      personaSnapshotRef: 'ps-1',
      timeMarked: 1000,
      expression: { valence: 0.5, arousal: 0.6, dominance: 0.4, intimacy: 0.5, certainty: 0.7, curiosity: 0.8, playfulness: 0.3, reflection: 0.5, urgency: 0.2 },
      duration: 500,
      ...over,
    }
  }
  it('accepts a valid intent', () => {
    expect(validatePerformanceIntent(intent())).toEqual({ ok: true })
  })
  it('rejects missing persona snapshot ref', () => {
    const r = validatePerformanceIntent(intent({ personaSnapshotRef: '' }))
    expect(r.ok).toBe(false)
  })
  it('rejects out-of-range valence', () => {
    const r = validatePerformanceIntent(intent({ expression: { valence: 1.5, arousal: 0.5, dominance: 0.5, intimacy: 0.5, certainty: 0.5, curiosity: 0.5, playfulness: 0.5, reflection: 0.5, urgency: 0.5 } }))
    expect(r.ok).toBe(false)
  })
  it('rejects out-of-range arousal', () => {
    const r = validatePerformanceIntent(intent({ expression: { valence: 0.5, arousal: -0.2, dominance: 0.5, intimacy: 0.5, certainty: 0.5, curiosity: 0.5, playfulness: 0.5, reflection: 0.5, urgency: 0.5 } }))
    expect(r.ok).toBe(false)
  })
})
