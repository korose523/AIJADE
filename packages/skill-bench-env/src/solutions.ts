/**
 * Reference ("ground-truth") solutions and deliberately-wrong candidates for the
 * RQ-C benchmark environment.
 *
 * `REFERENCE_SOLUTIONS` is the authoritative correct implementation of every
 * task in `BENCH_TASKS`. It is derived from the self-check implementations in
 * `tasks.test.ts` so the two can never silently diverge: `solutions.test.ts`
 * asserts every entry (a) has a matching `BENCH_TASKS` id and (b) passes `runTask`
 * against the task's full test suite.
 *
 * `WRONG_CANDIDATES` are *syntactically valid, runnable* implementations that
 * are deliberately incorrect. They are used by the mock backend to produce
 * "wrong but executable" candidates; the subtle errors in the real experiment
 * come from the (mock or Ollama) model step, not from these stubs.
 */

/**
 * Canonical reference implementations, one per task id. Each is a plain
 * function `(...args: any[]) => unknown`. `REFERENCE_SOLUTIONS` below turns each
 * into a string that defines a `solve` function so it runs unchanged in the VM.
 */
const REFS: Record<string, (...args: any[]) => unknown> = {
  // string
  'str-slugify': s => s.trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, ''),
  'str-reverse': s => s.split('').reverse().join(''),
  'str-is-palindrome': (s) => {
    const t = s.toLowerCase().replace(/[^a-z0-9]/g, '')
    let i = 0
    let j = t.length - 1
    while (i < j) {
      if (t[i] !== t[j])
        return false
      i++
      j--
    }
    return true
  },
  'str-capitalize-words': s => s.toLowerCase().replace(/(^|\s)\w/g, c => c.toUpperCase()),
  'str-count-vowels': (s) => {
    let n = 0
    const v = 'aeiou'
    const low = s.toLowerCase()
    for (const c of low) {
      if (v.includes(c))
        n++
    }
    return n
  },
  'str-truncate': (s, maxLen) => {
    if (maxLen <= 0)
      return ''
    if (s.length <= maxLen)
      return s
    return `${s.slice(0, maxLen)}…`
  },
  'str-unique-chars': (s) => {
    let out = ''
    for (const c of s) {
      if (!out.includes(c))
        out += c
    }
    return out
  },
  'str-to-camel': s => s.replace(/[-_]+(\w)?/g, (_, c) => (c ? c.toUpperCase() : '')),
  'str-rot13': (s) => {
    return s.replace(/[a-z]/gi, (c) => {
      const base = c <= 'Z' ? 65 : 97
      const code = c.charCodeAt(0) - base
      return String.fromCharCode((code + 13) % 26 + base)
    })
  },

  // array
  'arr-sum': nums => nums.reduce((s, x) => s + x, 0),
  'arr-max': nums => (nums.length ? Math.max.apply(null, nums) : -Infinity),
  'arr-unique': (arr) => {
    const seen = new Set<any>()
    const out: any[] = []
    for (const x of arr) {
      if (!seen.has(x)) {
        seen.add(x)
        out.push(x)
      }
    }
    return out
  },
  'arr-flatten': arr => arr.reduce((acc, x) => acc.concat(Array.isArray(x) ? x : [x]), []),
  'arr-chunk': (arr, size) => {
    if (size <= 0)
      return []
    const out: any[] = []
    for (let i = 0; i < arr.length; i += size)
      out.push(arr.slice(i, i + size))
    return out
  },
  'arr-intersection': (a, b) => {
    const sb = new Set<any>(b)
    const out: any[] = []
    const seen = new Set<any>()
    for (const x of a) {
      if (sb.has(x) && !seen.has(x)) {
        seen.add(x)
        out.push(x)
      }
    }
    return out
  },
  'arr-remove-falsy': arr => arr.filter(Boolean),
  'arr-second-largest': (nums) => {
    const u = [...new Set<any>(nums)].sort((x, y) => y - x)
    return u.length >= 2 ? u[1] : null
  },
  'arr-sum-evens': nums => nums.reduce((s, x) => s + (x % 2 === 0 ? x : 0), 0),

  // object
  'obj-pick': (obj, keys) => {
    const out: Record<string, any> = {}
    for (const k of keys) {
      if (k in obj)
        out[k] = obj[k]
    }
    return out
  },
  'obj-merge': (a, b) => Object.assign({}, a, b),
  'obj-count-keys': obj => Object.keys(obj).length,
  'obj-group-by': (arr, key) => {
    const out: Record<string, any> = {}
    for (const item of arr) {
      const k = item[key]
      if (!out[k])
        out[k] = []
      out[k].push(item)
    }
    return out
  },
  'obj-get-nested': (obj, path) => {
    let cur = obj
    for (const k of path) {
      if (cur === null || cur === undefined)
        return undefined
      cur = cur[k]
    }
    return cur
  },

  // math
  'math-clamp': (n, min, max) => Math.min(Math.max(n, min), max),
  'math-factorial': (n) => {
    let r = 1
    for (let i = 2; i <= n; i++)
      r *= i
    return r
  },
  'math-is-prime': (n) => {
    if (n < 2)
      return false
    for (let i = 2; i * i <= n; i++) {
      if (n % i === 0)
        return false
    }
    return true
  },
  'math-gcd': (a, b) => {
    a = Math.abs(a)
    b = Math.abs(b)
    while (b) {
      const t = b
      b = a % b
      a = t
    }
    return a
  },
  'math-fib': (n) => {
    let a = 0
    let b = 1
    for (let i = 0; i < n; i++) {
      const t = a
      a = b
      b = t + b
    }
    return a
  },
  'math-average': nums => (nums.length ? nums.reduce((s, x) => s + x, 0) / nums.length : 0),
  'math-round-to': (n, d) => Math.round(n * 10 ** d) / 10 ** d,

  // date
  'date-format-iso': (iso) => {
    const d = new Date(iso)
    const y = d.getUTCFullYear()
    const m = String(d.getUTCMonth() + 1).padStart(2, '0')
    const day = String(d.getUTCDate()).padStart(2, '0')
    return `${y}-${m}-${day}`
  },
  'date-day-of-week': (iso) => {
    const days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
    return days[new Date(iso).getUTCDay()]
  },
  'date-is-leap-year': (iso) => {
    const y = new Date(iso).getUTCFullYear()
    return (y % 4 === 0 && y % 100 !== 0) || y % 400 === 0
  },
  'date-add-days': (iso, days) => {
    const d = new Date(iso)
    d.setUTCDate(d.getUTCDate() + days)
    return d.toISOString()
  },
  'date-seconds-since': (a, b) => Math.floor((new Date(b).getTime() - new Date(a).getTime()) / 1000),

  // parsing
  'parse-query-string': (qs) => {
    const out: Record<string, any> = {}
    if (qs === '')
      return out
    const pairs = qs.split('&')
    for (const pair of pairs) {
      const i = pair.indexOf('=')
      const end = i < 0 ? pair.length : i
      const k = decodeURIComponent(pair.slice(0, end))
      const val = i < 0 ? '' : decodeURIComponent(pair.slice(i + 1))
      out[k] = val
    }
    return out
  },
  'parse-json-safe': (s) => {
    try {
      return JSON.parse(s)
    }
    catch {
      return null
    }
  },
  'parse-csv-line': (line) => {
    const res: any[] = []
    let cur = ''
    let inQ = false
    for (let i = 0; i < line.length; i++) {
      const c = line[i]
      if (inQ) {
        if (c === '"') {
          if (line[i + 1] === '"') {
            cur += '"'
            i++
          }
          else {
            inQ = false
          }
        }
        else {
          cur += c
        }
      }
      else if (c === ',') {
        res.push(cur)
        cur = ''
      }
      else if (c === '"') {
        inQ = true
      }
      else {
        cur += c
      }
    }
    res.push(cur)
    return res
  },
  'parse-version': (v) => {
    const parts = v.split('.')
    for (const p of parts) {
      if (!/^\d+$/.test(p))
        return null
    }
    return parts.map(Number)
  },

  // logic
  'logic-xor': (a, b) => (a && !b) || (!a && b),
  'logic-valid-parentheses': (s) => {
    const st: any[] = []
    for (const c of s) {
      if (c === '(' || c === '[' || c === '{') {
        st.push(c)
      }
      else {
        const t = st.pop()
        if (c === ')' && t !== '(')
          return false
        if (c === ']' && t !== '[')
          return false
        if (c === '}' && t !== '{')
          return false
      }
    }
    return st.length === 0
  },
  'logic-fizzbuzz': (n) => {
    if (n % 15 === 0)
      return 'FizzBuzz'
    if (n % 3 === 0)
      return 'Fizz'
    if (n % 5 === 0)
      return 'Buzz'
    return String(n)
  },
  'logic-roman-to-int': (s) => {
    const m: Record<string, number> = { I: 1, V: 5, X: 10, L: 50, C: 100, D: 500, M: 1000 }
    let total = 0
    for (let i = 0; i < s.length; i++) {
      const cur = m[s[i]]
      const nxt = m[s[i + 1]]
      if (nxt > cur)
        total -= cur
      else
        total += cur
    }
    return total
  },
  'logic-pangram': (s) => {
    const seen = new Set<any>()
    const low = s.toLowerCase()
    for (const c of low) {
      if (c >= 'a' && c <= 'z')
        seen.add(c)
    }
    return seen.size === 26
  },
}

/**
 * The correct implementation of every task, as a source-code string that defines
 * a `solve` function. The VM in `runTask` prefers a `solve` global, so these run
 * unchanged in the sandbox.
 */
export const REFERENCE_SOLUTIONS: Record<string, string> = Object.fromEntries(
  Object.entries(REFS).map(([id, fn]) => [
    id,
    `function solve(...args){ return (${fn.toString()})(...args) }`,
  ]),
)

/**
 * Deliberately incorrect but syntactically valid, runnable implementations.
 * Used by the mock backend to emit "wrong but executable" candidates. None of
 * these should ever pass a task's test suite.
 */
export const WRONG_CANDIDATES: readonly string[] = [
  'function solve(...args){ return undefined }',
  'function solve(...args){ return null }',
  'function solve(...args){ return 0 }',
  'function solve(...args){ return \'\' }',
  'function solve(...args){ return false }',
  'function solve(...args){ return [] }',
  'function solve(...args){ return {} }',
  'function solve(...args){ return args[0] }',
  'function solve(...args){ return args }',
]
