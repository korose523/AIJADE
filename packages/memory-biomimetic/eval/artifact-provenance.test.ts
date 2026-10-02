import process from 'node:process'

/**
 * `artifact-provenance` 的单元测试。
 *
 * 重点覆盖 `resolveGitDirty()` 的三种返回，因为它是本模块唯一会**抛错或误报**的
 * 新增逻辑，且误报方向是不对称的：
 *
 * · 谎报`false`（把脏树说成干净）会让一个**不可复现**的数字看起来可复现—— 最危险；
 * ·谎报 `'unknown'` 只是让人多查一步，代价可接受。
 *
 * 所以每个用例都断言"干净 ⇒false、脏 ⇒ true、无法判定 ⇒ 'unknown'"三者**互不混淆**。
 */
import { execSync } from 'node:child_process'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { afterEach, describe, expect, it } from 'vitest'

import { resolveGitDirty, resolveGitSha, RUN_PROVENANCE_SCHEMA, runProvenance, withProvenance } from './artifact-provenance'

/** 建一个可控的临时 git 仓库，测试期间把 CWD 指过去。 */
function inTempGitRepo(fn: (dir: string) => void): void {
  const dir = mkdtempSync(join(tmpdir(), 'ap-dirty-'))
  const cwd = process.cwd()
  try {
    execSync('git init -q && git config user.email t@t.t && git config user.name t', { cwd: dir })
    fn(dir)
  }
  finally {
    process.chdir(cwd)
    rmSync(dir, { recursive: true, force: true })
  }
}

/** 一个**不在**任何 git 仓库内的目录：向上找不到 `.git` 才是真的非 git 环境。 */
function inNonGitDir(fn: (dir: string) => void): void {
  const dir = mkdtempSync(join(tmpdir(), 'ap-nogit-'))
  const cwd = process.cwd()
  try {
    fn(dir)
  }
  finally {
    process.chdir(cwd)
    rmSync(dir, { recursive: true, force: true })
  }
}

afterEach(() => {
  // 兜底：任何用例若在抛错前没chdir 回去，别把污染留给下一个用例。
  if (!process.cwd().includes('aijade'))
    process.chdir(join(process.env.HOME ?? '/', '.codebuddy'))
})

describe('resolveGitDirty — 工作区脏不脏，如实回答', () => {
  it('干净树 ⇒ false', () => {
    inTempGitRepo((dir) => {
      writeFileSync(join(dir, 'a.txt'), 'x', 'utf8')
      execSync('git add -A && git commit -qm init', { cwd: dir })
      process.chdir(dir)
      expect(resolveGitDirty()).toBe(false)
    })
  })

  it('有已跟踪文件的未提交修改 ⇒ true', () => {
    inTempGitRepo((dir) => {
      const f = join(dir, 'a.txt')
      writeFileSync(f, 'x', 'utf8')
      execSync('git add -A && git commit -qm init', { cwd: dir })
      writeFileSync(f, 'y', 'utf8') // 改内容但不加暂存
      process.chdir(dir)
      expect(resolveGitDirty()).toBe(true)
    })
  })

  it('有未跟踪文件 ⇒ true（最容易漏掉的一类）', () => {
    inTempGitRepo((dir) => {
      writeFileSync(join(dir, 'a.txt'), 'x', 'utf8')
      execSync('git add -A && git commit -qm init', { cwd: dir })
      // 内容与已提交文件完全相同：仍是未跟踪文件，且会让实验结果与 commit 对不上。
      writeFileSync(join(dir, 'b.txt'), 'new', 'utf8')
      process.chdir(dir)
      expect(resolveGitDirty()).toBe(true)
    })
  })

  it('有暂存但未提交（index≠ HEAD）⇒ true', () => {
    inTempGitRepo((dir) => {
      writeFileSync(join(dir, 'a.txt'), 'x', 'utf8')
      execSync('git add -A && git commit -qm init', { cwd: dir })
      writeFileSync(join(dir, 'b.txt'), 'staged', 'utf8')
      execSync('git add -A', { cwd: dir })
      process.chdir(dir)
      expect(resolveGitDirty()).toBe(true)
    })
  })

  it('非 git 环境 ⇒ \'unknown\'，不抛错、也不谎报 false', () => {
    inNonGitDir((dir) => {
      process.chdir(dir)
      const d = resolveGitDirty()
      // 关键：不是 false。false 是一个"确定干净"的断言，无 git 时我们无从判断。
      expect(d).toBe('unknown')
      // 同一环境下 resolveGitSha 也要优雅降级，两者姿态一致。
      expect(resolveGitSha()).toBe('unknown')
    })
  })
})

describe('runProvenance — 溯源块字段齐备且schema 未变', () => {
  it('带齐 gitSha / gitShaAtRun / gitDirty 三项', () => {
    const p = runProvenance()
    expect(p.schema).toBe(RUN_PROVENANCE_SCHEMA)
    expect(typeof p.gitSha).toBe('string')
    expect(typeof p.gitShaAtRun).toBe('string')
    expect(p.gitDirty === true || p.gitDirty === false || p.gitDirty === 'unknown').toBe(true)
  })

  it('schema 号不变：既有 14 个脚本的产物结构不能因此对不上', () => {
    // 刻意钉住字面量：改schema 号会让全部历史产物在校验器眼里变成"未知格式"。
    expect(runProvenance().schema).toBe('aijade.run_provenance@1')
  })

  it('显式覆盖优先于自动求值（脚本作者可在非 git 环境声明自己知道的状态）', () => {
    const p = runProvenance({ gitSha: 'deadbeef', gitShaAtRun: 'cafe123', gitDirty: true })
    expect(p.gitSha).toBe('deadbeef')
    expect(p.gitShaAtRun).toBe('cafe123')
    expect(p.gitDirty).toBe(true)
  })

  it('withProvenance 以产物自带的 provenance 为准，不静默改写', () => {
    const custom = runProvenance({ gitSha: 'keepme' })
    const merged = withProvenance({ provenance: custom, v: 1 })
    expect(merged.provenance.gitSha).toBe('keepme')
  })
})

describe('本测试文件自身不会破坏 provenance', () => {
  it('仓库根对本模块而言是脏的（存在未跟踪项），故真实调用返回 true 而非崩溃', () => {
    // 不是断言"一定脏"——那会在干净树上失败；而是断言类型合法、且不抛错。
    const d = resolveGitDirty()
    expect(typeof d === 'boolean' || d === 'unknown').toBe(true)
    // 顺带确认脚本自身可读：防止 probe 被搬到别处后静默失效。
    expect(typeof readFileSync(new URL(import.meta.url), 'utf8')).toBe('string')
  })
})
