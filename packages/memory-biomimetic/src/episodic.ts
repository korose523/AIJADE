/**
 * v7 §10.1 — 经历图 Episodic Evidence Graph（双图记忆中的「经历」一半）。
 *
 * 与 §10.2 信念图（`./belief`）的关系是本模块的设计核心：
 *   - 信念图保存「系统当前可使用的命题」，会**裁决**出唯一事实（accepted/contested/retracted）；
 *   - 经历图**只保存「发生过什么」和证据**，并且 **允许矛盾并存，不强行生成唯一事实**。
 *
 * 五类关系（§10.1）：
 *   Event ─observed_in→ Source            （证据来源，§6 要求 ≥1）
 *   Event ─involves→ Entity               （涉及的实体）
 *   Event ─before/after→ Event            （时序；建模为 before/after 两个有向 kind）
 *   Event ─caused_candidate→ Outcome      （**候选**因果，不是既成事实）
 *   Event ─expressed_as→ Audio/Motion/Action
 *
 * 两条硬不变量（可强制、可测）：
 *   1. **§6 无来源不入图**：事件必须带 ≥1 个 `observed_in` 来源才能入图；拒绝被计数，
 *      所以「可追踪率」是被度量的，而不是被假设的。
 *   2. **时序自洽**：before/after 不得成环 —— 环会让「先后顺序」失去意义。
 *      （注意：这是结构自洽，不是事实裁决；**证据内容互相矛盾是允许并保留的**。）
 *
 * 与 CBR 的衔接：`caused_candidate` 只提出**候选**因果；是否成立由 §12 的
 * ITE = Y(do(gate=1)) − Y(do(gate=0)) 检验（`./cbr`）。提出与检验分离，避免把候选当结论。
 *
 * 纯逻辑 + 单一可变容器，无外部依赖；opt-in，不介入记忆 durability/salience（H2c 兼容护盾）。
 */

/** §10.1 五类关系（before/after 拆成两个有向 kind 以便查询）。 */
export type EpisodicEdgeKind
  = | 'observed_in'
    | 'involves'
    | 'before'
    | 'after'
    | 'caused_candidate'
    | 'expressed_as'

export const EPISODIC_EDGE_KINDS: EpisodicEdgeKind[] = [
  'observed_in',
  'involves',
  'before',
  'after',
  'caused_candidate',
  'expressed_as',
]

/** `observed_in` 指向的证据来源。 */
export interface EpisodicSource {
  id: string
  trusted: boolean
  /** 内容摘要（如 sha256）。用于判定同一事件的多个来源是否互相矛盾。 */
  contentDigest?: string
  consentPolicy?: string
}

/** 经历图中的事件节点：只记「发生过什么」的引用，不存唯一事实。 */
export interface EpisodicEvent {
  id: string
  /** 事件内容的引用/摘要（不是被裁决的事实）。 */
  contentRef: string
  occurredAt: number
}

export interface EpisodicEdge {
  kind: EpisodicEdgeKind
  from: string
  to: string
  createdAt: number
  /** 仅 `observed_in` 边携带来源元数据。 */
  source?: EpisodicSource
  weight?: number
}

/**
 * 同一事件的多个来源内容互相矛盾。
 * **两侧全部保留** —— 这正是 §10.1「允许矛盾并存，不强行生成唯一事实」。
 */
export interface SourceContradiction {
  eventId: string
  kind: 'conflicting_source'
  sources: EpisodicSource[]
}

function isTemporal(kind: EpisodicEdgeKind): boolean {
  return kind === 'before' || kind === 'after'
}

/** 规范化时序边为 (earlier, later)。 */
function normalizeTemporal(edge: EpisodicEdge): [string, string] | null {
  if (edge.kind === 'before')
    return [edge.from, edge.to]
  if (edge.kind === 'after')
    return [edge.to, edge.from]
  return null
}

/**
 * §10.1 经历图。事件必须带来源入图（§6）；时序边不得成环；证据矛盾被保留并暴露。
 */
export class EpisodicGraph {
  private eventList: EpisodicEvent[] = []
  private eventIndex = new Map<string, EpisodicEvent>()
  private edges: EpisodicEdge[] = []
  /** 被拒绝的「无来源入图」次数 —— §6 合规是被计量的，不是被假设的。 */
  private refusalCount = 0

  /** 事件数。 */
  get size(): number {
    return this.eventList.length
  }

  /** 按 id 查事件。 */
  event(id: string): EpisodicEvent | undefined {
    return this.eventIndex.get(id)
  }

  events(): EpisodicEvent[] {
    return [...this.eventList]
  }

  /** §6 合规计数：试图无来源入图的次数。 */
  get refusals(): number {
    return this.refusalCount
  }

  /**
   * 加入事件。**必须**带 ≥1 个来源（§6「无来源禁止进」）。
   * 纯拒绝语义：返回 `{ok:false, reason}`，不抛错，且事件不进图。
   */
  addEvent(e: EpisodicEvent, sources: EpisodicSource[]): { ok: true } | { ok: false, reason: string } {
    if (this.eventIndex.has(e.id))
      return { ok: false, reason: `Episodic event "${e.id}" already present` }
    if (sources.length === 0) {
      this.refusalCount++
      return { ok: false, reason: 'Episodic event requires ≥1 observed_in source (v7 §6 traceability)' }
    }
    this.eventIndex.set(e.id, e)
    this.eventList.push(e)
    for (const s of sources)
      this.attachSource(e.id, s)
    return { ok: true }
  }

  /** 追加一个来源（佐证；若内容摘要不同则成为「并存矛盾」而非覆盖）。 */
  addSource(eventId: string, source: EpisodicSource): { ok: true } | { ok: false, reason: string } {
    if (!this.eventIndex.has(eventId))
      return { ok: false, reason: `Unknown episodic event "${eventId}"` }
    this.attachSource(eventId, source)
    return { ok: true }
  }

  private attachSource(eventId: string, source: EpisodicSource): void {
    this.edges.push({
      kind: 'observed_in',
      from: eventId,
      to: source.id,
      createdAt: Date.now(),
      source,
    })
  }

  /**
   * 加入一条关系边。
   * 时序边（before/after）额外要求：两端都是已知事件、非自环、且**不成环**。
   */
  addEdge(edge: EpisodicEdge): { ok: true } | { ok: false, reason: string } {
    if (!EPISODIC_EDGE_KINDS.includes(edge.kind))
      return { ok: false, reason: `Unknown episodic edge kind "${edge.kind}"` }
    if (!this.eventIndex.has(edge.from))
      return { ok: false, reason: `Unknown source event "${edge.from}"` }

    if (isTemporal(edge.kind)) {
      if (!this.eventIndex.has(edge.to))
        return { ok: false, reason: `Temporal edge requires a known target event, got "${edge.to}"` }
      if (edge.from === edge.to)
        return { ok: false, reason: 'Temporal self-loop is meaningless' }
      if (this.createsCycle(edge))
        return { ok: false, reason: 'Temporal edge would create a cycle (before/after must stay acyclic)' }
    }
    this.edges.push(edge)
    return { ok: true }
  }

  /** 试探性地判断加入该时序边是否会成环（在 before/after 的规范化方向上做可达性检查）。 */
  private createsCycle(candidate: EpisodicEdge): boolean {
    const pair = normalizeTemporal(candidate)
    if (!pair)
      return false
    const [earlier, later] = pair
    // 若 later 已能到达 earlier，则加入 earlier→later 成环
    return this.reachable(later, earlier)
  }

  /** 在规范化时序图中做 BFS 可达性判断。 */
  private reachable(from: string, to: string): boolean {
    const adj = new Map<string, string[]>()
    for (const e of this.edges) {
      const p = normalizeTemporal(e)
      if (!p)
        continue
      const [a, b] = p
      const list = adj.get(a) ?? []
      list.push(b)
      adj.set(a, list)
    }
    const seen = new Set<string>([from])
    const queue = [from]
    while (queue.length) {
      const cur = queue.shift() as string
      if (cur === to)
        return true
      for (const nxt of adj.get(cur) ?? []) {
        if (!seen.has(nxt)) {
          seen.add(nxt)
          queue.push(nxt)
        }
      }
    }
    return false
  }

  /** 某事件的全部证据来源。 */
  sourcesOf(eventId: string): EpisodicSource[] {
    return this.edges
      .filter(e => e.kind === 'observed_in' && e.from === eventId && e.source)
      .map(e => e.source as EpisodicSource)
  }

  /** 从某事件出发的边，可按 kind 过滤。 */
  edgesFrom(eventId: string, kind?: EpisodicEdgeKind): EpisodicEdge[] {
    return this.edges.filter(e => e.from === eventId && (kind === undefined || e.kind === kind))
  }

  allEdges(): EpisodicEdge[] {
    return [...this.edges]
  }

  /** 候选因果（§10.1 `caused_candidate`）—— **候选**，是否成立由 CBR 的 ITE 检验。 */
  causalCandidates(eventId: string): string[] {
    return this.edges
      .filter(e => e.kind === 'caused_candidate' && e.from === eventId)
      .map(e => e.to)
  }

  /** 具身表达（audio / motion / action）。 */
  expressionsOf(eventId: string): string[] {
    return this.edges
      .filter(e => e.kind === 'expressed_as' && e.from === eventId)
      .map(e => e.to)
  }

  /** 涉及的实体。 */
  entitiesOf(eventId: string): string[] {
    return this.edges
      .filter(e => e.kind === 'involves' && e.from === eventId)
      .map(e => e.to)
  }

  /**
   * §6 可追踪率 = 有 ≥1 来源的事件 / 全部事件。
   * 入图时已强制 ≥1 来源，故此值应恒为 1；真正的合规信号是 `refusals`。
   */
  traceabilityRate(): number {
    if (this.eventList.length === 0)
      return 1
    const withSource = this.eventList.filter(e => this.sourcesOf(e.id).length > 0).length
    return withSource / this.eventList.length
  }

  /**
   * 并列存在的证据矛盾：**同一事件**有多个来源且 `contentDigest` 不同。
   * 两侧都保留、都不裁决（§10.1）。
   */
  contradictions(): SourceContradiction[] {
    const out: SourceContradiction[] = []
    for (const e of this.eventList) {
      const digests = new Set<string>()
      let hasDigest = false
      for (const s of this.sourcesOf(e.id)) {
        if (s.contentDigest !== undefined) {
          hasDigest = true
          digests.add(s.contentDigest)
        }
      }
      if (hasDigest && digests.size > 1)
        out.push({ eventId: e.id, kind: 'conflicting_source', sources: this.sourcesOf(e.id) })
    }
    return out
  }

  /**
   * 由 before/after 推出的拓扑序（确定性：同层按 occurredAt 再按 id）。
   * 若存在环则返回 null（正常路径下 `addEdge` 已阻止环）。
   */
  temporalOrder(): string[] | null {
    const indeg = new Map<string, number>()
    const adj = new Map<string, string[]>()
    for (const e of this.eventList) {
      indeg.set(e.id, 0)
      adj.set(e.id, [])
    }
    for (const e of this.edges) {
      const p = normalizeTemporal(e)
      if (!p)
        continue
      const [a, b] = p
      if (!indeg.has(a) || !indeg.has(b)) {
        continue
      }
      const neighbors = adj.get(a) as string[]
      neighbors.push(b)
      indeg.set(b, (indeg.get(b) as number) + 1)
    }
    const byId = new Map(this.eventList.map(e => [e.id, e]))
    const ready = this.eventList.filter(e => (indeg.get(e.id) as number) === 0).map(e => e.id)
    const order: string[] = []
    while (ready.length) {
      ready.sort((x, y) => {
        const ex = byId.get(x) as EpisodicEvent
        const ey = byId.get(y) as EpisodicEvent
        return ex.occurredAt - ey.occurredAt || (x < y ? -1 : x > y ? 1 : 0)
      })
      const cur = ready.shift() as string
      order.push(cur)
      for (const nxt of adj.get(cur) ?? []) {
        indeg.set(nxt, (indeg.get(nxt) as number) - 1)
        if ((indeg.get(nxt) as number) === 0)
          ready.push(nxt)
      }
    }
    return order.length === this.eventList.length ? order : null
  }
}
