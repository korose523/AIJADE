import type { ExperimentManifest } from './contracts'

import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

import { validateExperimentManifest } from './contracts'

/**
 * v7 §38 — a committed registry of reproducibly-registered experiments.
 *
 * Every eval script upserts its `ExperimentManifest` here at startup, so the
 * experiment (seed + conditions + committed metrics) is recorded and can be
 * re-run bit-for-bit. This is the "reproducible registration" contract that
 * makes every published claim falsifiable.
 */
export const REGISTRY_SCHEMA = 'aijade.experiment_registry@1'

/**
 * Committed registry path. Deliberately NOT under `results/` (which is
 * git-ignored at the repo root) so the registration survives and is versioned.
 */
export const DEFAULT_REGISTRY_PATH = 'eval/experiments.registry.json'

export interface ExperimentRegistry {
  schema: typeof REGISTRY_SCHEMA
  /** Last registration time (ms epoch). */
  updatedAt: number
  /** Number of distinct experiments currently registered. */
  count: number
  /** Keyed by manifest `id`; re-registration of the same id overwrites. */
  experiments: Record<string, ExperimentManifest>
}

export interface ManifestCondition {
  name: string
  description: string
  params?: Record<string, unknown>
}

export interface ManifestSpec {
  id: string
  name: string
  /** Package version under test; defaults to the package.json version. */
  version?: string
  /** Fixed seed (§38). Defaults to 0 for deterministic experiments. */
  seed?: number
  conditions: ManifestCondition[]
  /** Metrics the experiment commits to reporting — forces falsifiable claims. */
  metrics: string[]
  notes?: string
}

const DEFAULT_SEED = 0

function readPackageVersion(): string {
  try {
    const pkgPath = fileURLToPath(new URL('../package.json', import.meta.url))
    const pkg = JSON.parse(readFileSync(pkgPath, 'utf8')) as { version?: string }
    return pkg.version ?? '0.1.0'
  }
  catch {
    return '0.1.0'
  }
}

/**
 * Construct a §38 ExperimentManifest from a spec, pin the seed, and validate it.
 * Throws if the result violates any §38 invariant (finite seed, ≥1 condition,
 * ≥1 metric) so a malformed experiment can never be silently registered.
 */
export function buildExperimentManifest(spec: ManifestSpec): ExperimentManifest {
  // Omitted seed → default (deterministic experiments). An explicitly
  // non-finite seed is a programming error and must not be silently swallowed.
  const seed = spec.seed === undefined ? DEFAULT_SEED : spec.seed
  if (!Number.isFinite(seed))
    throw new Error(`ExperimentManifest "${spec.id}" requires a finite seed (reproducibility)`)
  const manifest: ExperimentManifest = {
    id: spec.id,
    schema: 'aijade.experiment_manifest@1',
    name: spec.name,
    version: spec.version ?? readPackageVersion(),
    seed,
    conditions: spec.conditions,
    metrics: spec.metrics,
    createdAt: Date.now(),
    ...(spec.notes ? { notes: spec.notes } : {}),
  }
  const v = validateExperimentManifest(manifest)
  if (!v.ok)
    throw new Error(`ExperimentManifest "${spec.id}" invalid: ${v.reason}`)
  return manifest
}

/** Read the committed registry, or return an empty one if absent/corrupt. */
export function readRegistry(path: string = DEFAULT_REGISTRY_PATH): ExperimentRegistry {
  try {
    if (existsSync(path)) {
      const parsed = JSON.parse(readFileSync(path, 'utf8')) as Partial<ExperimentRegistry>
      if (parsed.schema === REGISTRY_SCHEMA && parsed.experiments)
        return parsed as ExperimentRegistry
    }
  }
  catch {
    // fall through to empty registry
  }
  return { schema: REGISTRY_SCHEMA, updatedAt: 0, count: 0, experiments: {} }
}

/**
 * Upsert an experiment manifest into the committed registry. On re-registration
 * the original `createdAt` is preserved (provenance), only `updatedAt` advances.
 * Returns the updated registry. Refuses to register an invalid manifest.
 */
export function registerExperimentManifest(
  manifest: ExperimentManifest,
  path: string = DEFAULT_REGISTRY_PATH,
): ExperimentRegistry {
  const v = validateExperimentManifest(manifest)
  if (!v.ok)
    throw new Error(`Refusing to register invalid ExperimentManifest "${manifest.id}": ${v.reason}`)
  const reg = readRegistry(path)
  const prev = reg.experiments[manifest.id]
  const entry: ExperimentManifest = prev ? { ...manifest, createdAt: prev.createdAt } : manifest
  reg.experiments[manifest.id] = entry
  reg.updatedAt = Date.now()
  reg.count = Object.keys(reg.experiments).length
  mkdirSync(dirname(path), { recursive: true })
  writeFileSync(path, `${JSON.stringify(reg, null, 2)}\n`)
  return reg
}
