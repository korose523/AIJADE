# AIJADE 独立架构与当前功能入口

本轮按作者确认的范围独立实现产品能力，参考 MOSAIC 的职责分工与证据边界，不运行其源码、执行器或整套插件。AIJADE 是情感陪伴与持续交互的主项目；MOSAIC 的连接组研究和具身智能仍是独立项目。MOSAIC 本轮只读核对得到的运行失败、待验证或禁止启动状态，均不计为 AIJADE 完成能力。

完整功能清单见 [FUNCTIONS](FUNCTIONS.md)，机器清单见 [capabilities.json](../configs/companion/capabilities.json)，决定见 [ADR-005](decisions/ADR-005.md)。其中“已有实现”“可配置入口”“待实现”分别列出；有代码、能构建、可访问、真实服务验收和研究资格不互相替代。

七项产品职责是身份、记忆、生活、感知、规划、执行、交付。客户端和机器人宿主复用同一 `CompanionRuntime`；后端维护认证、角色选择、关系/收藏/日记、记忆、场景和交付状态；PostgreSQL 是既有持久权威。宿主保留自己的入站与交付队列，不再建立外部 Agent 或插件主库。

## 当前独立舞台

启用后，`/api/v1/stage` 直接读写本库 `NativeStageStore`，不再请求外部工作台。所有已认证用户拥有各自角色的虚拟场景；其他账户与其他角色不共用状态。写入必须显式指定角色，客户端将查询、写入、回执和后续查询固定在同一角色；中途切换角色不会改变原命令或提醒的目标。命令文本和 ID 有边界，重复 ID 与不同文本冲突，重复请求返回原回执；旧修订返回 409。命令批次全部验证后才提交，未支持的动作不会先写入部分结果。

支持表达参数、文字状态、站立与预定义虚拟位置；位置和姿势属于逻辑场景。跳舞、真实行走、手势运动播放等未完成的执行器明确返回不可用。回执区分 `state_applied`、`renderObserved` 和 `audioPlayed`，不借文字描述推断动作成功。页面中的模型提示也明确为虚拟逻辑状态；实际 MMD 表情应用和音频播放继续使用各自的回执链。

```text
Aijade__Modules__Stage=true
Stage__Enabled=true
```

原 `Stage:WorkbenchUrl`、机器人 `Renderer:MosaicPort` 需要移除；当前代码对这些退役运行配置明确报错，不偷偷继续连接外部项目。旧的 `MosaicStage` 客户端类型和 `mosaicStage` 设置字段仅作兼容转接，页面名称为“AIJADE 虚拟场景”。服务关闭或能力未配置时，聊天仍可独立运行。

## 当前独立语音

自有服务的启动、可配置模型、真实 HTTP 协议及验证见 [本地服务说明](../tools/companion-services/README.md)。它只绑定回环地址，系统命令无 shell，并对文本、WAV、正文、并发、超时与临时文件设限。已有模型目录通过参数选择，推理不自动下载模型。`/health` 明确区分配置、加载与实际请求成功。系统 TTS、个人音色训练、识别质量、对齐、歌声是不同能力，不合并成“语音全部完成”。

网关的 `local` 协议继续兼容 `/tts` 与 `/transcribe`，地址可设为 `http://127.0.0.1:8796`。只启用实际可用的合成/识别路由；本服务 `/align` 和 `/sing` 返回 503。真实系统音频及已有 tiny 权重的 smoke 回执是工程验证，不加入论文语料。

## 目录与验证入口

- `src/Aijade.Client`：共享回复运行库、角色同步、生活与渠道无关的产品逻辑。
- `src/Aijade.Server`：认证 API、领域持久状态、网关、交付与原生场景。
- `src/Aijade.Bots`、`src/Aijade.Integrations`：授权入站、协议适配、限流和平台交付。
- `src/Aijade.UI`、Web、MAUI：用户界面与独立的视觉/语音播放。
- `tools/companion-services`：本库本地媒体服务。
- `src/Aijade.Research`、`experiments`、固定渲染协议适配：独立研究装置及不可改写的历史证据。

```sh
python3 tools/verify-independent-architecture.py
python3 -B -m unittest discover -s tools/companion-services -p 'test_*.py' -v
dotnet test --configuration Release
```

架构守卫检查所有产品项目引用闭合、功能源入口、模块覆盖和跨项目运行调用，并用恶意路径、缺失模块/源码等负控制检验拒绝行为。模型、数据库、浏览器、QQ 和设备是否真实接通由对应运行回执说明；论文独立人工复核、留出设计和后端资格继续保留自己的门槛。
