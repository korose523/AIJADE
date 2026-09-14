# AIJADE 语音子系统架构重组计划

> 分阶段、可独立验证地统一语音抽象，**不一次性重写以免炸构建**。
> 本计划基于"超人格化情绪闭环"已落地的样板（services/speech + libs/speech/* + hearing.ts/chat.ts 改造）。

## 现状（痛点）

语音系统存在 **三层重叠抽象** + **若干重复/死代码**：

1. **Layer A — `pipelines-audio`**（真相源）：segmenter / playback / `llm-streaming-control` token bus
2. **Layer B — `stage-ui` provider registry**：`buildOpenAICompatibleProvider` + 一堆 TTS/ASR provider
3. **Layer C — BroadcastChannel bridge**：`services/speech/bus.ts`（transcription/emotion 跨标签通信）

重复/死代码：
- legacy `utils/tts.ts` 分块器 与 pipelines-audio segmenter 功能重叠
- 两套 Whisper 栈（WASM vs server vs transformers）
- 已注册但未接线的 Kokoro provider（`kokoro-local`）
- 情绪注入分散在 Stage.vue / hearing.ts / chat.ts，缺乏统一入口

## 阶段（每阶段可独立验证，验证通过再进下一阶段）

### Phase 1 — 统一三层语音抽象（当前）
- 设计 `SpeechFacade` 类型契约：synthesize(input, {providerId, emotion}) / transcribe(audio, {providerId}) / 情绪回灌
- 把 Stage.vue 的 `getTtsEmotionCapability`、hearing.ts 的 `currentUserEmotionName`、chat.ts 的 system 注入收敛到 facade
- 不动 BroadcastChannel，仅明确它只传 transcription 结果
- 验证：`vue-tsc` 全绿 + 冒烟测试通过

### Phase 2 — 去重分块器
- 删除 legacy `utils/tts.ts` 分块器，统一引用 pipelines-audio segmenter
- 提供兼容 shim，旧调用点逐步迁移

### Phase 3 — Whisper 统一
- 选定单一 Whisper 后端（优先 server 端 FunASR paraformer，统一到 funasr-transcription）
- 移除 WASM/transformers 双栈中未被引用的实现

### Phase 4 — Kokoro 接线
- 把 `kokoro-local` 从"注册但未接线"补成可用：实现 generateSpeech 直连客户端（同 index-tts.ts 模式）
- 或若确认弃用，则从 provider registry 移除

### Phase 5 — 情绪收口
- 所有情绪来源（TTS emo_text / CosyVoice instruct / ASR 检测）统一经 `tts-emotion.ts` + `currentUserEmotionName`
- 单一 emit 点，单一消费点（chat.ts system prompt + Stage.vue 表情/声音）

## 风险
- Phase 1 改动面广但侵入小（facade 包一层），优先做
- 每阶段前后跑 `vue-tsc --noEmit` 对比基线（历史仅 `useSmartSpeaker.ts`/`useWakeWord.ts` 的 SpeechRecognition 类型缺失，与本重组无关）
- 真机冒烟（`smoke_test.py`）作为回归门禁
