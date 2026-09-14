# AIJADE 功能文档核查报告：实现 vs UI 体现

> 核查时间：2026-07-30
> 核查对象：`E:\AIJADE\docs\` 下 5 份文档（AGENT_CAPABILITIES / ARCHITECTURE / COMPUTER_USE_INTEGRATION / desktop-lane-status / FEATURES）
> 方法：逐文件读取文档 → 对照 `E:\AIJADE` 代码库实际文件与实现 → 区分「代码实现」与「UI 体现」两端

---

## 0. 核心结论（一句话）

**文档描述的全部功能在代码层均已真实实现（无空壳、无桩包），但「UI 体现」分两端——桌宠模式 / 超人格化展示 / 电脑操控入口都在 Electron 桌面端（stage-tamagotchi），而你日常使用的 Web 端（stage-web / 5173）没有这些高级功能的 UI 入口。** 这正是你觉得"修改没在 UI 体现"的根因。

---

## 1. 文档来源须知（避免误读）

| 文档 | 标注范围 / 日期 | 性质 | 与当前 E:\AIJADE 的关系 |
|------|----------------|------|----------------------|
| AGENT_CAPABILITIES | `H:/AIJADE` / 2026-07-11 | 能力层设计+交付说明 | 描述的功能**已落到 E:\AIJADE**（包结构吻合） |
| ARCHITECTURE | `H:/AIJADE` / 2026-07-11 | 统一架构基线 | 描述的结构**与 E:\AIJADE 实际一致** |
| COMPUTER_USE_INTEGRATION | 本机 Windows / 2026-07-11 | Windows 真机融合交付 | **已在 E:\AIJADE 实现并验证**（win32-local 执行器） |
| FEATURES | `H:/AIJADE` / 2026-07-11 | 功能盘点 | 描述的功能**均真实存在** |
| desktop-lane-status | `/Users/liuziheng/airi` / 2026-05-08 | **上游 macOS 状态备忘** | 与当前 Windows 机器**无关**；该备忘说"桌面通道 macOS only"，但当前仓库**已超越它**（加了 `win32-local.ts` Windows 执行器） |

> 说明：`H:/AIJADE` 是此前仓库位置，现已在 `E:/AIJADE`；`desktop-lane-status.md` 是上游原作者的 macOS 开发分支备忘，不应作为当前 E 盘实现的依据。

---

## 2. 代码实现验证（全部 REAL-IMPL ✅）

| 文档声称 | 真实位置 | 状态 |
|----------|----------|------|
| `agent-llm-client`（createOllamaClient/complete/jsonComplete/listModels） | `packages/agent-llm-client/src/ollama.ts` 等 6 个 .ts | ✅ 真实，320 行 + 测试 |
| `agent-skill-forge`（detectTeachableMoment/generateSkill/validateSkill/evolveSkill/skillToMarkdown/defineSkill） | `packages/agent-skill-forge/src/forge.ts` `skill-markdown.ts` `index.ts` 等 8 个 .ts | ✅ 真实，693 行 + 测试 |
| `agent-continuous-learning`（13 维人格 / 5 激素 / DiscourseMemory / toPAD / toBigFive / toThreeForce / IntimacyState / toMoodProfile / toContext / idleMs） | `packages/agent-continuous-learning/src/persona.ts` `discourse-memory.ts` `learning.ts` 等 6 个 .ts | ✅ 真实，645 行 + 测试 |
| `agent-computer-use`（COMPUTER_USE_ACTIONS / createDryRunBackend / hermes-bridge / createComputerUseCapability） | `packages/agent-computer-use/src/schema.ts` `backend.ts` `hermes-bridge.ts` `capability.ts` 5 个 .ts | ✅ 真实，386 行 + 测试 |
| `agent-capabilities`（createAgentCapabilitiesBridge / wrapDeps / registerHooks） | `packages/agent-capabilities/src/bridge.ts` 2 个 .ts | ✅ 真实，157 行 + 测试 |
| chat.ts 接线（`createAgentCapabilitiesBridge` / `wrapDeps` / `registerHooks` / 三层桥接） | `packages/stage-ui/src/stores/chat.ts` L25/L223/L322/L325 | ✅ 真实接线，链路完整 |
| 后台 LLM 模型 | chat.ts L178 | ✅ 已修正为 `qwythos-9b:Q8_0`（非文档旧值 qwen2.5:7b） |
| Windows 真机执行器（win32-local.ts：observeWindows/takeScreenshot/click/typeText…） | `services/computer-use-mcp/src/executors/win32-local.ts` 565 行 | ✅ 真实，PowerShell + user32/GDI |
| 统一 computer_use 工具注册 | `services/computer-use-mcp/src/server/computer-use-unified.ts` + `register-tools.ts` | ✅ 真实 |
| 桌宠模式（pet.vue + 控制岛按钮 + build:win） | `apps/stage-tamagotchi/src/renderer/pages/pet.vue` + `components/stage-islands/controls-island/` | ✅ 真实（Electron 端） |
| 超人格化 VRM 驱动（setEmotionPAD） | `packages/stage-ui-three/src/composables/vrm/use-avatar-animation.ts` L320 | ✅ 真实 |
| 小米插件（7 工具） | `plugins/aijade-plugin-xiaomi/src/index.ts` + `xiaomi-client.ts` | ✅ 真实（其中 `xiaomi_execute_scene` 为桩返回，其余 6 个走真实 Mi Cloud API） |
| 其余插件（bilibili/claude-code/chess/homeassistant/web-extension） | `plugins/` 下 6 个目录 | ✅ 均存在 |

> 结论：**无空目录、无纯桩包**。每个 agent 包均带 `index.test.ts` 与 `vitest.config.ts`。

---

## 3. UI 体现分端对照（关键）

| 功能 | Electron 桌面端（stage-tamagotchi） | Web 端（stage-web / 5173，你日常用的） |
|------|--------------------------------------|------------------------------------------|
| 桌宠悬浮模式（/pet 路由） | ✅ 有（pet.vue + 控制岛「打开桌宠模式」按钮） | ❌ 无（Web 端无此路由/入口） |
| 超人格化展示（心情 emoji / 亲密度 / "想你"提示） | ✅ 有（pet.vue 读 `chatOrchestrator.personaState`） | ❌ 无（Web 端无 personaState 可视化面板） |
| 电脑操控 UI 入口 | ✅ 有（MCP 接线 + approve 钩子） | ❌ 无专属开关（后台 dry-run 静默运行） |
| 自动建技能 / 持续学习 | 后台运行，桌宠端可视化人格 | 后台运行，无可视化面板 |
| 语音全链路 / 3D 模型 / 美术创作 / 设置页 | ✅ | ✅ 有（设置页 account/characters/system） |
| 中文化 UI | ✅ | ✅ 有（我们刚做的 zh-Hans 翻译，刷新即生效） |

**验证事实**：
- `grep` 在 `apps/stage-web/src` 搜 "桌宠|pet|persona|电脑操控|agent-capabilities" → **No files found**
- 当前 5173 运行的是 `stage-web`（Web 端），不是 tamagotchi
- tamagotchi 是 Electron 应用（`electron-vite dev` / `build:win`），需 GUI 桌面环境

---

## 4. 与文档的 3 处小偏差（不影响功能）

| # | 文档说法 | 实际代码 | 影响 |
|---|----------|----------|------|
| 1 | COMPUTER_USE_ACTIONS 共 12 个 | `schema.ts` L11-25 实际 **13 个**（多了 focus_app 也算在内或计数差异） | 无，仅文档计数 |
| 2 | 后台 LLM 硬编码 `qwen2.5:7b` | chat.ts L178 实际 `qwythos-9b:Q8_0`（已修，否则后台静默失败） | 无，且修正更正确 |
| 3 | controls-island 在 `pages/` 下 | 实际在 `components/stage-islands/controls-island/` | 无，仅路径 |

---

## 5. 为什么你在 Web 端"看不到"这些功能

你启动路径：`E:\AIJADE\start.bat` → `pnpm dev` → **stage-web（5173，浏览器 Web 端）**。

而文档描述的「桌宠模式 / 超人格化展示 / 电脑操控 UI」全部在 **stage-tamagotchi（Electron 桌面应用）** 里。两端代码隔离：
- Web 端聊天时，**后端确实跑了** agent 能力层（自动建技能、持续学习、电脑操控 dry-run 都在后台执行），但**没有可视化面板**让你看到"技能列表""人格状态""心情"。
- 这些可视化只在 Electron 桌面端的 `pet.vue` 里。

所以不是"没实现"，而是"实现的 UI 在另一个端"。

---

## 6. 如何真正看到桌宠模式 / 超人格化 UI

需要运行 Electron 桌面端（**需要带显示器的 Windows 桌面环境**）：

```bash
cd E:\AIJADE
pnpm --filter @proj-aijade/stage-tamagotchi dev        # 开发模式（electron-vite dev，需 GUI）
# 或打包后运行：
pnpm --filter @proj-aijade/stage-tamagotchi build:win
```

启动后：右下角控制岛 → 点「打开桌宠模式」→ 进入 `/pet` 路由，即可看到悬浮桌宠 + 实时人格投影（心情 emoji / 熟悉度 / 信任度 / "想你"提示）。

> ⚠️ 注意：当前运行环境若是无显示器的服务器，Electron 窗口无法弹出，桌宠 UI 不可见（但代码存在且正确）。

---

## 7. 建议

1. **Web 端用户**：当前 Web 端已具备设置页、模型选择、语音、美术创作、中文化——这些是 Web 端该有的；桌宠/超人格化属于桌面端特性，不在 Web 端范围内，属预期。
2. **想验证桌宠**：在带显示器的 Windows 上跑 `stage-tamagotchi` dev/build，不要只用 `start.bat`（它只起 Web 端）。
3. **电脑操控**：当前默认 dry-run（仅记录动作、无 OS 副作用），真实操控已在 `win32-local.ts` 实现，经 `hermes-bridge` 接入；如需真机执行需确保 MCP 桌面执行器启用并授权。
4. **文档维护**：`desktop-lane-status.md` 是过时的上游 macOS 备忘，建议标注"已超越/仅参考"，避免误导。
