<script setup lang="ts">
import type { GameStudio } from '../../modules/game-agent/use-game-studio'

import { computed } from 'vue'

/**
 * 实操面板 —— AIJADE 真正上手玩。
 *
 * 感知（OBS 截图）→ 检索经验 → 决策（LLM）→ 安全清洗 → 注入键鼠。
 * 顶部常驻安全条：紧急停止热键状态、已注入动作数、一键夺回控制权。
 */
const props = defineProps<{ studio: GameStudio }>()

const studio = props.studio
const agent = studio.agent
const safety = agent.safety

const canStart = computed(() => !agent.running.value)
const stateText = computed(() => agent.lastState.value
  ? JSON.stringify(agent.lastState.value.structured, null, 2)
  : '（暂无）')
const isRealInject = computed(() =>
  agent.inputBackendId.value === 'ipc'
  && (agent.mode.value === 'autonomous' || agent.mode.value === 'goal'),
)
</script>

<template>
  <div class="flex flex-col gap-3">
    <!-- 安全条 -->
    <div
      class="flex flex-row flex-wrap items-center justify-between gap-2 rounded-lg p-2.5"
      :class="safety.panic.value ? 'bg-rose-500/15 border border-rose-400/40' : 'bg-white/5 border border-white/10'"
    >
      <div class="flex flex-col gap-0.5">
        <div class="text-xs" :class="safety.panic.value ? 'text-rose-200 font-semibold' : 'text-white/80'">
          {{ safety.panic.value ? '⛔ 紧急停止生效中，所有注入已被拦截' : `🛡 安全网就绪 · 紧急停止热键 ${safety.hotkey.value}` }}
        </div>
        <div class="text-[10px] text-white/45">
          {{ safety.hotkeyRegistered.value ? '全局热键已注册（游戏全屏时同样有效）' : '⚠ 热键注册失败，请改用下方按钮' }}
          · 已注入 {{ safety.injectedActions.value }} 个动作 · 限速 {{ safety.maxActionsPerSecond.value }}/秒
        </div>
      </div>
      <div class="flex flex-row gap-2">
        <button
          v-if="!safety.panic.value"
          class="rounded-full bg-rose-500/80 px-3.5 py-1.5 text-xs text-white font-semibold shadow transition-colors hover:bg-rose-500"
          @click="agent.emergencyStop()"
        >
          紧急停止
        </button>
        <button
          v-else
          class="rounded-full bg-emerald-500/80 px-3.5 py-1.5 text-xs text-white font-semibold shadow transition-colors hover:bg-emerald-500"
          @click="agent.resumeFromPanic()"
        >
          解除
        </button>
      </div>
    </div>

    <div v-if="agent.error.value" class="border border-rose-400/30 rounded bg-rose-500/10 p-2 text-xs text-rose-200">
      ⚠ {{ agent.error.value }}
    </div>
    <div v-if="!agent.demoMode.value && agent.obsStatus.value !== 'connected'" class="border border-amber-400/30 rounded bg-amber-400/10 p-2 text-xs text-amber-200">
      ⚠ 未连接 OBS（{{ agent.obsStatus.value }}）：非演示模式下点「开始」需要 OBS 提供画面。请先在上方填写 WebSocket 地址与源名称，并确认 OBS 已启动、obs-websocket 已开启。
    </div>

    <!-- 模式与后端 -->
    <div class="grid grid-cols-2 gap-2 text-sm">
      <label class="flex flex-col gap-1">
        <span class="text-xs text-white/60">运行模式</span>
        <select v-model="agent.mode.value" :disabled="agent.running.value" class="border border-white/15 rounded bg-white/10 px-2 py-1 outline-none">
          <option value="copilot">副驾驶（只分析）</option>
          <option value="read">阅读模式（确认后执行）</option>
          <option value="autonomous">自主（真实注入）</option>
          <option value="goal">目标驱动（自主+目标）</option>
        </select>
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-xs text-white/60">输入后端</span>
        <select v-model="agent.inputBackendId.value" :disabled="agent.running.value" class="border border-white/15 rounded bg-white/10 px-2 py-1 outline-none">
          <option value="dry-run">演练（不按键）</option>
          <option value="ipc">真实注入（SendInput）</option>
        </select>
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-xs text-white/60">视觉后端</span>
        <select v-model="agent.visionBackendId.value" :disabled="agent.running.value" class="border border-white/15 rounded bg-white/10 px-2 py-1 outline-none">
          <option value="mock-vision">模拟视觉</option>
          <option value="ollama-vision">Ollama 视觉</option>
        </select>
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-xs text-white/60">决策后端</span>
        <select v-model="agent.plannerBackendId.value" :disabled="agent.running.value" class="border border-white/15 rounded bg-white/10 px-2 py-1 outline-none">
          <option value="mock-planner">模拟规划</option>
          <option value="ollama-planner">Ollama 规划</option>
        </select>
      </label>
    </div>

    <label class="flex flex-col gap-1 text-sm">
      <span class="text-xs text-white/60">目标（会注入决策上下文，目标模式强调执行）</span>
      <input v-model="agent.goal.value" class="border border-white/15 rounded bg-white/10 px-2 py-1 outline-none" placeholder="例如：清理当前副本的精英怪并拾取掉落">
    </label>

    <!-- 经验注入与安全参数 -->
    <div class="grid grid-cols-3 gap-2 border border-white/10 rounded-lg bg-white/5 p-2 text-sm">
      <label class="flex flex-row items-center gap-2 text-xs text-white/75">
        <input v-model="agent.useKnowledge.value" type="checkbox">
        <span>注入学习经验（{{ studio.knowledge.count.value }} 条）</span>
      </label>
      <label class="flex flex-row items-center gap-2 text-xs text-white/75">
        <span class="whitespace-nowrap">检索条数</span>
        <input v-model.number="agent.knowledgeTopK.value" type="number" min="1" max="15" class="w-14 border border-white/15 rounded bg-white/10 px-1.5 py-0.5 outline-none">
      </label>
      <label class="flex flex-row items-center gap-2 text-xs text-white/75">
        <span class="whitespace-nowrap">单批上限</span>
        <input v-model.number="agent.maxBatch.value" type="number" min="1" max="20" class="w-14 border border-white/15 rounded bg-white/10 px-1.5 py-0.5 outline-none">
      </label>
      <label class="flex flex-row items-center gap-2 text-xs text-white/75">
        <span class="whitespace-nowrap">人性化抖动</span>
        <input v-model.number="agent.jitter.value" type="number" min="0" max="8" class="w-14 border border-white/15 rounded bg-white/10 px-1.5 py-0.5 outline-none">
      </label>
      <label class="flex flex-row items-center gap-2 text-xs text-white/75">
        <span class="whitespace-nowrap">循环间隔(ms)</span>
        <input v-model.number="agent.loopIntervalMs.value" type="number" min="300" step="100" class="w-20 border border-white/15 rounded bg-white/10 px-1.5 py-0.5 outline-none">
      </label>
      <label class="flex flex-row items-center gap-2 text-xs text-white/75">
        <span class="whitespace-nowrap">限速(次/秒)</span>
        <input
          :value="safety.maxActionsPerSecond.value" type="number" min="1" max="120" class="w-16 border border-white/15 rounded bg-white/10 px-1.5 py-0.5 outline-none"
          @change="safety.configure({ maxActionsPerSecond: Number(($event.target as HTMLInputElement).value) })"
        >
      </label>
    </div>

    <!-- Ollama -->
    <div
      v-if="agent.visionBackendId.value === 'ollama-vision' || agent.plannerBackendId.value === 'ollama-planner'"
      class="grid grid-cols-3 gap-2 text-sm"
    >
      <label class="flex flex-col gap-1">
        <span class="text-xs text-white/60">Ollama 地址</span>
        <input v-model="agent.ollamaBaseUrl.value" class="border border-white/15 rounded bg-white/10 px-2 py-1 outline-none">
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-xs text-white/60">视觉模型</span>
        <input v-model="agent.visionModel.value" class="border border-white/15 rounded bg-white/10 px-2 py-1 outline-none">
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-xs text-white/60">决策模型</span>
        <input v-model="agent.plannerModel.value" class="border border-white/15 rounded bg-white/10 px-2 py-1 outline-none">
      </label>
    </div>

    <!-- OBS -->
    <label class="flex flex-row items-center gap-2 text-sm text-white/80">
      <input v-model="agent.demoMode.value" type="checkbox" :disabled="agent.running.value">
      <span>演示模式（合成画面，无需 OBS / 模型）</span>
    </label>

    <div v-if="!agent.demoMode.value" class="grid grid-cols-3 gap-2 text-sm">
      <label class="flex flex-col gap-1">
        <span class="text-xs text-white/60">OBS WebSocket</span>
        <input v-model="agent.obsUrl.value" :disabled="agent.running.value" class="border border-white/15 rounded bg-white/10 px-2 py-1 outline-none">
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-xs text-white/60">密码（可选）</span>
        <input v-model="agent.obsPassword.value" type="password" :disabled="agent.running.value" class="border border-white/15 rounded bg-white/10 px-2 py-1 outline-none">
      </label>
      <label class="flex flex-col gap-1">
        <span class="text-xs text-white/60">OBS 源名称</span>
        <input v-model="agent.obsSource.value" :disabled="agent.running.value" class="border border-white/15 rounded bg-white/10 px-2 py-1 outline-none">
      </label>
    </div>

    <div v-if="isRealInject" class="border border-amber-400/30 rounded bg-amber-400/10 p-2 text-xs text-amber-200">
      ⚠ 当前配置会真实操控你的鼠标键盘。开始前请把游戏窗口放到前台，并记住随时可按 <b>{{ safety.hotkey.value }}</b> 夺回控制权。
    </div>

    <!-- 控制 -->
    <div class="flex flex-row flex-wrap items-center gap-3">
      <button v-if="canStart" class="rounded-full bg-primary-500 px-5 py-2 text-sm text-white shadow-md transition-colors hover:bg-primary-600" @click="agent.start()">
        ▶ 开始
      </button>
      <button v-else class="rounded-full bg-rose-500/80 px-5 py-2 text-sm text-white shadow-md transition-colors hover:bg-rose-500" @click="agent.stop()">
        ■ 停止
      </button>
      <button
        v-if="agent.running.value && agent.mode.value === 'read' && agent.lastActions.value.length"
        class="rounded-full bg-amber-500/80 px-4 py-2 text-sm text-white shadow-md transition-colors hover:bg-amber-500"
        @click="agent.confirmLastActions()"
      >
        ✔ 确认执行
      </button>
      <span class="text-xs text-white/60">
        {{ agent.running.value ? (agent.demoMode.value ? '演示运行中' : `OBS ${agent.obsStatus.value}`) : '空闲' }}
        · {{ agent.injecting.value ? '正在操控' : '未操控' }}
      </span>
    </div>

    <div v-if="agent.lastFrame.value" class="overflow-hidden border border-white/15 rounded-xl bg-black/40">
      <img :src="agent.lastFrame.value.dataUrl" class="max-h-[200px] w-full object-contain">
    </div>

    <div v-if="agent.lastActions.value.length" class="text-sm">
      <div class="mb-1 text-xs text-white/60">
        本轮动作
      </div>
      <div class="flex flex-col gap-1">
        <div v-for="(a, i) in agent.lastActions.value" :key="i" class="rounded bg-white/8 px-2 py-1 text-xs text-white/85">
          <span class="text-primary-300">{{ a.type }}</span>
          <span v-if="a.key"> · {{ a.key }}</span>
          <span v-if="a.button"> · {{ a.button }}</span>
          <span v-if="a.x !== undefined"> · ({{ a.x }},{{ a.y }})</span>
          <span v-if="a.durationMs"> · {{ a.durationMs }}ms</span>
          <span v-if="a.reason" class="text-white/55"> — {{ a.reason }}</span>
          <span v-if="a.say" class="mt-0.5 block text-primary-200/80">💬 {{ a.say }}</span>
        </div>
      </div>
    </div>

    <div v-if="agent.lastDropped.value.length" class="border border-amber-400/20 rounded bg-amber-400/8 p-2 text-xs text-amber-200/80">
      安全层拦截：{{ agent.lastDropped.value.join('；') }}
    </div>

    <div v-if="agent.lastKnowledge.value" class="text-sm">
      <div class="mb-1 text-xs text-white/60">
        本轮参考的经验
      </div>
      <pre class="max-h-[120px] overflow-auto whitespace-pre-wrap border border-white/10 rounded bg-black/40 p-2 text-xs text-emerald-200/85">{{ agent.lastKnowledge.value }}</pre>
    </div>

    <div class="text-sm">
      <div class="mb-1 text-xs text-white/60">
        识别到的游戏状态
      </div>
      <pre class="max-h-[140px] overflow-auto border border-white/10 rounded bg-black/40 p-2 text-xs text-white/80">{{ stateText }}</pre>
    </div>

    <div class="text-sm">
      <div class="mb-1 text-xs text-white/60">
        运行日志
      </div>
      <div class="max-h-[140px] flex flex-col gap-0.5 overflow-auto border border-white/10 rounded bg-black/40 p-2 text-xs text-white/70">
        <div v-for="(l, i) in agent.logs.value" :key="i">
          {{ l }}
        </div>
      </div>
    </div>
  </div>
</template>
