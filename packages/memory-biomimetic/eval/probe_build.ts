import { buildMemory, CORRECTED_RETRIEVAL_WEIGHTS, DEFAULT_GATING, evidenceRecall, loadLocomo, NO_GATING } from '../src/index'
import { resolveLocomoPath } from './locomo-path'

const log = (...a: unknown[]) => console.error('[probe]', ...a)

async function main(): Promise<void> {
  const { path } = resolveLocomoPath()
  log('loading', path)
  const convs = loadLocomo(path)
  log('loaded', convs.length, 'convs; conv0 episodes=', convs[0].episodes.length)

  log('buildMemory ON start (conv0)')
  const on = await buildMemory(convs[0], DEFAULT_GATING as any)
  log('buildMemory ON done -> facts=', on.facts.length, 'episodes=', on.episodes.length)

  log('buildMemory OFF start (conv0)')
  const off = await buildMemory(convs[0], NO_GATING as any)
  log('buildMemory OFF done -> facts=', off.facts.length)

  log('evidenceRecall ON default start')
  const r1 = evidenceRecall(on, convs[0], 4).overall
  log('evidenceRecall ON default=', r1)

  log('evidenceRecall ON corrected start')
  const r2 = evidenceRecall(on, convs[0], 4, CORRECTED_RETRIEVAL_WEIGHTS).overall
  log('evidenceRecall ON corrected=', r2)

  log('distractorLoad ON default start')
  let tl = 0
  for (const q of convs[0].qa) { const top = on.retrieve(q.question, 4, false); tl += top.length }
  log('distractorLoad ON default slots=', tl)

  log('DONE')
}

main().catch((e) => { console.error('PROBE ERROR', e); process.exit(1) })
