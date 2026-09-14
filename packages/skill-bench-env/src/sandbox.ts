import type { BenchFailure, BenchTask, ExecutionVerdict } from './types'

/// <reference types="node" />
import { runInNewContext } from 'node:vm'

import { BENCH_TASKS } from './tasks'

// --------------------------------------------------------------------------
// Code extraction
// --------------------------------------------------------------------------

/**
 * Extract the first ```js / ```javascript fenced code block from a model's
 * markdown output. Tolerates leading indentation, trailing ```, and code-fence
 * languages in any case. If no fenced block is found, the whole string is
 * treated as raw code.
 */
export function extractCodeBlock(markdown: string): string | undefined {
  if (markdown == null)
    return undefined
  const fenced = /```\s*(?:js|javascript)[ \t]*\r?\n([\s\S]*?)```/i
  const m = markdown.match(fenced)
  if (m)
    return m[1].replace(/\s+$/, '')
  return markdown
}

// --------------------------------------------------------------------------
// Sandbox context: only standard intrinsics + a no-op console.
// `require`, `process`, `fs`, and host globals are intentionally absent, so a
// submitted function cannot escape the VM. Native ECMAScript intrinsics (Object,
// Array, Math, JSON, Date, RegExp, ...) are provided automatically by the VM.
// --------------------------------------------------------------------------

function buildContext(): Record<string, unknown> {
  return {
    console: {
      log() {},
      info() {},
      warn() {},
      error() {},
      debug() {},
      trace() {},
    },
  }
}

// --------------------------------------------------------------------------
// Realm-agnostic deep equality.
// NOTE: we do NOT use `assert.deepStrictEqual` here — values returned from the
// VM have different intrinsic constructors than host values, so deepStrictEqual
// would wrongly report them as unequal. We compare structurally instead, which
// is also faster and has no cross-realm surprises.
// --------------------------------------------------------------------------

function deepEqual(a: unknown, b: unknown): boolean {
  if (Number.isNaN(a) && Number.isNaN(b))
    return true
  if (a === b)
    return true
  if (typeof a !== typeof b)
    return false

  // At this point a and b are both non-NaN, same typeof, and not null.
  // If they are primitives (number/string/boolean/...) they were already
  // rejected by `a === b` above, so any remaining primitive pair is unequal.
  if (typeof a !== 'object')
    return false

  const aArr = Array.isArray(a)
  const bArr = Array.isArray(b)
  if (aArr || bArr) {
    if (!aArr || !bArr)
      return false
    const aa = a as unknown[]
    const bb = b as unknown[]
    if (aa.length !== bb.length)
      return false
    for (let i = 0; i < aa.length; i++) {
      if (!deepEqual(aa[i], bb[i]))
        return false
    }
    return true
  }

  const ka = Object.keys(a as Record<string, unknown>)
  const kb = Object.keys(b as Record<string, unknown>)
  if (ka.length !== kb.length)
    return false
  const ra = a as Record<string, unknown>
  const rb = b as Record<string, unknown>
  for (const k of ka) {
    if (!Object.hasOwn(rb, k))
      return false
    if (!deepEqual(ra[k], rb[k]))
      return false
  }
  return true
}

function errMsg(e: unknown): string {
  if (e instanceof Error)
    return e.message
  return String(e)
}

function makeVerdict(
  start: number,
  ok: boolean,
  passed: number,
  total: number,
  failures: BenchFailure[],
  error?: string,
): ExecutionVerdict {
  return {
    ok,
    passed,
    total,
    durationMs: performance.now() - start,
    failures,
    error,
  }
}

// Appended to the user code to locate the callable target without re-parsing.
// `solve` is preferred, then a single user-defined global function, then the
// whole code is retried as an expression by the caller.
const DETECTION_SUFFIX = `
;globalThis.__CANDIDATE__ = (function () {
  if (typeof solve !== 'undefined' && typeof solve === 'function') return solve;
  var names = __INTRINSIC_FNS__;
  var fns = [];
  var keys = Object.getOwnPropertyNames(globalThis);
  for (var i = 0; i < keys.length; i++) {
    var k = keys[i];
    var excluded = false;
    for (var j = 0; j < names.length; j++) {
      if (names[j] === k) { excluded = true; break; }
    }
    if (excluded) continue;
    var v;
    try { v = globalThis[k]; } catch (e) { continue; }
    if (typeof v === 'function') fns.push(v);
  }
  if (fns.length === 1) return fns[0];
  return undefined;
})();
`

// --------------------------------------------------------------------------
// Execution + verdict
// --------------------------------------------------------------------------

/**
 * Run a submitted `code` string against a benchmark `task` inside a locked-down
 * VM and return a deterministic verdict. Every failure mode (syntax error, load
 * error, timeout, per-case throw, value mismatch) is converted into an
 * ExecutionVerdict; runTask itself never throws, so it is safe to call 120+
 * times in a batch experiment.
 */
export function runTask(code: string, task: BenchTask): ExecutionVerdict {
  const timeout = task.timeoutMs ?? 2000
  const start = performance.now()

  const ctx = buildContext()

  // Probe the names of all intrinsic global functions so the detection step can
  // ignore them and only consider user-defined functions.
  let intrinsicFns: string[] = []
  try {
    intrinsicFns = runInNewContext(
      `Object.getOwnPropertyNames(globalThis).filter(function (k) {
        try { return typeof globalThis[k] === 'function'; } catch (e) { return false; }
      })`,
      ctx,
    ) as string[]
  }
  catch {
    // If the probe itself fails we simply fall back to the `solve` heuristic.
  }

  let fn: unknown
  try {
    ctx.__INTRINSIC_FNS__ = intrinsicFns
    runInNewContext(code + DETECTION_SUFFIX, ctx, { timeout })
    fn = ctx.__CANDIDATE__
  }
  catch (e) {
    return makeVerdict(start, false, 0, task.tests.length, [], errMsg(e))
  }

  // Fallback: treat the whole code as a function expression.
  if (typeof fn !== 'function') {
    try {
      const exprCtx = buildContext()
      const expr = runInNewContext(`(${code})`, exprCtx, { timeout })
      if (typeof expr === 'function')
        fn = expr
    }
    catch {
      // ignore — if it isn't a function we report below.
    }
  }

  if (typeof fn !== 'function') {
    return makeVerdict(
      start,
      false,
      0,
      task.tests.length,
      [],
      'no callable function found (tried `solve`, single global function, and whole-code expression)',
    )
  }

  const failures: BenchFailure[] = []
  let passed = 0

  for (let i = 0; i < task.tests.length; i++) {
    const t = task.tests[i]
    try {
      const callCtx = buildContext()
      callCtx.__FN__ = fn
      callCtx.__ARGS__ = t.args
      const actual = runInNewContext('__FN__.apply(null, __ARGS__)', callCtx, { timeout })
      if (deepEqual(actual, t.expected)) {
        passed++
      }
      else {
        failures.push({ index: i, args: t.args, expected: t.expected, actual })
      }
    }
    catch (e) {
      const msg = errMsg(e)
      // A VM timeout aborts the whole evaluation (it cannot be contained to one
      // case), so surface it as a sandbox-level error.
      if (/timed out|timeout/i.test(msg))
        return makeVerdict(start, false, passed, task.tests.length, failures, msg)
      failures.push({ index: i, args: t.args, expected: t.expected, error: msg })
    }
  }

  return makeVerdict(start, failures.length === 0, passed, task.tests.length, failures)
}

// --------------------------------------------------------------------------
// Deterministic, reproducible task sampling
// --------------------------------------------------------------------------

/** mulberry32: a small, fast, seedable PRNG. Same seed -> same sequence. */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return function () {
    a = (a + 0x6D2B79F5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

/**
 * Return `n` distinct tasks sampled without replacement using a deterministic
 * PRNG seeded by `seed`. The same (n, seed) always yields the same ordered
 * subset, which keeps experiments reproducible.
 */
export function sampleTasks(n: number, seed: number): BenchTask[] {
  const pool = [...BENCH_TASKS]
  const count = Math.max(0, Math.min(n, pool.length))
  const rng = mulberry32(seed)
  for (let i = 0; i < count; i++) {
    const j = i + Math.floor(rng() * (pool.length - i))
    const tmp = pool[i]
    pool[i] = pool[j]
    pool[j] = tmp
  }
  return pool.slice(0, count)
}

export { BENCH_TASKS }
