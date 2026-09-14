<picture>
  <source
    width="100%"
    srcset="./content/public/banner-dark-1280x640.avif"
    media="(prefers-color-scheme: dark)"
  />
  <source
    width="100%"
    srcset="./content/public/banner-light-1280x640.avif"
    media="(prefers-color-scheme: light), (prefers-color-scheme: no-preference)"
  />
  <img width="250" src="./content/public/banner-light-1280x640.avif" />
</picture>

<h1 align="center">AIJADE</h1>

<p align="center">一个由大语言模型驱动的虚拟角色，能跑在浏览器、桌面和口袋里。</p>

<p align="center">
  <a href="../README.md">English</a> ·
  <a href="./README.ja-JP.md">日本語</a> ·
  <a href="./README.ko-KR.md">한국어</a> ·
  <a href="./README.ru-RU.md">Русский</a> ·
  <a href="./README.vi.md">Tiếng Việt</a> ·
  <a href="./README.fr.md">Français</a>
</p>

---

## 这是什么

AIJADE 是一个开源的虚拟角色平台。给它一个模型提供方和一个角色，你就得到一个会说话、会听、会记事、有形象的伙伴——**一套代码，三个前端，共用同一个角色引擎**。

它不是套在某个模型外面的聊天壳。真正有意思的是模型之外的部分：一条端到端跑通的语音链路、一个会随内部状态变化的 3D 形象、一层能跨会话留存记忆的存储，以及一个能从对话里自己学技能的智能体层。

## 平台

| 前端 | 目标平台 | 目录 |
| --- | --- | --- |
| **Web** | 任意现代浏览器 | [`apps/stage-web`](../apps/stage-web) |
| **桌面** | Windows / macOS / Linux（Electron） | [`apps/stage-tamagotchi`](../apps/stage-tamagotchi) |
| **移动** | iOS / Android | [`apps/stage-pocket`](../apps/stage-pocket) |
| **服务端** | Node.js 服务、后台与鉴权界面 | [`apps/server`](../apps/server)、[`apps/ui-admin`](../apps/ui-admin)、[`apps/ui-server-auth`](../apps/ui-server-auth) |

三个角色前端挂载的是同一套共享 UI 层 [`packages/stage-ui`](../packages/stage-ui)，所以角色做一次，各端表现一致。

## 特性

**角色与舞台**
- VRM 模型渲染，支持 `lookAt`、表情与 blendshape（[`packages/stage-ui-three`](../packages/stage-ui-three)），并支持 Live2D 与 Spine
- MMD / PMX / PMD 导入、GLB / glTF 兜底、动作合成融合
- **桌宠模式**：Electron 主窗口本身就是透明、无边框、置顶的宠物——可拖拽，心情与亲密度由实时内部状态渲染
- 全息模式，适配透明投影场景

**语音**
- 全双工语音：ASR 进、TTS 出，收口到单一入口
- 多 TTS 引擎（本地 Kokoro、零样本 IndexTTS2、CosyVoice 适配器）统一接口
- 情绪化合成，并能识别用户语气
- 唤醒词检测与免手操作的智能音箱链路（唤醒 → VAD → ASR → LLM → TTS）

**心智**
- 可插拔记忆后端，含 Postgres/pgvector 实现（[`packages/memory-pgvector`](../packages/memory-pgvector)）
- 仿生双图记忆：情节经验与有证据来源的信念（[`packages/memory-biomimetic`](../packages/memory-biomimetic)）
- 由情感动力学驱动的人格漂移——心情是真实有状态的，不是脚本写的

**智能体层**
- 自动技能创建：从对话中识别可教时刻 → 生成 → 校验 → 注册（[`packages/agent-skill-forge`](../packages/agent-skill-forge)）
- 持续学习：反馈闭环让已注册技能自我演进（[`packages/agent-continuous-learning`](../packages/agent-continuous-learning)）
- 电脑操控：默认 dry-run 后端，真实操控经 MCP 接缝接入（[`packages/agent-computer-use`](../packages/agent-computer-use)）
- 桥接层：把以上能力同构接入对话编排器（[`packages/agent-capabilities`](../packages/agent-capabilities)）

**生态**
- 插件 SDK 与类型化协议（[`packages/plugin-sdk`](../packages/plugin-sdk)、[`packages/plugin-protocol`](../packages/plugin-protocol)），已附带智能家居、媒体、棋类、编码智能体、浏览器等插件
- 聊天平台桥接：Discord、Telegram、Satori、Twitter
- [`services/`](../services) 下的 Minecraft 服务与电脑操控 MCP 服务
- [`engines/`](../engines) 下的 Godot 引擎实验

## 技术栈

| | 版本 |
| --- | --- |
| Node.js | `>=22.0.0` |
| pnpm | `10.33.0`（由 `packageManager` 锁定） |
| Vue | `3.5.32` |
| Vite | `8.0.8` |
| TypeScript | `5.9.3` |
| Electron | `41.2.1` |
| Pinia | `3.0.4` |
| Vue Router | `5.0.4` |
| UnoCSS | `66.6.8` |
| Vitest | `4.1.4` |
| Turbo | `2.9.6` |
| tsdown | `0.21.9` |
| oxlint | `1.60.0` |

pnpm workspace 单体仓库，由 Turborepo 管理。依赖版本通过 [`pnpm-workspace.yaml`](../pnpm-workspace.yaml) 里的 catalog 统一固定。

## 快速开始

需要 **Node.js ≥ 22** 与 **pnpm 10.33.0**（`corepack enable` 会自动取用锁定的版本）。

```bash
pnpm install
```

`postinstall` 会构建 workspace 内的包，所以首次安装耗时较长。

### 运行

```bash
pnpm dev                  # Web 端
pnpm dev:tamagotchi       # 桌面端（Electron）
pnpm dev:pocket:android   # 移动端 Android
pnpm dev:pocket:ios       # 移动端 iOS
pnpm dev:server           # 后端运行时
pnpm dev:docs             # 文档站
```

### 构建

```bash
pnpm build                # 全部包与应用
pnpm build:web            # 仅 Web 端
pnpm build:tamagotchi     # 仅桌面端
pnpm build:packages       # 仅 workspace 包
```

### 检查

```bash
pnpm typecheck            # 全量类型检查
pnpm lint                 # 经 moeru-lint 跑 oxlint + eslint
pnpm test:run             # 单元 / 视觉 / UI 测试套件
```

## 目录结构

```
apps/         各端前端及其后端（Web、桌面、移动、服务端、后台）
packages/     共享库——UI、角色、记忆、智能体、模型、音频、工具链
services/     旁路服务（语音、电脑操控 MCP、聊天桥接、Minecraft）
plugins/      基于插件 SDK 的一方插件
engines/      替代引擎实验
docs/         文档站、产品文档与研究笔记
```

## 文档

- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — 系统整体结构
- [`FEATURES.md`](./FEATURES.md) — 功能清单
- [`AGENT_CAPABILITIES.md`](./AGENT_CAPABILITIES.md) — 智能体能力层
- [`COMPUTER_USE_INTEGRATION.md`](./COMPUTER_USE_INTEGRATION.md) — 电脑操控接入

## 许可证

[MIT](../LICENSE)。
