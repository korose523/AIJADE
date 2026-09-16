/**
 * `@proj-aijade/research-telemetry`
 *
 * Turns AIJADE from a product prototype into an instrumented research
 * platform capable of producing publishable experimental data.
 *
 * Minimal usage:
 *
 * ```ts
 * import { startSession, toCsv } from '@proj-aijade/research-telemetry'
 *
 * const session = await startSession({ condition: 'baseline' })
 *
 * await session.recordTurn({
 *   role: 'assistant',
 *   persona: snapshotOf(personaState),   // 13-dim + hormones + PAD + BigFive
 *   latency: { llm: 812, total: 1140 },
 *   tokens: { prompt: 1204, completion: 96 },
 * })
 *
 * console.log(toCsv(await session.getStorage().readTurns(session.sessionId)))
 * ```
 *
 * The three things this unlocks, mapped to the gaps identified in the
 * accompanying feasibility study:
 *
 * - **Longitudinal data** — every record carries `sessionId` + `turnIndex` +
 *   timestamp, so week/month-scale trajectories need no extra bookkeeping.
 * - **Ablation** — `DEFAULT_CONDITIONS` gives one-component-off conditions with
 *   deterministic fingerprints for grouping replicates.
 * - **Parameter sweeps** — `sweepAxis` / `sweepGrid` / `defaultRelaxationSweep`
 *   generate the cells, and `fingerprintParameters` keeps them groupable.
 */

export {
  ABLATION_ENV_KEYS,
  ablationFromEnv,
  DEFAULT_CONDITIONS,
  describeAblation,
  fingerprintConfig,
  resolveCondition,
} from './ablation'
export {
  CSV_COLUMNS,
  flattenRecord,
  summarizeRecords,
  toCsv,
  toJsonl,
} from './export'

export type { SeriesSummary } from './export'
export {
  buildRenderAuditEntry,
  fingerprintAppliedParams,
} from './render-audit'

export {
  ExperimentSessionRunner,
  startSession,
} from './session'
export type {
  RecordTurnInput,
  StartSessionOptions,
} from './session'

export {
  createDefaultStorage,
  createFileStorage,
  createIndexedDbStorage,
  createMemoryStorage,
} from './storage'
export type {
  FileStorageOptions,
  IndexedDbStorageOptions,
  TelemetryStorage,
} from './storage'

export {
  defaultRelaxationSweep,
  fingerprintParameters,
  sweepAxis,
  sweepGrid,
} from './sweep'
export type { SweepAxis, SweepPoint } from './sweep'

export type { AppliedParams, AssetIdentity, RenderAuditEntry } from './types'
export type { AblationCondition } from './types'

export { FULL_ABLATION } from './types'
export type {
  AblationConfig,
  BigFiveSnapshot,
  DynamicsParameters,
  EndocrineSnapshot,
  ExperimentSession,
  IntimacySnapshot,
  LatencyBreakdown,
  PADSnapshot,
  PersonaSnapshot,
  PersonaVectorSnapshot,
  SessionMeta,
  TokenUsage,
  TurnRecord,
  TurnRole,
} from './types'
