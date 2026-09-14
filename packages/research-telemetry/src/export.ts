/**
 * Exporters: turn records → analysis-ready artefacts.
 *
 * The flat CSV is the important one. The nested `persona` object is exploded
 * into one column per scalar (`persona.pad.pleasure`, `persona.endocrine.dopamine`,
 * …) so that the file can go straight into pandas / R / DuckDB and be plotted
 * without a custom parser. A nested-JSON column would push that work onto every
 * analysis and is the usual reason telemetry ends up unused.
 */

import type { TurnRecord } from './types'

/** RFC-4180 field escaping. */
function csvCell(value: unknown): string {
  if (value === null || value === undefined)
    return ''
  const s = typeof value === 'string' ? value : String(value)
  if (/[",\n\r]/.test(s))
    return `"${s.replace(/"/g, '""')}"`
  return s
}

/**
 * Column order for the flat CSV.
 *
 * Stable and documented, so downstream notebooks can rely on positional or
 * named access across experiment iterations.
 */
export const CSV_COLUMNS: readonly string[] = [
  'sessionId',
  'turnIndex',
  'timestamp',
  'wallClock',
  'role',
  // persona: vector (13)
  ...['openness', 'warmth', 'curiosity', 'patience', 'formality', 'playfulness', 'caution', 'confidence', 'empathy', 'spontaneity', 'diligence', 'assertiveness', 'stability'].map(k => `persona.vector.${k}`),
  // persona: endocrine (5)
  ...['dopamine', 'serotonin', 'cortisol', 'oxytocin', 'adrenaline'].map(k => `persona.endocrine.${k}`),
  // persona: PAD (3)
  ...['pleasure', 'arousal', 'dominance'].map(k => `persona.pad.${k}`),
  // persona: BigFive (5)
  ...['O', 'C', 'E', 'A', 'N'].map(k => `persona.bigFive.${k}`),
  // persona: intimacy (6)
  ...['warmth', 'trust', 'dependence', 'security', 'familiarity', 'longing'].map(k => `persona.intimacy.${k}`),
  'persona.moodLabel',
  // skill forge
  'skillLibrarySize',
  'skillsCreatedThisTurn',
  'skillsRejectedThisTurn',
  // latency
  'latency.vad',
  'latency.asr',
  'latency.llm',
  'latency.tts',
  'latency.lipsync',
  'latency.memoryRetrieval',
  'latency.total',
  // tokens
  'tokens.prompt',
  'tokens.completion',
  'tokens.memoryInjected',
  // misc
  'memoryHits',
  'textLength',
] as const

/** Flatten one record into a row aligned with {@link CSV_COLUMNS}. */
export function flattenRecord(record: TurnRecord): Record<string, unknown> {
  const p = record.persona
  return {
    sessionId: record.sessionId,
    turnIndex: record.turnIndex,
    timestamp: record.timestamp,
    wallClock: record.wallClock,
    role: record.role,

    ...(p?.vector ? mapKeys(p.vector, k => `persona.vector.${k}`) : {}),
    ...(p?.endocrine ? mapKeys(p.endocrine, k => `persona.endocrine.${k}`) : {}),
    ...(p?.pad ? mapKeys(p.pad, k => `persona.pad.${k}`) : {}),
    ...(p?.bigFive ? mapKeys(p.bigFive, k => `persona.bigFive.${k}`) : {}),
    ...(p?.intimacy ? mapKeys(p.intimacy, k => `persona.intimacy.${k}`) : {}),
    ...(p?.moodLabel !== undefined ? { 'persona.moodLabel': p.moodLabel } : {}),

    ...(record.skillLibrarySize !== undefined ? { skillLibrarySize: record.skillLibrarySize } : {}),
    ...(record.skillsCreatedThisTurn !== undefined ? { skillsCreatedThisTurn: record.skillsCreatedThisTurn } : {}),
    ...(record.skillsRejectedThisTurn !== undefined ? { skillsRejectedThisTurn: record.skillsRejectedThisTurn } : {}),

    ...(record.latency ? mapKeys(record.latency, k => `latency.${k}`) : {}),
    ...(record.tokens ? mapKeys(record.tokens, k => `tokens.${k}`) : {}),

    ...(record.memoryHits !== undefined ? { memoryHits: record.memoryHits } : {}),
    ...(record.textLength !== undefined ? { textLength: record.textLength } : {}),
  }
}

function mapKeys<T extends object>(
  obj: T,
  fn: (key: string) => string,
): Record<string, unknown> {
  const out: Record<string, unknown> = {}
  for (const [k, v] of Object.entries(obj))
    out[fn(k)] = v
  return out
}

/** Export turn records as flat CSV (header row included). */
export function toCsv(records: readonly TurnRecord[]): string {
  const rows = records.map(flattenRecord)
  const header = CSV_COLUMNS.join(',')
  const body = rows
    .map(r => CSV_COLUMNS.map(c => csvCell(r[c])).join(','))
    .join('\n')
  return body.length > 0 ? `${header}\n${body}\n` : `${header}\n`
}

/** Export as JSONL — one record per line, append-friendly. */
export function toJsonl(records: readonly TurnRecord[]): string {
  return records.map(r => `${JSON.stringify(r)}\n`).join('')
}

// ---------------------------------------------------------------------------
// Summary statistics — the first thing you compute after a pilot run
// ---------------------------------------------------------------------------

export interface SeriesSummary {
  count: number
  min: number
  max: number
  mean: number
  /** Sample standard deviation (n-1). NaN when count < 2. */
  sd: number
}

function summarize(values: readonly number[]): SeriesSummary {
  const xs = values.filter(v => Number.isFinite(v))
  if (xs.length === 0) {
    return { count: 0, min: Number.NaN, max: Number.NaN, mean: Number.NaN, sd: Number.NaN }
  }
  const min = Math.min(...xs)
  const max = Math.max(...xs)
  const mean = xs.reduce((a, b) => a + b, 0) / xs.length
  if (xs.length < 2) {
    return { count: xs.length, min, max, mean, sd: Number.NaN }
  }
  const variance = xs.reduce((acc, x) => acc + (x - mean) ** 2, 0) / (xs.length - 1)
  return { count: xs.length, min, max, mean, sd: Math.sqrt(variance) }
}

/**
 * Per-numeric-column summary, plus total drift (last − first) for persona
 * series.
 *
 * `drift` matters for Gap #1: the question is not "what is the persona value"
 * but "does it move coherently over weeks, and does that movement track the
 * relationship outcome".
 */
export function summarizeRecords(records: readonly TurnRecord[]): {
  columns: Record<string, SeriesSummary>
  drift: Record<string, number>
} {
  const rows = records.map(flattenRecord)
  const columns: Record<string, SeriesSummary> = {}
  const drift: Record<string, number> = {}

  for (const col of CSV_COLUMNS) {
    const values = rows
      .map(r => r[col])
      .filter((v): v is number => typeof v === 'number' && Number.isFinite(v))
    columns[col] = summarize(values)

    if (col.startsWith('persona.') && values.length >= 2) {
      const ordered = rows
        .filter(r => typeof r[col] === 'number')
        .sort((a, b) => (a.turnIndex as number) - (b.turnIndex as number))
      const first = ordered[0]?.[col] as number | undefined
      const last = ordered[ordered.length - 1]?.[col] as number | undefined
      if (first !== undefined && last !== undefined)
        drift[col] = last - first
    }
  }

  return { columns, drift }
}
