# 期刊论文的判读归属与版本边界复核

起点为 `cac86c10cf4afae6f06dacad195d2530a333a600`。本轮优先核对导师 11/03 的三篇稿件意见与当前证据，修改源稿并同步学位论文；没有改变产品运行时、配置、归档标签、测量驱动或原始研究结果，没有新增模型调用或研究样本。

作者 11/10 确认四类定性材料“全部 AI 辅助判读”。[qualitative-provenance.json](qualitative-provenance.json) 将这一说明绑定到原始文件的 SHA-256，原 JSON 中的历史读者表述仍保留。P1 的存活变异体分类、P2 的测试说明重评和验证器理由、P3 的排序代码调查都属于探索性 AI 辅助判读，没有已记录的独立人工编码或评阅者间验证。重新计算标签计数不能独立验证这些标签，来源核对也不能替代类别准确性验证。

现有只读审计器增加可选的归属清单输入，不增加服务或运行时模块。正常检查示例：

```bash
python3 tools/audit_advisor_evidence.py \
  --qualitative-provenance experiments/engineering/2026-11-10-journal-review/qualitative-provenance.json \
  --out /tmp/aijade-journal-provenance-check.json
```

原归档中的“first author”或“one reader”不再直接当作独立人工评阅证明。工具同时保留旧归属、实际输入哈希与本次更正。错误的期望指纹使检查返回 4；将历史 P3-E 指标套到当前产品源码的严格检查返回 3。预期拒用单独记为拒用，不计成科学实验的成功。

P1 未调整的变异分数与 P2 原执行标签仍是主要测量，AI 辅助类别支持的调整值保留为有条件敏感性分析。P3 结论同时保留小门控效应的多重比较、精确交互检验与 bootstrap 判据不同的决定，且没有隐去未复现的无惩罚增益。当前共享运行时与 QQ 交付改动不自动继承旧产品召回。

原有实验、运行时与配置文件逐字节保护，论文 9,878 项事实及源表中的事实占位符逐项比较。实际清单、检查返回码、原始 JSON 和构建日志见 [receipt.json](receipt.json)。这些检查不运行 P2 的正式 Mac 再生成、P3 的完整政策比较或第 7 章保留集检验，也不表示稿件已获导师或期刊批准。
