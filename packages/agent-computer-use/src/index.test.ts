import type { McpComputerUseClient } from './index'

import { describe, expect, it, vi } from 'vitest'

import {
  computerUseParamsSchema,
  createComputerUseCapability,
  createComputerUseMcpTransport,
  createDryRunBackend,

} from './index'

describe('computerUseParamsSchema', () => {
  it('accepts a valid capture with som mode', () => {
    const r = computerUseParamsSchema.safeParse({ action: 'capture', mode: 'som', app: 'Safari' })
    expect(r.success).toBe(true)
  })

  it('rejects an unknown action', () => {
    const r = computerUseParamsSchema.safeParse({ action: 'explode' })
    expect(r.success).toBe(false)
  })

  it('rejects max_elements over 1000', () => {
    const r = computerUseParamsSchema.safeParse({ action: 'capture', max_elements: 5000 })
    expect(r.success).toBe(false)
  })
})

describe('computer-use capability (dry-run backend)', () => {
  const cap = createComputerUseCapability(createDryRunBackend())

  it('exposes the tool schema for agent discovery', () => {
    expect((cap.toolSchema.name as string)).toBe('computer_use')
  })

  it('routes a safe capture action', async () => {
    const res = await cap.call({ action: 'capture', mode: 'som' })
    expect(res.ok).toBe(true)
    expect(res.safe).toBe(true)
  })

  it('rejects invalid params without touching the backend', async () => {
    const res = await cap.call({ action: 'not-a-real-action' as never })
    expect(res.ok).toBe(false)
  })
})

describe('approval gate (fail-closed on non-safe actions)', () => {
  it('allows read-only actions without an approver', async () => {
    const cap = createComputerUseCapability(createDryRunBackend())
    const res = await cap.call({ action: 'list_apps' })
    expect(res.ok).toBe(true)
  })

  it('blocks non-safe actions when no approver is supplied', async () => {
    const cap = createComputerUseCapability(createDryRunBackend())
    const res = await cap.call({ action: 'click', element: 3 })
    expect(res.ok).toBe(false)
    expect(res.summary).toContain('requires approval')
  })

  it('defers to the approver for non-safe actions', async () => {
    const approve = vi.fn().mockResolvedValue(true)
    const cap = createComputerUseCapability(createDryRunBackend(), { approve })
    const res = await cap.call({ action: 'type', text: 'hello' })
    expect(approve).toHaveBeenCalledOnce()
    expect(res.ok).toBe(true)
  })

  it('blocks when the approver returns false', async () => {
    const approve = vi.fn().mockResolvedValue(false)
    const cap = createComputerUseCapability(createDryRunBackend(), { approve })
    const res = await cap.call({ action: 'key', keys: 'cmd+s' })
    expect(res.ok).toBe(false)
    expect(res.summary).toContain('requires approval')
  })
})

describe('createComputerUseMcpTransport (real backend)', () => {
  function fakeClient(impl: McpComputerUseClient['callTool']): McpComputerUseClient {
    return { callTool: impl }
  }

  it('qualifies the tool name and maps a structured result', async () => {
    const callTool = vi.fn().mockResolvedValue({
      structuredContent: { apps: ['Code', 'Ollama'] },
      isError: false,
    })
    const transport = createComputerUseMcpTransport(fakeClient(callTool))
    const res = await transport.request('list_apps', { action: 'list_apps' })
    expect(callTool).toHaveBeenCalledWith('computer_use::computer_use', { action: 'list_apps' })
    expect(res.ok).toBe(true)
    expect(res.safe).toBe(true)
    expect(res.data).toEqual({ apps: ['Code', 'Ollama'] })
  })

  it('honors a custom server name', async () => {
    const callTool = vi.fn().mockResolvedValue({ content: [{ type: 'text', text: 'ok' }] })
    const transport = createComputerUseMcpTransport(fakeClient(callTool), 'hermes')
    await transport.request('capture', { action: 'capture', mode: 'vision' })
    expect(callTool).toHaveBeenCalledWith('hermes::computer_use', { action: 'capture', mode: 'vision' })
  })

  it('propagates backend errors as not-ok', async () => {
    const callTool = vi.fn().mockResolvedValue({ isError: true, content: [{ type: 'text', text: 'boom' }] })
    const transport = createComputerUseMcpTransport(fakeClient(callTool))
    const res = await transport.request('click', { action: 'click', element: 1 })
    expect(res.ok).toBe(false)
    expect(res.summary).toContain('boom')
  })
})
