# AIJADE 项目现状

本文件描述 AIJADE（.NET 实现）的架构、功能状态、研究装置与实验产物，以及尚未完成的事项。每一项功能都给出证据：测试名（`tests/Aijade.Tests` 下的单元 / 集成测试，`tests/Aijade.E2E` 下的浏览器端到端测试）或实测说明。最后一节是进度总览表，每轮工作结束时更新。

## 1. 约束

1. 只使用宽松许可（MIT / Apache-2.0 / BSD）的第三方组件，逐个登记在 `THIRD-PARTY-NOTICES.md`；第三方 MMD 模型不随仓库分发。
2. 论文中的每个数字都由本仓库 `experiments/` 下的产物计算得到，产物由仓库内的驱动程序生成（见 `experiments/README.md`）。
3. 凭据（如 RCON 密码）只放在文件里，不写进代码或配置。

## 2. 技术栈

| 层 | 选型 |
|---|---|
| 运行时 | .NET 10（`global.json` 固定版本） |
| 服务端 | ASP.NET Core + Npgsql + PostgreSQL（向量扩展）；Redis 作为跨进程队列，worker 为独立进程 |
| AI 接入 | `Microsoft.Extensions.AI` 双向适配 + OpenAI 兼容客户端；绘图、语音按厂商原生接口接入 |
| 界面 | Blazor 组件库（`Aijade.UI`），Web 端为 Blazor WebAssembly（`Aijade.Web`），Android 为 .NET MAUI Blazor Hybrid（`Aijade.Maui`） |
| MMD 渲染 | babylon-mmd（MIT）经 JS 互操作嵌入，打包脚本见 `tools/mmd-bundle` |
| JavaScript 沙箱 | Jint（技能基准） |
| 插件 / 工具 | Model Context Protocol（服务端与客户端）+ 内置工具提供者 |
| 测试 | xUnit v3；Playwright（.NET）浏览器端到端 |

## 3. 解决方案结构

```
src/
  Aijade.Core          事件信封、JSON 规范化与哈希、随机数、Schema
  Aijade.Memory        仿生记忆内核：编码、巩固、检索打分、信念图、HAC、CDI、DIVE/AEL/VSE/PEF、PGC、v9 运行时、LoCoMo 载入
  Aijade.Learning      技能锻造、技能库、持续学习与人格
  Aijade.Growth        成长服务、指标、合成纵向基准与机制级试点
  Aijade.Research      RQ-C 装置与分析、技能基准与沙箱、统计、记忆检索实验（MemoryEval）
  Aijade.Telemetry     研究遥测
  Aijade.Providers     LLM 客户端、模型底座与确定性校验
  Aijade.Server        HTTP 服务端：v9/v10 事件管线、渲染身份投影、晋升闸门、长期记忆、账户、计费、网关、管理
  Aijade.Client        伴侣客户端编排（对话、能力接入）
  Aijade.UI / .Web     Blazor 界面与 Web 宿主（舞台、语音、设置、管理后台）
  Aijade.Maui          Android 应用
  Aijade.Bots          机器人宿主（Discord、Telegram、Satori、X、B 站直播、Minecraft）
  Aijade.Integrations  Minecraft 协议客户端、外部渲染器链路、家居与游戏工具
  Aijade.ComputerUse   计算机控制（MCP 服务器）
tools/
  Aijade.Experiments   论文实验命令：memory（及其单独部分）、growth-pilot、identity-a7、p2-models、sandbox-isolation
  Aijade.Rqc           RQ-C 运行器
  Aijade.P1            P1 端对端与时延驱动
  Aijade.Mutation      漂移矩阵与晋升闸门矩阵的变异实验
  Aijade.Substrate     模型底座确定性校验
tests/
  Aijade.Tests         单元与集成测试（含 PostgreSQL 上的服务端测试）
  Aijade.E2E           浏览器端到端测试
integrations/          浏览器扩展、VS Code 扩展、Claude Code 插件
experiments/           论文实验产物（见 experiments/README.md）
```

## 4. 功能状态

**✓** 已实现并有测试；**◐** 部分实现或未能在本机完整验证；**✗** 未实现。

### 4.1 伴侣核心
| 项目 | 状态 | 证据 |
|---|---|---|
| 多会话聊天、流式输出 | ✓ | E2E `A_sign_up_chat_streams…`；`Sse_parser…` |
| 角色卡与人设（默认艾娅德） | ✓ | E2E `A_a_character_card_drives_the_persona_and_greeting`、`Without_a_character_the_default_companion_is_aijade_9` |
| 上下文管理（历史窗口、视觉 / 浏览器 / IDE 上下文） | ✓ | `Orchestrator_streams_stores_and_reports…` 及上下文测试 |
| 分层记忆：近期、摘要、长期（持久化、浏览、搜索、遗忘、导入导出、记录开关、语义检索） | ✓ | E2E `A_what_the_user_says_reaches_long_term_memory…`；`ProductServerTests`；`Memory_search_goes_by_meaning…`；`ContinuousLearningTests` |
| 情绪与表情驱动 | ✓ | `Expression_markers…`、`Dialogue_acts_and_expressions…`；E2E `D_an_mmd_model_loads_and_its_morphs_follow_the_reply` |

### 4.2 模型接入
| 项目 | 状态 | 证据 |
|---|---|---|
| 聊天（OpenAI 兼容）、嵌入 | ✓ | 网关路由与密钥轮换（`ProductServerTests`）；`MeaiAdapterTests` |
| 语音合成：OpenAI 兼容、ElevenLabs、阿里云 Qwen-TTS / CosyVoice | ✓ | 网关语音路由测试 |
| 语音识别：流式（Web Speech）与整段（服务端转写） | ✓ | E2E `C_with_server_recognition_an_utterance_is_recorded_transcribed_and_sent` |
| 绘图：OpenAI 兼容、Replicate、ComfyUI、Gemini | ✓ | `Images_are_drawn_by_each_backend…`；E2E `B_with_drawing_switched_on…` |

### 4.3 语音交互与舞台
| 项目 | 状态 | 证据 |
|---|---|---|
| 麦克风选择、VAD 免提、按键说话、无法启动时提示 | ✓ | E2E 服务端识别测试；`C_voice_input_that_cannot_start_says_so_clearly` |
| 口型同步 | ✓ | 音频电平驱动头像与 MMD 口型形态键 |
| MMD 模型（PMX/PMD）、VMD 动作、物理、待机 / 说话 / 表情 | ✓ | E2E `D_an_mmd_model_loads…`、`D_an_idle_vmd_motion_loops_and_moves_the_model` |
| 视线、节拍同步、背景与场景 | ✓ | E2E 视线测试、`D_beat_sync_hears_the_music_and_finds_its_tempo`；`Beat_detector…` |
| 陪伴行为（情绪姿态、倾听点头、对话眼神） | ✓ | E2E 陪伴行为测试 |
| 外部渲染器链路（UDP，可驱动 MOSAIC 原生 MMD 客户端） | ✓ | `RendererLinkTests` |

### 4.4 设置、服务端与研究装置
| 项目 | 状态 | 证据 |
|---|---|---|
| 服务商、模块开关、外观、数据导出 / 导入 / 清除、账户 | ✓ | `Settings_round_trip…`；E2E 语言与退出登录 |
| 桌面壳的系统页（窗口、托盘） | ◐ | 属于桌面端，Web 端无对应项 |
| 事件信封与严格边界、渲染身份链与配对投影、双表不落库、契约漂移矩阵、摄入校验、晋升闸门 | ✓ | `ContractDriftMatrixTests`、`P1EndToEndTests`、`AdmissionChecksTests`、`PromotionGateMatrixTests` |
| 身份层与成长层（CDI / DIVE / AEL / VSE / PEF） | ✓ | `CdiTests`、`DiveAelTests`、`VseTests`、`PefTests` |
| 账户与登录（OIDC）、计费（Stripe）、管理后台 | ✓ | `AccountsOidcTests`、`ProductServerTests`；E2E `F_the_admin_console…` |
| RQ-C 装置、技能基准与沙箱、预检、指纹、退化守卫、统计、记忆检索实验 | ✓ | `HarnessTests`、`SandboxTests`、`StatsGoldenTests`、`RqcModelsTests`、`WeightAblationTests`、`RetrievalKDependenceTests` |

### 4.5 多端与集成
| 项目 | 状态 | 证据 |
|---|---|---|
| Web、PWA | ✓ | 全部 E2E |
| Android | ✓ | 在 Android 16 模拟器上实测注册、流式对话、令牌重启后保留 |
| Windows 桌面 | ◐ | MAUI 项目含 Windows 目标，需在 Windows 上构建 |
| macOS、iOS | ✗ | 需要 Xcode，本机无法安装 |
| MCP（服务端与客户端）、工具中枢（HomeAssistant、小米、Factorio、外部 MCP） | ✓ | `McpServerTests`、`ToolTests` |
| 计算机控制 | ◐ | macOS 实现与策略有测试（`ComputerUseTests`，不触碰真实桌面）；Windows 实现（含 UI Automation 元素编号、set_value 与截图标注）已编译并有脚本与解析的单元测试，未在 Windows 上运行 |
| Discord、Telegram、Satori、X、B 站直播 | ✓ | `IntegrationTests`；真实平台需令牌，未联网测试 |
| Minecraft | ◐ | 纯 .NET 协议客户端，在本机官方服务端上实测：寻路、跟随、挖掘与拾取、放置、攻击、按配方书合成、自动穿戴更好的盔甲、挖掘前换上合适工具、游泳过水渠与爬梯上下墙（`MinecraftTests`，单元与 5 个服务端用例）；主机满载时“跟随”用例偶有超时 |
| 浏览器扩展、VS Code、Claude Code 插件、国际象棋 | ✓ | E2E `I_the_browser_extension_reads…`；`ChessTests`；node 测试 |
| 9 种语言 | ✓ | `Every_locale_has_every_key…` |

## 5. 实验与论文证据

论文编号自 2026-10-19 起统一为 P1、P2、P3（原 P4 改为 P3；中文稿不再单独编号，作为各篇的中文译稿附在同一文件夹）。本文件一律使用新编号；已归档的实验记录保留当时的写法（见 `experiments/README.md`）。

实验命令与产物目录见 `experiments/README.md`（含 2026-10-15 自评目标量定义更正的说明）。论文仓库（私有，korose523/AIJADE-papers）中的 `_工具/facts.py` 只读这些产物；稿件源用占位符引用其中的数字，由 `_工具/render.py` 渲染。

| 论文 | 证据目录 | 状态 |
|---|---|---|
| P1（附中文对照译稿） | `experiments/p1/`、`experiments/growth-pilot/` | 全部在本实现上运行完成，稿件已由稿件源生成 |
| P3（附中文译稿；10-19 前编号为 P4） | `experiments/memory/`、`experiments/memory-longmemeval/` | 全部在本实现上运行完成（含对话聚类区间与 LongMemEval_s 复现），稿件已由稿件源生成 |
| P2（附中文译稿） | `experiments/rq-c/` | 7B 主运行、惰性对照、模拟阳性对照、1.5B 与温度扫描、确定性预检及其重复、差分测试、第二模型族对照（llama3.1:8b，`rq-c/family-gpu/`；llava-phi3 的第一次尝试已放弃，见 `rq-c/family/ABANDONED.md`）已完成，稿件已由稿件源生成 |

## 6. 未完成与需作者处理的事项

1. **需要作者操作**：macOS / iOS 构建（Xcode）；论文中作者单位、资助等占位信息。
2. **未能在本机完整验证**：Windows 桌面与计算机控制、各聊天平台与 B 站的真实联网、阿里云与 Google 的真实接口。
3. **检索打分（研究内核，已定性）**：冲突惩罚按冲突对累乘、总是压低较旧的一方（标准化模式下扫描前 150 个候选，关闭后交付召回大幅上升），加和模式的扫描窗口随 K 变化，检索下限为绝对值。这些都是 P3 测量与复现的对象，按设计保留并已在代码中注明；它们只存在于研究用记忆内核（`BioticMemory`），服务端记忆库不使用该内核。冲突判定对真实矛盾的精确度未评估，是否修改惩罚需先做这项评估。

## 7. 进度总览（2026-10-19）

开发过程中的逐日记录见版本历史；下表只列最终状态。

| 项 | 状态 |
|---|---|
| 服务端、Web、Android、集成、研究装置 | ✓ 完成（缺口见 §6） |
| Windows 计算机控制元素编号 | ✓ 已实现（UI Automation），单元测试通过；需在 Windows 上实测 |
| Minecraft | ✓ 寻路、跟随、挖掘拾取、放置、攻击、合成、换装备与工具、游泳攀爬均在本机官方服务端实测（42/42） |
| 安全补丁 | ✓ ASP.NET Core / .NET 升级到 10.0.13（SDK 10.0.402），修复 CVE-2026-102870、CVE-2026-96230；经作者同意作为“满两周”约束的安全例外 |
| 全量回归 | ✓ 最近一次本地全量（10-18）：Release 构建 0 警告 0 错误；单元与集成 374 通过、0 失败、7 跳过（需外部环境）；浏览器端到端 19/19。GitHub CI（含 PostgreSQL 与 VectorChord）371 通过、12 跳过 |
| P1 | ✓ 端到端用例、漂移矩阵与闸门矩阵、两组变异实验（在当前代码上重跑与存档逐项一致）、时延与校验开销、身份层阳性对照与机制级试点；时延测于 .NET 10.0.12 |
| P2 | ✓ 7B 主运行、惰性对照、模拟阳性对照、1.5B 与温度扫描、确定性预检、差分测试；自评目标量定义于 10-15 更正（见 `experiments/README.md`）；第二模型族对照（llama3.1:8b，Windows 显卡主机；llava-phi3 的第一次尝试因不遵守判定格式按事先规则放弃，记录保留）；提示模板对照（模板 B 下验证器放行全部技能） |
| P3 | ✓ 打分诊断与权重消融、交付轨道、门控与显著性来源、指标定义缺陷、泄漏审计、对话聚类区间、LongMemEval_s 复现；冲突惩罚定性为第二个新近偏置（关闭后标准化交付召回 0.199→0.548），门控不主张有效 |
| 研究装置 | ✓ RQ-C 运行器可恢复（丢弃半行、只重放共有步骤、逐步落盘），可选单次回复 token 上限、`--num-ctx`、`--verify-template`；`format-precheck` 格式预检；记忆实验的 `pool-check`、`delivery-check`、`gating-check`、`component-scales` |
| 公开仓库 | ✓ https://github.com/korose523/AIJADE（10-18 以本实现完整覆盖，旧历史不保留；推送前检查无密钥、无第三方数据集与模型）；语料用 `tools/data/fetch-corpora.sh` 下载并校验 |
| 论文仓库 | ✓ 私有仓库 https://github.com/korose523/AIJADE-papers：三篇英文投稿件、中文阅读译稿、稿件源与构建工具；论文中的代码地址与提交号由构建工具从本仓库读取 |
| 论文编号 | ✓ 10-19 统一为 P1/P2/P3（原 P4 改为 P3，中文稿不再单独编号）；本仓库的注释与文档同步改写，实验目录、命令名与已归档的运行记录不变 |
