<script setup lang="ts">
/**
 * 真机学习面板 —— AIJADE 在旁边看真人打游戏。
 *
 * 录制期间主进程以 ~15ms 轮询采集键鼠（不挂低级钩子，对反作弊更友好），
 * 同时按间隔从 OBS 抓关键帧，两条流按时间轴对齐后落盘成学习素材。
 */
import type { GameStudio } from '../../modules/game-agent/use-game-studio'

import { computed } from 'vue'

const props = defineProps<{ studio: GameStudio }>()

const studio = props.studio
const rm = studio.realMachine

const elapsedText = computed(() => {
  const total = Math.floor(rm.elapsedMs.value / 1000)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
})

async function onStop() {
  const n = await studio.finishRealMachineAndLearn()
  if (n > 0)
    await studio.knowledge.load()
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <p class="text-xs text-white/55 leading-relaxed">
      让 AIJADE 在旁边观摩你打游戏：同步记录你的键鼠操作与游戏画面，结束后自动提炼成经验入库。
      画面来自 OBS 源「{{ studio.agent.obsSource.value }}」，请先在「实操」页确认 OBS 配置。
    </p>

    <div v-if="studio.obsHint.value" class="border border-amber-400/30 rounded bg-amber-400/10 p-2 text-xs text-amber-200">
      ⚠ {{ studio.obsHint.value }}
    </div>
    <div v-if="studio.learnObsStatus.value !== 'connected'" class="border border-white/10 rounded bg-white/5 p-2 text-xs text-white/60">
      OBS 状态：{{ studio.learnObsStatus.value }} —— 真机学习会照常记录你的键鼠操作；未连接 OBS 时不会抓游戏画面关键帧（提炼出的经验不含画面示例）。
    </div>

    <div class="grid grid-cols-2 gap-2">
      <label class="flex flex-col gap-1">
        <span class="text-xs text-white/60">本次标题</span>
        <input
          v-model="rm.title.value" :disabled="rm.recording.value" placeholder="例如：赛季前期刷图手法"
          class="border border-white/15 rounded bg-white/10 px-2 py-1 text-sm outline-none"
        >
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-xs text-white/60">关键帧间隔（毫秒）</span>
        <input
          v-model.number="rm.frameIntervalMs.value" type="number" min="500" step="500" :disabled="rm.recording.value"
          class="border border-white/15 rounded bg-white/10 px-2 py-1 text-sm outline-none"
        >
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-xs text-white/60">操作关联窗口（毫秒）</span>
        <input
          v-model.number="rm.actionWindowMs.value" type="number" min="200" step="100" :disabled="rm.recording.value"
          class="border border-white/15 rounded bg-white/10 px-2 py-1 text-sm outline-none"
        >
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-xs text-white/60">最多保留关键帧</span>
        <input
          v-model.number="rm.maxFrames.value" type="number" min="20" step="10" :disabled="rm.recording.value"
          class="border border-white/15 rounded bg-white/10 px-2 py-1 text-sm outline-none"
        >
      </label>
    </div>

    <label class="flex flex-row items-center gap-2 text-sm text-white/80">
      <input v-model="rm.captionWhileRecording.value" type="checkbox" :disabled="rm.recording.value">
      <span>边录边让视觉模型描述画面（更慢，但提炼质量更高，需选 Ollama 视觉后端）</span>
    </label>

    <label class="flex flex-col gap-1">
      <span class="text-xs text-white/60">备注（可选，会一起交给提炼器）</span>
      <textarea
        v-model="rm.notes.value" rows="2" placeholder="例如：这局在练走位躲技能"
        class="resize-none border border-white/15 rounded bg-white/10 px-2 py-1 text-sm outline-none"
      />
    </label>

    <div class="flex flex-row flex-wrap items-center gap-3">
      <button
        v-if="!rm.recording.value"
        class="rounded-full bg-primary-500 px-5 py-2 text-sm text-white shadow-md transition-colors hover:bg-primary-600"
        @click="rm.start()"
      >
        ● 开始观摩
      </button>
      <button
        v-else
        class="rounded-full bg-rose-500/80 px-5 py-2 text-sm text-white shadow-md transition-colors hover:bg-rose-500"
        @click="onStop()"
      >
        ■ 结束并学习
      </button>
      <span v-if="rm.recording.value" class="text-xs text-emerald-300">
        录制中 {{ elapsedText }} · {{ rm.events.value.length }} 个事件 · {{ rm.keyframes.value.length }} 帧 · APM {{ rm.stats.value.apm }}
      </span>
      <span v-else-if="studio.distilling.value" class="text-xs text-amber-300">正在提炼经验…</span>
      <span class="text-xs text-white/50">OBS 采集：{{ studio.learnObsStatus.value }}</span>
    </div>

    <!-- OBS 观察：让 AIJADE 像人类一样"看"当前画面 -->
    <div class="flex flex-col gap-1.5 border border-sky-400/25 rounded bg-sky-400/5 p-2 text-xs text-sky-100/85">
      <div class="flex flex-row flex-wrap items-center gap-2">
        <button
          class="rounded bg-sky-500/80 px-3 py-1.5 text-xs text-white transition-colors hover:bg-sky-500"
          :disabled="studio.observing.value"
          @click="studio.startObservationLoop(1)"
        >
          {{ studio.observing.value ? `观察中 ${studio.obsFps.value.toFixed(1)} fps` : '▶ 通过 OBS 观察画面' }}
        </button>
        <button
          v-if="studio.observing.value"
          class="rounded bg-white/10 px-3 py-1.5 text-xs text-white transition-colors hover:bg-white/20"
          @click="studio.stopObservationLoop()"
        >
          停止观察
        </button>
        <label class="flex flex-row items-center gap-1.5">
          <input v-model="studio.hudEnabled.value" type="checkbox" @change="studio.hudEnabled.value ? studio.startHud() : studio.stopHud()">
          <span>同步到 OBS 观察叠层</span>
        </label>
      </div>
      <div v-if="studio.observing.value" class="text-white/70">
        <span class="text-sky-200">聚焦：</span>{{ studio.observation.value.focus || '—' }}
        <span v-if="studio.observation.value.goal" class="ml-2 text-sky-200">意图：</span>{{ studio.observation.value.goal }}
      </div>
      <div v-if="studio.observation.value.narration" class="text-sky-100/70 italic">
        🎙 {{ studio.observation.value.narration }}
      </div>
    </div>

    <div v-if="rm.error.value" class="border border-rose-400/30 rounded bg-rose-500/10 p-2 text-xs text-rose-200">
      {{ rm.error.value }}
    </div>

    <div v-if="rm.lastFrame.value" class="overflow-hidden border border-white/15 rounded-xl bg-black/40">
      <img :src="rm.lastFrame.value.dataUrl" class="max-h-45 w-full object-contain">
    </div>

    <div v-if="rm.recentActions.value.length">
      <div class="mb-1 text-xs text-white/60">
        刚刚捕捉到的操作
      </div>
      <div class="flex flex-row flex-wrap gap-1">
        <span v-for="(a, i) in rm.recentActions.value" :key="i" class="rounded bg-white/8 px-1.5 py-0.5 text-xs text-white/80">
          {{ a }}
        </span>
      </div>
    </div>

    <div v-if="rm.topKeys.value.length">
      <div class="mb-1 text-xs text-white/60">
        按键频率 Top
      </div>
      <div class="flex flex-row flex-wrap gap-1">
        <span v-for="([k, n]) in rm.topKeys.value" :key="k" class="rounded bg-primary-500/15 px-1.5 py-0.5 text-xs text-primary-200">
          {{ k }} × {{ n }}
        </span>
      </div>
    </div>

    <div v-if="rm.logs.value.length">
      <div class="mb-1 text-xs text-white/60">
        学习日志
      </div>
      <div class="max-h-30 flex flex-col gap-0.5 overflow-auto border border-white/10 rounded bg-black/40 p-2 text-xs text-white/70">
        <div v-for="(l, i) in rm.logs.value" :key="i">
          {{ l }}
        </div>
      </div>
    </div>
  </div>
</template>
