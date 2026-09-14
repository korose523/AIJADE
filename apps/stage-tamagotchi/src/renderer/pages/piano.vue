<script setup lang="ts">
/**
 * 蓝牙 MIDI 电钢琴面板（AIJADE 桌宠）。
 *
 * - 扫描并连接蓝牙 MIDI 电钢琴（Web MIDI 已配对设备 / Web Bluetooth 直连）。
 * - 演奏示例曲《小星星》：同时驱动真实电钢琴（MIDI sendNote）与内置 Web Audio 合成兜底。
 * - 实时显示最近弹奏的音符，电钢琴弹奏时也能看到反应。
 *
 * 入口：桌宠页(pet.vue)的「🎹 钢琴」按钮 → 路由 /piano。
 */
import { useRouter } from 'vue-router'

import { useMidi } from '../modules/midi/use-midi'

const router = useRouter()
const {
  devices,
  connected,
  activeDevice,
  status,
  lastNotes,
  playing,
  currentNote,
  scan,
  connect,
  disconnect,
  panic,
  playDemo,
  stopDemo,
} = useMidi()

function sourceLabel(source: string): string {
  if (source === 'webmidi')
    return 'Web MIDI · 已配对'
  if (source === 'webbt')
    return '蓝牙直连'
  return source
}

function goPet() {
  router.push('/pet')
}
</script>

<template>
  <div flex="~ col" bg="white/95 dark:neutral-900/95" text="neutral-800 dark:neutral-100" fixed inset-0 select-none overflow-auto backdrop-blur-md>
    <!-- 顶栏 -->
    <div flex="~ row" items-center justify-between px-4 py-3 border-b="1 neutral-200/60 dark:neutral-700/40">
      <div flex="~ row" items-center gap-2>
        <span text-xl>🎹</span>
        <span text-base font-semibold>蓝牙 MIDI 电钢琴</span>
      </div>
      <button
        text="sm"
        rounded-lg px-2 py-1 text-neutral-500 hover:text-neutral-800 dark:hover:text-neutral-100 hover:bg="neutral-200/60 dark:neutral-700/40"
        @click="goPet"
      >
        返回桌宠
      </button>
    </div>

    <div flex="~ col" gap-4 p-4>
      <!-- 状态 -->
      <div
        rounded-xl px-3 py-2 text="sm"
        bg="neutral-100/70 dark:neutral-800/60"
        border="1 neutral-200/60 dark:neutral-700/40"
      >
        {{ status || '点击「扫描设备」开始连接你的电钢琴。' }}
      </div>

      <!-- 扫描 -->
      <button
        :disabled="playing"
        bg="primary-500 hover:primary-600"

        rounded-xl px-4 py-2 text-sm text-white font-medium shadow-md transition-colors disabled:opacity-50
        @click="scan"
      >
        🔍 扫描蓝牙 MIDI 设备
      </button>

      <!-- 设备列表 -->
      <div v-if="devices.length" flex="~ col" gap-2>
        <div text="xs" text-neutral-400 tracking-wide uppercase>
          可用设备
        </div>
        <div
          v-for="d in devices" :key="d.id + d.source"
          flex="~ row" items-center justify-between gap-2
          rounded-xl px-3 py-2
          bg="white/70 dark:neutral-800/50"
          border="1 neutral-200/60 dark:neutral-700/40"
        >
          <div flex="~ col" min-w-0>
            <span truncate text-sm font-medium>{{ d.name }}</span>
            <span text-xs text-neutral-400>{{ sourceLabel(d.source) }}</span>
          </div>
          <button
            v-if="!d.isConnected"
            bg="primary-500 hover:primary-600"
            rounded-lg px-3 py-1 text-xs text-white font-medium
            @click="connect(d)"
          >
            连接
          </button>
          <span v-else text-xs text="emerald-500" font-medium>● 已连接</span>
        </div>
      </div>

      <!-- 已连接操作区 -->
      <div v-if="connected" flex="~ col" mt-1 gap-3>
        <div rounded-xl px-3 py-2 text-sm bg="emerald-50 dark:emerald-900/30" border="1 emerald-300/50 dark:emerald-700/40">
          已连接：<b>{{ activeDevice?.name }}</b>
        </div>

        <!-- 当前/最近音符 -->
        <div flex="~ col" items-center gap-2 py-2>
          <div text="5xl" font-bold :class="currentNote?.on ? 'text-primary-500' : 'text-neutral-400'">
            {{ currentNote ? currentNote.name : '—' }}
          </div>
          <div flex="~ row" max-w-full flex-wrap justify-center gap-1>
            <span
              v-for="(n, i) in lastNotes" :key="i"
              rounded px-1.5 py-0.5 text-xs
              :class="n.on ? 'bg-primary-500/20 text-primary-600 dark:text-primary-300' : 'bg-neutral-200/60 dark:bg-neutral-700/40 text-neutral-400'"
            >{{ n.name }}</span>
          </div>
        </div>

        <!-- 演奏控制 -->
        <div flex="~ row" gap-2>
          <button
            v-if="!playing"
            flex="1" bg="primary-500 hover:primary-600"
            rounded-xl px-4 py-2 text-sm text-white font-medium shadow-md
            @click="playDemo"
          >
            ▶ 演奏示例曲《小星星》
          </button>
          <button
            v-else
            flex="1" bg="amber-500 hover:amber-600"
            rounded-xl px-4 py-2 text-sm text-white font-medium shadow-md
            @click="stopDemo"
          >
            ⏸ 停止
          </button>
          <button
            bg="rose-500 hover:rose-600"
            rounded-xl px-4 py-2 text-sm text-white font-medium shadow-md
            @click="panic"
          >
            静音
          </button>
        </div>

        <button
          text="xs" text-neutral-400 underline-offset-2 hover:text-neutral-600 hover:underline dark:hover:text-neutral-200
          @click="disconnect"
        >
          断开连接
        </button>
      </div>

      <!-- 未连接提示 -->
      <div v-else text="xs" text-neutral-400 leading-relaxed>
        提示：电钢琴需支持 Bluetooth® MIDI。可先在系统蓝牙里配对（Web MIDI 会自动列出），
        或直接点「扫描设备」由软件直连。弹奏琴键时，上方会实时显示音名。
      </div>
    </div>
  </div>
</template>
