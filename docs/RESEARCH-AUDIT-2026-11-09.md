# 2026-11-09 导师意见与研究证据复核

作者要求对照 2026-11-03 审阅意见及结构图，继续补齐当前项目和论文缺口。本轮没有新的科学主运行；所有复核输出另存，未覆盖 `experiments/` 的研究记录、`experiments/plans/` 的冻结方案或 `configs/project-scope.json` 的冻结哈希。

## 实做的复核

- 三组第二主机归档候选（family、template-A、template-B）在 Mac 用既有 `sandbox-isolation` 驱动重放，各 7,200/7,200 与记录执行判定一致，总 21,600；新/共享参数对象的判定差异 0，读取时钟或随机数的候选 0。这是同候选执行重放，不是模型再生成或历史硬件无损的证明。
- `answerable-tables` 不调用模型地完整运行，751/751 历史全题集数值复现；与归档 `answerable`/`all` 结果块比较，1,712 个内容叶项相符（数值绝对容差 1e-9）；两项 `runtimeSeconds` 不同并单列。LoCoMo SHA-256 相符，原归档未覆盖。
- 从 P1-B 的逐条变异记录重算，分数/区间相符：漂移 0.4874 [0.4536, 0.5213]、晋升门 0.1188 [0.0951, 0.1475]。单读者分类仍为单读者，不因重算而成为独立审阅。
- 准入、漂移矩阵、晋升门、P1 端到端及外部渲染器现有回归共 11 通过、0 失败、0 跳过。

## P3-E 的版本边界

历史文本路径声明源码 `c40c46c231e2c8c92859a4916c755ce1f6bfd18a`，嵌入路径 `bbafb62891958b2c63f093b936537cd8c2e725cb`。`MemoryContext.cs` 与 `MemoryLibrary.cs` 两个冻结边界文件仍相同；当前 `Orchestrator.cs`、`Chat.razor`、`AppState.cs`、`CompanionBridge.cs` 四个相关文件已变。不能仅据两个文件未变，把旧 recall 数字当作当前 Web/QQ 版本测量，也不能仅据改动声称 recall 已变。

本轮工具比较列出的六个源码文件；历史结果只有声明提交，缺少独立绑定实际二进制的哈希。工具检查既不证明整个依赖树一致，也不补造该哈希。当前完整聊天路径的科学测量仍未完成。

```bash
python3 tools/audit_advisor_evidence.py --out /tmp/aijade-advisor-evidence.json
python3 tools/audit_advisor_evidence.py --out /tmp/aijade-advisor-current.json --require-current-version
python3 tools/audit_advisor_evidence.py --current-ref c40c46c231e2c8c92859a4916c755ce1f6bfd18a --out /tmp/aijade-advisor-archive.json --require-current-version
```

默认审计返回 0 表示冻结文件和重算一致；`--require-current-version` 当前返回 3 是预期的版本拒用，不表示检索性能下降。指定历史源码的比较返回 0 只表示所列文件匹配。脚本只读，不调用模型。

## 新资源事实与后续

作者确认无资助、主导项目和论文全部内容；CPU 在 2027 年 1 月前不能更换，其余工作在 Mac 完成。Mac 清点为 x86_64、4 物理核/8 逻辑线程、16 GiB RAM。现有 Ollama 0.40.6 的一次 1.5B `READY` 请求成功，运行状态 `size_vram=0`，模型随后卸载，临时服务停止。该短探针不证明 7B/8B/14B 正式设置可行，也不构成长期硬件资格。

原 P2-R `3f380be` 保留未执行；Mac 跨设备变更草稿在论文仓库另列。须核定设备资格、代表性模型容量/速度、确定性与跨环境解释。P2-A 仅静态筛查，P2-B 无正式大模型结果；P3-C 缺完整政策效应；第 7 章缺研究适配器、唯一技能状态权威和冻结后的新保留批次。产品角色/收藏同步及工程测试不关闭这些项。

上述资源探针是同日较早阶段的记录。随后完成的 7B/8B 固定请求开发预检及准入后复测见 [Mac 模型预检](MAC-MODEL-PREFLIGHT-2026-11-09.md)。本记录登记项目中可复核的证据，正式资格、主运行、发送和导师批准继续按各自真实记录判断。
