import type { GatingCoefficients, LocomoConversation } from '../src/index'

import process from 'node:process'

import {
  createOllamaSubstrate,
  measureDeterminism,
  RESEARCH_SAMPLING,
} from '../../model-substrate/src/index'
/**
 * P1.5 — LLM reader: translate the context-purity advantage into downstream QA F1.
 *
 * Design (every decision is stated so the experiment is falsifiable):
 *
 * 1. REPRODUCIBILITY (P0). The reader is the local Qwythos model behind
 *    `@proj-aijade/model-substrate` in `research` mode: temperature=0, top_k=1,
 *    repeat_penalty=1 — greedy decoding, never the server's defaults. A
 *    determinism pre-flight runs before anything else; if the substrate is not
 *    bit-exact we abort rather than publish unreproducible numbers. Every run
 *    carries a fingerprint (model digest + sampling + server version).
 *
 * 2. THE ONLY VARIABLE. For each question we build TWO memories that differ in
 *    exactly one thing — the gating config (DEFAULT_GATING vs NO_GATING). Same
 *    corpus, same distiller, same retrieval weights. Under NO_GATING nothing is
 *    pruned; under DEFAULT_GATING the trivial memories are pruned at
 *    consolidation. We retrieve the same top-K from each and ask the reader to
 *    answer. The hypothesis: the clean (ON) context yields >= F1 than the
 *    polluted (OFF) context.
 *
 * 3. TWO PROBES.
 *    (a) Controlled distractor-competition benchmark: hand-built scenes where a
 *        trivial distractor has HIGHER lexical similarity to the question than
 *        the important fact. This is the regime where adaptive forgetting MUST
 *        help. Under OFF the distractor occupies the top slots; under ON it is
 *        pruned. Direct mechanism demonstration.
 *    (b) LoCoMo slice: a small sample of real questions, for ecological context.
 *        On LoCoMo's lexical retrieval the gold evidence is usually the top
 *        match, so the expected gain here is small or null — an honest bound on
 *        the contribution, not a guaranteed win.
 *
 * Usage:  tsx eval/p1.5-reader.ts [path-to-locomo.json]
 */
import {
  BioticMemory,
  buildExperimentManifest,
  buildMemory,
  DEFAULT_GATING,
  DEFAULT_MEMORY_CONFIG,

  LexicalDistiller,
  loadLocomo,

  NO_GATING,
  registerExperimentManifest,
  tokenF1,
} from '../src/index'
import { resolveLocomoPath } from './locomo-path'

const MODEL = 'qwythos:latest'
const BASE_URL = 'http://localhost:11434'
const TOP_K = 4
// Short factual answers; our prompts are <300 tokens, so a 4096 context window
// is ample and avoids the cost of allocating a 32K window on every call.
const READER_SAMPLING = { ...RESEARCH_SAMPLING, num_ctx: 4096, num_predict: 48 }

const SYS = 'You answer questions strictly from the retrieved memory excerpts. Reply with one short phrase or value only. If the answer is not present in the excerpts, reply exactly: unknown.'

interface Scene {
  question: string
  answer: string
  evidence: string
  distractors: string[]
}

// Important turn: high dopamine (kept under ON, pruned-under-nothing).
const SALIENT = { affect: { valence: 0.85, arousal: 0.6, dominance: 0.7 }, dopamine: 0.9, cortisol: 0.2, socialWeight: 0.7 }
// Trivial turn: low dopamine (pruned under ON, kept under OFF).
const TRIVIAL = { affect: { valence: 0.5, arousal: 0.4, dominance: 0.5 }, dopamine: 0.25, cortisol: 0.35, socialWeight: 0.15 }

const SCENES: Scene[] = [
  { question: 'What is the secret launch code for the satellite?', answer: '4491', evidence: 'The access credential is 4491.', distractors: ['The satellite team discussed the launch code review meeting on friday.'] },
  { question: 'What is the admin password for the server?', answer: 'qwerty77', evidence: 'The root authentication string is qwerty77.', distractors: ['The server admin changed the password policy last week.'] },
  { question: 'Where is the board meeting tomorrow?', answer: 'room 402', evidence: 'The executive gathering is in room 402.', distractors: ['The board scheduled the meeting and reserved the room for tomorrow.'] },
  { question: 'What spice goes in the curry?', answer: 'cardamom', evidence: 'The aromatic pod is cardamom.', distractors: ['The curry recipe needs more spice and salt.'] },
  { question: 'What is the flight number to Tokyo?', answer: 'nh208', evidence: 'The carrier identifier is nh208.', distractors: ['The flight to tokyo departs from gate b.'] },
  { question: 'When is my sister\'s birthday?', answer: 'march 14', evidence: 'The sibling anniversary is march 14.', distractors: ['My sister planned a birthday party with friends.'] },
  { question: 'What is the delivery address?', answer: '12 oak street', evidence: 'The shipping destination is 12 oak street.', distractors: ['The delivery truck arrived at the address early.'] },
  { question: 'Who is the family doctor?', answer: 'dr lee', evidence: 'The physician is dr lee.', distractors: ['The family visited the doctor for a checkup.'] },
  { question: 'When is the project deadline?', answer: 'october 5', evidence: 'The cutoff date is october 5.', distractors: ['The project manager set the deadline after review.'] },
  { question: 'What is the wifi password?', answer: 'ilovecats', evidence: 'The network key is ilovecats.', distractors: ['The wifi router needed a password reset.'] },
  { question: 'What model is the new car?', answer: 'toyota prius', evidence: 'The vehicle is a toyota prius.', distractors: ['The new car has a better model this year.'] },
  { question: 'Which film did we see?', answer: 'inception', evidence: 'The motion picture was inception.', distractors: ['We saw the film at the cinema last night.'] },
]

function buildSceneMem(scene: Scene, gating: GatingCoefficients): BioticMemory {
  // consolidateThreshold 0 so even a tiny bank triggers selective pruning —
  // faithful to the same consolidation path LoCoMo uses, just without the
  // real corpus volume. Only the gating differs between the two instances.
  const config = { ...DEFAULT_MEMORY_CONFIG, gating, consolidateThreshold: 0 } as typeof DEFAULT_MEMORY_CONFIG
  const mem = new BioticMemory(config, Date.now())
  mem.encode({ id: 'imp', content: scene.evidence, createdAt: 1_000, encoding: SALIENT, context: { sessionId: 's', interlocutor: 'a', task: undefined, tags: [] } })
  scene.distractors.forEach((d, i) => {
    mem.encode({ id: `dist${i}`, content: d, createdAt: 1_000 + i, encoding: TRIVIAL, context: { sessionId: 's', interlocutor: 'b', task: undefined, tags: [] } })
  })
  return mem
}

function ctxBlock(items: { content: string }[]): string {
  return items.map((it, i) => `${i + 1}. ${it.content}`).join('\n')
}

/**
 * Reader call that never aborts the whole run on one empty/error completion.
 * A blank answer is a legitimate (if bad) outcome and scores F1 = 0.
 */
async function safeGenerate(
  substrate: ReturnType<typeof createOllamaSubstrate>,
  messages: { role: 'system' | 'user' | 'assistant', content: string }[],
  sampling: typeof READER_SAMPLING,
): Promise<{ text: string, fingerprint: string }> {
  try {
    const r = await substrate.generate({ messages, sampling })
    return { text: r.text, fingerprint: r.fingerprint.fingerprint }
  }
  catch {
    return { text: '', fingerprint: '' }
  }
}

/** LoCoMo answers are sometimes arrays; coerce to a comparable string. */
function f1(pred: string, gold: unknown): number {
  const g = Array.isArray(gold) ? gold.join(' ') : String(gold ?? '')
  return tokenF1(pred, g)
}

interface ReaderResult {
  question: string
  on: { text: string, f1: number }
  off: { text: string, f1: number }
}

async function run(): Promise<void> {
  const m = buildExperimentManifest({
    id: 'p1.5-reader-qa-f1',
    name: 'P1.5: LLM reader — downstream QA token-F1 under clean (ON) vs polluted (OFF) context',
    seed: 0,
    conditions: [
      { name: 'gating-ON', description: 'DEFAULT_GATING — distractor-pruned context', params: { gating: 'DEFAULT_GATING' } },
      { name: 'gating-OFF', description: 'NO_GATING — polluted context', params: { gating: 'NO_GATING' } },
    ],
    metrics: ['tokenF1.ON', 'tokenF1.OFF', 'tokenF1.gap', 'determinism.identical'],
    notes: 'Requires local Ollama substrate qwythos:latest in research mode (temperature=0, top_k=1). A determinism pre-flight aborts the run if the substrate is not bit-exact, so numbers are never published unreproducibly. Two probes: controlled distractor-competition benchmark + small LoCoMo slice.',
  })
  registerExperimentManifest(m)
  console.info(`experiment registered: ${m.schema} ${m.id}@${m.version} (seed ${m.seed}, ${m.conditions.length} conditions, ${m.metrics.length} metrics)`)
  console.info()

  const locomoPath = resolveLocomoPath(process.argv[2]).path
  const substrate = createOllamaSubstrate({ model: MODEL, mode: 'research', baseUrl: BASE_URL, sampling: READER_SAMPLING })
  const distiller = new LexicalDistiller()

  // --- (1) determinism pre-flight -------------------------------------------
  console.info('=== P1.5 LLM reader (deterministic, fingerprinted) ===')
  console.info(`model: ${MODEL}  mode: research  sampling: temp=${READER_SAMPLING.temperature} top_k=${READER_SAMPLING.top_k} rep_pen=${READER_SAMPLING.repeat_penalty}`)
  const fp = await substrate.fingerprint(READER_SAMPLING)
  console.info(`fingerprint: ${fp.fingerprint}  (${fp.model.tag}@${fp.model.digest?.slice(0, 12)} server=${fp.serverVersion})`)
  console.info('determinism pre-flight (varied seeds, must be identical for greedy):')
  const det = await measureDeterminism(substrate, [{ role: 'user', content: 'Reply with the single word: yes.' }], { runs: 5, seedStrategy: 'varied' })
  console.info(`  identical=${det.identical} uniqueOutputs=${det.uniqueOutputs}/${det.runs} ${det.identical ? 'OK' : 'FAIL'}`)
  if (!det.identical)
    throw new Error('Substrate is not bit-exact under varied seeds — aborting rather than publish unreproducible numbers.')

  // --- (2) controlled distractor-competition benchmark ----------------------
  console.info('\n--- controlled distractor-competition benchmark ---')
  const bench: ReaderResult[] = []
  for (const scene of SCENES) {
    const onMem = buildSceneMem(scene, DEFAULT_GATING)
    const offMem = buildSceneMem(scene, NO_GATING)
    await onMem.consolidate(distiller)
    await offMem.consolidate(distiller)
    const onTop = onMem.retrieve(scene.question, TOP_K, false)
    const offTop = offMem.retrieve(scene.question, TOP_K, false)
    const onRes = await safeGenerate(substrate, [{ role: 'system', content: SYS }, { role: 'user', content: `Retrieved memory:\n${ctxBlock(onTop)}\n\nQuestion: ${scene.question}\nAnswer:` }], READER_SAMPLING)
    const offRes = await safeGenerate(substrate, [{ role: 'system', content: SYS }, { role: 'user', content: `Retrieved memory:\n${ctxBlock(offTop)}\n\nQuestion: ${scene.question}\nAnswer:` }], READER_SAMPLING)
    bench.push({
      question: scene.question,
      on: { text: onRes.text.trim(), f1: f1(onRes.text, scene.answer) },
      off: { text: offRes.text.trim(), f1: f1(offRes.text, scene.answer) },
    })
  }
  const f1On = bench.reduce((s, r) => s + r.on.f1, 0) / bench.length
  const f1Off = bench.reduce((s, r) => s + r.off.f1, 0) / bench.length
  console.info(`mean token-F1  ON=${f1On.toFixed(3)}  OFF=${f1Off.toFixed(3)}  gap(ON-OFF)=${(f1On - f1Off >= 0 ? '+' : '')}${(f1On - f1Off).toFixed(3)}`)
  for (const r of bench)
    console.info(`  ON  F1=${r.on.f1.toFixed(2)} "${r.on.text}"  | OFF F1=${r.off.f1.toFixed(2)} "${r.off.text}"  | Q: ${r.question}`)
  console.info(`  (ON should win: OFF's top-K is polluted by the higher-similarity distractor)`)

  // --- (3) LoCoMo slice (ecological context) --------------------------------
  console.info('\n--- LoCoMo slice (small, for ecological context) ---')
  const convs = loadLocomo(locomoPath)
  const slice: { conv: LocomoConversation, q: any }[] = []
  for (const c of convs.slice(0, 2)) {
    for (const q of c.qa.slice(0, 6))
      slice.push({ conv: c, q })
  }
  const sliceRes: ReaderResult[] = []
  for (const { conv, q } of slice) {
    const onMem = await buildMemory(conv, DEFAULT_GATING as GatingCoefficients)
    const offMem = await buildMemory(conv, NO_GATING as GatingCoefficients)
    const onTop = onMem.retrieve(q.question, TOP_K, false)
    const offTop = offMem.retrieve(q.question, TOP_K, false)
    const onRes = await safeGenerate(substrate, [{ role: 'system', content: SYS }, { role: 'user', content: `Retrieved memory:\n${ctxBlock(onTop)}\n\nQuestion: ${q.question}\nAnswer:` }], READER_SAMPLING)
    const offRes = await safeGenerate(substrate, [{ role: 'system', content: SYS }, { role: 'user', content: `Retrieved memory:\n${ctxBlock(offTop)}\n\nQuestion: ${q.question}\nAnswer:` }], READER_SAMPLING)
    sliceRes.push({
      question: q.question,
      on: { text: onRes.text.trim(), f1: f1(onRes.text, q.answer) },
      off: { text: offRes.text.trim(), f1: f1(offRes.text, q.answer) },
    })
  }
  const sOn = sliceRes.reduce((s, r) => s + r.on.f1, 0) / sliceRes.length
  const sOff = sliceRes.reduce((s, r) => s + r.off.f1, 0) / sliceRes.length
  console.info(`slice n=${sliceRes.length}  mean token-F1  ON=${sOn.toFixed(3)}  OFF=${sOff.toFixed(3)}  gap(ON-OFF)=${(sOn - sOff >= 0 ? '+' : '')}${(sOn - sOff).toFixed(3)}`)
  console.info('  (expected small/null: lexical retrieval already surfaces the gold evidence,')
  console.info('   so ON and OFF retrieve the same top item; distractors rarely displace it.)')

  // --- artifact -------------------------------------------------------------
  const artifact = {
    fingerprint: fp.fingerprint,
    model: `${fp.model.tag}@${fp.model.digest}`,
    serverVersion: fp.serverVersion,
    sampling: READER_SAMPLING,
    determinism: { identical: det.identical, uniqueOutputs: det.uniqueOutputs, runs: det.runs },
    benchmark: { meanF1On: f1On, meanF1Off: f1Off, gap: f1On - f1Off, perScene: bench },
    locomoSlice: { n: sliceRes.length, meanF1On: sOn, meanF1Off: sOff, gap: sOn - sOff, perQuestion: sliceRes },
  }
  const fs = await import('node:fs')
  fs.mkdirSync(new URL('./results/', import.meta.url), { recursive: true })
  fs.writeFileSync(new URL('./results/p1.5-reader.json', import.meta.url), JSON.stringify(artifact, null, 2))
  console.info(`\nartifact written: eval/results/p1.5-reader.json`)
}

run().catch((e) => {
  console.error(e)
  process.exit(1)
})
