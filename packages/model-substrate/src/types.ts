/**
 * L0 model substrate — core types.
 *
 * ## Why this package exists
 *
 * The previous architecture's single most damaging defect (blocker B2) was that
 * its Ollama client sent **no sampling options at all**. The server therefore
 * used its own defaults (temperature≈0.8), so two runs with the same nominal
 * `--seed` produced different results. Every number it produced was
 * unreproducible, which makes it unpublishable.
 *
 * This package makes that class of mistake difficult to commit:
 *
 * 1. **Sampling is mandatory.** There is no code path that talks to a model
 *    without an explicit, fully-specified `SamplingConfig`. Partial configs are
 *    rejected, not silently defaulted.
 * 2. **Every result carries a fingerprint** sufficient to reproduce it:
 *    model tag + digest + every sampling parameter + server version.
 * 3. **Research mode is a guardrail**, not a suggestion. In `research` mode the
 *    substrate refuses to run unless decoding is actually deterministic
 *    (`temperature === 0`).
 * 4. **Determinism is measured, not assumed.** Greedy decoding on llama.cpp is
 *    usually* bit-exact but is not guaranteed (batch scheduling and
 *    floating-point reduction order can vary). `measureDeterminism` gives you
 *    the empirical answer instead of a hope.
 */

/** How the substrate is being used. */
export type SubstrateMode
  /** Production / interactive use. Any sampling is allowed. */
  = | 'interactive'
  /** Experiments. Deterministic decoding is enforced. */
    | 'research'

/**
 * Fully specified decoding parameters.
 *
 * Every field is required. This is deliberate: an omitted parameter means "use
 * whatever the server defaults to", which silently breaks reproducibility when
 * the server is upgraded or a different model tag is resolved.
 *
 * `think` covers reasoning models (Qwen3.x / Qwythos): when true the model
 * emits a separate `thinking` trace and may leave `content` empty until the
 * trace finishes. It is a decoding parameter, so it is part of the fingerprint
 * — a run with thinking on is a different run from one with it off.
 */
export interface SamplingConfig {
  temperature: number
  seed: number
  top_p: number
  top_k: number
  repeat_penalty: number
  /** Context window actually requested. */
  num_ctx: number
  /** Upper bound on generated tokens. */
  num_predict: number
  /** Reasoning-model thinking toggle. Must be explicit — affects output & cost. */
  think: boolean
}

/**
 * What the server says the model is.
 *
 * `digest` matters more than `tag`: a tag such as `latest` is mutable, but the
 * digest pins the exact weights.
 */
export interface ModelIdentity {
  tag: string
  digest?: string
  /** Weight file size in bytes, when reported. Changes if weights change. */
  sizeBytes?: number
  family?: string
  parameterSize?: string
  quantization?: string
}

/** Everything needed to reproduce a run. Emitted with every result. */
export interface RunFingerprint {
  /** Schema version of this fingerprint, so old artifacts stay interpretable. */
  schema: string
  mode: SubstrateMode
  model: ModelIdentity
  sampling: SamplingConfig
  /** Order-independent hash of `sampling`. */
  samplingHash: string
  /** Ollama server version, when discoverable. */
  serverVersion?: string
  /** Short stable id covering model + sampling + server. */
  fingerprint: string
}

export type ChatRole = 'system' | 'user' | 'assistant'

export interface ChatMessage {
  role: ChatRole
  content: string
}

export interface GenerateOptions {
  messages: ChatMessage[]
  /**
   * Per-call sampling override. Must be a *complete* config — partial overrides
   * are rejected, because a partial override means the non-overridden fields
   * come from somewhere the reader cannot see.
   */
  sampling?: SamplingConfig
  /** Ask the server to constrain output to JSON. */
  json?: boolean
}

export interface GenerateResult {
  text: string
  /** The exact config used, after enforcement. Write this into artifacts. */
  fingerprint: RunFingerprint
  /** Server-reported model name. */
  model: string
  createdAt: string
  totalDurationNs?: number
  evalCount?: number
  promptEvalCount?: number
}

export interface Substrate {
  /** Resolve and cache the model's identity (including digest). */
  identity: () => Promise<ModelIdentity>
  /** Full fingerprint for the next call. */
  fingerprint: (sampling?: SamplingConfig) => Promise<RunFingerprint>
  generate: (options: GenerateOptions) => Promise<GenerateResult>
}

/** Thrown when a request would silently be non-reproducible. */
export class SamplingError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'SamplingError'
  }
}
