<script setup lang="ts">
import type { ExpressionCueId } from '@proj-aijade/stage-ui/constants/expression-grammar'
import type { PersonalityLpm } from '@proj-aijade/stage-ui/constants/personality-lpm'

import {
  AIJADE_EXPRESSION_GRAMMAR,
  findExpressionCue,
} from '@proj-aijade/stage-ui/constants/expression-grammar'
import {
  clampLpm,
  DEFAULT_AIJADE_LPM,
  PERSONALITY_LPM_DIMS,
  PERSONALITY_LPM_LABELS,
} from '@proj-aijade/stage-ui/constants/personality-lpm'
import { useSettingsStageModel } from '@proj-aijade/stage-ui/stores/settings/stage-model'
import { Checkbox, FieldRange } from '@proj-aijade/ui'
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

/**
 * Persona payload is written ONLY when the user actually interacts.
 *
 * Legacy cards carry `undefined` for both fields. We display the design-doc
 * baseline (`DEFAULT_AIJADE_LPM` / no cues) as a *view* fallback, but we must
 * not persist that baseline into the card on mere render — otherwise opening
 * the tab once would silently freeze a default that
 * `resolveAijadeExtension()` is supposed to supply.
 */
const selectedPersonality = defineModel<PersonalityLpm | undefined>('selectedPersonality', { required: true })
const selectedExpressionGrammar = defineModel<ExpressionCueId[] | undefined>('selectedExpressionGrammar', { required: true })

/** Display values: stored value if present, otherwise the design-doc baseline. */
const lpmValues = computed<PersonalityLpm>(() => selectedPersonality.value ?? DEFAULT_AIJADE_LPM)

const enabledCues = computed<Set<ExpressionCueId>>(
  () => new Set(selectedExpressionGrammar.value ?? []),
)

/** Localised dimension label, falling back to the constant's English name. */
function lpmLabel(dim: keyof PersonalityLpm): string {
  const key = `settings.pages.card.persona.dims.${dim}`
  const translated = t(key)
  return translated === key ? PERSONALITY_LPM_LABELS[dim] : translated
}

function setDim(dim: keyof PersonalityLpm, value: number) {
  // clampLpm fills the other dimensions from the stored value (or the baseline
  // when nothing is stored yet), so we never emit a partially-populated object.
  selectedPersonality.value = clampLpm({ ...lpmValues.value, [dim]: value })
}

function setCueEnabled(id: ExpressionCueId, enabled: boolean) {
  const next = new Set(enabledCues.value)
  if (enabled)
    next.add(id)
  else
    next.delete(id)
  // Preserve the grammar table's declaration order so the stored array is
  // stable (and therefore diffable / replayable) regardless of click order.
  selectedExpressionGrammar.value = AIJADE_EXPRESSION_GRAMMAR
    .map(cue => cue.id)
    .filter(cueId => next.has(cueId))
}

function cueLabel(id: ExpressionCueId): string {
  const key = `settings.pages.card.persona.grammar.${id}.label`
  const translated = t(key)
  return translated === key ? (findExpressionCue(id)?.label ?? id) : translated
}

function cueTrigger(id: ExpressionCueId): string {
  const key = `settings.pages.card.persona.grammar.${id}.trigger`
  const translated = t(key)
  return translated === key ? (findExpressionCue(id)?.trigger ?? '') : translated
}

// ── Read-only model asset identity ───────────────────────────────────────────
// Shown for traceability: a rendered performance can only be reproduced if the
// model asset identity is known alongside the applied parameters.
const stageModelStore = useSettingsStageModel()

const assetFormat = computed(() => stageModelStore.stageModelSelectedDisplayModel?.format ?? undefined)
const assetHash = computed(() => stageModelStore.stageModelAssetVersionHash)
</script>

<template>
  <div class="flex flex-col gap-6">
    <!-- Superpersona LPM ─ six continuous dimensions -->
    <section class="flex flex-col gap-4">
      <div class="flex flex-col gap-1">
        <div class="text-sm font-semibold">
          {{ t('settings.pages.card.persona.sections.lpm') }}
        </div>
        <div class="text-xs text-$text-secondary">
          {{ t('settings.pages.card.persona.sections.lpm_hint') }}
        </div>
      </div>

      <FieldRange
        v-for="dim in PERSONALITY_LPM_DIMS"
        :key="dim"
        :model-value="lpmValues[dim]"
        :min="0"
        :max="1"
        :step="0.05"
        :label="lpmLabel(dim)"
        :format-value="(value: number) => value.toFixed(2)"
        @update:model-value="(value: number) => setDim(dim, value)"
      />
    </section>

    <!-- Expression cue grammar ─ fixed rules, not random jitter -->
    <section class="flex flex-col gap-4">
      <div class="flex flex-col gap-1">
        <div class="text-sm font-semibold">
          {{ t('settings.pages.card.persona.sections.grammar') }}
        </div>
        <div class="text-xs text-$text-secondary">
          {{ t('settings.pages.card.persona.sections.grammar_hint') }}
        </div>
      </div>

      <div
        v-for="cue in AIJADE_EXPRESSION_GRAMMAR"
        :key="cue.id"
        class="flex flex-row items-start gap-3"
      >
        <Checkbox
          :model-value="enabledCues.has(cue.id)"
          @update:model-value="(value: boolean) => setCueEnabled(cue.id, value)"
        />
        <div class="flex flex-col gap-1">
          <div class="text-sm font-medium">
            {{ cueLabel(cue.id) }}
          </div>
          <div class="text-xs text-$text-secondary">
            {{ cueTrigger(cue.id) }}
          </div>
          <div class="font-mono text-xs text-$text-muted">
            {{ t('settings.pages.card.persona.dwell') }}: {{ cue.dwellMs[0] }}–{{ cue.dwellMs[1] }}ms
          </div>
        </div>
      </div>
    </section>

    <!-- Model asset identity (read-only) -->
    <section class="flex flex-col gap-3">
      <div class="flex flex-col gap-1">
        <div class="text-sm font-semibold">
          {{ t('settings.pages.card.persona.sections.asset') }}
        </div>
        <div class="text-xs text-$text-secondary">
          {{ t('settings.pages.card.persona.sections.asset_hint') }}
        </div>
      </div>

      <div class="flex flex-col gap-1 font-mono text-xs">
        <div>
          {{ t('settings.pages.card.persona.asset_format') }}:
          <span>{{ assetFormat ?? t('settings.pages.card.persona.not_computed') }}</span>
        </div>
        <div class="break-all">
          {{ t('settings.pages.card.persona.asset_hash') }}:
          <span>{{ assetHash ?? t('settings.pages.card.persona.not_computed') }}</span>
        </div>
      </div>
    </section>
  </div>
</template>
