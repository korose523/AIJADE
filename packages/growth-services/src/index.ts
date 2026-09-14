/**
 * `@proj-aijade/growth-services` — single import surface.
 *
 * Re-exports the twelve product-layer services, the port interfaces, the in-memory
 * / stub adapters, the orchestrator, and the §53.2 growth contracts + validators
 * from the `@proj-aijade/memory-biomimetic` research kernel (so consumers can
 * import everything from one place).
 */

export * from './adapters'
export * from './architecture-critic'
// --- pilot / benchmark / metrics (evaluation formalism + synthetic benchmark) ---
export * from './benchmark'
export * from './epistemic-verifier'
export * from './evolution-lab'
export * from './growth-loop'
export * from './in-memory'
export * from './interest-service'
export * from './knowledge-acquirer'
export * from './life-journal'
export * from './metrics'
export * from './performance-director'
export * from './pilot'
// --- local modules ---------------------------------------------------------
export * from './ports'
export * from './quest-planner'
export * from './sharing-policy'
export * from './synthesis-workbench'

export * from './transfer-lab'
export * from './trusted-release-controller'
export * from './util'

// --- §53.2 growth contract types (from the research kernel) -----------------
export type {
  AssociationPath,
  ClaimMap,
  ContractSource,
  EvaluationEvidencePack,
  EvolutionProposal,
  // shared v7 contracts referenced by the growth loop
  ExperimentManifest,
  InterestThread,
  KnowledgeArtifact,
  LearningQuest,
  LifeJournalEntry,
  PerformanceIntent,
  ShareCandidate,
  SignedRelease,
  SourceRecord,
  TransferRecord,
} from '@proj-aijade/memory-biomimetic'

// --- §53.2 growth contract validators + a few helpers -----------------------
export {
  validateAssociationPath,
  validateClaimMap,
  validateEvaluationEvidencePack,
  validateEvolutionProposal,
  validateExperimentManifest,
  validateInterestThread,
  validateKnowledgeArtifact,
  validateLearningQuest,
  validateLifeJournalEntry,
  validatePerformanceIntent,
  validateShareCandidate,
  validateSignedRelease,
  validateSourceRecord,
  validateTransferRecord,
} from '@proj-aijade/memory-biomimetic'
