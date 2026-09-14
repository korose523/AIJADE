import type { ChatCompletion, ChatMessage, ChatRequestOptions, Logger } from '@proj-aijade/agent-llm-client'

/**
 * Platforms a skill may declare (mirrors Hermes Agent's `platforms:` frontmatter).
 * Omit the field for skills that are portable across OSes.
 */
export type SkillPlatform = 'macos' | 'linux' | 'windows'

export interface SkillFrontmatter {
  /** lowercase-hyphenated, <= 64 chars, no spaces. */
  name: string
  /** ONE sentence, <= 60 chars, ends with a period. States the capability. */
  description: string
  /** semver, starts at 0.1.0. */
  version: string
  author: string
  platforms?: SkillPlatform[]
  metadata?: {
    tags?: string[]
    [key: string]: unknown
  }
}

export interface SkillBody {
  /** Human title (H1). */
  title: string
  /** 2-3 sentence intro: what it does, what it does NOT, key dependency stance. */
  intro?: string
  /** Concrete trigger phrases. */
  whenToUse: string[]
  prerequisites?: string[]
  /** Canonical invocation, framed through available tools. */
  howToRun?: string
  /** Flat command/endpoint list. */
  quickReference?: string[]
  /** Numbered steps with copy-paste-exact commands. */
  procedure: string[]
  pitfalls?: string[]
  /** A single check that proves the skill worked. */
  verification?: string
}

/**
 * Optional AIJADE-native executable capability that travels with the skill.
 * Hand-authored skills (via {@link defineSkill}) may attach a `run` function so
 * the skill is not just documentation but an actionable tool.
 */
export interface SkillRunContext {
  input: string
  tools: SkillToolInvoker
  logger: Logger
}

export interface SkillToolInvoker {
  call: (name: string, args: unknown) => Promise<unknown>
}

export interface SkillRunResult {
  ok: boolean
  output: string
}

export interface SkillModule {
  run?: (ctx: SkillRunContext) => Promise<SkillRunResult> | SkillRunResult
  /** Tool names this skill is allowed to invoke. */
  tools?: string[]
}

export type SkillSource = 'hand-authored' | 'llm-generated' | 'evolved'

export interface SkillEvolutionEntry {
  at: number
  feedback: string
  summary: string
  fromVersion: string
  toVersion: string
}

export interface SkillPackage {
  frontmatter: SkillFrontmatter
  body: SkillBody
  /** AIJADE-native executable module (optional; not serializable to SKILL.md). */
  module?: SkillModule
  createdAt: number
  updatedAt: number
  source: SkillSource
  evolutionLog: SkillEvolutionEntry[]
}

/** A lightweight proposal produced by teachable-moment detection. */
export interface SkillDraft {
  proposedName: string
  title: string
  summary: string
  whenToUse: string[]
}

/** Result of running a skill through the validation / sandbox loop. */
export interface SkillValidationResult {
  ok: boolean
  errors: string[]
  warnings: string[]
  /** 0..1 quality score from the structural + LLM self-check. */
  score: number
}

/** A sandbox that executes (or dry-runs) a skill to verify it is sound. */
export interface SkillSandbox {
  (pkg: SkillPackage): Promise<{ ok: boolean, notes: string }>
}

/**
 * The minimal LLM surface the forge needs. {@link OllamaClient} from
 * `@proj-aijade/agent-llm-client` satisfies this structurally.
 */
export interface SkillForgeLLM {
  complete: (messages: ChatMessage[], options?: ChatRequestOptions) => Promise<ChatCompletion>
  jsonComplete: <T = unknown>(
    messages: ChatMessage[],
    options?: ChatRequestOptions & { schema?: import('@proj-aijade/agent-llm-client').ZodSchemaLike<T> },
  ) => Promise<T>
}

export interface SkillForgeOptions {
  llm: SkillForgeLLM
  /** Optional sandbox used in the validation loop (e.g. AIJADE's computer-use dry-run). */
  sandbox?: SkillSandbox
  /** Persist / load registered skills. Defaults to an in-memory registry. */
  registry?: SkillRegistry
  /** Max teachable-moment detection attempts per conversation. */
  maxDetectAttempts?: number
}

export interface SkillRegistry {
  add: (pkg: SkillPackage) => void
  get: (name: string) => SkillPackage | undefined
  has: (name: string) => boolean
  list: () => SkillPackage[]
  remove: (name: string) => boolean
}
