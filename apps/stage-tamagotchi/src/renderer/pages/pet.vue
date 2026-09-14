<script setup lang="ts">
/**
 * Desktop-pet mode (桌宠模式).
 *
 * The AIJADE main window is already transparent + frameless + always-on-top, so
 * this route *is* the floating desktop pet. It reuses the fully-initialized
 * renderer: chat goes through the same `chatSyncStore` pipeline that already
 * routes through the agent-capabilities bridge (auto skill creation, computer
 * control, continuous learning), and the live persona projection
 * (`chatOrchestrator.personaState`) drives the mood / intimacy display.
 */
import { defineInvoke } from '@moeru/eventa'
import { useElectronEventaContext, useElectronEventaInvoke } from '@proj-aijade/electron-vueuse'
import { useChatOrchestratorStore } from '@proj-aijade/stage-ui/stores/chat'
import { useChatSessionStore } from '@proj-aijade/stage-ui/stores/chat/session-store'
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import { electron, electronStartDraggingWindow } from '../../shared/eventa'
import { useChatSyncStore } from '../stores/chat-sync'

const router = useRouter()
const chatOrchestrator = useChatOrchestratorStore()
const chatSession = useChatSessionStore()
const chatSyncStore = useChatSyncStore()

const context = useElectronEventaContext()
const isLinux = useElectronEventaInvoke(electron.app.isLinux)
const startDraggingWindow = !isLinux() ? defineInvoke(context.value, electronStartDraggingWindow) : undefined

const input = ref('')

const persona = chatOrchestrator.personaState
const sending = computed(() => chatOrchestrator.sending)

const messages = computed(() => chatSession.getSessionMessages(chatSession.activeSessionId))
const lastAssistant = computed(() => {
  for (let i = messages.value.length - 1; i >= 0; i--) {
    const m = messages.value[i]
    if (m.role === 'assistant')
      return textOf(m)
  }
  return ''
})

interface EndocrineLike {
  dopamine: number
  serotonin: number
  cortisol: number
  oxytocin: number
  adrenaline: number
}

function moodEmoji(e: EndocrineLike): string {
  const rank: [string, number][] = [
    ['😊', e.serotonin],
    ['🤩', e.dopamine],
    ['😣', e.cortisol],
    ['🥰', e.oxytocin],
    ['😮', e.adrenaline],
  ]
  rank.sort((a, b) => b[1] - a[1])
  return rank[0]?.[0] ?? '🙂'
}

function textOf(m: { role: string, content?: unknown }): string {
  if (typeof m.content === 'string')
    return m.content
  return ''
}

const emoji = computed(() => moodEmoji(persona.endocrine))
const longing = computed(() => persona.intimacy.longing)
const lonelyHint = computed(() => (longing.value > 0.45 ? '（好像有点想你了…）' : ''))

async function send() {
  const text = input.value.trim()
  if (!text || sending.value)
    return
  input.value = ''
  try {
    await chatSyncStore.requestIngest({ text, toolset: 'artistry' })
  }
  catch (err) {
    input.value = text
    console.error('[pet] send failed:', err)
  }
}

function goHome() {
  router.push('/')
}
</script>

<template>
  <div flex="~ col" fixed inset-0 select-none items-center justify-center p-4>
    <!-- Draggable pet avatar -->
    <div
      flex="~ col"
      cursor-move items-center gap-1
      @mousedown="startDraggingWindow?.()"
    >
      <div
        text="7xl"
        filter="drop-shadow(0 4px 10px rgb(0 0 0 / 0.35))"
        transition-transform duration-200 hover:scale-110
      >
        {{ emoji }}
      </div>
      <div class="text-sm text-white/80 font-medium">
        AIJADE {{ lonelyHint }}
      </div>
    </div>

    <!-- Chat bubble -->
    <div
      max-w="80%" min-w="180px"
      bg="white/85 dark:white/10"
      text="sm center"
      mt-3 rounded-2xl px-4 py-2 text-neutral-800 shadow-lg backdrop-blur-md dark:text-neutral-100
      border="1 neutral-200/60 dark:neutral-700/40"
      min-h="2.5rem"
    >
      {{ lastAssistant || '想聊点什么吗？' }}
    </div>

    <!-- Intimacy hint -->
    <div class="mt-1 text-xs text-white/60">
      亲密度 · 熟悉 {{ (persona.intimacy.familiarity * 100).toFixed(0) }}% · 信任 {{ (persona.intimacy.trust * 100).toFixed(0) }}%
    </div>

    <!-- Input row -->
    <div mt-4 w="full" max-w="260px" flex="~ row" items-center gap-2>
      <input
        v-model="input"
        type="text"
        :placeholder="sending ? '思考中…' : '和 AIJADE 说点什么'"
        :disabled="sending"
        w="full" bg="white/85 dark:white/10"
        text="sm"
        rounded-full px-4 py-2 text-neutral-800 outline-none dark:text-neutral-100 border="1 neutral-200/60 dark:neutral-700/40"
        @keydown.enter="send"
      >
      <button
        :disabled="sending"
        bg="primary-500 hover:primary-600"
        flex="~"
        h-9 w-9 shrink-0 items-center justify-center rounded-full text-lg text-white shadow-md transition-colors
        @click="send"
      >
        ↑
      </button>
    </div>

    <!-- Back to full stage -->
    <button
      class="mt-4 text-xs text-white/60 underline-offset-2 hover:text-white hover:underline"
      @click="goHome"
    >
      返回完整界面
    </button>

    <!-- Quick actions -->
    <div class="mt-2 max-w-[260px] w-full flex flex-col gap-2">
      <!-- Game studio: prominent entry so it is easy to find -->
      <button
        class="flex flex-row items-center justify-center gap-2 rounded-xl bg-primary-500 px-4 py-2.5 text-sm text-white font-medium shadow-md transition-colors hover:bg-primary-600"
        @click="router.push('/game-agent')"
      >
        <span class="text-base">🎮</span>
        <span>进入游戏工作室</span>
      </button>

      <!-- Open Bluetooth MIDI piano panel -->
      <button
        class="flex flex-row items-center justify-center gap-2 rounded-xl bg-white/10 px-4 py-2 text-xs text-white/85 transition-colors hover:bg-white/15"
        @click="router.push('/piano')"
      >
        🎹 蓝牙 MIDI 电钢琴
      </button>
    </div>
  </div>
</template>
