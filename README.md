# AIJADE

> LLM 驱动的虚拟角色平台 —— **附仿生记忆与技能成长研究内核**
>
> monorepo · web / desktop / mobile · TypeScript · pnpm + turbo

[简体中文](#aijade-是什么) · [English](#what-is-aijade) · [溯源](#溯源与许可) · [研究](#研究内核)

---

## AIJADE 是什么

AIJADE 是一个跨端虚拟角色平台：浏览器、桌面（Electron / Tauri）、移动端（Capacitor / PWA）与
即时通讯侧（Telegram / Discord / Minecraft 等）均可承载同一个角色。

它与通用"AI 陪伴应用"的区别在于**平台之下有一层可测量的研究内核**：角色的记忆不是无差别的向量库，
而是一套受生物启发的读写、巩固与身份约束机制；角色的技能不是静态提示词，而是可执行、可被环境
反馈剪枝的技能条目。这层内核是本仓库的原创贡献，也是相关论文的实验对象。

```
apps/          stage-web · stage-tamagotchi · stage-pocket · ui-admin · ui-server-auth · component-calling · server
packages/      平台包（stage-* / ui* / core-* / server-* / plugin-*）+ 研究内核（见下）
services/      computer-use-mcp · speech · discord-bot · telegram-bot · minecraft · satori-bot · twitter-services
plugins/       aijade-plugin-{bilibili-laplace, claude-code, game-chess, homeassistant, web-extension, xiaomi}
engines/       stage-tamagotchi-godot
experiments/   实验产物
```

---

## 研究内核

| 包 | 职责 |
|---|---|
| `packages/memory-biomimetic` | 仿生记忆内核：DGM 双图记忆、HAC 稳态预测式巩固、CDI 受约束身份演化、显著度预测与生命周期管理 |
| `packages/research-harness` | 实验装置：2×2 析因设计、区组化任务分配、退化守卫、统计管线（BCa bootstrap / Holm / DiD / McNemar） |
| `packages/skill-bench-env` | 可执行技能基准环境 + 无泄漏沙箱 oracle |
| `packages/skill-forge-store` | 技能库持久化与学习闭环单元 |
| `packages/agent-skill-forge` | 技能锻造：候选生成 → 自评 → 环境反馈 → 剪枝 |
| `packages/agent-capabilities` | 人格演化 / 技能锻造的编排入口 |
| `packages/agent-continuous-learning` | 持续学习循环 |
| `packages/research-telemetry` | 实验遥测采集 |
| `packages/growth-services` | 成长服务层 |
| `packages/model-substrate` | 模型基底抽象 |

**纵向人格轨迹默认不采集（opt-in，合规要求）**：`agent-capabilities` 的 `onPersonaUpdate`
钩子现通过 `createPersonaTelemetryRecorder()`（由 `agent-continuous-learning` 提供）接入
`research-telemetry`，用于产出跨会话的纵向人格轨迹数据。该记录**默认关闭**——人格轨迹属于
人类被试数据，静默采集无法通过 IRB 审查（本研究受韩国《生命伦理与安全法》约束）。开启方式：
设置项 `settings/research/telemetry-consent`（localStorage，默认 `false`）。**撤回同意不仅停止
记录，还会清除已记录的数据**；遥测写入失败只会上报 `onError`，绝不中断对话。

**设计原则（实验有效性的前提）**：

1. **操纵必须因果可达** —— 任何被声明的实验因子，必须存在一条从因子到测量结果的因果通路。
   若某因子在实现上无法影响输出，则该设计是"构造性零"，任何主效应/交互在数学上不可能被检出。
   实现层面有 `detectDegeneracy()` 守卫强制报警（详见 `research-harness` 文件头）。
2. **分析单元 = 技能，而非执行** —— 一个被复用 N 轮的技能与自身完全相关（ρ=1）。
   把每次执行当作独立伯努利试验会把标准误低估约 1.5× 并造出虚假显著。
3. **确定性优先** —— 实验在 `temperature: 0` 下运行；输出的多样性来源应放在**提示词**里，
   而不是采样器里，否则结果不可复现。
4. **无泄漏** —— 沙箱 oracle 反馈可暴露"哪一例失败"，**绝不**暴露期望输出。

---

## 快速开始

```bash
# 环境：Node ≥ 22 · pnpm 10.x
pnpm install

pnpm dev:web            # 浏览器端主界面
pnpm dev:tamagotchi     # 桌面宠物（Electron）
pnpm dev:server-auth    # 鉴权服务
pnpm dev:admin          # 管理后台
pnpm build              # 全量构建
pnpm test:run           # 全量测试（vitest）
pnpm lint               # 代码检查
```

### 运行研究实验（需要本地 ollama）

```bash
# 1) 准备模型
ollama pull qwen2.5-coder:7b-instruct

# 2) 重试活性探针（验证"因子 → 输出"因果通路是否真的活着）
pnpm --filter @proj-aijade/research-harness exec tsx scripts/retry-liveness-probe.mts

# 3) 全量预注册实验（trials=30 / rounds=5 / tasks=12 / seed=42）
pnpm --filter @proj-aijade/research-harness exec tsx src/cli.ts \
  --trials 30 --seed 42 --backend ollama \
  --model qwen2.5-coder:7b-instruct --rounds 5 --tasks 12 \
  --out experiments/rq-c
```

> ⚠️ 全量运行需数小时。**先跑第 2 步**：若探针显示"重试输出与上次逐字节相同"，
> 说明因果通路已死，此时跑全量只会得到构造性零。

---

## 研究合规与治理

| 文件 | 作用 |
|---|---|
| [`PROVENANCE.md`](./PROVENANCE.md) | 与上游 Project AIRI 的衍生关系、许可义务履行状态、原创贡献边界 |
| [`THIRD-PARTY-NOTICES.md`](./THIRD-PARTY-NOTICES.md) | 第三方代码 / 资产 / 模型权重的许可与归属 |
| [`AI-ASSISTED-DEVELOPMENT.md`](./AI-ASSISTED-DEVELOPMENT.md) | AI 辅助开发披露（中 / 韩 / ACM 三种口径） |
| [`LICENSE`](./LICENSE) | MIT，含上游版权声明 |

**投稿前必须确认**：`AI-ASSISTED-DEVELOPMENT.md` §4 使用记录表已由作者本人填写真实情况，
且无任何 AI 生成数据被当作实验结果。

---

## 溯源与许可

本仓库是 **[Project AIRI](https://github.com/moeru-ai/airi)** 的衍生作品，上游采用 MIT 许可
（`Copyright (c) 2024-PRESENT Neko Ayaka`）。

- 平台层（`stage-*` / `ui*` / `core-*` / `server-*` / `plugin-*` / `services/*` / `engines/*`）
  **继承自上游**，本仓库主要是改名与品牌化，**不主张原创**。
- 研究内核（见上表）为 AIJADE 原创新增，是论文贡献主体。

详细边界、待核实项与核查方法见 [`PROVENANCE.md`](./PROVENANCE.md)。

> 📌 上游的 VitePress 文档站（原 `docs/`，约 320 个文件）已在本仓库移除：
> 其内容面向上游品牌且已与当前代码基脱节，保留会构成对读者的误导。
> 上游文档请访问上游仓库。AIJADE 自身的开发笔记位于仓库外的文档集。

---

## What is AIJADE

A cross-platform LLM virtual-character platform (web / desktop / mobile / IM bots) with a
**measurable research core**: biomimetic memory (dual-graph memory, homeostatic
consolidation, constrained identity evolution) and executable, environment-pruned skill
forging. The platform layer is inherited from Project AIRI; the research kernel is original.

---

## 免责声明

本项目仅供研究与学习用途。角色形象、语音、字体等第三方资产的商业使用请自行确认授权。
平台内所有由 LLM 生成的内容均为模型输出，不代表本项目立场。
