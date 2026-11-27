# AIJADE-next

A long-running AI companion with verifiable, evidence-gated learning and a biomimetic memory, written in .NET.
See [docs/STATUS.md](docs/STATUS.md) for the architecture, feature status and open items, and
[experiments/README.md](experiments/README.md) for the experiments behind the papers. Design ideas for the virtual-character side were drawn from the open-source Project AIRI (see Acknowledgements).

## Project scope

AIJADE's primary development line is emotional companionship: conversation, initiative, a fictional daily life,
relationship state, photos, voice and a private media collection. The author prioritises completing AIJADE.
MOSAIC focuses on connectome research and embodied intelligence; the projects may borrow useful product ideas.
[ADR-004](docs/decisions/ADR-004.md) supersedes the previous research-first/product-maintenance priority.
Web and QQ share the selected character, life/location profile, relationship, media collection and explicitly saved diary excerpts through the server.
See [the complete capability inventory](docs/FUNCTIONS.md) and [independent architecture](docs/INDEPENDENT-ARCHITECTURE.md) for current ownership boundaries, configuration and research version separation.

See [the companion setup and sync guide](docs/COMPANION.md) for pairing, live changes, media and optional local services.

The existing dissertation apparatus and archived results remain separate. Product data is never used as research data,
and the measured memory sources remain frozen. [PROJECT-SCOPE](docs/PROJECT-SCOPE.md) and
[configs/project-scope.json](configs/project-scope.json) preserve module dependency boundaries, checked by
`ProjectScopeTests`. The shared persona/initiative contract ([ADR-002](docs/decisions/ADR-002.md)) and selective migration
of MOSAIC product functions ([ADR-003](docs/decisions/ADR-003.md)) continue to apply. New product functionality and
passing engineering checks do not change scientific gates or manuscript readiness.

Research methods, original requests and replies, failures and verification receipts are indexed in
[experiments](experiments/README.md), including the [Mac model preflight](experiments/mac-preflight/2026-11-09-7b8b/README.md)
and [engineering regressions and local-model product checks](experiments/engineering/2026-11-10-shared-diary/receipt.json).
Development preflights do not replace primary studies or establish prior public registration.

The [Chapter 7 research adapter](experiments/ch7/README.md) now has separately
archived retrieval-led development evidence: actual memory content selects a
frozen program before execution and rendering, and each original test database
continues into state/write-back/reuse. Ten known C2 cases are retained with the
failed initialization attempt and a semantic counterexample. This supplies no
C1/C2 effect, held-out result or product automatic-learning claim.

A later [paired development comparator](experiments/ch7/paired-development-2026-11-12/README.md)
qualifies the strong module-local baseline and fixed scoring on the same known
cases. C1 preserves admission, execution, promotion gates, idempotency and
revocation; C2 adds the cross-record joins and shared transaction. All twenty
case/arm records, fixed denominators and both audit/regression corrections are
retained. These are designed development contrasts, without held-out inference.

The held-out comparison followed on 21 November 2026. The Mac qualification
met both approved criteria on its seventh attempt, after four recorded
deviations, and the 40-pair comparison completed on its second launch, after
a fifth. Both launches used the time limits of the qualification's execution
plan (1,800 s per block, 600 s for the renderer, no resource thresholds) in
place of the frozen plan's block and overall limits, memory and swap stops and
120-second unloaded admission window; the launch record stated these limits
before the first launch without calling them a deviation, and the supervisor's
review of 27 November 2026 numbers this as the sixth deviation. Under C1, 12 of 28
scheduled windows had a wrong durable promotion
and 8 of 32 had a wrong reuse in round 2; under C2 both counts were 0. The 8
wrong reuses are cases that C1 wrongly promoted in round 1, and no case was
stopped in round 2 by C2 alone. The supervisor accepted both results on 23
November 2026, the qualification on condition that the renderer change is
public; that change was published in `f620d32`, and the review of 27 November
2026 keeps the approval of both results. The result concerns these 40
constructed pairs and is not a population estimate.

As of 27 November 2026 the records of these Chapter 7 runs and of the P2-R
regenerations (re-runs of three archived model runs, see "Reproducing the
measurements") are not on `main`. Those of Chapter 7 are on
`research/ch7-mac-qualification-20261121` (`cb7033f`, `99807a5`, `f620d32`).
The P2-R records of host 2 (19 November 2026, a deviation record) and of the
department server (24 November 2026, with deviations; on 27 November 2026 the
supervisor decided to use group A once three steps are done, to keep group B
exploratory and not to rerun P2-R; see "Decision of 27 November 2026" in
[its README](experiments/rq-c/department-20261124/README.md#decision-of-27-november-2026))
are on `live2d-chat-stability-20261118`, under
`experiments/rq-c/host2-local-20261119/` and
`experiments/rq-c/department-20261124/`.

## Runtime composition

The [architecture guide](docs/ARCHITECTURE.md) records the checked DeepSeek Harness, superagent, Comma and companion-plugin
references and their mapping to the implementation. Web/native apps, chat connectors and MCP compose capabilities through
`CompanionRuntime`; ordinary chat, first lines and reminders share reply streaming and persistence. Explicit companion media
commands use that entry point too. Optional modules are named, switchable and isolated from one another's failures.

The [30-project companion reference catalogue](docs/COMPANION-REFERENCES.md) pins source and licence checks; third-party
plugins were not installed or copied. The [system overview](docs/architecture/overview.png) and
[message flow](docs/architecture/turn-flow.png) are rendered from editable Mermaid in the architecture guide.
Product turns keep a stable module selection, bound optional prompt/history size and stop further tools after an
uncertain tool outcome. Character limits are configurable and are not model-token or real-model speed guarantees.

`/diary save` stores a completed exchange using server-checked source messages; `/diary` reads today's excerpts.
The companion page reads and forgets the same account-and-character diary. Forgetting an excerpt retains the original
chat. This is mutable product data, and an assistant's saved words are not independent research evidence.
The [optional local-model check](docs/COMPANION.md) records real replies and readiness separately from controlled-provider
regressions; cold-start failures and marker-only responses are kept in the engineering records.

Ordinary QQ replies, proactive first messages, due reminders and shared-runtime commands attach a stored message identity to a bounded delivery log.
Text, image and audio parts require complete platform acknowledgements; uncertain results or failed observation writes
stop later parts without an automatic resend. The companion page shows these records. Acceptance by the platform is
distinct from recipient delivery or reading. The Web view labels reply origins and reminder identities. Consuming a stored reminder line remains separate from platform acceptance; retained attempts prevent redispatch of the same stored source.

For a companion deployment, configure the existing PostgreSQL and model gateway, then run `tools/run-companion.sh`.
It keeps the core, shared memory and evidence pipeline, and mounts MCP, external tools, the AIJADE-owned virtual scene and billing only
when selected. The existing `full` profile remains the default for deployment and research compatibility. No new service stack,
package dependency or .NET project is required.

## Build and test

Requires the .NET 10 SDK (pinned in `global.json`).

```bash
dotnet test
```

Use the workspace launcher to keep build outputs, corpora, temporary files and tool caches in this checkout:

```bash
tools/with-workspace-env.sh dotnet test
```

When code, manuscripts and research files share a parent workspace, set `AIJADE_WORKSPACE_ROOT` to that absolute directory.
The default working directories are under its `.runtime/`; `AIJADE_ARTIFACTS` and `AIJADE_DATA_DIR` may select other
directories inside the workspace. Parent traversal and existing symlinks that resolve outside it are refused.
`tools/run-companion.sh` and `tools/data/fetch-corpora.sh` use this environment automatically. This controls their local
file locations and does not sandbox arbitrary commands. Database services and browser tests still need their own checks.

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

The chat stage can also load an installed Live2D package on loopback. See the [local Live2D setup](docs/LIVE2D-LOCAL.md).

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
  `run-template.sh`) give the exact flags. A re-run does not reproduce the trajectory step by step: in every
  regeneration made so far, some generated programs differ from those of the archived run. Three archived runs (the
  second-family control and the two prompt-template runs) were regenerated on host 2 under a newer service version on
  19 November 2026 (a deviation record) and on the department server on 24 November 2026 (group A under the archived
  service version and the exploratory group B under the newer one, with deviations). On 27 November 2026 the supervisor
  decided to use group A after the source commits and records left on site are retrieved and checked, the commits are
  published and both groups are re-scored; until then no number from these regenerations enters the P2 manuscript or
  Chapter 5 of the dissertation, and group B never enters P2.

## The companion elsewhere

**Chat platforms** — `src/Aijade.Bots` runs the companion on Discord, Telegram, QQ (through NapCat's OneBot 11, answering
only the owner's private messages), Satori (QQ, OneBot, KOOK … via Koishi), X, Bilibili live rooms and Minecraft
(offline-mode Java Edition 26.3 servers). It signs in to your server with a bot account and answers through the same
conversation pipeline as the apps; memory is kept per person. In private chats on QQ and Telegram she keeps the reminders
she promises ("十分钟后提醒我喝水") and sends them when they are due. In Minecraft the companion also
acts on requests that name it, in English or Chinese: *come here* / 过来, *follow me* / 跟着我, *stop* / 停下,
*go to x y z* / 去 x y z, *dig x y z* / 挖 x y z (and picks up what drops), *place x y z* / 放 x y z (with any block in its
hotbar), *pick up* / 捡起来, *attack the pig* / 打猪 (pig, cow, sheep, chicken, zombie, skeleton, creeper, spider, slime),
*where are you* / 你在哪. It walks found paths (steps up one block, drops up to three) at walking speed, digs and places as a
survival player, and respawns after dying.

```bash
Aijade__Server=https://your-server/ Aijade__Token=<bot account token> Telegram__Token=<bot token> dotnet run --project src/Aijade.Bots
```

See `src/Aijade.Bots/Program.cs` for every setting (Discord, OneBot, Satori, X, Bilibili, Minecraft, drawing, tools, memory, reminders).

**MCP** — the server is an MCP server at `/mcp` (talk with the companion, search and add memory, as the calling
account). `integrations/claude-code` connects Claude Code to it.

**Tools** — administrators configure tools the companion may use (Settings → Admin → Tools): external MCP servers,
Home Assistant, Xiaomi Mi Home, Factorio. `src/Aijade.ComputerUse` is an MCP server for computer control; desktop-changing
actions run only if `AIJADE_COMPUTER_USE_ALLOW` allows them. On macOS, `capture` with `mode=som` returns a screenshot with
numbered interface elements (and `mode=ax` the numbered list), so the model can `click` or `set_value` by element number;
this needs the Accessibility permission. Users switch tool use on with the "MCP tools" module.

**Model routes** — besides chat models, the gateway (Settings → Admin → Gateway) takes one route each for speech
(`kind`: `openai`, `elevenlabs`, `aliyun-qwen-tts`, `aliyun-cosyvoice`, or `local` for AIJADE's own loopback voice service on the same
machine), images (`openai`, `replicate`, `comfyui`, `gemini` — Google AI Studio's native API, e.g.
`gemini-2.5-flash-image`), embeddings, transcription (also `local`) and alignment (`local` only: each Chinese character of
a spoken reply timed, so that the stage's mouth follows the text). For providers other than OpenAI the route's `voice`
takes precedence over the client's.

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

The [relocated runtime archive](experiments/ch7/relocated-runtime-2026-11-16/README.md)
retains project-local dependency restoration, complete Mac regressions, the
before-window binary freeze and one refused known-input admission. Its memory
and swap conditions passed; the frozen Ollama process-name condition did not.
In that archive the full finite driver is unqualified and the confirmed
held-out comparison is NOT_RUN. The Mac qualification under the two criteria
that the supervisor approved and the 40-pair comparison were completed later,
on 21 November 2026 (see "Project scope" above). The archive verifier is
offline and cannot launch or retry a study.

## Licence

MIT, © 2026 Zexiao Weng. Third-party components are listed in [THIRD-PARTY-NOTICES.md](THIRD-PARTY-NOTICES.md).

## Retained typed-lifecycle backend refusal

The [17 November lifecycle archive](experiments/ch7/mac-lifecycle-2026-11-17/README.md) adds typed persistent controllers, parent-held identity gates for finite children, actual parent waits, scoped discovered-descendant ledgers and fixed monotonic phase scheduling. The sole actual window stops during settling:294 raw process-predicate PASS records,293 streaming-validated records and300 required; the final capture completes after the fixed600-second deadline. Admission never starts and all20 known conditions remain unattempted. Earlier UNKNOWN rows and refusals are retained.

Complete offline replay and twelve effective, coherently manifested archive-corruption controls validate the terminal evidence. They do not qualify the full backend, the current independent companion product or the confirmed 40-pair held-out comparison. On 17 November 2026 Table 7.3 was NOT_RUN, and the lifecycle attempt of that day generated no fresh seed or replacement window. Product main preserves its later independent companion implementation and materializes exact research Q separately for historical verification.


## Native READY engineering refusal (E6)

The E6 attempt retained 168 settling records: 167 PASS and one UNKNOWN. Its final complete service was 2.245 seconds against the fixed 2-second ceiling, and the after-listener whole call was 0.581 seconds against 0.5; no nested controller was reached. See the [Native READY evidence and boundaries](experiments/ch7/native-ready-2026-11-18/README.md) and the [fixed S6 research archive and code](https://github.com/korose523/AIJADE/tree/5b741633150b636ed9747e0638fd4792297bc0bc). At the date of that archive (18 November 2026), backend qualification, seed construction and the confirmed 40-pair comparison were unexecuted. The Mac qualification under the two criteria that the supervisor approved, the construction of the held-out cases and the 40-pair comparison followed on 21 November 2026, on branch `research/ch7-mac-qualification-20261121`. Current product main does not inherit research qualification.
