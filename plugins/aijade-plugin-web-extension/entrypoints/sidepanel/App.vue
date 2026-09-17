<script lang="ts" setup>
import { Button, Callout } from '@proj-aijade/ui'
import { computed, onMounted } from 'vue'

import { useSidePanelStore } from './stores'

/**
 * v10 §15.1 Companion Sidebar。
 *
 * 四块内容（可折叠）：
 * 1. 摘要卡片 —— 当前页面/选中文本的**归约后**证据文本；
 * 2. 视频字幕要点 —— `time_spans` 时间码 + 规范化 caption；
 * 3. 观点与评价 —— `claims`（含 confidence）+ `uncertainty_notes`，并**列出证据引用**
 *    （`content_hash` / `transcript_hash` / `evaluation_target`）以便回放；
 * 4. 风险提示 —— 不确定性、信息缺口、可能误读。
 *
 * 安全边界（v10 §15.5）：本组件只**展示**由 background 归约/评价得到的证据态，
 * 绝不构造 `intent_ref` / `render_ref` 这类因果关键 ref，也不直接调用 LLM 或服务端。
 */

/** 「网页文本观察」payload（与 `aijade.video.observation.webpage_text` 契约同形）。 */
interface WebpageTextPayload {
  source_url: string
  content_hash: string
  spans: { start_offset: number, end_offset: number, label?: string }[]
  observation_text: string
}

/** 「视频字幕观察」payload（与 `aijade.video.observation.video_transcript` 契约同形）。 */
interface VideoTranscriptPayload {
  video_id: string
  transcript_hash: string
  time_spans: { start_ms: number, end_ms: number, text: string }[]
  caption_text: string
}

const store = useSidePanelStore()

onMounted(() => store.init())

const pagePayload = computed<WebpageTextPayload | null>(() => {
  const evidence = store.pageEvidence.value
  return evidence ? (evidence.payload as unknown as WebpageTextPayload) : null
})

const subtitlePayload = computed<VideoTranscriptPayload | null>(() => {
  const evidence = store.subtitleEvidence.value
  return evidence ? (evidence.payload as unknown as VideoTranscriptPayload) : null
})

const opinion = computed(() => store.opinion.value)

/** 证据引用（回放锚点）：只列出确实参与归约的 hash，不做任何推导。 */
const evidenceRefs = computed(() => {
  const refs: { label: string, value: string }[] = []
  if (pagePayload.value)
    refs.push({ label: 'page content_hash', value: pagePayload.value.content_hash })
  if (subtitlePayload.value)
    refs.push({ label: 'subtitle transcript_hash', value: subtitlePayload.value.transcript_hash })
  if (opinion.value)
    refs.push({ label: 'evaluation_target', value: opinion.value.payload.evaluation_target })
  return refs
})

/** 信息缺口：诚实列出"本来就没有拿到"的输入，而不是让 UI 看起来完整。 */
const gaps = computed(() => {
  const list: string[] = []
  if (!store.pageEvidence.value)
    list.push('尚未捕获页面文本（摘要卡片无输入）')
  if (!store.subtitleEvidence.value)
    list.push('尚未捕获视频字幕（字幕要点无输入）')
  if (!opinion.value)
    list.push('观点评价未产出（未请求、LLM 未配置、或输出未通过严格归约）')
  return list
})

function formatMs(value: number): string {
  const totalSeconds = Math.floor(Math.max(0, value) / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}

function formatConfidence(value: number): string {
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`
}

function shorten(value: string, max = 64): string {
  return value.length > max ? `${value.slice(0, max)}…` : value
}
</script>

<template>
  <main :class="['flex', 'flex-col', 'gap-3', 'w-full', 'text-sm']">
    <header :class="['flex', 'items-center', 'gap-2']">
      <div :class="['flex-1', 'font-semibold']">
        Companion
      </div>
      <span :class="store.connected.value ? 'text-green-600' : 'text-gray-500'">
        {{ store.connected.value ? '已连接' : '未连接' }}
      </span>
      <Button size="sm" :disabled="store.syncing.value" @click="store.refresh">
        {{ store.syncing.value ? '刷新中…' : '刷新' }}
      </Button>
    </header>

    <Callout v-if="store.lastError.value" theme="orange" label="Connection error">
      <div :class="['text-xs', 'leading-snug', 'opacity-80']">
        {{ store.lastError.value }}
      </div>
    </Callout>

    <!-- 1. 摘要卡片 -->
    <section :class="['border', 'rounded', 'p-2']">
      <h2 :class="['font-medium', 'mb-1']">
        摘要卡片
      </h2>
      <template v-if="pagePayload">
        <div :class="['text-xs', 'opacity-70', 'break-all']">
          {{ pagePayload.source_url }}
        </div>
        <p :class="['mt-1', 'leading-snug', 'whitespace-pre-wrap']">
          {{ pagePayload.observation_text }}
        </p>
        <div :class="['text-xs', 'opacity-60', 'mt-1']">
          hash {{ shorten(pagePayload.content_hash) }} · {{ pagePayload.spans.length }} 个片段
        </div>
      </template>
      <p v-else :class="['text-xs', 'opacity-60']">
        尚未捕获页面内容。
      </p>
    </section>

    <!-- 2. 视频字幕要点 -->
    <section :class="['border', 'rounded', 'p-2']">
      <h2 :class="['font-medium', 'mb-1']">
        视频字幕要点
      </h2>
      <template v-if="subtitlePayload">
        <ul :class="['flex', 'flex-col', 'gap-1']">
          <li v-for="(span, index) in subtitlePayload.time_spans" :key="index" :class="['flex', 'gap-2']">
            <span :class="['font-mono', 'text-xs', 'opacity-70', 'whitespace-nowrap']">
              {{ formatMs(span.start_ms) }}–{{ formatMs(span.end_ms) }}
            </span>
            <span :class="['leading-snug']">{{ span.text }}</span>
          </li>
        </ul>
        <div :class="['text-xs', 'opacity-60', 'mt-1']">
          video {{ subtitlePayload.video_id }} · hash {{ shorten(subtitlePayload.transcript_hash) }}
        </div>
      </template>
      <p v-else :class="['text-xs', 'opacity-60']">
        尚未捕获视频字幕。
      </p>
    </section>

    <!-- 3. 观点与评价（可折叠，含证据引用） -->
    <details :class="['border', 'rounded', 'p-2']" open>
      <summary :class="['font-medium', 'cursor-pointer']">
        观点与评价
      </summary>
      <template v-if="opinion">
        <ul :class="['mt-2', 'flex', 'flex-col', 'gap-1']">
          <li v-for="(claim, index) in opinion.payload.claims" :key="index" :class="['flex', 'gap-2']">
            <span :class="['text-xs', 'opacity-70', 'whitespace-nowrap']">{{ formatConfidence(claim.confidence) }}</span>
            <span :class="['leading-snug']">{{ claim.claim_text }}</span>
          </li>
        </ul>
        <p :class="['mt-2', 'text-xs', 'leading-snug', 'opacity-80']">
          {{ opinion.payload.uncertainty_notes }}
        </p>
      </template>
      <p v-else :class="['mt-1', 'text-xs', 'opacity-60']">
        尚无观点评价（不伪造：未产出即不展示结论）。
      </p>
    </details>

    <!-- 证据引用视图（供回放定位） -->
    <section :class="['border', 'rounded', 'p-2']">
      <h2 :class="['font-medium', 'mb-1']">
        证据引用（可回放）
      </h2>
      <ul v-if="evidenceRefs.length" :class="['flex', 'flex-col', 'gap-1', 'text-xs']">
        <li v-for="ref in evidenceRefs" :key="ref.label" :class="['flex', 'gap-2']">
          <span :class="['opacity-70', 'whitespace-nowrap']">{{ ref.label }}</span>
          <span :class="['font-mono', 'break-all']">{{ ref.value }}</span>
        </li>
      </ul>
      <p v-else :class="['text-xs', 'opacity-60']">
        暂无证据引用。
      </p>
    </section>

    <!-- 4. 风险提示 -->
    <section :class="['border', 'rounded', 'p-2']">
      <h2 :class="['font-medium', 'mb-1']">
        风险提示
      </h2>
      <ul v-if="gaps.length" :class="['flex', 'flex-col', 'gap-1', 'text-xs']">
        <li v-for="gap in gaps" :key="gap">
          · {{ gap }}
        </li>
      </ul>
      <p v-else :class="['text-xs', 'opacity-60']">
        输入完整。
      </p>
      <p :class="['mt-1', 'text-xs', 'opacity-60', 'leading-snug']">
        评价结论来自 LLM，可能误读原文；请以上方证据引用为准自行复核。
      </p>
    </section>
  </main>
</template>
