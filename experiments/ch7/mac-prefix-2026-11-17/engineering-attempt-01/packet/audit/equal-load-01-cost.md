# 工程等负载 engineering-01：10条记录的只读成本分解

结果仍为 **ENGINEERING_EQUAL_LOAD_REFUSED**。本分析没有编辑源码、重跑窗口、调用 observer/native/API、运行 dummy 或启动 Python 性能探针。仅处理原始记录，并核对冻结源码和本地标准库说明。

源码为 `b5af85f7a1b5f1da3ceeda0a9c1a64393a0e3efb`，passport SHA `5755e4942768002eed52762a432c947bc6279ac945fcc8d7f9d0bb579da939e2`。保留10条连续raw，9条被阶段控制器完整接受；第9号样本的完整service为2.042617058秒，超过事前2秒工程门槛，callback拒用。10条raw内进程判据和外层streamValidationStatus均为PASS，第10条仍在callback拒用前原样写出，不能据此声称阶段已接受10条。其guard whole observation为2.007219576秒，低于另设的2.5秒上限。没有开始科学资格、admission、业务flow、renderer、模型或新留出构造。

## 十条实际时间

下表除prefix bytes外均为毫秒。两次native wrapper与C内部duration是嵌套统计，不再加入full service求和；原C绝对时钟不与Python绝对时钟比较。

| index | full service | guard whole | 两次native wrapper | 两次C内部 | post-unlock guard | outer validator | raw writer | journal bytes |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 | 1885.153 | 1841.531 | 390.732 | 2.456 | 51.704 | 33.282 | 8.777 | 86050 |
| 1 | 1843.575 | 1820.045 | 378.769 | 2.183 | 38.194 | 20.030 | 3.162 | 95978 |
| 2 | 1832.116 | 1796.404 | 374.398 | 2.463 | 37.846 | 30.085 | 5.260 | 105905 |
| 3 | 1896.827 | 1863.221 | 397.221 | 3.194 | 43.417 | 28.120 | 5.179 | 115834 |
| 4 | 1871.744 | 1839.345 | 382.440 | 2.686 | 41.751 | 24.377 | 7.635 | 125759 |
| 5 | 1931.272 | 1898.452 | 418.574 | 2.913 | 42.870 | 29.110 | 3.363 | 135686 |
| 6 | 1844.629 | 1813.757 | 389.800 | 3.025 | 47.088 | 26.681 | 3.524 | 145615 |
| 7 | 1893.570 | 1859.822 | 382.645 | 3.258 | 39.961 | 26.431 | 6.844 | 155541 |
| 8 | 1917.678 | 1884.726 | 426.706 | 2.834 | 50.347 | 24.821 | 7.692 | 165465 |
| 9 | 2042.617 | 2007.220 | 422.157 | 3.573 | 47.179 | 30.933 | 4.050 | 175393 |

## 真正已观测到的主要区间

以下为从outer sample start到callback真实返回的互不重叠区间均值。完整逐样本边界、所有小区间与逐40个finite task记录保存在JSON；每条分解之和已与原fullServiceSeconds核对。

| 区间 | 平均毫秒 | 占full service均值 |
|---|---:|---:|
| beforeGraphCompletedToListenerReadyMixed | 558.113 | 29.44% |
| afterGraphCompletedToListenerReadyMixed | 557.597 | 29.41% |
| afterGraphEnvelope | 212.931 | 11.23% |
| beforeGraphEnvelope | 207.664 | 10.95% |
| beforeListenerReadyToReapedField | 128.119 | 6.76% |
| afterListenerReadyToReapedField | 121.268 | 6.40% |
| postUnlockGuard | 44.036 | 2.32% |
| outerValidation | 27.387 | 1.44% |
| sampleStartToBeforeGraphStart | 17.209 | 0.91% |
| afterReapedFieldToCoordinationUnlock | 7.516 | 0.40% |
| beforeReapedToAfterGraphStartExcludingApi | 5.748 | 0.30% |
| rawWriter | 5.549 | 0.29% |
| apiRecordedDuration | 2.279 | 0.12% |
| guardReturnToSamplerCompleted | 0.270 | 0.01% |
| diagnosticEntryBuildAndWrite | 0.113 | 0.01% |
| phaseEventWrite | 0.061 | 0.00% |
| rawWriterCompletedToEventCallbackStart | 0.032 | 0.00% |
| samplerCompletedToOuterValidatorStart | 0.014 | 0.00% |
| outerValidationCompletedToRawWriterStart | 0.008 | 0.00% |
| callbackPostDiagnosticTail | 0.006 | 0.00% |

最大混合区间是两次graph-complete至listener-ready，平均合计1.115709秒，占平均service的58.85%。冻结代码在这里重新解析native证据、读取daemon精确身份并完整认证可执行文件，然后准备和启动listener的Python ready shim。当前记录没有这些子操作的独立起止，不能将该区间全叫site启动、全叫daemon哈希或全叫fsync。

两次native graph/managed wrapper也有固定开销。C自己保存的内部采集／序列化clock duration合计只有毫秒级；Python wrapper还包含ready启动、内核身份确认、REGISTER/RELEASE/WAIT、管道、实际wait、清理与C执行，不能将约0.4秒包装时间写成C纯耗时。

后unlock guard含remember、sample快照和inner验证；outer validator另行重判；raw、phase-event、diagnostic输出也分别有真实时钟。本次10条中这些区间比最大的混合区间小。首条post-unlock和outer核验均不比末条低，不能据此将失败归因于前缀线性增长。

## 第9号与第0号的算术差分

该表仅分解首末观测差异，不能解释因果。

| 区间 | 末条减首条毫秒 |
|---|---:|
| beforeGraphCompletedToListenerReadyMixed | 102.634 |
| afterGraphCompletedToListenerReadyMixed | 24.790 |
| afterGraphEnvelope | 16.135 |
| beforeListenerReadyToReapedField | 15.208 |
| beforeGraphEnvelope | 10.377 |
| apiRecordedDuration | -10.278 |
| afterListenerReadyToReapedField | 5.197 |
| rawWriter | -4.727 |
| postUnlockGuard | -4.525 |
| afterReapedFieldToCoordinationUnlock | 4.177 |
| outerValidation | -2.350 |
| beforeReapedToAfterGraphStartExcludingApi | 1.064 |
| sampleStartToBeforeGraphStart | 0.917 |
| diagnosticEntryBuildAndWrite | -0.693 |
| guardReturnToSamplerCompleted | -0.442 |
| rawWriterCompletedToEventCallbackStart | -0.009 |
| callbackPostDiagnosticTail | -0.005 |
| samplerCompletedToOuterValidatorStart | -0.004 |
| phaseEventWrite | -0.002 |
| outerValidationCompletedToRawWriterStart | -0.000 |

## 生命周期时钟能证明与不能证明的成本

完整journal有213个事件：70次FINITE_REGISTER、70次RELEASE、70次WAIT，加controller/scope事件。70个直接任务包括30个实际预检Git任务和40个观测任务；其实际父wait均为0。每个观测有before-native、before-listener、after-native、after-listener四个直接finite任务。

成功launch没有保留独立parent launch-start时钟。native的graphStarted到ready只是启动成本上包络；listener的graphCompleted到ready还含daemon哈希等前置步骤。ready到REGISTER、REGISTER到RELEASE、RELEASE到reaped字段和reaped到WAIT事件可直接差分，但不是单操作耗时。事件monotonic在写入／fsync之前记录，REGISTER→RELEASE等区间包含前一个append/fsync及下一个append准备。Popen.wait返回后还先做Registry._lease查找才采样reapedMonotonic，因此该字段也不是内核reap的精确瞬间。没有单独fsync或纯target运行时间。

| 40个观测finite任务包络 | min ms | median ms | mean ms | max ms |
|---|---:|---:|---:|---:|
| readyToRegisterSeconds | 4.738 | 7.128 | 7.455 | 12.679 |
| registerToReleaseEventSeconds | 2.348 | 4.131 | 4.490 | 8.986 |
| releaseEventToReapedFieldSeconds | 10.931 | 62.475 | 64.867 | 129.134 |
| reapedFieldToWaitEventSeconds | 1.472 | 2.359 | 2.603 | 5.260 |

## daemon文件认证候选

冻结 `_read_identity` 对app和serve的每次读取都调用完整 `_file_sha`；每个样本before/after各做一次。诊断只stat已绑定路径，当前大小为59,795,424和78,301,616字节，源码意味着每tick约276,194,080字节daemon内容认证。这说明存在实质固定工作量，但没有各SHA的单独实测时间，不能据此指定毫秒因果贡献。不可用仅stat/inode/mtime缓存取代原完整内容认证。

## stdlib-only shim与 `-S -B` 的潜在方案

实际shim已经只导入json/os/sys/time，不导入psutil。当前父launch为 `[sys.executable, "-B", shim, readyFD, gateFD, "--", target, *args]`。本地CPython3.12的site.py明确记载默认初始化会处理site路径、.pth及customize，`-S`抑制该过程。当前没有site导入成本或实际customize副作用的单独测量。

可以提出下一版仅将shim解释器前缀改为 `[sys.executable, "-S", "-B", shim, ...]` 的窄候选。保持最终 `os.execve(command[0], command, dict(os.environ))`、target argv和父传入env处理不变；不要把-S传给本来就是Python的target，不要全局设置PYTHONNOUSERSITE/PYTHONPATH。其可能收益为降低四次ready握手的固定解释器初始化，但幅度、变异和是否足以完成冻结全负载均UNKNOWN。最大的混合区间仍包含完整daemon认证，-S不会消除该工作量。

未检查继承环境中sitecustomize/usercustomize/.pth是否有环境副作用，所以不能只凭execve一行未改就断言有效环境完全等价。下一步应先用显式、非秘密的受控环境字典证明两种shim交给target的argv/env完全一致，保持同PID、parent、gate下两次出生身份、source/exec哈希、release、actualwait与失败清理拒绝。不得读取或输出实际credential环境来做比较。

上述候选与控制均NOT_RUN。本次不实施修改或探针，不形成第二个工程窗口或新科学资格计划。完整固定负载验证仍未完成。

## 解释界限与原始来源

本次是单台机器单个被拒用run的10条顺序记录，账本长度与时间共同变化。prefix仅覆盖86,050至175,393字节，不能以这段前缀推断完整账本成本或作因果增长拟合。cursor实际10次调用、各212个增量事件、0次旧跨scope冷回放，说明这段路径被调用，不证明未来全负载被接受。所有原始run文件和28项源码哈希已核对，写报告后再读原始输入哈希不变。

| 原始文件 | 字节 | SHA-256 |
|---|---:|---|
| `/Volumes/Untitled/AIJADE/.runtime/posix/runs/ch7-prefix-20261117/engineering-01/admission/telemetry.jsonl` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `/Volumes/Untitled/AIJADE/.runtime/posix/runs/ch7-prefix-20261117/engineering-01/engineering-passport.json` | 12919 | `5755e4942768002eed52762a432c947bc6279ac945fcc8d7f9d0bb579da939e2` |
| `/Volumes/Untitled/AIJADE/.runtime/posix/runs/ch7-prefix-20261117/engineering-01/lifecycle-journal.jsonl` | 175982 | `e2e26fda0a68357be70f88a5ab3120ce77bbeb03095701626e8646f7045eb8d2` |
| `/Volumes/Untitled/AIJADE/.runtime/posix/runs/ch7-prefix-20261117/engineering-01/phase-events.jsonl` | 4248 | `a746bbb9cd1c8501290df7b8c842753da6ffa06defefd0a55a9f66495eac9ff9` |
| `/Volumes/Untitled/AIJADE/.runtime/posix/runs/ch7-prefix-20261117/engineering-01/preflight-continuity.json` | 1558 | `abb98993ed5388f58c12c5eceff92e086e49d37976f36be871576742b5f8d400` |
| `/Volumes/Untitled/AIJADE/.runtime/posix/runs/ch7-prefix-20261117/engineering-01/process-policy.json` | 1814 | `e4972d319ef064237225f3d5906838d269d7cc0df008d847368517750dd80e32` |
| `/Volumes/Untitled/AIJADE/.runtime/posix/runs/ch7-prefix-20261117/engineering-01/receipt.json` | 135203 | `283009d667c22fd1d5811a877a8f8d7b004245ca7f2ac868670614773fb0a643` |
| `/Volumes/Untitled/AIJADE/.runtime/posix/runs/ch7-prefix-20261117/engineering-01/service-events.jsonl` | 3575 | `d7d85880fdb7943df9ca18ddcc07a811092dad03e5483c50502546e0a2ff453a` |
| `/Volumes/Untitled/AIJADE/.runtime/posix/runs/ch7-prefix-20261117/engineering-01/settling/telemetry.jsonl` | 4324360 | `e90ef7680dafb519901b236c113e7f66998bc96d0fd86aa61ead98c1117a9575` |
| `/Volumes/Untitled/AIJADE/.runtime/posix/runs/ch7-prefix-20261117/engineering-01/tail/events.jsonl` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `/Volumes/Untitled/AIJADE/.runtime/posix/runs/ch7-prefix-20261117/engineering-01/tail/telemetry.jsonl` | 0 | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |

完整源码身份与每条绝对时钟见JSON。报告只写成本分解，不代替独立全量终止审计、工程接受或科学资格判定。
