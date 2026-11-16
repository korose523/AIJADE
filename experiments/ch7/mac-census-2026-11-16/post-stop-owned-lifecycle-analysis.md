# Mac 批量进程观测方案停止后的只读诊断

本报告只分析 qualification-01 已保存的证据与冻结代码，未运行新的进程快照、资格窗口、renderer 或模型，未修改 Q、策略、原始记录，未发布任何内容。记录状态仍为 **STOPPED**，完成 **0 个 block、0/20 条条件记录**；20 条保留为 **UNKNOWN**，不是 unattempted。正式硬件资格仍为 false。

## 已完成的前置阶段与独立审计限制

静置回执为 `FIXED_SETTLING_COMPLETE_NO_ADMISSION_DECISION`，准入回执为 `ADMITTED`。逐行读取原始遥测得到：静置 300 个 PASS，准入 60 个 PASS，两个阶段的 ownedRoots/ownedProcesses 均为空；准入最低可用内存 7168843776 bytes，swap 范围 0 bytes，阶段内最大采样间隔 2.009202645014739 秒。

但静置结束 `138215.144676326` 到准入开始 `138218.775848829` 的空档为 **3.631172503024573 秒**，超过冻结 `finite_sequence_audit.py:394` 要求的 ≤3 秒。此处是对原始时间戳和冻结谓词的静态核对，不是完整独立审计已通过。`run_finite_sequence.py:99-111` 在静置 phase 返回后、准入开始前重新验证全部静置样本，可解释部分时延；没有分段计时，不能断言整个空档均由该重演造成。准入结束至序列 epoch 为 0.737594867998268 秒。

## 最后一次实际样本

文件有 9 行 JSON：**8 个实际样本，另 1 行错误 marker**。实际样本前 7 个 PASS，第 8 个在序列 t=14.010577935987s 为 FAIL。错误 marker 重复该时刻，不是第 9 个实际样本。

| 目标身份 | before | after | 可支持的结论 |
|---|---|---|---|
| 55469 / createTime 1794833067.305583 | ppid 55463 | ppid 55463 | 身份和父 PID 未变 |
| 57792 / createTime 1794833805.810615 | ppid 55469 | ppid 55469 | 身份和父 PID 未变 |
| 57825 / createTime 1794833813.907719 | ppid 57792，存在 | 本批次缺席 | 只支持该旧身份在 after 批次缺席 |

原始 native stdout 的 Base64 解码后 SHA256、字节数与记录相符；before/after 分别为 656/655 条，均 native status OK、一次成功读取、零错误，graph errors 为空。批量快照明确声明并非原子机器历史，因此没有推出精确退出时刻或干净退出。原生 CLOCK_MONOTONIC 的绝对值没有与 Python 时钟原点混同。

57825 在 t=8.010553936997894s 被识别为 owned descendant，之后 `OwnedRegistry.remember()` 将它加入 active，于下一个 tick 作为 required root；它不在 explicitlyRegisteredIdentities 中。最终两个阶段之间，before 的四条 owned RSS 均有值；after 在 `_owned_ids()` 先抛 ValueError 后，没有完成任何 owned RSS 行，聚合值保持 null。此处泛化错误名 `OWNED_PROCESS_RSS_UNKNOWN` 不能反推某个实际 RSS 读取必然失败。

## 连锁诊断的冻结代码路径

1. `finite_runtime.py:234-274` 将所有已观测 owned 身份记为 active，并在每 tick 将尚未被 live lookup 退休的身份都传为根。事前 lookup 不能保证短命 worker 在之后两个批次一直存在。
2. `mac_process_guard_v2.py:418-430` 中，一个根缺失即让 `_owned_ids()` 整组抛错；没有返回有效根的部分闭包。
3. `_snapshot():553-578` 将该 ValueError 记为通用 ownership/RSS unknown，after ownedProcesses 留空。
4. `validate_observation():650-652` 在闭包失败后使用 `members=set()`；`:686-696` 再将 before 中仍在 after 的稳定身份与空集合比较，输出 55469、57792 的 `OWNED_PROCESS_REPARENTED_OUTSIDE_CLOSURE`。该谓词没有要求真实 parentPid 发生变化。

因此，两条 reparent FAIL 是**闭包失效后的连锁标记**，不构成这两位控制器真实重新挂接的证据。原始 FAIL 标签、null RSS、停止结果全部保留；不能因此把本次改判为 PASS。

## 停止位置、身份与处置的边界

`block-1/` 和其 receipt 均不存在，`block-1-controller.log` 为 0 bytes。冻结 `run_finite_block.py:44-99` 在建立输出目录前核验 Git/repository/build/policy/input/protected sources，故这些事实与仍在输出前预检相符；无法定位具体指令。该代码阶段确实调用 Git，但 57825 的原始类别仅为 `other`，没有 executable/argv 证明，**不能将其确认为 Git**。最终 block controller 的 -15 是父控制器终止后的回执，不是 worker 57825 的退出码。

`run_finite_sequence.py:244-253` 在缺 block receipt 时以已启动 active controller 作为 flow_started 回退；`finite_runtime.py:375-393` 在无 journal 时保守给出 20 UNKNOWN。完成数 0、UNKNOWN 20、in-flight 0、unattempted 0 不应根据无目录而重标。最终身份登记为 ALL_NON_CONTROLLER_OWNED_IDENTITIES_ABSENT；57825 在 checkedMonotonic=138354.672995216 后被记为 ABSENT，仅证明清理阶段观测的旧身份缺席。

## 下轮可修复设计与必需负控（全部 NOT_RUN）

- **逐 tick 流式验证。** 将 phase-end 的全部样本重演移出下一固定阶段开始前的路径，仍测量并执行 ≤3 秒边界，不放宽 600/120 秒、采样数、缺测或超时规则；独立回放保留在整条尝试结束后。负控包括慢验证、漏边界样本、超 3 秒过渡。
- **区分持久控制器与已发现有限 worker。** 控制器保留显式 PID/createTime 必须存活租约；发现的后代保留历史身份台账，完整合法 bulk 中缺席可作为旧 worker 已不在图的证据。present+RSS 读取错误仍 UNKNOWN/null，不能归零；不完整 batch 不能证明退出；真实孤儿/重新挂接仍拒用。
- **带类型的部分闭包。** 返回 matched/missing/reused roots、diagnostic members、coverageComplete；不完整闭包仍不通过、完整聚合 RSS 仍 unknown；有效部分仅作诊断。负控必须保证缺一个 worker 不伪造稳定控制器 reparent，同时真实改父/逃逸仍被拒用。
- **显式阶段与子进程来源。** 给预检命令/driver 加 launch/exit 身份租约和 executable 证据，匿名 other 不能归因。覆盖缺 block journal 的 UNKNOWN、PID 复用、所需 controller 缺失、RSS 读取未知和诊断因果顺序。

以上仅设计与离线负控建议，**没有执行新测试、没有第二资格窗口，也没有从诊断推导新的执行授权**。不得据此填入正式留出结果或宣称硬件资格已建立。

证据绑定：Q `d96152b98f61e3cb47db9ec3d95e00591830d024`；B `a20f090423548dedbf1337ec50786daa9e2d028a`；plan `d8c5ed7cc58267571c5bdb1ee1cd1043eba9c6a3136f340677d69087575038b5`；policy `1c48614601b9b74c0da4fb6860848cba5a12ea0570f3053ddfa487e7036097f8`。本报告列示的 5 个代码文件逐字节匹配 Q；完整原始文件 SHA256、两帧目标记录、样本表与 NOT_RUN 设计见同名 JSON。
