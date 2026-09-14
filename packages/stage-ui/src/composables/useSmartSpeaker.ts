/**
 * Amber HE Smart Speaker Mode — 琥珀HE智能音箱模式
 *
 * 串联唤醒词 → TTS应答 → 持续对话 → 关闭命令全链路。
 * 适用于 Gowild 琥珀 HE 全息投影硬件。
 *
 * 工作流程:
 *   休眠 ─"你好小爱"→ TTS"我在，请说"─→ 用户说话 → ASR → LLM → TTS ─┐
 *    ↑                                                              │
 *    └──── 用户说"关闭/退出/再见" ←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←←┘
 */

import { computed, onUnmounted, readonly, ref } from 'vue'

import { useWakeWord } from './useWakeWord'

interface SmartSpeakerOptions {
  /** 唤醒词 */
  wakePhrases?: string[]
  /** 关闭/退出命令词 */
  closePhrases?: string[]
  /** 唤醒后回调 — TTS 播报唤醒应答 */
  onWakeAck: () => void
  /** 用户命令回调 — 触发 LLM 处理 */
  onCommand: (text: string) => void
  /** 关闭回调 — 用户说再见时触发 */
  onClose: () => void
  /** 命令等待超时 (ms) */
  listenTimeout?: number
  /** 对话冷却时间 (ms) */
  cooldown?: number
}

export function useSmartSpeaker(options: SmartSpeakerOptions) {
  const {
    wakePhrases = ['你好小爱', '嘿AIJADE', '小爱同学'],
    closePhrases = ['关闭', '退出', '再见', '拜拜', '睡觉', '休息', '退下', '闭嘴'],
    onWakeAck,
    onCommand,
    onClose,
    listenTimeout = 15000,
    cooldown = 2000,
  } = options

  const isAwake = ref(false)
  const status = ref<'idle' | 'acknowledging' | 'listening' | 'processing' | 'speaking'>('idle')
  const speechText = ref('')
  const turnCount = ref(0)

  let wakeTimer: ReturnType<typeof setTimeout> | null = null
  let speechRecognition: SpeechRecognition | null = null

  const wake = useWakeWord({
    phrases: wakePhrases,
    cooldown,
    onWake: (command: string) => {
      // 如果唤醒词后直接跟着命令文本
      if (command.length > 0) {
        // 检查是否是关闭命令
        if (isCloseCommand(command)) {
          handleClose()
          return
        }
        // 直接发送命令给 LLM（跳过应答）
        handleCommand(command)
        return
      }

      // 正常唤醒 → TTS 应答 → 监听命令
      wakeUp()
    },
  })

  /** 唤醒 → TTS"我在" → 监听命令 */
  function wakeUp() {
    if (isAwake.value)
      return

    isAwake.value = true
    turnCount.value = 0
    status.value = 'acknowledging'
    speechText.value = ''

    // 播放 TTS 唤醒应答
    onWakeAck()

    // 等待 TTS 播完 + 短暂停顿后开始监听
    setTimeout(() => {
      if (!isAwake.value)
        return
      status.value = 'listening'
      startCommandRecognition()
      resetWakeTimer()
    }, 1500)

    console.log('[SmartSpeaker] 唤醒 — TTS 应答 → 监听命令')
  }

  /** 超时自动休眠 */
  function sleep() {
    if (!isAwake.value)
      return
    isAwake.value = false
    status.value = 'idle'
    turnCount.value = 0
    if (wakeTimer)
      clearTimeout(wakeTimer)
    stopCommandRecognition()
    console.log('[SmartSpeaker] 休眠 — 等待唤醒词')
  }

  /** 处理用户关闭命令 */
  function handleClose() {
    status.value = 'acknowledging'
    if (wakeTimer)
      clearTimeout(wakeTimer)
    stopCommandRecognition()
    onClose()
    // 短暂延迟后休眠
    setTimeout(sleep, 2000)
    console.log('[SmartSpeaker] 用户说再见 → 关闭会话')
  }

  /** 处理语音命令 (已过滤关闭命令) */
  function handleCommand(text: string) {
    if (!text.trim())
      return

    if (isCloseCommand(text)) {
      handleClose()
      return
    }

    speechText.value = text
    status.value = 'processing'
    turnCount.value++

    if (wakeTimer)
      clearTimeout(wakeTimer)
    stopCommandRecognition()

    onCommand(text)
    console.log(`[SmartSpeaker] 命令 #${turnCount.value}: "${text}"`)
  }

  /** 一轮回复完成后 — 继续监听下一轮 */
  function continueListening() {
    if (!isAwake.value)
      return
    status.value = 'listening'
    speechText.value = ''
    startCommandRecognition()
    resetWakeTimer()
    console.log(`[SmartSpeaker] 等待下一轮命令... (第${turnCount.value}轮后)`)
  }

  function resetWakeTimer() {
    if (wakeTimer)
      clearTimeout(wakeTimer)
    wakeTimer = setTimeout(() => {
      console.log('[SmartSpeaker] 超时，自动休眠')
      sleep()
    }, listenTimeout)
  }

  /** 检查是否是关闭命令 */
  function isCloseCommand(text: string): boolean {
    const t = text.toLowerCase().trim()
    return closePhrases.some(phrase => t.includes(phrase))
  }

  // ── 语音识别（命令模式）─────────────────────────────────────────

  function startCommandRecognition() {
    if (!window.SpeechRecognition && !window.webkitSpeechRecognition)
      return

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    speechRecognition = new SpeechRecognition()
    speechRecognition.continuous = false
    speechRecognition.interimResults = true
    speechRecognition.lang = 'zh-CN'

    speechRecognition.onresult = (event: SpeechRecognitionEvent) => {
      resetWakeTimer()

      const transcript = event.results[event.results.length - 1][0].transcript.trim()
      speechText.value = transcript

      if (event.results[event.results.length - 1].isFinal) {
        handleCommand(transcript)
      }
    }

    speechRecognition.onend = () => {
      if (isAwake.value && status.value === 'listening' && !speechText.value) {
        try { speechRecognition?.start() }
        catch (_) {}
      }
    }

    speechRecognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      if (event.error === 'no-speech') {
        // 没听到声音，重试
        try { speechRecognition?.start() }
        catch (_) {}
        return
      }
      if (event.error === 'aborted' || event.error === 'not-allowed') {
        sleep()
      }
    }

    try { speechRecognition.start() }
    catch (_) {}
  }

  function stopCommandRecognition() {
    if (speechRecognition) {
      speechRecognition.abort()
      speechRecognition = null
    }
  }

  // ── 公开 API ────────────────────────────────────────────────────

  /** TTS 播完后的状态更新 */
  function onTtsFinished() {
    if (status.value === 'speaking' || status.value === 'processing') {
      // 检查是否是因为关闭命令触发的应答
      if (speechText.value && isCloseCommand(speechText.value)) {
        sleep()
        return
      }
      continueListening()
    }
  }

  /** 手动结束当前会话 */
  function manualClose() {
    status.value = 'acknowledging'
    if (wakeTimer)
      clearTimeout(wakeTimer)
    stopCommandRecognition()
    isAwake.value = false
    onClose()
    setTimeout(sleep, 1500)
  }

  function start() { wake.start() }
  function stop() { wake.stop(); sleep() }

  onUnmounted(() => { stop() })

  const statusText = computed(() => {
    const map: Record<string, string> = {
      idle: '休眠中',
      acknowledging: '应答中...',
      listening: '聆听中...',
      processing: '处理中...',
      speaking: '回复中...',
    }
    return map[status.value] || status.value
  })

  return {
    isAwake: readonly(isAwake),
    status: readonly(status),
    statusText,
    speechText: readonly(speechText),
    turnCount: readonly(turnCount),
    isWakeListening: wake.isListening,
    wakeSupported: wake.isSupported,

    start,
    stop,
    sleep,
    manualClose,
    onTtsFinished,
    continueListening,
  }
}
