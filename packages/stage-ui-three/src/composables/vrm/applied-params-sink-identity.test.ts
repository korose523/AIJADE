import { describe, expect, it } from 'vitest'

/**
 * The render-receipt sink is an `InjectionKey` (a `Symbol`). `Stage.vue` imports it
 * via the **package path** (`@proj-aijade/stage-ui-three/composables/vrm`) while
 * `VRMModel.vue` imports it via a **relative path** (`../../composables/vrm/use-avatar-animation`).
 *
 * `provide`/`inject` only connect when both sides resolve to the SAME module instance
 * (the SAME `Symbol`). If the two specifiers resolve to two different module instances
 * (e.g. one via `src`, one via `dist`), `inject(key, () => {})` silently falls back to the
 * no-op default and the entire receipt chain dies — while every other test and typecheck
 * stays green. This test pins the two imports to the same value.
 *
 * If this assertion ever fails, DO NOT paper over it: report the two resolved absolute
 * paths so the ambiguity can be eliminated at the source.
 *
 * NOTE: the package-path specifier resolves to `composables/vrm/index.ts`, whose barrel
 * re-exports `lip-sync` → `wlipsync`, which references the browser-only `AudioWorkletNode`.
 * That global does not exist in the node test runtime, so we stub it (and guard the stub so
 * it never clobbers a real implementation) purely to let the module graph load — this is
 * test-environment plumbing, NOT masking the identity assertion below.
 */
;

(globalThis as unknown as { AudioWorkletNode?: unknown }).AudioWorkletNode
  ??= class AudioWorkletNode {}

const { appliedParamsSinkKey: viaPackage } = await import('@proj-aijade/stage-ui-three/composables/vrm')
const { appliedParamsSinkKey: viaRelative } = await import('./use-avatar-animation')

describe('appliedParamsSinkKey — cross-import module identity', () => {
  it('package-path and relative-path imports resolve to the same InjectionKey instance', () => {
    expect(viaPackage).toBe(viaRelative)
  })
})
