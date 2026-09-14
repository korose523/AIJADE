# AIJADE 智能体能力层（Agent Capabilities）

> 生成日期：2026-07-11
> 范围：在 `H:/AIJADE` 单体仓库中新增「与 Hermes Agent 融合后的电脑操控 + 自动技能创建 + 持续学习」能力层；Phase C 进一步**扩展超人格化**并新增**桌宠模式（Desktop Pet Mode）**。
> 目标：把参考论文（HY-Motion、LPM）与开源项目（AkaneCompanionLab、emotion_spirit、leuke、Openclaw）的能力，落地为 AIJADE 原生的、可独立测试的 TypeScript 包，并通过既有的 `wrapDeps` / `registerHooks` 扩展点接入对话编排器，**不修改编排器内部**。

---

## 1. 为什么这么做

用户原始诉求：AIJADE 缺一个「与 Hermes Agent 融合后的控制电脑相关的 agent 能力，主要是**自动创建 skill 技能**与**持续学习**的能力」。

Hermes Agent（Nous Research，位于 `C:\Users\Administrator\AppData\Local\hermes\hermes-agent\`）是一个 Python + Tauri + Rust 单体仓库，通过 LLM 工具调用循环 + `tools/computer_use/` 驱动 `cua-driver`（Windows 走 `SendInput` + Windows UI Automation）来控制电脑；并具备「复杂任务后自动创建 skill、skill 在使用中自我改进、周期性记忆唤醒、兼容 agentskills.io 开放标准」的特性。

直接把整个 Hermes 单体仓库拷贝进 AIJADE（严格 TS 工作区）不可行。因此采用**契约融合**策略：

- 抽取 Hermes 的**契约**（agentskills.io 的 `SKILL.md` 格式、`computer_use` 动作 schema、学习循环语义），用 AIJADE 原生 TS 重新实现；
- 预留**融合缝**（`agent-computer-use` 的 `hermes-bridge.ts`），后续无需耦合即可把真实的 Hermes `cua`/MCP 后端接进来。

---

## 2. 包结构（5 个新增包）

| 包 | 职责 | 关键依赖 |
|----|------|----------|
| `packages/agent-llm-client` | 共享的 OpenAI 兼容 / Ollama 客户端（`createOllamaClient`，`complete` / `jsonComplete<T>` / `listModels`）；零依赖日志器 | `nanoid` |
| `packages/agent-skill-forge` | 自主技能创建 + 演进：teachable-moment 检测 → 生成 → 校验 → 注册；从反馈演进（`evolveSkill`）；`SKILL.md` 序列化/反序列化（agentskills.io 格式） | `agent-llm-client`, `nanoid`, `zod` |
| `packages/agent-continuous-learning` | 人格（13 维）+ 内分泌（5 激素）+ LPM 有界话语记忆 + 反馈→技能演进闭环 | `agent-llm-client`, `agent-skill-forge` |
| `packages/agent-computer-use` | Hermes 融合的电脑操控：12 动作 schema、dry-run 后端、Hermes MCP 融合缝（无 `node:child_process` 耦合） | `zod` |
| `packages/agent-capabilities` | 桥：把上面三者拼进 `createChatOrchestratorRuntime`（`wrapDeps` / `registerHooks`，与 memory / performance 同构） | 以上全部 + `core-agent`, `server-sdk` |

所有包 `exports` 直接指向 `./src/index.ts`，下游按 TS 源码消费，无需预构建。

---

## 3. 接入方式（与 memory / performance 同构的桥模式）

`packages/stage-ui/src/stores/chat/memory-performance.ts` 已经示范了桥模式：`wrapDeps(deps)` 注入 `runtimeContextProviders` + 生命周期回调（`onUserMessageAppended` 等），`registerHooks(runtime)` 挂 `runtime.hooks.*`。

`createAgentCapabilitiesBridge` 完全镜像这一模式：

```ts
// packages/stage-ui/src/stores/chat.ts （已接线）
const capabilitiesLlm = createOllamaClient({ baseURL: 'http://localhost:11434', model: 'qwen2.5:7b' })
const computerUse = createComputerUseCapability(createDryRunBackend())
const capabilities = createAgentCapabilitiesBridge({ llm: capabilitiesLlm, computerUse })

const runtime = createChatOrchestratorRuntime(
  capabilities.wrapDeps(performanceBridge.wrapDeps(memoryBridge.wrapDeps(baseDeps))),
)
capabilities.registerHooks(runtime)
```

桥内部做四件事：

1. **上下文注入**：`provider()` 把「人格状态 + 技能索引 + 电脑操控提示」打包成一个 `ContextMessage`（`ContextUpdateStrategy.ReplaceSelf`），通过 `runtimeContextProviders` 注入；同时 `getSystemPromptSupplement` 追加技能索引与电脑操控说明。
2. **回合摄取**：`onUserMessageAppended` / `onAssistantMessageAppended` → `learning.ingestTurn()`，把对话流喂给持续学习层。
3. **自动建技能**：`onAssistantTurnReady` → `learning.compact()` + `maybeCreateSkill()`（检测 teachable-moment，命中则 `generateSkill` → `register`）。带 `creating` 互斥锁，防止并发重入。
4. **人格漂移**：`registerHooks` 在 `onChatTurnComplete` 中按回合间隔 `learning.tick(dt)`，让情绪随时间衰减/漂移，避免「冻结」。

> 设计取舍：桥**故意不**把 `memory` 传给能力层（`createSkillForge` 仅接收 `llm`），避免与 AIJADE 已有的分层记忆引擎重复喂数据。

---

## 4. 三大能力详解

### 4.1 自动技能创建（`agent-skill-forge`）

- **检测**：`detectTeachableMoment(history)` 用 LLM 判断是否值得沉淀（`shouldCreate` + `draft`）。
- **生成 + 自修复**：`generateSkill(draft)` 生成 `SkillPackage`；若结构校验不过，带错误信息再生成一轮（self-repair）。
- **校验**：`validateSkill(pkg)` = Zod 结构校验（0.6 分起步）+ 可选 sandbox + LLM 自评（最高 1.0），输出 `ok / errors / warnings / score`。
- **演进（HY-Motion 风格）**：`evolveSkill(pkg, feedback)` 从用户反馈改进技能、bump 版本、追加 `evolutionLog`。
- **两种形态都满足用户要求**：
  - AIJADE 原生 TS 能力模块（`SkillPackage`，可挂载 `module.run` 变成可执行工具）；
  - 可导出的 `SKILL.md`（`skillToMarkdown` / `parseSkillMarkdown`，严格遵循 agentskills.io 格式：YAML frontmatter + When to Use / Prerequisites / How to Run / Quick Reference / Procedure / Pitfalls / Verification）。
- **手写入口**：`defineSkill({ frontmatter, body })` 一键创建（默认值 `version: '0.1.0'`, `author: 'AIJADE'`, `source: 'hand-authored'`）。

frontmatter 校验规则（对齐 Hermes 规范）：`name` 小写连字符、`description` ≤ 60 字符且以句号结尾、`version` semver。

### 4.2 持续学习（`agent-continuous-learning`）

- **人格向量 `PersonaVector`（13 维）**：openness / warmth / curiosity / patience / formality / playfulness / caution / confidence / empathy / spontaneity / diligence / assertiveness / stability —— 来自 emotion_spirit 的人格漂移模型。
- **内分泌状态 `EndocrineState`（5 激素）**：dopamine / serotonin / cortisol / oxytocin / adrenaline —— 来自 leuke 的 tick 动力学；激素向基线衰减，并反过来偏置人格向量（cortisol 升 → caution 升、patience 降；dopamine 升 → curiosity / playfulness 升）。
- **交互应用**：`applyInteraction(state, signal)`（`valence` / `arousal`）同时推动激素与人格。
- **时间漂移**：`drift(state, dtMs)` 在「静默时钟」tick 上调用，激素均值回归 + 人格缓慢漂移，避免人格乱跑。
- **LPM 有界话语记忆 `DiscourseMemory`**：`createDiscourseMemory({ window, maxChunks })` —— 近期消息逐字保留，溢出部分由 LLM 压缩成「sink」句，环形保留 ≤ 3 个 chunk（对应 LPM 的 chunking + sink token + 3-chunk 混合缓存）。提供 `recentMessages()`（供 teachable-moment 检测）、`context()`、`compact()`、`stats()`。
- **反馈闭环**：`captureFeedback(feedback)` 按名称/描述匹配技能 → `forge.evolveSkill` → 回写注册表。

`createContinuousLearning({ llm, memory?, skillForge?, personaSeed?, feedbackThreshold })` 把以上组装为统一入口：`getPersona`、`ingestTurn`、`tick`、`captureFeedback`、`contextSupplement`、`discourse`。

#### 4.2.1 超人格化扩展（Phase C，参考 emotion_spirit / leuke / AkaneCompanionLab / Openclaw）

在既有「13 维人格 + 5 激素内分泌」内核之上，从参考项目抽取并落地了更完整的超人格化投射层（API 全部在 `agent-continuous-learning`，并已加入 `index.ts` 导出）：

- **PAD 情绪空间** `toPAD(state) → { pleasure, arousal, dominance }`：把人格/激素态折叠成 Mehrabian PAD 三维，供 VRM 表情引擎实时驱动（对应 `stage-ui-three` 的 `setEmotionPAD(pad)`）。
- **大五人格** `toBigFive(vector) → { O, C, E, A, N }`：**必须由 13 维人格向量加权派生**（emotion_spirit 硬约束，绝不硬编码），例如 `N` 由 `1 - stability` 等派生。
- **三力动力学** `toThreeForce(state) → { natural, social, individual }`：自然/社交/个体三股驱动力，加和**恒为 1**，决定行为的「独处 vs 社交 vs 自我实现」倾向（AkaneCompanionLab 单轮 performance bundle 风格）。
- **六维亲密度** `IntimacyState { warmth, trust, dependence, security, familiarity, longing }`：`createIntimacyState()` 初始化，`applyIntimacy(state, signal)` 随交互更新，`driftIntimacy(state, dtMs)` 做时间漂移——**空闲时 `longing` 缓慢爬升**（leuke 静默时钟的"想你"机制）。
- **心情投射** `toMoodProfile(state) → { label, emoji, voiceRate, voicePitch, style }`：语音速率/音高由内分泌推导（`voiceRate = 1 + 0.2·(DA-0.5) - 0.1·(5HT-0.5) + 0.15·(ADR-0.3)`，钳制 0.6..1.6），对应 leuke 的 `voice_loop`（激素 → 语速/音高）。`MOOD_EMOJI` 映射：content😊 / motivated🤩 / stressed😣 / connected🥰 / alert😮。
- **紧凑上下文补丁** `toContext(state)` 现在输出 token 友好的单行摘要：`Persona[...] mood=LABEL😊 PAD(p:..,a:..,d:..) big5(O:..,C:..,E:..,A:..,N:..) force(social:..) intimacy(warmth:..,trust:..,familiar:..,longing:..)`（Openclaw 的 numeric persona matrix 思路，便宜且可被 LLM 直接消费）。
- **静默时钟 / 空闲时长** `idleMs()`（来自 `learning` 接口）：返回距上次交互的毫秒数，供 `driftIntimacy` 与桌宠的"想你"提示使用。

> 兼容性：`createPersonaState` / `applyInteraction` / `drift` 的签名与行为完全保持，既有测试继续通过；新增结构仅为**增量投射**，不改动核心 13 维 + 5 激素演化。

### 4.3 电脑操控（Hermes 融合，`agent-computer-use`）

- **动作 schema**：`COMPUTER_USE_ACTIONS`（12 个：capture / click / double_click / right_click / middle_click / drag / scroll / type / key / set_value / wait / list_apps / focus_app）、`CAPTURE_MODES`（som / vision / ax）、`SAFE_ACTIONS`（capture / wait / list_apps 无需 OS 副作用）。`COMPUTER_USE_TOOL_SCHEMA` 为 OpenAI function-calling JSON，逐字对齐 Hermes。
- **后端抽象**：`ComputerUseBackend` 接口 + `createDryRunBackend()`（只记录动作、不产生 OS 效果，对齐 AIJADE `computer-use-mcp` 的 dry-run）。
- **融合缝 `hermes-bridge.ts`**：`buildHermesMcpCall(params)`（构造 MCP `tools/call` 负载）+ `createHermesBackend(transport)`（把外部 Hermes `cua`/MCP 包成 `ComputerUseBackend`）。**这是把真实 Hermes 后端接进来的唯一扩展点**，当前不耦合 `node:child_process`。
- **能力封装**：`createComputerUseCapability(backend)` 暴露 `toolSchema` + `call(params)`（先经 Zod 校验再路由到后端）。

---

## 5. 参考映射（论文 / 仓库 → 落地位置）

| 参考 | 核心思想 | AIJADE 落地 |
|------|----------|-----------|
| **HY-Motion**（论文） | 从人类反馈做强化学习式技能进化 | `agent-skill-forge` 的 `evolveSkill(pkg, feedback)`（bump 版本 + 追加 `evolutionLog`），`agent-continuous-learning` 的 `captureFeedback` 闭环 |
| **LPM**（论文，arXiv:2604.07823） | 有界话语记忆：chunking + sink token + 3-chunk 混合缓存 | `agent-continuous-learning` 的 `DiscourseMemory`（window + maxChunks 环形 + LLM 压缩 sink） |
| **AkaneCompanionLab** (misaka-coder) | 工具-校验-反馈循环 | `agent-skill-forge` 的 `validateSkill`（结构 + sandbox + LLM 自评）与 `generateSkill` 的自修复 |
| **emotion_spirit** (Aston957) | 13 维人格漂移 | `agent-continuous-learning` 的 `PersonaVector`（13 维）+ `applyInteraction` / `drift` |
| **leuke** (Wsk160122) | 内分泌 tick 情绪动力学 + 静默时钟 | `agent-continuous-learning` 的 `EndocrineState`（5 激素）+ `drift(dtMs)`（在 `onChatTurnComplete` 按间隔调用） |
| **Openclaw---New-memory** (Chiyuchen-web) | 三核记忆（工作 / 长期 / 情景） | 工作记忆 = `DiscourseMemory.recentMessages()`；长期记忆 = `memory-pgvector` 情景层；上下文补丁 = `learning.contextSupplement()`（人格 + 话语） |
| **超人格化扩展（Phase C）** | PAD 情绪空间 + 大五（由 13 维派生）+ 三力动力学 + 六维亲密度 + 心情→emoji/语音 | `toPAD` / `toBigFive` / `toThreeForce` / `IntimacyState`(`applyIntimacy`/`driftIntimacy`) / `toMoodProfile`；`toContext` 紧凑单行补丁 |
| **Hermes Agent** | 电脑操控 schema + agentskills.io skill 标准 + `/learn` 自动建技能 | `agent-computer-use`（schema + dry-run + `hermes-bridge` 融合缝）；`agent-skill-forge`（`SKILL.md` 序列化 + teachable-moment 自动建技能） |

---

## 6. 如何启用 / 使用

默认在 `packages/stage-ui/src/stores/chat.ts` 已接线（`autoCreateSkills` 默认 `true`，电脑操控默认 dry-run）。

- **关闭自动建技能**：`createAgentCapabilitiesBridge({ ...autoCreateSkills: false })`。
- **接真实 Hermes 后端**（扩展点）：实现 `ComputerUseTransport`，用 `createHermesBackend(transport)` 替换 `createDryRunBackend()`，再把 `createComputerUseCapability(backend)` 传入桥。
- **导出技能**：`skillToMarkdown(pkg)` 得到 `SKILL.md` 文本，可直接落盘或推送 agentskills.io。
- **手写技能**：`defineSkill({ frontmatter: { name, description }, body: { title, whenToUse, procedure } })`。

---

## 7. 校验状态（本交付）

| 包 | typecheck (`tsc --noEmit`) | 测试 (`vitest run`) |
|----|---------------------------|---------------------|
| agent-llm-client | ✅ Done | ✅ 6 passed |
| agent-computer-use | ✅ Done | ✅ 6 passed |
| agent-skill-forge | ✅ Done | ✅ 5 passed |
| agent-continuous-learning | ✅ Done | ✅ 6 passed |
| agent-capabilities | ✅ Done | ✅ 2 passed |
| stage-ui（集成接线） | ✅ `vue-tsc --noEmit` 通过 | — |

> 修复记录：初版存在 4 类严格模式问题，已全部修复——`agent-llm-client` 未使用声明与 `nanoid` 占位 hack（改为每请求 trace id）；`agent-skill-forge` 未使用类型 + `parseSkillMarkdown` body 解析不收集段落内容（重写为按行收集）+ 引号/嵌套 frontmatter 往返；`agent-continuous-learning` `toContext` 误读 `PersonaVector.dopamine/cortisol`（应为 `EndocrineState`）；`agent-capabilities` 向 `createSkillForge` 误传 `memory` + 钩子回调返回 `void`（改为 `async` 返回 `Promise<void>`）；`stage-ui` 缺 3 个 workspace 依赖（已补并重新链接）。

---

## 8. 限制与后续

- **电脑操控默认 dry-run**：真实 OS 操控需接入 `hermes-bridge` 后端（或 AIJADE 已有的 `computer-use-mcp`），当前桥已留好扩展点。
- **技能 sandbox**：`validateSkill` 支持可选 `sandbox`，默认不执行（LLM 自评），安全且离线可用。
- **LLM 依赖本地 Ollama**（`qwen2.5:7b`）：可替换为任意 OpenAI 兼容端点。
- **metadata 嵌套块**：`SKILL.md` 的 `metadata:` 子块写入/读取已支持一层嵌套，更深结构建议后续用 YAML 库替代手写解析。

---

## 9. 桌宠模式（Desktop Pet Mode，Phase C）

AIJADE 已内置 `apps/stage-tamagotchi`（Electron 透明 / 无边框 / 置顶虚拟角色应用）。其主窗口**本就是透明、无边框、`screen-saver` 级别置顶**，因此"桌宠模式"不需要新建应用——而是复用已完全初始化的渲染进程，新增 `/pet` 路由（`apps/stage-tamagotchi/src/renderer/pages/pet.vue`）。

### 9.1 能力对照

| 用户要求 | 落地方式 |
|----------|----------|
| **桌面悬浮** | 主窗口已由 `transparentWindowConfig()` + `setAlwaysOnTop(true, 'screen-saver', 1)` 实现透明 / 无边框 / 置顶；`pet.vue` 头像区 `@mousedown="startDraggingWindow?.()"` 调用 `electronStartDraggingWindow` 拖拽（非 Linux）。 |
| **打字聊天** | `pet.vue` 复用 `useChatSyncStore.requestIngest({ text, toolset: 'artistry' })` —— 与 `InteractiveArea.vue` 同一管道，**自动继承**能力层桥（自动建技能 / 电脑操控 / 持续学习），并展示最近一条助手气泡（`lastAssistant`）。 |
| **调用 Agent** | 聊天请求经 `chat-sync`（权威窗口）→ `chatOrchestrator.ingest`，触发完整 Agent 循环（工具调用、技能创建、上下文注入）。 |
| **超人格化展示** | `pet.vue` 直接读取 `chatOrchestrator.personaState`（响应式投影，由 `chat.ts` 的 `onChatTurnComplete` 同步）；按 `endocrine` 5 激素映射心情 emoji，展示亲密度（熟悉% / 信任%）与"想你"提示（`longing > 0.45` 时）。 |

### 9.2 入口与打包

- **进入**：控制岛（`controls-island/index.vue`）新增「打开桌宠模式」按钮（`i-solar:cat-bold`，`router.push('/pet')`）；`pet.vue` 内「返回完整界面」`router.push('/')` 回到完整 Stage。
- **打包**：随现有 `pnpm --filter @proj-aijade/stage-tamagotchi run build:win`（及 `build:mac` / `build:linux`）一并产出，**无需额外构建配置**。
- **数据流图**：

  ```
  用户(桌宠输入框)
    → pet.vue.send()
    → chatSyncStore.requestIngest({ text, toolset: 'artistry' })
    → [权威窗口] chatOrchestrator.ingest
        ├─ capabilities.wrapDeps → memory / performance / capabilities 桥
        ├─ 上下文注入：learning.contextSupplement()（超人格化补丁）
        ├─ 工具调用 / 自动建技能 / 电脑操控(dry-run)
        └─ onChatTurnComplete → personaState 同步
    → pet.vue 读取 personaState → 心情 emoji / 亲密度 / 气泡
  ```
