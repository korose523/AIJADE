/**
 * `@proj-aijade/research-harness` — RQ-C 2x2 experiment harness.
 *
 * Public surface: the backends, the experiment runner, the statistics, and the CLI
 * entrypoint (see `cli.ts` for the command-line interface).
 */

export type {
  CandidateGenerator,
  LLMBackend,
  MockBackendOptions,
  OllamaBackendOptions,
  SelfVerifier,
  SelfVerifierVerdict,
} from './backends'
export { createMockBackend, createOllamaBackend } from './backends'

export type {
  CellPrecision,
  Condition,
  ConditionResult,
  ExperimentResult,
  RunOptions,
  StepRecord,
} from './harness'
export {
  conditionId,
  CONDITIONS,
  runExperiment,
} from './harness'

export {
  bcaBootstrapCI,
  bootstrapCI,
  bootstrapPooledPrecision,
  chiSquare2x2,
  cohensH,
  cramersV,
  differenceInDifferences,
  erf,
  holmBonferroni,
  logOddsInteraction,
  mcnemarExactOrChi,
  minDetectableEffectProportion,
  mulberry32,
  normalCdf,
  normalQuantile,
  normalSf,
  oddsRatio,
  pooledDifferenceInDifferences,
  pooledPrecision,
  powerForEffectProportion,
  riskDifference,
  riskDifferenceCI,
  twoSidedNormalP,
} from './stats'
export type {
  ChiSquareResult,
  CI,
  DiDResult,
  HolmStep,
  LogOddsInteractionResult,
  McNemarResult,
  RiskDifferenceCI,
  SkillCount,
} from './stats'
