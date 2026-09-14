import type { EndogenousState, HacConfig } from './hac'
import type { ScoreParts } from './retrieval'
import type { BioticMemory } from './store'
import type { GatingCoefficients } from './types'

/**
 * v7 §27 证据织层（Evidence Fabric）。
 *
 * The evidence fabric is a **logical** provenance layer that weaves the store's
 * belief graph, episodic evidence graph, distilled facts and the §25 revision
 * audit trail into a single queryable graph — it does **not** add a physical
 * microservice (v7 §32.1 explicitly反对过早微服务化). It also implements the
 * §27 两级解释 (two-level explanation):
 *   - 简版：一句自然语言归因；
 *   - 研究版：完整事件链 + 分数分解(ScoreParts) + HAC 门控状态 + 策略链(gating/hac config)。
 *
 * 范围护盾：本模块只读 store 状态、从不自行决定保留期 / 显著性；durability/salience
 * 决策仍归 HAC（§9.3），证据织层只消费与呈现。
 */

export type ProvenanceKind
  = | 'belief'
    | 'belief-revision'
    | 'episode'
    | 'fact'
    | 'procedural'
    | 'working'
    | 'rejection'

export interface ProvenanceNode {
  ref: string
  kind: ProvenanceKind
  label: string
  detail: Record<string, unknown>
}

export interface ProvenanceEdge {
  from: string
  to: string
  relation: string
}

export interface ProvenanceGraph {
  version: 1
  nodes: ProvenanceNode[]
  edges: ProvenanceEdge[]
}

/** Build the full provenance graph from the live store (v7 §27 reverse-trace chain). */
export function buildProvenanceGraph(mem: BioticMemory): ProvenanceGraph {
  const nodes: ProvenanceNode[] = []
  const edges: ProvenanceEdge[] = []

  for (const e of mem.episodes) {
    nodes.push({
      ref: e.id,
      kind: 'episode',
      label: `Episode: ${truncate(e.content)}`,
      detail: { content: e.content, tags: e.context?.tags ?? [], salience: e.encoding.salience },
    })
  }
  for (const f of mem.facts) {
    nodes.push({
      ref: f.id,
      kind: 'fact',
      label: `Fact: ${truncate(f.content)}`,
      detail: { content: f.content, derivedFrom: f.derivedFrom },
    })
    for (const src of f.derivedFrom)
      edges.push({ from: f.id, to: src, relation: 'distilled-from' })
  }
  for (const p of mem.procedural) {
    nodes.push({
      ref: p.id,
      kind: 'procedural',
      label: `Procedural: ${truncate(p.content)}`,
      detail: { content: p.content, derivedFrom: p.derivedFrom },
    })
  }
  for (const w of mem.working) {
    nodes.push({
      ref: w.id,
      kind: 'working',
      label: `Working: ${truncate(w.content)}`,
      detail: { content: w.content },
    })
  }
  for (const b of mem.beliefs) {
    nodes.push({
      ref: b.id,
      kind: 'belief',
      label: `Belief: ${truncate(b.proposition)}`,
      detail: {
        proposition: b.proposition,
        status: b.status,
        owner: b.owner,
        confidence: b.confidence,
      },
    })
    for (const ev of b.evidenceIds)
      edges.push({ from: b.id, to: ev, relation: 'evidenced-by' })
    for (const ce of b.counterEvidenceIds)
      edges.push({ from: b.id, to: ce, relation: 'contested-by' })
  }
  for (const r of mem.beliefRevisions) {
    nodes.push({
      ref: r.id,
      kind: 'belief-revision',
      label: `Revision ${r.id}`,
      detail: { at: r.at, actor: r.actor, rationale: r.rationale, deltaLogit: r.deltaLogit },
    })
    edges.push({ from: r.id, to: r.beliefId, relation: 'revision-of' })
  }
  mem.beliefRejections.forEach((j, i) => {
    const ref = `rej_${j.at}_${i}`
    nodes.push({
      ref,
      kind: 'rejection',
      label: `Rejected: ${truncate(j.proposition)}`,
      detail: { proposition: j.proposition, reason: j.reason, at: j.at },
    })
  })

  return { version: 1, nodes, edges }
}

/**
 * Reverse-trace the upstream provenance chain of `targetRef`: from the target,
 * follow the outgoing edges (e.g. a belief → its evidence episodes, a fact → its
 * source episodes) to collect every source recursively. Returns the target first,
 * then its sources. Cycles are guarded by a visited set.
 */
export function traceProvenance(graph: ProvenanceGraph, targetRef: string): ProvenanceNode[] {
  const byRef = new Map(graph.nodes.map(n => [n.ref, n]))
  const outgoing = new Map<string, ProvenanceEdge[]>()
  for (const e of graph.edges) {
    if (!outgoing.has(e.from))
      outgoing.set(e.from, [])
    outgoing.get(e.from)!.push(e)
  }
  const chain: ProvenanceNode[] = []
  const seen = new Set<string>()
  const queue: string[] = [targetRef]
  while (queue.length > 0) {
    const ref = queue.shift()!
    if (seen.has(ref))
      continue
    seen.add(ref)
    const node = byRef.get(ref)
    if (node)
      chain.push(node)
    for (const e of outgoing.get(ref) ?? []) {
      if (!seen.has(e.to))
        queue.push(e.to)
    }
  }
  return chain
}

export interface SimpleExplanation {
  level: 'simple'
  text: string
}

export interface ResearchExplanation {
  level: 'research'
  summary: string
  chain: ProvenanceNode[]
  /** Score decomposition (ScoredCandidate.parts) when a query is supplied; else null. */
  scores: ScoreParts | null
  /** HAC endogenous state at explanation time (null when HAC disabled). */
  gating: { z: EndogenousState | null }
  /** The policy chain that produced this state (v7 §27: 模型 & 策略链). */
  policy: { gating: GatingCoefficients, hac: HacConfig | undefined }
}

export type Explanation = SimpleExplanation | ResearchExplanation

/**
 * Two-level explanation (v7 §27). `query` enables the research-level score
 * decomposition for memory refs; omit it to get the chain + policy only.
 */
export function explain(
  ref: string,
  level: 'simple' | 'research',
  mem: BioticMemory,
  opts?: { query?: string },
): Explanation {
  const graph = buildProvenanceGraph(mem)
  const node = graph.nodes.find(n => n.ref === ref)

  if (!node) {
    const fallback = `No provenance node found for "${ref}".`
    if (level === 'simple')
      return { level: 'simple', text: fallback }
    return {
      level: 'research',
      summary: fallback,
      chain: [],
      scores: null,
      gating: { z: mem.hacState() ?? null },
      policy: { gating: mem.config.gating, hac: mem.config.hac },
    }
  }

  if (level === 'simple')
    return { level: 'simple', text: simpleText(node) }

  const chain = traceProvenance(graph, ref)
  const scores = opts?.query ? mem.scoreCandidateById(opts.query, ref)?.parts ?? null : null
  return {
    level: 'research',
    summary: simpleText(node),
    chain,
    scores,
    gating: { z: mem.hacState() ?? null },
    policy: { gating: mem.config.gating, hac: mem.config.hac },
  }
}

function simpleText(node: ProvenanceNode): string {
  switch (node.kind) {
    case 'belief':
      return `Belief "${shorten(String(node.detail.proposition))}" — status=${String(node.detail.status)}, confidence=${String(node.detail.confidence)}.`
    case 'episode':
      return `Episode "${shorten(String(node.detail.content))}" was encoded (salience=${String(node.detail.salience)}).`
    case 'fact':
      return `Fact "${shorten(String(node.detail.content))}" distilled from ${(node.detail.derivedFrom as string[]).length} source episode(s).`
    default:
      return `${node.kind} "${shorten(node.label)}".`
  }
}

function truncate(s: string, n = 40): string {
  return s.length > n ? `${s.slice(0, n)}…` : s
}

function shorten(s: string, n = 60): string {
  return s.length > n ? `${s.slice(0, n)}…` : s
}
