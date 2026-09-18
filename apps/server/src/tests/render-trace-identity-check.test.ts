import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

import { PGlite } from '@electric-sql/pglite'
import { getTableConfig, PgDialect } from 'drizzle-orm/pg-core'
import { beforeEach, describe, expect, it } from 'vitest'

import { buildMemoryV9Ddl } from '../schemas/pglite-ddl'

import * as schema from '../schemas/memory-v9'

/**
 * 复核报告 R4（两步走 · 第一步）：render_traces 两阶段身份不变量。
 *
 * 原方案的「三个 ref 收紧 NOT NULL」不可实施 —— persona.render_requested 先到建行时
 * 回执侧为空、lpm.render_ready 的 asset_version_hash 契约上可选（见内核
 * personaRenderRequestedSchema / lpmRenderReadySchema）。真正落库强制的是两条不变量：
 *   ① 每行至少一端身份；② 有回执端必有 applied_params_hash。
 *
 * 测两层：
 * - 语义层：PGlite 按 schema 生成的 DDL（含 CHECK，立即校验）上验证合法/非法形状。
 * - 同源层：迁移文件 0025 的 CHECK 表达式必须与 schema 渲染结果逐字一致（防漂移）。
 */

const CHECK_NAME = 'render_traces_identity_phase_check'

function renderSchemaCheck(): string {
  const checks = getTableConfig(schema.v9RenderTraces as never).checks as readonly {
    name: string
    value: unknown
  }[]
  const c = checks.find(c => c.name === CHECK_NAME)
  if (!c)
    throw new Error(`schema 未登记 ${CHECK_NAME} —— R4 第一步已回退？`)
  return new PgDialect().sqlToQuery(c.value as never).sql
}

function normalize(s: string): string {
  return s.replace(/\s+/g, ' ').trim()
}

describe('render_traces 两阶段身份不变量（PGlite · schema CHECK 语义）', () => {
  let client: PGlite

  beforeEach(async () => {
    client = new PGlite()
    await client.exec(buildMemoryV9Ddl())
  })

  it('先到端为 render_requested（只有 intent_ref）⇒ 允许', async () => {
    await client.query(
      `INSERT INTO render_traces (id, session_id, trace_id, correlation_id, event_id, projection_status, intent_ref)
       VALUES ('r1', 's-1', 't-1', 'c-1', 'e-1', 'partial', 'intent-1')`,
    )
  })

  it('先到端为 render_ready（render_ref + applied_params_hash，asset_version_hash 契约可选）⇒ 允许', async () => {
    await client.query(
      `INSERT INTO render_traces (id, session_id, trace_id, correlation_id, event_id, projection_status, render_ref, applied_params_hash)
       VALUES ('r1', 's-1', 't-1', 'c-1', 'e-1', 'partial', 'render-1', 'hash-1')`,
    )
  })

  it('配对完成（intent_ref + render_ref + applied_params_hash 齐备）⇒ 允许', async () => {
    await client.query(
      `INSERT INTO render_traces (id, session_id, trace_id, correlation_id, event_id, projection_status, intent_ref, render_ref, applied_params_hash, asset_version_hash)
       VALUES ('r1', 's-1', 't-1', 'c-1', 'e-1', 'paired', 'intent-1', 'render-1', 'hash-1', 'avh-1')`,
    )
  })

  it('有回执端但无内容指纹（render_ref 有、applied_params_hash 空）⇒ 数据库拒绝', async () => {
    await expect(client.query(
      `INSERT INTO render_traces (id, session_id, trace_id, correlation_id, event_id, projection_status, render_ref)
       VALUES ('r1', 's-1', 't-1', 'c-1', 'e-1', 'partial', 'render-1')`,
    )).rejects.toThrow(CHECK_NAME)
  })

  it('两端身份皆空的无主行 ⇒ 数据库拒绝', async () => {
    await expect(client.query(
      `INSERT INTO render_traces (id, session_id, trace_id, correlation_id, event_id, projection_status)
       VALUES ('r1', 's-1', 't-1', 'c-1', 'e-1', 'partial')`,
    )).rejects.toThrow(CHECK_NAME)
  })
})

describe('0025 迁移 ↔ schema 同源（防漂移）', () => {
  it('迁移文件中的 CHECK 表达式与 schema 渲染结果一致', () => {
    const migrationSql = readFileSync(
      fileURLToPath(new URL('../../drizzle/0025_render_traces_identity_phase_check.sql', import.meta.url)),
      'utf8',
    )
    // 0025 尾语句的 CHECK(...) 片段（NOT VALID 不参与比较 —— 那是迁移侧对存量行的放行语义）。
    const m = migrationSql.match(/CHECK \((.*)\) NOT VALID/s)
    expect(m).not.toBeNull()
    expect(normalize(m![1])).toBe(normalize(renderSchemaCheck()))
  })

  it('journal 已登记 0025', () => {
    const journal = JSON.parse(
      readFileSync(fileURLToPath(new URL('../../drizzle/meta/_journal.json', import.meta.url)), 'utf8'),
    ) as { entries: { tag: string }[] }
    expect(journal.entries.some(e => e.tag === '0025_render_traces_identity_phase_check')).toBe(true)
  })
})
