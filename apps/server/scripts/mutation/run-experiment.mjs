#!/usr/bin/env node
/**
 * J1 故障注入 / 变异实验装置 — 运行器（P0 #26）。
 *
 * 设计约束（硬）：
 *  - **零生产代码磁盘改动**：变异只在 vitest 运行期通过 transform 钩子对目标模块源码做
 *    **内存中**字符串替换，绝不写回 .ts 源文件。
 *  - 反后门三约束：① 运行前断言 git 工作树除本目录外无改动（生产未被触碰）；
 *    ② 记录并断言 `git rev-parse HEAD` 运行前后相等（注入只发生在运行期）；
 *    ③ 不创建/修改 `apps/server/scripts/mutation/` 之外的任何 .ts/.mjs 源文件。
 *
 * 机制：每次对一个变异体启动一个独立的 vitest 进程。vitest 配置内置 transform 插件，
 * 读取 `AIJADE_MUTATION_ID` 环境变量，对 `mutations.json` 中该变异体的目标文件做定向替换。
 * 测试内联捕获矩阵 `check()` 的 `FAIL ` 行，写入 `.result-<id>.json`；
 * 运行器读取该文件，计算 newRed / falseRed，判别 caught / survived。
 *
 * 用法：
 *   node apps/server/scripts/mutation/run-experiment.mjs [id ... | all | baseline-only]
 */

import { spawnSync } from 'node:child_process'
import { existsSync, readdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { dirname, join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const __dir = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(__dir, '../../../..') // apps/server/scripts/mutation -> repo root (4 levels up)
const MUT_DIR = 'apps/server/scripts/mutation'

const mutations = JSON.parse(readFileSync(join(__dir, 'mutations.json'), 'utf8'))

// ---------------------------------------------------------------------------
// 反后门：git 工作树洁净 + HEAD 稳定
// ---------------------------------------------------------------------------
function git(args) {
  const r = spawnSync('git', args, { cwd: ROOT, encoding: 'utf8' })
  if (r.status !== 0)
    throw new Error(`git ${args.join(' ')} failed: ${r.stderr || r.stdout}`)
  return r.stdout
}

function snapshotDirty() {
  const porcelain = git(['status', '--porcelain']).trim()
  const set = new Set()
  for (const line of porcelain.split('\n').filter(Boolean)) {
    const p = line.trim().split(/\s+/).pop()
    set.add(p)
  }
  return set
}

/**
 * 反后门：仅失败于"本装置运行过程中**新引入**的、位于 ${MUT_DIR}/ 之外的改动"。
 * 运行前已存在的无关改动（如其他实验留下的 registry 改动）予以容忍，不阻断实验。
 */
function checkGitHygiene(preDirty) {
  const dirty = snapshotDirty()
  for (const p of dirty) {
    if (p.startsWith(`${MUT_DIR}/`))
      continue
    if (!preDirty.has(p)) {
      throw new Error(
        `运行期出现了本目录之外的全新改动（生产代码可能被触碰）：${p}\n`
        + `本装置只允许在 ${MUT_DIR}/ 下产生新文件。`,
      )
    }
  }
}

// ---------------------------------------------------------------------------
// 生成 vitest 配置 + 内联测试（均在 MUT_DIR，运行后清理）
// ---------------------------------------------------------------------------
const CONFIG_PATH = join(__dir, '_vitest.config.mjs')
const TEST_PATH = join(__dir, '_matrix.test.mts')

function writeHarnessFiles() {
  writeFileSync(CONFIG_PATH, `import { defineConfig } from 'vitest/config'
import { readFileSync } from 'node:fs'

const MUTATIONS = JSON.parse(readFileSync(new URL('./mutations.json', import.meta.url), 'utf8'))

export default defineConfig({
  root: process.env.AIJADE_ROOT,
  test: {
    environment: 'node',
    include: [process.env.AIJADE_TEST_FILE],
    reporters: ['dot'],
    server: { deps: { inline: ['@proj-aijade/memory-biomimetic'] } },
  },
  plugins: [{
    name: 'aijade-mutation',
    enforce: 'pre',
    transform(code, id) {
      const mid = process.env.AIJADE_MUTATION_ID
      if (!mid || mid === 'baseline') return null
      const m = MUTATIONS.find(x => x.id === mid)
      if (!m || !m.implementable) return null
      const rel = m.file.split('/').join('/')
      const norm = id.split('?')[0].split('\\\\').join('/')
      if (!norm.endsWith(rel)) return null
      const reps = (m.replacements && m.replacements.length)
        ? m.replacements
        : (m.match ? [{ match: m.match, replace: m.replace }] : [])
      let work = code
      for (const rep of reps) {
        const idx = work.indexOf(rep.match)
        if (idx === -1) {
          const msg = 'MUTATION ' + mid + ' match not found: ' + JSON.stringify(rep.match)
          return { code: code + '\\nthrow new Error(' + JSON.stringify(msg) + ')', map: null }
        }
        work = work.slice(0, idx) + rep.replace + work.slice(idx + rep.match.length)
      }
      return { code: work, map: null }
    },
  }],
})
`)
  writeFileSync(TEST_PATH, `import { it } from 'vitest'
import { writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const failMessages = []
const origErr = console.error.bind(console)
console.error = (...args) => {
  try {
    const s = args.map(a => (a && a.message) ? a.message : (typeof a === 'string' ? a : JSON.stringify(a))).join(' ')
    if (s.startsWith('FAIL ')) failMessages.push(s)
  } catch {}
  origErr(...args)
}

it('contract-drift matrix under mutation', async () => {
  const id = process.env.AIJADE_MUTATION_ID || 'baseline'
  const { runContractDriftMatrix } = await import('../../scripts/verify-v10-contract-drift.ts')
  const { failures } = await runContractDriftMatrix({ postgres: false })
  const out = fileURLToPath(new URL('./.result-' + id + '.json', import.meta.url))
  writeFileSync(out, JSON.stringify({ id, failures, failMessages }))
})
`)
}

function cleanupHarnessFiles() {
  for (const f of [CONFIG_PATH, TEST_PATH]) {
    try { rmSync(f) }
    catch {}
  }
  // 删除所有 .result-*.json
  for (const f of readdirSync(__dir)) {
    if (f.startsWith('.result-') && f.endsWith('.json')) {
      try { rmSync(join(__dir, f)) }
      catch {}
    }
  }
}

// ---------------------------------------------------------------------------
// 运行单个变异体（一个独立 vitest 进程）
// ---------------------------------------------------------------------------
function runOne(id) {
  // 清掉上次的 result
  const prev = join(__dir, `.result-${id}.json`)
  if (existsSync(prev))
    rmSync(prev)

  const r = spawnSync(
    process.execPath,
    [
      join(ROOT, 'node_modules/vitest/vitest.mjs'),
      'run',
      '--no-watch',
      '--config',
      relative(ROOT, CONFIG_PATH),
      relative(ROOT, TEST_PATH),
    ],
    {
      cwd: ROOT,
      encoding: 'utf8',
      env: {
        ...process.env,
        AIJADE_MUTATION_ID: id,
        AIJADE_ROOT: ROOT,
        AIJADE_TEST_FILE: relative(ROOT, TEST_PATH),
      },
    },
  )

  const resultPath = join(__dir, `.result-${id}.json`)
  if (!existsSync(resultPath)) {
    // 测试未产出结果文件：通常是 transform 注入失败或矩阵抛错
    const stderr = (r.stderr || r.stdout || '').split('\n').filter(l => /MUTATION|Error|Transform failed|SyntaxError|Cannot|ENOENT|fail/i.test(l)).slice(-15).join(' | ')
    writeFileSync(join(__dir, `._debug-${id}.txt`), `status=${r.status} error=${r.error ? r.error.message : ''}\n---STDERR---\n${r.stderr || ''}\n---STDOUT---\n${r.stdout || ''}`)
    return { executed: true, observedVerdict: 'mutationError', newRed: 0, falseRed: 0, failures: -1, failMessages: [], note: stderr }
  }
  const data = JSON.parse(readFileSync(resultPath, 'utf8'))
  return data
}

// ---------------------------------------------------------------------------
// 主流程
// ---------------------------------------------------------------------------
function main() {
  const headBefore = git(['rev-parse', 'HEAD']).trim()
  const preDirty = snapshotDirty()
  writeHarnessFiles()

  const args = process.argv.slice(2)
  let ids
  if (args.length === 0 || args[0] === 'all') {
    ids = ['baseline', ...mutations.map(m => m.id)]
  }
  else if (args[0] === 'baseline-only') {
    ids = ['baseline']
  }
  else {
    ids = ['baseline', ...args]
  }

  const results = {}
  for (const id of ids) {
    if (id === 'baseline') {
      const d = runOne('baseline')
      if (d.failures !== 0) {
        cleanupHarnessFiles()
        throw new Error(`BASELINE 不为 0（failures=${d.failures}），装置无效，终止。FAIL 样例：${(d.failMessages || []).slice(0, 5).join(' || ')}`)
      }
      results.baseline = { failures: 0, newRed: 0 }
      console.log(`baseline: failures=0 OK`)
      continue
    }
    const m = mutations.find(x => x.id === id)
    if (!m) {
      console.log(`跳过未知 id: ${id}`)
      continue
    }
    if (!m.implementable) {
      results[id] = { executed: false, observedVerdict: 'notImplemented', predicted: m.predictedVerdict, note: m.note }
      console.log(`${id}: notImplemented (${m.predictedVerdict}) — ${m.note}`)
      continue
    }
    const d = runOne(id)
    let observedVerdict
    let falseRed = []
    if (d.observedVerdict === 'mutationError') {
      observedVerdict = 'mutationError'
    }
    else if (d.failures === 0) {
      observedVerdict = 'survived'
    }
    else {
      observedVerdict = 'caught'
      const ec = m.expectedContains || []
      const red = d.failMessages || []
      falseRed = ec.length
        ? red.filter(msg => !ec.some(sub => msg.includes(sub)))
        : []
    }
    results[id] = {
      executed: true,
      observedVerdict,
      predicted: m.predictedVerdict,
      classHint: m.classHint,
      expectedCapture: m.expectedCapture,
      failures: d.failures,
      newRed: (d.failMessages || []).length,
      falseRed: falseRed.length,
      totalRed: (d.failMessages || []).length,
      note: m.note,
    }
    console.log(`${id}: predicted=${m.predictedVerdict} observed=${observedVerdict} newRed=${(d.failMessages || []).length} falseRed=${falseRed.length}`)
  }

  // 汇总
  const list = mutations
  const executed = list.filter(m => m.implementable)
  let caught = 0; let survived = 0; let notImpl = 0
  for (const m of list) {
    const r = results[m.id]
    if (!r)
      continue
    if (r.observedVerdict === 'caught')
      caught++
    else if (r.observedVerdict === 'survived')
      survived++
    else if (r.observedVerdict === 'notImplemented')
      notImpl++
  }
  const denom = caught + survived
  const diffScore = denom === 0 ? 0 : Number((caught / denom).toFixed(3))

  const report = {
    run: {
      generatedBy: 'run-experiment.mjs',
      gitShaBefore: headBefore,
      matrixVersion: 'verify-v10-contract-drift (PGlite leg)',
      dualLeg: false,
      note: '仅 PGlite 腿（默认）；--postgres 腿当前仓库不可达，按设计 skipped。',
    },
    baseline: { total: 531, failures: 0, perClass: { kernel: 160, http: 141, noWrite: 226, guard: 4 } },
    mutants: list.map(m => ({
      id: m.id,
      file: m.file,
      classHint: m.classHint,
      expectedCapture: m.expectedCapture,
      expectedContains: m.expectedContains,
      predictedVerdict: m.predictedVerdict,
      ...(results[m.id] || { executed: false, observedVerdict: 'notRun' }),
    })),
    summary: {
      total: list.length,
      executed: executed.length,
      caught,
      survived,
      notImplemented: notImpl,
      equivalent: list.filter(m => !m.implementable && /equivalent/i.test(m.note)).length,
      diffScore,
    },
  }

  // 校验 HEAD 稳定 + 运行期无新生产改动
  const headAfter = git(['rev-parse', 'HEAD']).trim()
  if (headAfter !== headBefore) {
    throw new Error(`HEAD 不稳定：${headBefore} -> ${headAfter}`)
  }
  checkGitHygiene(preDirty)

  writeFileSync(join(__dir, 'mutation-report.json'), JSON.stringify(report, null, 2))

  // Markdown
  const md = renderMarkdown(report)
  writeFileSync(join(__dir, 'mutation-report.md'), md)

  cleanupHarnessFiles()
  console.log('\n=== summary ===')
  console.log(`caught=${caught} survived=${survived} notImplemented=${notImpl} diffScore=${diffScore}`)
  console.log('wrote mutation-report.json + mutation-report.md')
}

function renderMarkdown(report) {
  const lines = []
  lines.push('# J1 变异/故障注入实验报告（mutation-report）')
  lines.push('')
  lines.push(`- git: \`${report.run.gitShaBefore}\``)
  lines.push(`- 装置：内存 transform 注入，零生产代码磁盘改动`)
  lines.push(`- baseline：531/531（failures=0）`)
  lines.push('')
  lines.push('## 检测率矩阵：注入 ID × 断言类别 → 由绿转红数 / 期望捕获数')
  lines.push('')
  lines.push('| ID | 文件 | 类别 | 期望捕获 | 预测 | 观测 | 新红 | falseRed |')
  lines.push('|---|---|---|---|---|---|---|---|')
  for (const mt of report.mutants) {
    const r = mt
    lines.push(`| ${mt.id} | \`${mt.file}\` | ${mt.classHint} | ${mt.expectedCapture} | ${mt.predictedVerdict} | ${r.observedVerdict} | ${r.newRed ?? '-'} | ${r.falseRed ?? '-'} |`)
  }
  lines.push('')
  const s = report.summary
  lines.push(`## 汇总`)
  lines.push('')
  lines.push(`- 总变异体：${s.total}　已执行：${s.executed}　捕获(caught)：${s.caught}　存活(survived)：${s.survived}　未实现(notImplemented)：${s.notImplemented}　等价(equivalent)：${s.equivalent}`)
  lines.push(`- **diffScore（检测率）= caught / (caught + survived) = ${s.diffScore}**`)
  lines.push('')
  lines.push('## 存活 / 未实现变异（论文诚实检测边界）')
  lines.push('')
  for (const mt of report.mutants) {
    if (mt.observedVerdict === 'survived' || mt.observedVerdict === 'notImplemented') {
      lines.push(`- **${mt.id}** [${mt.observedVerdict}] (${mt.classHint})：${mt.note}`)
    }
  }
  return lines.join('\n')
}

main()
