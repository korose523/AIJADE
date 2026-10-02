# J1 变异/故障注入实验报告（mutation-report）

- git: `8185713b95fb6e3f80de0517f46c19be796cf3ab`
- 装置：内存 transform 注入，零生产代码磁盘改动
- baseline：531/531（failures=0）

## 检测率矩阵：注入 ID × 断言类别 → 由绿转红数 / 期望捕获数

| ID | 文件 | 类别 | 期望捕获 | 预测 | 观测 | 新红 | falseRed |
|---|---|---|---|---|---|---|---|
| FU-01 | `packages/memory-biomimetic/src/events.ts` | kernel | kernel | caught | caught | 1 | 0 |
| FU-02 | `packages/memory-biomimetic/src/events.ts` | kernel | kernel | caught | caught | 1 | 0 |
| FU-03 | `apps/server/src/routes/v9/schema.ts` | http | http | caught | caught | 1 | 0 |
| FU-04 | `apps/server/src/routes/v9/events.ts` | http | http | caught | caught | 97 | 51 |
| FU-05 | `apps/server/src/routes/v9/schema.ts` | http | http+no-write | caught | caught | 2 | 0 |
| FU-06 | `packages/memory-biomimetic/src/events.ts` | guard+kernel | guard+kernel | caught | caught | 21 | 19 |
| FU-07a | `apps/server/src/services/domain/v9-events.ts` | http+no-write | http+no-write | caught | survived | 0 | 0 |
| FU-07b | `apps/server/src/services/domain/v9-events.ts` | http+no-write | http+no-write | caught | caught | 3 | 0 |
| FU-08 | `apps/server/src/services/domain/v9-events.ts` | none | http | survived | survived | 0 | 0 |
| FU-09 | `apps/server/src/services/domain/v9-events.ts` | none | no-write | caught | caught | 2 | 0 |
| FU-10 | `apps/server/src/services/domain/v9-events.ts` | none | none | survived | survived | 0 | 0 |
| FU-11 | `apps/server/src/services/domain/v9-events.ts` | none | none | survived | survived | 0 | 0 |
| FU-12 | `apps/server/src/routes/v9/events.ts` | none | none | survived | survived | 0 | 0 |
| FU-13 | `packages/memory-biomimetic/src/events.ts` | none | none | survived | survived | 0 | 0 |
| FU-14 | `apps/server/src/services/domain/v9-events.ts` | http+no-write | http+no-write | caught | caught | 11 | 11 |
| FU-15 | `apps/server/src/services/domain/v9-events.ts` | none | none | survived | survived | 0 | 0 |
| FU-16 | `packages/memory-biomimetic/src/store.ts` | none | none | notImplemented | notImplemented | - | - |
| FU-17 | `apps/server/src/routes/v9/schema.ts` | none | none | survived | survived | 0 | 0 |
| FU-18 | `packages/memory-biomimetic/src/events.ts` | none | none | survived | survived | 0 | 0 |
| FU-19 | `packages/memory-biomimetic/src/events.ts` | none | none | notImplemented | notImplemented | - | - |

## 汇总

- 总变异体：20　已执行：18　捕获(caught)：9　存活(survived)：9　未实现(notImplemented)：2　等价(equivalent)：1
- **diffScore（检测率）= caught / (caught + survived) = 0.5**

## 存活 / 未实现变异（论文诚实检测边界）

- **FU-07a** [survived] (http+no-write)：删 validateLearningReference 内 render_ref 自引用 throw（learning 分支）：设计预测应翻红，但实测 survived —— 531 矩阵缺 'render_ref 自引用' 负例（fixtures 恒用合法 render_ref），该 throw 被移除后无断言落红。诚实边界⑤：learning 分支自引用守卫未被矩阵覆盖。
- **FU-08** [survived] (none)：删 applied_params_hash 不匹配 throw：矩阵无 '哈希不一致应被拒' 负例（fixtures 恒用 seed 哈希）→ 仍全绿。诚实边界①。
- **FU-10** [survived] (none)：projectionStatusOf 恒 'paired'：531 无 projection_status 断言（仅 E2E P1b 捕获）→ 仍全绿。诚实边界②。
- **FU-11** [survived] (none)：删 append-only 冲突 throw：531 无 '同 trace 二回执' 负例（仅 E2E N8 捕获）→ 仍全绿。诚实边界②。
- **FU-12** [survived] (none)：causality.inputHash 改常量：矩阵只查存在性、不查 '值↔内容' 一致；promotion 门复算提案自身 input_hash，中链不可见 → 仍全绿。诚实边界③（验证 c）。
- **FU-13** [survived] (none)：跳过 assertV10RequiredFields 的 causality 强制：531 无 'v10 topic 缺 tick/causality' 负例（仅 E2E N2/N3）→ 仍全绿。诚实边界③。
- **FU-15** [survived] (none)：拒绝路径也写 audit_log_entries：countRows（line 628-632）只数 events/render_traces 两表，第三表写入不被捕获 → 仍全绿。诚实边界④。
- **FU-16** [notImplemented] (none)：不可注入：531 矩阵走 drizzle/PGlite，模块图从未 import BioticMemory（store.ts），内存库写入完全不在观测域内；强制注入需构造 StorageAdapter（触及生产构造），故标记 notImplemented。
- **FU-17** [survived] (none)：删 tick 的 integer()（允许浮点）：531 无浮点 tick 负例 → 仍全绿。语义等价边界。
- **FU-18** [survived] (none)：仅改 envelopeSchema（不动 line 351）：真正判据是 topicEvent 的 strictObject，104 被遮蔽 → 改 104 不触发任何红。证明 '两处都定义严格性' 的遮蔽面（文档所述漂移形状）。
- **FU-19** [notImplemented] (none)：语义等价变异（注释/字段序改写）无可见锚点，注入不产生可观测差异，应在 diffScore 分母中排除；标记 notImplemented（equivalent）。
