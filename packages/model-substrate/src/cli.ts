/**
 * L0 substrate CLI.
 *
 *   pnpm verify -- --model qwythos --runs 5
 *   pnpm verify -- --model qwen2.5-coder:7b-instruct --runs 5 --seed-strategy varied
 *   pnpm verify -- --model qwythos --control
 *
 * Run this before any long experiment. If a model cannot reproduce its own
 * output, every downstream number is decoration.
 *
 * `--control` additionally runs the **positive control** arm. Without it the
 * only thing this CLI can tell you is that outputs matched across seeds — which
 * is *also* what you get when the sampling parameters are silently dropped (see
 * the false-positive note in `verify.ts`). With it, a `PASS` additionally means
 * the substrate was shown to respond to sampling parameters, and any other
 * outcome exits non-zero.
 */

import type { DeterminismAudit } from './verify'

import { createOllamaSubstrate } from './client'
import { auditDeterminism, measureDeterminism } from './verify'

function parseArgs(argv: string[]): Record<string, string> {
  const out: Record<string, string> = {}
  for (let i = 0; i < argv.length; i++) {
    const token = argv[i]
    if (!token.startsWith('--'))
      continue
    const [key, inlineValue] = token.slice(2).split('=')
    if (inlineValue !== undefined) {
      out[key] = inlineValue
      continue
    }
    const next = argv[i + 1]
    if (next !== undefined && !next.startsWith('--')) {
      out[key] = next
      i += 1
    }
    else {
      out[key] = 'true'
    }
  }
  return out
}

const USAGE = 'Usage: cli.ts verify --model <tag> [--runs N] [--seed-strategy fixed|varied] [--control] [--base-url URL]'

/**
 * The probe must be able to *diverge* under sampling, otherwise it cannot serve
 * as a positive control.
 *
 * The obvious probe — "reply with exactly three words" — has one correct answer
 * under every decoding mode, so the control arm would report "identical" even
 * on a substrate where sampling works perfectly, i.e. a guaranteed false alarm.
 * Asking for a paragraph of connected prose forces many token-level choices that
 * a sampler will make differently.
 */
const PROBE = 'In about 120 words, explain the water cycle to a student. '
  + 'Write connected prose; do not use bullet points or lists.'

async function main(): Promise<void> {
  const [command = 'verify', ...rest] = process.argv.slice(2)
  const args = parseArgs(rest)

  if (command !== 'verify') {
    console.error(`Unknown command "${command}". ${USAGE}`)
    process.exit(2)
  }

  const model = args.model
  if (!model) {
    console.error(`--model is required.\n${USAGE}`)
    process.exit(2)
  }

  const runs = Number.parseInt(args.runs ?? '5', 10)
  const seedStrategy = args['seed-strategy'] === 'varied' ? 'varied' : 'fixed'
  // 127.0.0.1, NOT localhost: Ollama listens on IPv4 only, and Node resolves
  // `localhost` to ::1 first → ECONNREFUSED on a perfectly healthy server.
  const baseUrl = args['base-url'] ?? 'http://127.0.0.1:11434'
  const withControl = args.control === 'true' || args.control === '1'

  const substrate = createOllamaSubstrate({ model, mode: 'research', baseUrl })

  const identity = await substrate.identity()
  const fingerprint = await substrate.fingerprint()

  console.log('──────────────────────────────────────────────')
  console.log(' L0 substrate — determinism verification')
  console.log('──────────────────────────────────────────────')
  console.log(` model        ${identity.tag}`)
  console.log(` digest       ${identity.digest ?? '(unresolved — tag is mutable, weights are NOT pinned)'}`)
  console.log(` weights      ${identity.sizeBytes ? `${(identity.sizeBytes / 1e9).toFixed(2)} GB` : '-'}`)
  console.log(` family       ${identity.family ?? '-'}  params ${identity.parameterSize ?? '-'}  quant ${identity.quantization ?? '-'}`)
  console.log(` mode         ${fingerprint.mode}`)
  console.log(` sampling     ${JSON.stringify(fingerprint.sampling)}`)
  console.log(` samplingHash ${fingerprint.samplingHash}`)
  console.log(` server       ${fingerprint.serverVersion ?? '(unknown)'}`)
  console.log(` fingerprint  ${fingerprint.fingerprint}`)
  console.log(` runs         ${runs} (seed strategy: ${seedStrategy})`)
  console.log(` control      ${withControl ? 'ENABLED (positive control + audit verdict)' : 'off (passing here does NOT prove greedy decoding)'}`)
  console.log('──────────────────────────────────────────────')

  const messages = [{ role: 'user' as const, content: PROBE }]

  if (!withControl) {
    const report = await measureDeterminism(substrate, messages, { runs, seedStrategy })

    for (const run of report.perRun)
      console.log(` run ${run.index}  seed=${run.seed}  hash=${run.hash}  chars=${run.chars}`)

    console.log('──────────────────────────────────────────────')
    if (report.identical) {
      console.log(` PASS  ${report.uniqueOutputs} distinct output across ${report.runs} runs.`)
      if (seedStrategy === 'varied')
        console.log('       Outputs match even with different seeds — decoding is genuinely greedy.')
    }
    else {
      console.log(` FAIL  ${report.uniqueOutputs} distinct outputs across ${report.runs} runs.`)
      console.log('       Do not run experiments on this substrate until this is understood.')
    }
    console.log('──────────────────────────────────────────────')
    console.log(' NOTE  This is an UNTESTED pass: identical outputs are also what a dropped')
    console.log('       sampling config produces. Re-run with --control to make it evidence.')
    console.log('──────────────────────────────────────────────')

    process.exit(report.identical ? 0 : 1)
  }

  // The control arm needs a substrate that *permits* sampling; a research-mode
  // substrate rejects temperature !== 0 by design. Same model, same server.
  const controlSubstrate = createOllamaSubstrate({
    model,
    mode: 'interactive',
    baseUrl,
    sampling: { ...fingerprint.sampling, temperature: 1, top_k: 40, top_p: 0.95 },
  })

  const audit: DeterminismAudit = await auditDeterminism(substrate, messages, {
    runs,
    seedStrategy,
    control: { substrate: controlSubstrate, runs },
  })

  for (const run of audit.check.perRun)
    console.log(` check  run ${run.index}  seed=${run.seed}  hash=${run.hash}  chars=${run.chars}`)
  console.log(` check  => ${audit.check.uniqueOutputs} distinct across ${audit.check.runs} runs (${audit.check.seedStrategy} seed)`)

  console.log('──────────────────────────────────────────────')
  console.log(' POSITIVE CONTROL  (sampling deliberately opened — this arm MUST diverge)')
  console.log(` sampling   ${JSON.stringify(audit.control.sampling)}`)
  console.log(` hash       ${audit.control.samplingHash}`)
  for (const run of audit.control.perRun)
    console.log(` control  run ${run.index}  seed=${run.seed}  hash=${run.hash}  chars=${run.chars}`)
  console.log(` control  => verdict=${audit.control.verdict}  ${audit.control.uniqueOutputs} distinct across ${audit.control.runs} runs`)
  if (audit.control.error)
    console.log(` control  error: ${audit.control.error}`)
  console.log('──────────────────────────────────────────────')

  console.log(` VERDICT  ${audit.verdict}`)
  console.log(` ${audit.reason}`)
  console.log('──────────────────────────────────────────────')

  process.exit(audit.verdict === 'pass' ? 0 : 1)
}

main().catch((e) => {
  console.error(e instanceof Error ? e.message : String(e))
  process.exit(1)
})
