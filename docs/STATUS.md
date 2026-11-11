# AIJADE 项目现状

**2026-11-12 最新开发验证。** [清单驱动的实时研究流程](../experiments/ch7/live-manifest-2026-11-12/README.md)已按先行方案 `1ffb94b`、输入冻结 `6b6e157` 和实现 `7a162ec` 完成。运行器不按旧案例编号选择干预或预期结果，使用真实返回的任务/代码/行为及显式操作。首轮在二十条前缀后因全局交换增量持续超限停止，零条后缀不计作零错误；原记录保留。修订记录 `341a683` 之后，一次固定 120 秒空载准入通过（交换范围 32 MiB），在相同上限、二进制、输入和新二十份数据库上完成一轮条件性重跑：二十条完整轨迹，106.27 秒，交换增量零。独立重建与七种破坏控制通过；五项解析、五项计分控制及本地完整回归 660 通过/23 跳过均保留，38 浏览器测试未启用。完整原始记录、空载窗口、两个批次、构建失败及清理四十份数据库均归档；已知窗口计数与此前相同，不是新留出案例、总体效果或正式 Mac 资格。正式四十对方案的案例数/后端核定、新案例构造、P2/P3 科学缺口和作者/导师确认仍开放。

**2026-11-12 计分准备记录。** [不依赖开发编号的计分接口](../experiments/ch7/manifest-preparation-2026-11-12/README.md)按先行方案 `c75df8e` 完成；既有二十条条件记录换名、重排后，逐例及两组汇总与原冻结计分器一致。十八项仪器检查包含 C2 不利结果、反向比较和缺失观测拒用；另列孤立 spec/report，并将缺失或错误关联晋升记录的正常链判为不完整。原实际正常结果与所有主计数不变。331 项实际源码/输入/依赖文件绑定原公开版本；十二个新归档文件仅含既有记录派生和仪器检查，没有新模型判读或留出观察。四十对新案例方案只是待核定建议，未生成案例或种子；通用实时运行器仍待实现，正式方案/案例数/后端确认及表 7.3 仍开放。

**2026-11-12 配对开发测量。** [C1 基线与配对开发计分](../experiments/ch7/paired-development-2026-11-12/README.md)按先行方案/顺序/计分 `290439f`，在执行代码 `82f223b` 上完成十对已知案例、二十份原数据库与共同的十个渲染意图。C1 保留准入、执行、晋升三闸门、幂等和撤销；C2 加关联与共同事务。预定非法晋升窗口 7、非法复用窗口 8：C1 的非法持久化晋升为 3/7、非法复用为 2/8，C2 为 0/7、0/8。I3 首次合法动作与 I7 撤销前晋升不误计；S1 语义限制保留，第二轮动作语义未测。首次本地默认回归的一项 QQ 观察超时、隔离通过和原配置 655 通过/22 跳过均保留，原因未确定，38 浏览器检查仍跳过。测后 DTO/协议核验修正有先行记录 `831a321` 和审计代码 `87a6dd0`；四项转换控制、七种破坏控制通过，原始数据、二进制和计分未改，测量未重跑。全新保留批次及正式方案/案例数确认、P2 新判读、P3 答案质量、独立人工核验和正式 Mac 资格仍开放。以下历次段落保留各自测量日期与范围。

本文件描述 AIJADE（.NET 实现）的架构、功能状态、研究装置与实验产物，以及尚未完成的事项。每一项功能都给出证据：测试名（`tests/Aijade.Tests` 下的单元 / 集成测试，`tests/Aijade.E2E` 下的浏览器端到端测试）或实测说明。最后一节是进度总览表，每轮工作结束时更新。

当前优先完善情感陪伴产品，角色、地点时区、关系、收藏和主动保存的共同日记按账号／角色共享。配置与同步见 [COMPANION](COMPANION.md)，模块边界见 [PROJECT-SCOPE](PROJECT-SCOPE.md) 和 [ADR-004](decisions/ADR-004.md)。

共享能力装配、统一回复流、精简运行配置和参考来源见 [ARCHITECTURE](ARCHITECTURE.md)。本机 `companion` 队列按任务唤醒，完整配置保留原 worker 时序；研究管线与既有测量源码保留。

[第 7 章后续检索驱动开发批次](../experiments/ch7/retrieval-led-2026-11-12/README.md)已在修订方案 `73c2c09` 与冻结代码 `1feac42` 下完成：真实检索结果中的任务、代码哈希与行为类型驱动后续执行及映射，渲染器随后启动，十份原案例数据库持续保留至准入、状态写回和第二轮复用。已知 C2 开发案例 10/10，首轮晋升 4、结果记忆 9、第二轮沙箱执行 3；语义不当但标识有效的 S1 仍被接受。另保留首轮初始化失败（候选、渲染和模型均未运行）、逐例未执行账本、三组 API 内容变更控制及五种破坏控制。资源限制未触发；本地全库 651 通过、21 条件跳过，38 浏览器检查仍跳过。旧[回放记录及时间边界](../experiments/ch7/CHRONOLOGY-BOUNDARY.md)不改写。C1、比较计分、全新保留批次、P2 新模型判读、P3 答案质量、独立人工核验和正式 Mac 资格仍未完成。

[第 7 章两轮研究路径的开发资格](../experiments/ch7/2026-11-12/README.md)已按先行方案 `aed0795` 和观察器修正 `c4b384b`，在冻结代码 `3223a11` 上完整重跑十例，C2 回执导入后路径的回放资格 10/10。执行／渲染在准备阶段先行完成，之后的每例初始记忆检索没有驱动该前缀；[时间顺序边界](../experiments/ch7/CHRONOLOGY-BOUNDARY.md)据实披露。提议准入、晋升、唯一技能状态、结果写回及第二轮读取／复用已执行；事务写入失败全部回滚，撤销优先于旧记忆。语义不符但标识有效的反例仍被晋升并复用，作为能力边界保留。首轮观察器失败、两轮完整原始记录和全库回归的旧 .NET 路径失败均保留；最终本机 649 通过、20 条件跳过、38 浏览器未启用，三类归档拒用检查通过。这是独立测试宿主中的研究适配器，不是产品自动学习入口；第 7 章 C1/C2 保留批次、P2 新模型结果和正式 Mac 资格仍未完成。

研究记录分别索引到 [既有结果复核](../experiments/engineering/2026-11-09-research-audit/README.md) 与 [Mac 模型预检](../experiments/mac-preflight/2026-11-09-7b8b/README.md)。7B 首轮交换阈值停止保留，准入后两模型固定请求各 10/10；正式资格、确定性及 P2 主运行仍各自验收。

[P2-A JavaScript 移植与题意核验](../experiments/p2-a/javascript-port/2026-11-11/README.md)覆盖原静态 direct 类全部 425 个任务与 116,753 个用例身份。冻结执行 `fe6df91` 有 422 个任务全量一致，115,629 条用例一致。`HumanEval/132` 的 CPU 停止及后续 1,014 条定向验证分别归档。`Mbpp/255` 仍缺 109 条参考，`Mbpp/739` 的发布值差异和精确修正版均有记录。生成提示、两种验证提示和 Jint 的新调用路径统一使用顶层 `solve`，并声明 BigInt、字典条目、元组和精确十进制表示及逐条浮点容差。

[原 52 个阻断任务的逐项台账](../experiments/p2-a/javascript-port/2026-11-11/results/blocked-tasks.md)包含 46 个供作者核读的发布移植、4 个精确算术修正版及两个继续阻断任务。四个修正版的 1,048 条适用用例全部一致。题意核验保留定义域外用例、发布值冲突和缺失参考的原始身份。正式作者逐条审读、最终任务集、设备资格和模型预试仍需完成。

[P2-A 完整公共基准参考准备](../experiments/p2-a/reference-oracles/2026-11-10/README.md)于 11 月 11 日在 Mac 上完成两遍全部 542 个任务的固定预算尝试，记录 330,042 条输入／参考输出，5 个任务两遍均因输出、内存或 CPU 限制中断。原静态 direct 类 425 个任务中，373 个满足本轮机械准备条件，107,640 对输入／预期输出与题面分开保存；52 个仍被阻断。537 个两遍完整任务中，533 个可比较且记录相同，4 个输出不可比较而保留未知；一项原生断言因新命名空间缺少 `math` 导入失败，属于测试环境限制。首次尝试因 JSON 字典键排序改变输入顺序整批拒用，先单独推送修订再完整重跑，未合并有利片段或提高资源限额。完整原始尝试、失败、类型／比较规则及独立复算均保留；1,192 个既有文件和 10,613 项旧论文事实不变。没有模型调用、JavaScript 移植、任务集定稿、硬件资格或 P2 再生成完成声明。

[P3 完整配置政策比较](../experiments/p3-policy/2026-11-10/README.md)已完成全部 16 个配置，每个 10 段 LoCoMo 对话、1,986 题，共 31,776 次实际提示捕获。产品按文本／嵌入、返回上限 6／60、最新五条／响应并集顺序交叉比较；生产默认提供器未改。文本响应顺序使提示证据召回从 0.118183 变为 0.288890，嵌入上限 6 时从 0.247552 变为 0.259945；嵌入返回 60 条再取最新五条反而降到 0.040392，池至提示损失为 0.955835。扩大服务端窗口会把损失转移到客户端，不保证最终召回提高；本语料各配置没有新增组装损失。全部条件与损失拆分保留，不据测试语料自动部署赢家。

外部 native write/read 比较中，LangChain 自身减仅相关度评分的 recall@8 效应为 −0.313748，刷新政策为 −0.000706，D 为 0.313042 [0.236006, 0.396921]；Mem0 分别为 +0.259940、0、0.259940 [0.201427, 0.310905]。这是命名配置中的对话宏平均命中率，区别于产品提示中的证据比例。Mem0 阈值未改变候选掩码或前八条，且 `infer=False` 原生实体集合为空；不能据此推断所有维护政策无效。产品执行 `fd4fb30`、外部执行 `1c78bf9` 各绑定完整独立尝试，无拼接。原文档／问题向量重放不变，另为 735 个辅助实体输入做 12 次本地嵌入调用；政策执行无实时模型请求，聊天／答案／裁判模型调用均为零。float32 记录失败、实体分支降级造成的被拒尝试和修复前测试全部保留。974 个既有研究／运行时／配置文件与原 9,980 项论文事实不变，新事实独立命名。默认事实提取、更广维护政策、完整 Web／QQ、回答质量、P2 冻结再生成和第 7 章保留比较仍开放。

[新版 P3-E 完整语料回执](../experiments/p3-e/2026-11-10-shared-runtime/receipt.json)：按先行单独推送的方案，在 Mac 上以 `c6c48eb` 的实际二进制完成文本／嵌入各 10 段 LoCoMo 对话、1,986 题。主集合 1,540 个可回答问题，其中 1,536 个列有证据；实际完整提示召回为文本 0.118183 [0.089561, 0.144012]、嵌入 0.247552 [0.186023, 0.311994]，对话均值、95% 对话 bootstrap 区间。候选池至实际提示损失分别为 0.474979 和 0.748675；本语料没有新增组装损失，也没有截断或无法归属的记忆块。逐题证据计数与历史快照一致，不能外推为其他输入／配置的等价。

测量入口仅开启共享运行时的记忆模块，每题空历史、不回写问题，聊天模型由本地响应替身代替；不覆盖完整 Web／QQ、多轮、生活上下文或主动消息。实际嵌入为本地 nomic：2,081 次上游 HTTP 请求、7,868 个输入；NumPy 对全部 1,986 次服务器搜索的数值复算匹配，不额外调用模型。初次嵌入尝试的 915 题及 28 次 HTTP 500、记录器延迟清理缺陷与修复回归均保留，最终两条件全部重跑，不拼接尝试。完整捕获、压缩副本重算、缺行／重复／坏指纹拒用检查均通过。875 个既有源码、配置及实验文件未改；论文旧事实 9,878 项不变，新增 102 项 `p3e2.*` 事实。新版回执可单独进行当前配置审计，原 v1 指标的版本拒用继续保留。研究完成仅限这项固定配置测量，不表示 P2 再生成、完整政策比较、第 7 章或投稿批准完成。

历史阶段（完整语料复测前）：[期刊论文优先核对回执](../experiments/engineering/2026-11-10-journal-review/receipt.json)记录本轮来源更正与只读审计。作者确认四类定性材料均为 AI 辅助判读；原归档保留，更正清单绑定原始指纹。审计器能拒绝不匹配的指纹及把历史 P3-E 指标套到新源码。9,878 项事实和源表占位符不变，稿件新增第 12 类归属文字回归检查。运行时、配置和既有实验均未改；这里没有新增模型样本、独立人工验证或正式研究完成状态。

历史阶段（完整语料复测前）：[实际提示观察器资格回执](../experiments/engineering/2026-11-10-observed-prompt/receipt.json)继续补齐 P3 的测量装置：实际捕获请求中的完整记忆与预计条目分开记录，部分截断不计为完整条目，未捕获或来源有歧义时保留未知。七个合成 API／数据库场景通过，默认长文本夹具预计五条而完整出现两条；这不是语料召回率。v2 驱动要求显式选择旧直接入口或共享纯记忆入口，使用独立格式并拒绝覆盖输出；完整语料循环未执行，当前产品的召回仍未测。最新 UTC 单元／集成 575 通过、15 跳过、0 失败；定向 20 通过、1 项完整语料运行跳过。853 个既有源码、配置及实验文件未变，9,878 项事实和 P3 表格行一致。运行时未改，本轮未重跑浏览器或真实平台检查，前轮记录按版本保留。

[最新主动消息与提醒交付回执](../experiments/engineering/2026-11-10-proactive-delivery/receipt.json)：普通 QQ 回复、主动开口和到期提醒共用来源关联记录及同一发送器，网页区分来源类型并显示提醒触发 ID。类型从已存消息元数据读取。提醒文本已存与平台接受分别记录；同一聊天内已存提醒在恢复时复用来源，原尝试仍保留时不重发。生成失败释放认领，夜间／冷却／安静请求门控继续适用。其他平台保持文本发送回退，网页与机器人的提醒日程仍各自保存。

上一轮主动交付扩展的 Release 构建 0 警告、0 错误。UTC 单元／集成 567 通过、15 项按条件跳过、0 失败；定向 50/50 通过。完整配置浏览器 32 通过、6 项授权 MMD 环境项跳过，精简配置专项 11 通过、无跳过，均无失败。原始 TRX、修正前失败和编译记录列在新回执中。644 个起点已有的研究、既有工程证据、共同基础和声明测量文件逐字节不变；9,878 项论文事实一致。没有新增 .NET 项目、NuGet、表或后台服务，没有改变模型提示或配置，也没有新增真实 QQ／NapCat 账号联机或模型性能运行。记录是 relay 的授权观察，不是已读或独立研究证明；仍没有持久 outbox、入站去重或自动补发。

[上一轮交付观察回执](../experiments/engineering/2026-11-10-delivery-receipts/receipt.json)记录普通回复与共享运行时命令的首次接入：UTC 单元／集成 562 通过、15 跳过；完整浏览器 31 通过、6 跳过；精简配置 10 通过。新一轮在其基础上扩展主动消息和提醒，保留旧回执与原始产物。

[上一轮共同日记回执](../experiments/engineering/2026-11-10-shared-diary/receipt.json)记录服务器来源校验、跨端保存／读取／遗忘、冲突与隔离，以及时钟注入修复。修复前 GitHub Linux CI 的空白时区用例受到宿主环境影响；默认时钟注册改为不覆盖显式注入，UTC 全量单元／集成 544 通过、15 项按条件跳过。完整配置浏览器 30 通过、6 项授权 MMD 环境项跳过；精简配置专项 9 通过、无跳过，均无失败。跳过清单和原始失败按各自回执列出。552 个既有研究／共同基础与声明测量文件相对 `4af8d5b` 的基线逐字节不变。

上一轮共同日记工作还实际接通缓存本地模型检查，结果与受控替身测试分开：1.5B 两次只输出情绪标记，均未完成可见回复；增加可见文字指令也未使第二次通过。8B 冷加载超过普通 300 秒期限；另一次在独立预加载约 246 秒后完成两轮聊天与日记保存／读取／遗忘，上游请求约 33、26 秒。记录器先收全真实响应再转发 SSE，未测首字延迟。此次输出上限 256 token，不能作为正式模型资格、持续容量或主研究结果。全部失败、资源采样、输入和响应保留在上述目录。

发布时的 Linux 回归另见[跟进回执](../experiments/engineering/2026-11-10-shared-diary/ci-followup/receipt.json)：`caf405d` 的首次 CI 为 538 通过、1 失败、20 跳过；失败限于注入时钟夹具查找 `ROK` 别名。跟进夹具改用规范 ID `Asia/Seoul`，时钟对象身份、空白配置和 Web/QQ 一致性断言全部保留，UTC 下定向 3/3 通过。运行时代码未再改动，原失败和上一轮所有记录保留；新提交由 GitHub 再运行完整套件。

[上轮陪伴架构回执](../experiments/engineering/2026-11-10-life-architecture/receipt.json)：全量单元／集成 537 通过、14 项按条件跳过；完整配置浏览器 29 通过、6 项按条件跳过，精简配置专项 8 通过。新增边界专项 18 通过。30 个陪伴参考仓库均核对固定提交的 README 与 LICENSE，其中 6 个抽样阅读关键源码；另保留 3 个架构主参考，均未安装或导入其源码/素材。550 个既有研究／共同基础及声明测量文件与该轮基线 `54ba8a5` 逐字节一致。该轮模型、媒体和 QQ 出站使用受控替身。

共享运行时固定单轮模块选择，并采用 `bounded-context-v1` 产品长度策略、工具调用期限和结果未知时停止后续工具。此前的共同日记轮次补充可见文字回复指令，标记本身不能算完成回复；指令不保证模型服从，也不触发自动重试或编造兜底文字。原始存储文本不改；旧直接构造入口未显式选择新选项时保留原提示行为。产品提示策略已改变，冻结记忆文件未改不等于实验条件一致；新策略的研究评估尚未运行。可编辑架构源与 PNG/SVG 见 [ARCHITECTURE](ARCHITECTURE.md)，完整参考目录见 [COMPANION-REFERENCES](COMPANION-REFERENCES.md)。此前的[运行时重构回执](../experiments/engineering/2026-11-10-runtime-refactor/receipt.json)和[发布回归回执](../experiments/engineering/2026-11-10-github-validation/receipt.json)保留原记录。

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
  Aijade.Client        跨 Web/MAUI/机器人/MCP 的共享运行时：能力装配、媒体路由、回复流与工具预算
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
| 多会话聊天、流式输出 | ✓ | E2E `A_sign_up_chat_streams…`、`A_a_message_sent_while_the_server_cannot_be_reached_says_so_in_the_chat`（断网时在聊天里提示，不弹页面的通用错误条；联网后照常）、`C_a_finished_reply_is_not_called_unfinished_when_its_receipt_and_speech_cannot_reach_the_server`（回复已经完成，只是之后的渲染回执和朗读发不出去，不提示“这一轮没有完成”）；`Sse_parser…` |
| 角色卡与人设（默认艾娅德） | ✓ | E2E `A_a_character_card_drives_the_persona_and_greeting`、`Without_a_character_the_default_companion_is_aijade_9` |
| 共同日记：显式保存普通对话、网页／QQ 读取、网页遗忘 | ✓ | `CompanionDiaryTests`；E2E `A_saved_diary_exchange_can_be_read_on_signed_QQ_and_forgotten_on_the_Web_without_deleting_the_chat`；真实本地 8B 就绪后的两轮开发检查。保存摘录不验证所述活动真实性，遗忘不删除原聊天，非自动日记或历史版本归档 |
| 上下文管理（历史窗口、视觉 / 浏览器 / IDE 上下文） | ✓ | `Orchestrator_streams_stores_and_reports…` 及上下文测试 |
| 分层记忆：近期、摘要、长期（持久化、浏览、搜索、遗忘、导入导出、记录开关、语义检索） | ✓ | E2E `A_what_the_user_says_reaches_long_term_memory…`；`ProductServerTests`；`Memory_search_goes_by_meaning…`；`ContinuousLearningTests` |
| 情绪与表情驱动 | ✓ | `Expression_markers…`、`Dialogue_acts_and_expressions…`；E2E `D_an_mmd_model_loads_and_its_morphs_follow_the_reply` |
| 约好的提醒（聊天页与 QQ、Telegram 私聊；移植 MOSAIC，ADR-003 补充三） | ✓ | `RemindersTests`（MOSAIC 模块生成的 35 条向量、提醒簿、到点那句话、渠道上的完整流程；生成或发送超时只误一次检查，循环照常）；浏览器端到端 `A_a_reminder_asked_for_in_chat_is_set_in_local_time_and_kept_with_her_promise`（聊天页按浏览器的时区设定，与她答应的话一起存下）、`A_a_due_reminder_is_said_in_its_chat_even_after_a_minute_the_server_could_not_be_reached`（到点那句在聊天页说出；连不上服务端的那一分钟之后照常，每分钟的检查不停） |
| 自拍（时不时把舞台上的自拍发进聊天；移植 MOSAIC，ADR-003 补充六；设置默认关闭） | ✓ | `SelfiesTests`（MOSAIC 生成的规则与取景向量、存图与入聊天）；E2E `D_the_mmd_stage_takes_her_selfie_from_arms_length`、`D_the_built_in_avatar_stage_mounts_without_a_model` |

### 4.2 模型接入
| 项目 | 状态 | 证据 |
|---|---|---|
| 聊天（OpenAI 兼容）、嵌入 | ✓ | 网关路由与密钥轮换（`ProductServerTests`）；`MeaiAdapterTests` |
| 语音合成：OpenAI 兼容、ElevenLabs、阿里云 Qwen-TTS / CosyVoice | ✓ | 网关语音路由测试 |
| 本机语音合成、识别与逐字对齐（MOSAIC 在 Windows 上的回环服务，ADR-003 补充一、四） | ◐ | `LocalVoiceTests`（测试替身）；接真实服务的联机检查待作者在 Windows 上做 |
| 语音识别：流式（Web Speech）与整段（服务端转写） | ✓ | E2E `C_with_server_recognition_an_utterance_is_recorded_transcribed_and_sent` |
| 绘图：OpenAI 兼容、Replicate、ComfyUI、Gemini | ✓ | `Images_are_drawn_by_each_backend…`；E2E `B_with_drawing_switched_on…` |

### 4.3 语音交互与舞台
| 项目 | 状态 | 证据 |
|---|---|---|
| 麦克风选择、VAD 免提、按键说话、无法启动时提示 | ✓ | E2E 服务端识别测试；`C_voice_input_that_cannot_start_says_so_clearly` |
| 朗读回复（浏览器的自动播放规则、放不出的音频） | ✓ | E2E `C_a_reply_the_browser_will_not_let_be_heard_yet_leaves_the_chat_free…`（浏览器还不让发声时这句只显示，这一轮不等它；之后的点击或按键让后面的话照常朗读；无头浏览器从不拦声音，测试里按较严的规则模拟）、`C_speech_the_browser_cannot_play_leaves_the_text_reply_and_the_chat_going`（解不出的音频不让页面停住，文字回复照常） |
| 口型同步 | ✓ | 音频电平驱动头像与 MMD 口型形态键；有逐字对齐时按韵母分到あいうえお、b/p/m 闭唇（ADR-003 补充四）：`LipSyncTests`（与 MOSAIC 模块生成的向量逐帧相等），E2E `C_spoken_audio_carries_the_aligned_vowel_shape…`、`D_with_the_aligned_text_the_mmd_mouth…` |
| 镜头跟随（像屋里的观众，移植 MOSAIC 的 ViewerFollow，ADR-003 补充五；设置默认关闭） | ✓ | `ViewerFollowTests`（MOSAIC 类生成的 6 组向量）；E2E `D_with_camera_follow_the_view_keeps_her_in_frame…` |
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
| QQ（OneBot 11，经作者自装的 NapCat；只回负责人私聊，语音消息可转写，ADR-003 补充二） | ◐ | `OneBotConnectorTests`（签名、解析、经假 NapCat 的完整往返、语音转写、没有文字时的固定回复、某一步超时只误这一条）；未接真实 NapCat |
| Minecraft | ◐ | 纯 .NET 协议客户端，在本机官方服务端上实测：寻路、跟随、挖掘与拾取、放置、攻击、按配方书合成、自动穿戴更好的盔甲、挖掘前换上合适工具、游泳过水渠与爬梯上下墙（`MinecraftTests`，单元与 5 个服务端用例）；主机满载时“跟随”用例偶有超时 |
| 浏览器扩展、VS Code、Claude Code 插件、国际象棋 | ✓ | E2E `I_the_browser_extension_reads…`；`ChessTests`；node 测试 |
| 9 种语言 | ✓ | `Every_locale_has_every_key…` |

## 5. 实验与论文证据

论文编号自 2026-10-19 起统一为 P1、P2、P3（原 P4 改为 P3；中文稿不再单独编号，作为各篇的中文译稿附在同一文件夹）。本文件一律使用新编号；已归档的实验记录保留当时的写法（见 `experiments/README.md`）。

实验命令与产物目录见 `experiments/README.md`（含 2026-10-15 自评目标量定义更正的说明）。论文仓库（私有，korose523/AIJADE-papers）中的 `_工具/facts.py` 只读这些产物；稿件源用占位符引用其中的数字，由 `_工具/render.py` 渲染。

| 论文 | 证据目录 | 状态 |
|---|---|---|
| P1（附中文对照译稿） | `experiments/p1/`、`experiments/growth-pilot/` | 全部在本实现上运行完成，稿件已由稿件源生成 |
| P3（附中文译稿；10-19 前编号为 P4） | `experiments/memory/`、`experiments/memory-longmemeval/`、`experiments/p3-longmemeval/2026-11-11/` | LoCoMo 已有完整记录；LongMemEval 的历史 479 个标注题含 9 个官方拒答题，470 个可回答题口径须复算验收，不能沿用旧表冒作已完成。 |
| P2（附中文译稿） | `experiments/rq-c/` | 7B 主运行、惰性对照、模拟阳性对照、1.5B 与温度扫描、确定性预检及其重复、差分测试、第二模型族对照（llama3.1:8b，`rq-c/family-gpu/`；llava-phi3 的第一次尝试已放弃，见 `rq-c/family/ABANDONED.md`）已完成，稿件已由稿件源生成 |

## 6. 未完成与需作者处理的事项

1. **需要作者操作**：macOS / iOS 构建（Xcode）；利益冲突、致谢及正式投稿批准，以及投稿信中的期刊、日期与预印本等占位。作者已确认主导全部项目和论文、没有资助；这些事实不再重复列为缺失。单位与导师的作者贡献角色沿用 10-27 的记录。
2. **未能在本机完整验证**：Windows 桌面与计算机控制、各聊天平台与 B 站的真实联网、阿里云与 Google 的真实接口。
3. **检索打分（研究内核，已定性）**：冲突惩罚按冲突对累乘、总是压低较旧的一方（标准化模式下扫描前 150 个候选，关闭后交付召回大幅上升），加和模式的扫描窗口随 K 变化。这些都是 P3 测量与复现的对象，按设计保留并已在代码中注明；它们只存在于研究用记忆内核（`BioticMemory`），服务端记忆库不使用该内核。绝对的检索下限（0.02）由评测施加，`Retrieve()` 本身不用它。冲突判定对真实矛盾的精确度未评估，是否修改惩罚需先做这项评估。

## 7. 进度总览（2026-11-05）

开发过程中的逐日记录见版本历史；下表只列最终状态。

**2026-10-22 导师第一次审阅之后。** 三篇论文暂缓投稿，先使主张与证据吻合；作者改为翁泽潇与郑玟圃（通讯作者）。按审阅意见能做的文书修改已在论文仓库完成。代码方面：RQ-C 运行器把代码提交号写进每次运行的 `summary.json`（可用 `AIJADE_GIT_COMMIT` 指定，远程主机上的副本也一样；找不到时给出警告，`ca0d860`）；数据集许可说明补全（LoCoMo、LongMemEval_s 的哈希与许可）；修复记忆检索可能返回本轮自身发言的问题（`819d944`）。新的运行（P1 替代设计比较与另行构造的缺陷集、P2 扩大候选与更大模型、P3 其他记忆系统与嵌入相似度）按导师排期在 12 月 1 日之后、与导师商定后再做；付费 API 先与导师商定费用。只用已有数据、不调用模型的三项分析（P3 只用可回答问题的重算与按证据计的召回、门控与打分方式的交互、P2 环境反馈对验证器错误率的影响与逐轮稳定性）现在执行：方案先于实现与执行提交在 `experiments/plans/2026-10-22-followup-analyses.md`（未在外部平台注册），结果文件记录代码提交号。

| 项 | 状态 |
|---|---|
| 审阅后的追加分析（不调用模型） | ✓ 方案提交于 `aee0429`，代码提交于 `761165d`，结果由该提交在干净工作区生成：`experiments/memory/answerable-reanalysis.json`（全部问题上的数值与已归档文件逐项一致，42/42）、`experiments/rq-c/verifier-feedback.json`（输入哈希与方案一致）。P3：排除对抗问题后各项对比方向不变；门控与打分方式的交互在可回答问题上，加和对标准化的区间含零，关闭惩罚对标准化的区间不含零但符号翻转检验 p = 0.070。P2：反馈对两种错误率的影响均未检出；逐轮趋势检验对可用技能“检出”，但第 0 轮之后每轮只有 1–2 个任务，同任务内的比较（探索性）显示这是任务构成而非验证器漂移 |
| P2-A 第 0 阶段：公开代码基准的静态兼容性筛查（不生成，不执行数据集代码） | ✓ 10-25，代码 `629187a`，结果 `experiments/p2-a/evalplus-compatibility.json`。按现有 RQ-C 判定（精确结构相等，无 BigInt、Set、元组，对象键为字符串）与 EvalPlus 评测器的特例（浮点输出强制 1e-6 容差、按集合比较、专用判定），把 HumanEval+ 164 题分为可直接移植 117、需注意 24、需改判定 8、不兼容 15；MBPP+ 378 题分为 308、10、34、26。不兼容主要是超过 2^53 的整数（15 与 18 题）。这是筛查，不是移植：期望输出须运行规范解才能得到，任务来源与是否加容差、按集合比较的判定，12 月与导师商定 |
| P2 未通过测试的候选与任务说明的比对（不调用模型） | ✓ 11-04。结果都已知之后才做的探索性重新统计，事先没有方案，不算修正：沙箱、评测台和运行都不变，运行本身的标签仍是报告的估计。`experiments/rq-c/oracle_audit.py` 用原标签逐位复现 `p2-models.json` 的区间，回放与五次运行的记录标签全部一致。主运行 13 个不可用程序中 3 个不是行为错误（`const` 绑定、未命名为 `solve` 的 1 个；说明不决定的测试用例使之失败的 2 个），59 次误放中占 20 次；重新评分后误放率 39/115 = 0.339，误拒率 82/756 = 0.108，反馈效应的不一致配对从 20:1 变为 8:1。结果 `experiments/rq-c/oracle-audit.json` |
| P2 第二主机的完整性审计（不调用模型） | ✓ 10-25。作者确认，第二模型族与提示模板 A、B 三组运行所用的显卡主机，就是另一项目因 CPU 错误记录而排除的那台。三组运行中运行器、沙箱、执行判定与分析都在主主机上，第二主机只提供模型输出。方案先于实现提交（`8b45434`），代码 `c5dfe26`，结果 `experiments/rq-c/host-audit.json`。检查结果：四组运行共 6,242 次现场生成与 3,243 条验证器回复中，无损坏字符、无空代码、无不可解析代码；验证器回复格式不符只见于 llama3.1:8b（3/770，模型行为，按规则记为 FAIL）；两份 GPU 运行日志无错误行；确定性预检在固定种子下均通过；同一 7B 模型与模板在两台主机上，各项比例的区间相互重叠。按方案读作"未见严重损坏的迹象"；不改变文本格式的变化，只有在另一台主机上重跑才能排除 |
| P3 打分结构的源码读取（不安装、不运行） | ✓ 11-05。结果都已知之后做的探索性读取，事先没有方案，一位读者：21 个开源记忆系统在固定提交上的排序方式，`experiments/memory/scorer-survey.json`。只说明各系统如何组合信号，不说明对召回的影响 |
| P2 验证器回复的判读（不调用模型） | ✓ 11-05。同样是结果之后、事先没有方案、一位读者：主运行的接受大多只有 PASS，拒绝理由逐段程序对照代码、任务说明与重放结果编码，`experiments/rq-c/verifier_reasons.py`、`verifier-reasons.json` |
| 范围治理：研究线为主，非研究线只维护 | ✓ 10-26。参照 MOSAIC 的 ADR-017 新增 `docs/PROJECT-SCOPE.md`、`docs/decisions/ADR-001.md` 与 `configs/project-scope.json`：模块分为研究线、共同基础、非研究线与测试，第 4–6 章的研究对象路径单独列出。`ProjectScopeTests` 检查三件事：每个模块已声明归属；研究线与共同基础不引用非研究线；共同基础不引用研究线。现有引用无越线，无需改代码。阳性对照中，故意改错的归属与漏掉的声明都被检出 |
| 导师 10-27 意见 | ✓ 第二主机审计 A5 所用的两份运行日志（`experiments/rq-c/run-family-gpu.log`、`run-template.log`）纳入版本库，他人可复核 A5；P3 表 1–9 改用 1,540 个可回答问题重算的方案提交于 `experiments/plans/2026-10-27-p3-answerable-tables.md`（不调用模型，12 月 2 日后计算）；`experiments/README.md` 删去“提交历史就是方案的时间戳”，改为只陈述提交顺序（不说明方案何时公开），并说明 10 月 22 日以前的运行脚本与记录、各 RQ-C `summary.json` 的 `preregistrationDeviation` 字段所称的 "pre-registered"，指运行前在代码中固定的协议（`Harness.cs` 的 `Preregistration`），未在外部平台注册；记录保持原样，类名与字段名不改以便与归档摘要对照，活代码中的注释已改 |
| 范围与开发顺序（导师 10-27 意见） | ✓ 10-28。`docs/PROJECT-SCOPE.md` 的开发顺序改为导师同意的顺序（设备资格与再生成在先）；第 6 章产品传递路径（P3-E 的测量对象）`src/Aijade.Client/Chat/MemoryContext.cs` 与 `src/Aijade.Server/Memory/MemoryLibrary.cs` 列入 `researchObjects`，在 P3-E 运行并归档之前不改。`ProjectScopeTests` 通过。10-31：这两个文件的内容哈希记入 `configs/project-scope.json` 的 `frozen`，`ProjectScopeTests` 检查（阳性对照：在副本中给 `MemoryContext.cs` 加一行即失败，只改换行符不失败） |
| 与 MOSAIC 非研究线共享伴侣契约（ADR-002） | ✓ 10-28，作者指示的例外。`configs/companion/contract.json` 1.0.0：艾娅德的人设（两边同一段文字；默认人设随之更新）、AIJADE 9 个舞台表情对 MOSAIC 4 个情绪的名称对应、主动开口规则（闸门、权重、阈值）。主动开口的参考实现 `src/Aijade.Client/Companion/Initiative.cs` 在 MOSAIC 实现生成的 18 条向量上判定全部相同（阳性对照：阈值改为 0.76 时两项测试失败）。同日契约升为 1.1.0，主动开口接入聊天：`ChatOrchestrator.SpeakFirstAsync` 与聊天页每分钟一次的询问，设置"安静时她会先开口"默认关闭；说明与沉默消息与 MOSAIC 逐字一致（4 条向量），生成时不经记忆召回与学习观察者。契约 1.2.0：MOSAIC 在 QQ 上测过的文字渠道规则（没有身体时的两条说明与推迟动作的补句）由 `CompanionBridge` 在 Discord、Telegram、X 与 Satori 转接的平台上采用，与 MOSAIC 的常量逐字一致；聊天平台配置见 `docs/COMPANION.md`。用 MOSAIC 的家作舞台的对照与方案见 `docs/STAGE-MOSAIC.md`（建议经 MOSAIC 工作台的文字指令，不动渲染器契约）；作者选方案 A，第 1 步已完成：契约 1.3.0 的"舞台"一节与判定实现 `src/Aijade.Client/Companion/Stage.cs`，在 MOSAIC 代码生成的 45 句向量上全部一致，尚未接入界面；MOSAIC 已在 r392 采用 1.3.0（状态接口返回她在哪与姿势，跳舞可不带名字），本仓库在 r392 上重新生成向量，内容相同。第 2 步（作者选服务端转发）：服务端 `/api/v1/stage` 只限管理员、只转发到本机回环地址上的工作台、只放行七种指令；聊天页设置"舞台：MOSAIC 的家"默认关闭；用测试替身验证，尚未与运行中的工作台联机（ADR-002 补充四）。契约 1.4.0（10-29，MOSAIC 提议，作者接受 A、B）：她可以提到 MOSAIC 的 B 站学动作器真学到的动作，转发只留契约字段、至多 5 条，说明里不写第三方的视频标题与 UP 主（ADR-002 补充五）；MOSAIC r418 实现，r425 采用（开关默认打开）。MOSAIC 已在 r389 采用契约 1.2.0（人设逐字相同，向量回归一致）。10-31 只读核对 MOSAIC r529：与契约有关的三份源文件改过（`companion.py` r418、`LiveSceneCommands.cs` r478、`home-v1.json` r470），但人设、学到动作的规则原文与工作台接口不变，重新生成的向量内容相同，只更新了源文件哈希与读取日期。MOSAIC 只读，其一侧的采用写在 `docs/COMPANION-CONTRACT.md` 的交接一节。不触及研究对象，不进入研究 |
| 舞台转发联机检查（ADR-002 补充四、五） | ✓ 11-06，在 Mac 上用 MOSAIC 工作台与家的复制件做（代码 `c29bf8e`）：有无动作库两条分支各 17 步全部符合预期。缺口：转发的 200 只表示指令被接受，动作中止时 AIJADE 不知道（未修改）。真实聊天回合、`learned` 不为空、声音和 Windows 未查。见 [STAGE-MOSAIC](STAGE-MOSAIC.md) 第五节末尾 |
| 舞台动作结果（ADR-002 补充六，契约 1.4.1） | ✓ 11-06，补联机检查发现的缺口：转发多给 `sequenceRunning`、`notice`，聊天页跟到指令执行完并判定；没做成时页面显示工作台原话，下一轮告诉模型哪个动作没发生（原话不交给模型）。工作台副本上两条分支各 10 行全部符合预期，含舞蹈库挪开时的真实中止。真实聊天回合未跑；判定依赖 MOSAIC 提示的措辞（r683）。不进入研究 |
| 迁移 MOSAIC 的非研究线功能，第一批（ADR-003） | ✓ 11-03，作者 11-02 的要求与选定。本机语音合成与识别、QQ（OneBot 11）、约好的提醒、逐字对齐的口型：做法、与 MOSAIC 的差异与验证见 `docs/decisions/ADR-003.md` 补充一至四，整合蓝图 `docs/INTEGRATION-MOSAIC.md` 一同提交。提醒与口型各用 MOSAIC 自己的模块生成的向量核对（35 条、10 组，全部一致）；本机服务与 NapCat 用测试替身验证，接真实服务的联机检查由作者在 Windows 上做。只改非研究线，不新增数据库迁移，不下载模型。同时按 MOSAIC r580、r601、r612 更新三份契约向量记录的源文件哈希（重新生成的内容相同） |
| 迁移第二批（ADR-003） | ✓ 11-03 作者确认两项开工。相机跟随（补充五，提交 `fea6d74`）与自拍（补充六，作者选定只在应用里，不发到渠道）都已实现：MOSAIC 代码生成的向量逐条一致，浏览器端到端在作者本机的模型上通过 |
| Mac 上提前运行（作者 11-05 决定，导师未审方案） | ✓ 11-05，全部本地提交，未推送。P3 可回答问题表（复现 751/751）；P3-D 嵌入；P3-C：LangChain、LlamaIndex、Mem0（CrewAI 在本机装不上）；P1-A 输入缺陷矩阵，以及代码缺陷与 11 个消费者测试（增补，11-06 完成；含义改变的 5 个缺陷：1/1/5/0）；P1-B 存活变异体判读（一位读者）；P1-B Stryker.NET：漂移 0.487 / 已执行 0.712，闸门 0.119 / 已执行 0.266；P3-E：提示词召回 文本 0.118、嵌入 0.248；P2-A 第 1 阶段数据核对。 |
| P1-C 外部渲染器（作者 11-06 决定在 Mac 上运行，导师未审方案） | ✓ 11-06，本地提交，未推送。方案 `d27fca4`，代码 `86f5818`，运行 `6ca1618`，结果 `678fc48`。研究对象目录 `src/Aijade.Integrations/Renderer` 只新增 `RenderEvidence.cs`，现有文件未改；第 4 章回归在 `678fc48` 上重跑：461 通过、14 跳过、0 失败，端到端 29/29（跳过的是要外部环境的可选测试）。客户端取得资格；回执主题漂移 26/26、篡改 6/6、封存与导入 17/17（三轮相同）。第一轮作废（强杀未生效），列为偏离。主要在测服务器，检查和预期结果出自一人。 |
| 新的运行 | ⏸ 需要合格设备的部分：设备资格与第二主机三次运行再生成 → P2-A 主运行与 P2-B → 第 7 章；每项方案单独推送并发给导师。 |

最终状态：

| 项 | 状态 |
|---|---|
| 服务端、Web、Android、集成、研究装置 | ✓ 完成（缺口见 §6） |
| Windows 计算机控制元素编号 | ✓ 已实现（UI Automation），单元测试通过；需在 Windows 上实测 |
| Minecraft | ✓ 寻路、跟随、挖掘拾取、放置、攻击、合成、换装备与工具、游泳攀爬均在本机官方服务端实测（42/42） |
| 安全补丁 | ✓ ASP.NET Core / .NET 升级到 10.0.14（SDK 10.0.403，10-29），修复 CVE-2026-111497（Brotli 解码越界写，经请求解压与 HttpClient 可达），并重发 10.0.13 未修完的 CVE-2026-70197（SocketAsyncEventArgs）与 CVE-2026-102870（Blazor WebAssembly Server/DevServer 包）；此前 10.0.13（SDK 10.0.402）修复 CVE-2026-96230 等。两次都经作者同意，作为“满两周”约束的安全例外；SDK 安装包按发布元数据的 SHA-512 核对 |
| 全量回归 | ✓ 当时的本地全量（11-04，这次提交的工作树，在内置盘副本中完全重新编译；外置盘是经 macFUSE 挂载的 NTFS，在上面构建会卡住）：解决方案构建 0 警告；单元与集成 447 项中 440 通过、0 失败、7 跳过（真实 Minecraft 服务端 5 项、完整预注册回放 1 项、MOSAIC 真实渲染器 1 项；数据库用本机 PostgreSQL）；浏览器端到端 29/29 通过，含作者本机 PMX 模型上的 MMD 舞台用例。同日早先两次全量里一条提醒用例失败，查明是副本的增量构建留下了旧二进制（做过“去掉修复就失败”的检查后，`rsync -a` 恢复的文件时间较旧，不触发重新编译），不是产品问题：同一份源码完全重新编译后通过；此后本地回归按内容同步、用 `--no-incremental` 构建。`D_an_idle_vmd_motion_loops_and_moves_the_model` 在一次只跑舞台用例时未检测到动作播放，单独重跑与全量都通过，按满载下的偶发记录。启动子进程的测试要用 .NET 10 的 `dotnet`：系统默认的 6/7 会使 `ComputerUseTests` 的一项失败。MOSAIC 真实解析器一致性测试最近一次在 10-31 用 MOSAIC 当日的构建通过（只读加载其 `Mosaic.Scene.Core.dll` 的临时副本）。GitHub CI（含 PostgreSQL 与 VectorChord）在 `f9dd421` 之后的各次提交上都通过，最近一次为 `9586074` |
| P1 | ✓ 端到端用例、漂移矩阵与闸门矩阵、两组变异实验（在当前代码上重跑与存档逐项一致）、时延与校验开销、身份层阳性对照与机制级试点；时延测于 .NET 10.0.12 |
| P2 | ✓ 7B 主运行、惰性对照、模拟阳性对照、1.5B 与温度扫描、确定性预检、差分测试；自评目标量定义于 10-15 更正（见 `experiments/README.md`）；第二模型族对照（llama3.1:8b，Windows 显卡主机；llava-phi3 的第一次尝试因不遵守判定格式按事先规则放弃，记录保留）；提示模板对照（模板 B 下验证器放行全部技能） |
| P3 | 已有打分、权重、交付、门控、指标、泄漏和 LoCoMo 对话聚类结果；LongMemEval 旧 479 标注题口径发现混入拒答题，保留历史结果，470 题复算及第二语料完整产品文本路径待执行/验收，详见新归档。旧召回数不改写为新口径结论；门控不主张普遍有效。 |
| 研究装置 | ✓ RQ-C 运行器可恢复（丢弃半行、只重放共有步骤、逐步落盘），可选单次回复 token 上限、`--num-ctx`、`--verify-template`；`format-precheck` 格式预检；记忆实验的 `pool-check`、`delivery-check`、`gating-check`、`component-scales`。11-03 在 `b6296a1` 上把归档的 RQ-C 模拟运行（30 个 trial、种子 42、`--save-candidates`）重跑到临时目录（不入库，不调用模型）：`candidates.jsonl` 与 `experiments/rq-c/rq-c-s42-mock-t30-r5` 的逐字节相同；`trials.jsonl` 的 7,200 条记录除计时 `durationMs` 与后来加入的 `codeHash` 外相同；`summary.json` 只差提交号、退化说明与 10-15 更正后的诊断命名 |
| 公开仓库 | ✓ https://github.com/korose523/AIJADE（10-18 以本实现完整覆盖，旧历史不保留；推送前检查无密钥、无第三方数据集与模型）；语料用 `tools/data/fetch-corpora.sh` 下载并校验 |
| 论文仓库 | ✓ 私有仓库 https://github.com/korose523/AIJADE-papers：三篇英文投稿件、中文阅读译稿、稿件源与构建工具；论文中的代码地址与提交号由构建工具从本仓库读取 |
| 论文编号 | ✓ 10-19 统一为 P1/P2/P3（原 P4 改为 P3，中文稿不再单独编号）；本仓库的注释与文档同步改写，实验目录、命令名与已归档的运行记录不变 |

## 陪伴配置与验证

[统一使用说明](COMPANION.md)维护角色与地点时区、Web/QQ 绑定、关系与收藏、照片与音频、随时配置的本地服务。资料按新回合生效；跨账号绑定不合并历史与私人记忆。角色未设时区时的机器人配置回退已覆盖白天及安静时段。

实际 QQ/NapCat 到达、专属音色训练及长期陪伴效用按各自条件验收。工程测试与开发容量预检不填充论文主结果；原始失败、输入和回执保存在 `experiments/`。
