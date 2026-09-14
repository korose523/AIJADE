import type { SkillBody, SkillFrontmatter } from './types'

/**
 * Prompt templates for the skill forge. They encode Hermes Agent's skill-
 * authoring standards (description <= 60 chars ending in a period, modern
 * section order, tool framing) so the model authors skills the way a
 * maintainer would by hand.
 */

const AUTHORING_STANDARDS = `Follow the skill-authoring standards EXACTLY:
- name: lowercase-hyphenated, <=64 chars, no spaces.
- description: ONE sentence, <=60 characters, ends with a period. State the capability, not the implementation. No marketing words.
- version: "0.1.0"
- author: "AIJADE"
- platforms: only if OS-bound (windows/linux/macos); omit for portable skills.
- metadata.tags: a few Capitalized, Relevant tags.
Body sections (in order): title (H1), intro (2-3 sentences), "When to Use" (bullet triggers), "Prerequisites" (env/creds), "How to Run" (canonical invocation), "Quick Reference" (flat list), "Procedure" (numbered steps, copy-paste exact), "Pitfalls" (known limits), "Verification" (one proof command).
Never invent commands, paths, or APIs you were not given. Keep it scannable (~100-200 lines).`

export function buildTeachableMomentPrompt(history: string): string {
  return `You review a finished conversation to decide whether a REUSABLE skill should be distilled from it.
A skill is worth creating when the conversation solved a non-trivial, repeatable task (a workflow, an API, a toolchain, a debugging recipe) — NOT for one-off chit-chat.

CONVERSATION:
${history}

Decide: shouldCreate (boolean), a one-line rationale, and — only if shouldCreate — a draft with proposedName (lowercase-hyphenated), title, summary (<=60 char sentence ending with period), and whenToUse (bullet trigger phrases).`
}

export function buildGenerationPrompt(draft: {
  proposedName: string
  title: string
  summary: string
  whenToUse: string[]
}): string {
  return `Author ONE complete skill from this draft. Output strict JSON: { "frontmatter": {...}, "body": {...} }.
DRAFT:
- proposedName: ${draft.proposedName}
- title: ${draft.title}
- summary: ${draft.summary}
- whenToUse: ${draft.whenToUse.join('\n  - ')}

${AUTHORING_STANDARDS}`
}

export function buildValidationPrompt(frontmatter: SkillFrontmatter, body: SkillBody): string {
  return `You are a skill reviewer. Inspect this skill and judge whether it is correct, self-contained, and safe to run.
Flag: invented commands/paths/APIs, missing prerequisites, unverifiable steps, or a description that lies about the capability.
Return strict JSON: { "ok": boolean, "warnings": string[], "score": number /*0..1*/ }.

SKILL:
name: ${frontmatter.name}
description: ${frontmatter.description}
${body.procedure.map((s, i) => `${i + 1}. ${s}`).join('\n')}
verification: ${body.verification ?? '(none)'}
whenToUse: ${body.whenToUse.join('; ')}`
}

export function buildEvolutionPrompt(
  current: { frontmatter: SkillFrontmatter, body: SkillBody },
  feedback: string,
): string {
  return `Improve the existing skill based on user feedback. Keep the same name. Rewrite ONLY what the feedback requires; do not churn unrelated sections.
Return strict JSON of the FULL updated skill: { "frontmatter": {...}, "body": {...} }.

FEEDBACK:
${feedback}

CURRENT SKILL:
title: ${current.body.title}
description: ${current.frontmatter.description}
procedure:
${current.body.procedure.map((s, i) => `${i + 1}. ${s}`).join('\n')}
pitfalls: ${(current.body.pitfalls ?? []).join('; ')}
verification: ${current.body.verification ?? '(none)'}

${AUTHORING_STANDARDS}`
}
