<script setup lang="ts">
import { Callout } from '@proj-aijade/ui'
import { storeToRefs } from 'pinia'
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'

import { useMinecraftStore } from '../../stores/modules/gaming-minecraft'

const minecraftStore = useMinecraftStore()
const { t } = useI18n()

const {
  serviceConnected,
  latestRuntimeContextText,
  lastRuntimeContextAt,
  runtimeContextAgeMs,
  trafficEntries,
} = storeToRefs(minecraftStore)

const statusTheme = computed(() => serviceConnected.value ? 'lime' : 'orange')

const statusLabel = computed(() => {
  return serviceConnected.value
    ? t('settings.pages.modules.gaming-minecraft.status.service-online')
    : t('settings.pages.modules.gaming-minecraft.status.service-offline')
})

const lastRuntimeUpdate = computed(() => {
  if (!lastRuntimeContextAt.value)
    return t('settings.pages.modules.gaming-minecraft.status.no-runtime-context')

  const seconds = Math.floor(runtimeContextAgeMs.value / 1000)
  if (seconds > 60)
    return t('settings.pages.modules.gaming-minecraft.status.last-context-stale')

  return t('settings.pages.modules.gaming-minecraft.status.last-context-seconds', { seconds })
})

function formatTrafficTime(timestamp: number) {
  return new Intl.DateTimeFormat(undefined, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).format(timestamp)
}

function formatTrafficPayload(payload: unknown) {
  return JSON.stringify(payload, null, 2)
}

onMounted(() => {
  minecraftStore.initialize()
})
</script>

<template>
  <div :class="['flex flex-col gap-6']">
    <Callout :theme="statusTheme" :label="statusLabel">
      <div :class="['flex flex-col gap-2 text-sm']">
        <div>
          {{ lastRuntimeUpdate }}
        </div>
      </div>
    </Callout>

    <div :class="['rounded-2xl border border-$hairline bg-$surface-1 p-4 border-$hairline bg-$surface-1']">
      <div :class="['mb-3 text-sm font-medium text-$text-primary text-$text-primary']">
        {{ t('settings.pages.modules.gaming-minecraft.setup.title') }}
      </div>
      <div :class="['flex flex-col gap-2 text-sm text-$text-secondary text-$text-primary']">
        <p>{{ t('settings.pages.modules.gaming-minecraft.setup.description') }}</p>
        <code :class="['w-fit rounded-md bg-$surface-1 px-2 py-1 text-xs text-$text-primary']">services/minecraft/README.md</code>
      </div>
    </div>

    <div :class="['rounded-2xl border border-$hairline bg-$surface-1 p-4 border-$hairline bg-$surface-1']">
      <div :class="['mb-3 text-sm font-medium text-$text-primary text-$text-primary']">
        {{ t('settings.pages.modules.gaming-minecraft.runtime.title') }}
      </div>
      <div :class="['grid gap-3 text-sm text-$text-secondary text-$text-primary']">
        <div>
          <div :class="['text-xs uppercase tracking-wide text-$text-secondary text-$text-muted']">
            {{ t('settings.pages.modules.gaming-minecraft.runtime.connection') }}
          </div>
          <div>{{ statusLabel }}</div>
        </div>
        <div>
          <div :class="['text-xs uppercase tracking-wide text-$text-secondary text-$text-muted']">
            {{ t('settings.pages.modules.gaming-minecraft.runtime.latest-context') }}
          </div>
          <pre
            :class="[
              'mt-2 whitespace-pre-wrap rounded-lg bg-$surface-1 p-3 text-xs text-$text-primary',
            ]"
          >{{ latestRuntimeContextText || t('settings.pages.modules.gaming-minecraft.runtime.waiting') }}</pre>
        </div>
      </div>
    </div>

    <div :class="['rounded-2xl border border-$hairline bg-$surface-1 p-4 border-$hairline bg-$surface-1']">
      <div :class="['mb-3 text-sm font-medium text-$text-primary text-$text-primary']">
        {{ t('settings.pages.modules.gaming-minecraft.debug.title') }}
      </div>
      <div
        v-if="trafficEntries.length === 0"
        :class="['text-sm text-$text-secondary text-$text-muted']"
      >
        {{ t('settings.pages.modules.gaming-minecraft.debug.empty') }}
      </div>
      <div v-else :class="['flex flex-col gap-3']">
        <div
          v-for="entry in [...trafficEntries].reverse()"
          :key="entry.id"
          :class="['rounded-xl border border-$hairline bg-$surface-1 p-3 border-$hairline bg-$scrim']"
        >
          <div :class="['flex flex-wrap items-center justify-between gap-2 text-xs text-$text-secondary text-$text-muted']">
            <span>{{ entry.type }}</span>
            <span>{{ formatTrafficTime(entry.receivedAt) }}</span>
          </div>
          <div :class="['mt-2 text-sm font-medium text-$text-primary text-$text-primary']">
            {{ entry.summary }}
          </div>
          <div :class="['mt-1 text-xs text-$text-secondary text-$text-muted']">
            {{ t('settings.pages.modules.gaming-minecraft.debug.source', { source: entry.source }) }}
          </div>
          <pre :class="['mt-3 overflow-x-auto rounded-lg bg-$surface-1 p-3 text-xs text-$text-primary']">{{ formatTrafficPayload(entry.payload) }}</pre>
        </div>
      </div>
    </div>
  </div>
</template>
