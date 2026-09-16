import { describe, expect, it } from 'vitest'

import {
  ACCEPT_EXIT,
  ACCEPTANCE_SQL,
  AUDIT_ACTION_RENDER_READY_WITHOUT_MATCHING_REQUEST,
  buildJsonReport,
  describeConnectionError,
  evaluateAcceptance,
  redactSecrets,
  V9_TOPICS,
} from './accept-v9-render-loop'

/**
 * 只测**纯函数**（决策逻辑 / 错误格式化 / 脱敏 / JSON 组装）。
 *
 * ⚠️ 本测试**不**覆盖"连接真实运行库读真实数据"那一跳 —— 本机没有运行期数据库。
 * 那一跳是**未验证**的，见 `accept-v9-render-loop.ts` 顶部的诚实边界说明。
 */
describe('evaluateAcceptance', () => {
  it('passes when a render_ready exists and pairs with a same-trace request', () => {
    const v = evaluateAcceptance({
      renderReadyCount: 1,
      latestTraceId: 'trace-1',
      requestCountForLatestTrace: 1,
      orphanAuditCount: 0,
    })
    expect(v.pass).toBe(true)
    expect(v.exitCode).toBe(0)
    expect(v.lines.some(l => l.startsWith('PASS'))).toBe(true)
    expect(v.lines.some(l => l.startsWith('WARN'))).toBe(false)
  })

  it('still passes but warns when orphan audit rows exist alongside a healthy pair', () => {
    const v = evaluateAcceptance({
      renderReadyCount: 2,
      latestTraceId: 'trace-1',
      requestCountForLatestTrace: 1,
      orphanAuditCount: 1,
    })
    expect(v.pass).toBe(true)
    expect(v.exitCode).toBe(0)
    expect(v.lines.some(l => l.includes('WARN'))).toBe(true)
  })

  it('fails when the runtime DB has zero render_ready rows', () => {
    const v = evaluateAcceptance({
      renderReadyCount: 0,
      latestTraceId: null,
      requestCountForLatestTrace: null,
      orphanAuditCount: 0,
    })
    expect(v.pass).toBe(false)
    expect(v.exitCode).toBe(1)
    expect(v.lines.some(l => l.includes('没有任何 lpm.render_ready'))).toBe(true)
  })

  it('fails when the render_ready has no same-trace request (unpaired)', () => {
    const v = evaluateAcceptance({
      renderReadyCount: 1,
      latestTraceId: 'trace-1',
      requestCountForLatestTrace: 0,
      orphanAuditCount: 1,
    })
    expect(v.pass).toBe(false)
    expect(v.exitCode).toBe(1)
    expect(v.lines.some(l => l.includes('配对失败'))).toBe(true)
  })

  it('fails when the pairing count could not be resolved at all', () => {
    const v = evaluateAcceptance({
      renderReadyCount: 3,
      latestTraceId: null,
      requestCountForLatestTrace: null,
      orphanAuditCount: 0,
    })
    expect(v.pass).toBe(false)
    expect(v.exitCode).toBe(1)
  })

  it('echoes the measured values into the output for peer review', () => {
    const v = evaluateAcceptance({
      renderReadyCount: 7,
      latestTraceId: 'trace-x',
      requestCountForLatestTrace: 2,
      orphanAuditCount: 3,
    })
    expect(v.lines[0]).toContain('7')
    expect(v.lines[1]).toContain('trace-x')
    expect(v.lines[2]).toContain('2')
    expect(v.lines[3]).toContain('3')
  })
})

describe('v9 literals are a single source of truth', () => {
  it('pins the exact topic and audit-action strings', () => {
    expect(V9_TOPICS.lpmRenderReady).toBe('aijade.lpm.render_ready')
    expect(V9_TOPICS.personaRenderRequested).toBe('aijade.persona.render_requested')
    expect(AUDIT_ACTION_RENDER_READY_WITHOUT_MATCHING_REQUEST)
      .toBe('render_ready_without_matching_request')
  })

  it('never hardcodes a topic literal inside SQL (they must travel as $n params)', () => {
    for (const sql of Object.values(ACCEPTANCE_SQL)) {
      expect(sql).not.toContain(V9_TOPICS.lpmRenderReady)
      expect(sql).not.toContain(V9_TOPICS.personaRenderRequested)
      expect(sql).not.toContain(AUDIT_ACTION_RENDER_READY_WITHOUT_MATCHING_REQUEST)
    }
    expect(ACCEPTANCE_SQL.countRenderReady).toContain('$1')
    expect(ACCEPTANCE_SQL.countRequestForTrace).toContain('$2')
    expect(ACCEPTANCE_SQL.countOrphanAudit).toContain('$1')
  })

  it('uses physical table names, not drizzle export names', () => {
    expect(ACCEPTANCE_SQL.countRenderReady).toContain('"events"')
    expect(ACCEPTANCE_SQL.countOrphanAudit).toContain('"audit_log_entries"')
    for (const sql of Object.values(ACCEPTANCE_SQL))
      expect(sql).not.toContain('v9Events')
  })
})

describe('aCCEPT_EXIT', () => {
  it('keeps every failure class on a distinct code so CI can tell them apart', () => {
    const codes = Object.values(ACCEPT_EXIT)
    expect(new Set(codes).size).toBe(codes.length)
    expect(ACCEPT_EXIT.pass).toBe(0)
    expect(ACCEPT_EXIT.fail).toBe(1)
    expect(ACCEPT_EXIT.missingDatabaseUrl).toBe(2)
    expect(ACCEPT_EXIT.connectOrQueryError).toBe(3)
    expect(ACCEPT_EXIT.unexpected).toBe(4)
  })
})

describe('describeConnectionError', () => {
  it('flattens an AggregateError whose own message is empty (the localhost//IPv6 case)', () => {
    const err = {
      message: '',
      errors: [
        new Error('connect ECONNREFUSED ::1:5432'),
        new Error('connect ECONNREFUSED 127.0.0.1:5432'),
      ],
    }
    const lines = describeConnectionError(err)
    expect(lines[0]).toContain('AggregateError')
    expect(lines.some(l => l.includes('::1:5432'))).toBe(true)
    expect(lines.some(l => l.includes('127.0.0.1:5432'))).toBe(true)
  })

  it('keeps a non-empty aggregate message as the headline', () => {
    const err = { message: 'all addresses failed', errors: [new Error('ECONNREFUSED')] }
    expect(describeConnectionError(err)[0]).toBe('all addresses failed')
  })

  it('handles a plain Error', () => {
    expect(describeConnectionError(new Error('connect ECONNREFUSED 127.0.0.1:5432')))
      .toEqual(['connect ECONNREFUSED 127.0.0.1:5432'])
  })

  it('falls back to the error name when the message is blank', () => {
    // `new Error('')` 会被 unicorn/error-message 拦下，故先建后清空。
    const e = new Error('placeholder')
    e.message = ''
    expect(describeConnectionError(e)).toEqual([e.name])
  })

  it('handles non-Error throwables without crashing', () => {
    expect(describeConnectionError('boom')).toEqual(['boom'])
    expect(describeConnectionError(undefined)).toEqual(['undefined'])
  })
})

describe('redactSecrets', () => {
  it('removes the whole DSN when it appears verbatim', () => {
    const dsn = 'postgresql://u:sekret@localhost:5432/postgres'
    const out = redactSecrets(`cannot connect to ${dsn}`, dsn)
    expect(out).not.toContain('sekret')
    expect(out).toContain('<DATABASE_URL redacted>')
  })

  it('masks any user:password@ left over even without the DSN passed in', () => {
    const out = redactSecrets('failed: postgresql://alice:hunter2@db:5432/x')
    expect(out).not.toContain('hunter2')
    expect(out).toContain('alice:***@')
  })

  it('leaves innocuous text untouched', () => {
    expect(redactSecrets('connect ECONNREFUSED 127.0.0.1:5432'))
      .toBe('connect ECONNREFUSED 127.0.0.1:5432')
  })
})

describe('buildJsonReport', () => {
  it('reports PASS with the measured counts', () => {
    const input = {
      renderReadyCount: 2,
      latestTraceId: 'trace-1',
      requestCountForLatestTrace: 1,
      orphanAuditCount: 0,
    }
    const report = buildJsonReport(input, evaluateAcceptance(input))
    expect(report.result).toBe('PASS')
    expect(report.pass).toBe(true)
    expect(report.exitCode).toBe(0)
    expect(report.countLpmRenderReady).toBe(2)
    expect(report.traceId).toBe('trace-1')
    expect(report.countPersonaRenderRequested).toBe(1)
    expect(report.auditGapCount).toBe(0)
    expect(report.auditGapAction).toBe(AUDIT_ACTION_RENDER_READY_WITHOUT_MATCHING_REQUEST)
  })

  it('is JSON-serialisable and reports FAIL when there is no receipt', () => {
    const input = {
      renderReadyCount: 0,
      latestTraceId: null,
      requestCountForLatestTrace: null,
      orphanAuditCount: 0,
    }
    const report = buildJsonReport(input, evaluateAcceptance(input))
    expect(report.result).toBe('FAIL')
    expect(report.exitCode).toBe(1)
    expect(JSON.parse(JSON.stringify(report)).result).toBe('FAIL')
  })
})
