# AIJADE 项目现状

本文件描述 AIJADE（.NET 实现）的架构、功能状态、研究装置与实验产物，以及尚未完成的事项。每一项功能都给出证据：测试名（`tests/Aijade.Tests` 下的单元 / 集成测试，`tests/Aijade.E2E` 下的浏览器端到端测试）或实测说明。最后一节是进度总览表，每轮工作结束时更新。

> **当前适用范围（2026-10-26）**：项目以学位论文研究线为主，非研究线（伴侣产品及其扩展）只维护既有功能，不再扩张，见 [PROJECT-SCOPE](PROJECT-SCOPE.md) 与 [ADR-001](decisions/ADR-001.md)。第 4 节的功能状态是工程验证，不换算为研究进度。各模块的归属见 `configs/project-scope.json`。

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
configs/               项目范围：各模块归属研究线、共同基础或非研究线（project-scope.json）
```

研究线：Research、Experiments、Rqc、P1、Mutation、Substrate、`tools/data` 与 `experiments/`。共同基础：Core、Memory、Learning、Telemetry、Providers、Growth。其余为非研究线。第 4–6 章的研究对象另列在 `configs/project-scope.json` 的 `researchObjects` 中：Server 的 `V9`、Memory 的研究内核与契约、Integrations 的外部渲染器链路。

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

1. **需要作者操作**：macOS / iOS 构建（Xcode）；论文中第一作者的 CRediT 角色、资助、利益冲突与致谢，以及投稿信中的期刊、日期与预印本等占位（单位与导师的作者贡献角色已于 10-27 按导师意见写入）。
2. **未能在本机完整验证**：Windows 桌面与计算机控制、各聊天平台与 B 站的真实联网、阿里云与 Google 的真实接口。
3. **检索打分（研究内核，已定性）**：冲突惩罚按冲突对累乘、总是压低较旧的一方（标准化模式下扫描前 150 个候选，关闭后交付召回大幅上升），加和模式的扫描窗口随 K 变化，检索下限为绝对值。这些都是 P3 测量与复现的对象，按设计保留并已在代码中注明；它们只存在于研究用记忆内核（`BioticMemory`），服务端记忆库不使用该内核。冲突判定对真实矛盾的精确度未评估，是否修改惩罚需先做这项评估。

## 7. 进度总览（2026-10-28）

开发过程中的逐日记录见版本历史；下表只列最终状态。

**2026-10-22 导师第一次审阅之后。** 三篇论文暂缓投稿，先使主张与证据吻合；作者改为翁泽潇与郑玟圃（通讯作者）。按审阅意见能做的文书修改已在论文仓库完成。代码方面：RQ-C 运行器把代码提交号写进每次运行的 `summary.json`（可用 `AIJADE_GIT_COMMIT` 指定，远程主机上的副本也一样；找不到时给出警告，`ca0d860`）；数据集许可说明补全（LoCoMo、LongMemEval_s 的哈希与许可）；修复记忆检索可能返回本轮自身发言的问题（`819d944`）。新的运行（P1 替代设计比较与另行构造的缺陷集、P2 扩大候选与更大模型、P3 其他记忆系统与嵌入相似度）按导师排期在 12 月 1 日之后、与导师商定后再做；付费 API 先与导师商定费用。只用已有数据、不调用模型的三项分析（P3 只用可回答问题的重算与按证据计的召回、门控与打分方式的交互、P2 环境反馈对验证器错误率的影响与逐轮稳定性）现在执行：方案先于实现与执行提交在 `experiments/plans/2026-10-22-followup-analyses.md`（未在外部平台注册），结果文件记录代码提交号。

| 项 | 状态 |
|---|---|
| 审阅后的追加分析（不调用模型） | ✓ 方案提交于 `aee0429`，代码提交于 `761165d`，结果由该提交在干净工作区生成：`experiments/memory/answerable-reanalysis.json`（全部问题上的数值与已归档文件逐项一致，42/42）、`experiments/rq-c/verifier-feedback.json`（输入哈希与方案一致）。P3：排除对抗问题后各项对比方向不变；门控与打分方式的交互在可回答问题上，加和对标准化的区间含零，关闭惩罚对标准化的区间不含零但符号翻转检验 p = 0.070。P2：反馈对两种错误率的影响均未检出；逐轮趋势检验对可用技能“检出”，但第 0 轮之后每轮只有 1–2 个任务，同任务内的比较（探索性）显示这是任务构成而非验证器漂移 |
| P2-A 第 0 阶段：公开代码基准的静态兼容性筛查（不生成，不执行数据集代码） | ✓ 10-25，代码 `629187a`，结果 `experiments/p2-a/evalplus-compatibility.json`。按现有 RQ-C 判定（精确结构相等，无 BigInt、Set、元组，对象键为字符串）与 EvalPlus 评测器的特例（浮点输出强制 1e-6 容差、按集合比较、专用判定），把 HumanEval+ 164 题分为可直接移植 117、需注意 24、需改判定 8、不兼容 15；MBPP+ 378 题分为 308、10、34、26。不兼容主要是超过 2^53 的整数（15 与 18 题）。这是筛查，不是移植：期望输出须运行规范解才能得到，任务来源与是否加容差、按集合比较的判定，12 月与导师商定 |
| P2 第二主机的完整性审计（不调用模型） | ✓ 10-25。作者确认，第二模型族与提示模板 A、B 三组运行所用的显卡主机，就是另一项目因 CPU 错误记录而排除的那台。三组运行中运行器、沙箱、执行判定与分析都在主主机上，第二主机只提供模型输出。方案先于实现提交（`8b45434`），代码 `c5dfe26`，结果 `experiments/rq-c/host-audit.json`。检查结果：四组运行共 6,242 次现场生成与 3,243 条验证器回复中，无损坏字符、无空代码、无不可解析代码；验证器回复格式不符只见于 llama3.1:8b（3/770，模型行为，按规则记为 FAIL）；两份 GPU 运行日志无错误行；确定性预检在固定种子下均通过；同一 7B 模型与模板在两台主机上，各项比例的区间相互重叠。按方案读作"未见严重损坏的迹象"；不改变文本格式的变化，只有在另一台主机上重跑才能排除 |
| 范围治理：研究线为主，非研究线只维护 | ✓ 10-26。参照 MOSAIC 的 ADR-017 新增 `docs/PROJECT-SCOPE.md`、`docs/decisions/ADR-001.md` 与 `configs/project-scope.json`：模块分为研究线、共同基础、非研究线与测试，第 4–6 章的研究对象路径单独列出。`ProjectScopeTests` 检查三件事：每个模块已声明归属；研究线与共同基础不引用非研究线；共同基础不引用研究线。现有引用无越线，无需改代码。阳性对照中，故意改错的归属与漏掉的声明都被检出 |
| 导师 10-27 意见 | ✓ 第二主机审计 A5 所用的两份运行日志（`experiments/rq-c/run-family-gpu.log`、`run-template.log`）纳入版本库，他人可复核 A5；P3 表 1–9 改用 1,540 个可回答问题重算的方案提交于 `experiments/plans/2026-10-27-p3-answerable-tables.md`（不调用模型，12 月 2 日后计算）；`experiments/README.md` 删去“提交历史就是方案的时间戳”，改为只陈述提交顺序（不说明方案何时公开），并说明 10 月 22 日以前的运行脚本与记录、各 RQ-C `summary.json` 的 `preregistrationDeviation` 字段所称的 "pre-registered"，指运行前在代码中固定的协议（`Harness.cs` 的 `Preregistration`），未在外部平台注册；记录保持原样，类名与字段名不改以便与归档摘要对照，活代码中的注释已改 |
| 范围与开发顺序（导师 10-27 意见） | ✓ 10-28。`docs/PROJECT-SCOPE.md` 的开发顺序改为导师同意的顺序（设备资格与再生成在先）；第 6 章产品传递路径（P3-E 的测量对象）`src/Aijade.Client/Chat/MemoryContext.cs` 与 `src/Aijade.Server/Memory/MemoryLibrary.cs` 列入 `researchObjects`，在 P3-E 运行并归档之前不改。`ProjectScopeTests` 通过 |
| 与 MOSAIC 非研究线共享伴侣契约（ADR-002） | ✓ 10-28，作者指示的例外。`configs/companion/contract.json` 1.0.0：艾娅德的人设（两边同一段文字；默认人设随之更新）、AIJADE 9 个舞台表情对 MOSAIC 4 个情绪的名称对应、主动开口规则（闸门、权重、阈值）。主动开口的参考实现 `src/Aijade.Client/Companion/Initiative.cs` 在 MOSAIC 实现生成的 18 条向量上判定全部相同（阳性对照：阈值改为 0.76 时两项测试失败）。同日契约升为 1.1.0，主动开口接入聊天：`ChatOrchestrator.SpeakFirstAsync` 与聊天页每分钟一次的询问，设置"安静时她会先开口"默认关闭；说明与沉默消息与 MOSAIC 逐字一致（4 条向量），生成时不经记忆召回与学习观察者。契约 1.2.0：MOSAIC 在 QQ 上测过的文字渠道规则（没有身体时的两条说明与推迟动作的补句）由 `CompanionBridge` 在 Discord、Telegram、X 与 Satori 转接的平台上采用，与 MOSAIC 的常量逐字一致；聊天平台对照与方案见 `docs/CHAT-CHANNELS-MOSAIC.md`。用 MOSAIC 的家作舞台的对照与方案见 `docs/STAGE-MOSAIC.md`（建议经 MOSAIC 工作台的文字指令，不动渲染器契约）；作者选方案 A，第 1 步已完成：契约 1.3.0 的"舞台"一节与判定实现 `src/Aijade.Client/Companion/Stage.cs`，在 MOSAIC 代码生成的 45 句向量上全部一致，尚未接入界面；MOSAIC 已在 r392 采用 1.3.0（状态接口返回她在哪与姿势，跳舞可不带名字），本仓库在 r392 上重新生成向量，内容相同。第 2 步（作者选服务端转发）：服务端 `/api/v1/stage` 只限管理员、只转发到本机回环地址上的工作台、只放行七种指令；聊天页设置"舞台：MOSAIC 的家"默认关闭；用测试替身验证，尚未与运行中的工作台联机（ADR-002 补充四）。MOSAIC 已在 r389 采用契约 1.2.0（人设逐字相同，向量回归一致）。MOSAIC 只读，其一侧的采用写在 `docs/COMPANION-CONTRACT.md` 的交接一节。不触及研究对象，不进入研究 |
| 新的运行 | ⏸ 12 月起按导师同意的顺序：设备资格与第二主机三次运行再生成 → P2-A → P2-A 主运行与 P2-B → P3 表·产品路径·P3-C → P1-A·B·外部渲染器 → 第 7 章；每项方案单独推送并发给导师后再写代码 |

最终状态：

| 项 | 状态 |
|---|---|
| 服务端、Web、Android、集成、研究装置 | ✓ 完成（缺口见 §6） |
| Windows 计算机控制元素编号 | ✓ 已实现（UI Automation），单元测试通过；需在 Windows 上实测 |
| Minecraft | ✓ 寻路、跟随、挖掘拾取、放置、攻击、合成、换装备与工具、游泳攀爬均在本机官方服务端实测（42/42） |
| 安全补丁 | ✓ ASP.NET Core / .NET 升级到 10.0.14（SDK 10.0.403，10-29），修复 CVE-2026-111497（Brotli 解码越界写，经请求解压与 HttpClient 可达），并重发 10.0.13 未修完的 CVE-2026-70197（SocketAsyncEventArgs）与 CVE-2026-102870（Blazor WebAssembly Server/DevServer 包）；此前 10.0.13（SDK 10.0.402）修复 CVE-2026-96230 等。两次都经作者同意，作为“满两周”约束的安全例外；SDK 安装包按发布元数据的 SHA-512 核对 |
| 全量回归 | ✓ 最近一次本地全量（10-28，舞台第 2 步）：解决方案构建 0 警告；单元与集成 366 通过、0 失败、42 跳过（需数据库或外部环境，本地未设 `AIJADE_TEST_DATABASE_URL`）。GitHub CI（含 PostgreSQL 与 VectorChord）在 `b4933e4` 通过。浏览器端到端最近一次为 10-18 的 19/19 |
| P1 | ✓ 端到端用例、漂移矩阵与闸门矩阵、两组变异实验（在当前代码上重跑与存档逐项一致）、时延与校验开销、身份层阳性对照与机制级试点；时延测于 .NET 10.0.12 |
| P2 | ✓ 7B 主运行、惰性对照、模拟阳性对照、1.5B 与温度扫描、确定性预检、差分测试；自评目标量定义于 10-15 更正（见 `experiments/README.md`）；第二模型族对照（llama3.1:8b，Windows 显卡主机；llava-phi3 的第一次尝试因不遵守判定格式按事先规则放弃，记录保留）；提示模板对照（模板 B 下验证器放行全部技能） |
| P3 | ✓ 打分诊断与权重消融、交付轨道、门控与显著性来源、指标定义缺陷、泄漏审计、对话聚类区间、LongMemEval_s 复现；冲突惩罚定性为第二个新近偏置（关闭后标准化交付召回 0.199→0.548），门控不主张有效 |
| 研究装置 | ✓ RQ-C 运行器可恢复（丢弃半行、只重放共有步骤、逐步落盘），可选单次回复 token 上限、`--num-ctx`、`--verify-template`；`format-precheck` 格式预检；记忆实验的 `pool-check`、`delivery-check`、`gating-check`、`component-scales` |
| 公开仓库 | ✓ https://github.com/korose523/AIJADE（10-18 以本实现完整覆盖，旧历史不保留；推送前检查无密钥、无第三方数据集与模型）；语料用 `tools/data/fetch-corpora.sh` 下载并校验 |
| 论文仓库 | ✓ 私有仓库 https://github.com/korose523/AIJADE-papers：三篇英文投稿件、中文阅读译稿、稿件源与构建工具；论文中的代码地址与提交号由构建工具从本仓库读取 |
| 论文编号 | ✓ 10-19 统一为 P1/P2/P3（原 P4 改为 P3，中文稿不再单独编号）；本仓库的注释与文档同步改写，实验目录、命令名与已归档的运行记录不变 |
