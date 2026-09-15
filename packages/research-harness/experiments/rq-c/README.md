# RQ-C 实验产物登记与说明

本目录存放 **RQ-C（自评可信度测量）** 研究协议的实验产物。
每个子目录 = 一次完整运行。文件名遵循 `<protocol>-s<seed>-<backend>-t<trials>-r<rounds>[-<标记>]`。

> ⚠️ **本文件是审查入口。** RQ-C 的结论只有在正确区分下列三类运行之后才成立：
> **阳性对照（mock）**、**阴性对照（INERT）**、**主结果（live）**。
> 把 mock 或 INERT 的结果当作实证发现引用，是本协议中最容易犯、也最致命的错误。

---

## 1. 预注册协议常量

| 参数 | 预注册值 | 说明 |
|---|---|---|
| 任务数 `tasks` | 12 | 每轮固定任务集，区组设计 |
| 轮次 `rounds` | 5 | 每任务最多 5 轮 |
| 试次数 `trials` | 30 | 每条件 30 个独立试次 |
| 随机种子 `seed` | 42 | 采样锁定 |
| 采样温度 `temperature` | 0 | 贪心解码，保证可复现 |
| 剪枝阈值 `pruneThreshold` | 0.5 | `envFeedback` 条件下的低精度剪枝 |
| 最小调用数 `pruneMinCalls` | 3 | 至少 3 次调用后才允许剪枝 |
| 分析单元 | **skill** | 非 execution（见 `src/harness.ts` 文件头） |

每条件步数 = 30 × 12 × 5 = **1800**；四条件合计 **7200 步**。

**四格设计（2×2 析因）**

| | `envFeedback` OFF | `envFeedback` ON |
|---|---|---|
| **`selfVerification` OFF** | `sv0-ef0`（对照） | `sv0-ef1` |
| **`selfVerification` ON** | `sv1-ef0` | `sv1-ef1` |

> 📌 目录名中的 `t30-r3` 与 `pruneMinCalls=1` 属于**偏离预注册**的试点配置，
> 不得与预注册主结果混用。偏离项由 harness 的 `preregistrationDeviation` 字段自动记录。

---

## 2. 运行登记表

| 目录 | 后端 | 试次/轮次 | 步数 | 角色 | 可否引用为实证 |
|---|---|---|---|---|---|
| `rq-c-s42-mock-t30-r5` | mock（注入参数） | 30 / 5 | 7200 | **阳性对照** | ❌ 不可（模拟数据） |
| `rq-c-s42-ollama-t30-r5-INERT-2026-09-14` | ollama | 30 / 5 | 7200 | **阴性对照**（退化证据） | ❌ 不可（构造性零） |
| `rq-c-s42-ollama-t30-r5` | ollama | 30 / 5 | 7200 | **主结果** | ✅ 可（修复后重跑） |
| `rq-c-s42-ollama-t30-r3` | ollama | 30 / 3 | 2880 | 试点（偏离预注册） | ❌ 不可（仅内部参考） |
| `rq-c-attmend-s42-ollama-t3-r5` | ollama | 3 / 5 | 62 | 重试活性试跑（中断） | ❌ 不可 |
| `rq-c-smoke-validate-s42` | ollama | 1 / 3 | 36 | 管线冒烟 | ❌ 不可 |

---

## 3. 三类运行的角色与结果

### 3.1 阳性对照 — `rq-c-s42-mock-t30-r5`

模拟后端注入已知的 **hallucination = 0.30 / miss = 0.10**，用于验证**估计器与控制流**能否
检出人为植入的效应。它不检验现象，只检验装置。

| 指标 | 值 |
|---|---|
| 交互项 log-odds | **−0.1753** |
| 标准误 | 0.0603 |
| z | **−2.907** |
| p | **0.0037** ✅ 显著 |
| 检出率一致性 agreement | 0.804 |
| 估计的 hallucination / miss | 0.242 / 0.129 |
| nSkills / nExecutions | 2199 / 7200 |
| 80% 功效最小可检出效应 | **8.42 pp** |

> **结论**：装置**有能力**检出交互效应。这是主结果"阴性"时唯一有说服力的辩护依据。
> ⚠️ 摘要中必须写明 "simulation, do not cite as empirical"（该字段已自动写入 `summary.json`）。
> ⚠️ 该运行的 `gitHash` 为 `9062133…`，**不在当前仓库历史中**（历史已被压平）。
> 引用前需确认其对应的代码状态，或在新代码上重跑一次以消除该溯源缺口。

### 3.2 阴性对照 — `rq-c-s42-ollama-t30-r5-INERT-2026-09-14`

2026-09-14 的实跑。四格 precision **完全相同**，交互项恰为 0、p = 1。

| 指标 | 值 |
|---|---|
| 交互项 log-odds | **0（精确）** |
| p | **1.0** |
| 自评 miss 率 | **0.704**（模型在**正确**时也 70% 判为 fail） |
| 自评 hallucination 率 | 0.096 |
| 一致性 agreement | 0.733 |
| nSkills / nExecutions | 1708 / 7200 |

**根因（两个缺陷叠加）**：

1. `createOllamaBackend.generate(task, _ctx)` **完全不读 `_ctx`** → 重生成的提示词与上一次逐字节相同；
2. 运行使用 `temperature: 0` → 相同提示词解码出相同文本。

⇒ 执行结果成为**任务身份**的纯函数（44 个任务中 5 个恒失败、39 个恒通过），
**两个因子都没有通往结果的因果通路**。任何量级的主效应/交互在数学上都不可能被检出。

> **为什么必须保留这次运行**：它是"我们在 2026-09-14 报告的零是**构造性零**，
> 而非经验零"的直接证据。删掉它，就等于把一个已被证伪的结论留在论文里。
> 修复见提交 `ac03b31`；守卫 `detectDegeneracy()` 会使同类运行**显式报警**而非静默通过。

### 3.3 主结果 — `rq-c-s42-ollama-t30-r5`

修复后（`ac03b31`）在 qwen2.5-coder:7b-instruct 上的重跑。**本目录即论文 §5 的唯一数据来源。**
运行进行中，`summary.json` 在四条件全部完成后生成。

---

## 4. 产物文件说明

| 文件 | 内容 |
|---|---|
| `trials.jsonl` | 逐步记录（每行一步）：条件、试次、轮次、任务、技能 ID、是否复用、自评裁决、执行结果、耗时 |
| `summary.json` | 汇总：格均值与 CI、效应量、McNemar、DiD、析因交互、Holm 多重比较、功效、诊断、退化判定、预注册偏离、`gitHash` / 采样指纹 |
| `table*.csv` / `fig*.csv` / `figures.json` | 由汇总派生、供论文直接引用的图表数据（仅 mock 运行完整生成） |
| `trials.jsonl.bak-*` | 运行期备份，**非产物**，不得引用 |

`.gitignore` 默认排除 `experiments/`（防止含人类交互日志的遥测外泄）。
本目录经**定向白名单**纳入版本控制——RQ-C 协议无人类被试（候选由 LLM 生成、由确定性沙箱 oracle 判定），
隐私理由不适用，而"结果可复核"的义务适用。见 `.gitignore` 中的 `EXCEPTION` 段。

---

## 5. 复跑方式

```bash
# 阳性对照（秒级~分钟级，不依赖 ollama）
pnpm --filter @proj-aijade/research-harness exec tsx src/cli.ts \
  --trials 30 --seed 42 --backend mock --rounds 5 --tasks 12 \
  --out experiments/rq-c/rq-c-s42-mock-t30-r5

# 主结果（数小时，需 ollama + qwen2.5-coder:7b-instruct）
pnpm --filter @proj-aijade/research-harness exec tsx src/cli.ts \
  --trials 30 --seed 42 --backend ollama --model qwen2.5-coder:7b-instruct \
  --rounds 5 --tasks 12 --out experiments/rq-c/rq-c-s42-ollama-t30-r5
```

**跑前必做**：先运行重试活性探针（`scripts/retry-liveness-probe.mts`）。
若探针显示重试输出与上次逐字节相同，说明因果通路已死，此时跑全量只会重现构造性零。
