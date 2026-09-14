/**
 * Wake Word Detection — 唤醒词检测
 *
 * 使用浏览器 SpeechRecognition API 持续监听唤醒词。
 * 检测到唤醒词后触发回调，串联 VAD → ASR → LLM 全链路。
 *
 * 默认唤醒词：'你好小爱' → 可自定义
 *
 * 用法：
 *   const wake = useWakeWord({
 *     phrases: ['你好小爱', '嘿AIJADE'],
 *     onWake: () => startListening(),
 *   })
 *   wake.start()
 */

import { onUnmounted, readonly, ref } from 'vue'

interface WakeWordOptions {
  /** 唤醒词列表 */
  phrases?: string[]
  /** 检测到唤醒词时的回调 */
  onWake: (transcript: string) => void
  /** 唤醒后冷却时间 (ms)，避免连续触发 */
  cooldown?: number
  /** 语言 */
  lang?: string
}

export function useWakeWord(options: WakeWordOptions) {
  const {
    phrases = ['你好小爱', '嘿AIJADE', '小爱同学'],
    onWake,
    cooldown = 3000,
    lang = 'zh-CN',
  } = options

  const isListening = ref(false)
  const lastWake = ref(0)
  const lastTranscript = ref('')
  const errorMessage = ref<string | null>(null)

  let recognition: SpeechRecognition | null = null

  /** 检查浏览器是否支持 */
  function isSupported(): boolean {
    return !!(window.SpeechRecognition || window.webkitSpeechRecognition)
  }

  /** 开始持续监听 */
  function start() {
    if (!isSupported()) {
      errorMessage.value = '浏览器不支持语音识别 (需要 Chrome/Edge)'
      return
    }

    if (isListening.value)
      return

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition
    recognition = new SpeechRecognition()
    recognition.continuous = true
    recognition.interimResults = true
    recognition.lang = lang
    recognition.maxAlternatives = 1

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      const now = Date.now()
      if (now - lastWake.value < cooldown)
        return

      // 检查所有结果中是否包含唤醒词
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript.trim()
        lastTranscript.value = transcript

        const matched = phrases.find(phrase =>
          transcript.includes(phrase),
        )
        if (matched) {
          lastWake.value = now
          console.log(`[WakeWord] 检测到唤醒词: "${matched}" → "${transcript}"`)

          // 提取唤醒词后的命令文本
          const commandIndex = transcript.indexOf(matched) + matched.length
          const command = transcript.slice(commandIndex).trim()

          onWake(command || transcript)
          break
        }
      }
    }

    recognition.onerror = (event: SpeechRecognitionErrorEvent) => {
      if (event.error === 'aborted' || event.error === 'not-allowed') {
        errorMessage.value = `语音识别错误: ${event.error}`
        stop()
        // 自动重启（Chrome 有时会中断连续模式）
        setTimeout(() => {
          if (!isListening.value)
            start()
        }, 1000)
      }
    }

    recognition.onend = () => {
      // 自动重启以保持持续监听
      if (isListening.value) {
        try { recognition?.start() }
        catch (_) { /* ignore */ }
      }
    }

    try {
      recognition.start()
      isListening.value = true
      errorMessage.value = null
      console.log(`[WakeWord] 开始监听唤醒词: [${phrases.join(', ')}]`)
    }
    catch (e: any) {
      errorMessage.value = `启动语音识别失败: ${e.message}`
    }
  }

  /** 停止监听 */
  function stop() {
    isListening.value = false
    if (recognition) {
      recognition.abort()
      recognition = null
    }
    console.log('[WakeWord] 停止监听')
  }

  /** 更新唤醒词列表 */
  function setPhrases(newPhrases: string[]) {
    const wasListening = isListening.value
    stop()
    phrases.splice(0, phrases.length, ...newPhrases)
    if (wasListening)
      start()
  }

  onUnmounted(() => stop())

  return {
    isListening: readonly(isListening),
    lastTranscript: readonly(lastTranscript),
    errorMessage: readonly(errorMessage),
    isSupported,
    start,
    stop,
    setPhrases,
  }
}

// Web Speech API types (SpeechRecognition / SpeechRecognitionEvent / …) are
// declared once, globally, in `src/types/speech-recognition.d.ts` (REORG Phase 1
// baseline fix). They are no longer duplicated here.
