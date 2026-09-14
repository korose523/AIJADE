/**
 * `@proj-aijade/skill-forge-store`
 *
 * Drop-in replacement for the in-memory skill registry, built so that RQ-C
 * (skill discovery / self-verification bias) becomes measurable.
 *
 * The three things it adds over `agent-skill-forge`'s `createSkillRegistry`:
 *
 * 1. **Persistence** — JSONL so the library survives a restart and a learning
 *    curve can span sessions.
 * 2. **Outcome accounting** — call / success / failure counters, so *precision*
 *    is computable. Upstream, registration was equated with success, which
 *    makes only a recall-like quantity available.
 * 3. **Retirement** — skills can leave the active set, which is what lets the
 *    library's quality change over time.
 *
 * Minimal usage:
 *
 * ```ts
 * const reg = createSkillRegistry()
 *
 * const s = await reg.create({ name: 'mine_stone', domain: 'game' })
 * await reg.setSelfVerification(s.skillId, 'pass', { score: 0.9, model: 'qwen' })
 * await reg.recordExecution(s.skillId, { ok: false, detail: 'no pickaxe' })
 *
 * const m = await reg.metrics()
 * m.selfVerificationHallucinationRate  // 1.0 — self-passed but failed
 * ```
 */

export {
  assertOracleAvailable,
  createSkillRegistry,
} from './registry'
export type {
  CreateSkillOptions,
  SkillRegistry,
  SkillRegistryOptions,
} from './registry'

export {
  createJsonlSkillStore,
  createMemorySkillStore,
} from './storage'
export type {
  JsonlSkillStoreOptions,
  SkillStore,
} from './storage'

export {
  computeLearningLoopTable,
  computeMetrics,
  computeSelfVerificationDiagnostics,
  computeTwoByTwo,
  hasEnvironmentalOracle,
} from './types'
export type {
  ExecutionOutcome,
  LearningLoopCell,
  SelfVerificationDiagnostic,
  SkillDomain,
  SkillLibraryMetrics,
  SkillLifecycle,
  SkillRecord,
  TwoByTwoCell,
} from './types'
