# @proj-aijade/memory-pgvector

Layered memory engine for AIJADE, with **Scope-Recall** scoped/ranked retrieval.

This module upgrades AIJADE's previous "keep recent turns + compact old turns into a
summary" approach (see `packages/core-agent/src/messages/compaction.ts`) into a
real three-tier memory with semantic, scoped, time-aware recall — inspired by the
companion projects the team studied:

| Reference | Idea adopted |
|-----------|--------------|
| AkaneCompanionLab | 分层记忆：近期原话 → 阶段摘要 → 长期语义，带时间窗与"加固" |
| Hermes Scope-Recall (B 站 BV12ELn6yEmB) | 按作用域过滤 + 加权排序的召回，而非全局 top-K |
| "有活人感和长期记忆的 AI 桌宠" (B 站 BV16PEo6rEXi) | 长期记忆带来"活人感" |

## Tiers

1. **Episodic** — verbatim recent messages (mirrors AIJADE `RawMessage`). Kept until
   compacted or expired (`ttlMs`).
2. **Summary** — compacted windows (mirrors the `summary` history item from
   `compactConversationEntries`, with optional `fromTurnIndex`/`toTurnIndex`).
3. **Long-term** — distilled, embedded facts with a `timeRange` and a `salience`
   (reinforcement) counter, recalled via Scope-Recall.

## Scope-Recall

`recall(query, opts)` ranks long-term memories by:

```
score = cosine_similarity(query, memory) × timeDecay(lastSeen) × reinforcementBoost(salience)
```

- **Scope filter** — only memories tagged with the requested `scopes` are considered.
- **Time decay** — exponential half-life; unseen memories fade.
- **Reinforcement** — each recall bumps `salience` (+1) and `lastSeen`, so frequently
  recalled facts are "consolidated" and rank higher (the AkaneCompanionLab "加固").

Recent episodic + summary context is always included (ranked by recency) so the
current conversation stays available.

## Usage

```ts
import { LayeredMemory } from '@proj-aijade/memory-pgvector'

const memory = new LayeredMemory({
  // production: inject a real embedder + pgvector-backed VectorStore
  // embedder: embeddingsFromXsai,
  // vectorStore: new PgVectorStore(connectionString),
  halfLifeMs: 30 * 24 * 60 * 60 * 1000,
})

await memory.ingestEpisodic('user likes playing minecraft and building redstone', { scope: 'game' })
const [summary] = await memory.compact('game') // → SummaryMemory + distilled long-term facts
const results = await memory.recall('tell me about minecraft', { scopes: ['game'], limit: 5 })
```

The engine is **pure TypeScript with zero runtime dependencies**, so it is fully
unit-testable without a database. The default `createHashEmbedder` is a deterministic
bag-of-words embedder (fine for tests/demos); swap in a real embedding model and a
pgvector `VectorStore` for production.

## Integration points

- `src/engine/` — the testable core (types, embed, vector-store, scope-recall, layered-memory).
- `src/index.ts` — the runtime module entry; instantiates the engine and registers the
  `memory-pgvector` module. The `recall`/`ingest` RPC handlers can be wired to the
  server-sdk module protocol here once the request/response contract is finalised.
- `src/port.ts` — `createLayeredMemoryPort` / `createDefaultLayeredMemory`: the
  AIJADE-facing `MemoryPort` (recall / ingestUser / ingestAssistant / maybeCompact) that
  the chat pipeline consumes without knowing about embeddings or vector stores.
- `src/performance/` — the structured "performance" layer (see below), LPM-1.0 inspired.
- Natural call sites in AIJADE: `compactConversationEntries` (replace/expand with
  `compact`) and the session recall path in `packages/core-agent` / `packages/server-runtime`.

## Real-time pipeline wiring (memory actually runs)

Memory is wired into AIJADE's **live** chat pipeline through AIJADE's own extension points
in `packages/core-agent` — no orchestrator internals are touched:

- `packages/stage-ui/src/stores/chat/memory-performance.ts` bridges the engine to the
  `createChatOrchestratorRuntime({ deps })` call:
  - `createMemoryBridge(port)` injects recalled memory as a `runtimeContextProvider`
    (the **same hook** AIJADE's Minecraft integration uses) and persists every turn into
    the episodic tier via the `onUserMessageAppended` / `onAssistantMessageAppended`
    lifecycle callbacks. Recall is pre-computed per send (FIFO buffer) because the
    providers are synchronous.
  - `createPerformanceBridge(director, onState)` drives a `PerformanceDirector` from the
    orchestrator token hooks (`onTokenLiteral` / `onTokenSpecial` / `onStreamEnd`).
- `packages/stage-ui/src/stores/chat.ts` composes the bridges:

  ```ts
  import { createPerformanceDirector } from '@proj-aijade/memory-pgvector/performance'
  import { createDefaultLayeredMemory, createLayeredMemoryPort } from '@proj-aijade/memory-pgvector/port'

  import { createMemoryBridge, createPerformanceBridge } from './chat/memory-performance'

  const memoryPort = createLayeredMemoryPort(createDefaultLayeredMemory(), { scope: 'chat' })
  const memoryBridge = createMemoryBridge(memoryPort)
  const performanceDirector = createPerformanceDirector()
  const performanceState = ref(performanceDirector.snapshot())
  const performanceBridge = createPerformanceBridge(performanceDirector, s => performanceState.value = s)

  const runtime = createChatOrchestratorRuntime(
    performanceBridge.wrapDeps(memoryBridge.wrapDeps(baseDeps)),
  )
  performanceBridge.registerHooks(runtime)
  ```

> **Install note:** `@proj-aijade/memory-pgvector` was added as a `workspace:^` dependency of
> `stage-ui`, and its `package.json` now exposes source subpaths (`/port`, `/performance`,
> `/engine`). After pulling these changes, run `pnpm install` so the workspace symlink is
> created; the subpath imports resolve to TypeScript sources (no build step required).

## Structured performance layer (LPM-1.0 inspired)

`src/performance/` turns the companion from "text generator" into a *performer*, in the
spirit of **LPM 1.0** (Large Performance Model, arXiv:2604.07823):

- `markers.ts` — a tiny LLM-authorable marker vocabulary (`<|emotion:happy|>`,
  `<|gesture:wave|>`, `<|state:speak|>`, `<|gaze:user|>`, `<|music:calm|>`,
  `<|relation:+1|>`) that rides AIJADE's existing `<|...|>` special-marker stream. The
  orchestrator already strips these from the spoken voice and routes them through the
  `token-special` hook, so the avatar reacts in real time.
- `director.ts` — `PerformanceDirector` is a **three-state machine** (`listen` / `speak`
  / `silence`) plus structured cues (emotion, gesture, gaze, music, relationship delta):
  - `listen` — user is talking; avatar listens (replaces canned idle animation).
  - `speak` — **entered on the FIRST streamed token**, not after the full reply is ready.
    This closes the "artificial silence" gap that makes companions feel like
    "人工智障" (StreamPet / BV1yT96mE6t).
  - `silence` — turn over, alive-idle.
  - Explicit emotion markers *lock* the lexicon guess so the model stays in character.

### Mapping to the four new references

| Reference | What it contributed | Where it lands |
|-----------|---------------------|----------------|
| **HY-Motion 1.0** (arXiv:2512.23464, Tencent-Hunyuan) | Text→3D *body* motion via DiT + Flow Matching. **Offline batch only**, no real-time, no facial/emotion control. | `gesture` markers are the natural offline hook for HY-Motion (generate body motion from `<|gesture:…|>` later, in a batch pipeline). Not wired live — it is not a real-time driver. |
| **LPM 1.0** (arXiv:2604.07823 + site) | Conversation = performance; `[Listen]/[Speak]/[Silence]` real-time states; multimodal control (text→action/emotion, audio→speak/listen, image→identity); causal streaming for infinite-length, identity-stable generation. | The whole `src/performance/` design + the three-state machine + multimodal marker vocabulary. |
| **large-performance-model.github.io** | Project page: "human-like performance", nuanced micro-expressions, real-time listening generation replacing canned animations. | Reinforces the `listen`/`silence` states + micro-expression-first design. |
| (earlier) AkaneCompanionLab / Hermes Scope-Recall / BV16 | Layered memory + scoped recall. | `src/engine/` (done previously) + `src/port.ts`. |

## Scripts

```bash
pnpm --filter @proj-aijade/memory-pgvector test       # vitest
pnpm --filter @proj-aijade/memory-pgvector typecheck  # tsc --noEmit
```

## Avatar integration (performance → VRM expressions)

The structured `PerformanceState` does not stop at the orchestrator — it is
forwarded all the way to the 3D avatar so facial expression + real-time state
react to the *streamed* reply, not just the finished one. This is the
"角色表现力结构化" payoff.

**Prop chain (no `stage-ui` import from `stage-ui-three`):**

```
chat store `performanceState`  (ref<PerformanceState>)
   └─ Stage.vue           :performance-state="performanceState"
        └─ ThreeScene      :performance-state="props.performanceState"   (stage-ui-three)
             └─ VRMModel    :performance-state="props.performanceState"  (stage-ui-three)
                  └─ useAvatarAnimation(vrm, mixer, [], emote).applyPerformance(state)
                       └─ useVRMEmote.setEmotion(...) → VRM expressionManager
```

**What `useAvatarAnimation` does with each snapshot** (`packages/stage-ui-three/
src/composables/vrm/use-avatar-animation.ts`):

- `state` → body/clip state machine:
  - `listen` → `listen` (avatar in a listening posture; expression reset to `neutral`).
  - `speak`  → `speak` (entered on the first token — closes the silence gap).
  - `silence`→ `speak-end` (back to idle; expression reset to `neutral`).
  - Clip transitions are **safe no-ops** when the named `AnimationClip` is not
    loaded (today only the idle clip ships), so the avatar simply keeps idling.
- `emotion` → VRM emote preset (only applied on *change*, so streaming token
  flicker does not thrash the face):

  | PerformanceEmotion | VRM emote |
  |--------------------|-----------|
  | `happy` / `loving` | `happy` |
  | `sad` / `worried`  | `sad` |
  | `angry`            | `angry` |
  | `surprised`        | `surprised` |
  | `thinking`         | `think` |
  | `calm` / `neutral` | `neutral` |

- `gesture` → a brief emote pulse (`setEmotionWithResetAfter`, ~2.5 s) mapped by
  name (`wave`/`cheer`/`celebrate`/`agree`/`nod` → `happy`, `disagree` → `angry`,
  `shrug` → `sad`, `point` → `surprised`). This is the stop-gap until real gesture
  clips (e.g. from HY-Motion) are wired as offline batch motion.

**Re-run note:** `stage-ui-three` now also declares `@proj-aijade/memory-pgvector`
as a `workspace:^` dependency (type-only import of `PerformanceState`), so the
`pnpm install` above also links it for the 3D package.

