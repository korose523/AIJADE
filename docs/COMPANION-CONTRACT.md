# 与 MOSAIC 共享的伴侣契约（非研究线）

决定见 [ADR-002](decisions/ADR-002.md)。契约文件是 [`configs/companion/contract.json`](../configs/companion/contract.json)，当前版本 1.2.0（2026-10-28）：1.1.0 加入"她先开口时说什么"，AIJADE 的聊天据此接入主动开口；1.2.0 加入"文字渠道"规则，AIJADE 的聊天平台据此采用。它属于非研究线：

- 不是学位论文任何研究的输入、样本、奖励或判定条件；
- 不触及研究对象；
- 不新增网络接口或进程。

本仓库不修改 MOSAIC。MOSAIC 一侧需要做的事见文末"交接"。

## 文件

| 文件 | 内容 |
|---|---|
| `configs/companion/contract.json` | 人设、表情名称的对应、主动开口规则（闸门、权重、阈值） |
| `configs/companion/initiative-vectors.json` | 由 MOSAIC 的实现生成：主动开口的 18 条判定向量（`initiative()`），以及 4 条"说明"与"沉默"消息（`proactive_note()`、`silence()`，含四舍六入五成双与截断）；记录其文件的 SHA-256 与读取日期，并含"道别"与"安静"两张词表 |
| `configs/companion/generate_initiative_vectors.py` | 重新生成向量的脚本：只读加载 MOSAIC 的伴侣模块（用包占位，不执行其包初始化，不写字节码） |
| `src/Aijade.Client/Chat/Orchestrator.cs` | `ChatOrchestrator.DefaultPersona` 即契约中的人设提示词 |
| `src/Aijade.Client/Companion/Initiative.cs` | 主动开口规则、对话到"轮次"的映射、"说明"与"沉默"消息（AIJADE 一侧的实现） |
| `src/Aijade.Client/Chat/Orchestrator.cs` | `ChatOrchestrator.SpeakFirstAsync`：规则允许时生成并保存她先开口的一句 |
| `src/Aijade.UI/Pages/Chat.razor`、`Settings.razor` | 聊天页每分钟询问一次；设置"安静时她会先开口"（`ModuleSettings.SpeakFirst`，默认关闭） |
| `tests/Aijade.Tests/CompanionContractTests.cs` | 契约与代码一致；判定与"说明""沉默"在全部向量上与 MOSAIC 相同；对话映射；闸门挡住时不调用模型 |
| `configs/companion/text-channel-vectors.json`、`generate_text_channel_vectors.py` | 文字渠道规则的常量（用语法树从 MOSAIC 的 `tools/companion_qq.py` 读取，不执行该脚本）与 8 条"补句"用例 |
| `src/Aijade.Client/Companion/TextChannel.cs` | 文字渠道规则（AIJADE 一侧）；由 `CompanionBridge` 在 Discord、Telegram、X 与 Satori 转接的平台上使用 |
| `tests/Aijade.Tests/ClientTests.cs` | 端到端（需要数据库，在 CI 上运行）：她的一句单独保存并带标记；发给模型的消息依次为人设、最近的对话、说明、沉默；不问上下文提供者，不通知观察者 |

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

**她先开口时说什么（1.1.0）**：
- 发给模型的消息与 MOSAIC 相同：人设 → 最近 4 轮对话（她先开口的一句只作为助手消息出现）→ 一条说明 → 一条表示沉默的用户消息"（N 分钟没有说话）"。
- 说明逐字取自 MOSAIC 的 `proactive_note()`：说一句新的短话（不超过 30 字）；有可接的话题就接着问一个好答的问题；不编造经历，不像刚见面那样打招呼，最多问一个问题；引用她上一句，要求说不一样的。
- 她的一句单独保存为助手消息，带标记 `proactive`。生成时不调用上下文提供者（包括记忆召回），也不通知观察者，所以这一句既不会被召回，也不会被学习；这与 MOSAIC"召回旧对话不会用到这种轮次"一致，也使它不经过第 6 章 P3-E 冻结的记忆路径。

**AIJADE 产品中的位置**：设置里的"安静时她会先开口"默认关闭。打开后，聊天页每分钟询问一次；正在回复、正在听或用户正在输入时不问，对话里还没有一轮问答时也不问。生成的一句像普通回复一样显示、驱动舞台、按语音设置朗读。MOSAIC 是单人本机使用，默认开启；AIJADE 是多用户产品，所以默认关闭。

## 文字渠道（1.2.0）

她没有身体的聊天渠道上，按 MOSAIC 在 QQ 上测过的规则回答（Windows llama3.1:8b，2026-10-28）：

- **说明**：每条消息前加一条系统说明"这里没有身体，不能动、跳舞、走或做手势；对方要求时，和气地说回到屏幕前再做"。消息里有动作词（跳舞、鞠躬、挥手、转圈等）时，再加一条针对这一句的说明。两条都放在用户这句话之前。
- **补句**：请求做动作，而回复里没有任何推迟的说法（屏幕、等你、回来、不能、下次等）时，在发出的文字末尾补一句"等你回到屏幕前，我再做给你看。"。保存的回复不变。
- **依据**：MOSAIC 的检查结果：
  - 只有一般说明时，4 次跳舞请求中有 2 次仍被答应；
  - 两条说明都加上后，15 次中 9 次明确推迟；
  - 再加补句，最后两遍 8 次动作请求全部推迟。
- **AIJADE 的范围**：`CompanionBridge` 在 Discord、Telegram、X 与 Satori 转接的平台上使用这些规则，说明里的渠道名写作"Telegram text messages"等。哔哩哔哩直播（可能驱动舞台）与 Minecraft（她有化身）不用。`BridgeOptions.TextChannelRules` 可以关闭这些规则。
- **一致性**：两条说明与 MOSAIC 的原文逐字相同（渠道名换成"QQ text messages on their phone"与"QQ"时），动作词、推迟词与补句相同，8 条用例的补句结果相同。
- **限制与未采用**：
  - 动作词只有中文；
  - MOSAIC 出错时的固定回复与图片的回复是中文定句，而 AIJADE 的渠道多用户、多语言，暂不纳入。

## 修改契约

任何一边改人设、表情词表或主动开口规则，先改契约、升版本号。

- 主动开口规则变了，用下面的命令重新生成向量。本仓库的契约测试在两边同步之前会失败。
- MOSAIC 的伴侣模块仍在频繁修改。向量文件记录的 SHA-256 只标明生成时读的版本：2026-10-28 当天该文件改过两次，主动开口的参数、词表与 18 条判定都没有变。

```bash
python3 -B -I configs/companion/generate_initiative_vectors.py "$MOSAIC/ai-python/mosaic/integration/companion.py" configs/companion/initiative-vectors.json
```

## 交接：MOSAIC 一侧（由 MOSAIC 的会话或作者采用）

**状态（2026-10-28）**：MOSAIC 已在 SVN r389 采用 1.2.0。
- 人设文字与契约逐字相同，按原方法复查（16 条消息 × 2）：32 句中没有出错、照抄或奉承；问名字 2 次都答“我叫艾娅德”；8 句难过的回复中有 5 句给对方留了选择。
- 两份伴侣文档记下契约版本；共享常量旁加了注释，改动时会告知 AIJADE 一侧。
- 它用两份生成脚本在自己的代码上回归，内容全部相同。本仓库独立核对过上述各点，并把向量文件记录的源文件哈希更新为 r389 之后的版本。

1. **人设文字**：把 `PERSONA` 开头的 ", the companion from the owner's AIJADE character bible:" 改为 ":"，即与契约文字逐字相同。2026-10-28 核对过，两者只差这一处。改后建议按原方法在 Windows 的 llama3.1:8b 上复查一次（16 条消息 × 2）。
2. **记下契约版本**：在 MOSAIC 的伴侣文档中记下所依据的契约版本（当前为 1.2.0）。以后改 `PERSONA`、`EMOTIONS`、`INITIATIVE`、`LEAVING` 或 `HUSH` 时，同时提出契约的修改。
3. **可选**：用 `initiative-vectors.json` 回归 MOSAIC 自己的 `initiative()`。向量就是由它生成的，代码不变时必然一致。
4. **不涉及**：本契约不改变第 4 章外部比较所用的渲染器契约（[MOSAIC-RENDERER](MOSAIC-RENDERER.md)），也不要求 MOSAIC 连接 AIJADE 的服务端。

## 以后可以考虑的（未做，需作者另行决定）

- **聊天平台**：两边渠道的对照与四个方案见 [CHAT-CHANNELS-MOSAIC](CHAT-CHANNELS-MOSAIC.md)。方案 A（文字渠道规则）已在 1.2.0 完成；B（AIJADE 的 OneBot 11 连接器）与 C（渠道上先开口）待作者决定。

- **AIJADE 作对话大脑**：AIJADE 服务端提供只听本机、与 Ollama `/api/chat` 兼容的接口，MOSAIC 只改 `CompanionUrl`。要先解决两套记忆并存的问题，并保证 MOSAIC 的动作说明原样透传。
- **MOSAIC 作 AIJADE 的舞台**：对照与五个方案见 [STAGE-MOSAIC](STAGE-MOSAIC.md)。现有渲染器契约只能做表情与头部姿态（发送端是第 4 章的研究对象，只能调用，不能修改）；走路、坐下要经 MOSAIC 工作台的文字指令（方案 A），待作者决定。
