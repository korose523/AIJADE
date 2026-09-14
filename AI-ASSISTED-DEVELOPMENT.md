# AI-ASSISTED-DEVELOPMENT — AI 辅助开发披露

> ⚠️ **本文件是披露框架 + 模板，必须由作者（研究者本人）核对并填写真实使用情况后方可投稿/答辩。**
> 其中标注「〔待作者核实〕」的内容为占位/示例，**不是既定事实**。

---

## 1. 为什么必须披露（合规依据）

| 口径 | 要求 | 要点 |
|---|---|---|
| **中国** | 《学位法》第三十七条 | 代写 / 剽窃 / 伪造可**撤销学位**。部分高校明文允许 AI 辅助**代码编写调试**，但须列明工具名/版本/日期/使用过程；**部分高校禁止**用 AI 做研究方案设计、创新性方法设计、**算法框架搭建**。 |
| **韩国** | 无国家强制，校级自定 | 如国民大学《AI 伦理宪章》把**未披露 AI 使用**列为研究禁止行为，给出引用格式（见 §3）。 |
| **出版方（更严）** | ACM / CIKM 等 | GenAI **不得列为作者**；凡用于**研究过程**（实验设计、数据生成、编码、仿真、分析）者**必须在 Methods 详述**。CIKM 2025 已设强制披露章节（不计页数）。 |

**核心推论（决定贡献主张怎么写）**：
> **贡献主张必须押在「设计决策 + 实验证据」上，而不是「代码产出量」上。**
> 代码量在中国部分高校口径下不加分、甚至可能触发审查；设计决策与实验证据在中韩两地都是硬通货。

---

## 2. 披露总原则

1. AIJADE 的 AI 辅助开发史**写进 Methods**。这是**加分项**，前提是写清「我用 AI 做了什么、我又**人工验证**了什么」。
2. 任何由 AI 生成的**实验数据**不得作为论文实验数据（中国农业大学口径：不得将 AI 生成数据作为实验数据）。
3. 算法框架 / 研究方法 / 创新性设计若涉及 AI，须按所在院校口径判断是否越界，**必要时改为人工主导并如实说明**。

---

## 3. 引用 / 披露格式

**韩国高校（国民大学式，文内或脚注）：**
```
<工具名> (<版本或日期>). [Task: <任务简述>; Verified: <人工核验方式>].
例：WorkBuddy (Claude, 2026-09-07). [Task: 起草科研化重构方案与治理文档; Verified: 作者逐行审阅并修改定稿].
```

**ACM Methods 披露（建议段落骨架）：**
> During development we used <tool(s)> for <scope: e.g., code drafting, refactoring, test authoring, documentation>.
> All AI-generated code and text were reviewed, edited, and validated by the authors. Experimental design,
> research questions, algorithmic framing, and all reported measurements were defined and verified by the authors.
> No AI-generated data were used as experimental results. Tool name(s), version(s), and usage period: <…>.

---

## 4. 使用记录表（**待作者填写**）

| 日期 | 工具 / 模型 | 版本 | 用途（Task） | AI 产出 | 人工核验（Verified） |
|---|---|---|---|---|---|
| 〔待作者核实〕 | 〔如 WorkBuddy / Claude / Copilot〕 | 〔版本/日期〕 | 〔如：research-telemetry 包脚手架〕 | 〔如：初稿代码〕 | 〔如：单测 10/10 + 逐行审阅〕 |
| 2026-09-07 | WorkBuddy（Claude） | 〔待补〕 | 起草 `THIRD-PARTY-NOTICES.md` / `PROVENANCE.md` / 本披露框架；git 基线 | 文档初稿 | **待作者审阅定稿** |
| … | | | | | |

---

## 5. 投稿前检查清单

- [ ] 已按**目标院校**（中国/韩国）口径确认 AI 使用是否越界（尤其算法框架与研究设计）。
- [ ] Methods 已包含 AI 辅助披露段落，含工具名/版本/使用期/用途/人工核验。
- [ ] 无任何 AI 生成数据被当作实验结果。
- [ ] 贡献主张建立在**设计决策 + 实验证据**上，并已可复算（见 `PROVENANCE.md` §3）。
- [ ] 目标期刊/会议的 GenAI 披露章节已按模板填写。
