# AIJADE 统一架构（重构后基线）

> 生成日期：2026-07-11
> 范围：把 WorkBuddy 各会话的 AIJADE 工作、H: 盘散落的功能线（语音 / 动作 / LLM / 智能家居 / 全息）统一进 `H:/AIJADE` 单体仓库，并整理为 pnpm monorepo 规范布局。
> 原则：运行中的服务保持运行（ASR `:8000`、IndexTTS2 `:8765`、Ollama `:11434` 均不中断）；GB 级本地资产与 `.env` 不入库。

## 1. 仓库拓扑（pnpm workspace）

```
AIJADE/
├─ apps/                 # 各端宿主
│  ├─ stage-web/          # Web 主端（含 /kimodo 演示页）
│  ├─ stage-tamagotchi/  # 桌面 / 电子宠物端
│  ├─ stage-pocket/       # 安卓 / iOS 移动端（Capacitor）
│  └─ ui-server-auth/     # 认证服务端
├─ packages/             # 可复用库与界面包
│  ├─ stage-ui/          # 核心 UI + 语音 / 对话 / 情绪状态 + 唤醒词 / 智能音箱 / 全息
│  ├─ stage-ui-three/     # 3D / VRM / MMD(PMX) / GLB 渲染与动作
│  ├─ stage-pages/        # 设置页（含语音 / 转录 provider 页）
│  ├─ stage-layouts/      # 布局与转写 composable
│  ├─ pipelines-audio/    # TTS chunker 等音频管线（被 stage-ui 复用）
│  ├─ i18n/              # 国际化（默认 zh-Hans）
│  ├─ memory-pgvector/    # PGVector 记忆后端（含 engine / performance / port）
│  ├─ agent-llm-client/   # 共享 OpenAI 兼容 / Ollama 客户端（能力层基础设施）
│  ├─ agent-skill-forge/  # 自主技能创建 + 演进（HY-Motion / agentskills.io）
│  ├─ agent-continuous-learning/ # 人格(13维)+内分泌(5)+LPM 话语记忆+反馈闭环
│  ├─ agent-computer-use/ # Hermes 融合的电脑操控（12 动作 schema + dry-run + MCP 融合缝）
│  ├─ agent-capabilities/ # 桥：把上述三者拼进编排器（wrapDeps/registerHooks）
│  └─ model-driver-mediapipe/ # MediaPipe 任务资产
├─ plugins/              # 社区 / 集成插件
│  ├─ aijade-plugin-xiaomi/     # 米家智能家居（7 个工具）
│  ├─ aijade-plugin-bilibili-laplace/
│  ├─ aijade-plugin-claude-code/
│  ├─ aijade-plugin-game-chess/
│  ├─ aijade-plugin-homeassistant/
│  └─ aijade-plugin-web-extension/
├─ integrations/         # 三方集成（vscode-airi 等）
├─ engines/              # 推理 / 能力引擎
├─ services/            # 后端 / 运行时服务
│  ├─ speech/            # ASR 语音识别（运行中 :8000）
│  ├─ local-llm/        # 本地 LLM（Qwythos-9B via Ollama；git 忽略）
│  ├─ computer-use-mcp/  # 计算机操控 MCP
│  ├─ discord-bot/ satori-bot/ telegram-bot/ twitter-services/ minecraft/
├─ optimization-assets/  # KIMODO + HY-Motion 融合资产（GB 级；git 忽略 venv / 模型，仅 kimodo_dryrun 样例入库）
├─ ollama-models/       # Ollama 模型仓库（运行中，git 忽略，不移动）
├─ config/amber-he/      # 全息模式配置
├─ docs/                 # 文档（含 development/airi-history 历史归档）
└─ （外部依赖）IndexTTS2 @ I:/D:（:8765，零样本 TTS，独立仓库）
```

## 2. 分层与数据流

- **表现层**：`stage-web` / `stage-tamagotchi` / `stage-pocket` 复用 `packages/stage-ui` + `stage-ui-three`。
- **语音全链路**（统一入口 `SpeechFacade`）：
  - 听：麦克风 → ASR（`services/speech` `:8000`）/ FunASR → `reportListenedEmotion` 情绪识别
  - 说：`SpeechFacade.synthesize` → Kokoro（本地）或 IndexTTS2（`:8765`，零样本）或 CosyVoice（本地适配器）→ `getTtsEmotionCapability` 情绪语音
  - 唤醒：Web Speech `useWakeWord` → VAD → ASR → LLM → TTS（智能音箱模式 `useSmartSpeaker`）
- **3D / 动作**：VRM / PMX(MMD) / GLB 经 `stage-ui-three` 渲染；KIMODO / HY-Motion 动作合成资产在 `optimization-assets`。
- **LLM**：Ollama（`:11434`）提供 OpenAI 兼容 `/v1`，运行 Qwythos-9B；OpenClaw 网关可选。
- **记忆**：`memory-pgvector`（Postgres / 向量）。

## 3. 代码整洁度（本次重构已收口）

- 移除冗余 Whisper 胶水（`composables/whisper.ts`、`libs/inference/adapters/whisper.ts`）。
- TTS chunker 去重：统一复用 `pipelines-audio` 的 `tts-chunker`，`stage-ui/src/utils/tts.ts` 退化为 shim。
- 全局 `SpeechRecognition` 类型声明（`types/speech-recognition.d.ts`）消除 vue-tsc 基线类型错。

## 4. 边界与约束

- **不入库**：`.env`、`local-llm/` 全部、`ollama-models/` 全部、`optimization-assets/` 下的 `kimodo_env` / `motion_env` / `refs` / `text_encoders` / `tmp*` / `kimodo_test` / `h` 及各类模型权重（`.gguf` / `.bin` / `.onnx` / `.safetensors` / `.ckpt`）。
- **外部服务**：IndexTTS2、Ollama 作为运行时依赖，独立于仓库版本管理。
- **安全红线**（源自同源约束，本仓库沿用）：不公开排名、变比率限速、25 分钟重置。

## 5. 智能体能力层（2026-07-11 新增）

把「与 Hermes Agent 融合后的电脑操控 + 自动技能创建 + 持续学习」落地为 5 个 AIJADE 原生 TS 包，通过既有的 `wrapDeps` / `registerHooks` 扩展点接入 `createChatOrchestratorRuntime`，**不修改编排器内部**。参考 HY-Motion、LPM 论文与 AkaneCompanionLab / emotion_spirit / leuke / Openclaw 项目，以及 Hermes Agent 的 `computer_use` schema 与 agentskills.io `SKILL.md` 标准。

- 数据流：`stage-ui` 的 `chat.ts` 用 `capabilities.wrapDeps(...)` 包裹 `performanceBridge` / `memoryBridge` 的依赖，并调用 `capabilities.registerHooks(runtime)`。
- 电脑操控默认 **dry-run**（仅记录动作、无 OS 副作用）；真实操控走 `agent-computer-use` 的 `hermes-bridge.ts` 融合缝。
- **超人格化扩展（Phase C）**：`agent-continuous-learning` 在「13 维人格 + 5 激素内分泌」内核上新增 PAD 情绪空间、大五人格（由 13 维加权派生，绝不硬编码）、三力动力学（自然/社交/个体，加和=1）、六维亲密度与心情→emoji/语音投射；`toContext` 输出紧凑、token 友好的单行补丁注入对话上下文。详见 [`docs/AGENT_CAPABILITIES.md`](./AGENT_CAPABILITIES.md) §4.2.1。
- **桌宠模式（Phase C）**：复用 `apps/stage-tamagotchi` 既有的透明 / 无边框 / 置顶主窗口，新增 `/pet` 路由（`pages/pet.vue`）实现桌面悬浮 + 打字聊天 + 调用 Agent + 超人格化展示；控制岛新增「打开桌宠模式」入口。详见 [`docs/AGENT_CAPABILITIES.md`](./AGENT_CAPABILITIES.md) §9。
- 详见 [`docs/AGENT_CAPABILITIES.md`](./AGENT_CAPABILITIES.md)。
