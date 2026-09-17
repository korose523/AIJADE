# diag-weight-ablation — weight-ablation table (2026-09-15 re-run)

**Command**
```
env -u NODE_OPTIONS node_modules/.bin/tsx eval/diag-weight-ablation.ts
```
(run from `packages/memory-biomimetic`; corpus `eval/data/locomo10.json`, sha256 `79fa87e9…`, 10 conversations, 1986 questions)

**Exit status:** 0

**Machine-readable output:**
- `eval/results/p2-weight-ablation-2026-09-15.json` (script-native, fresh at 18:36)
- `eval/results/diag-weight-ablation-2026-09-15.json` (dated copy)

## Headline numbers (recall@K, K=8; condition = NO_GATING, re-rank pool = 150)

| weights          | sim | str | rec | ctx |  K=1  |  K=2  |  K=4  |  K=8  |
|------------------|-----|-----|-----|-----|-------|-------|-------|-------|
| current (default)|  1  | 0.6 | 0.3 | 0.4 | 0.0368| 0.0579| 0.0780| 0.0906|
| sim-only         |  1  |  0  |  0  |  0  | 0.1828| 0.2508| 0.3102| 0.3580|
| sim+ctx          |  1  |  0  |  0  | 0.4 | 0.1903| 0.2583| 0.3202| 0.3640|
| sim+str          |  1  | 0.6 |  0  |  0  | 0.1511| 0.2044| 0.2563| 0.2981|
| no-recency       |  1  | 0.6 |  0  | 0.4 | 0.1611| 0.2160| 0.2638| 0.3046|
| sim-heavy        |  3  | 0.6 | 0.3 | 0.4 | 0.1662| 0.2226| 0.2800| 0.3207|
| str-only         |  0  |  1  |  0  |  0  | 0.0076| 0.0096| 0.0136| 0.0176|
| rec-only         |  0  |  0  |  1  |  0  | 0.0076| 0.0096| 0.0136| 0.0176|

**sim-only vs current gap @K=8:** +0.2674 (3.95×). Same ~4× ratio as the pre-fix table (§8.2: 0.2049 vs 0.0534).

**Recency bias (current weights, top-8):** mean 7.73/8 memories newer than the gold evidence vs an unbiased baseline of 3.79 — slot age percentile 0.976. Bias confirmed.

## ⚠️ Interpretation caveat (important)

This table is **deliberately constructed to bypass the store's `standardized` default**: it reads the raw `parts` (similarity/strength/recency/context) from `retrieve()` and re-combines them with explicit weights over the top-150 candidates. Because it never applies the new z-scoring, it **still** shows the ~4× mismatch between `current` and `sim-only`. That gap is the **demonstration of the dimensional mismatch** that motivated commit `014b17b` — it is **not** a regression and does **not** measure the fix's effect.

The decisive question — "what does the store do by default under `standardized`?" — is answered by the **store-level runs** (p1.5-recall, p2-h2-forgetting, p2-h2-salience, p2-quantile-retention-sweep, p2-h5), which call `retrieve()` with the default `retrievalScoreMode: 'standardized'`. See those reports for the actual post-fix behaviour.

## Raw stdout

```
=== 权重消融 + 新近偏置逐条核验 ===
corpus : /Users/mac/WorkBuddy/AIJADE/AIJADE/packages/memory-biomimetic/eval/data/locomo10.json
sha256 : 79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4
convs  : 10
condition: NO_GATING（不剪枝、不重加权，隔离出纯检索器行为）

  weights       sim  str  rec  ctx      K=1      K=2      K=4      K=8   note
  current         1  0.6  0.3  0.4   0.0368   0.0579   0.0780   0.0906   现行 DEFAULT_RETRIEVAL_WEIGHTS
  sim-only        1    0    0    0   0.1828   0.2508   0.3102   0.3580   只用相似度（相关性优先）
  sim+ctx         1    0    0  0.4   0.1903   0.2583   0.3202   0.3640   相似度 + 上下文
  sim+str         1  0.6    0    0   0.1511   0.2044   0.2563   0.2981   相似度 + 强度（去新近项）
  no-recency      1  0.6    0  0.4   0.1611   0.2160   0.2638   0.3046   现行权重但把 recency 置 0
  sim-heavy       3  0.6  0.3  0.4   0.1662   0.2226   0.2800   0.3207   相似度 ×3
  str-only        0    1    0    0   0.0076   0.0096   0.0136   0.0176   只用强度（极端对照）
  rec-only        0    0    1    0   0.0076   0.0096   0.0136   0.0176   只用新近（极端对照，受池截断影响最大）

--- 新近偏置逐条核验（现行权重的 top-8）---
  已扫描题目                 : 1986
  无证据时间戳（跳过）        : 9
  top-8 中比金标准证据更晚的条数 : 实测均值 7.73 / 8
  若无偏置的期望基线          : 分位 × 8 ≈ 3.79
  top-8 的年龄分位均值        : 0.976（愈大愈"新"）

--- 判读（本段由上方实测数字生成，无硬编码结论）---
【① 新近偏置是否存在】
  top-8 中"比证据更晚"的条数 7.73 vs 无偏置基线 3.79
  ⇒ ✅ 偏置存在：top-8 显著偏向"更晚"的记忆，超过池子的自然分位。

【② 权重消融】(K=8，候选池固定为现行打分前 150 条)
  current   0.0906   （基准）
  sim-only  0.3580   +0.2674
  no-recency0.3046   +0.2140
  sim-heavy 0.3207   +0.2301
  rec-only  0.0176   -0.0730  ← 受池截断影响最大，只当下界读

【③ 结论】
  ⇒ 只用相似度 0.3580 / 去掉 recency 0.3046 **都优于**现行权重 0.0906。
     即：**打分函数里的非相关性项（recency / strength）在系统性地损害检索**。
  ⇒ 可行动的改动：把 recency 权重调低或置 0，或对 similarity 做加权归一（sim-heavy 0.3207）。

⚠️ 口径限制：重排仅在现行打分的前 150 条内进行，
   故与现行权重差异极大的组合（rec-only 尤甚）的数字只能当作**下界**。
```
