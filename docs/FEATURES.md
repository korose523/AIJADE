# AIJADE 功能清单（重构后基线，2026-07-11）

> 本文为「检索 WorkBuddy 全部 AIJADE 内容 → 整合进 H:/AIJADE → 重构为统一单体项目」后的功能盘点。

## 一、核心对话与角色
- 多端 AI 虚拟角色（Web / 桌面宠物 / 移动端），共享 `stage-ui`。
- Provider 系统：LLM / Ollama / Qwythos 自动发现（`/v1/models`）。
- 中文化 UI：默认 `zh-Hans`（5 个 i18n 模块统一默认语言）。

### 1.1 桌宠悬浮模式（Desktop-Pet Mode）
- **入口**：右下角悬浮控制抽屉（`controls-island`）的「打开桌宠模式」按钮 → `router.push('/pet')`。
- **窗体即桌宠**：AIJADE 主窗口本身为透明 / 无边框 / 置顶，因此 `/pet` 路由（经 `unplugin-vue-router` 自动注册）即是悬浮在桌面的宠物本体，无需额外窗口。
- **复用已初始化的 renderer**：对话走同一条 `chatSyncStore.requestIngest({ text, toolset: 'artistry' })` 管线，天然经过 `agent-capabilities` 桥（自动技能创建、电脑操控、持续学习）。
- **实时人格投影**：`chatOrchestrator.personaState`（`agent-continuous-learning` 的 `PersonaState`）驱动表情与亲密度——由 5 项内分泌激素（dopamine/serotonin/cortisol/oxytocin/adrenaline）映射出心情 emoji，由 `intimacy.familiarity / trust / longing` 渲染「熟悉 / 信任 / 想你」提示（静默越久 `longing` 越高，呈现「好像有点想你了…」）。
- **可拖拽**：`mousedown` 调用 Electron 窗口拖拽（`electronStartDraggingWindow`，Linux 除外）。
- **返回完整舞台**：底部「返回完整界面」按钮 `router.push('/')`。
- 详见 [`docs/AGENT_CAPABILITIES.md`](./AGENT_CAPABILITIES.md) 的能力层接入说明。

## 二、语音全链路（SpeechFacade 统一入口）
- ASR 语音识别（`services/speech` `:8000`）。
- TTS 多引擎：Kokoro（本地）、IndexTTS2（零样本，`:8765`）、CosyVoice（本地适配器）。
- 情绪语音：`getTtsEmotionCapability` + `tts-emotion` 情绪化合成。
- 聆听情绪：`reportListenedEmotion` 识别用户语气。
- 唤醒词：`useWakeWord`（Web Speech，监听「你好小爱」等）。
- 智能音箱模式：`useSmartSpeaker`（唤醒 → VAD → ASR → LLM → TTS 全链路）。
- 代码收口：移除冗余 Whisper 胶水；TTS chunker 去重复用 `pipelines-audio`。

## 三、3D / 动作 / 模型
- VRM 角色渲染（`stage-ui-three`，lookAt / 表情 / blendshape）。
- MMD / PMX / PMD 导入（`pmx-loader`，基于 three-stdlib MMDLoader）。
- GLB / glTF 导入（`loadGlbFallback`）。
- KIMODO + HY-Motion 动作合成融合（`optimization-assets` 资产 + `kimodo_dryrun` 样例）。

## 四、本地 LLM
- Qwythos-9B（Q4_K_M / Q8_0）经 Ollama（`:11434`）OpenAI 兼容端点。
- 启动脚本 `services/local-llm/start_qwythos.bat`。
- 可选 OpenClaw 网关（`:18789`）暴露 chatCompletions / tools。

## 五、智能家居 / 扩展
- 米家插件 `aijade-plugin-xiaomi`（7 个工具：设备查询 / 控制 / 场景等）。
- bilibili-laplace、claude-code、game-chess、homeassistant、web-extension 插件。
- computer-use-mcp、discord / satori / telegram / twitter / minecraft 服务。

## 六、全息 / 音箱形态
- 全息模式 `amber-he-mode`（透明背景 + 投影，适配 720p 全息屏，`?hologram=1`）。
- 智能音箱全链路（见第二节）。

## 七、记忆与引擎
- `memory-pgvector`：PGVector 记忆后端（`engine` / `performance` / `port` 模块）。
- `engines/` 推理与能力引擎。

## 八、智能体能力层（2026-07-11 新增）
- **自动技能创建**（`agent-skill-forge`）：从对话中检测「可教时刻」→ 生成 → 结构/沙箱/LLM 三重校验 → 注册；技能从用户反馈自我演进（`evolveSkill`，HY-Motion 风格）；可导出的 agentskills.io `SKILL.md`。
- **持续学习**（`agent-continuous-learning`）：13 维人格漂移（emotion_spirit）+ 5 激素内分泌动力学与静默时钟漂移（leuke）+ LPM 有界话语记忆（window + sink chunk 环形）；反馈闭环驱动技能演进。
- **电脑操控**（`agent-computer-use`，Hermes 融合）：12 动作 `computer_use` schema + dry-run 后端 + Hermes MCP 融合缝；默认 dry-run，真实操控可经融合缝接入 Hermes `cua`/MCP。
- **桥接**（`agent-capabilities`）：以 `wrapDeps` / `registerHooks` 同构方式接入 `createChatOrchestratorRuntime`，自动注入人格/技能上下文、摄取回合、按回合漂移人格。
- 详见 [`docs/AGENT_CAPABILITIES.md`](./AGENT_CAPABILITIES.md)。

## 九、文档与历史
- `docs/development/airi-history/`：2026-06-27 / 2026-07-09~11 工作日志归档（来自 WorkBuddy 各会话）。
- `docs/ARCHITECTURE.md`、`docs/FEATURES.md`、`docs/AGENT_CAPABILITIES.md`：统一架构、功能分析与智能体能力层说明。
