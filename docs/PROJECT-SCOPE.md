# 当前项目范围与开发顺序

2026-10-26：项目以学位论文研究线为主，非研究线独立维护、只保留既有可用功能。依据是作者"根据计划书将非研究线向 MOSAIC 项目看齐"的要求，以及学位论文计划书 v0（作者 10 月 25 日暂定的选题与问题，待导师确认）。决定见 [ADR-001](decisions/ADR-001.md)，模块归属见 [机器可读范围](../configs/project-scope.json)。

本文件只治理范围与优先级。研究结论是否成立，由 `experiments/` 下的产物及事先提交的方案判定，不由本文件、配置或测试数量判定。

## 主线：学位论文研究线

**问题。** 长期运行的 AI 伴侣自己学习、自己评判自己生成的技能、自己挑选记忆来用时，这些内部判断错得有多严重，应当用什么外部证据来核实？

| 章 | 内部判断与外部证据 | 研究对象（代码位置） | 装置与驱动 | 产物 |
|---|---|---|---|---|
| 4 学习晋升 | 学习提议能否晋升；对照真实渲染回执 | `src/Aijade.Server/V9`（信封边界、渲染身份链、晋升闸门）、`src/Aijade.Memory/V9` 与 `Contracts`、`src/Aijade.Integrations/Renderer`（外部渲染器） | `tools/Aijade.P1`、`tools/Aijade.Mutation`；`ContractDriftMatrixTests`、`PromotionGateMatrixTests`、`P1EndToEndTests` | `experiments/p1/` |
| 5 技能自评 | 新技能是否可用；对照确定性执行判定 | `src/Aijade.Research/SkillBench`、`RqC` | `tools/Aijade.Rqc`、`tools/Aijade.Substrate`、`aijade-experiments` | `experiments/rq-c/`、`experiments/p2-a/` |
| 6 记忆检索 | 记忆是否相关；对照语料的金标证据话轮 | `src/Aijade.Memory/BioticMemory*`（研究用内核，产品服务端不使用）；产品的实际传递路径（P3-E）：客户端 `src/Aijade.Client/Chat/MemoryContext.cs` 与服务端 `src/Aijade.Server/Memory/MemoryLibrary.cs` | `src/Aijade.Research/MemoryEval`、`aijade-experiments` | `experiments/memory/`、`experiments/memory-longmemeval/` |
| 7 综合 | 三层判断对照外部证据；最小两轮整合检验（资格确认批次 + 保留批次上 C1 与 C2 的比较） | 计划中（方案草稿在论文仓库，2 月动工前单独推送） | 计划中 | — |

**开发顺序**（导师 2026-10-27 同意；12 月 1 日之后执行）：
1. 设备资格与第二主机三次运行的再生成、逐步对照（第 5 章）；
2. P2-A：移植（先查 MultiPL-E）、难度预实验、精度设计（第 5 章）；
3. P2-A 主运行与 P2-B（第 5 章）；
4. P3 表 1–9 重算、产品传递路径 P3-E、外部记忆系统 P3-C（第 6 章）；
5. P1-A、P1-B 与外部渲染器比较（第 4 章）；
6. 第 7 章的整合检验（WP01、WP03 2 月先行）。

每项的方案在执行前提交到 `experiments/plans/`：单独推送，并把方案 PDF 发给导师之后再写代码。

**研究线规则。**
1. 方案先于执行提交；结果文件记录方案与代码的提交号；偏离逐条列出。
2. 改动研究对象路径（`configs/project-scope.json` 中的 `researchObjects`）时，须重跑对应章的回归并在 `docs/STATUS.md` 记录：
   - 第 4 章：契约漂移矩阵、闸门矩阵、端到端用例；
   - 第 6 章：与已归档结果逐项一致的检验；产品传递路径（P3-E 的测量对象）在 P3-E 运行并归档之前不改，必须改时记入 `docs/STATUS.md`，并在 P3-E 的结果中列为偏离。这两个文件（`MemoryContext.cs`、`MemoryLibrary.cs`）的内容哈希记在 `configs/project-scope.json` 的 `frozen` 中，由 `ProjectScopeTests` 检查：非研究线的改动不会在不知不觉中改到它们；必须改时，先按上面记录，再更新哈希。

   作为测量对象按设计保留的行为（如研究内核的冲突惩罚）不修改。
3. 研究装置只依赖研究线与共同基础，不引用非研究线模块。由 `ProjectScopeTests` 检查。
4. 研究运行不接入真实用户数据，也不启用产品的自动聊天、语音、移动端与机器人等并发驱动。
5. 新的主运行在显卡主机上进行之前，先通过主机资格检查。该主机的 CPU 有错误记录，见 `experiments/rq-c/host-audit.json`。

## 非研究线：独立维护，只保留可用功能

非研究线是伴侣产品及其扩展。它们保持现有命令、接口、数据格式与测试，在学位论文期间只做维护，不扩张。

| 线 | 模块 | 现状（见 `docs/STATUS.md` 第 4 节） |
|---|---|---|
| 伴侣产品：聊天、记忆库、角色、设置、账户与计费、管理后台、Web 与 PWA | `src/Aijade.Server`（除 `V9`）、`Aijade.Client`、`Aijade.UI`、`Aijade.Web` | 已实现并有测试 |
| 语音与舞台：识别与合成网关、口型、MMD 舞台、陪伴行为 | 同上，`tools/mmd-bundle` | 已实现并有测试 |
| 多端 | `src/Aijade.Maui` | Android 已实测；Windows 未在本机验证；macOS/iOS 未实现 |
| 集成：MCP 与工具中枢、聊天平台、Minecraft、计算机控制、浏览器扩展、VS Code、Claude Code | `src/Aijade.Integrations`（除 `Renderer`）、`Aijade.Bots`、`Aijade.ComputerUse`、`integrations/*`、`tools/minecraft` | 已实现；部分未在真实平台验证 |
| 品牌素材 | `brand` | — |

**非研究线规则**（对齐 MOSAIC ADR-017 的扩展线规则）：
1. **只做维护**：修复缺陷、安全补丁与依赖更新。学位论文期间不新增功能、平台或集成，不重写前端，不更换渲染器。作者另有明确指示的，作为例外记入新的 ADR。现有例外：[ADR-002](decisions/ADR-002.md)，与 MOSAIC 非研究线共享伴侣契约（人设、表情名称、主动开口规则；[COMPANION-CONTRACT](COMPANION-CONTRACT.md)）。
2. **不进入研究**：非研究线不作为研究的输入、样本、奖励或判定条件，研究结论不依赖它们的运行状态。
3. **不算研究进度**：工程验证（单元与端到端测试、平台实测）不换算为研究进度或论文完成率。
4. **不改研究对象**：非研究线的改动不触及研究对象路径；必须触及时，按研究线规则重跑回归。
5. **退役程序**：退役某一功能先写 ADR，并在移除前存好恢复档案（参照 MOSAIC ADR-019）。
6. **用户数据**：真实用户的对话与评估不进入研究。若要在研究中使用，先走机构审查（导师 10 月 24 日意见 1.1 节）。

## 与 MOSAIC 的关系

- MOSAIC 的连接组研究不进入学位论文。
- MOSAIC 的原生 Godot 客户端实现了本仓库的外部渲染器契约（[MOSAIC-RENDERER](MOSAIC-RENDERER.md)），在第 4 章作为外部比较对象。本仓库不修改 MOSAIC。
- 两个项目的伴侣（非研究线）共用一份契约：艾娅德的人设、表情名称的对应与主动开口规则（[ADR-002](decisions/ADR-002.md)、[COMPANION-CONTRACT](COMPANION-CONTRACT.md)）。只在非研究线，不触及研究对象，不做运行时耦合。
- 本文件的组织方式参照 MOSAIC 的 `docs/PROJECT-SCOPE.md` 与 ADR-017：研究优先、扩展隔离、静态检查模块归属。两个项目的研究问题互不依赖。

## 文档与架构治理

- **当前范围**：本文件、[ADR-001](decisions/ADR-001.md)、[`configs/project-scope.json`](../configs/project-scope.json)。功能状态与进度见 [`docs/STATUS.md`](STATUS.md)；实验与驱动程序见 [`experiments/README.md`](../experiments/README.md)。
- **静态检查**：`tests/Aijade.Tests/ProjectScopeTests` 检查三件事：
  - `src/`、`tools/`、`tests/`、`integrations/` 下每个模块都声明了归属；
  - 声明的路径与研究对象都存在；
  - 项目引用不越线：研究线与共同基础不引用非研究线，共同基础不引用研究线。

  这是静态检查，看不到运行时的 HTTP 与文件调用，也不代表任何研究通过。
