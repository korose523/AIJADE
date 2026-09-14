<script setup lang="ts">
import type { GameStudio } from '../../modules/game-agent/use-game-studio'

import { computed, onMounted, onUnmounted, ref } from 'vue'

/**
 * 经验库面板 —— 学习成果的仓库，也是实操时的"参考书"。
 *
 * 上半部分是提炼出的经验条目（决策时按相关度检索注入提示词），
 * 下半部分是原始学习素材（可重新提炼，比如之后换了更强的模型再炼一遍）。
 */
const props = defineProps<{ studio: GameStudio }>()

const studio = props.studio
const kb = studio.knowledge
const filterKind = ref('all')
const keyword = ref('')
const confirmingClear = ref(false)
let clearTimer: ReturnType<typeof setTimeout> | null = null

const kindLabels: Record<string, string> = {
  rule: '规则',
  combo: '连招',
  tip: '技巧',
  hotkey: '按键',
  mistake: '误区',
}

const sourceLabels: Record<string, string> = {
  'real-machine': '真机',
  'video': '视频',
  'manual': '手动',
}

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return kb.items.value.filter((it) => {
    if (filterKind.value !== 'all' && it.kind !== filterKind.value)
      return false
    if (!kw)
      return true
    return `${it.title} ${it.condition} ${it.action} ${it.tags.join(' ')}`.toLowerCase().includes(kw)
  })
})

function fmtDate(ts: number) {
  return new Date(ts).toLocaleString()
}

function fmtDuration(ms: number) {
  const s = Math.round(ms / 1000)
  if (s < 60)
    return `${s}秒`
  return `${Math.floor(s / 60)}分${s % 60}秒`
}

async function refresh() {
  await Promise.all([kb.load(), kb.loadEpisodes()])
}

async function onRedistill(id: string) {
  const n = await studio.distillById(id)
  if (n > 0)
    await refresh()
}

async function onClear() {
  if (!confirmingClear.value) {
    confirmingClear.value = true
    clearTimer = setTimeout(() => {
      confirmingClear.value = false
    }, 3000)
    return
  }
  if (clearTimer) {
    clearTimeout(clearTimer)
    clearTimer = null
  }
  confirmingClear.value = false
  await kb.clear()
}

async function onReveal() {
  await kb.revealDataDir()
}

onMounted(refresh)
onUnmounted(() => {
  if (clearTimer)
    clearTimeout(clearTimer)
})
</script>

<template>
  <div class="flex flex-col gap-3">
    <div class="flex flex-row flex-wrap items-center justify-between gap-2">
      <div class="text-sm text-white/85">
        共 <span class="text-primary-300 font-semibold">{{ kb.count.value }}</span> 条经验 ·
        {{ Object.entries(kb.byKind.value).map(([k, n]) => `${kindLabels[k] ?? k} ${n}`).join(' / ') || '暂无' }}
      </div>
      <div class="flex flex-row gap-2">
        <button class="rounded bg-white/10 px-2.5 py-1 text-xs text-white transition-colors hover:bg-white/20" @click="refresh()">
          刷新
        </button>
        <button class="rounded bg-white/10 px-2.5 py-1 text-xs text-white transition-colors hover:bg-white/20" @click="onReveal()">
          打开数据目录
        </button>
        <button class="rounded bg-rose-500/20 px-2.5 py-1 text-xs text-rose-200 transition-colors hover:bg-rose-500/35" @click="onClear()">
          {{ confirmingClear ? '再次点击确认清空？' : '清空经验' }}
        </button>
      </div>
    </div>

    <div class="grid grid-cols-3 gap-2 text-sm">
      <label class="col-span-2 flex flex-col gap-1">
        <span class="text-xs text-white/60">搜索</span>
        <input v-model="keyword" class="border border-white/15 rounded bg-white/10 px-2 py-1 outline-none" placeholder="按标题/条件/做法/标签过滤">
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-xs text-white/60">类型</span>
        <select v-model="filterKind" class="border border-white/15 rounded bg-white/10 px-2 py-1 outline-none">
          <option value="all">全部</option>
          <option value="rule">规则</option>
          <option value="combo">连招</option>
          <option value="tip">技巧</option>
          <option value="hotkey">按键</option>
          <option value="mistake">误区</option>
        </select>
      </label>
    </div>

    <div class="grid grid-cols-3 gap-2 border border-white/10 rounded-lg bg-white/5 p-2 text-sm">
      <label class="col-span-1 flex flex-row items-center gap-2 text-xs text-white/75">
        <input v-model="studio.useLLMDistill.value" type="checkbox">
        <span>提炼时调用语言模型</span>
      </label>
      <label class="flex flex-row items-center gap-2 text-xs text-white/75">
        <span class="whitespace-nowrap">每份最多</span>
        <input v-model.number="studio.distillMaxItems.value" type="number" min="1" max="20" class="w-14 border border-white/15 rounded bg-white/10 px-1.5 py-0.5 outline-none">
        <span>条</span>
      </label>
      <span class="self-center text-xs text-white/45">
        关闭模型时走启发式提炼，完全离线可用
      </span>
    </div>

    <!-- 经验条目 -->
    <div v-if="filtered.length" class="flex flex-col gap-2">
      <div
        v-for="it in filtered" :key="it.id"
        class="flex flex-col gap-1 border border-white/12 rounded-lg bg-white/5 p-2.5"
      >
        <div class="flex flex-row items-start justify-between gap-2">
          <div class="flex flex-row flex-wrap items-center gap-1.5">
            <span class="rounded bg-primary-500/20 px-1.5 py-0.5 text-[10px] text-primary-200">{{ kindLabels[it.kind] ?? it.kind }}</span>
            <span class="rounded bg-white/10 px-1.5 py-0.5 text-[10px] text-white/70">{{ sourceLabels[it.source] ?? it.source }}</span>
            <span class="text-sm text-white/90 font-medium">{{ it.title }}</span>
          </div>
          <button class="text-xs text-white/40 transition-colors hover:text-rose-300" @click="kb.remove(it.id)">
            删除
          </button>
        </div>
        <div class="text-xs text-white/65 leading-relaxed">
          <span class="text-white/45">条件：</span>{{ it.condition }}
        </div>
        <div class="text-xs text-white/80 leading-relaxed">
          <span class="text-white/45">做法：</span>{{ it.action }}
        </div>
        <div v-if="it.sequence?.length" class="text-xs text-emerald-300/85">
          可回放：{{ it.sequence.map(a => a.key ?? a.button ?? a.type).join(' → ') }}
        </div>
        <div class="flex flex-row items-center gap-2 text-[10px] text-white/40">
          <span>置信度 {{ Math.round(it.confidence * 100) }}%</span>
          <span>·</span>
          <span>已被采用 {{ it.usedCount }} 次</span>
          <span v-if="it.tags.length">· {{ it.tags.join(' / ') }}</span>
        </div>
      </div>
    </div>
    <div v-else class="rounded bg-white/5 p-3 text-center text-xs text-white/45">
      还没有经验。先去「真机学习」或「视频学习」采集素材吧。
    </div>

    <!-- 原始素材 -->
    <div class="mt-1 text-sm">
      <div class="mb-1 text-xs text-white/60">
        原始学习素材（{{ kb.episodes.value.length }}）
      </div>
      <div v-if="kb.episodes.value.length" class="flex flex-col gap-1.5">
        <div
          v-for="ep in kb.episodes.value" :key="ep.id"
          class="flex flex-row items-center justify-between gap-2 border border-white/10 rounded bg-black/25 px-2.5 py-2"
        >
          <div class="min-w-0 flex flex-col gap-0.5">
            <div class="truncate text-xs text-white/85">
              {{ ep.title }}
            </div>
            <div class="text-[10px] text-white/45">
              {{ sourceLabels[ep.source] ?? ep.source }} · {{ fmtDate(ep.startedAt) }} · {{ fmtDuration(ep.durationMs) }} ·
              {{ ep.eventCount }} 事件 / {{ ep.frameCount }} 帧
            </div>
          </div>
          <div class="flex shrink-0 flex-row gap-1.5">
            <button
              :disabled="studio.distilling.value"
              class="rounded bg-primary-500/20 px-2 py-1 text-[10px] text-primary-200 transition-colors hover:bg-primary-500/35 disabled:opacity-40"
              @click="onRedistill(ep.id)"
            >
              重新提炼
            </button>
            <button class="rounded bg-white/8 px-2 py-1 text-[10px] text-white text-white/60 transition-colors hover:bg-rose-500/25" @click="kb.deleteEpisode(ep.id)">
              删除
            </button>
          </div>
        </div>
      </div>
      <div v-else class="text-xs text-white/40">
        暂无素材
      </div>
    </div>

    <div v-if="studio.distillLogs.value.length" class="text-sm">
      <div class="mb-1 text-xs text-white/60">
        提炼日志
      </div>
      <div class="max-h-[110px] flex flex-col gap-0.5 overflow-auto border border-white/10 rounded bg-black/40 p-2 text-xs text-white/70">
        <div v-for="(l, i) in studio.distillLogs.value" :key="i">
          {{ l }}
        </div>
      </div>
    </div>
  </div>
</template>
