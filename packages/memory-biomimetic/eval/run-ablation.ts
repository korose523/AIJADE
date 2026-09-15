/**
 * P1 ablation runner — the actual experiment.
 *
 * The contribution of physiological gating is demonstrated through RETENTION
 * CURVES, not QA recall: QA recall saturates because the gold-evidence turn is
 * lexically the closest match to its question regardless of gating, so a
 * similarity-dominated score hides the gating's effect. Retention is measured
 * directly: for every memory, is its gating-modulated strength still above the
 * retrieval floor after a forgetting horizon? Split by IMPORTANT (gold-evidence
 * referenced) vs TRIVIAL memories.
 *
 *   ON  : important survival stays high; trivial collapses (pruned).
 *   OFF : important == trivial (no selectivity, both kept & decay equally).
 *
 * The separation gap (important − trivial) under ON should be large and positive;
 * under OFF it should be ~0. That gap is the contribution.
 *
 * Usage:  tsx eval/run-ablation.ts [path-to-locomo.json] [conversation-limit]
 */
import process from 'node:process'

import { buildExperimentManifest, buildMemory, DEFAULT_GATING, loadLocomo, NO_GATING, registerExperimentManifest, retentionCurve } from '../src/index'
import { resolveLocomoPath } from './locomo-path'

const DELTAS = [0, 7, 30, 90, 180, 365]

async function main(): Promise<void> {
  const m = buildExperimentManifest({
    id: 'p1-gating-retention-ablation',
    name: 'P1: physiological gating ON vs OFF — retention under forgetting horizon',
    seed: 0,
    conditions: [
      { name: 'gating-ON', description: 'DEFAULT_GATING — important memories kept, trivial pruned at consolidation', params: { gating: 'DEFAULT_GATING' } },
      { name: 'gating-OFF', description: 'NO_GATING — no selectivity, important == trivial', params: { gating: 'NO_GATING' } },
    ],
    metrics: ['retention.important', 'retention.trivial', 'separationGap.importantMinusTrivial'],
    notes: 'Retention measured at horizons [0,7,30,90,180,365]d. Main contrast = separation gap (important − trivial) under ON vs OFF; ON should be large & positive, OFF ≈ 0.',
  })
  registerExperimentManifest(m)
  console.info(`experiment registered: ${m.schema} ${m.id}@${m.version} (seed ${m.seed}, ${m.conditions.length} conditions, ${m.metrics.length} metrics)`)
  console.info()

  const path = resolveLocomoPath(process.argv[2]).path
  const limit = process.argv[3] ? Number(process.argv[3]) : undefined

  const convs = loadLocomo(path)
  const subset = limit ? convs.slice(0, limit) : convs

  console.info('=== P1 ablation: physiological gating ON (DEFAULT) vs OFF (NO_GATING) ===')
  console.info(`corpus        : ${path}`)
  console.info(`conversations : ${subset.length}`)
  console.info(`metric        : retention (fraction of memories still above retrieval floor)`)
  console.info()

  const rows = DELTAS.map(() => ({ impOn: [] as number[], impOff: [] as number[], triOn: [] as number[], triOff: [] as number[] }))
  const gapOnLast: number[] = []
  const gapOffLast: number[] = []

  for (const conv of subset) {
    const onMem = await buildMemory(conv, DEFAULT_GATING)
    const offMem = await buildMemory(conv, NO_GATING)
    DELTAS.forEach((d, i) => {
      const on = retentionCurve(onMem, conv, d)
      const off = retentionCurve(offMem, conv, d)
      rows[i].impOn.push(on.important)
      rows[i].impOff.push(off.important)
      rows[i].triOn.push(on.trivial)
      rows[i].triOff.push(off.trivial)
      if (i === DELTAS.length - 1) {
        gapOnLast.push(on.important - on.trivial)
        gapOffLast.push(off.important - off.trivial)
      }
    })
  }

  const avg = (a: number[]) => a.reduce((x, y) => x + y, 0) / a.length

  console.info('retention by forgetting horizon (avg over conversations):')
  console.info('  horizon   impON  impOFF  triON  triOFF   gapON  gapOFF')
  DELTAS.forEach((d, i) => {
    const r = rows[i]
    const gapOn = avg(r.impOn) - avg(r.triOn)
    const gapOff = avg(r.impOff) - avg(r.triOff)
    console.info(
      `  +${String(d).padStart(4)}d   ${avg(r.impOn).toFixed(3)}  ${avg(r.impOff).toFixed(3)}   ${avg(r.triOn).toFixed(3)}  ${avg(r.triOff).toFixed(3)}    ${gapOn >= 0 ? '+' : ''}${gapOn.toFixed(3)}  ${gapOff >= 0 ? '+' : ''}${gapOff.toFixed(3)}`,
    )
  })
  console.info()
  console.info(`mean separation gap @ +${DELTAS[DELTAS.length - 1]}d:  ON ${avg(gapOnLast).toFixed(3)}   OFF ${avg(gapOffLast).toFixed(3)}`)
  console.info(`  (ON should be large & positive; OFF ≈ 0 — that contrast is the contribution)`)
}

main().catch((e) => {
  console.error(e)
  process.exit(1)
})
