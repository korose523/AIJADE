export { createDiscourseMemory, type DiscourseMemory, type DiscourseMemoryOptions } from './discourse-memory'
export {
  DEFAULT_DYNAMICS,
  type DriftConfig,
  fingerprintDynamics,
  type HormoneName,
  type HormoneReaction,
  type IntimacyName,
  type IntimacyReaction,
  type IntimacyRelaxation,
  type PersonaDynamicsConfig,
  type Relaxation,
  resolveDynamics,
  type TraitName,
  type TraitReaction,
} from './dynamics'
export { type ContinuousLearning, type ContinuousLearningOptions, createContinuousLearning, type PersonaUpdateEvent } from './learning'
export {
  applyInteraction,
  applyIntimacy,
  type BigFive,
  createIntimacyState,
  createPersonaState,
  drift,
  driftIntimacy,
  type EndocrineState,
  type InteractionSignal,
  type IntimacyState,
  type MoodProfile,
  type PADState,
  type PersonaState,
  type PersonaVector,
  setDynamicsRng,
  type ThreeForceState,
  toBigFive,
  toContext,
  toMoodProfile,
  toPAD,
  toThreeForce,
} from './persona'
export { createLexiconSignalExtractor, createLlmSignalExtractor, extractSignal, type SignalExtractor, type SignalExtractorOptions } from './signal'
export {
  createPersonaTelemetryRecorder,
  type PersonaTelemetryOptions,
  type PersonaTelemetryRecorder,
  toPersonaSnapshot,
} from './telemetry'
export * from './types'
