# AIJADE 陪伴运行架构

AIJADE 优先开发持续交互的情感陪伴。MOSAIC 的连接组研究和具身智能保持独立，两个项目按明确接口借鉴产品能力。本页描述本轮重构后已有的代码与运行关系；30 个陪伴项目和 3 个架构主参考见 [参考目录](COMPANION-REFERENCES.md)，它们的能力不计入 AIJADE 的完成状态。

## 🧭 系统总览

图中的 `CompanionRuntime` 是各宿主进程内复用的 **.NET 代码库**，不是新增的中央 Agent 服务器。实线表示已有调用/依赖，虚线表示需配置启用的可选集成。模型、图像、语音和 MOSAIC 舞台是否可用，取决于相应服务及授权资产；图中有适配入口不代表服务已经接通。

<!-- architecture:overview -->
```mermaid
flowchart LR
    accTitle: AIJADE implemented system architecture
    accDescr: Web and bot hosts reuse a shared in-process companion library, call an authenticated server and retain a separate research apparatus. Dashed edges indicate configurable optional integrations.
    subgraph channel_hosts["渠道宿主"]
        web_apps["Web / MAUI<br/>界面 · 语音 · 表现"]
        chat_bots["QQ / 其他渠道<br/>授权 · 节奏 · 交付"]
    end
    companion_runtime["共享运行时代码库<br/>CompanionRuntime<br/>ChatOrchestrator<br/>装配 · 预算 · 回复流"]
    foundation["共同基础代码<br/>记忆 · 学习 · 遥测<br/>保留研究约束"]
    subgraph server_host["AIJADE 后端部署 · full 或 companion"]
        core_api["认证 HTTP API<br/>聊天 · 同步 · 媒体 · 证据"]
        state_store[("PostgreSQL<br/>角色 · 关系 · 收藏<br/>日记 · 交付记录<br/>地点时区 · 记忆 · 事件<br/>修订号 · 授权绑定")]
        event_worker["既有队列 / Worker<br/>本机唤醒或 Redis<br/>沿用 V9 处理器"]
    end
    model_services["配置的模型/媒体服务<br/>聊天 · 图片 · ASR<br/>TTS · 歌声"]
    optional_integrations["可选集成<br/>MCP · Tools · Stage<br/>Billing"]
    research_drivers["独立研究驱动<br/>P1 / P2 / P3<br/>原始记录与证据"]
    web_apps -->|"各端加载"| companion_runtime
    chat_bots -->|"各端加载"| companion_runtime
    companion_runtime -->|"认证 HTTP"| core_api
    companion_runtime -->|"编译依赖"| foundation
    core_api --> state_store
    core_api --> event_worker
    event_worker --> state_store
    core_api --> model_services
    core_api -.->|"显式启用"| optional_integrations
    research_drivers -->|"既有研究路径"| core_api
    research_drivers -->|"编译依赖"| foundation
    classDef host fill:#ede9fe,stroke:#7c3aed,stroke-width:2px,color:#3b0764
    classDef core fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#1e3a5f
    classDef data fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#14532d
    classDef optional fill:#fef9c3,stroke:#ca8a04,stroke-width:2px,color:#713f12
    class web_apps,chat_bots host
    class companion_runtime,core_api core
    class foundation,state_store,event_worker,research_drivers data
    class model_services,optional_integrations optional
```

可直接查看[总览 PNG](architecture/overview.png) 或[矢量 SVG](architecture/overview.svg)。本页 Mermaid 是可编辑的唯一源稿，图片由 [渲染脚本](../tools/render-architecture.py)提取生成；未依赖 GitHub 的 Mermaid 版本。

Web、MAUI、QQ 按渠道能力装配。MCP 的普通聊天工具也复用此库，当前只装配记忆与普通聊天，并未获得 Web/QQ 的身份绑定和媒体交付能力。客户端的天气适配器在用户配置地点并开启后直接读取 Open-Meteo，不经过模型网关；未启用或读取失败时不假造实时天气。

后端部署区内的 PostgreSQL 是独立数据库组件；API 与 worker 根据 `Aijade:Role` 同进程或分离部署。图中的组合区域不表示它们是同一个进程。

## 🔄 单轮消息与结果交付

<!-- architecture:turn-flow -->
```mermaid
flowchart TB
    accTitle: AIJADE bounded conversation flow
    accDescr: A bound channel request takes either the explicit media route or the ordinary conversation route. Successful persistence precedes completion and channel delivery, and uncertain tool outcomes stop further tool actions.
    channel_input["渠道准备<br/>核对绑定/共享状态<br/>准备渠道规则"]
    command_route{"显式陪伴命令？"}
    media_command["显式命令处理并保存<br/>媒体/日常/关系/日记<br/>不调用聊天模型"]
    store_user["保存用户消息<br/>创建 TurnContext"]
    module_snapshot["固定本轮模块选择<br/>生活→记忆→学习<br/>再取可选上下文"]
    prompt_build["装配提示/长度预算<br/>保留人设与当前输入<br/>数据库原文不改"]
    bounded_model["聊天/可选工具<br/>4 轮 · 12 次 · 30 秒/次<br/>结果未知停后续工具"]
    store_reply["解析/保存回复<br/>表情 · 表演意图<br/>成功后发完成事件"]
    channel_delivery["渠道交付<br/>网页 / QQ / 媒体播放<br/>QQ 回复逐片段记录<br/>接受 / 拒绝 / 未知 · 非已读"]
    turn_failure["TurnFailed / 渠道错误<br/>不发完成事件<br/>调用方取消继续传播"]
    channel_input --> command_route
    command_route -->|"是且陪伴启用"| media_command
    command_route -->|"普通聊天"| store_user
    media_command -->|"MediaCompleted"| channel_delivery
    store_user --> module_snapshot
    module_snapshot --> prompt_build
    prompt_build --> bounded_model
    bounded_model --> store_reply
    store_reply -->|"TurnCompleted"| channel_delivery
    store_user -->|"写入失败"| turn_failure
    store_reply -->|"模型或存储失败"| turn_failure
    media_command -->|"API 失败"| turn_failure
    classDef process fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#1e3a5f
    classDef decision fill:#fef9c3,stroke:#ca8a04,stroke-width:2px,color:#713f12
    classDef success fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#14532d
    classDef failure fill:#fee2e2,stroke:#dc2626,stroke-width:2px,color:#7f1d1d
    class channel_input,store_user,module_snapshot,prompt_build,bounded_model,media_command process
    class command_route decision
    class store_reply,channel_delivery success
    class turn_failure failure
```

可直接查看[流程 PNG](architecture/turn-flow.png) 或[矢量 SVG](architecture/turn-flow.svg)。主动消息和到期提醒走原有门控，再共用回复解析与保存；它们跳过普通记忆召回与学习观察者，只可带产品生活上下文，不冒充一条用户输入，也不转入外部工具循环。

## 📨 QQ 交付记录与返回阶段

`TurnCompleted` 表示回复成功保存，随后 QQ 平台调用有独立结果。普通回复、主动消息、到期提醒和经共享运行时处理的 `/photo`、`/sing`、`/life`、`/relationship`、`/diary` 命令都携带来源消息 ID，通过同一 QQ 发送器登记回执。服务端从已存来源的元数据识别普通回复、主动消息或提醒，并为提醒保留触发 ID；绑定和收藏导入命令仍不在这份记录内。

<!-- architecture:qq-delivery -->
```mermaid
flowchart TB
    accTitle: Source-linked QQ delivery observations
    accDescr: Ordinary replies, gated first lines and due reminders retain their stored identities and reserve an attempt before dispatch. Reminder generation consumes a local promise separately from platform acceptance. Valid acknowledgements permit another part; rejections and unknown outcomes stop later sends. Acceptance does not establish recipient delivery or reading.
    reply_origin["普通回复 / 显式命令"]
    initiative_origin["主动门控通过<br/>生成并保存主动消息"]
    reminder_origin["约定提醒到期<br/>复用已存来源或生成保存<br/>消费本地提醒 · 不等于发送成功"]
    stored_reply["回复已入库<br/>来源 ID / 原文 SHA-256<br/>来源类型 / 提醒触发 ID"]
    prepared["授权范围内登记尝试<br/>已有记录则不再发送"]
    dispatched["登记片段与请求指纹<br/>调用 QQ 发送 API"]
    part_ack["片段获平台回执<br/>HTTP 成功 + ok + retcode 0<br/>有效消息编号"]
    completed["计划片段全部结束<br/>已获平台回执 · 非已读"]
    rejected["明示拒绝<br/>保留已确认片段，停止后续"]
    unknown["结果未知<br/>停止后续，不自动重发"]
    interrupted["新输入或本地失败中断<br/>保留已确认片段"]
    reply_origin --> stored_reply
    initiative_origin --> stored_reply
    reminder_origin --> stored_reply
    stored_reply --> prepared
    prepared --> dispatched
    dispatched --> part_ack
    part_ack -->|"还有片段"| dispatched
    part_ack -->|"结束记录成功"| completed
    dispatched -->|"明示失败"| rejected
    dispatched -->|"异步 / 超时 / 残缺回执 / 无法写入观察"| unknown
    prepared -->|"10 分钟无结束记录"| unknown
    prepared -->|"中断"| interrupted
    part_ack -->|"中断"| interrupted
    classDef active fill:#dbeafe,stroke:#2563eb,stroke-width:2px,color:#1e3a5f
    classDef accepted fill:#dcfce7,stroke:#16a34a,stroke-width:2px,color:#14532d
    classDef stopped fill:#fef9c3,stroke:#ca8a04,stroke-width:2px,color:#713f12
    class reply_origin,initiative_origin,reminder_origin,stored_reply,prepared,dispatched active
    class part_ack,completed accepted
    class rejected,unknown,interrupted stopped
```

[交付流程 PNG](architecture/qq-delivery.png) / [SVG](architecture/qq-delivery.svg)。创建发送记录失败时不发出平台请求；片段回执无法持久保存时也不发送下一片段。分段发送不具备整体回滚，未知也不等于未发送。记录由持有授权的 relay 上报，不能抵御 relay 自己伪造观察；不构成独立研究证据。

交付数据仍在现有 PostgreSQL `config_kv` 中，按账号／角色独立、按需读取，普通角色载荷不携带它。每角色最多保留 128 次尝试、每次最多 64 个片段；仅淘汰较早的已结束记录，并累计淘汰数，进行中记录满额则拒绝新增。未结束记录超过 10 分钟投影为未知，原聊天不删。重复阻止仅覆盖仍保留的来源消息，不是永久 exactly-once、入站事件去重、持久 outbox 或重启后自动补发。

`FirstRepliesAsync` 与 `DueReminderReplyAsync` 返回带来源的 `ChannelReply`，旧文本接口继续兼容。`IProactiveConnector.SendReplyAsync` 允许 QQ 复用普通回复发送器；其他连接器默认仍使用原文本发送接口。提醒簿的 `done` 只表示提醒文本已存，平台拒绝或结果未知不会重新生成。若进程在保存文本后、更新提醒文件前停止，下一次检查会按同一聊天内的提醒 ID 复用已存消息；原尝试仍在保留窗口内时不再发送。这不覆盖聊天删除、角色切换或保留记录被淘汰后的重复。调度与提醒簿继续归各渠道所有，没有新增中央调度器。

## 🧩 代码职责与状态所有权

| 代码或数据 | 负责内容与边界 |
|---|---|
| [CompanionRuntime / ChatModuleSet](../src/Aijade.Client/Chat/CompanionRuntime.cs) | 一张有序清单同时装配上下文和观察者；每个 `TurnContext` 的模块选择只确定一次，开关影响下一轮。可选模块故障独立降级，调用方取消保留。缓存以弱引用关联回合，不启动清理循环 |
| [ChatOrchestrator](../src/Aijade.Client/Chat/Orchestrator.cs) | 保存用户消息、提示装配与模型调用；普通聊天、主动消息、提醒共用回复解析/存储/意图构建。写入失败发出 `TurnFailed` |
| [PromptBudget](../src/Aijade.Client/Chat/PromptBudget.cs) | 产品附加上下文、历史与工具结果长度限制。截断有标记，不切开 UTF-16 代理对；优先保留近期历史，不改数据库中的原文 |
| [CompanionMediaTurn](../src/Aijade.Client/Companion/CompanionMediaTurn.cs) | `/photo`、`/sing`、`/life`、`/relationship`、`/diary` 显式入口；保存结果后产生 `MediaCompleted`，图片/歌声可能调用已配置的专用服务，日记不调用模型 |
| [ToolConversation](../src/Aijade.Client/Chat/ToolConversation.cs) | 有界的按需工具执行，工具须在本轮清单内，参数须为 JSON 编码对象。零轮数/零调用数不探测工具，直接走流式聊天 |
| `CompanionSyncStore` / PostgreSQL | 账户/角色、地点时区、关系与收藏的权威状态；修订号、并发冲突检查、可撤销 QQ 授权。日记使用同一权限边界下独立、按需读取的文档，不进入普通状态载荷 |
| `ICompanionDelivery` / `OneBotDelivery` | 可选 notebook 能力把已存来源关联到 QQ 的分段发送观察；发送前登记、严格解析回执、按序完成、未知或记录失败停止后续。没有增加宿主、模型调用或后台重试器 |
| `ServerModules` / `CompanionWorker` | 启动时组合可选集成；精简配置且无 Redis 时排空既有队列，再等待合并唤醒。沿用 `V9Worker.DrainOnceAsync`，不新增调度平台 |
| `Aijade.Bots` / 渠道连接器 | 授权、会话映射、单会话串行、消息节奏与平台交付。网页 localStorage 的提醒与机器人文件中的提醒仍是各自渠道状态，没有宣称统一同步 |

公共消息、HTTP/OneBot/SignalR/渲染协议、表结构及研究驱动继续保留。新增预算是产品类，不是新进程或新 .NET 项目；本轮未增加 NuGet 包。MOSAIC 只通过已有舞台/渲染接口作为可选产品适配，不把连接组研究放入 AIJADE 的聊天主循环。

## ⚙️ 有界执行与可修改配置

| 项目 | 产品默认值 | 生效与含义 |
|---|---:|---|
| 单模块上下文 | 4,000 字符 | 按装配顺序取用，超出时带截断标记 |
| 附加上下文合计 | 12,000 字符 | 包含模块间分隔符；预算用完后不再请求后续上下文 |
| 历史 | 最近 24 条内最多 24,000 字符 | 从最近消息向前保留整条；仅当最新一条本身超长时保留有标记的片段 |
| 单个工具结果 | 8,000 字符 | 普通结果超长时截断；不把结果未知的关键说明裁掉 |
| 工具轮数 / 外部调用数 | 4 / 12 | 各自钳制为 0–16 / 0–64；任一为零不请求工具清单 |
| 单次工具期限 | 30 秒 | 钳制为 1–300 秒；取消等待不等于远端撤销动作 |

以上长度按 UTF-16 字符计，**不是 token 容量保证或新的速度测量**；人设、当前输入、渠道规则和工具定义不在附加上下文预算内。小于截断标记的可用空间直接省略该片段，不产生无提示的残缺断言。较低预算会改变产品提示内容，实际模型仍须按其上下文窗口和输出预算配置。

超时、网络中断、HTTP 408/5xx 或不可解析回执会向模型交还“结果未知”的说明，并禁止本轮后续工具与自动重试。已生效的远端动作可能继续存在；这是执行边界，不是事务回滚或跨崩溃 exactly-once。模型能否准确复述错误仍需真实模型验收，工程测试不替代它。

Web/MAUI 的导出设置支持 `promptBudget` 和 `toolTimeoutSeconds`，导入保存后下一轮使用；原有界面无须增加技术配置页。QQ 宿主支持 `Bridge:ToolTimeoutSeconds`、`Bridge:PromptBudget:ModuleCharacters`、`SupplementCharacters`、`HistoryCharacters` 和 `ToolResultCharacters`。环境变量将 `:` 替换为 `__`。

QQ 的这些运行参数在 `Aijade.Bots` 启动时读取，修改环境变量后重启机器人宿主；共享的角色与生活状态仍在下一轮从服务端读取。

```json
{
  "promptBudget": {
    "moduleCharacters": 4000,
    "supplementCharacters": 12000,
    "historyCharacters": 24000,
    "toolResultCharacters": 8000
  },
  "toolTimeoutSeconds": 30
}
```

此片段合并到现有导出文件的 `settings` 中，保持外层 `format: aijade.export.v1`。长度配置分别钳制到 0–128,000。预算没有被加入跨端共享角色状态，Web 本地设置和机器人部署参数仍可按渠道能力不同；已统一同步的角色、地点时区、关系与收藏保持原生效规则。

## 🚀 运行配置与功能边界

| 配置 | `full`（原有默认） | `companion`（显式选择） |
|---|---|---|
| 核心 API、聊天、角色/关系/收藏同步、记忆与证据管线 | 保留 | 保留 |
| MCP、外部工具、MOSAIC 舞台桥、Stripe | 默认挂载 | 默认不挂载，可逐项开启 |
| 单进程无 Redis 的后台队列 | 原 worker 时序 | 同一处理器，有任务唤醒 |
| Redis 分离 API/worker | 原路径 | 原路径 |

```bash
# 先配置现有 DATABASE_URL、模型网关与账户
tools/run-companion.sh

# 按需开启原有工具与 MCP
tools/run-companion.sh --Aijade:Modules:Tools=true --Aijade:Modules:Mcp=true
```

配置通过 `Aijade__Profile=companion`、`Aijade__Modules__Tools=true` 等环境变量也可设置。角色仍有 `api`、`worker`、`all`；模块组合启动后修改需重启。认证后的 `GET /api/v1/runtime` 返回实际 profile、角色、队列方式与集成开关。错误模块名、未知 profile、非法布尔值在启动时报错；未挂载的 API 返回 404。

| 功能状态 | 内容 |
|---|---|
| 已有并继续复用 | 共享角色/地点时区/关系/收藏、普通聊天、主动消息门控、虚拟日常、表情与节奏、照片/语音/唱歌的可配置入口；稳定单轮模块清单、上下文与工具预算 |
| 当前追加 | 普通 QQ 回复与共享媒体命令的来源关联交付记录、分段平台回执、拒绝／未知／中断状态、网页读取；保留共享日记、时钟注入修复与空回复检查 |
| 配置后仍需实测 | 真实 QQ 收发、天气联网、图像服务、本地授权音色/歌声、MOSAIC/MMD 舞台与外部工具设备 |
| 后续独立扩展 | 自动生成且保留历史版本的日记、持久生活任务与平台交付 outbox、多角色社交；当前未实现，不画成已部署模块 |

## 🧪 验证与研究兼容

工程测试覆盖模块切换、故障/取消、截断后的提示与原始存储、旧直接构造入口、无效工具参数、超时/断网/5xx、零预算，并回归完整聊天与同步流程。最新[主动消息与提醒回执](../experiments/engineering/2026-11-10-proactive-delivery/receipt.json)补充来源类型、提醒触发身份、已存提醒恢复和跨端显示；[上轮交付观察回执](../experiments/engineering/2026-11-10-delivery-receipts/receipt.json)覆盖授权来源、重复登记、部分成功、异步／残缺回执、取消、存储故障和浏览器读取。此前[共同日记回执](../experiments/engineering/2026-11-10-shared-diary/receipt.json)中的标记空回复、冷加载超时和模型就绪后通过分别保留，未改写为本轮运行。实际命令、计数、跳过项、日志与源码哈希和保护清单在各轮回执中列明。

研究/共同基础的既有文件以及声明的研究对象按基线逐字节核对。直接 `new ChatOrchestrator(...)` 且未显式设置 `PromptBudget` 的旧驱动保留原提示长度策略；产品工厂采用新预算，因此 **冻结记忆文件未改不等于产品提示与原实验完全一致**。后续基于产品传递路径的测量须记录新策略和配置，已有论文结果不重写、不据工程 PASS 提升研究结论。

内存队列仍会随进程结束而丢失；持久分离部署继续配置 Redis。没有引入 Cordis 热安装、Comma 式任务验收平台、跨进程工具动作事务 outbox、自动平台登录/发帖或自动人格改写。本轮也没有运行新训练、正式研究实验或论文投稿。
