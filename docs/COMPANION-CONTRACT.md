# 与 MOSAIC 共享的伴侣契约（非研究线）

决定见 [ADR-002](decisions/ADR-002.md)。契约文件是 [`configs/companion/contract.json`](../configs/companion/contract.json)，当前版本 1.0.0（2026-10-28）。它属于非研究线：

- 不是学位论文任何研究的输入、样本、奖励或判定条件；
- 不触及研究对象；
- 不新增网络接口或进程。

本仓库不修改 MOSAIC。MOSAIC 一侧需要做的事见文末"交接"。

## 文件

| 文件 | 内容 |
|---|---|
| `configs/companion/contract.json` | 人设、表情名称的对应、主动开口规则（闸门、权重、阈值） |
| `configs/companion/initiative-vectors.json` | 主动开口的 18 条判定向量：由 MOSAIC 的 `initiative()` 生成，记录其文件的 SHA-256 与读取日期，并含"道别"与"安静"两张词表 |
| `configs/companion/generate_initiative_vectors.py` | 重新生成向量的脚本：按文件路径只读加载 MOSAIC 的伴侣模块，不执行其包初始化，不写字节码 |
| `src/Aijade.Client/Chat/Orchestrator.cs` | `ChatOrchestrator.DefaultPersona` 即契约中的人设提示词 |
| `src/Aijade.Client/Companion/Initiative.cs` | 主动开口规则的参考实现（AIJADE 一侧），尚未接入任何产品界面 |
| `tests/Aijade.Tests/CompanionContractTests.cs` | 契约与代码一致；参考实现在全部向量上与 MOSAIC 的判定相同 |

## 人设：艾娅德（Aijade-9）

- **提示词**：见契约的 `persona.prompt`。两边使用同一段文字。来源是作者的 v9 角色圣经（§1、§5、§6），措辞取自 MOSAIC 10 月 28 日在 llama3.1:8b 上检查过的版本（16 条消息 × 2）。
- **刻意不写入的内容**：
  - 圣经 §6.2 的"先复述信号，把感受与事实分开"：在 llama3.1:8b 上，它让模型把情绪硬读进闲聊；
  - 圣经 §6.3 的引用模板句：在 8 条难过的回复中有 6 条被原样照抄。
- **AIJADE 的变化**：默认人设由原来概括圣经的那段文字（"treats emotion as a signal…"）改为契约文字。角色库里另建的角色不受影响。

## 表情名称的对应

只对应名称，不对应两边的数值向量。

| AIJADE 舞台表情（`[[emote:…]]`） | MOSAIC 回复的 emotion |
|---|---|
| joy | happy |
| calm | calm |
| curious | curious |
| sad、angry、surprised、shy、thinking、sleepy | neutral（没有对应） |

MOSAIC 的 neutral 在 AIJADE 一侧不写标记。MOSAIC 的手势（none、head_dip、head_tilt）在 AIJADE 中没有对应的标记，不在对应表中。

## 主动开口（她先开口）

机会评分而非随机定时器（AIJADE v5"主动陪伴引擎"的结构），规则固定，不做自适应：

- **闸门**，按顺序检查，任一成立就不开口：
  1. 深夜 0–7 点；
  2. 两小时内要求过安静；
  3. 对方最后一句是道别或说要忙；
  4. 她连着两句没人接；
  5. 安静不到 3 分钟（上一句没人接时 6 分钟）；
  6. 距她上次先开口不到 8 分钟（没人接时 16 分钟）；
  7. 这一小时已先开口 3 次。
- **分数**：0.35 × 相关性 + 0.15 × 新颖性 + 0.35 × 社交需要 + 0.15 × 场合 − 0.6 × 打扰风险 − 0.4 × 本小时次数 / 3；分数不低于 0.75 才开口。各分量的定义见契约的 `initiative.parts`。
- **效果**：有话题可接时约 5.5 分钟开口，没有时约 10 分钟。
- **一致性**：18 条向量覆盖每道闸门和阈值两侧；AIJADE 的参考实现与 MOSAIC 的实现判定全部相同。阳性对照中，把阈值改为 0.76 后，两项契约测试都失败。

## 修改契约

任何一边改人设、表情词表或主动开口规则，先改契约、升版本号。

- 主动开口规则变了，用下面的命令重新生成向量。本仓库的契约测试在两边同步之前会失败。
- MOSAIC 的伴侣模块仍在频繁修改。向量文件记录的 SHA-256 只标明生成时读的版本：2026-10-28 当天该文件改过两次，主动开口的参数、词表与 18 条判定都没有变。

```bash
python3 -B -I configs/companion/generate_initiative_vectors.py "$MOSAIC/ai-python/mosaic/integration/companion.py" configs/companion/initiative-vectors.json
```

## 交接：MOSAIC 一侧（由 MOSAIC 的会话或作者采用）

1. **人设文字**：把 `PERSONA` 开头的 ", the companion from the owner's AIJADE character bible:" 改为 ":"，即与契约文字逐字相同。2026-10-28 核对过，两者只差这一处。改后建议按原方法在 Windows 的 llama3.1:8b 上复查一次（16 条消息 × 2）。
2. **记下契约版本**：在 MOSAIC 的伴侣文档中记下所依据的契约版本（1.0.0）。以后改 `PERSONA`、`EMOTIONS`、`INITIATIVE`、`LEAVING` 或 `HUSH` 时，同时提出契约的修改。
3. **可选**：用 `initiative-vectors.json` 回归 MOSAIC 自己的 `initiative()`。向量就是由它生成的，代码不变时必然一致。
4. **不涉及**：本契约不改变第 4 章外部比较所用的渲染器契约（[MOSAIC-RENDERER](MOSAIC-RENDERER.md)），也不要求 MOSAIC 连接 AIJADE 的服务端。

## 以后可以考虑的（未做，需作者另行决定）

- **AIJADE 作对话大脑**：AIJADE 服务端提供只听本机、与 Ollama `/api/chat` 兼容的接口，MOSAIC 只改 `CompanionUrl`。要先解决两套记忆并存的问题，并保证 MOSAIC 的动作说明原样透传。
- **MOSAIC 作 AIJADE 的舞台**：AIJADE 的聊天渠道经现有渲染器契约驱动 MOSAIC 客户端。外部渲染器的发送端是第 4 章的研究对象，只能调用，不能修改。
- **AIJADE 产品接入主动开口**：用本契约的参考实现，在 Web 聊天中让伴侣先开口。
