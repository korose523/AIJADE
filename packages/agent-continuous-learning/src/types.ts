import type { ChatCompletion, ChatMessage, ChatRequestOptions } from '@proj-aijade/agent-llm-client'
import type { SkillForge } from '@proj-aijade/agent-skill-forge'
import type { MemoryPort } from '@proj-aijade/memory-pgvector/port'

/**
 * Minimal LLM surface used by the learning layer. {@link OllamaClient} from
 * `@proj-aijade/agent-llm-client` satisfies this structurally.
 */
export interface LearningLLM {
  complete: (messages: ChatMessage[], options?: ChatRequestOptions) => Promise<ChatCompletion>
  jsonComplete: <T = unknown>(
    messages: ChatMessage[],
    options?: ChatRequestOptions & { schema?: import('@proj-aijade/agent-llm-client').ZodSchemaLike<T> },
  ) => Promise<T>
}

export type { MemoryPort, SkillForge }
