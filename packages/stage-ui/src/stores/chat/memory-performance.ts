/**
 * Bridges the memory engine + structured-performance layer into AIJADE's realtime
 * chat pipeline (`createChatOrchestratorRuntime`) through AIJADE's own extension
 * points — no modification of the orchestrator internals required.
 *
 * - Memory: recalled context is injected as a `runtimeContextProvider` (the same
 *   hook AIJADE's Minecraft integration uses), and each turn is persisted into the
 *   episodic tier via the `*MessageAppended` lifecycle callbacks.
 * - Performance: the orchestrator's token hooks (`onTokenLiteral` /
 *   `onTokenSpecial` / `onStreamEnd`) drive a {@link PerformanceDirector} whose
 *   state the UI can subscribe to in real time.
 *
 * Design mirrors the references the user supplied:
 * - AkaneCompanionLab / Hermes Scope-Recall / "活人感" long-term memory videos →
 *   the layered memory engine (already in `@proj-aijade/memory-pgvector`).
 * - LPM 1.0 (arXiv:2604.07823) → the three real-time states (listen / speak /
 *   silence) + multimodal performance markers.
 * - StreamPet / "告别人工智障式沉默" (BV1yT96mE6t) → `speak` is entered on the
 *   FIRST streamed token, eliminating the idle-before-first-word gap.
 */
import type { ChatOrchestratorRuntime, ChatOrchestratorRuntimeDeps, ContextMessage } from '@proj-aijade/core-agent'
import type { PerformanceDirector, PerformanceEmotion, PerformanceState } from '@proj-aijade/memory-pgvector/performance'
import type { MemoryPort } from '@proj-aijade/memory-pgvector/port'

import type { AppliedParams, LpmRenderReadyReceipt } from '../../utils/render-receipt'

import { ContextUpdateStrategy } from '@proj-aijade/server-sdk'
import { nanoid } from 'nanoid'

import {

  buildRenderReceipt,

  mintRenderRef,
} from '../../utils/render-receipt'

const MEMORY_CONTEXT_ID = 'memory:recall'

/**
 * Owns the memory side of the pipeline: a FIFO recall buffer (the orchestrator's
 * `runtimeContextProviders` are synchronous, so we pre-compute the recall for
 * each send and let the provider drain it in FIFO order) plus turn ingestion.
 */
export function createMemoryBridge(port: MemoryPort) {
  const pendingRecalls: string[] = []

  const provider = (): ContextMessage | null => {
    const text = pendingRecalls.shift() ?? ''
    if (!text)
      return null
    return {
      id: nanoid(),
      contextId: MEMORY_CONTEXT_ID,
      strategy: ContextUpdateStrategy.ReplaceSelf,
      text,
      createdAt: Date.now(),
    }
  }

  function wrapDeps(deps: ChatOrchestratorRuntimeDeps): ChatOrchestratorRuntimeDeps {
    return {
      ...deps,
      runtimeContextProviders: [...(deps.runtimeContextProviders ?? []), provider],
      onUserMessageAppended: (event) => {
        deps.onUserMessageAppended?.(event)
        void port.ingestUser(event.messageText)
      },
      onAssistantMessageAppended: (event) => {
        deps.onAssistantMessageAppended?.(event)
        void port.ingestAssistant(event.messageText)
      },
      onAssistantTurnReady: (event) => {
        deps.onAssistantTurnReady?.(event)
        void port.maybeCompact?.()
      },
    }
  }

  /** Pre-compute the recall for a send so the (sync) provider can drain it. */
  async function prepareSend(userText: string): Promise<void> {
    const recall = await port.recall(userText)
    pendingRecalls.push(recall ?? '')
  }

  return { wrapDeps, prepareSend }
}

/**
 * Owns the performance side: wires the orchestrator's token stream into a
 * {@link PerformanceDirector} and surfaces its state via `onState`.
 *
 * The returned `feedUserAudio` is the LPM dual-stream "listen audio branch"
 * entry point: push the user's live speech level (0..1) and an optional emotion
 * hint from the ASR / audio pipeline so the avatar's listening reactions become
 * richer and empathetically tuned to *how* the user is speaking.
 */
export function createPerformanceBridge(
  director: PerformanceDirector,
  onState: (state: PerformanceState) => void,
  options?: {
    /**
     * 当前活跃 session 的 id 解析器（由编排层注入）。`render_ref` 的归档维度之一，
     * 必须稳定。缺失时 `recordAppliedParams` 静默跳过（无法铸造稳定的回指身份，
     * 而不是把回执写成一个空 session）。
     */
    getSessionId?: () => string | undefined
    /**
     * 模型资产身份哈希的解析器（由编排层注入）。本文件不直接读 settings store，
     * 以免引入耦合——该值来自 `useSettingsStageModel().stageModelAssetVersionHash`，
     * 是**已 async 解析过**的值，此处只同步读取，**不要 await**。可能为 undefined
     * （资产哈希尚未就绪），`buildRenderReceipt` 会据此降级为缺省。
     */
    getAssetVersionHash?: () => string | undefined
    /** 回执组装成功后的回调（由编排层注入，例如存进 store）。undefined 则仅静默跳过。 */
    onRenderReceipt?: (receipt: LpmRenderReadyReceipt) => void
  },
) {
  // 轮界计数：每次 `onMessageSendStarted` 进入新一轮。渲染发生在流式过程中，
  // 自然归属到"当前"这一轮。`mintRenderRef` 据此铸出确定性的回指身份。
  let turnSeq = 0
  const getSessionId = options?.getSessionId
  const getAssetVersionHash = options?.getAssetVersionHash
  const onRenderReceipt = options?.onRenderReceipt

  function wrapDeps(deps: ChatOrchestratorRuntimeDeps): ChatOrchestratorRuntimeDeps {
    return {
      ...deps,
      onMessageSendStarted: (event) => {
        deps.onMessageSendStarted?.(event)
        director.enterListen()
        onState(director.snapshot())
        turnSeq++
      },
    }
  }

  function registerHooks(runtime: ChatOrchestratorRuntime): void {
    runtime.hooks.onTokenSpecial(async (special) => {
      director.applyMarkers(special)
      onState(director.snapshot())
    })
    runtime.hooks.onTokenLiteral(async (literal) => {
      director.onToken(literal)
      onState(director.snapshot())
    })
    runtime.hooks.onStreamEnd(async () => {
      director.onTurnEnd()
      onState(director.snapshot())
    })
  }

  /** LPM dual-stream audio cue — see {@link PerformanceDirector.feedUserAudio}. */
  function feedUserAudio(level: number, emotionHint?: PerformanceEmotion | null): void {
    director.feedUserAudio(level, emotionHint)
  }

  /**
   * 把渲染器本轮实际写入的参数汇总成一条 `aijade.lpm.render_ready` 回执。
   *
   * 三种结局（刻意区分）：
   * - `params` 为空 map ⇒ `buildRenderReceipt` 返回 `undefined`，这里一并返回
   *   `undefined` 且**不**调用 `onRenderReceipt`。这是"什么都没写"的合法跳过，不是错误。
   * - 没有活跃 session（`getSessionId` 返回空/undefined）⇒ 无法铸造稳定的 `render_ref`，
   *   同样返回 `undefined` 静默跳过，避免让渲染路径崩溃。
   * - 正常 ⇒ 返回通过本地 schema 校验的回执，并在 `onRenderReceipt` 存在时回调它。
   *
   * 注意：本函数被 `VRMModel` 的 `onAppliedParams` 在 `applyPerformance` 同步路径里调用，
   * 故任何异常都可能中断渲染——上面的空/缺省守卫正是为此而设。
   */
  function recordAppliedParams(params: AppliedParams): LpmRenderReadyReceipt | undefined {
    const sessionId = getSessionId?.() ?? ''
    if (!sessionId)
      return undefined
    const receipt = buildRenderReceipt({
      sessionId,
      renderRef: mintRenderRef(sessionId, turnSeq),
      appliedParams: params,
      assetVersionHash: getAssetVersionHash?.(),
    })
    // buildRenderReceipt 在 appliedParams 为空时返回 undefined（合法跳过，非错误）。
    if (receipt)
      onRenderReceipt?.(receipt)
    return receipt
  }

  // Self-driven tick: the orchestrator's token stream only emits on token / special /
  // stream-end events, so `director.tick()` would otherwise never run in production
  // (grep confirms it is only called from tests + IdleSpontaneousController). Without
  // this loop, `feedUserAudio`'s smoothed `_listenArousal` is never sampled/emit-ted,
  // so the #103 overlay's `listenArousal` bar would stay frozen at 0 while listening.
  // Drive it on a timer so listening reactions animate AND `listenArousal` is sampled
  // into the snapshot and pushed to the UI in real time. This is the single throttled
  // sampler — deliberately NOT the per-audio-frame path the `feedUserAudio` doc-comment
  // warns against (the audio analyser taps `feedUserAudio` at ~80ms; we emit once here).
  const tickTimer = setInterval(() => {
    director.tick()
    onState(director.snapshot())
  }, 100)

  /** Stop the self-driven tick loop (called on store teardown / HMR dispose). */
  function stop(): void {
    clearInterval(tickTimer)
  }

  return { wrapDeps, registerHooks, feedUserAudio, recordAppliedParams, stop }
}
