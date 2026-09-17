import { describe, expect, it } from 'vitest'

import { validatePerformanceIntent } from './contracts-v8'
import { AIJADE_TOPICS, safeParseAijadeEvent } from './events'
import {
  buildLpmRenderReadyEvent,
  buildPerformanceIntent,
  buildPersonaRenderRequestedEvent,
  clampExpression,
  DEFAULT_CONSISTENCY_THRESHOLDS,
  deriveChannels,
  identityConsistencyCheck,
  mapPersonaToExpression,
  NEUTRAL_EXPRESSION,
  scheduleDuplex,
} from './pef'

describe('clampExpression (§52.3)', () => {
  it('clamps valence to [−1,1] and all other components to [0,1]', () => {
    const e = clampExpression({
      valence: 5,
      arousal: -1,
      dominance: 2,
      intimacy: 0.5,
      certainty: Number.NaN,
      curiosity: 0.5,
      playfulness: 1.5,
      reflection: -0.5,
      urgency: 0.5,
    })
    expect(e.valence).toBe(1)
    expect(e.arousal).toBe(0)
    expect(e.dominance).toBe(1)
    expect(e.intimacy).toBe(0.5)
    expect(e.certainty).toBe(0) // NaN → 0
    expect(e.playfulness).toBe(1)
    expect(e.reflection).toBe(0)
  })

  it('keeps an already-legal vector unchanged', () => {
    const e = clampExpression({ ...NEUTRAL_EXPRESSION })
    expect(e).toEqual(NEUTRAL_EXPRESSION)
  })
})

describe('mapPersonaToExpression (§52.2)', () => {
  it('returns a legal vector for a bare dialogue act', () => {
    const e = mapPersonaToExpression({ dialogueAct: 'inform' })
    for (const [k, val] of Object.entries(e)) {
      if (k === 'valence')
        expect(val).toBeGreaterThanOrEqual(-1)
      else
        expect(val).toBeGreaterThanOrEqual(0)
      expect(val).toBeLessThanOrEqual(1)
    }
  })

  it('comfort raises intimacy and lowers arousal relative to inform', () => {
    const inform = mapPersonaToExpression({ dialogueAct: 'inform' })
    const comfort = mapPersonaToExpression({ dialogueAct: 'comfort' })
    expect(comfort.intimacy).toBeGreaterThan(inform.intimacy)
    expect(comfort.arousal).toBeLessThan(inform.arousal)
  })

  it('question raises curiosity', () => {
    const e = mapPersonaToExpression({ dialogueAct: 'question' })
    expect(e.curiosity).toBeGreaterThan(NEUTRAL_EXPRESSION.curiosity)
  })

  it('transient expressive state blends with the character baseline', () => {
    const calm = mapPersonaToExpression({ dialogueAct: 'inform' })
    const excited = mapPersonaToExpression({
      dialogueAct: 'inform',
      expressiveState: { arousal: 1, valence: 0.8 },
    })
    expect(excited.arousal).toBeGreaterThan(calm.arousal)
    expect(excited.valence).toBeGreaterThan(calm.valence)
  })

  it('relationship formality suppresses playfulness; intimacy raises intimacy', () => {
    const casual = mapPersonaToExpression({ dialogueAct: 'inform', relationship: { formality: 0, intimacy: 0.9 } })
    const formal = mapPersonaToExpression({ dialogueAct: 'inform', relationship: { formality: 1, intimacy: 0.9 } })
    expect(formal.playfulness).toBeLessThan(casual.playfulness)
    expect(casual.intimacy).toBeGreaterThan(NEUTRAL_EXPRESSION.intimacy)
  })

  it('developmental interests feed curiosity (§52.2 — growth, not consciousness claims)', () => {
    const e = mapPersonaToExpression({
      dialogueAct: 'inform',
      developmental: { interests: ['a', 'b', 'c'], milestones: ['m1'] },
    })
    const plain = mapPersonaToExpression({ dialogueAct: 'inform' })
    expect(e.curiosity).toBeGreaterThan(plain.curiosity)
    expect(e.reflection).toBeGreaterThan(plain.reflection)
  })

  it('never exceeds legal bounds even with extreme inputs', () => {
    const e = mapPersonaToExpression({
      dialogueAct: 'celebrate',
      character: { valence: 1, arousal: 1, playfulness: 1 },
      expressiveState: { valence: 1, arousal: 1 },
      relationship: { intimacy: 1, formality: 0 },
      developmental: { interests: Array.from({ length: 50 }, (_, i) => `i${i}`) },
    })
    expect(e.valence).toBeLessThanOrEqual(1)
    expect(e.arousal).toBeLessThanOrEqual(1)
    expect(e.curiosity).toBeLessThanOrEqual(1)
    expect(e.playfulness).toBeLessThanOrEqual(1)
  })
})

describe('deriveChannels (§52.2/§52.3)', () => {
  it('produces backend-agnostic channel directives with prosody ∈ [0,1]', () => {
    const c = deriveChannels(NEUTRAL_EXPRESSION, 'inform')
    expect(c.textStyle).toBeTruthy()
    expect(c.face).toBeTruthy()
    expect(c.gaze).toBeTruthy()
    expect(c.gesture).toBeTruthy()
    expect(c.posture).toBeTruthy()
    expect(c.cameraBehavior).toBeTruthy()
    for (const v of Object.values(c.voiceProsody)) {
      expect(v).toBeGreaterThanOrEqual(0)
      expect(v).toBeLessThanOrEqual(1)
    }
  })

  it('high urgency raises prosody rate; positive valence raises pitch', () => {
    const calm = deriveChannels({ ...NEUTRAL_EXPRESSION, urgency: 0, arousal: 0.3 }, 'inform')
    const urgent = deriveChannels({ ...NEUTRAL_EXPRESSION, urgency: 1, arousal: 0.9, valence: 0.6 }, 'inform')
    expect(urgent.voiceProsody.rate).toBeGreaterThan(calm.voiceProsody.rate)
    expect(urgent.voiceProsody.pitch).toBeGreaterThan(calm.voiceProsody.pitch)
  })

  it('backchannel act maps to backchannel turn-taking; question yields the floor', () => {
    expect(deriveChannels(NEUTRAL_EXPRESSION, 'backchannel').turnTaking).toBe('backchannel')
    expect(deriveChannels(NEUTRAL_EXPRESSION, 'question').turnTaking).toBe('yield')
    expect(deriveChannels(NEUTRAL_EXPRESSION, 'inform').turnTaking).toBe('hold')
  })

  it('high-valence high-arousal expression selects a bright smile', () => {
    const c = deriveChannels({ ...NEUTRAL_EXPRESSION, valence: 0.6, arousal: 0.8 }, 'celebrate')
    expect(c.face).toBe('bright_smile')
  })
})

describe('buildPerformanceIntent (§52.4 — time-marked incremental intents)', () => {
  const ids = { id: 'pi-1', agentId: 'agent-1', userScope: 'user-1', personaSnapshotRef: 'snap:abc' }

  it('builds an intent that passes contract #28 validation', () => {
    const intent = buildPerformanceIntent(
      { dialogueAct: 'comfort', sceneContext: 'evening_chat', relationship: { intimacy: 0.8 } },
      ids,
      1_700_000_000_000,
      1500,
    )
    const v = validatePerformanceIntent(intent)
    expect(v.ok).toBe(true)
  })

  it('propagates scene context and time marker', () => {
    const intent = buildPerformanceIntent({ dialogueAct: 'inform', sceneContext: 'study' }, ids, 42, 1000)
    expect(intent.sceneContext).toBe('study')
    expect(intent.timeMarked).toBe(42)
    expect(intent.duration).toBe(1000)
    expect(intent.schema).toBe('aijade.performance_intent@1')
  })
})

describe('scheduleDuplex (§52.4 — full-duplex scheduling)', () => {
  it('listen signals trigger the backchannel planner', () => {
    const d = scheduleDuplex({ type: 'listen_signal' })
    expect(d.turnTaking).toBe('backchannel')
    expect(d.motion).toContain('micro_expression')
    expect(d.abortSpeech).toBe(false)
  })

  it('partial semantics trigger anticipatory gaze/posture preparation', () => {
    const d = scheduleDuplex({ type: 'partial_semantics' })
    expect(d.turnTaking).toBe('hold')
    expect(d.motion).toContain('anticipatory')
    expect(d.abortSpeech).toBe(false)
  })

  it('committed clauses produce prosody + gesture phrase + lip timeline', () => {
    const d = scheduleDuplex({ type: 'committed_clause' })
    expect(d.motion).toContain('lip_timeline')
    expect(d.abortSpeech).toBe(false)
  })

  it('user interruption aborts speech, blends out motion and yields', () => {
    const d = scheduleDuplex({ type: 'user_interruption' })
    expect(d.turnTaking).toBe('yield')
    expect(d.abortSpeech).toBe(true)
    expect(d.blendOutMotion).toBe(true)
    expect(d.motion).toBe('listen_pose')
  })
})

describe('identityConsistencyCheck (§52.5)', () => {
  it('passes a clean observation with no degradation', () => {
    const v = identityConsistencyCheck({})
    expect(v.ok).toBe(true)
    expect(v.degrade).toBe('none')
  })

  it('passes observations below all thresholds', () => {
    const v = identityConsistencyCheck({
      faceIdentityDrift: 0.1,
      clothingDrift: 0.1,
      voiceprintDrift: 0.1,
      prosodyDrift: 0.1,
      emotionSemanticConflict: 0.1,
      lipSyncDeviationMs: 50,
      sceneContinuityBreak: false,
    })
    expect(v.ok).toBe(true)
  })

  it('face identity drift degrades to pure voice (identity-level failure)', () => {
    const v = identityConsistencyCheck({ faceIdentityDrift: 0.5 })
    expect(v.ok).toBe(false)
    if (!v.ok) {
      expect(v.degrade).toBe('voice')
      expect(v.failures.map(f => f.kind)).toContain('face_identity_drift')
    }
  })

  it('forbidden actions and boundary violations degrade to pure voice', () => {
    const v = identityConsistencyCheck({ forbiddenActions: ['break_character_dance'] })
    expect(v.ok).toBe(false)
    if (!v.ok)
      expect(v.degrade).toBe('voice')

    const v2 = identityConsistencyCheck({ boundaryViolations: ['overfamiliar_honorifics'] })
    expect(v2.ok).toBe(false)
    if (!v2.ok)
      expect(v2.degrade).toBe('voice')
  })

  it('scene continuity break is identity-level (voice), not avatar', () => {
    const v = identityConsistencyCheck({ sceneContinuityBreak: true })
    expect(v.ok).toBe(false)
    if (!v.ok)
      expect(v.degrade).toBe('voice')
  })

  it('expression-level failures only degrade to controllable avatar', () => {
    const v = identityConsistencyCheck({
      prosodyDrift: 0.9,
      lipSyncDeviationMs: 500,
      emotionSemanticConflict: 0.9,
      clothingDrift: 0.9,
    })
    expect(v.ok).toBe(false)
    if (!v.ok) {
      expect(v.degrade).toBe('avatar')
      expect(v.failures).toHaveLength(4)
    }
  })

  it('identity-level failure dominates when mixed with expression-level failures', () => {
    const v = identityConsistencyCheck({
      faceIdentityDrift: 0.9,
      lipSyncDeviationMs: 500,
    })
    expect(v.ok).toBe(false)
    if (!v.ok)
      expect(v.degrade).toBe('voice')
  })

  it('respects custom thresholds', () => {
    const strict = { ...DEFAULT_CONSISTENCY_THRESHOLDS, prosodyDrift: 0.1 }
    const v = identityConsistencyCheck({ prosodyDrift: 0.2 }, strict)
    expect(v.ok).toBe(false)
    const lenient = identityConsistencyCheck({ prosodyDrift: 0.2 })
    expect(lenient.ok).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// §52.5 — 渲染请求事件（内核 → 具身侧）
// ---------------------------------------------------------------------------

const ENVELOPE = {
  event_id: 'evt_pef_1',
  trace_id: 'tr_pef_1',
  correlation_id: 'cor_pef_1',
  timestamp: 1_700_000_000_000,
  producer: 'pef',
  // 信封的观察/传输字段是**必填**的（与 HTTP 边界同集），测试里如实给出。
  origin_device: 'test-device',
  privacy_level: 1 as const,
  evidence_refs: [],
  causal_context_refs: ['tr_pef_1'],
  risk_score: 0,
  idempotency_key: 'idem_pef_1',
  replay_mode: 'live' as const,
  risk_level: 'low' as const,
}

function intent(over: Partial<{ id: string, personaSnapshotRef: string }> = {}) {
  return buildPerformanceIntent(
    { dialogueAct: 'inform' },
    {
      id: over.id ?? 'pi_1',
      agentId: 'agent-1',
      userScope: 'user-1',
      personaSnapshotRef: over.personaSnapshotRef ?? 'ps_1',
    },
    ENVELOPE.timestamp,
    800,
  )
}

describe('pEF — persona.render_requested 构造', () => {
  it('合法意图 ⇒ 合法事件，且 topic 属于登记集合', () => {
    const ev = buildPersonaRenderRequestedEvent(intent(), 'session-1', ENVELOPE)
    expect(ev.topic).toBe('aijade.persona.render_requested')
    expect((AIJADE_TOPICS as readonly string[]).includes(ev.topic)).toBe(true)
    expect(safeParseAijadeEvent(ev).success).toBe(true)
  })

  it('persona_snapshot_ref 与 PerformanceIntent 同源同值（§52.5 可审计）', () => {
    const i = intent({ personaSnapshotRef: 'ps_abc' })
    const ev = buildPersonaRenderRequestedEvent(i, 'session-1', ENVELOPE)
    const p = ev.payload as Record<string, unknown>
    expect(p.persona_snapshot_ref).toBe(i.personaSnapshotRef)
    expect(p.persona_snapshot_ref).toBe('ps_abc')
  })

  it('intent_ref 就是意图 id，使 lpm.render_ready.render_ref 可回指', () => {
    const i = intent({ id: 'pi_xyz' })
    const ev = buildPersonaRenderRequestedEvent(i, 'session-1', ENVELOPE)
    expect((ev.payload as Record<string, unknown>).intent_ref).toBe('pi_xyz')
  })

  it('空 personaSnapshotRef ⇒ 抛错（结构上排除「先渲染再补身份」）', () => {
    expect(() => buildPersonaRenderRequestedEvent(intent({ personaSnapshotRef: '' }), 'session-1', ENVELOPE)).toThrow()
  })

  it('事件不携带 expression/通道参数（那些属于 PerformanceIntent 本体）', () => {
    const ev = buildPersonaRenderRequestedEvent(intent(), 'session-1', ENVELOPE)
    const p = ev.payload as Record<string, unknown>
    expect(Object.keys(p).sort()).toEqual(['intent_ref', 'persona_snapshot_ref', 'session_id'])
  })
})

describe('pEF — lpm.render_ready 构造（请求/回执对的回执端）', () => {
  const APPLIED = 'emotion.intensity=0.4|emotion.preset=s:happy'

  it('合法回执 ⇒ 合法事件，且 topic 属于登记集合', () => {
    const ev = buildLpmRenderReadyEvent(
      { sessionId: 'session-1', renderRef: 'pi_1', appliedParamsHash: APPLIED },
      ENVELOPE,
    )
    expect(ev.topic).toBe('aijade.lpm.render_ready')
    expect((AIJADE_TOPICS as readonly string[]).includes(ev.topic)).toBe(true)
    expect(safeParseAijadeEvent(ev).success).toBe(true)
  })

  it('render_ref 与请求端 intent_ref 同源同值，使回执可回指（配对不靠推断）', () => {
    const req = buildPersonaRenderRequestedEvent(intent({ id: 'pi_pair' }), 'session-1', ENVELOPE)
    const intentRef = (req.payload as Record<string, unknown>).intent_ref
    const ready = buildLpmRenderReadyEvent(
      { sessionId: 'session-1', renderRef: intentRef as string, appliedParamsHash: APPLIED },
      ENVELOPE,
    )
    expect((ready.payload as Record<string, unknown>).render_ref).toBe(intentRef)
    expect((ready.payload as Record<string, unknown>).render_ref).toBe('pi_pair')
  })

  it('applied_params_hash 原样透传，不被本函数改写', () => {
    const ev = buildLpmRenderReadyEvent(
      { sessionId: 's', renderRef: 'rr', appliedParamsHash: APPLIED },
      ENVELOPE,
    )
    expect((ev.payload as Record<string, unknown>).applied_params_hash).toBe(APPLIED)
  })

  it('空 appliedParamsHash ⇒ 抛错，且错误说明"什么都没写"（不是泛泛的校验失败）', () => {
    expect(() =>
      buildLpmRenderReadyEvent({ sessionId: 's', renderRef: 'rr', appliedParamsHash: '' }, ENVELOPE),
    ).toThrow(/没有渲染发生|不可表达/)
  })

  it('assetVersionHash 缺省 ⇒ payload 不含该键（而非 undefined 键）', () => {
    const ev = buildLpmRenderReadyEvent({ sessionId: 's', renderRef: 'rr', appliedParamsHash: APPLIED }, ENVELOPE)
    const p = ev.payload as Record<string, unknown>
    expect('asset_version_hash' in p).toBe(false)
    expect(Object.keys(p).sort()).toEqual(['applied_params_hash', 'render_ref', 'session_id'])
  })

  it('assetVersionHash 为空串 ⇒ 降级为缺省（空串不得伪装成"已计算"）', () => {
    const ev = buildLpmRenderReadyEvent(
      { sessionId: 's', renderRef: 'rr', appliedParamsHash: APPLIED, assetVersionHash: '' },
      ENVELOPE,
    )
    expect('asset_version_hash' in (ev.payload as Record<string, unknown>)).toBe(false)
  })

  it('assetVersionHash 有值 ⇒ 原样带出，且键集合固定为四个', () => {
    const ev = buildLpmRenderReadyEvent(
      { sessionId: 's', renderRef: 'rr', appliedParamsHash: APPLIED, assetVersionHash: 'avh_1' },
      ENVELOPE,
    )
    const p = ev.payload as Record<string, unknown>
    expect(p.asset_version_hash).toBe('avh_1')
    expect(Object.keys(p).sort()).toEqual([
      'applied_params_hash',
      'asset_version_hash',
      'render_ref',
      'session_id',
    ])
  })

  it('空 sessionId / 空 renderRef ⇒ 抛错（身份不可为空白）', () => {
    expect(() =>
      buildLpmRenderReadyEvent({ sessionId: '', renderRef: 'rr', appliedParamsHash: APPLIED }, ENVELOPE),
    ).toThrow()
    expect(() =>
      buildLpmRenderReadyEvent({ sessionId: 's', renderRef: '', appliedParamsHash: APPLIED }, ENVELOPE),
    ).toThrow()
  })
})
