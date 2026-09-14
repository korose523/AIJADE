# AIJADE 游戏能力提升说明（参考 VedalAI / super-agent-party / moeru-ai/airi）

> 本次优化基于三个开源项目，针对性增强本地 AIJADE（stage-tamagotchi）的「玩游戏」与 Agent 能力。
> 合规前提：仅「看画面 / 接收游戏状态 → 理解 → 操作 / 输出意图」，不读内存、不挂钩子；纯 PvE / 研究 / 许可场景，不做 PvP 自瞄作弊。
> 真实键鼠注入永远由用户显式开启，且全局热键 **F9** 可随时紧急停止夺回控制权。

## 一、整体架构：学习 / 实操 两大部分

游戏能力被切成两条主链路，由一个总控 `useGameStudio()` 装配：

```
                    useGameStudio()
    ┌───────────────────┬──────────────────────────┐
   学习（被动吸收）                         实操（主动上手）
   ├─ 真机学习  realMachine       ├─ useGameAgent（感知→检索→决策→清洗→注入）
   ├─ 视频学习  video            │    ├─ 模式 copilot/read/autonomous/goal
   └─ 经验库    knowledge        │    ├─ 安全网 play/safety + 主进程 input-safety
        （提炼成果，决策时检索注入）  │    └─ OBS 视觉 / Ollama 规划
                                   └─ 直播    live（OBS 推流 + TTS 旁白 + 字幕）
```

- **学习 = 给 AIJADE 喂料**：真机学习看真人打、视频学习看录像/直播/解析视频，二者都落盘成「学习素材（episode）」，再由经验库提炼成结构化经验（规则 / 连招 / 技巧 / 按键 / 误区）。
- **实操 = AIJADE 自己打**：每轮循环「OBS 抓帧感知 → 经验库按相关度检索注入 → 规划器决策 → 渲染端安全清洗 → 主进程注入键鼠」。
- **直播 = 边打边播**：一键开播串联「连 OBS → 开推流 → 启动 Agent 循环」，决策器每产出一句 `say` 自动 TTS 念出并写入 OBS 字幕源。

## 二、VedalAI/neuro-game-sdk → 内置「Neuro SDK 服务器」

**项目**：https://github.com/VedalAI/neuro-game-sdk
**做法**：游戏作为 WebSocket 客户端连接 AI（默认 `localhost:8000`），注册动作、上报文本化状态（可带截图），AI 回传「动作 + say（旁白/语音）」。

**交付**：`src/main/services/game-agent/neuro-server.ts`（零外部依赖，用 Node 内置 `http/crypto/net` 实现 WebSocket 握手与帧编解码）
- 实现协议消息：`registerActions` / `state`（含 `image`+`context`）/ `query` → 回 `action`+`say` / `response`。
- 决策调用 Ollama `/api/chat`（支持 `images` 多模态）；无可用模型时自动 mock 兜底，保证链路随时可演示。
- 仅暴露 `game-agent:neuro-server:start|stop|status` 三个 IPC，由 NeuroPanel 控制启停；默认只监听 `127.0.0.1`。
- 渲染端 `neuro-client.ts`（`useNeuroServer()`）轮询状态，UI 展示连接到的游戏、AI 旁白、已注册动作、日志。

**效果**：AIJADE 成为任何集成了 neuro-sdk 的游戏（卡牌 / 视觉小说 / 回合制类）的「AI 大脑」，游戏侧执行真实按键、AIJADE 只输出意图与旁白。这是与「屏幕视觉模式」并列的第二条、更稳定的游戏接入路径。

## 三、heshengtao/super-agent-party → 多模式 + 边玩边说

**项目**：https://github.com/heshengtao/super-agent-party
**做法**：参考其多模式控制（副驾驶 / 阅读确认 / 自主 / 目标）与「LLM 边推理边发言」。

**交付**（屏幕视觉模式，即 `useGameAgent` + 实操面板）：
- 运行模式：`copilot`（只分析）/ `read`（列出动作、需用户点「确认执行」才注入）/ `autonomous`（真实注入）/ `goal`（目标驱动：自主 + 把目标注入决策上下文）。
- 规划器（mock/ollama）与动作对象新增 `say` 旁白字段，UI 实时显示 AIJADE「边玩边说」。
- 「目标」输入框作为决策上下文（尤其 goal 模式强调执行）。

## 四、moeru-ai/airi（上游）→ 对齐 Agent 循环与记忆

**项目**：https://github.com/korose523/AIJADE
**做法**：上游核心是「感知 → 记忆 → 决策 → 行动」Agent 环 + 记忆缓冲 + 多模型抽象。

**交付**：
- `use-game-agent` 的循环对齐为「感知(OBS/合成帧) → 记忆(最近帧 history 缓冲) → 决策(planner) → 行动(input)」。
- 经验库（`useKnowledgeBase`）按相关度检索 `topK` 条经验，作为 `PlannerRequest.knowledge` 注入决策；每 20 轮 `persistUsage()` 回写采用计数。
- 复用了本地已有的 `@proj-airi/duckdb-wasm` 记忆底座与 `eventa` IPC 体系。

## 五、安全网（合规底线）

**主进程 `src/main/services/game-agent/input-safety.ts`**：
- 全局热键 **F9** 紧急停止（panic）；令牌桶限速 `maxActionsPerSecond`；单飞执行避免重入。

**渲染端 `src/renderer/modules/game-agent/play/safety.ts`**：
- `sanitizeActions(actions, profile)`：白名单 `profile.allowedActions` 过滤 → 参数夹取（坐标/时长/键位）→ 人性化抖动 → 单批上限截断。
- `useInputSafety(pollMs)`：轮询主进程 `game-agent:safety:status`，暴露 panic / hotkey / injectedActions 等，支持 `panicNow / resume / configure`。
- `SafeIpcInputBackend`：经 `game-agent:send-input` 注入并解析拒绝原因（`describeRejection()`）。

## 六、文件清单

新增：
- `src/main/services/game-agent/neuro-server.ts` — Neuro SDK 服务器（主进程）
- `src/main/services/game-agent/input-recorder.ts` — 真机学习键鼠录制（主进程）
- `src/main/services/game-agent/input-safety.ts` — 主进程安全网
- `src/renderer/modules/game-agent/neuro-client.ts` — 渲染端 Neuro 客户端 + `useNeuroServer()`
- `src/renderer/modules/game-agent/play/safety.ts` — 渲染端安全清洗层
- `src/renderer/modules/game-agent/learning/real-machine.ts` — 真机学习（录制 + 关键帧对齐 + 落盘）
- `src/renderer/modules/game-agent/learning/video-learner.ts` — 视频学习（抽帧 / 直播采样 / 解说文本）
- `src/renderer/modules/game-agent/stream/obs-stream.ts` — OBS 推流/录制/场景/字幕控制
- `src/renderer/modules/game-agent/stream/use-live-stream.ts` — 直播导播台（TTS 旁白串行队列 + OBS 字幕）
- `src/renderer/modules/game-agent/use-game-studio.ts` — 总控（装配全部链路 + 一键开播 + 自动旁白）
- `src/renderer/components/GameAgent/RealMachinePanel.vue` — 真机学习面板
- `src/renderer/components/GameAgent/VideoLearningPanel.vue` — 视频学习面板
- `src/renderer/components/GameAgent/KnowledgePanel.vue` — 经验库面板
- `src/renderer/components/GameAgent/PlayPanel.vue` — 实操面板（含安全条）
- `src/renderer/components/GameAgent/StreamPanel.vue` — 直播面板
- `src/renderer/components/GameAgent/NeuroPanel.vue` — Neuro SDK 服务器面板
- `AIJADE_游戏能力提升说明.md` — 本文档

修改：
- `src/main/windows/main/index.ts` — 注册 neuro-server / input-recorder / safety 等 handler
- `src/renderer/modules/game-agent/types.ts` — `AgentAction.say`、`NeuroServerOptions/Status`、经验条目类型
- `src/renderer/modules/game-agent/planner.ts` — 输出 `say`、注入 `goal`、消费 `knowledge`
- `src/renderer/modules/game-agent/obs.ts` — `request()` 提升为公开 `call()`（直播复用同一 OBS 连接）
- `src/renderer/modules/game-agent/use-game-agent.ts` — 知识注入 + 安全清洗 + panic 轮询 + `emergencyStop/resumeFromPanic`
- `src/renderer/modules/game-agent/index.ts` — 导出 learning / play / stream 全部模块
- `src/renderer/pages/game-agent.vue` — 六 Tab（真机学习 / 视频学习 / 经验库 / 实操 / 直播 / Neuro SDK）

## 七、质量门禁与维护记录

- **Lint**：`eslint` 对 `components/GameAgent` 与 `pages/game-agent.vue` 已 **0 error**（仅剩非阻塞的 `unocss/order` 顺序告警，与既有面板一致）。
  - 注意：本项目 ESLint 规则禁止 `confirm()`（`no-alert`）与 `error instanceof Error ? error.message`（`no-restricted-syntax`，应改用 `errorMessageFrom`）。经验库面板的「清空」已改为二次点击确认，规避 `no-alert`。
  - 模板统一用 **标准 `class` 写法**（曾因 `eslint --fix` 的 attributify 排序规则把含 `/` 的裸属性拆坏，已全部迁移为 class，避免再次 `--fix` 回退）。
- **Typecheck**：`pnpm typecheck`（vue-tsc --noEmit）全量 **0 error**（vue-tsc 会编译 .vue 模板，故模板语法已验证）。
- **编译冒烟**：`electron-vite dev` 主进程 / 预加载 / 渲染进程均成功转译（516 模块），渲染 dev server 正常起在 `localhost:5173`。
  - ⚠️ 沙箱内 Electron 进程启动时若环境存在 `ELECTRON_RUN_AS_NODE=1` 会退化成纯 Node 模式，报 `does not provide an export named 'BrowserWindow'`；双击 **`E:\AIJADE\start-pet.bat`** 已用 PowerShell 把该变量真正置 `$null` 规避，正常环境无需处理。

## 八、验证状态

- [x] `pnpm --filter @proj-aijade/stage-tamagotchi typecheck`（vue-tsc）通过（exit 0）。
- [x] `eslint` 对游戏模块 **0 error**。
- [x] `electron-vite dev` 三进程（main / preload / renderer）编译无报错，渲染服务可达。
- [ ] Neuro SDK 与真实 neuro-sdk 游戏的端到端联调（协议为标准 WebSocket 文本帧，待实际游戏客户端连接）。
- [ ] 真机/视频学习 → 经验库 → 实操注入 的端到端闭环（需用户接入 OBS + 选择模型/真实注入后端在 GUI 实测）。

## 九、使用方式

双击 `E:\AIJADE\start-pet.bat` 开桌宠 → 「🎮 游戏 Agent」：
1. **真机学习**：在「实操」页确认 OBS 配置 → 切「真机学习」填标题/间隔 → 「开始观摩」→ 打一局 → 「结束并学习」自动提炼。
2. **视频学习**：选本地文件 / 直链 / OBS 源 → 设抽帧间隔 → 粘贴解说文本 → 「开始学习」→ 「结束并提炼」。
3. **经验库**：查看/搜索/按类型过滤经验，可重新提炼或清空（二次确认）。
4. **实操**：OBS 加游戏源 → 选模式（副驾驶/阅读/自主/目标）→ 勾选「注入学习经验」→ 开始；自主模式真实操作，随时 F9 夺回。
5. **直播**：连 OBS → 选字幕文本源 / 语音 → 「一键开播」（推流 + AI 上线自动旁白），可切场景、录播。
6. **Neuro SDK**：填端口/模型/目标 → 「启动服务器」→ 任意 neuro-sdk 游戏连 `ws://localhost:8000`，由 AIJADE 操控并实时旁白。

---

## 十、OBS 观察叠层（参考 obs-urlsource：把 OBS 当 AIJADE 的「眼睛」）

**目标（本次收窄后的范围）**：参考 [royshil/obs-urlsource](https://github.com/royshil/obs-urlsource) 的源码级契约，把 OBS **更好地接入 AIJADE**，让 AIJADE 像人类主播一样「**通过观察学习**」玩游戏——只「看画面 → 理解 → 把注意力画在画面上」，不读内存、不注入任何操作。这是纯感知可视化能力，是「实操/注入」链路之外的**第二条、更安全的观察通道**。

> 明确**不做**：自瞄 / 内存读取 / 反作弊绕过 / 进程级游戏钩子（DeltaForce-OBS-Locker、obs-vkcapture、obs-ptz 等仅作参考，不落地）。真实注入仍由用户显式开启，全局热键 **F9** 可随时紧急停止。

### 10.1 核心思路：复用 obs-urlsource 的「URL → 场景」渲染模式

obs-urlsource 注册了一个 id 为 `url_source` 的 OBS 输入，它周期性 `fetch` 一个 URL/API、把文本/JSON 渲染进场景。我们把 AIJADE 的「观察注意力」也通过**本地 HTTP 端点 + OBS 源轮询**呈现，于是有两种渲染后端可选：

| 后端 | OBS 源类型 | 加载地址 | 效果 |
| --- | --- | --- | --- |
| 富文本 HUD | `browser_source`（CEF/Chromium，默认） | `http://127.0.0.1:{port}/hud` | 半透明叠层 + 注意力框 + 聚焦/意图/旁白条，效果最好 |
| 纯文本叠层 | `url_source`（obs-urlsource 插件） | `http://127.0.0.1:{port}/hud.txt` | 纯文本「聚焦/意图/旁白/置信度」，兼容性更广（未装 CEF 源也能用） |

### 10.2 观察链路（全解耦、零依赖）

```
OBS 抓帧(GetSourceScreenshot)
   → OllamaVisionBackend.analyze(frame, instruction: OBSERVE_INSTRUCTION)   # 以「观察解说」视角理解
   → ObservationState { focus, goal, narration, confidence, boxes[] }
   → observeOnce() 更新 observation + pushObservationToHud()
   → 主进程 HUD 本地 HTTP(ws://127.0.0.1:{port}/hud.json)   # 状态容器，仅存状态
   → OBS 里的 browser_source/url_source 每 ~800ms~1s 轮询 → 渲染到场景
```

- **观察循环默认 1 fps**：足够「看懂画面」且省算力；UI 可调（RealMachinePanel/VideoLearningPanel 的「通过 OBS 观察画面」按钮）。
- 所有渲染在 **OBS 侧**，AIJADE 主逻辑零依赖、不碰游戏进程。

### 10.3 obs-urlsource 精确契约（已按源码对齐）

`url_source` 的 settings 严格按 obs-urlsource 的 `url_source_request_data`（nlohmann::json 反序列化）构造，见 `obs-overlay.ts` 的 `urlSourceSettings()`：

- `inputKind = "url_source"`（见 `url-source-info.c`）。
- settings keys：`url`、`request_data`(序列化 JSON 字符串)、`output_type='text'`、`template='{{output}}'`、`update_timer=1000`、`css_props`、`render_width=640`、`is_image_url=false`、`run_while_not_visible=true`、`send_to_stream=false`、`text_sources='none'`。
- `request_data` 内：`url_or_file='url'`、`method='GET'`、`headers=[]`、`output_type='text'`、`output_json_path/...`、`kv_delimiter='='` 等字段齐备，确保 obs-urlsource 能正确解析 `/hud.txt`。

### 10.4 关键文件（本次新增 / 修改）

新增：
- `src/main/services/game-agent/hud-server.ts` — 主进程 HUD 本地 HTTP 服务（`/hud` 富文本、`/hud.json` 状态、`/hud.txt` 纯文本）；注册 IPC `game-agent:hud:start|stop|push|status`。
- `src/renderer/modules/game-agent/stream/obs-overlay.ts` — `ObsOverlayController`（在 OBS 当前场景创建/更新/移除叠层源，并让叠层精确盖在游戏源之上）+ `pushObservationToHud()`。
- `src/renderer/modules/game-agent/types.ts` — 观察叠层类型 `ObservationState` / `ObservationBox`，`VisionRequest.instruction` 字段。
- `src/renderer/modules/game-agent/vision.ts` — `OllamaVisionBackend.analyze` 注入 `instruction`（观察解说指令）。

修改：
- `src/main/windows/main/index.ts` — 调用 `registerHudServer()`（在 `registerNeuroServer()` 之后）。
- `src/renderer/modules/game-agent/use-game-studio.ts` — 新增观察状态(`hudPort/hudEnabled/overlayKind/overlayName/observing/obsFps/observation`)、`OBSERVE_INSTRUCTION` 视觉指令、`observeFrame()/observeOnce()/startObservationLoop()/stopObservationLoop()/startHud()/stopHud()/ensureOverlay()/removeOverlay()/toggleOverlay()`。
- `src/renderer/modules/game-agent/index.ts` — 导出 `./stream/obs-overlay`。
- `src/renderer/components/GameAgent/StreamPanel.vue` — 「观察叠层」区（启停 HUD 服务、`browser_source`/`url_source` 选择、创建/移除叠层源）。
- `src/renderer/components/GameAgent/RealMachinePanel.vue` / `VideoLearningPanel.vue` — 「OBS 观察」条（启动/停止观察循环、`hudEnabled` 同步、`observation.focus/goal/narration` 展示）。
- `src/renderer/pages/game-agent.vue` — `statusLine` 追加「OBS 观察中 X fps」。

### 10.5 使用方式

1. OBS 里给目标游戏加「窗口捕获 / 游戏捕获」源（默认名如「火炬之光无限」），开 obs-websocket（默认 4455）。
2. 桌宠「🎮 游戏 Agent」→ 在「实操 / 真机学习 / 视频学习」任一面板点 **「▶ 通过 OBS 观察画面」**（默认 1 fps，可重复点停止）。
3. 勾选 **「同步到 OBS 观察叠层」** → 自动启动主进程 HUD 服务 + 在当前 OBS 场景创建「AIJADE 观察叠层」源（`browser_source` 富文本或 `url_source` 纯文本，可在 StreamPanel 切换）。
4. OBS 场景里即可看到 AIJADE「此刻在盯什么（注意力框）、打算干什么（意图）、怎么解说（旁白）、有多确定（置信度）」。
5. 真实键鼠注入仍走实操链路（F9 急停），观察叠层本身不注入任何操作。

### 10.6 跨游戏知识迁移引擎（宽口径阶段已落地，UI 待接线）

早先「多种游戏知识迁移」探索产出的引擎已实现（未接 UI、未端到端验证）：
- `learning/game-mechanics.ts`（机制向量 + 余弦相似度）、`learning/skill-taxonomy.ts`（`classifySkill`）、`learning/transfer.ts`（`transferKnowledge`）、`knowledge-base.ts`（`listAll()/searchTransfer()/markTransferConfirmed`）、`distill.ts`（`attachSkillMeta` 打 `skillCategory`/`universal` 标签）、`types.ts`（`SkillCategory`/`GameMechanic`/`GameGenre`）。
- 状态：可作为 AIJADE 快速上手新游戏的「机制类比」底座，待后续接 UI 并在 GUI 实测。

### 10.7 质量门禁与本次修复（21:28 续）

- **Typecheck**：`pnpm --filter @proj-aijade/stage-tamagotchi typecheck`（vue-tsc --noEmit）**0 error**。
- **Lint**：对本次改动文件（`use-game-studio.ts` / `knowledge-base.ts` / `obs-overlay.ts` / `hud-server.ts` / 三个面板 / `game-agent.vue` / `index.ts`）跑 `eslint --no-cache` **0 error**（仅剩非阻塞 `unocss/order` 顺序告警与 `no-restricted-syntax` 建议改用 `errorMessageFrom` 的警告，与既有代码一致）。注意：本次对 `.ts` 文件用了 `eslint --fix`（安全，不涉及 Vue attributify）；`.vue` 文件**绝不**再跑 `--fix`（会拆坏 `text-white/60` 这类裸属性）。
- **本次修复的 bug**（否则 typecheck/运行失败）：
  1. `use-game-studio.ts` `OBSERVE_INSTRUCTION` 数组里 `boxes=...` 项字符串字面量内换行 → `Unterminated string literal`，已合并为单行。
  2. `knowledge-base.ts` 从 `../types` 导入 `KnowledgeItem/KnowledgeKind/LearningEpisode`，但三者定义在 `./learning/types`，`GameProfile` 在 `../types` → 拆分导入路径后 typecheck 通过。
  3. `main/windows/main/index.ts` 漏调 `registerHudServer()`（仅 import 未接线）→ 补上，HUD IPC 才生效。
  4. 面板里 `studio.observation.focus.value` 误写（observation 是 shallowRef）→ 改为 `studio.observation.value.focus`。
  5. `use-game-studio.ts` 错误处理用了未定义的 `pushLog` → 改为 `console.warn`。
- **验证局限**：OBS 叠层的真实渲染需用户侧 OBS + obs-urlsource 插件（url_source 后端）实际联调；`browser_source` 后端只需 OBS 自带浏览器源即可。

---

## 十一、桌宠模式 UI 中文化与游戏入口（2026-07-31）

- **问题**：桌宠模式（桌宠浮动窗口）界面偏英文，且找不到游戏入口。
- **根因**：默认语言被英文覆盖——`packages/stage-ui/.../settings/general.ts` 在无语言设置时回退 `navigator.language || 'en'`（英文系统→`en`）并持久化；`@proj-aijade/i18n` 的 `zh-Hans` 词条本身齐全，只是没被默认启用。
- **修复（只改 app 层，无需重建共享包 dist）**：
  - `src/renderer/composables/use-language.ts` — `watch`/`restore` 兜底改 `zh-Hans`；`restore()` 无持久化设置默认 `zh-Hans`，有持久化但仍是 `en` 且主进程无显式语言则迁移到 `zh-Hans`。
  - `src/main/services/airi/i18n/index.ts` 与 `src/main/index.ts`(autoUpdater) 的 `en` 兜底改 `zh-Hans`。
  - `pet.vue` 底部游戏入口由极小链接升级为醒目「🎮 进入游戏工作室」按钮（路由 `/game-agent`）。
- **结果**：双击 `start-pet.bat` 后默认简体中文；**在右下角控制岛（展开 UI）点「🎮 进入游戏工作室」即进游戏 Agent 六 Tab 面板**（该按钮位于 `controls-island/index.vue` 展开面板的网格中，紧邻「打开桌宠模式」）。`pet.vue` 页面内同样保留该入口。`pet.vue` 页面内的入口需先点控制岛「打开桌宠模式」才看得到，故主入口以控制岛为准。若仍显示英文，是曾在设置里手动选过英文（主进程有记录，会尊重），可在设置改回简体中文。
- **质量**：改动文件（use-language.ts / i18n service / main/index.ts / pet.vue / controls-island/index.vue）`eslint --no-cache` **0 error**、`pnpm typecheck` **0 error**。pet.vue 及控制岛既有的 attributify 写法已统一改为标准 `class`（规避 `vue/valid-attribute-name` 陷阱）。

