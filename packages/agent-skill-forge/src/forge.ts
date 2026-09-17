import type { ChatMessage } from '@proj-aijade/agent-llm-client'

import type {
  SkillDraft,
  SkillEvolutionEntry,
  SkillForgeOptions,
  SkillPackage,
  SkillRegistry,
  SkillValidationResult,
} from './types'

import { createLogger } from '@proj-aijade/agent-llm-client'
import { z } from 'zod'

import {
  buildEvolutionPrompt,
  buildGenerationPrompt,
  buildTeachableMomentPrompt,
  buildValidationPrompt,
} from './prompts'
import { createPersistentSkillRegistry, createSkillRegistry } from './registry'
import { skillGenerationSchema } from './schema'

const logger = createLogger('agent-skill-forge')

const teachableSchema = z.object({
  shouldCreate: z.boolean(),
  rationale: z.string(),
  draft: z.object({
    proposedName: z.string(),
    title: z.string(),
    summary: z.string(),
    whenToUse: z.array(z.string()),
  }).optional(),
})

const validationSchema = z.object({
  ok: z.boolean(),
  warnings: z.array(z.string()),
  score: z.number().min(0).max(1),
})

export interface SkillForge {
  readonly registry: SkillRegistry
  /** Decide whether a finished conversation is worth distilling into a skill. */
  detectTeachableMoment: (history: ChatMessage[]) => Promise<SkillDraft | null>
  /** Turn a draft into a validated skill package (with one self-repair pass). */
  generateSkill: (draft: SkillDraft) => Promise<SkillPackage>
  /** Run the structural + sandbox + LLM self-check loop. */
  validateSkill: (pkg: SkillPackage) => Promise<SkillValidationResult>
  /** Improve an existing skill from user feedback (HY-Motion RL-from-feedback). */
  evolveSkill: (pkg: SkillPackage, feedback: string) => Promise<SkillPackage>
  /** Validate then persist into the registry. */
  register: (pkg: SkillPackage) => { registered: boolean, result: SkillValidationResult }
}

function bumpVersion(v: string): string {
  const m = v.match(/^(\d+)\.(\d+)\.(\d+)$/)
  if (!m)
    return v
  const [, a, b, c] = m
  return `${a}.${b}.${Number(c) + 1}`
}

function historyToString(history: ChatMessage[]): string {
  return history.map(m => `${m.role}: ${m.content}`).join('\n\n')
}

export function createSkillForge(options: SkillForgeOptions): SkillForge {
  const { llm, sandbox } = options
  const registry = options.registry
    ?? (options.skillLibraryPath
      ? createPersistentSkillRegistry([], { file: options.skillLibraryPath })
      : createSkillRegistry())

  async function detectTeachableMoment(history: ChatMessage[]): Promise<SkillDraft | null> {
    const historyText = historyToString(history)
    if (!historyText.trim())
      return null
    const parsed = await llm.jsonComplete(historyText
      ? [{ role: 'system', content: 'You output strict JSON only.' }, { role: 'user', content: buildTeachableMomentPrompt(historyText) }]
      : [], { schema: teachableSchema })
    if (!parsed.shouldCreate || !parsed.draft)
      return null
    return parsed.draft
  }

  async function attemptGenerate(draft: SkillDraft, priorErrors?: string[]): Promise<SkillPackage | null> {
    let prompt = buildGenerationPrompt(draft)
    if (priorErrors && priorErrors.length > 0)
      prompt += `\n\nPREVIOUS ERRORS TO FIX:\n${priorErrors.map(e => `- ${e}`).join('\n')}`
    const parsed = await llm.jsonComplete([{ role: 'system', content: 'You output strict JSON only.' }, { role: 'user', content: prompt }], { schema: skillGenerationSchema })
    const now = Date.now()
    return {
      frontmatter: parsed.frontmatter,
      body: parsed.body,
      createdAt: now,
      updatedAt: now,
      source: 'llm-generated',
      evolutionLog: [],
    }
  }

  async function generateSkill(draft: SkillDraft): Promise<SkillPackage> {
    const first = await attemptGenerate(draft)
    if (!first)
      throw new Error('Skill generation returned no content.')
    const result = await validateSkill(first)
    if (result.ok)
      return first
    // Self-repair pass using the structural errors.
    const repaired = await attemptGenerate(draft, result.errors)
    if (repaired) {
      const recheck = await validateSkill(repaired)
      logger.debug(`generateSkill repaired: score ${result.score.toFixed(2)} -> ${recheck.score.toFixed(2)}`)
      return recheck.score >= result.score ? repaired : first
    }
    return first
  }

  async function validateSkill(pkg: SkillPackage): Promise<SkillValidationResult> {
    const errors: string[] = []
    const warnings: string[] = []

    const structural = skillGenerationSchema.safeParse({ frontmatter: pkg.frontmatter, body: pkg.body })
    const structuralOk = structural.success
    if (!structuralOk && structural.error) {
      for (const issue of structural.error.issues)
        errors.push(`${issue.path.join('.') || 'skill'}: ${issue.message}`)
    }

    let score = structuralOk ? 0.6 : 0

    if (sandbox) {
      try {
        const sand = await sandbox(pkg)
        if (!sand.ok) {
          errors.push(`sandbox: ${sand.notes}`)
          score *= 0.5
        }
        else {
          warnings.push(`sandbox: ${sand.notes}`)
        }
      }
      catch (err) {
        warnings.push(`sandbox skipped: ${(err as Error).message}`)
      }
    }

    try {
      const judge = await llm.jsonComplete([{ role: 'system', content: 'You output strict JSON only.' }, { role: 'user', content: buildValidationPrompt(pkg.frontmatter, pkg.body) }], { schema: validationSchema })
      warnings.push(...judge.warnings)
      const llmScore = Number.isFinite(judge.score) ? judge.score : 0
      score = structuralOk ? 0.5 + llmScore * 0.5 : llmScore * 0.3
      if (!judge.ok && structuralOk)
        errors.push('LLM reviewer judged the skill unsafe/incomplete.')
    }
    catch (err) {
      warnings.push(`LLM self-check skipped: ${(err as Error).message}`)
    }

    score = Math.max(0, Math.min(1, score))
    return { ok: structuralOk && errors.length === 0, errors, warnings, score }
  }

  async function evolveSkill(pkg: SkillPackage, feedback: string): Promise<SkillPackage> {
    const fromVersion = pkg.frontmatter.version
    const toVersion = bumpVersion(fromVersion)
    const parsed = await llm.jsonComplete([{ role: 'system', content: 'You output strict JSON only.' }, { role: 'user', content: buildEvolutionPrompt({ frontmatter: pkg.frontmatter, body: pkg.body }, feedback) }], { schema: skillGenerationSchema })

    const entry: SkillEvolutionEntry = {
      at: Date.now(),
      feedback,
      summary: `evolved ${parsed.frontmatter.name} from ${fromVersion} -> ${toVersion}`,
      fromVersion,
      toVersion,
    }
    const now = Date.now()
    return {
      frontmatter: { ...parsed.frontmatter, version: toVersion },
      body: parsed.body,
      module: pkg.module,
      createdAt: pkg.createdAt,
      updatedAt: now,
      source: 'evolved',
      evolutionLog: [...pkg.evolutionLog, entry],
    }
  }

  function register(pkg: SkillPackage): { registered: boolean, result: SkillValidationResult } {
    // Synchronous validation-only path for registration; async deep checks
    // are the caller's responsibility via validateSkill when a sandbox is set.
    const structural = skillGenerationSchema.safeParse({ frontmatter: pkg.frontmatter, body: pkg.body })
    if (structural.success) {
      registry.add(pkg)
      return { registered: true, result: { ok: true, errors: [], warnings: [], score: 0.6 } }
    }
    const errors = structural.error.issues.map(i => `${i.path.join('.') || 'skill'}: ${i.message}`)
    return { registered: false, result: { ok: false, errors, warnings: [], score: 0 } }
  }

  return {
    registry,
    detectTeachableMoment,
    generateSkill,
    validateSkill,
    evolveSkill,
    register,
  }
}
