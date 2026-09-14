<script setup lang="ts">
import type { SpeechProvider } from '@xsai-ext/providers/utils'

import {
  SpeechPlayground,
  SpeechProviderSettings,
} from '@proj-aijade/stage-ui/components'
import { useSpeechStore } from '@proj-aijade/stage-ui/stores/modules/speech'
import { useProvidersStore } from '@proj-aijade/stage-ui/stores/providers'
import { Callout } from '@proj-aijade/ui'
import { computed, onMounted, watch } from 'vue'

const providerId = 'cosyvoice-local'
const defaultModel = 'cosyvoice-v1'

const speechStore = useSpeechStore()
const providersStore = useProvidersStore()

const availableVoices = computed(() => {
  return speechStore.availableVoices[providerId] || []
})

onMounted(async () => {
  await speechStore.loadVoicesForProvider(providerId)
})

watch([availableVoices], async () => {
  await speechStore.loadVoicesForProvider(providerId)
})

async function handleGenerateSpeech(input: string, voiceId: string) {
  const provider = await providersStore.getProviderInstance(providerId) as SpeechProvider
  if (!provider) {
    throw new Error('Failed to initialize speech provider')
  }

  const providerConfig = providersStore.getProviderConfig(providerId)
  const model = providerConfig.model as string | undefined || defaultModel

  const options = {
    ...providerConfig,
  }

  return await speechStore.speech(
    provider,
    model,
    input,
    voiceId,
    options,
  )
}
</script>

<template>
  <Callout
    theme="violet"
    label="Local CosyVoice server"
  >
    Runs a self-hosted CosyVoice server (FunAudioLLM/CosyVoice) at the Base URL below.
    Instruct emotion mode is enabled automatically whenever the persona expresses an
    emotion, so the voice itself carries the feeling.
  </Callout>

  <SpeechProviderSettings :provider-id="providerId" :default-model="defaultModel">
    <template #playground>
      <SpeechPlayground
        :available-voices="availableVoices" :generate-speech="handleGenerateSpeech"
        :api-key-configured="true" :use-ssml="false"
        default-text="Hello! This is a test of the local CosyVoice speech synthesis."
      />
    </template>
  </SpeechProviderSettings>
</template>

<route lang="yaml">
  meta:
    layout: settings
    stageTransition:
      name: slide
  </route>
