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

实验命令与产物目录见 `experiments/README.md`（含 2026-10-15 自评目标量定义更正的说明）。论文工作区（`docs/08_论文工程`）中的 `_工具/facts.py` 只读这些产物；稿件源用占位符引用其中的数字，由 `_工具/render.py` 渲染。

| 论文 | 证据目录 | 状态 |
|---|---|---|
| P1（英文）/ J1、J2（中文） | `experiments/p1/`、`experiments/growth-pilot/` | 全部在本实现上运行完成，稿件已由稿件源生成 |
| P4（英文）/ J5（中文） | `experiments/memory/`、`experiments/memory-longmemeval/` | 全部在本实现上运行完成（含对话聚类区间与 LongMemEval_s 复现），稿件已由稿件源生成 |
| P2（英文）/ J3（中文） | `experiments/rq-c/` | 7B 主运行、惰性对照、模拟阳性对照、1.5B 与温度扫描、确定性预检及其重复、差分测试、第二模型族对照（llama3.1:8b，`rq-c/family-gpu/`；llava-phi3 的第一次尝试已放弃，见 `rq-c/family/ABANDONED.md`）已完成，稿件已由稿件源生成 |

## 6. 未完成与需作者处理的事项

1. **需要作者操作**：macOS / iOS 构建（Xcode）；论文中作者单位、资助等占位信息。
2. **未能在本机完整验证**：Windows 桌面与计算机控制、各聊天平台与 B 站的真实联网、阿里云与 Google 的真实接口。
3. **检索打分（研究内核，已定性）**：冲突惩罚按冲突对累乘、总是压低较旧的一方（标准化模式下扫描前 150 个候选，关闭后交付召回大幅上升），加和模式的扫描窗口随 K 变化，检索下限为绝对值。这些都是 P4 测量与复现的对象，按设计保留并已在代码中注明；它们只存在于研究用记忆内核（`BioticMemory`），服务端记忆库不使用该内核。冲突判定对真实矛盾的精确度未评估，是否修改惩罚需先做这项评估。

## 7. 进度总览（2026-10-15）

| 项 | 状态 |
|---|---|
| 服务端、Web、Android、集成、研究装置 | ✓ 完成（缺口见 §6） |
| 代码中指向旧实现的注释与命名 | ✓ 已清理 |
| Windows 计算机控制元素编号 | ✓ 已实现（UI Automation），单元测试通过；需在 Windows 上实测 |
| RQ-C 退化守卫 | ✓ 逐步日志记录候选代码指纹，守卫只认代码有变化的恢复（旧日志沿用原规则） |
| Minecraft 装备与游泳攀爬 | ✓ 均已在本机服务端实测（42/42） |
| P1 / J1 / J2 | ✓ 由稿件源生成，构建与一致性守卫通过 |
| P4 / J5 | ✓ 由稿件源生成，构建与一致性守卫通过；新增对话聚类区间与 LongMemEval_s 复现（§5.8、表 9，479 个问题）：打分诊断与门控符号复现，标准化的交付召回提升未复现，已如实写入摘要与局限 |
| P2 / J3 | ✓ 由稿件源生成，构建与一致性守卫通过；结论已按修正后的数据重写，新增自评误差与阳性对照的数据图、差分测试（§6.7）；⏳ 第二模型族对照待 llava-phi3 运行结束后写入 |
| 安全补丁 | ✓ ASP.NET Core / .NET 升级到 10.0.13（SDK 10.0.402），修复 CVE-2026-102870、CVE-2026-96230；经作者同意作为“满两周”约束的安全例外 |
| SCI 模拟评审 | ✓ P1/P2/P4 各一轮模拟外审并按意见修改（P4 补对话聚类区间，P2 补关键文献与解析核查，P1 精简正文并补文献）；记录见 `docs/08_论文工程/审查/2026-10-15_SCI模拟评审与修改记录.md` |
| 七篇论文统一复查 | ✓ 禁用词与英文破折号清零；中文破折号按规范改写；去掉投稿稿中的内部论文编号与旧自评结论；每个投稿目录自带所用图片 |
| 旧仓库、旧生成器、目录命名 | ✓ 旧仓库与过时的论文生成器先移入 `_待删除/`，作者已于 2026-10-17 永久删除（删除后论文流水线全部重跑通过，代码与工具链不引用其中内容）；`memory-redo` → `memory`，`rq-c-dotnet` → `rq-c` |
| 全量回归（单元、E2E） | ✓ 2026-10-15（10.0.13）：Release 构建 0 警告 0 错误；单元与集成 356 通过、0 失败（7 项需外部环境跳过）；浏览器端到端 19/19 |
| 回归复核（10-15 晚） | 全量运行中 3 项依赖 Postgres 的测试在 llava-phi3 运行占满机器时失败（并发写入 20 个只有 3 个成功、测试库销毁超时），单独重跑 19/19 通过，判定为负载所致；入库基准测试改为失败时报告错误类型 |
| 投稿净稿逐字复查（10-15 晚） | ✓ 去掉 P1 文献条目中的内部核查批注、旧实现路径与内部编号、J1 悬空的“数据可用性声明”引用、表情符号；构建器把这些残留列为构建失败 |
| 第二模型族收尾流水线 | ✓ 已登记到 facts.py 与 p2-models（未完成时自动跳过）；`experiments/rq-c/finish-family.sh` 一条命令完成重建、分析、差分测试与论文渲染 |
| RQ-C 运行器稳健性（10-15 晚） | ✓ 恢复时丢弃被杀进程留下的半行记录、只重放两份记录共有的步骤、每步立即落盘；新增可选的单次回复 token 上限（`--max-reply-tokens`，默认关闭，计入指纹），达到上限记为未作答并单独计数；均有测试 |
| 第二模型族运行（llava-phi3） | ⏳ 第 1620 步一次 16 分钟的失控生成被 Ollama 以重复中止（记为未作答）；23:15 因误读缓冲输出手动停机，从第 1608 步恢复，重放逐字复现原记录；此后带 4096 token 上限运行。纯 CPU 推理约每秒 4 个 token，预计 10 月 17 日上午结束 |
| 全量回归（10-15 夜） | ✓ Release 构建 0 警告 0 错误；单元与集成 360 通过、0 失败（7 项需外部环境跳过），在实验运行期间以低优先级完成；本轮未改 Web 端，浏览器端到端沿用 19/19 |
| P4/J5 复审（10-16） | ✓ 发现诊断候选池只覆盖 50%/36% 的问题、冲突惩罚是第二个新近偏置（关闭后标准化交付召回 0.199→0.548、0.182→0.866），标准化下门控在关闭惩罚后由零变为小幅正效应；新增 `pool-check`、`delivery-check`、`gating-check` 与池内标准差，均有测试；P4/J5 相应章节已改写；LongMemEval 上关闭惩罚后门控无可检测效应，论文明确不主张门控有益 |
| 全量回归（10-16 凌晨） | ✓ 单元与集成 362 通过、0 失败（7 项需外部环境跳过） |
| P1 存档复现（10-16） | ✓ 两组变异实验在当前代码上重跑，与存档逐项一致；P1/J1/J2 写明时延测于 .NET 10.0.12 |
| 第二模型族运行进度（10-16 06:20） | ⏳ 3659/7200 步，已进入自评条件（每步先生成再验证，约 40 秒/请求）；按 7B 主运行的请求数换算剩余约 1840 个请求，预计 10 月 17 日清晨结束 |
| 第二模型族判定格式（10-16 晚） | ⚠ llava-phi3 的验证器不以 PASS/FAIL 开头，按预注册规则全部判为 FAIL，技能无法入库、每步重新生成；作者决定按预注册规则跑完（约 3 天，4151/7200 步）。`p2-models` 已加探索性复读（读最后的总体判定），收尾脚本会一并输出；可选开关 `--verdict-fallback` 已实现并测试，未使用 |
| 第二模型族进度（10-17 00:00） | ⏳ 4337/7200 步，约 34 步/小时，预计 10 月 20 日中午前后结束；§6.5 写作骨架已备好（`parts/P2_family_draft.md`，未并入） |
| 第二模型族进度（10-18 17:30） | ⏳ 5501/7200 步。10-18 起 MOSAIC c3 phase0 的 5 个工作容器（各约 130–145% CPU）与 Fabric 容器同时运行，系统负载约 80，速度由约 34 步/小时降到约 11 步/小时；剩余约 1700 步，若负载持续约需 6 天，负载解除后约 2 天。按约定未触碰其他容器 |
| 第二模型族对照（10-18） | ✓ llava-phi3 因不遵守判定格式放弃（停在 5505 步，记录保留）；按事先固定的规则（非 Qwen、7–9B 指令模型、格式预检 5/5）选出 llama3.1:8b，经 Tailscale 在 Windows RTX 5080 上运行（Ollama 0.40.0，上下文 4096），17 分钟完成。验证器放过 76/97 个不可用技能、拒绝 1/673 个可用技能，差值按任务重抽后不含零；已写入 P2/J3 §6.5、表 6、方法、效度与局限，摘要已更新 |
| 新工具 | ✓ `format-precheck`（格式预检）与 `--num-ctx` 选项，均有测试；`run-family-gpu.sh`、`finish-family.sh` 改为使用独立产物目录 |
| 收尾核查（10-18 晚） | ✓ 全量回归 374 通过 / 0 失败 / 7 跳过；浏览器端到端 19/19；投稿占位信息整理为 `docs/08_论文工程/投稿前作者待办清单.md`（九类，均需作者提供；仓库尚无提交，代码可用性声明需先确定公开方式） |
| 提示模板对照（10-18 晚） | ✓ 事先登记模板 B 的措辞与方案；主模型（权重摘要与主运行一致）在 Windows 显卡主机上以模板 A、B 各跑一遍。主机差异：A 在主机 2 上放过 0.538、拒绝 0.094（主运行 0.424/0.107），落在主运行按任务重抽的区间内；模板差异：B 下验证器对全部 750 个技能判 PASS。写入 P2/J3 新节 §6.8 与表 7，方法、效度、讨论、结论与摘要同步更新；新增 `--verify-template` 选项与测试 |
| 公开仓库（10-18） | ✓ 按作者要求以 AIJADE-next 完整覆盖 https://github.com/korose523/AIJADE（作者执行强制推送，旧历史不保留；推送前检查无密钥、无第三方数据集与模型）。GitHub CI（Ubuntu）首轮 340 通过、1 失败：电脑操控服务只实现 macOS/Windows，相应测试在其他平台改为跳过。论文中的仓库地址与提交哈希由构建脚本自动填写 |
