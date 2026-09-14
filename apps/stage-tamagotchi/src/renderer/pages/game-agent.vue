<script setup lang="ts">
/**
 * 游戏 Agent 面板（/game-agent）—— AIJADE 的「游戏工作室」。
 *
 * 整个能力被切成两大部分：
 *
 *   【学习】  真机学习：在旁边看真人玩，同步记录键鼠 + 画面，提炼成经验
 *            视频学习：看录像/直链/直播，抽帧理解，结合解说文本提炼
 *            经验库  ：学习成果的仓库，实操时按相关度检索注入决策
 *
 *   【实操】  看 OBS 画面 → 检索经验 → 决策 → 安全清洗 → 真实操控鼠标键盘
 *   【直播】  OBS 推流 + AI 旁白语音 + 同步字幕，一键开播
 *
 * 合规底线不变（参照 AI-collaborative-game / ScreenPlay、上游 moeru-ai/aijade）：
 * 只「看画面 → 理解 → 操作」，不读内存、不挂钩子；真实注入永远由用户显式开启，
 * 且随时可用全局热键 F9 夺回控制权。
 */
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'

import KnowledgePanel from '../components/GameAgent/KnowledgePanel.vue'
import NeuroPanel from '../components/GameAgent/NeuroPanel.vue'
import PlayPanel from '../components/GameAgent/PlayPanel.vue'
import RealMachinePanel from '../components/GameAgent/RealMachinePanel.vue'
import StreamPanel from '../components/GameAgent/StreamPanel.vue'
import VideoLearningPanel from '../components/GameAgent/VideoLearningPanel.vue'

import { useGameStudio } from '../modules/game-agent/use-game-studio'

const router = useRouter()
const studio = useGameStudio()

type TabKey = 'real-machine' | 'video' | 'knowledge' | 'play' | 'stream' | 'neuro'

const tabs: { key: TabKey, label: string, group: string }[] = [
  { key: 'real-machine', label: '真机学习', group: '学习' },
  { key: 'video', label: '视频学习', group: '学习' },
  { key: 'knowledge', label: '经验库', group: '学习' },
  { key: 'play', label: '实操', group: '实操' },
  { key: 'stream', label: '直播', group: '直播' },
  { key: 'neuro', label: 'Neuro SDK', group: '直播' },
]

const active = ref<TabKey>('play')

const statusLine = computed(() => {
  const parts: string[] = []
  if (studio.realMachine.recording.value)
    parts.push('真机学习中')
  if (studio.video.learning.value)
    parts.push('视频学习中')
  if (studio.observing.value)
    parts.push(`OBS 观察中 ${studio.obsFps.value.toFixed(1)}fps`)
  if (studio.distilling.value)
    parts.push('提炼中')
  if (studio.agent.running.value)
    parts.push(studio.agent.injecting.value ? '实操中（正在操控）' : '实操中（仅分析）')
  if (studio.live.status.value.streaming)
    parts.push(`直播中 ${studio.live.durationText.value}`)
  return parts.length ? parts.join(' · ') : '空闲'
})
</script>

<template>
  <div class="h-full w-full flex flex-col select-none items-center overflow-auto p-4 text-white">
    <div class="max-w-[720px] w-full flex flex-col gap-3">
      <!-- 顶栏 -->
      <div class="flex flex-row items-center justify-between">
        <div class="text-lg font-semibold">
          🎮 游戏工作室 · {{ studio.profile.name }}
        </div>
        <button class="text-xs text-white/60 underline-offset-2 hover:text-white hover:underline" @click="router.push('/pet')">
          返回桌宠
        </button>
      </div>

      <div class="flex flex-row items-center gap-2 text-xs text-white/60">
        <span
          class="h-1.5 w-1.5 rounded-full"
          :class="studio.busy.value ? 'bg-emerald-400 animate-pulse' : 'bg-white/25'"
        />
        <span>{{ statusLine }}</span>
        <span v-if="studio.agent.safety.panic.value" class="text-rose-300 font-semibold">· ⛔ 紧急停止生效中</span>
      </div>

      <!-- Tab -->
      <div class="flex flex-row flex-wrap gap-1 border border-white/10 rounded-lg bg-white/5 p-1">
        <button
          v-for="t in tabs" :key="t.key"
          class="rounded-md px-3 py-1.5 text-xs transition-colors"
          :class="active === t.key ? 'bg-primary-500/30 text-primary-100 font-medium' : 'text-white/60 hover:bg-white/8 hover:text-white/85'"
          @click="active = t.key"
        >
          <span class="mr-1 text-[10px] text-white/35">{{ t.group }}</span>{{ t.label }}
        </button>
      </div>

      <!-- 内容 -->
      <RealMachinePanel v-if="active === 'real-machine'" :studio="studio" />
      <VideoLearningPanel v-else-if="active === 'video'" :studio="studio" />
      <KnowledgePanel v-else-if="active === 'knowledge'" :studio="studio" />
      <PlayPanel v-else-if="active === 'play'" :studio="studio" />
      <StreamPanel v-else-if="active === 'stream'" :studio="studio" />
      <NeuroPanel v-else-if="active === 'neuro'" />

      <p class="border border-amber-400/30 rounded bg-amber-400/10 p-2 text-xs text-amber-300/80 leading-relaxed">
        ⚠️ 责任提示：自动化操作在线游戏可能违反其用户协议并导致封号。本功能用于研究 / 无障碍 / 许可场景，请勿用于破坏公平性。
        开启「自主模式」即表示你了解并自担风险；真机学习只记录你自己的操作，不上传任何数据。全局热键 <b>F9</b> 可随时紧急停止。
      </p>
    </div>
  </div>
</template>
