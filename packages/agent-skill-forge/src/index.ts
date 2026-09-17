import type { SkillBody, SkillFrontmatter, SkillModule, SkillPackage } from './types'

export { createSkillForge, type SkillForge } from './forge'
export { createPersistentSkillRegistry, createSkillRegistry, type MeasuredSkillRegistry, type MeasuredSkillRegistryOptions, type PersistentSkillRegistryOptions } from './registry'
export {
  platformSchema,
  skillBodySchema,
  skillFrontmatterSchema,
  skillGenerationSchema,
} from './schema'
export { parseSkillMarkdown, skillToMarkdown } from './skill-markdown'
export * from './types'

export interface DefineSkillInput {
  frontmatter: Omit<SkillFrontmatter, 'version' | 'author'> & Partial<Pick<SkillFrontmatter, 'version' | 'author'>>
  body: SkillBody
  module?: SkillModule
}

/**
 * Author a skill declaratively in TypeScript — the "AIJADE-native capability
 * module" half of the user's request. The returned {@link SkillPackage} can be
 * registered directly or exported to a SKILL.md via {@link skillToMarkdown}.
 */
export function defineSkill(input: DefineSkillInput): SkillPackage {
  const now = Date.now()
  return {
    frontmatter: {
      version: '0.1.0',
      author: 'AIJADE',
      ...input.frontmatter,
    },
    body: input.body,
    module: input.module,
    createdAt: now,
    updatedAt: now,
    source: 'hand-authored',
    evolutionLog: [],
  }
}
