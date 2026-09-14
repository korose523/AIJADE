<picture>
  <source
    width="100%"
    srcset="./docs/content/public/banner-dark-1280x640.avif"
    media="(prefers-color-scheme: dark)"
  />
  <source
    width="100%"
    srcset="./docs/content/public/banner-light-1280x640.avif"
    media="(prefers-color-scheme: light), (prefers-color-scheme: no-preference)"
  />
  <img width="250" src="./docs/content/public/banner-light-1280x640.avif" />
</picture>

<h1 align="center">AIJADE</h1>

<p align="center">An LLM-powered virtual character that runs in your browser, on your desktop, and in your pocket.</p>

<p align="center">
  <a href="./docs/README.zh-CN.md">简体中文</a> ·
  <a href="./docs/README.ja-JP.md">日本語</a> ·
  <a href="./docs/README.ko-KR.md">한국어</a> ·
  <a href="./docs/README.ru-RU.md">Русский</a> ·
  <a href="./docs/README.vi.md">Tiếng Việt</a> ·
  <a href="./docs/README.fr.md">Français</a>
</p>

<p align="center">
  <a href="./LICENSE"><img src="https://img.shields.io/github/license/korose523/AIJADE.svg?style=flat&colorA=080f12&colorB=1fa669"></a>
  <a href="./package.json"><img src="https://img.shields.io/badge/node-%3E%3D22-1fa669.svg?style=flat&colorA=080f12&colorB=1fa669"></a>
  <a href="./package.json"><img src="https://img.shields.io/badge/pnpm-10.33.0-1fa669.svg?style=flat&colorA=080f12&colorB=1fa669"></a>
</p>

---

## What it is

AIJADE is an open-source virtual character platform. Give it an LLM provider and a character, and you get a companion that talks, listens, remembers and has a face — one codebase with three front-ends sharing the same character engine.

It is not a chat wrapper around a single model. The interesting part is everything around the model: a voice pipeline that runs end to end, a 3D character that reacts to internal state, a memory layer that survives across sessions, and an agent layer that can learn new skills from conversation.

## Platforms

| Front-end | Target | Directory |
| --- | --- | --- |
| **Web** | Any modern browser | [`apps/stage-web`](./apps/stage-web) |
| **Desktop** | Windows / macOS / Linux (Electron) | [`apps/stage-tamagotchi`](./apps/stage-tamagotchi) |
| **Mobile** | iOS / Android | [`apps/stage-pocket`](./apps/stage-pocket) |
| **Server** | Node.js service, admin and auth UIs | [`apps/server`](./apps/server), [`apps/ui-admin`](./apps/ui-admin), [`apps/ui-server-auth`](./apps/ui-server-auth) |

All three character front-ends mount the same shared UI layer, [`packages/stage-ui`](./packages/stage-ui), so a character built once behaves the same everywhere.

## Highlights

**Character and stage**
- VRM model rendering with `lookAt`, expressions and blend shapes ([`packages/stage-ui-three`](./packages/stage-ui-three)), plus Live2D and Spine support
- MMD / PMX / PMD import, GLB / glTF fallback, and motion synthesis blending
- Desktop-pet mode: the Electron window itself becomes a transparent, frameless, always-on-top pet — draggable, with mood and intimacy rendered from live internal state
- Hologram mode for transparent projection setups

**Voice**
- Full-duplex speech: ASR in, TTS out, behind a single entry point
- Multiple TTS engines (local Kokoro, zero-shot IndexTTS2, CosyVoice adapters) behind one interface
- Emotion-aware synthesis, and listening-side emotion detection for the user's tone
- Wake-word detection and a hands-free smart-speaker pipeline (wake → VAD → ASR → LLM → TTS)

**Mind**
- Pluggable memory backends, including a Postgres/pgvector store ([`packages/memory-pgvector`](./packages/memory-pgvector))
- Biomimetic dual-graph memory for episodic experience and evidence-sourced beliefs ([`packages/memory-biomimetic`](./packages/memory-biomimetic))
- Continuous persona drift driven by affect dynamics, so mood is genuinely stateful rather than scripted

**Agent layer**
- Automatic skill creation: detect a teachable moment in conversation, generate a skill, validate and register it ([`packages/agent-skill-forge`](./packages/agent-skill-forge))
- Continuous learning with feedback loops that let registered skills evolve ([`packages/agent-continuous-learning`](./packages/agent-continuous-learning))
- Computer use with a dry-run backend by default and an MCP seam for real control ([`packages/agent-computer-use`](./packages/agent-computer-use))
- One bridge that wires all of the above into the chat orchestrator ([`packages/agent-capabilities`](./packages/agent-capabilities))

**Ecosystem**
- A plugin SDK with a typed protocol ([`packages/plugin-sdk`](./packages/plugin-sdk), [`packages/plugin-protocol`](./packages/plugin-protocol)) and shipped plugins for smart home, media, chess, coding agents and the browser
- Chat platform bridges: Discord, Telegram, Satori, Twitter
- A Minecraft service and a computer-use MCP server under [`services/`](./services)
- An optional Godot-based engine experiment under [`engines/`](./engines)

## Tech stack

| | Version |
| --- | --- |
| Node.js | `>=22.0.0` |
| pnpm | `10.33.0` (pinned via `packageManager`) |
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

A pnpm workspace monorepo managed with Turborepo. Dependency versions are pinned through catalogs in [`pnpm-workspace.yaml`](./pnpm-workspace.yaml).

## Getting started

Requires **Node.js ≥ 22** and **pnpm 10.33.0** (`corepack enable` picks up the pinned version).

```bash
pnpm install
```

`postinstall` builds the workspace packages, so the first install takes a while.

### Run

```bash
pnpm dev                  # web client
pnpm dev:tamagotchi       # desktop app (Electron)
pnpm dev:pocket:android   # mobile, Android
pnpm dev:pocket:ios       # mobile, iOS
pnpm dev:server           # backend runtime
pnpm dev:docs             # documentation site
```

### Build

```bash
pnpm build                # all packages and apps
pnpm build:web            # web client only
pnpm build:tamagotchi     # desktop app only
pnpm build:packages       # workspace packages only
```

### Check

```bash
pnpm typecheck            # typecheck all packages and apps
pnpm lint                 # oxlint + eslint via moeru-lint
pnpm test:run             # unit, visual and UI test suites
```

## Repository layout

```
apps/         front-ends and their backends (web, desktop, mobile, server, admin)
packages/     shared libraries — UI, character, memory, agent, model, audio, tooling
services/     side services (speech, computer-use MCP, chat bridges, Minecraft)
plugins/      first-party plugins built on the plugin SDK
engines/      alternative engine experiments
docs/         documentation site, product docs and research notes
```

## Documentation

- [`docs/ARCHITECTURE.md`](./docs/ARCHITECTURE.md) — how the system fits together
- [`docs/FEATURES.md`](./docs/FEATURES.md) — feature inventory
- [`docs/AGENT_CAPABILITIES.md`](./docs/AGENT_CAPABILITIES.md) — the agent capability layer
- [`docs/COMPUTER_USE_INTEGRATION.md`](./docs/COMPUTER_USE_INTEGRATION.md) — computer-use integration

## License

[MIT](./LICENSE).
