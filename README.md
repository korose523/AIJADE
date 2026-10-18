# AIJADE-next

A long-running AI companion with verifiable, evidence-gated learning and a biomimetic memory, written in .NET.
See [docs/STATUS.md](docs/STATUS.md) for the architecture, feature status and open items, and
[experiments/README.md](experiments/README.md) for the experiments behind the papers. Design ideas for the virtual-character side were drawn from the open-source Project AIRI (see Acknowledgements).

## Build and test

Requires the .NET 10 SDK (pinned in `global.json`).

```bash
dotnet test
```

If the checkout lives on a filesystem that rejects extended attributes (e.g. exFAT), put build output elsewhere:

```bash
AIJADE_ARTIFACTS=$HOME/.cache/aijade-next-artifacts dotnet test
```

Database-backed tests need PostgreSQL (with VectorChord) and Redis; `tools/dev-services.sh` starts both in Docker. Without
`AIJADE_TEST_DATABASE_URL` they are skipped, never reported as passing.

Browser end-to-end tests (`tests/Aijade.E2E`, Playwright + headless Chromium) run the built server as its own process and
walk through sign-up, chat, memory, characters, voice, stage and settings. They are opt-in; the first run downloads
Chromium:

```bash
AIJADE_E2E=1 AIJADE_TEST_DATABASE_URL=postgres://aijade:aijade@127.0.0.1:55432/aijade dotnet test tests/Aijade.E2E
```

Add `AIJADE_E2E_MMD_DIR=<folder>` and `AIJADE_E2E_MMD_MODEL=<file.pmx>` to also test the MMD stage with a model you are
licensed to use. Models are served from that folder and never copied into the repository.

## Reproducing the measurements

Every number in the accompanying papers is computed from the files under `experiments/`; [experiments/README.md](experiments/README.md)
lists each file with the driver that regenerates it. Three studies use this code:

| Study | Artefacts | Main drivers |
|---|---|---|
| Verifiable event-driven architecture and evidence-gated learning | `experiments/p1/`, `experiments/growth-pilot/` | `tools/Aijade.P1` (against a running server and worker), `tools/Aijade.Mutation`, `aijade-experiments growth-pilot` |
| Self-assessment reliability of agent-generated skills | `experiments/rq-c/` | `tools/Aijade.Rqc`, `aijade-experiments p2-models`, `differential`, `format-precheck` |
| Retrieval scoring in the biomimetic memory | `experiments/memory/`, `experiments/memory-longmemeval/` | `aijade-experiments memory`, `memory-uncertainty`, `pool-check`, `delivery-check`, `gating-check`, `longmemeval` |

(`aijade-experiments` is `dotnet run --project tools/Aijade.Experiments -c Release --`.)

- **Re-analysis without a model.** The statistics of the self-assessment study are recomputed from the archived per-step
  logs (`aijade-experiments p2-models`); the memory experiments are deterministic and need only the two third-party
  corpora, which `tools/data/fetch-corpora.sh` downloads and checks against the SHA-256 pinned in the code.
- **Re-running the model runs.** They use Ollama with `qwen2.5-coder:7b-instruct` (weights `dae161e27b0e…`),
  `qwen2.5-coder:1.5b` and `llama3.1:8b` (`46e0c10c039e…`) at temperature 0 with a fixed seed; each run's summary records
  the model digest and the server version, and the scripts in `experiments/rq-c/` (`run-redo.sh`, `run-family-gpu.sh`,
  `run-template.sh`) give the exact flags. Greedy decoding on other hardware changes individual generations, so a re-run
  reproduces the estimates within their uncertainty rather than the trajectory step by step.

## The companion elsewhere

**Chat platforms** — `src/Aijade.Bots` runs the companion on Discord, Telegram, Satori (QQ, OneBot, KOOK … via Koishi),
X, Bilibili live rooms and Minecraft (offline-mode Java Edition 26.3 servers). It signs in to your server with a bot account
and answers through the same conversation pipeline as the apps; memory is kept per person. In Minecraft the companion also
acts on requests that name it, in English or Chinese: *come here* / 过来, *follow me* / 跟着我, *stop* / 停下,
*go to x y z* / 去 x y z, *dig x y z* / 挖 x y z (and picks up what drops), *place x y z* / 放 x y z (with any block in its
hotbar), *pick up* / 捡起来, *attack the pig* / 打猪 (pig, cow, sheep, chicken, zombie, skeleton, creeper, spider, slime),
*where are you* / 你在哪. It walks found paths (steps up one block, drops up to three) at walking speed, digs and places as a
survival player, and respawns after dying.

```bash
Aijade__Server=https://your-server/ Aijade__Token=<bot account token> Telegram__Token=<bot token> dotnet run --project src/Aijade.Bots
```

See `src/Aijade.Bots/Program.cs` for every setting (Discord, Satori, X, Bilibili, Minecraft, drawing, tools, memory).

**MCP** — the server is an MCP server at `/mcp` (talk with the companion, search and add memory, as the calling
account). `integrations/claude-code` connects Claude Code to it.

**Tools** — administrators configure tools the companion may use (Settings → Admin → Tools): external MCP servers,
Home Assistant, Xiaomi Mi Home, Factorio. `src/Aijade.ComputerUse` is an MCP server for computer control; desktop-changing
actions run only if `AIJADE_COMPUTER_USE_ALLOW` allows them. On macOS, `capture` with `mode=som` returns a screenshot with
numbered interface elements (and `mode=ax` the numbered list), so the model can `click` or `set_value` by element number;
this needs the Accessibility permission. Users switch tool use on with the "MCP tools" module.

**Model routes** — besides chat models, the gateway (Settings → Admin → Gateway) takes one route each for speech
(`kind`: `openai`, `elevenlabs`, `aliyun-qwen-tts`, `aliyun-cosyvoice`), images (`openai`, `replicate`, `comfyui`,
`gemini` — Google AI Studio's native API, e.g. `gemini-2.5-flash-image`), embeddings and transcription. For providers
other than OpenAI the route's `voice` takes precedence over the client's.

**Browser and editor** — `integrations/browser-extension` (YouTube / Bilibili: title, position, subtitles) and
`integrations/vscode` (file, language, line; code only if allowed) tell the companion what you are watching or working on,
when the matching module is on.

## Android app

`src/Aijade.Maui` is the same app as a .NET MAUI Blazor Hybrid shell (Android; iOS / Mac Catalyst need Xcode). It needs
the `maui-android` workload, JDK 17 and the Android SDK, and is kept out of `Aijade.slnx`:

```bash
dotnet build src/Aijade.Maui -f net10.0-android -p:JavaSdkDirectory=<jdk17> -p:AndroidSdkDirectory=<android-sdk>
```

A debug APK that is installed with `adb install` (rather than deployed by an IDE) must carry its assemblies; add
`-p:EmbedAssembliesIntoApk=true -p:RuntimeIdentifier=android-x64` (or `android-arm64` for a phone). On first launch the
app asks for the server address; from the Android emulator the host's development server is `http://10.0.2.2:<port>`.

## Acknowledgements

AIJADE referenced the open-source virtual-character / AI-companion project [Project AIRI](https://github.com/moeru-ai/airi)
(MIT). We thank Neko Ayaka and all of its contributors.

## Licence

MIT, © 2026 Zexiao Weng. Third-party components are listed in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).
