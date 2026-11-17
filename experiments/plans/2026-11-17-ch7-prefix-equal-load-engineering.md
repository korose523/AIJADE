# E4 工程等负载验证固定方案：前缀核验优化后的完整 360+2 tick

状态：ENGINEERING_PROTOCOL_FIXED_BEFORE_MEASUREMENT。源码、具体argv、输出目录与各项SHA由独立的活动工程passport绑定到实际提交，并在首个控制器启动前公开；本文件不能单独启动。analysis下原始DRAFT和所有静态审查继续保留。工程运行不重开任何已消耗的科学资格窗口。

## 问题、边界与固定顺序

既有 Q3 `0c42cc29c64730131466af6b079a900005713cba` / B3 `efbcfa0196cbc69bd24cad5b03f01b5078898b7b` 在唯一600秒静置窗口内留下294条连续原始记录，293条流式核验通过；最后一条完成时间600.336714976秒超过固定终点。20条已知条件均未尝试，未开始admission、业务flow、renderer、模型或留出构造。旧结论与全部旧资料保持原样。

本轮顺序固定为：优化在线成本增长 → 冻结E4工程代码和协议 → 完整工程等负载及独立全回放 → 冻结新的前瞻科学资格P4/Q4/B4 → 唯一完整已知输入资格 → 仅在独立资格接受后导出一次seed并执行已确认40对。E4成功只说明本冻结实现完成了工程负载，不授予后端、硬件、产品、人工作者核读或留出资格。

## 工程运行前的冻结清单

Root须填齐passport.freeze：工程决定的commit/path/SHA；实际clean实现commit与repository；runner/launcher路径与SHA；Python/psutil、native helper及C源、identity-ready shim、lsof及策略身份；全部原14项与新增传递依赖源码SHA；独立参考一致性与所有负控收据；唯一输出/temp/packet路径；预检实际有限任务数量；磁盘预算和最少余量；准确exec argv。所有路径与新文件均在AIJADE下，复用已安装运行时，不临时下载组件。

开始前独立核对源码工作树、实际Git blob、policy原字节与对应实现、native/source/shim/daemon/listener/API契约、冻结参数及输出不存在。先结束其它build/test/PDF/压缩/复制任务；不为获得PASS终止无关应用、不重启或调优原Colima两CPU/两GiB服务。进度由持续父控制器输出，窗口中不新增轮询辅助进程。已有19.8GiB APFS卷只余约5GiB的库存不能写成剩余20GiB；冻结时须重新读取实际余量，确保新工作树/构建/原始日志/压缩副本及余量的峰值预算可共存。不得静默删除旧失败或历史包。

## 固定负载与时钟

| 阶段 | globalIndex | 名义时刻（相对同一origin） | 观测数 | owned roots |
|---|---:|---:|---:|---|
| settling | 0–299 | 0,2,…,598秒 | 300 | 空；ownedProcesses也为空 |
| admission-like | 300–359 | 600,602,…,718秒 | 60 | 空；ownedProcesses也为空 |
| engineering tail | 360–361 | 720,722秒 | 2 | 仅已注册同一controller PID/出生身份 |

共362条全部必须PASS。每条均有真实before/after native capture、before/after listener有限任务、直接loopback `/api/ps` 显式 `{models:[]}`、guard内核验和外层独立核验以及完整raw/event回调。包括tail在内为724次native、724个listener有限任务、362次API读取、724次在线判定、1448个观测有限任务；预检另外固定30个真实source-proof Git有限任务，完整命令列表与执行顺序必须在运行前冻结；包括原观测负载共1478个有限任务。数量、真实launch/read/wait工作量与旧30等量，不声称逐条argv完全相同；新列表未实际执行前不写成运行事实。历史4322-event合成脚本不含完整实时native/API/写盘负载，不能替代本运行。

单一实际monotonic origin，所有名义目标始终为origin+index×2；不因上一样本、phase实际进入或线程创建重置网格。settling的deadline是实际origin+600；admission-like的实际进入时间另测，deadline仍按原语义actualEntry+120，不能把计划600倒填成actualEntry。实际phase exit/entry分别测量。tail等待前一phase真实结束，但目标仍为origin+720/+722，固定最终deadline为origin+724，不将迟入补成新的四秒窗口。保留原helper的actualEntry+120 phaseClock，同时在E4外层对后段所有sample和完整service加更严格绝对上限origin+720；settling上限origin+600，tail上限origin+724。真实phase exit/entry本身不得倒填。

无slot遗漏、替换、补录、扩窗或择优子段。保留原phase end三秒容差，但每条采集、两次验证、raw/event回调及每tick记账必须在所属固定deadline内完成。全局相邻实际starts严格递增且差≤3秒，跨settling→admission-like及idle→tail均包括。每tick start lateness必须在0至0.5秒；完整service≤2秒是新增且预先固定的更严格工程门槛，不替换原whole-observation≤2.5秒。native/API/listener调用各≤0.5秒，协调锁等待≤1.25秒，原大小/增长/未知拒用语义保持。

后段仍检查每次available≥4GiB及swap-used范围≤64MiB。tail实际自有controller RSS须为从raw重建的已知非负整数；UNKNOWN不能填零。原运行期RSS/available/swap连续30秒界限保留，但两个tail样本不证明长时间压力承受能力，不能据此声称已验证30秒持续边界。

## 推荐运行器与精确复用边界

新增独立、源码绑定的工程runner，tracked路径为 `experiments/ch7/run_equal_load.py`；不能调用 `run_finite_sequence.execute/_execute`，该入口在admission通过后会进入已知病例flow。也不调用case/input/seed/renderer/SQL入口。

1. 打开唯一新目录和所有日志；以 `Registry(..., roots=[self PID/birth], stage='engineering-prefix-e4', source_commit=Qe, policy_sha256=Pe, capture_lock_path=guard.coordination_lock_path(policy)).activate()` 建立同一controller的scope。在窗口前完成已固定30项、仍被真实登记、等待和审计的source-proof Git预检；不是30个无效空命令或虚构lease。
2. 用优化后的实际guard及 `load_mac_policy` 的等价源码闭包检查，保留每次真实source/policy/native身份与原raw规则。采样适配器仿现有 `observed` 返回utc、availableBytes、swapUsedBytes、processObservation、raw重建RSS及source身份；不提前填controller拥有的monotonic或validation字段。
3. 复用 `phase_continuity.run_preflight(sampler_unloaded, outer_validator, writers, event_writer=..., settling_seconds=600, service_observer=...)` 的冻结工程扩展。新增optional service_observer接收raw与完整event callback返回后由调用者实际读取的clock，只在memory记录completion和检查阈值，不做I/O；旧默认调用与原27控制必须保留。sampler的roots严格为空。writer仅write+flush；lifecycle append保留fsync。不能把claim PASS/RSS当作外层验证结果，也不能把writer Registry的可变state直接借给独立验证会话。
4. run_preflight返回后不做全量回放、压缩、Git扫描或大收据写盘。将原schedule.origin、lastSample和runtimeHandoffAnchor交给同一controller内的固定两次observer线程。此工程tail适配器只在720/722目标运行两次，沿用真实捕获/两次核验/写回逻辑；不得直接使用当前MacMonitor的 `deadline=time.monotonic()`，因为它会用线程实际起点重设调度网格。复用其采样、raw检查与handoff约束，但冻结一个可接absolute origin、exact targets与count=2的工程适配入口。
5. tail记录相同controller身份、真实observer-thread移交时间及完整roots。第360条actual start减idle第359条actual start≤3秒；第361条与第360条同样≤3秒。不能用handoff占位时间代替第一条真正raw start。
6. 完成固定tail后停止并join该线程，记录stop结果；`Registry.final()` 本身核对已有handle parent wait、scope和账本状态，不增加native capture。最终scope close及全部已知身份处置必须留原记录。允许受控父进程在controller退出后，只对已记录PID/出生身份作一次只读absence查询；不能称全机历史clean。
7. 之后才运行从第一个字节开始的完整独立cold audit，构建manifest和无损压缩包。严禁窗口内动态选择成功前缀、自动重启或在结果失败后生成cases。任何负载/写回/退出异常保留partial raw、sentinel、sidecar与terminal refusal。

固定工程输出布局为 `settling/telemetry.jsonl`、`admission/telemetry.jsonl`、`tail/telemetry.jsonl`、`phase-events.jsonl`、`tail/events.jsonl`、`service-events.jsonl`、`lifecycle-journal.jsonl`、`process-policy.json`、`preflight-continuity.json`、`receipt.json`。phase-events只保留原360条idle采样对应的全部原序phase事件，不能在审计时删记录；tail的独立事件完整保留于 `tail/events.jsonl`，schema为 `aijade.ch7.equal-load-tail-event.v1`。tail raw与service-events明确phase=tail，含义始终仅工程。执行passport由Root另在C4/engineering-01-passport.json实际冻结，不使用本analysis草稿启动。

## 完整计时与写回证据

每条保留scheduled/start/observationCompleted/validatorStart/validatorCompleted/raw writerStart/raw writerCompleted、event callbackStart/callbackCompleted和serviceCompleted。完整service从外层actual sample start计到捕获、两次核验、raw/event回调与约定每tick记账返回；新增成本记录的写回也属于负载，不在测量后偷偷排除。event完成时间在回调真实返回后读取并写入独立cost trace；不能把sample-written事件内的raw-writer完成时间冒称该事件自身callback完成。辅助service-record写入的完成时间在真实写入返回后测量，由wrapper的最终receipt逐sample绑定保存；它不能自举放进同一条尚未完成的写回。更外层实际完成检查仍覆盖它，不能只用下一start猜测或省略最后一条，最终runner精确字段需与独立auditor共同冻结。

有限任务补记attempt start、ready、parent-held gate下真实kernel出生身份、register、release、reap与WAIT事件时刻。不把native内部clock的绝对原点与Python比较，只比较其内部duration。raw/event现行write+flush不是每条fsync，不声称物理介质持久化；lifecycle每条fsync原样保留。所有压缩保留原字节和logical SHA/size。

报告全362及各阶段/首末四分段的每段n/min/median/p95/max、journal bytes/events、prefix读取/比较/hash/解析/投影成本、锁等待、native包装与C内部、API/listener、两次核验、raw/event写入、service及lateness。它们是本次描述性工程数据；tick不是独立设备复现，相关增长不等于毫秒因果归因。

## 优化安全与控制复用

最小改动先只优化验证侧历史JSON/状态重复replay，仍对每次实际旧前缀字节做exact认证。独立session绑定run/source/policy/scope/controller PID/birth及流；所有新tail事务性验证后再发布；快照不与未来WAIT/SCOPE_CLOSE共享可变容器。两条在线校验链仍分别重判每条native/API/RSS，不缓存整条PASS。fstat/inode/size/mtime、claimed SHA、advisory锁不能代替旧字节认证。删除旧前缀扫描需要另一个不可改片段/认证append协议方案，不是本E4默认。

必须复用并保持原phase27、continuity、journal/prefix/raw/refused、guard/native、process lifecycle及adapter控制；新增warm-cache旧byte同长改写且恢复mtime、coherent历史重写、截断/回退/同字节文件替换、部分tail事务失败、返回快照外部篡改、跨run/scope/controller缓存串用、future WAIT修旧cutoff、旧native重用/API/RSS篡改负控。每个负控先证明完整baseline可接受；优化结果与保留cold reference逐prefix/分块边界/状态/RSS一致。旧294条拒用仍须原样拒用。已有19种真实block corruption规则保持，实际新资格若进入flow后仍须对真实完整block执行；E4不能伪造出一个live-block baseline。

## 接受、归档和后续科学门槛

E4接受必须同时满足：362条全部原始与两次判定PASS；300/60/2人口及序号、固定网格/截止/迟滞/service/3秒连续性；所有真实native/API/listener和生命周期身份闭合；无unknown RSS、未处置scope或失败sidecar；冷参考一致性与全raw/journal独立重放；完整physical/logical manifest；只发生冻结允许的工程操作。外层status仅用ENGINEERING_EQUAL_LOAD_PASS/REFUSED，stage名称admission只为复用原phase schema，不表示科学admission已执行。

无论E4结果如何，backendQualification、hardwareQualification、heldoutComplete、humanReview、authorApproval均false，table7_3=NOT_RUN，fresh cases/seed/I=0。Root在完整E4接受后再单独冻结科学P4/Q4/B4，不复用P3的已消耗资格许可。若工程后再改运行时依赖，必须重新核对相同负载是否仍对最终实现成立；不能把旧工程PASS借给新源码。

## 候选运行器接口与静态审查边界

候选C4/run_equal_load.py的实际passport schema为 `aijade.ch7.equal-load-passport.v1`，当前字段为repo/output/sourceCommit/runnerSha256/sourceFiles/policyPath/policySha256/observerSources/preflightCommands；每条预检命令有arguments和stdoutSha256。receipt schema为 `aijade.ch7.equal-load-result.v1`。本analysis草稿不属于活动passport。

service-events保存诊断写入前实际取得的sampleId/globalIndex/phase/scheduledMonotonic/deadlineMonotonic/sampleStartedMonotonic/callbackStartedMonotonic/phaseEventWriteCompletedMonotonic/startLatenessSeconds；receipt.services延伸绑定同一条的diagnosticWriteCompletedMonotonic/callbackCompletedMonotonic/serviceCompletedMonotonic/fullServiceSeconds。该completion在完整event callback返回后读取，须覆盖诊断write+flush和该callback全部必做工作。最终字段以冻结源码为准，并由独立auditor逐字段核验。最新版候选的Registry前Git命令已移除；30项managed命令承担HEAD/status与28项source-proof，sourceFiles有28条、observerSources有14条。命令列表与实际输出SHA须另冻结，不能把bootstrap进程隐去。

已实际只读核对候选SHA `430c3d2891c9886b36668e9b65b1c081fb8943b9414d5939b7c10789286aaceb`：tail拒用原raw保存、final未知拒用、完整callback后clock、362唯一ID、raw_rows及时pop及移除Registry前Git均已见修正。该SHA只是被审候选，不是E最终冻结身份。尚须明确失败边界：tail线程若在固定join预算后仍存活，顶层必须REFUSED，不能在可能继续append的线程旁宣称journal稳定关闭；父launcher的有限自有controller终止/等待/证据协议需冻结。本审查不是执行证据。


Frozen executable contract
--------------------------
+
The executable implementation is `experiments/ch7/run_equal_load.py`. Its separate
passport binds the exact committed source tree, this plan, the policy, the 28
source proofs, 30 actual managed Git commands, Python/psutil, parent launcher and
output before the first controller launch. The draft passport is nonexecutable.
The exact engineering passport is separately published before measurement; it
does not reopen any consumed scientific qualification plan.

Every 300+60 idle sample uses the original phase controller. The controller's
optional `service_observer` receives an actual clock immediately after the full
event callback has returned. That callback includes the raw event write and the
service diagnostic write with flush. The observer only records memory fields and
checks the frozen engineering limits. Its completion witness is retained in the
terminal receipt; a row cannot contain its own future write-completion clock.
Tail events are stored separately in `tail/events.jsonl`. The two tail samples
are called by one actual observer thread after the real idle phase exit, at the
unchanged global targets origin+720 and origin+722. Its first join deadline is
origin+727; a failure is immediately adverse, with at most ten further seconds
for cleanup only. An active thread forbids stable-final/close claims. The exact
owned parent watchdog waits at most 850 seconds and may terminate only the
freshly created, birth-bound controller's own process group, retaining actual
parent wait and unresolved cleanup status. No timeout can extend a measurement
phase or authorize a replacement attempt.

`ENGINEERING_EQUAL_LOAD_PASS` requires all 362 unique original observations, the
300/60 populations, actual callback-return service <=2 seconds, absolute start
lateness <=0.5 seconds, whole observation <=2.5 seconds, all original helper/API/
lock limits, actual adjacent starts <=3 seconds, service deadlines at origin+600,
origin+720 and origin+724, resource limits, 1,478 exact finite register/release/
parent-wait chains, an absent-and-closed final registry, a joined thread, and a
separate complete cold replay. Scope flags remain false for scientific admission,
backend qualification, formal hardware qualification and independent human
review; scientific flows, models, rendering and fresh heldout cases remain zero.

The old-prefix read/comparison barrier and full detached snapshots remain
proportional to history size. This engineering change reduces repeated parsing
and hashing; it does not claim constant complexity or causal attribution of the
entire historical delay to a single implementation detail.

Procedural assistance used the installed Scientific Agent Skills experimental
design guidance and existing author materials, with all interpretations explicitly
AI-assisted. Software reference, checked against the current arXiv record on
2026-11-17: T. Kassis, V. Agarwal, Y. He, D. Patel and A. M. Brueckner,
"Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents,"
2026, https://doi.org/10.48550/arXiv.2609.00065. This cites workflow assistance;
it is not empirical support for AIJADE's qualification or performance.
