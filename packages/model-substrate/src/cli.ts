/**
 * L0 substrate CLI.
 *
 *   pnpm verify -- --model qwythos --runs 5
 *   pnpm verify -- --model qwen2.5-coder:7b-instruct --runs 5 --seed-strategy varied
 *
 * Run this before any long experiment. If a model cannot reproduce its own
 * output, every downstream number is decoration.
 */

import { createOllamaSubstrate } from './client'
import { measureDeterminism } from './verify'

function parseArgs(argv: string[]): Record<string, string> {
  const out: Record<string, string> = {}
  for (let i = 0; i < argv.length; i++) {
    const token = argv[i]
    if (!token.startsWith('--'))
      continue
    const [key, inlineValue] = token.slice(2).split('=')
    out[key] = inlineValue ?? argv[++i] ?? ''
  }
  return out
}

const PROBE = 'Reply with exactly three words: substrate determinism probe.'

async function main(): Promise<void> {
  const [command = 'verify', ...rest] = process.argv.slice(2)
  const args = parseArgs(rest)

  if (command !== 'verify') {
    console.error(`Unknown command "${command}". Usage: cli.ts verify --model <tag> [--runs N] [--seed-strategy fixed|varied]`)
    process.exit(2)
  }

  const model = args.model
  if (!model) {
    console.error('--model is required')
    process.exit(2)
  }

  const runs = Number.parseInt(args.runs ?? '5', 10)
  const seedStrategy = args['seed-strategy'] === 'varied' ? 'varied' : 'fixed'
  const baseUrl = args['base-url'] ?? 'http://localhost:11434'

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
  console.log('──────────────────────────────────────────────')

  const report = await measureDeterminism(substrate, [{ role: 'user', content: PROBE }], { runs, seedStrategy })

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

  process.exit(report.identical ? 0 : 1)
}

main().catch((e) => {
  console.error(e instanceof Error ? e.message : String(e))
  process.exit(1)
})
