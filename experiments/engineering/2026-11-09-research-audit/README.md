# 既有结果的一致性复核（2026-11-09）

本目录归档既有数据的执行重放与重算回执，实际运行日期和输入、工具、输出哈希保留在原 JSON 中。本次文档整理只补归档这些回执，没有重跑研究或改写原始结果。

| 检查 | 记录 | 已测范围 |
|---|---|---|
| 三组旧候选的 Mac 执行重放 | [mac-archive-replay.json](mac-archive-replay.json) | family、template-A、template-B 各 7,200/7,200 判定相符，共 21,600；新／共享参数对象判定差为 0 |
| P3 确定性表重算 | [p3-l2-repeatability.json](p3-l2-repeatability.json) | 751/751 历史全题值复现；可回答／全题两块 1,712 内容叶项一致，两项执行时间差异单列 |
| 来源、冻结边界及分数复核 | [evidence-audit.json](evidence-audit.json) | P1-B 漂移 0.4874 [0.4536, 0.5213]、晋升门 0.1188 [0.0951, 0.1475]；357 个存活项仍为单读者分类 |

这些检查验证既有记录的算式、执行和版本边界，不是 P2 模型再生成、历史硬件无损证明、独立团队复现或新的真实用户研究。后续模型调用另见 [Mac 开发预检](../../mac-preflight/2026-11-09-7b8b/README.md)。

## P3-E 的版本检查

历史文本路径声明源码 `c40c46c231e2c8c92859a4916c755ce1f6bfd18a`，嵌入路径声明 `bbafb62891958b2c63f093b936537cd8c2e725cb`。两个冻结边界文件相同，不等于当前完整产品路径与历史相同；聊天编排、页面、状态和机器人桥接已经变化。旧 recall 值不能直接当作当前 Web/QQ 的测量，也不能仅因改动就声称 recall 已变。

只读工具比较六个列出的源码文件。历史数据没有独立绑定实际二进制的哈希，源码匹配不补造该信息，也不验证完整依赖树。

```bash
python3 tools/audit_advisor_evidence.py --out /tmp/aijade-evidence.json
python3 tools/audit_advisor_evidence.py --out /tmp/aijade-current.json --require-current-version
python3 tools/audit_advisor_evidence.py --current-ref c40c46c231e2c8c92859a4916c755ce1f6bfd18a --out /tmp/aijade-archive.json --require-current-version
```

命令从仓库根目录运行。当前 `--require-current-version` 返回 3 是版本拒用，不能解读为性能下降；指定历史源码时返回 0 只表示所比较的文件相符。工具不调用模型，不修改归档。
