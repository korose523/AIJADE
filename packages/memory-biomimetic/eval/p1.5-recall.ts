import type { BioticMemory, GatingCoefficients, LocomoConversation } from '../src/index'

import process from 'node:process'

/**
 * P1.5 — model-free interference characterization (no LLM needed).
 *
 * P1 proved gating-ON is a *subset* of OFF (ON only prunes trivial memories),
 * so ON can never beat OFF on raw evidence recall. The expected downstream
 * benefit must therefore come from CONTEXT PURITY under a limited retrieval
 * budget: under ON the trivial distractors are gone, so the retrieved context
 * is clean; under OFF the context is polluted with trivial distractors that
 * compete for the top-K slots.
 *
 * This script quantifies that gap *without* calling a model, over all 10
 * LoCoMo conversations:
 *
 *   recall@K   — fraction of questions whose gold-evidence memory is in the
 *                top-K. Expected ~1.0 for both (the evidence turn is lexically
 *                the closest match to its question regardless of gating).
 *   distractorLoad@K — fraction of top-K slots that are NON-evidence memories
 *                (trivial distractors). Expected ON ≈ 0, OFF > 0. This is the
 *                precise statement of the interference the reader must survive.
 *
 * Usage:  tsx eval/p1.5-recall.ts [path-to-locomo.json] [conversation-limit]
 */
import { buildExperimentManifest, buildMemory, DEFAULT_GATING, evidenceRecall, loadLocomo, NO_GATING, registerExperimentManifest } from '../src/index'
import { resolveLocomoPath } from './locomo-path'

const KS = [1, 2, 3, 4, 6, 8]

/** Fraction of top-K retrieved slots that are NOT gold-evidence memories. */
function distractorLoad(mem: BioticMemory, conv: LocomoConversation, k: number): number {
  let total = 0
  let trivial = 0
  for (const q of conv.qa) {
    const top = mem.retrieve(q.question, k, false)
    const ev = new Set<string>()
    for (const e of q.evidence) {
      ev.add(e)
      ev.add(`fact_${e}`)
    }
    for (const c of top) {
      total++
      if (!ev.has(c.id))
        trivial++
    }
  }
  return total ? trivial / total : 0
}

function avg(a: number[]): number {
  return a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0
}

async function main(): Promise<void> {
  const m = buildExperimentManifest({
    id: 'p1.5-gating-interference-recall',
    name: 'P1.5: model-free interference characterization — gating ON vs OFF over LoCoMo',
    seed: 0,
    conditions: [
      { name: 'gating-ON', description: 'DEFAULT_GATING — trivial distractors pruned', params: { gating: 'DEFAULT_GATING' } },
      { name: 'gating-OFF', description: 'NO_GATING — trivial distractors retained', params: { gating: 'NO_GATING' } },
    ],
    metrics: ['recall@K', 'distractorLoad@K'],
    notes: 'K ∈ [1,2,3,4,6,8]. recall@K saturates ~1.0 for both; the gating-dependent effect is distractorLoad@K (ON ≈ 0, OFF > 0).',
  })
  registerExperimentManifest(m)
  console.info(`experiment registered: ${m.schema} ${m.id}@${m.version} (seed ${m.seed}, ${m.conditions.length} conditions, ${m.metrics.length} metrics)`)
  console.info()

  const path = resolveLocomoPath(process.argv[2]).path
  const limit = process.argv[3] ? Number(process.argv[3]) : undefined
  const convs = loadLocomo(path)
  const subset = limit ? convs.slice(0, limit) : convs

  console.info('=== P1.5 model-free interference characterization ===')
  console.info(`corpus        : ${path}`)
  console.info(`conversations : ${subset.length}`)
  console.info(`metric A      : recall@K  (gold-evidence in top-K)`)
  console.info(`metric B      : distractorLoad@K (non-evidence share of top-K)`)
  console.info()

  const recall = KS.map(() => ({ on: [] as number[], off: [] as number[] }))
  const load = KS.map(() => ({ on: [] as number[], off: [] as number[] }))

  for (const conv of subset) {
    const on = await buildMemory(conv, DEFAULT_GATING as GatingCoefficients)
    const off = await buildMemory(conv, NO_GATING as GatingCoefficients)
    const gOn = on.config.gating
    const gOff = off.config.gating
    void gOn
    void gOff
    KS.forEach((k, i) => {
      recall[i].on.push(evidenceRecall(on, conv, k).overall)
      recall[i].off.push(evidenceRecall(off, conv, k).overall)
      load[i].on.push(distractorLoad(on, conv, k))
      load[i].off.push(distractorLoad(off, conv, k))
    })
  }

  console.info('recall@K  (mean fraction of questions with gold evidence in top-K):')
  console.info('  K    recallON  recallOFF   gap')
  KS.forEach((k, i) => {
    const a = avg(recall[i].on)
    const b = avg(recall[i].off)
    console.info(`  ${String(k).padStart(2)}   ${a.toFixed(3)}    ${b.toFixed(3)}     ${(a - b >= 0 ? '+' : '')}${(a - b).toFixed(3)}`)
  })
  console.info()
  console.info('distractorLoad@K  (mean fraction of top-K slots that are trivial distractors):')
  console.info('  K     loadON   loadOFF    gap(OFF-ON)')
  KS.forEach((k, i) => {
    const a = avg(load[i].on)
    const b = avg(load[i].off)
    console.info(`  ${String(k).padStart(2)}    ${a.toFixed(3)}    ${b.toFixed(3)}     +${(b - a).toFixed(3)}`)
  })
  console.info()
  console.info('Interpretation (DERIVED from the measured numbers printed above — no hardcoded claims):')
  const i8 = KS.indexOf(8)
  const rOn = (i: number) => avg(recall[i].on)
  const rOff = (i: number) => avg(recall[i].off)
  const lOn = (i: number) => avg(load[i].on)
  const lOff = (i: number) => avg(load[i].off)
  const maxRecall = Math.max(...KS.map((_, i) => Math.max(rOn(i), rOff(i))))
  const gap8 = rOn(i8) - rOff(i8)
  const loadGap8 = lOff(i8) - lOn(i8)
  console.info(`  recall@K is MEASURED, not assumed. Max mean recall@K across all K and both conditions = ${maxRecall.toFixed(3)}.`)
  console.info(maxRecall < 0.9
    ? '  => recall@K is well below 1.0 for BOTH gating conditions: lexical retrieval does NOT reliably bring the gold-evidence memory into the top-K. The prior hardcoded claim "recall@K is ~1.0 for both" is contradicted by the data and has been removed.'
    : '  => at least one condition reaches near-saturation recall@K; the prior "~1.0 for both" assumption holds here.')
  KS.forEach((k, i) => {
    const g = rOn(i) - rOff(i)
    console.info(`  K=${String(k).padStart(2)}: recallON=${rOn(i).toFixed(3)} recallOFF=${rOff(i).toFixed(3)} gap(ON-OFF)=${(g >= 0 ? '+' : '')}${g.toFixed(3)}  loadON=${lOn(i).toFixed(3)} loadOFF=${lOff(i).toFixed(3)}`)
  })
  console.info(`  gating effect at K=8: recallON - recallOFF = ${(gap8 >= 0 ? '+' : '')}${gap8.toFixed(3)} => ${gap8 > 0.005 ? 'ON > OFF (gating helps recall@8)' : gap8 < -0.005 ? 'ON < OFF — SIGN REVERSAL (gating hurts recall@8)' : 'no material difference'}.`)
  console.info(`  distractorLoad@8: ON=${lOn(i8).toFixed(3)} OFF=${lOff(i8).toFixed(3)} (OFF-ON=${loadGap8 >= 0 ? '+' : ''}${loadGap8.toFixed(3)}).`)
  console.info(loadGap8 > 0.01
    ? '  => As expected, OFF retains trivial distractors (higher load); ON prunes them (cleaner context).'
    : '  => Distractor-load difference is small; gating does not materially change context purity under this scorer.')
  console.info('  Whether the distractor-load gap degrades ANSWERS (F1) is measured by p1.5-reader.ts — not asserted here.')
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
