# PROVENANCE — 来源与衍生关系声明

**文件版本**：v1.0
**最后更新**：2026-09-15
**状态**：🟡 待作者核实 2 项（见 §6 #1、#2；#3 已于 2026-09-15 澄清）

本文件声明 AIJADE 代码库的来源、衍生关系与许可义务履行情况。它是**学术溯源披露**的一部分：
AIJADE 的论文贡献建立在"在既有开源平台之上实现并评估一套仿生记忆与技能成长机制"这一主张之上，
因此衍生关系必须可核查，否则"原始贡献"的边界无法被审稿人确认。

---

## 1. 上游项目识别

| 项 | 值 |
|---|---|
| 上游项目名 | **Project AIRI** |
| 上游仓库 | `https://github.com/moeru-ai/airi` |
| 上游维护方 | Moeru AI / Neko Ayaka |
| 上游许可证 | **MIT** |
| 上游版权声明（逐字） | `Copyright (c) 2024-PRESENT Neko Ayaka` |
| 本仓库角色 | **衍生作品（derivative work）**，非独立原创项目 |

上游 MIT 许可证正文已逐字保留在本仓库根目录 `LICENSE` 中。

---

## 2. 衍生关系的性质

本仓库在上游代码基线上做了三类改动，分别对应不同的溯源义务：

| 类别 | 内容 | 规模 | 溯源义务 |
|---|---|---|---|
| **A. 继承（未修改或仅改名）** | `stage-*`、`ui*`、`core-*`、`audio*`、`pipelines-*`、`server-*`、`plugin-*`、`model-driver-*`、`services/*`、`engines/*`、`apps/*` 等绝大多数包 | 绝大多数代码行 | 保留上游 MIT 版权声明；标注来源 |
| **B. 重命名 / 重新品牌化** | npm scope `@proj-airi/*` → `@proj-aijade/*`；插件目录 `airi-plugin-*` → `aijade-plugin-*`；仓库链接指向 `github.com/korose523/AIJADE`；i18n 中的上游标识替换为 AIJADE | 全仓 | 同上 + 须在 README/溯源文件说明"改名不改变来源" |
| **C. AIJADE 原创新增** | 见 §3 | 研究内核 | 声明为作者原创贡献，构成论文贡献主体 |

> ⚠️ **重要**：类别 B 只改名不改来源。仓库中出现 `AIJADE Team` 作为 `author` 字段，
> **不代表**上游包由 AIJADE 原创。审稿人若据此判断"自研平台"，将构成事实性误导。
> 本文件即为消除该歧义而存在。

---

## 3. AIJADE 原创新增（论文贡献主体）

以下包为 AIJADE 作者原创或实质性改造，是论文中"我们的方法"所指向的实现：

| 包 | 角色 |
|---|---|
| `packages/memory-biomimetic` | 仿生记忆内核：DGM 双图记忆、HAC 稳态预测式巩固、CDI 受约束身份演化、AEL/DIVE/VSE/PEF 组件 |
| `packages/research-harness` | RQ-C 可信度测量实验装置：2×2 析因设计、区组化任务分配、退化守卫、统计管线（BCa / block bootstrap / Holm / DiD） |
| `packages/research-telemetry` | 实验遥测采集 |
| `packages/skill-bench-env` | 可执行技能基准环境与沙箱 oracle（无泄漏验证） |
| `packages/skill-forge-store` | 技能库持久化与学习闭环单元（LearningLoopCell） |
| `packages/agent-skill-forge` | 技能锻造：候选生成 → 自评 → 环境反馈 → 剪枝 |
| `packages/agent-capabilities` | 人格演化与技能锻造的编排入口 |
| `packages/agent-continuous-learning` | 持续学习循环 |
| `packages/growth-services` | 成长服务层 |
| `packages/model-substrate` | 模型基底抽象 |
| `experiments/` | 实验结果产物（含预注册配置） |

**边界声明的诚实性要求**：论文中凡描述上述机制的段落可主张为本研究贡献；
凡描述舞台渲染、Live2D/VRM 驱动、TTS 管线、聊天前端等，**必须**明确归因于上游 Project AIRI，
不得作为本研究贡献呈现。

### 3.1 品牌与角色图像素材（2026-09-15 起）

项目的品牌/角色图像素材（应用图标、favicon、open-graph 卡片、启动图、
macOS 托盘与分层图标、Android/iOS 图标族）属于**本项目自有素材**，不是第三方素材，
故登记于此而非 `THIRD-PARTY-NOTICES.md`。

| 项 | 内容 |
|---|---|
| 角色 | 沫璃 / Meryl —— 银白双马尾、白色蕾丝女仆头饰、蓝眼、黑白女仆装（与 `docs/07_开发笔记/角色卡_女仆酱配置.md` 一致） |
| 形象来源 | 项目方提供的看板娘立绘与三视图设定稿 |
| 生成方式 | 以上述参考稿为输入、经 AI 图像生成（图生图）产出，再由 `brand/meryl/build-assets.py` 派生全部尺寸与格式 |
| 上游关系 | **零继承**。本次替换移除了所有上游吉祥物素材；此前 `apple-touch-icon.png` 内嵌的 "AIRI" 字样与 open-graph 卡片上的 "Project AIRI" 文案一并清除 |

**复现方式具备两个性质**，与 §5 的可复现性主张一致：

1. **尺寸对齐**：构建脚本对每个栅格目标**回读其原文件像素尺寸**并照此输出，
   因此替换不会改变任何构建槽位或 CSS 假设——这也是本次改动可被机械核验的原因。
2. **安全区不是估计值**：PWA maskable 主体占高 73%（保证圆为 80%），
   Android 自适应前景主体占高 57%（安全区为 61%）。两者均为实测，
   脚本运行时会打印实测占比。

⚠️ 未纳入版本库的构建产物（如 `apps/stage-pocket/android/app/src/main/assets/public/`）
**不写入**；下次构建会从上述受控源重新生成。

---

## 4. 许可义务履行状态

MIT 许可证的实质条件是：

> "The above copyright notice and this permission notice shall be included in all
> copies or substantial portions of the Software."

| 检查项 | 状态 | 说明 |
|---|---|---|
| 上游版权声明是否保留 | ✅ 已修复（2026-09-15） | 修复前 `LICENSE` **仅有** `Copyright (c) 2026-PRESENT AIJADE`，上游版权声明被覆盖 —— 构成 MIT 违规。现已逐字补回 `Copyright (c) 2024-PRESENT Neko Ayaka` |
| 许可证正文是否保留 | ✅ 是 | MIT 正文原样保留 |
| 是否标注衍生关系 | ✅ 是 | 本文件 + `LICENSE` 抬头 + README |
| 第三方依赖清单 | ✅ 见 `THIRD-PARTY-NOTICES.md` | 依赖树见 `pnpm-lock.yaml` |
| 子包独立许可证是否保留 | ✅ 是 | `packages/font-*/LICENSE*`、`packages/stage-ui-spine/LICENSE.md`、`packages/ccc/LICENSE` 等均在树中 |

> 📌 **修复记录**：2026-09-15 审查发现 `LICENSE` 的上游版权行在品牌化过程中被替换而非追加。
> 该行为在 MIT 下不可自愈（失去声明即失去许可条件），已在本轮治理中修正。

---

## 5. 可复现性与"原创贡献"的可核查性

为让审稿人能区分继承代码与原创代码，建议按以下方式核查：

```bash
# 1) 确认上游基线（需网络）
git clone --depth 1 https://github.com/moeru-ai/airi /tmp/airi-upstream

# 2) 取出本仓库的原创包清单（见 §3）
ls packages/ | grep -E "memory-biomimetic|research-harness|research-telemetry|skill-bench-env|skill-forge-store|agent-skill-forge|agent-capabilities|agent-continuous-learning|growth-services|model-substrate"

# 3) 逐包比对：上游存在 → 继承；上游不存在 → AIJADE 原创
```

> ⚠️ 本仓库的 git 历史已被压平为单一提交（`5432bd3 AIJADE: LLM-powered virtual character platform`），
> **无法**从本仓库历史中恢复上游的具体引入点（fork 点 commit）。
> 因此 §3 的原创性边界目前依赖"上游是否存在同名包"这一人工比对，而非自动化 diff。
> 该局限必须在论文的可复现性声明中如实说明。

---

## 6. 待作者核实事项

| # | 事项 | 为什么重要 | 建议动作 |
|---|---|---|---|
| 1 | **上游 fork 点 commit hash** | 审稿人可能要求"给出你基于的准确版本"。当前无法从压平的历史中恢复 | 从原始 fork 记录 / 本地残留的 `.git` 备份 / 上游 release 时间线推断，填入本节；或明确声明"基于 upstream main 分支 2026-09 前后的快照" |
| 2 | **上游许可证在 fork 时点的原文** | 本文件引用的是当前上游 `main` 的版权行（`2024-PRESENT Neko Ayaka`）。若 fork 时点声明不同，需以 fork 时点为准 | 核对 fork 时点的上游 `LICENSE`，如有差异则同步修正根 `LICENSE` |
| 3 | **`bucket/` 目录的来源** | 该目录已入库，用途与来源未在文档中说明 | ✅ 已澄清（见 §6.1）：Scoop 分发清单，非运行时依赖，不归入 §2-A 的继承改动 |

---

### 6.1 `bucket/` 目录溯源澄清（解决 §6#3）

`bucket/aijade.json` 是 **Scoop 包管理器**（Windows 第三方软件分发器，`https://scoop.sh`）的**入库清单（manifest）**，
指向 GitHub Release `github.com/korose523/AIJADE` 的分发产物。其性质与结论如下：

- **用途**：供终端用户通过 `scoop install aijade`（经 `scoop bucket add` 添加本仓库的 `bucket/`）一键安装预构建的 AIJADE 桌面程序；属于**发布/分发环节**，而非构建或运行时的源码/依赖。
- **是否运行时依赖**：**否**。该 JSON 不被 `pnpm` / `turbo` / 任何应用代码引用，不进入 `node_modules`，不参与打包。删除它只会影响 Scoop 渠道分发，不影响仓库内任何构建或测试。
- **是否上游继承**：**否**。上游 Project AIRI 不含 `bucket/` 目录；此为 AIJADE 侧自行添加的发布通道配置（属 §2-B 品牌化/发布配套，而非 §3 原创研究贡献）。
- **溯源结论更新**：`bucket/` 不归入 §2-A（继承）与 §3（原创），作为独立的"分发清单"登记于此，避免被误判为缺失来源的代码或数据产物。

> 📌 与 §7 #1 的衔接：`bucket/aijade.json` 本身不含第三方代码/字体/数据集，故无需登记到
> `THIRD-PARTY-NOTICES.md`；但其分发的二进制产物的许可证仍由上游 MIT 与 §4 的许可义务覆盖。

---

## 7. 维护约定

1. 任何新增第三方代码、模型权重、数据集、字体、图标集，**必须**同步登记到 `THIRD-PARTY-NOTICES.md`。
2. 任何"改名/搬移/重组"操作**不改变**溯源结论，不得据此淡化上游来源。
3. AI 辅助开发的使用情况单独记录在 `AI-ASSISTED-DEVELOPMENT.md`，与本文件互补、不互相替代。
4. 本文件在每次投稿前必须复核一次（见 `AI-ASSISTED-DEVELOPMENT.md` §5 检查清单）。
