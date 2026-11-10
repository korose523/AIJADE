# 陪伴与“养鱼”开源参考目录

2026-11-10 检索“给大肥鱼完整且丰富的一生”“给大肥鱼完整的一生”“蓝色大肥鱼”“养鱼”，经 Exa 网页检索、B 站搜索与 GitHub 原始仓库交叉定位，检查 42 个候选，收录下列 **30 个不同仓库**。每项均读取固定提交的 README 与 LICENSE；其中 6 个仓库另抽样阅读关键源码。它们大多属于 DSH 或 AstrBot 同一生态，衍生关系见表，不能据此声称发现了 30 套独立架构。

这些是文档与源码抽样核对，**没有安装或运行任何第三方插件**，作者宣称的体验、测试数量、性格真实性与性能没有被本项目独立验证。项目代码与角色/图片/音色的许可分开检查，未导入第三方源码或素材。固定提交、文件哈希、检索路径、排除项及采用状态见 [机器可读目录](../experiments/engineering/2026-11-10-life-architecture/references.json)。

## 🔎 30 个参考项目与取舍

| # | 项目与固定源码 | 代码许可 | 文档/抽样源码中可借鉴的设计 | AIJADE 的取舍 |
|---|---|---|---|---|
| 1 | [多数字生命实验 · deepseek-harness-digital-life](https://github.com/nefelibata5136-code/deepseek-harness-digital-life/tree/6c81c913fd837662b001f1fb88d59d78eb3d2164) | [MIT](https://github.com/nefelibata5136-code/deepseek-harness-digital-life/blob/6c81c913fd837662b001f1fb88d59d78eb3d2164/LICENSE) | 独立身份、生活 worker、私有空间与通信边界 | 采用身份与状态所有权的划分；多角色社会与跨 Agent 通信未接入 |
| 2 | [大肥鱼生活 · dsh-dafeiyu-life](https://github.com/minedalang/dsh-dafeiyu-life/tree/87b9e4ae6945ed517642b6a2a3353cadbfc654aa) | [MIT](https://github.com/minedalang/dsh-dafeiyu-life/blob/87b9e4ae6945ed517642b6a2a3353cadbfc654aa/LICENSE) | 工作/生活域、计划和可核对的动作回执 | 采用规则先判断、结果不确定时停止；自主平台活动未接入 |
| 3 | [dsh-fish · dsh-fish](https://github.com/ssamurias/dsh-fish/tree/b2db80cbac0cd546fa5777fdb80e029c458c45db) | [MIT](https://github.com/ssamurias/dsh-fish/blob/b2db80cbac0cd546fa5777fdb80e029c458c45db/LICENSE) | 持续性格、记忆、唤醒和消息来源区分 | 借鉴用户消息与系统活动分开；不采纳意识或人格真实性的宣称 |
| 4 | [养鱼 · dsh-yangyu](https://github.com/YKY0521/dsh-yangyu/tree/8d58e7c3aeb68d2b46f1d913f4891c388da65923) | [MIT](https://github.com/YKY0521/dsh-yangyu/blob/8d58e7c3aeb68d2b46f1d913f4891c388da65923/LICENSE) | 角色绑定、分角色记忆、配置和导出 | 沿用服务端账户/角色隔离；不新建一份本地权威角色数据 |
| 5 | [AuraLife · dsh-auralife](https://github.com/hsushjk/dsh-auralife/tree/64554d4cafbfb4322d4e6316390474799a268eab) | [MIT](https://github.com/hsushjk/dsh-auralife/blob/64554d4cafbfb4322d4e6316390474799a268eab/LICENSE) | 模块化记忆、虚拟生活和多模态器官 | 只参考模块划分；自动生成器官、自修改和激素模型未引入 |
| 6 | [大肥鱼世界 · dsh-fish-world](https://github.com/1838601405/dsh-fish-world/tree/d46c9110ce2d1bce933d3379e3c0173d4f748b72) | [GPL-3.0](https://github.com/1838601405/dsh-fish-world/blob/d46c9110ce2d1bce933d3379e3c0173d4f748b72/LICENSE) | 虚拟家、日记、地图和伴侣界面 | 参考功能分区；继续复用现有 UI，不引入第二套 Flutter 应用 |
| 7 | [dsh-companion · dsh-companion](https://github.com/yyh-001/dsh-companion/tree/787c8a0c4ed9a2dcae67e15544bfab0d69b219a3) | [MIT](https://github.com/yyh-001/dsh-companion/blob/787c8a0c4ed9a2dcae67e15544bfab0d69b219a3/LICENSE) | SOUL/USER/MEMORY 分工与持续陪伴 | 保留人设、用户状态与记忆各自来源；不将摘要自动覆盖作者人设 |
| 8 | [人格蒸馏 · dsh-persona-distill](https://github.com/Speraymer/dsh-persona-distill/tree/5b833119b1443b3298f25518bb7e0b96ccb8e421) | [MIT](https://github.com/Speraymer/dsh-persona-distill/blob/5b833119b1443b3298f25518bb7e0b96ccb8e421/LICENSE) | 手工人格段与自动整理段分开，独立蒸馏会话 | 采用可扩展但不混写的边界；本轮没有启用人格自动学习任务 |
| 9 | [鲸鱼娘皮肤 · dsh-deep-whale](https://github.com/Small-tailqwq/dsh-deep-whale/tree/d9bb4989c941d4d1d5cee1fa8388f2d14f0a771b) | [MIT](https://github.com/Small-tailqwq/dsh-deep-whale/blob/d9bb4989c941d4d1d5cee1fa8388f2d14f0a771b/LICENSE) | 主题皮肤与独立切换面板 | 表现资源与对话逻辑分开；未导入任何皮肤或立绘 |
| 10 | [dsh-pet · dsh-pet](https://github.com/PC2005-cloud/dsh-pet/tree/c25386848f70f6e40902e4376f6e7b1e196bc326) | [MIT](https://github.com/PC2005-cloud/dsh-pet/blob/c25386848f70f6e40902e4376f6e7b1e196bc326/LICENSE) | 桌宠随宿主状态变化的轻量交互 | 参考无额外 LLM 的状态表现；继续使用已有表情/表演意图 |
| 11 | [鲸鱼娘桌宠 · dsh-whale-musume](https://github.com/Sutera-Diffusus/dsh-whale-musume/tree/a61d5479892de6259f1beefbf3a142d250357571) | [MIT](https://github.com/Sutera-Diffusus/dsh-whale-musume/blob/a61d5479892de6259f1beefbf3a142d250357571/LICENSE) | 宿主活动到动作与桌面交互的映射 | 参考事件到表现的单向映射；小游戏和成就系统未移植 |
| 12 | [鲸鱼娘 Live2D · dsh-whale-girl-live2d](https://github.com/Andersen216/dsh-whale-girl-live2d/tree/f977bef508690e75ba6535cd8f4ce18e7f6ba9b0) | [MIT](https://github.com/Andersen216/dsh-whale-girl-live2d/blob/f977bef508690e75ba6535cd8f4ce18e7f6ba9b0/LICENSE) | Agent 状态驱动 Live2D 表情和动作 | 保留渲染器适配边界；未引入 Live2D 引擎或外部模型素材 |
| 13 | [B 站鲸鱼 · dsh-bili-whale](https://github.com/Alterssss/dsh-bili-whale/tree/8b0009f8ce2ebdc421afcb2e727b19ac18912ec6) | [MIT](https://github.com/Alterssss/dsh-bili-whale/blob/8b0009f8ce2ebdc421afcb2e727b19ac18912ec6/LICENSE) | 生物钟、持久计划、预算与退避 | 沿用规则决定何时唤醒；不将生活循环变成无限模型调用 |
| 14 | [B 站鱼塘 · dsh-bili-pond](https://github.com/YOYOLnFu/dsh-bili-pond/tree/57765435e33a8697c7f3b3b9f317c6146cd05faa) | [MIT](https://github.com/YOYOLnFu/dsh-bili-pond/blob/57765435e33a8697c7f3b3b9f317c6146cd05faa/LICENSE) | 定量筛选、去重、日报和投递状态 | 参考队列与交付事实分开；B 站登录、评论与私信未接入 |
| 15 | [抖音鲸鱼 · dsh-douyin-whale](https://github.com/jackey670/dsh-douyin-whale/tree/6d6e71f2ebb3fb8e096b1447116f615677b4b503) | [MIT](https://github.com/jackey670/dsh-douyin-whale/blob/6d6e71f2ebb3fb8e096b1447116f615677b4b503/LICENSE) | 主人给定内容队列、发送闸、回读和默认 dry-run | 借鉴不确定结果不重复执行；抖音读取/写入适配器未接入 |
| 16 | [大肥鱼直播 · dsh-livestream](https://github.com/luckui/dsh-livestream/tree/6c2f405b5520bea932808c224ba9ca6d65f41756) | [MIT](https://github.com/luckui/dsh-livestream/blob/6c2f405b5520bea932808c224ba9ca6d65f41756/LICENSE) | 弹幕、语音、OBS 与角色表现的组合 | 仅作多模态适配参考；自动直播、赠礼/私信行为未接入 |
| 17 | [大肥鱼表情包知识库 · dsh-nekowhale-stickers](https://github.com/Loping151/dsh-nekowhale-stickers/tree/1483eac4cadc38229a2e62a85e36862d073fb330) | [Apache-2.0](https://github.com/Loping151/dsh-nekowhale-stickers/blob/1483eac4cadc38229a2e62a85e36862d073fb330/LICENSE) | 带场景/情绪标注的表情包检索与 MCP | 沿用自有收藏与情绪选择；不导入第三方非商业素材 |
| 18 | [鲸鱼娘全局人设 · dsh-whale-musume-persona](https://github.com/Kaalia0912/dsh-whale-musume-persona/tree/0fbdcf217e3bf94e35fef36f7ac56134b704529b) | [MIT](https://github.com/Kaalia0912/dsh-whale-musume-persona/blob/0fbdcf217e3bf94e35fef36f7ac56134b704529b/LICENSE) | 人设提示与宿主模式的装配关系 | 保留 AIJADE 自己的人设；不覆盖原模型能力说明或研究提示 |
| 19 | [QQ Bridge · dsh-qq-bridge](https://github.com/TomoyoNatsume/dsh-qq-bridge/tree/6e13f95415bf58c9534b4616ed074087dc5e5631) | [MIT](https://github.com/TomoyoNatsume/dsh-qq-bridge/blob/6e13f95415bf58c9534b4616ed074087dc5e5631/LICENSE) | QQ 官方接口或 NapCat/OneBot 到宿主会话的桥接 | 继续复用已有 OneBot 11、授权绑定和独立渠道交付 |
| 20 | [消息 Hub · dsh-msg-hub](https://github.com/AbcdefgXW/dsh-msg-hub/tree/0fd11c38fa21d5639ea53f067a221d8ff7d8675c) | [MIT](https://github.com/AbcdefgXW/dsh-msg-hub/blob/0fd11c38fa21d5639ea53f067a221d8ff7d8675c/LICENSE) | 多 IM 适配、媒体引用、任务唤醒与回传 | 采用渠道适配器保持薄层的做法；不在渠道内复制 Agent 循环 |
| 21 | [肥鱼日记 · fatfish-diary](https://github.com/qwqpj/fatfish-diary/tree/bfacf4b48f7cd997c1d98677aa362a2d6e492f5a) | [MIT](https://github.com/qwqpj/fatfish-diary/blob/bfacf4b48f7cd997c1d98677aa362a2d6e492f5a/LICENSE) | 以事实统计为底座的日记、生成元信息与旧稿留档 | 参考事实/叙述/生成记录分开；日记生成 worker 未接入 |
| 22 | [给所有肥鱼完整人生 · DSH-a-complete-life-for-every-fish](https://github.com/zhugeweimu/DSH-a-complete-life-for-every-fish/tree/951fbdce561d392b708e1158a8edf2eff7475d54) | [Apache-2.0](https://github.com/zhugeweimu/DSH-a-complete-life-for-every-fish/blob/951fbdce561d392b708e1158a8edf2eff7475d54/LICENSE) | 独立记忆服务加薄 DSH 工具壳的两层模板 | 采用一份权威数据、多个适配入口；这是模板与演示，不是已验收整套产品 |
| 23 | [肥鱼语气 · dsh-fish-tone](https://github.com/MX3a48c5/dsh-fish-tone/tree/b22b071644379ae8abb2640c412eef9ea2de49ee) | [MIT](https://github.com/MX3a48c5/dsh-fish-tone/blob/b22b071644379ae8abb2640c412eef9ea2de49ee/LICENSE) | 语言表现与可选性格风味包分开 | 参考按需装配；不强塞口癖、热梗或额外无效内容 |
| 24 | [肥鱼记忆 · feiyu-memory](https://github.com/airpineapplea/feiyu-memory/tree/cf35d41f06c2b764a87531be825756e95b612155) | [MIT](https://github.com/airpineapplea/feiyu-memory/blob/cf35d41f06c2b764a87531be825756e95b612155/LICENSE) | 分层记忆、门控固化、线索检索与日记 | 借鉴有限上下文按需取用；现有研究记忆实现未替换 |
| 25 | [大肥鱼 AstrBot · dafeiyu-astrbot](https://github.com/whyever77/dafeiyu-astrbot/tree/74bc6ccef9c94deb852855c8461cdddf2907f991) | [MIT](https://github.com/whyever77/dafeiyu-astrbot/blob/74bc6ccef9c94deb852855c8461cdddf2907f991/LICENSE) | QQ 多模态、生活、情绪与来源可见的记忆展示 | 用于功能盘点；不复制整套 AstrBot/LivingMemory 到 .NET 主干 |
| 26 | [主动续话 · dsh-proactive-chat](https://github.com/shuaig22/dsh-proactive-chat/tree/b19cd3cef9bc89ef3344e3fbd18c485b6080ad73) | [MIT](https://github.com/shuaig22/dsh-proactive-chat/blob/b19cd3cef9bc89ef3344e3fbd18c485b6080ad73/LICENSE) | 按活跃程度续话、无人回应退避和有限打字等待 | 保留原主动消息门控和有界节奏；不因对方未回复惩罚关系 |
| 27 | [鱼的心 · astrbot_plugin_fish_heart](https://github.com/Vivy33/astrbot_plugin_fish_heart/tree/fdb2e798461998d5760321ea37e8145c0aa6113d) | [MIT](https://github.com/Vivy33/astrbot_plugin_fish_heart/blob/fdb2e798461998d5760321ea37e8145c0aa6113d/LICENSE) | 与记忆分开的短期情绪状态、驱动与主动开口条件 | 只参考状态分工与冷却；九维驱动、成人扩展及惩罚机制未引入 |
| 28 | [陪伴记忆与心跳 · dsh-companion-memory](https://github.com/xy261624/dsh-companion-memory/tree/1264bca0488dae556cd5ba17c519af2207501ba1) | [MIT](https://github.com/xy261624/dsh-companion-memory/blob/1264bca0488dae556cd5ba17c519af2207501ba1/LICENSE) | 跨会话记忆、自动整理、静默期、主动唤醒来源 | 参考来源区分和唤醒前检查；不沿用心跳默认全权限配置 |
| 29 | [大肥鱼有话说 · astrbot_plugin_feiyusays](https://github.com/GZSGZ/astrbot_plugin_feiyusays/tree/f223e09b8d5c360779f54098b4182cc4c7057d41) | [MIT](https://github.com/GZSGZ/astrbot_plugin_feiyusays/blob/f223e09b8d5c360779f54098b4182cc4c7057d41/LICENSE) | 文字气泡图片与所见即所得位置配置 | 可用作轻量图片表达入口参考；气泡渲染器和模板未接入 |
| 30 | [Free Vision · dsh-free-vision](https://github.com/FuzzySoul/dsh-free-vision/tree/9daa0dc4b42920c129bec5988765a585a0523843) | [MIT](https://github.com/FuzzySoul/dsh-free-vision/blob/9daa0dc4b42920c129bec5988765a585a0523843/LICENSE) | 独立视觉模型适配、超时和附件体积限制 | 采用有限工具执行；已有视觉入口保留，不假定免费额度持续可用 |

## 🧬 继承关系、许可与证据深度

- 14 号 `dsh-bili-pond` 的 README 明确说明由 `c1overzz/dsh-bili-scroll` 衍生；15 号 `dsh-douyin-whale` 保留原工具包作者归属。两者是不同仓库，计入插件清单，但不当作独立架构证据。
- 22 号记忆项目在一仓库中提供服务版与 DSH 工具版，23 号语气项目有主包与附属包，28 号记忆项目有整理与心跳子插件；每仓库只计一次。
- 9 号皮肤、16 号直播、17 号表情包、21 号日记中的角色素材不随代码许可自动开放。表中许可指本次所核对的代码；本轮没有导入这些资产。
- 重点抽样文件：`dsh-dafeiyu-life/index.js` 的计划与回执装配，`dsh-fish/lib/{budget,deliver}.js` 的回复长度与消息来源，`dsh-persona-distill/index.js` 的手工/自动人格分段，`feiyu-memory/src/core/recall.mjs` 的检索选择，`dsh-companion-memory/plugins/dsh-heartbeat/index.js` 的静默与唤醒来源，`dsh-free-vision/dsh/index.js` 的调用超时与附件限制。这是局部阅读，不是安全审计。
- 同名视频与同一关键词不代表作者或代码相同。已确认多数字生命作者视频简介链接了 1 号仓库；仍未确认此前 Vespera／Whisper 洗碗视频的作者绑定源码，不将其当作本轮已核对的开源模型。

## 🧩 另外 3 个架构主参考

下列 3 项来自同日上一轮已固定提交的架构核对，不包含在上表 30 项的配额中。详细读取范围见[原始参考回执](../experiments/engineering/2026-11-10-runtime-refactor/references.json)。

| 来源 | 许可 | 采用范围 |
|---|---|---|
| [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness/tree/fcc0ad462172522aaf5c93a7b2e01f6b9f0b0159) | MIT | profile、能力装配与生命周期 |
| [dsh-superagent-prototype](https://github.com/deepseek-ai/dsh-superagent-prototype/tree/8c32a9dc5d72c033816c6a8110b37f40cf94fba4) | MIT | 官方研究原型；Runtime/Engine/适配器职责 |
| [Comma](https://github.com/AFK-surf/Comma/tree/66ab3dc92475005aea9afd123df36a28e4ef86ab) | AGPL-3.0-only | 持续任务与会话分离、事件唤醒；未引入其服务栈或代码 |

本次的 superagent 指 DeepSeek 官方的 `dsh-superagent-prototype`。AIJADE 保留 .NET、PostgreSQL、现有 HTTP/OneBot/渲染协议，参考装配、状态所有权和执行边界，没有引入另一套 Harness、Elixir/Lean 或多数据库服务栈。

## 🛠️ 本轮转化成的实现

| 设计问题 | 当前实现与证据 |
|---|---|
| 同一渠道重复组装上下文与观察者 | 继续使用 `CompanionRuntime` 的有序能力清单；`ChatModuleSet` 对每个 `TurnContext` 缓存模块选择，一轮内开关不造成观察者只收到半轮 |
| 生活/记忆/外部上下文无限叠加 | Web 与 QQ 的清单先放生活，再放记忆、学习与可选外部上下文；`PromptBudget` 限制每模块、附加上下文、历史和单个工具结果，明确按字符计而非 token |
| 工具开关开着但预算为零仍作额外请求 | 零轮数或零调用数直接保留流式聊天，不探测工具清单 |
| 工具超时后模型重复请求同一动作 | 单次调用有 1–300 秒边界；超时、网络中断、5xx 或不可解析回执标为结果未知，本轮后续工具停止且不自动重试 |
| 渠道或插件持有第二份权威身份 | 延续服务端同步状态、修订号和 QQ 授权；本轮不新增第二套数据库、Agent 循环或人格自动改写 |

架构与图片见 [ARCHITECTURE](ARCHITECTURE.md)。功能“已有”“本轮改变”“尚未接通”分别写明，参考项目的功能不能计为 AIJADE 已完成。真实 QQ 交付、本地音色、授权 MMD/Live2D 资产、持久自主生活任务与真实模型效果需各自验收。

## 📌 排除与后续选择

许可不明的 `dsh-fish-soul`、`ai-girlfriend-v2`、`dsh-dafeiyu-memory`、`dsh-proactive` 等不进入 30 项开源配额；`Yuuyuko-uu` 的相关仓库采用自定义插件许可，也不按 MIT 开源项目计数。404、只有视频而无法确认源码、整合包内许可混杂者保留为线索。排除不表示项目质量差，只表示目前证据不足以满足本目录的条件。

后续扩展优先顺序是：先用真实 Web/QQ 会话验收同一身份与媒体交付，再考虑带来源与历史版本的日记，最后才增加有持久计划/交付回执的自主生活任务。它们需复用现有状态与队列，不增加独立记忆主库，也不把产品日志直接纳入论文数据。已有研究原始记录与冻结测量源码保持不变；产品上下文策略变化是版本变化，不等于原实验条件一致。
