# 用 MOSAIC 原生 MMD 客户端作为 AIJADE 的外部渲染器

MOSAIC（作者的另一项目）的原生 Godot 客户端实现了 AIJADE 渲染器契约。AIJADE-next 实现了这一契约的发送端：陪伴者每轮回复产生的 PEF PerformanceIntent，经 UDP 驱动 MOSAIC 客户端中的 MMD 角色。

## 契约（以 MOSAIC `host-dotnet/Mosaic.Scene.Core/AijadePackets.cs` 为准）

- **传输**：每个 UDP 数据报装一个 JSON 对象，不超过 8 KiB，目标为 `127.0.0.1:PORT`（MOSAIC 的 `--behavior-live PORT`）。
- **基础字段**：
  - 必需：`run_id`、`seq`、`t_sim`、`schema_version`（v1.x）。
  - 可选：`episode_id`、`trace_id`、`dt_ms`。
  - 每种包类型构成一条流：`seq` 必须严格递增，`t_sim` 不得倒退，否则该包被丢弃；跳号计为缺口。
- **`AffectToAvatarPacket`**：
  - `avatar_emotion_vector` 与 `avatar_emotion_semantics`：valence −1…1，arousal、dominance、curiosity 0…1。
  - 可选 `mmd_morph_targets`：权重 0…1，0–100 量程会被拒收。
  - 可选 `animation_state_hint`。
- **`ControlToAvatarPosePacket`**：
  - `pose_params` 与 `pose_semantics`：取值 −1…1，对应 head_yaw ±60°、head_pitch ±30°、head_roll ±30°、lean ±20°。
  - `locomotion_mode`：只渲染 `idle`。
- **字段白名单**：白名单外的字段一律拒收。渲染器无法表现的语义会如实列为 unmapped，而不是被猜测处理。
- **`RenderStatePacket`**：渲染器每显示一帧新包，就记一行（会话结束时写入 `aijade-render-state.jsonl`），内容包括所消费包的 trace_id、实际应用的 morph 与骨骼、`missing_keys`、`unmapped` 和 `applied_params_hash`。渲染器不会回写情感或控制链路。

## AIJADE-next 侧

- `Aijade.Integrations.Renderer.AijadeRendererPackets`：把 PerformanceIntent 映射为两种包。trace_id 取 intent id，用于事后把 RenderState 与 intent 配对。
  - 情绪向量直接取自 PEF。
  - 姿态由 PEF 的 posture 与 gaze 通道查一张固定的小表得到（如 thinking 时视线短暂移开、leaning_in 时前倾）。映射是确定的：同一 intent 总是生成同样的包。
- `AijadePacketStamper`：负责加盖 run_id、按类型递增的 seq、单调的 t_sim 和 v1.0。
- `MosaicRendererLink`：通过 UDP 发送，并检查 8 KiB 上限。
- `RenderStateReceipts`：把 `aijade-render-state.jsonl` 读成每个 intent 的渲染回执（实际应用的参数与渲染器自己的哈希）。哈希可由行内参数重算核对。
- **Bots 宿主**：配置 `Renderer:MosaicPort=PORT` 后，Discord、Telegram、Minecraft 等渠道里的每轮回复都会驱动 MOSAIC 中的角色。渲染器不可达时不影响回复。

## 验证

- `RendererLinkTests`：
  - 包结构与取值范围、字段白名单、seq 与 t_sim 单调、回环 UDP 收发、RenderState 读取与哈希重算。
  - **MOSAIC 真实解析器一致性**（需设 `AIJADE_MOSAIC_CORE_DLL` 指向已构建的 `Mosaic.Scene.Core.dll`，从临时副本只读加载）：全部 DialogueAct 生成的包都被 `AijadePackets.Translate` 接受，没有任何字段被报告为 unmapped，`AijadeSequence` 也全部接受。
- 尚未做的：与运行中的 MOSAIC 客户端联机渲染（需在 MOSAIC 仓库内构建、启动 Godot 客户端，按其研究隔离规则由作者决定何时运行）。

## 同时借鉴的陪伴行为（Web 舞台）

参照 MOSAIC 原生客户端的陪伴行为层，AIJADE-next 的 MMD 舞台新增以下行为（`tools/mmd-bundle/mmd-backend.src.js`），由 E2E 测试 `D_the_mmd_companion_shows_its_mood_…` 用真实模型验证：

- **情绪姿态**：负效价且低支配时，上半身与颈部前倾；正效价且高支配时挺直。按 600 ms 半衰期缓动，回执中记为 `posture.lean`。
- **倾听点头**：用户说完一句（至少 1.2 秒）、停顿约 250 ms 后点头，每三次中有一次点两下；陪伴者自己说话时不点头。
- **对话眼神**：说话时每 2.5–5 秒短暂移开视线 0.35–0.7 秒。
- **实现细节**：偏移写入运行时持有的同一个四元数对象，叠加在待机动作之上。低帧率时点头按慢动作播放，不会被整段跳过。内置头像也会做倾听点头。麦克风模块通过 `aijade-user-speech` 窗口事件通知舞台，不经过 .NET 往返。
