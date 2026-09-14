export {
  createOllamaSubstrate,
  QWYTHOS_INTERACTIVE_SAMPLING,
  RESEARCH_SAMPLING,
} from './client'

export type { OllamaSubstrate, OllamaSubstrateOptions } from './client'

export {
  assertCompleteSampling,
  assertResearchMode,
  buildFingerprint,
  FINGERPRINT_SCHEMA,
  fnv1a,
  hashSampling,
  resolveModelIdentity,
  resolveServerVersion,
} from './fingerprint'

export type { ModelIdentity as FingerprintModelIdentity } from './types'

export type {
  ChatMessage,
  ChatRole,
  GenerateOptions,
  GenerateResult,
  ModelIdentity,
  RunFingerprint,
  SamplingConfig,
  Substrate,
  SubstrateMode,
} from './types'

export { SamplingError } from './types'

export {
  assertDeterminism,
  hashText,
  measureDeterminism,
} from './verify'

export type { DeterminismOptions, DeterminismReport, DeterminismRun } from './verify'
