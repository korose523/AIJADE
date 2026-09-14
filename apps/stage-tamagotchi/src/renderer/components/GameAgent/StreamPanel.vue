<script setup lang="ts">
import type { GameStudio } from '../../modules/game-agent/use-game-studio'

import { computed, onMounted, ref } from 'vue'

/**
 * 直播面板 —— AIJADE 的导播台。
 *
 * 「一键开播」把三件事串起来：连 OBS → 开推流 → 启动 Agent 循环，
 * 之后决策器每产出一句 say，就自动念出来并同步写进 OBS 字幕源。
 */
const props = defineProps<{ studio: GameStudio }>()

const studio = props.studio
const live = studio.live
const voices = ref<{ name: string, lang: string }[]>([])

const healthColor = computed(() => ({
  good: 'text-emerald-300',
  warning: 'text-amber-300',
  bad: 'text-rose-300',
  idle: 'text-white/50',
}[live.health.value]))

const healthText = computed(() => ({
  good: '推流健康',
  warning: '轻微丢帧',
  bad: '丢帧严重',
  idle: '未推流',
}[live.health.value]))

function refreshVoices() {
  voices.value = live.listVoices().map(v => ({ name: v.name, lang: v.lang }))
}

onMounted(() => {
  refreshVoices()
  // 语音列表在部分平台上是异步加载的
  if (typeof window !== 'undefined' && window.speechSynthesis)
    window.speechSynthesis.onvoiceschanged = refreshVoices
})
</script>

<template>
  <div class="flex flex-col gap-3">
    <p class="text-xs text-white/55 leading-relaxed">
      直播导播台通过 obs-websocket 控制推流与字幕。AI 的旁白会串行播报：写字幕 → 语音念出 → 停留片刻 → 下一句，
      积压过多时自动丢弃旧内容（直播讲的是当下）。
    </p>

    <!-- 连接与状态 -->
    <div class="grid grid-cols-2 gap-2 text-sm">
      <label class="flex flex-col gap-1">
        <span class="text-xs text-white/60">OBS WebSocket</span>
        <input v-model="live.obsUrl.value" :disabled="live.connected.value" class="border border-white/15 rounded bg-white/10 px-2 py-1 outline-none">
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-xs text-white/60">密码（可选）</span>
        <input v-model="live.obsPassword.value" type="password" :disabled="live.connected.value" class="border border-white/15 rounded bg-white/10 px-2 py-1 outline-none">
      </label>
    </div>

    <div class="flex flex-row flex-wrap items-center gap-2">
      <button
        v-if="!live.connected.value"
        :disabled="live.connecting.value"
        class="rounded bg-white/10 px-3 py-1.5 text-xs text-white transition-colors hover:bg-white/20 disabled:opacity-50"
        @click="live.connect()"
      >
        {{ live.connecting.value ? '连接中…' : '连接导播' }}
      </button>
      <button v-else class="rounded bg-white/10 px-3 py-1.5 text-white text-white/70 transition-colors hover:bg-white/20" @click="live.disconnect()">
        断开
      </button>
      <span class="text-xs" :class="live.connected.value ? 'text-emerald-300' : 'text-white/50'">
        {{ live.connected.value ? '导播已连接' : '未连接' }}
      </span>
      <span v-if="live.error.value" class="text-xs text-rose-300">{{ live.error.value }}</span>
    </div>

    <!-- 直播状态卡 -->
    <div class="grid grid-cols-4 gap-2 border border-white/12 rounded-lg bg-white/5 p-2.5 text-xs">
      <div class="flex flex-col gap-0.5">
        <span class="text-white/45">状态</span>
        <span :class="live.status.value.streaming ? 'text-rose-300 font-semibold' : 'text-white/70'">
          {{ live.status.value.streaming ? '● 直播中' : '○ 未开播' }}
        </span>
      </div>
      <div class="flex flex-col gap-0.5">
        <span class="text-white/45">时长</span>
        <span class="text-white/85">{{ live.durationText.value }}</span>
      </div>
      <div class="flex flex-col gap-0.5">
        <span class="text-white/45">码率</span>
        <span class="text-white/85">{{ live.status.value.kbitsPerSec }} kbps</span>
      </div>
      <div class="flex flex-col gap-0.5">
        <span class="text-white/45">健康度</span>
        <span :class="healthColor">{{ healthText }}（丢帧 {{ live.dropRate.value }}%）</span>
      </div>
    </div>

    <!-- 一键开播 -->
    <div class="flex flex-row flex-wrap items-center gap-3">
      <button
        v-if="!live.status.value.streaming"
        class="rounded-full bg-rose-500 px-5 py-2 text-sm text-white font-semibold shadow-md transition-colors hover:bg-rose-600"
        @click="studio.goLive()"
      >
        ⏺ 一键开播（推流 + AI 上线）
      </button>
      <button
        v-else
        class="rounded-full bg-white/12 px-5 py-2 text-sm text-white shadow-md transition-colors hover:bg-white/20"
        @click="studio.endLive()"
      >
        ■ 下播
      </button>
      <button class="rounded bg-white/10 px-3 py-1.5 text-xs text-white transition-colors hover:bg-white/20" @click="live.toggleRecording()">
        {{ live.status.value.recording ? '停止录制' : '开始录制' }}
      </button>
      <button class="rounded bg-white/10 px-3 py-1.5 text-white text-white/70 transition-colors hover:bg-white/20" @click="live.toggleStreaming()">
        {{ live.status.value.streaming ? '仅停推流' : '仅开推流' }}
      </button>
    </div>

    <!-- 场景切换 -->
    <div v-if="live.scenes.value.length" class="text-sm">
      <div class="mb-1 text-xs text-white/60">
        场景（当前：{{ live.currentScene.value }}）
      </div>
      <div class="flex flex-row flex-wrap gap-1.5">
        <button
          v-for="s in live.scenes.value" :key="s"
          class="rounded px-2.5 py-1 text-xs transition-colors"
          :class="s === live.currentScene.value ? 'bg-primary-500/30 text-primary-100' : 'bg-white/8 text-white/70 hover:bg-white/15'"
          @click="live.switchScene(s)"
        >
          {{ s }}
        </button>
      </div>
    </div>

    <!-- 旁白与字幕 -->
    <div class="flex flex-col gap-2 border border-white/12 rounded-lg bg-white/5 p-2.5">
      <div class="text-xs text-white/80 font-medium">
        旁白 / 字幕
      </div>

      <div class="grid grid-cols-2 gap-2 text-sm">
        <label class="flex flex-col gap-1">
          <span class="text-xs text-white/60">OBS 字幕文本源</span>
          <select v-model="live.subtitleSource.value" class="border border-white/15 rounded bg-white/10 px-2 py-1 outline-none">
            <option value="">
              （不写字幕）
            </option>
            <option v-for="t in live.textInputs.value" :key="t.name" :value="t.name">
              {{ t.name }}
            </option>
          </select>
        </label>
        <label class="flex flex-col gap-1">
          <span class="text-xs text-white/60">语音</span>
          <select v-model="live.ttsVoice.value" class="border border-white/15 rounded bg-white/10 px-2 py-1 outline-none">
            <option value="">
              （自动选中文）
            </option>
            <option v-for="v in voices" :key="v.name" :value="v.name">
              {{ v.name }} · {{ v.lang }}
            </option>
          </select>
        </label>
      </div>

      <div class="flex flex-row flex-wrap items-center gap-3 text-xs text-white/75">
        <label class="flex flex-row items-center gap-1.5">
          <input v-model="live.enableTts.value" type="checkbox">
          <span>语音播报</span>
        </label>
        <label class="flex flex-row items-center gap-1.5">
          <input v-model="studio.autoNarrate.value" type="checkbox">
          <span>自动播报 AI 决策旁白</span>
        </label>
        <label class="flex flex-row items-center gap-1.5">
          <span>语速</span>
          <input v-model.number="live.ttsRate.value" type="number" min="0.5" max="2" step="0.1" class="w-16 border border-white/15 rounded bg-white/10 px-1.5 py-0.5 outline-none">
        </label>
        <label class="flex flex-row items-center gap-1.5">
          <span>字幕停留(ms)</span>
          <input v-model.number="live.subtitleHoldMs.value" type="number" min="0" step="100" class="w-20 border border-white/15 rounded bg-white/10 px-1.5 py-0.5 outline-none">
        </label>
        <button class="rounded bg-white/10 px-2 py-1 text-white text-white/70 transition-colors hover:bg-white/20" @click="live.clearNarrations()">
          清空
        </button>
      </div>

      <div v-if="live.currentText.value" class="border border-primary-400/25 rounded bg-black/35 p-2 text-xs text-primary-200">
        🔊 {{ live.currentText.value }}
      </div>

      <div v-if="live.narrations.value.length" class="max-h-[120px] flex flex-col gap-1 overflow-auto border border-white/10 rounded bg-black/35 p-2">
        <div v-for="(n, i) in live.narrations.value.slice(-20).reverse()" :key="i" class="text-[10px]" :class="n.spoken ? 'text-white/50' : 'text-white/85'">
          {{ new Date(n.at).toLocaleTimeString() }} · {{ n.text }}
        </div>
      </div>
    </div>

    <!-- 观察叠层（让 AIJADE 像人类一样"看"游戏并把注意力画到画面上） -->
    <div class="flex flex-col gap-2 border border-white/12 rounded-lg bg-white/5 p-2.5">
      <div class="text-xs text-white/80 font-medium">
        观察叠层（OBS 作为 AIJADE 的眼睛）
      </div>
      <p class="text-xs text-white/55 leading-relaxed">
        开启后，AIJADE 持续从 OBS 源抓帧理解画面，把"此刻在盯什么 / 打算做什么"推给本地 HUD，
        再由 OBS 场景里的浏览器源（或 obs-urlsource 的 url_source）实时画到画面上——像主播一样把目光展示出来。
      </p>

      <div class="flex flex-row flex-wrap items-center gap-2">
        <button
          v-if="!studio.hudEnabled.value"
          class="rounded bg-white/10 px-3 py-1.5 text-xs text-white transition-colors hover:bg-white/20"
          @click="studio.startHud()"
        >
          启动 HUD 服务
        </button>
        <button
          v-else
          class="rounded bg-white/10 px-3 py-1.5 text-xs text-white transition-colors hover:bg-white/20"
          @click="studio.stopHud()"
        >
          停止 HUD 服务
        </button>

        <label class="flex flex-row items-center gap-1.5 text-xs text-white/75">
          <span>渲染方式</span>
          <select v-model="studio.overlayKind.value" :disabled="!!studio.overlayName.value" class="border border-white/15 rounded bg-white/10 px-2 py-1 outline-none">
            <option value="browser_source">浏览器源（推荐，富文本+注意力框）</option>
            <option value="url_source">URL 源（obs-urlsource 插件，纯文本）</option>
          </select>
        </label>

        <button
          class="rounded px-3 py-1.5 text-xs text-white transition-colors"
          :class="studio.overlayName.value ? 'bg-rose-500/70 hover:bg-rose-500' : 'bg-primary-500 hover:bg-primary-600'"
          :disabled="!studio.hudEnabled.value"
          @click="studio.toggleOverlay()"
        >
          {{ studio.overlayName.value ? '移除 OBS 叠层' : '在 OBS 创建叠层源' }}
        </button>
      </div>

      <div class="text-xs text-white/60">
        HUD：{{ studio.hudEnabled.value ? `已启动（端口 ${studio.hudPort.value}）` : '未启动' }}
        <span v-if="studio.overlayName.value" class="text-emerald-300"> · 叠层源「{{ studio.overlayName.value }}」已就位（OBS 状态：{{ studio.overlayStatus.value }}）</span>
        <span v-else-if="studio.hudEnabled.value" class="text-white/45"> · 可在 OBS 手动添加浏览器源指向 http://localhost:{{ studio.hudPort.value }}/hud</span>
      </div>
    </div>

    <div v-if="live.logs.value.length" class="text-sm">
      <div class="mb-1 text-xs text-white/60">
        导播日志
      </div>
      <div class="max-h-[110px] flex flex-col gap-0.5 overflow-auto border border-white/10 rounded bg-black/40 p-2 text-xs text-white/70">
        <div v-for="(l, i) in live.logs.value" :key="i">
          {{ l }}
        </div>
      </div>
    </div>
  </div>
</template>
