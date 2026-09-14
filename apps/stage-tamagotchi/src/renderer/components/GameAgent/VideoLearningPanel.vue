<script setup lang="ts">
/**
 * 视频学习面板 —— AIJADE 通过看视频/看直播涨经验。
 *
 * 本地文件与直链走 seek 抽帧（可快进，一小时录像几十秒就"看"完）；
 * OBS 源走实时采样（用来看别人的直播）。视频里没有键鼠标注，
 * 所以强烈建议把解说/字幕文本粘进来——游戏解析视频的干货基本都在解说里。
 */
import type { GameStudio } from '../../modules/game-agent/use-game-studio'

import { computed, ref } from 'vue'

const props = defineProps<{ studio: GameStudio }>()

const studio = props.studio
const video = studio.video
const fileInput = ref<HTMLInputElement | null>(null)

const progressText = computed(() => {
  if (!video.total.value)
    return ''
  return `${video.processed.value}/${video.total.value}`
})

function onPick(e: Event) {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (file)
    video.selectFile(file)
}

async function onStop() {
  const n = await studio.finishVideoAndLearn()
  if (n > 0)
    await studio.knowledge.load()
}
</script>

<template>
  <div class="flex flex-col gap-3">
    <p class="text-xs text-white/55 leading-relaxed">
      让 AIJADE 看视频学打法。本地录像/直链会按固定秒数抽帧快速"看完"；选 OBS 源则是实时看直播。
      抽出的画面交给视觉模型描述，再与解说文本一起提炼成经验。
    </p>

    <div v-if="studio.obsHint.value" class="border border-amber-400/30 rounded bg-amber-400/10 p-2 text-xs text-amber-200">
      ⚠ {{ studio.obsHint.value }}
    </div>
    <div v-if="video.kind.value === 'obs' && studio.learnObsStatus.value !== 'connected'" class="border border-amber-400/30 rounded bg-amber-400/10 p-2 text-xs text-amber-200">
      ⚠ OBS 状态：{{ studio.learnObsStatus.value }} —— 选了「OBS 源（看直播）」但需要先连 OBS。请确认 OBS 已启动、obs-websocket 已开启，且「源名称」与「实操」页一致。
    </div>

    <div class="grid grid-cols-3 gap-2">
      <label class="flex flex-col gap-1">
        <span class="text-xs text-white/60">素材来源</span>
        <select
          v-model="video.kind.value" :disabled="video.learning.value"
          class="border border-white/15 rounded bg-white/10 px-2 py-1 text-sm outline-none"
        >
          <option value="file">本地视频文件</option>
          <option value="url">视频直链 URL</option>
          <option value="obs">OBS 源（看直播）</option>
        </select>
      </label>
      <label v-if="video.kind.value !== 'obs'" class="flex flex-col gap-1">
        <span class="text-xs text-white/60">抽帧间隔（秒）</span>
        <input
          v-model.number="video.sampleIntervalSec.value" type="number" min="1" :disabled="video.learning.value"
          class="border border-white/15 rounded bg-white/10 px-2 py-1 text-sm outline-none"
        >
      </label>
      <label v-else class="flex flex-col gap-1">
        <span class="text-xs text-white/60">采样间隔（毫秒）</span>
        <input
          v-model.number="video.obsSampleIntervalMs.value" type="number" min="500" step="500" :disabled="video.learning.value"
          class="border border-white/15 rounded bg-white/10 px-2 py-1 text-sm outline-none"
        >
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-xs text-white/60">最多抽取帧数</span>
        <input
          v-model.number="video.maxFrames.value" type="number" min="5" :disabled="video.learning.value"
          class="border border-white/15 rounded bg-white/10 px-2 py-1 text-sm outline-none"
        >
      </label>
    </div>

    <div v-if="video.kind.value === 'file'" class="flex flex-row items-center gap-2">
      <input ref="fileInput" type="file" accept="video/*" hidden @change="onPick">
      <button class="rounded bg-white/10 px-3 py-1.5 text-xs text-white transition-colors hover:bg-white/20" @click="fileInput?.click()">
        选择视频文件
      </button>
      <span class="text-xs text-white/60">{{ video.originLabel.value || '未选择' }}</span>
    </div>

    <label v-else-if="video.kind.value === 'url'" class="flex flex-col gap-1">
      <span class="text-xs text-white/60">视频直链（需可直接播放，注意跨域限制）</span>
      <input
        v-model="video.url.value" :disabled="video.learning.value" placeholder="https://.../gameplay.mp4"
        class="border border-white/15 rounded bg-white/10 px-2 py-1 text-sm outline-none"
      >
    </label>

    <label class="flex flex-row items-center gap-2 text-sm text-white/80">
      <input v-model="video.captionFrames.value" type="checkbox" :disabled="video.learning.value">
      <span>用视觉模型描述每一帧（关闭则只存画面，提炼质量下降）</span>
    </label>

    <label class="flex flex-col gap-1">
      <span class="text-xs text-white/60">解说 / 字幕 / 攻略文本（强烈建议粘贴，提炼质量提升最明显）</span>
      <textarea
        v-model="video.transcript.value" rows="3" placeholder="把视频的解说词、字幕或攻略文章贴进来"
        class="resize-none border border-white/15 rounded bg-white/10 px-2 py-1 text-sm outline-none"
      />
    </label>

    <div class="grid grid-cols-2 gap-2">
      <label class="flex flex-col gap-1">
        <span class="text-xs text-white/60">素材标题</span>
        <input
          v-model="video.title.value" :disabled="video.learning.value"
          class="border border-white/15 rounded bg-white/10 px-2 py-1 text-sm outline-none"
        >
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-xs text-white/60">备注</span>
        <input
          v-model="video.notes.value" :disabled="video.learning.value"
          class="border border-white/15 rounded bg-white/10 px-2 py-1 text-sm outline-none"
        >
      </label>
    </div>

    <div class="flex flex-row flex-wrap items-center gap-3">
      <button
        v-if="!video.learning.value"
        :disabled="!video.canStart.value"
        class="rounded-full bg-primary-500 px-5 py-2 text-sm text-white shadow-md transition-colors disabled:cursor-not-allowed disabled:bg-white/10 hover:bg-primary-600"
        @click="video.start()"
      >
        ▶ 开始学习
      </button>
      <button
        v-else
        class="rounded-full bg-rose-500/80 px-5 py-2 text-sm text-white shadow-md transition-colors hover:bg-rose-500"
        @click="onStop()"
      >
        ■ 结束并提炼
      </button>
      <span v-if="video.learning.value" class="text-xs text-emerald-300">
        学习中 {{ progressText }} · {{ Math.round(video.progress.value * 100) }}%
      </span>
      <span v-else-if="studio.distilling.value" class="text-xs text-amber-300">正在提炼经验…</span>
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

    <div v-if="video.learning.value" class="h-1 w-full overflow-hidden rounded-full bg-white/10">
      <div class="h-full rounded-full bg-primary-400 transition-all" :style="{ width: `${Math.round(video.progress.value * 100)}%` }" />
    </div>

    <div v-if="video.error.value" class="border border-rose-400/30 rounded bg-rose-500/10 p-2 text-xs text-rose-200">
      {{ video.error.value }}
    </div>

    <div v-if="video.lastFrame.value" class="overflow-hidden border border-white/15 rounded-xl bg-black/40">
      <img :src="video.lastFrame.value.dataUrl" class="max-h-45 w-full object-contain">
    </div>

    <div v-if="video.keyframes.value.length">
      <div class="mb-1 text-xs text-white/60">
        已抽取 {{ video.keyframes.value.length }} 帧
      </div>
      <div class="flex flex-row gap-1 overflow-x-auto pb-1">
        <img
          v-for="(kf, i) in video.keyframes.value.slice(-12)" :key="i" :src="kf.thumbnail"
          class="h-11 border border-white/10 rounded object-cover"
        >
      </div>
    </div>

    <div v-if="video.logs.value.length">
      <div class="mb-1 text-xs text-white/60">
        学习日志
      </div>
      <div class="max-h-30 flex flex-col gap-0.5 overflow-auto border border-white/10 rounded bg-black/40 p-2 text-xs text-white/70">
        <div v-for="(l, i) in video.logs.value" :key="i">
          {{ l }}
        </div>
      </div>
    </div>
  </div>
</template>
