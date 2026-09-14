<script setup lang="ts">
/**
 * Neuro SDK 服务器面板（VedalAI 协议）。
 *
 * 与「实操」页的思路互补：实操是 AIJADE 看画面按键盘（适用任何游戏），
 * 这里则是游戏主动把可用动作注册给 AIJADE，由 AIJADE 决策后回传（更精确，但需游戏支持 SDK）。
 */
import { computed } from 'vue'

import { useNeuroServer } from '../../modules/game-agent'

const neuro = useNeuroServer()

const connectedGame = computed(() => neuro.status.value?.connectedGame ?? null)
const neuroSay = computed(() => neuro.status.value?.lastSay ?? '')
const neuroLogs = computed(() => neuro.status.value?.logs ?? [])
const neuroActions = computed(() => neuro.status.value?.registeredActions ?? [])
</script>

<template>
  <div class="flex flex-col gap-2">
    <div class="flex flex-row items-center justify-between">
      <div class="text-sm text-primary-200 font-semibold">
        🎮 Neuro SDK 服务器模式
      </div>
      <span class="text-xs" :class="neuro.running.value ? 'text-emerald-300' : 'text-white/50'">
        {{ neuro.running.value ? `监听中 :${neuro.port.value}` : '未启动' }}
      </span>
    </div>
    <p class="text-xs text-white/55 leading-relaxed">
      参考 VedalAI/neuro-game-sdk：启动后 AIJADE 成为「AI 大脑」，任何集成了 neuro-sdk 的游戏
      （如卡牌/视觉小说类）连接 <code class="text-primary-300">ws://localhost:{{ neuro.port.value }}</code> 即可被 AIJADE 操控并实时旁白。
      无需 OBS；无模型时自动 mock 兜底演示。
    </p>

    <div v-if="!neuro.running.value" class="grid grid-cols-2 gap-2 text-sm">
      <label class="flex flex-col gap-1">
        <span class="text-xs text-white/60">端口</span>
        <input v-model.number="neuro.port.value" class="border border-white/15 rounded bg-white/10 px-2 py-1 outline-none">
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-xs text-white/60">Ollama 地址</span>
        <input v-model="neuro.baseUrl.value" class="border border-white/15 rounded bg-white/10 px-2 py-1 outline-none">
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-xs text-white/60">模型</span>
        <input v-model="neuro.model.value" class="border border-white/15 rounded bg-white/10 px-2 py-1 outline-none">
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-xs text-white/60">目标（可选）</span>
        <input v-model="neuro.goal.value" class="border border-white/15 rounded bg-white/10 px-2 py-1 outline-none">
      </label>
      <label class="col-span-2 flex flex-col gap-1">
        <span class="text-xs text-white/60">系统提示词（人设/玩法）</span>
        <textarea v-model="neuro.systemPrompt.value" rows="2" class="resize-none border border-white/15 rounded bg-white/10 px-2 py-1 outline-none" />
      </label>
    </div>

    <div class="flex flex-row items-center gap-3">
      <button v-if="!neuro.running.value" class="rounded-full bg-primary-500 px-5 py-2 text-sm text-white shadow-md transition-colors hover:bg-primary-600" @click="neuro.start()">
        ▶ 启动服务器
      </button>
      <button v-else class="rounded-full bg-rose-500/80 px-5 py-2 text-sm text-white shadow-md transition-colors hover:bg-rose-500" @click="neuro.stop()">
        ■ 停止服务器
      </button>
      <span v-if="connectedGame" class="text-xs text-emerald-300">已连接游戏：{{ connectedGame }}</span>
    </div>

    <div v-if="neuroSay" class="border border-white/10 rounded bg-black/30 p-2 text-xs text-primary-200/90">
      💬 AIJADE 旁白：{{ neuroSay }}
    </div>

    <div v-if="neuroActions.length" class="text-xs text-white/60">
      已注册动作：{{ neuroActions.map(a => a.name).join('、') }}
    </div>

    <div v-if="neuroLogs.length" class="max-h-[120px] flex flex-col gap-0.5 overflow-auto border border-white/10 rounded bg-black/40 p-2 text-xs text-white/70">
      <div v-for="(l, i) in neuroLogs" :key="i">
        {{ l }}
      </div>
    </div>
  </div>
</template>
