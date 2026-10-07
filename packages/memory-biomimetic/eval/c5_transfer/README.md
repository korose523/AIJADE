# C5 可迁移性实验（AIJADE 五条可复现性约束 × mem0）

本目录回答的问题**不是**"mem0 表现如何"，而是：

> **AIJADE 的五条可复现性约束，能否在第三方记忆系统上被*计算*出来？**

两者必须分开的原因：前者需要等算力与等条件的 A/B，本实验两者都不具备；
后者只需要"判据所需的可观测量是否存在"，而这正是可审计的。

## 五条约束与施加层级

层级含义：`black` = 只有被测系统公开 API；`gray` = 运行环境由我们控制。

| 约束 | 施加层级 | 判定 | 关键理由 |
|------|----------|------|----------|
| 1 determinism pre-check | gray | 部分施加 | mem0 不暴露 substrate，采样参数实际取值不可观测 |
| 2 run fingerprint | gray | 部分施加 | 模型 digest / 依赖锁 / 喂入输入可钉；mem0 内部提示词版本不可得 |
| 3 degeneracy guard | black | **完整施加** | 只需被测系统输出，判据完全可算 |
| 4 leak-free sandbox oracle | black | **完整施加** | 且实测到两类真实泄漏向量 |
| 5 artifact registry | gray | 部分施加 | "control / main result"只存在于运行者侧 |

## 运行

```bash
# 依赖（venv 内，不污染系统Python）
/Users/mac/.workbuddy/binaries/python/envs/default/bin/python -m pip install mem0ai ollama

# 语料（LongMemEval oracle 切分，MIT）
curl -L -o packages/memory-biomimetic/eval/data/longmemeval_oracle.jsonl \
  https://huggingface.co/datasets/xiaowu0162/longmemeval/resolve/main/longmemeval_oracle

# 底座：把采样参数钉进模型别名（mem0 不透传 seed/top_k，见 adapter.mem0_observability）
printf 'FROM qwythos:latest\nPARAMETER num_ctx 16384\nPARAMETER temperature 0\nPARAMETER top_p 1.0\nPARAMETER top_k 1\nPARAMETER repeat_penalty 1.0\nPARAMETER seed 42\n' > /tmp/Modelfile.c5
ollama create c5-qwythos-16k -f /tmp/Modelfile.c5
ollama pull nomic-embed-text          # embedder；注意 mem0 默认 dims=512 与实际 768 不符

# 两臂
python packages/memory-biomimetic/eval/c5_transfer/run.py --arm store --limit 3 \
  --out packages/memory-biomimetic/eval/results/c5-mem0-transfer-store-arm.json
python packages/memory-biomimetic/eval/c5_transfer/run.py --arm infer --limit 1 \
  --out packages/memory-biomimetic/eval/results/c5-mem0-transfer-infer-arm.json

# 测试
python -m pytest packages/memory-biomimetic/eval/c5_transfer/ -q
```

## 两个臂为什么都存在

|臂 | mem0 调用 | 实测结果 | 作用 |
|----|-----------|----------|------|
| `store` | `add(infer=False)` | 4/4 成功，检索非空，守卫判`reachable` | **主结果**：证明判据在真实第三方系统上可算 |
| `infer` | `add(infer=True)` | 抽取事件恒为 0，守卫判`APPARATUS_INADEQUATE` | **对照**：证明守卫会拦住一个会被误读为"构造性零"的数字 |

`infer` 臂的抽取恒空已定位到根因（不是本实验的 bug）：mem0 的 ollama provider
向最后一条user 消息追加 `"Please respond with valid JSON only."` 并置
`format="json"`，本机底座模型在该组合下无限生成 JSON 前缀/空白直至
`num_predict` 耗尽（实测 512 与 2048 均为 `done=length`、内容长度 0）；
去掉该后缀、其余不变则 `done=stop`、解析出 6 条记忆。

⇒ `store` 臂绕过了 mem0 的 LLM 抽取环节，其检索数字**只能**用于验证判据可计算性，
**不可**作为 mem0 事实抽取能力的证据。

## 结论边界（写作者必须遵守）

产物里`verdict_scope.inferenceScope = "judge-computability-only"`。可以说：

- 五条约束中，**三条在纯黑盒下完全可算**（3、4 完全施加；且3 的两个分支都实测到了）；
- 约束 1、2、5 **只能在灰盒下部分施加**，缺口已逐条写明；
- 约束 4 在本语料上实测到**两类真实泄漏向量**，其中 `has_answer` 是可直接消除的。

**不可以说**：

- "五条约束在别的项目里带来了提升" —— 需A/B，本实验不具备；
- 任何 mem0 的能力水平评估 —— 小 n + 本机算力（见产物 `feasibility`）。

## 文件

| 文件 | 作用 |
|------|------|
| `adapter.py` | 唯一触碰 mem0 的地方；五条约束的探针与可观测性事实 |
| `degeneracy.py` | 退化守卫判定（三种"零"的区分），有单测锁定 |
| `fingerprint_lib.py` | FNV-1a，与 `model-substrate` 同算法；用公开标准向量验证 |
| `run.py` | runner；`--one` 单题子进程隔离，`--arm` 选臂 |
| `test_*.py` | 13 项测试：标准向量、键序一致性、退化判定 |
