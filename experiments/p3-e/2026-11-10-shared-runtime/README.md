# P3-E：新版共享运行时的完整 LoCoMo 测量

方案先于本轮装置扩展，独立提交为 `d1527e01d19c7e5524a0afa3f003d741a9d131a6`，见 `experiments/plans/2026-11-10-p3-e-shared-runtime.md`。用户本轮明确授权 Mac 完整测量；不推断导师收件、批准或外部预注册。产品基线为 `d9dcf6bdc928f822e7a2fc3bf4e2cb00a36ebade`，研究内核、运行时、冻结记忆文件与历史实验均不改。

当前阶段：装置编译及定向资格已通过，完整语料结果尚待运行后填入。定向 14 通过，1 项正式语料测试按条件跳过；包含真实 API／数据库的合成观察器边界及嵌入响应记录器的成功／失败断言。实际本地 nomic 服务的合成请求返回 768 维，模型 digest 与方案一致。

接下来依方案运行文本和嵌入两条件，各自覆盖全部 10 段对话、1,986 个问题。入口为仅开启记忆的新版共享运行时、每题空历史，不包含完整 Web／QQ、多轮、生活模块、问题回写或主动消息。语料完整覆盖与产品功能完整覆盖分别说明。逐题观测、实际嵌入响应和存储快照留存，长文件可无损压缩；原 v1 文件和分析器不覆盖。

LoCoMo 来源：Adyasha Maharana、Dong-Ho Lee、Sergey Tulyakov、Mohit Bansal、Francesco Barbieri、Yuwei Fang，*Evaluating Very Long-Term Conversational Memory of LLM Agents*（ACL 2024），原数据与代码为 https://github.com/snap-research/locomo 。含语料原文的存储快照、实际提示和传输记录是本研究的格式投影／观测制品；这些内容沿用原始 CC BY-NC 4.0 条件，原许可证保存在 `LOCOMO-LICENSE.txt`，不以本项目的源码许可重新授权。聚合计数、装置代码和分析脚本各按其标注处理；模型文件未随包发布。
