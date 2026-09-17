import type { ExtensionStatus } from '../../../src/shared/types'
import type { OpinionEvaluationPayload, V10EvidenceEvent } from '../../../src/shared/v10-evidence'

import { createGlobalState } from '@vueuse/core'
import { computed, ref } from 'vue'

import { onBackgroundStatus, requestEvidence } from '../../../src/shared/sidepanel-bridge'

interface SidePanelEvidence {
  status: ExtensionStatus
  pageEvidence: V10EvidenceEvent | null
  subtitleEvidence: V10EvidenceEvent | null
  opinion: OpinionEvaluationPayload | null
}

export const useSidePanelStore = createGlobalState(() => {
  const status = ref<ExtensionStatus | null>(null)
  const pageEvidence = ref<V10EvidenceEvent | null>(null)
  const subtitleEvidence = ref<V10EvidenceEvent | null>(null)
  const opinion = ref<OpinionEvaluationPayload | null>(null)
  const syncing = ref(true)
  const initialized = ref(false)

  const connected = computed(() => status.value?.connected ?? false)
  const lastError = computed(() => status.value?.lastError)

  function hydrate(next: SidePanelEvidence) {
    status.value = next.status
    pageEvidence.value = next.pageEvidence
    subtitleEvidence.value = next.subtitleEvidence
    opinion.value = next.opinion
  }

  /** 完整刷新（含后台 LLM 观点评价）。用于初始加载与手动刷新按钮。 */
  async function refresh() {
    syncing.value = true
    try {
      const next = await requestEvidence({ includeOpinion: true })
      hydrate(next)
    }
    catch (err) {
      console.warn('[sidepanel] requestEvidence(含观点评价) 失败:', err)
    }
    finally {
      syncing.value = false
    }
  }

  /** 轻量刷新：只取确定性归约（page/subtitle），不触发后台 LLM。用于后台状态变更时更新。 */
  async function refreshLight() {
    try {
      const next = await requestEvidence({ includeOpinion: false })
      hydrate(next)
    }
    catch (err) {
      console.warn('[sidepanel] requestEvidence(轻量) 失败:', err)
    }
  }

  function init() {
    if (initialized.value)
      return
    initialized.value = true
    void refresh()
    onBackgroundStatus((next) => {
      status.value = next
      // 后台捕获到新页面/字幕或连接变化时，用确定性归约轻量更新视图（不打 LLM）。
      void refreshLight()
    })
  }

  return {
    status,
    pageEvidence,
    subtitleEvidence,
    opinion,
    syncing,
    connected,
    lastError,
    init,
    refresh,
  }
})
