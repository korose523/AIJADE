# Mac bulk census 唯一尝试的独立终止审计

本轮审计接受的是终止记录的完整性，不是后端资格。Q 为 `d96152b98f61e3cb47db9ec3d95e00591830d024`，B 为 `a20f090423548dedbf1337ec50786daa9e2d028a`。原尝试没有重启，没有产生新 seed、40 对留出输入或新实验结果。

完整重放了600.0026361839846秒静置的300个PASS观测、120.00541552799405秒准入的60个PASS观测，以及运行阶段7个PASS与1个FAIL；另有1条原始 observationError sentinel。736个 before/after native response 从其完整原始字节重新解析，368份 `/api/ps` 原始响应均明确为 `{"models":[]}`，没有用摘要或状态布尔值替代证据。

控制器的准入记录是 `ADMITTED`，但静置结束到准入开始有3.6311725030245725秒缺口。Q 的 `finite_sequence_audit._admission` 明确要求 `0 <= start - settling_end <= 3`；本轮因此不能通过独立全序列准入连续性审计。各阶段内样本最多间隔分别为2.0092260930105112秒和2.0092026450147387秒，不能将阶段内覆盖通过写成阶段之间连续。

运行15.20738540100865秒后停止。最后一帧 after 原始图缺少一个此前登记的root，RSS读取返回UNKNOWN，ownedProcesses为空，ownedRssBytes为null。Q v2在一个root缺失时令整个成员集合为空，继而给两个仍在原始图中、PID/创建时间/parent均未改变的controller生成 `OWNED_PROCESS_REPARENTED_OUTSIDE_CLOSURE` FAIL标签。原始FAIL和标签必须保留；这些标签本身不能证明两个controller发生了真实reparent，不能据此修成PASS或把未知RSS当成0。

唯一block子controller确曾启动，最终退出码-15；`block-1-controller.log` 为0字节，`block-1`输出目录不存在，没有case轨迹、flow、renderer或数据库lease文件。结合Q中创建输出目录先于flow/renderer/lease操作的顺序，可以单独标为“未达到这些步骤”的推断；category为other的进程图不是Git身份认证，也不是完整OS执行历史。原receipt中的20个unknown条件记录原样保留，不能改成unattempted或零分。

原331项受保护源码、旧85项拒用packet的physical/logical字节、旧relocation归档与12,311项facts baseline逐项保全。实际576项.NET构建文件和当前native helper在终止后只读重算SHA，均与B一致，程序集含Q；离线CI可以核对该后验观测回执与B绑定，不能称为CI重读了原Mac现场二进制。独立psutil只读证明19个本次已记录owned身份均已不存在，原2-controller退出回执与root的11-known身份回执也同时保留；这不证明从未采到的子进程历史或全机clean。

完整工程记录包括128项source-bound Python controls、source CI成功、实际used默认684Passed/29NotExecuted及浏览器38NotExecuted，未使用的首轮663Passed/21Failed/29NotExecuted及浏览器38NotExecuted，原8候选与12placement控制，以及中间native、timeout、fortify fixture失败与最终修复。第一轮外置artifact root失败没有被隐藏，也没有用于资格。未保全中间C源码的早期native编译元数据不能被宣传为可复现源码版本。

正式硬件资格、完整finite driver、40对留出比较、独立人工审阅和产品继承资格均保持false；表7.3保持NOT_RUN。归档和审计不构成新的执行授权。
