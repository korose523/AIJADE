# p2-h2-salience — H2 de-oracled: content-salience gated vs uniform (2026-09-15 re-run)

**Command**
```
env -u NODE_OPTIONS node_modules/.bin/tsx eval/p2-h2-salience.ts
```
(run from `packages/memory-biomimetic`; corpus `eval/data/locomo10.json`, 10 conversations, horizon +90d, budgets 10%/25%/50%, K=4)

**Exit status:** 0

**Machine-readable output:**
- `eval/results/p2-h2-salience.json` (script-native, fresh at 18:47)
- `eval/results/p2-h2-salience-2026-09-15.json` (dated copy)

## Headline numbers

**Predictor quality (predicted content salience vs oracle labels):**
- pooled AUC = **0.645** (0.5 = random) — below the 0.78 "usable" bar cited in the script header, i.e. the salience signal is real but weak.
- per-conversation AUC: [0.62 0.57 0.67 0.59 0.68 0.70 0.58 0.68 0.64 0.68], mean 0.641.

**Gated vs uniform recall@4 after budget truncation (evidenceRecall@4):**

| budget | gated  | uniform | gap (gated−uniform) |
|--------|--------|---------|---------------------|
| 10%    | 0.1048 | 0.0423  | **+0.0625** |
| 25%    | 0.1215 | 0.0754  | **+0.0460** |
| 50%    | 0.1536 | 0.1183  | **+0.0353** |

## Interpretation

- **gated > uniform at every budget** — the content-salience gate recovers more evidence than the uniform (NO_GATING) baseline under matched storage. The gap is **positive and widens as the budget tightens** (10% → largest gap), matching the pre-registered falsifiable prediction (tighter budget ⇒ gating matters more). H2 (de-oracled) therefore **holds**.
- **Caveat:** the gate rides on a predicted-salience signal of pooled AUC 0.645, which is below the 0.78 threshold the script itself names as "usable". The advantage is real but rests on a weak predictor; closing it further requires improving the salience model, not just the gating mechanics.
- This result is the *de-oracled* H2 (no oracle labels leaked), so it is not the oracle-leakage artifact the original H2 could have been.

## Raw stdout

```
=== H2 去 oracle 化：预测（内容）salience 下的 gated vs uniform ===
corpus        : /Users/mac/WorkBuddy/AIJADE/AIJADE/packages/memory-biomimetic/eval/data/locomo10.json
conversations : 10
horizon       : +90d
budgets       : 10%, 25%, 50%
metric        : evidenceRecall@4 after budget truncation

--- 预测器质量（predicted vs oracle 标注）---
  pooled AUC : 0.645   (0.5 = 随机)
  逐对话 AUC : [0.62 0.57 0.67 0.59 0.68 0.70 0.58 0.68 0.64 0.68]  mean=0.641

--- H2 对照：gated vs uniform（预测/内容显著性门控）---
  budget |  gated  | uniform |  gap
    10%  | 0.105 | 0.042 | +0.063
    25%  | 0.121 | 0.075 | +0.046
    50%  | 0.154 | 0.118 | +0.035

artifact written: eval/results/p2-h2-salience.json
```
