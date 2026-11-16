# AIJADE 功能目录与独立实现边界

本目录按实际源码入口整理，机器源为 [capabilities.json](../configs/companion/capabilities.json)。九个职责域覆盖全部十五个 `src` 项目；这是现有项目的功能归属，不是新增九个常驻服务。

“已实现”表示存在本库逻辑；“配置入口”表示本库已有协议/服务适配，实际模型、设备、账号或平台仍需配置并验证；“待实现”和“迁移中”不计完成。目录自身只做源码清点，不授予真实设备、渲染、物理、学习效果或科学资格。

AIJADE 以持续交互的情感陪伴为主；MOSAIC 的连接组研究和具身产品线分别保持独立。借鉴七职责、唯一权威和效果回执的边界，不复制其源码、官方 Harness 安装或未通过的物理能力。文献、来源与旧实验外部比较仍保留。

## 项目归属

| 项目 | 主域 | 职责 |
|---|---|---|
| `Aijade.Bots` | delivery | 授权机器人宿主与渠道装配 |
| `Aijade.Client` | planning | 各端共享的产品运行库与领域客户端 |
| `Aijade.ComputerUse` | execution | 本库计算机操作工具；桌面动作需权限与平台支持 |
| `Aijade.Core` | support | 线协议、数值/随机与共同基础类型 |
| `Aijade.Growth` | research | 探索性成长/验证/发布服务与试验算法；不是已验收自主成长 |
| `Aijade.Integrations` | delivery | 本库渠道适配；Renderer子目录为单列研究适配器 |
| `Aijade.Learning` | research | 连续学习、技能包与注册库；晋升仍受研究协议约束 |
| `Aijade.Maui` | delivery | 共享UI的移动/桌面壳；构建需相应工作负载 |
| `Aijade.Memory` | memory | 来源、检索、事务与记忆模型；含单列研究算法 |
| `Aijade.Providers` | support | 模型服务与substrate协议适配；模型权重由配置提供 |
| `Aijade.Research` | research | 基准、统计、沙箱、检索驱动研究适配器 |
| `Aijade.Server` | support | 认证API、PostgreSQL权威与现有事件worker的单一组合宿主 |
| `Aijade.Telemetry` | support | 会话、轮次与表现遥测；观察不等同科学验收 |
| `Aijade.UI` | delivery | 各宿主复用的Blazor产品界面与浏览器舞台 |
| `Aijade.Web` | delivery | Web/PWA宿主 |

## 身份与关系 · identity

权威：账户/角色/授权绑定的服务端修订状态。

| 功能 | 状态 | 实际入口 / 源码 | 验证及配置边界 |
|---|---|---|---|
| 账户、登录与退出 | 已实现 | `/api/v1/auth/sign-up/email`；`/api/v1/auth/sign-in/email`；`/api/v1/auth/sign-out`；`/api/v1/auth/session`；[源码](../src/Aijade.Server/Auth/Accounts.cs) | PostgreSQL与宿主认证配置 |
| OIDC登录与账号清除 | 配置入口 | `/api/v1/auth/providers`；`/api/v1/auth/oidc/login`；`/api/v1/auth/account`；[源码](../src/Aijade.Server/Auth/Oidc.cs) | 用户配置的OIDC提供方；可用性独立验证 |
| 角色卡与会话选择 | 已实现 | `/api/v1/characters`；`/api/v1/chats`；[源码](../src/Aijade.Server/Product/Library.cs) | 仅源代码入口清点；测试与真实服务验收另看版本化回执。 |
| 网页与QQ私聊授权绑定及撤销 | 已实现 | `/api/v1/companion/pairing-code`；`/api/v1/companion/pair`；`/api/v1/companion/links`；`CompanionConfiguration.ForAsync`；[源码](../src/Aijade.Server/Product/CompanionSync.cs) | 仅源代码入口清点；测试与真实服务验收另看版本化回执。 |
| 角色、地点时区与关系修订同步 | 已实现 | `/api/v1/companion/characters/{id}/profile`；`/api/v1/companion/characters/{id}/observe`；[源码](../src/Aijade.Server/Product/CompanionSync.cs) | 仅源代码入口清点；测试与真实服务验收另看版本化回执。 |
| 私群聊天、记忆、后备关系与收藏隔离 | 已实现 | `ChannelScope.Conversation`；`ChannelScope.Memory`；`ChannelScope.Companion`；[源码](../src/Aijade.Integrations/ChannelScope.cs) | 原生QQ当前为授权主人私聊；群消息在通用桥接层处理 |
| 表情、服装、参考图与歌曲收藏 | 已实现 | `/api/v1/companion/characters/{id}/assets`；`CompanionMedia.Validate`；[源码](../src/Aijade.Server/Product/CompanionSync.cs) | 素材与音色应有独立来源授权 |

## 记忆 · memory

权威：账户、角色与受众范围内的持久记录；检索证据有来源。

| 功能 | 状态 | 实际入口 / 源码 | 验证及配置边界 |
|---|---|---|---|
| 记忆持久化、来源与事务 | 已实现 | `LongTermMemoryService`；`MemoryTxEngine`；[源码](../src/Aijade.Server/Memory/LongTermMemoryService.cs) | 仅源代码入口清点；测试与真实服务验收另看版本化回执。 |
| 普通聊天记录及相关记忆召回 | 已实现 | `ConversationRecorder.RecordAsync`；`MemoryRecallProvider.SupplyAsync`；`/api/v1/memory/items`；[源码](../src/Aijade.Client/Chat/MemoryContext.cs) | 嵌入模式需要可配置模型服务；召回指标不等于回答质量 |
| 记忆浏览、检索、遗忘、导入导出 | 已实现 | `/api/v1/memory/items`；`/api/v1/memory/items/export`；`/api/v1/memory/items/import`；[源码](../src/Aijade.Server/Memory/MemoryLibrary.cs) | 历史活动按真实存储的消息、主动、自拍与提醒计数展示；旧MoodTrend投影不作为当前心情或关系 |
| 信念、情节与记忆生命周期算法 | 已实现 | `BeliefMath`；`EpisodicGraph`；[源码](../src/Aijade.Memory/Beliefs/BeliefGraph.cs) | 产品使用范围与研究测量分开；不把算法类存在当自然长时记忆效果 |

## 生活 · life

权威：显式虚拟日程、关系变化、天气和日记；不宣称生物意识。

| 功能 | 状态 | 实际入口 / 源码 | 验证及配置边界 |
|---|---|---|---|
| 虚拟日程、兴趣、发型和季节服装 | 已实现 | `CompanionWorld`；`LifeMoment`；`CompanionExperience`；[源码](../src/Aijade.Client/Companion/CompanionExperience.cs) | 明确虚拟生活；不声称角色在现实世界持续行动 |
| 可配置地点、时区与真实天气 | 配置入口 | `CompanionWeather`；`CompanionProfile`；[源码](../src/Aijade.Client/Companion/CompanionWeather.cs) | 用户配置地点与天气开关；Open-Meteo HTTP；失败保留未知 |
| 主动开口、安静时段与冷却 | 已实现 | `Initiative`；`CompanionLife`；`CompanionBridge.FirstRepliesAsync`；[源码](../src/Aijade.Client/Companion/Initiative.cs) | 产品设置启用且渠道可达；不能用主动次数证明陪伴质量 |
| 提醒解析、保存与到期触发 | 已实现 | `ReminderBook`；`ConnectorHost.RemindOnceAsync`；[源码](../src/Aijade.Client/Companion/Reminders.cs) | 设置时区；提醒生成、平台接受与已读分别记录 |
| 共同日记的版本与共享 | 已实现 | `/api/v1/companion/characters/{id}/diary`；[源码](../src/Aijade.Server/Product/CompanionDiary.cs) | 日记保留来源；不能改写成用户原话 |
| 自拍时机与照片请求 | 已实现 | `Selfies`；`CompanionMediaTurn`；`/api/v1/images/selfie`；[源码](../src/Aijade.Client/Companion/Selfies.cs) | 生图/舞台图像服务需配置，生成内容与真实照片区分 |
| 短期情绪独立于长期关系 | 待实现 | `设计中的生活模块扩展点`；[源码](../docs/VIDEO-REFERENCE-ADOPTION.md) | 尚无独立短期情绪状态机；不宣称激素或生物意识 |

## 感知 · perception

权威：用户授予的媒体与带来源的观察；生成内容不充当真实感知。

| 功能 | 状态 | 实际入口 / 源码 | 验证及配置边界 |
|---|---|---|---|
| 整段与流式语音识别适配 | 配置入口 | `/api/v1/openai/v1/audio/transcriptions`；`ModelServices.Map`；[源码](../src/Aijade.Server/Product/ModelServices.cs) | 用户配置ASR端点/权重或服务；不是已训练自有语音模型 |
| 语音合成与逐字对齐 | 配置入口 | `/api/v1/openai/v1/audio/speech`；`/api/v1/openai/v1/audio/alignment`；`LipSync`；[源码](../src/Aijade.Server/Product/Gateway.cs) | 配置TTS/对齐服务与获授权音色；成功HTTP不证明音色质量 |
| 图像缩放、描述与视觉上下文 | 配置入口 | `VisionSession`；`VisionInterpreter`；[源码](../src/Aijade.Client/Chat/Vision.cs) | 用户选择媒体或开启感知；视觉模型与浏览器权限需验证 |
| 带来源的实时上下文 | 已实现 | `/api/v1/context/{source}`；[源码](../src/Aijade.Server/Product/LiveContext.cs) | 观察、生成推测、设备真值不能混作同一事实 |
| 节拍、音量、口型与视线输入 | 已实现 | `BeatDetector`；`LipSync`；[源码](../src/Aijade.Client/Chat/BeatSync.cs) | 表现输入不代表真实情绪或具身控制 |
| 按播放位置绑定字幕与抽帧 | 待实现 | `设计中的同视频/时间戳观察合同`；[源码](../docs/VIDEO-REFERENCE-ADOPTION.md) | 持续一起看与换片取消界面尚未实现 |
| 前台按键摄像头与麦克风采集 | 待实现 | `移动端感知扩展点`；[源码](../docs/VIDEO-REFERENCE-ADOPTION.md) | 独立移动感知客户端待实现 |

## 规划 · planning

权威：同一回复运行库、模块选择与预算；模型只提出受限意图。

| 功能 | 状态 | 实际入口 / 源码 | 验证及配置边界 |
|---|---|---|---|
| 统一回复、上下文与观察者管线 | 已实现 | `CompanionRuntime.Create`；`ChatModuleSet`；`ChatOrchestrator.SendAsync`；[源码](../src/Aijade.Client/Chat/CompanionRuntime.cs) | 共享代码库并非新增Agent服务器 |
| 模块快照与提示长度预算 | 已实现 | `ChatModuleSet`；`PromptBudget`；[源码](../src/Aijade.Client/Chat/CompanionRuntime.cs) | 字符预算与token/模型容量分开核对 |
| 受限工具循环、超时与未知停止 | 已实现 | `ToolConversation`；`ToolHub`；`/api/v1/tools/call`；[源码](../src/Aijade.Client/Chat/ToolConversation.cs) | 工具路由需授权配置；结果未知不自动重放 |
| 伴侣/完整宿主的能力装配 | 已实现 | `ServerModules.Read`；`tools/run-companion.sh`；[源码](../src/Aijade.Server/ServerModules.cs) | 模块开关不安装插件；完整模式保留研究兼容路径 |
| 发言准入、会话串行与限流 | 已实现 | `CompanionBridge.ShouldAnswer`；`CompanionBridge.AnswerAsync`；[源码](../src/Aijade.Integrations/CompanionBridge.cs) | 原生QQ只接授权主人的私聊；通用群聊不是QQ多群实收验收 |
| 分段输入的有界合并窗口 | 待实现 | `现有入站队列扩展点`；[源码](../docs/VIDEO-REFERENCE-ADOPTION.md) | 保留原始消息ID、命令与媒体边界；合并策略待实现 |

## 执行 · execution

权威：本库领域操作与明确授权执行；逻辑状态、渲染和物理效果分别记录。

| 功能 | 状态 | 实际入口 / 源码 | 验证及配置边界 |
|---|---|---|---|
| AIJADE原生虚拟舞台状态与命令 | 已实现 | `/api/v1/stage`；`/api/v1/stage/command`；`NativeStageStore.ReadAsync`；`NativeStageStore.ApplyAsync`；`CompanionStage`；[源码](../src/Aijade.Server/Product/Stage.cs) | 本轮以本库/PostgreSQL虚拟状态替换外部工作台代理；renderObserved=false，逻辑状态不等同渲染、声音播放、动作或物理效果 |
| 网页MMD舞台与表现 | 已实现 | `StagePanel`；`stage.js`；[源码](../src/Aijade.UI/Shared/StagePanel.razor) | 用户自有/获授权PMX、VMD和渲染依赖；浏览器及真实模型单独验收 |
| 图像、自拍与参考图服务路由 | 配置入口 | `/api/v1/images`；`/photo`；[源码](../src/Aijade.Server/Product/Images.cs) | 配置生成模型与参考素材；生成结果要标明 |
| 歌声端点与歌曲收藏 | 配置入口 | `/api/v1/openai/v1/audio/singing`；`/sing`；[源码](../src/Aijade.Server/Product/CompanionLocalServices.cs) | 本地或用户自有歌声服务与音色；目录配置不等于加载/训练完成 |
| 计算机只读观察与授权操作 | 配置入口 | `aijade-computer-use MCP stdio`；[源码](../src/Aijade.ComputerUse/Program.cs) | 平台权限与明确写操作授权；不是通用无限桌面代理 |
| Minecraft协议、导航与行为 | 配置入口 | `Minecraft:Host`；`MinecraftBehaviour`；[源码](../src/Aijade.Integrations/Minecraft/McClient.cs) | 配置游戏服务端并单独运行实机测试 |
| 与角色进行国际象棋 | 已实现 | `Chess`；`ChessCompanion`；`ChessGame`；[源码](../src/Aijade.Client/Games/Chess.cs) | 仅源代码入口清点；测试与真实服务验收另看版本化回执。 |
| HomeAssistant/小米设备协议适配 | 配置入口 | `ToolHub领域提供方`；[源码](../src/Aijade.Server/Tools/HomeAssistantTools.cs) | 已授权设备与API；适配代码由AIJADE拥有，实际设备效果另验收 |
| Factorio服务协议适配 | 配置入口 | `ToolHub Factorio提供方`；[源码](../src/Aijade.Server/Tools/Factorio.cs) | 配置游戏服务与操作权限 |
| 虚拟房间与可编辑角色资产流程 | 待实现 | `舞台与资产扩展点`；[源码](../docs/VIDEO-REFERENCE-ADOPTION.md) | 房间交互/拆层工作流待实现；不安装外部房间/拆层插件 |

## 交付 · delivery

权威：宿主与渠道投递；保存、平台回执、接收/已读分别对待。

| 功能 | 状态 | 实际入口 / 源码 | 验证及配置边界 |
|---|---|---|---|
| 网页与PWA宿主 | 已实现 | `Aijade.Web`；`PWA service worker`；[源码](../src/Aijade.Web/Program.cs) | 浏览器端到端测试需显式启用 |
| Android/Windows共享UI宿主 | 配置入口 | `Aijade.Maui`；[源码](../src/Aijade.Maui/MauiProgram.cs) | 对应MAUI工作负载、SDK与目标设备；不在默认solution构建中 |
| QQ授权主人私聊、语音和收藏入口 | 配置入口 | `OneBot:NapCat`；`OneBot:Owner`；`OneBotConnector.RunAsync`；[源码](../src/Aijade.Integrations/OneBotConnector.cs) | NapCat OneBot11服务、密钥文件与主人白名单；本轮不宣称真实QQ接收通过 |
| Telegram与Discord适配 | 配置入口 | `Telegram:Token`；`Discord:Token`；[源码](../src/Aijade.Bots/TelegramConnector.cs) | 平台注册与已授权令牌 |
| Satori与X协议适配 | 配置入口 | `Satori:Url`；`X:AccessToken`；[源码](../src/Aijade.Integrations/SatoriConnector.cs) | 用户配置平台服务及授权；不安装整套第三方插件宿主 |
| B站直播渠道适配 | 配置入口 | `Bilibili:RoomId`；[源码](../src/Aijade.Integrations/BilibiliLiveConnector.cs) | 房间及可选授权登录；不等于自动刷视频/评论能力 |
| 普通/主动/提醒的统一交付记录 | 已实现 | `/api/v1/companion/characters/{id}/deliveries`；[源码](../src/Aijade.Server/Product/CompanionDelivery.cs) | 保存、发送尝试、平台接受、未知与已读分别处理 |
| 有界分段、发送节奏与中断 | 已实现 | `OneBotConnector.SendReplyAsync`；[源码](../src/Aijade.Integrations/OneBotConnector.cs) | 平台回执和当前输入版本共同限制后续片段 |
| 本库MCP服务与可配置提供方 | 配置入口 | `Aijade:Modules:Mcp`；`/api/v1/tools`；[源码](../src/Aijade.Server/Mcp/AijadeMcpServer.cs) | MCP是兼容协议；外部提供方需用户配置，非默认插件安装器 |

## 独立研究 · research

权威：P1/P2/P3/第7章的冻结源码、驱动、原始记录与未通过门槛。

| 功能 | 状态 | 实际入口 / 源码 | 验证及配置边界 |
|---|---|---|---|
| P1契约、变异与外部回执研究 | 已实现 | `tools/Aijade.P1`；`tools/Aijade.Mutation`；[源码](../tools/Aijade.P1/Program.cs) | 冻结研究方案与已有记录；工程测试不是外部科学效度 |
| P2技能、JS沙箱、判断与基准 | 已实现 | `SkillBench`；`JudgmentPreparation`；`PublicBenchBank`；[源码](../src/Aijade.Research/SkillBench/Bench.cs) | 保留逐题纳入/排除与AI辅助判读；不把准备工作当模型效果 |
| P3 LoCoMo/LongMemEval与政策评测 | 已实现 | `MemoryEval`；`tools/Aijade.Experiments`；[源码](../src/Aijade.Research/MemoryEval/MetricDefinitions.cs) | 已有回执限定语料、政策、版本和分母；不外推回答质量 |
| 受限请求与验证反馈研究 | 已实现 | `RqcRunner`；`RequestBudget`；[源码](../src/Aijade.Research/RqC/RqcRunner.cs) | 输入、模型、次数与终止条件须绑定方案 |
| 学习、技能晋升与因果证据事务 | 已实现 | `PromotionService`；`EvidenceDomainService`；`V9CausalRuntime`；[源码](../src/Aijade.Server/V9/PromotionService.cs) | 事务一致不代表技能语义正确；研究资格独立 |
| 成长、兴趣、验证与可信发布原型 | 已实现 | `GrowthLoop`；`TrustedReleaseController`；`RunPilot`；[源码](../src/Aijade.Growth/GrowthLoop.cs) | 探索性/研究模块，不宣称已通过自主学习或普遍技能迁移 |
| 第7章有限流程与历史证据守卫 | 已实现 | `experiments/ch7/run_finite_sequence.py`；`tools/verify-historical-manifest.py`；[源码](../experiments/ch7/finite_runtime.py) | 不新增案例、模型调用或硬件资格；旧准入拒绝与失败原样保留 |
| 原渲染器协议研究适配 | 已实现 | `MosaicRendererLink`；`experiments/ch7/godot_local.py`；[源码](../src/Aijade.Integrations/Renderer/MosaicRendererLink.cs) | 仅历史比较/显式研究适配；不进入默认产品宿主；不改旧字节 |

## 基础支撑 · support

权威：数据库、模型协议、部署、管理、遥测与文档；不建立第二套角色权威。

| 功能 | 状态 | 实际入口 / 源码 | 验证及配置边界 |
|---|---|---|---|
| API宿主、数据库与迁移 | 已实现 | `AijadeServer`；`/healthz`；[源码](../src/Aijade.Server/AijadeServer.cs) | PostgreSQL；服务部署与数据库备份另行管理 |
| 现有事件worker与可选Redis | 已实现 | `CompanionWorker`；`IJobBroker`；`V9Worker`；[源码](../src/Aijade.Server/ServerModules.cs) | companion单机可使用原有本机唤醒；Redis显式配置 |
| 聊天、嵌入、图像与语音模型协议 | 配置入口 | `/api/v1/openai/v1/chat/completions`；`/api/v1/openai/v1/embeddings`；[源码](../src/Aijade.Server/Product/Gateway.cs) | 用户提供模型服务或本机权重；独立编排不等于独立训练基础模型 |
| 本地服务配置、健康检查与歌声设置 | 已实现 | `/api/v1/admin/gateway/local-services`；`/api/v1/admin/gateway/local-services/check`；[源码](../src/Aijade.Server/Product/CompanionLocalServices.cs) | 检查只证明被检接口可达，训练/音色效果仍未知 |
| 管理后台与提供方配置 | 已实现 | `/api/v1/admin`；`/api/v1/providers`；`/api/v1/admin/tools`；[源码](../src/Aijade.Server/Product/Admin.cs) | 用户授权管理范围及加密保存的服务凭据 |
| 可选计费与额度 | 配置入口 | `Aijade:Modules:Billing`；`FluxLedger`；[源码](../src/Aijade.Server/Product/Billing.cs) | Stripe等计费服务与明确配置；不自动购买服务 |
| 会话、轮次、表现与来源遥测 | 已实现 | `TelemetryJson`；`RenderReporter`；[源码](../src/Aijade.Telemetry/Telemetry.cs) | 日志完整性与真实效果验收分开 |
| 多语言、设置与各端共享UI | 已实现 | `Strings`；`AppSettings`；`ServiceRegistration`；[源码](../src/Aijade.Client/I18n/Strings.cs) | 仅源代码入口清点；测试与真实服务验收另看版本化回执。 |
| 数值、线协议与可重放随机基础 | 已实现 | `WireSchema`；`Mulberry32`；[源码](../src/Aijade.Core/Schema/WireSchema.cs) | 保留既有比较与参考语义；不因重构改变历史计分 |
| 本机路径、启动配置与CI | 已实现 | `tools/run-companion.sh`；`tools/verify-independent-architecture.py`；[源码](../tools/with-workspace-env.sh) | 本机所有工作产物保留在指定AIJADE根；CI通过不是论文投稿就绪 |
| 完整状态备份与隔离恢复演练 | 待实现 | `记忆与同步状态的备份扩展点`；[源码](../docs/VIDEO-REFERENCE-ADOPTION.md) | 已有记忆导出不等于账户/关系/绑定完整灾备 |

## 版本、依赖与研究例外

生产入口是 `tools/run-companion.sh`、服务端 `Program.cs/ServerModules` 和机器人 `Program.cs`。这些入口由本库拥有，不以 MOSAIC 工作目录或原生执行器作为产品启动依赖。标准SDK、数据库驱动、模型服务和OneBot/MCP等协议兼容仍显式记录，不能把协议适配说成自有模型训练。

原 `src/Aijade.Integrations/Renderer/` 与 `experiments/ch7/finite_*`、`godot_local.py` 属历史研究适配边界。根 `tools/` 当前没有 `finite-*` 运行器，不能杜撰路径。它们继续用于既有来源与比较证据，保持字节和科学状态；本轮目录不批准新的有限研究运行，也不把新产品等同旧冻结实现。

原生舞台 `Stage.Map` 只连接本库 `NativeStageStore`；守卫拒绝在该实际入口重新加入 `IHttpClientFactory`、`CreateClient` 或HTTP转发调用。旧 `Workbench` URI校验helper与JSON兼容名称保留，不算运行依赖。`ownedRuntimeSources` 同时列明原生舞台与本库媒体服务；用户配置的本地协议服务仍是许可的显式适配。

运行 `python3 tools/verify-independent-architecture.py --check-only --self-test` 可检查项目引用闭合、十五项目分类、能力源路径、产品启动器与原生舞台边界，并执行九个内存中的拒绝控制。检查默认只输出到stdout，不改项目或原始实验；所需本机报告应重定向到指定AIJADE根下的 `.research/`。目录清点的是基准提交之上的当前重构工作树，不能当作旧提交已含全部新实现。

本轮目录包含 69 个功能族。完整视频参考与待实现验收规格见 [独立实现记录](VIDEO-REFERENCE-ADOPTION.md)，当前架构见 [ARCHITECTURE](ARCHITECTURE.md)。
