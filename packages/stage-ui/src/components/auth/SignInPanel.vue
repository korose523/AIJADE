<script setup lang="ts">
import type { OAuthProvider } from '../../libs/auth'
import type { SignInProviderDefinition } from './providers'

import { Button, Callout } from '@proj-aijade/ui'
import { computed } from 'vue'

import Alert from '../misc/alert.vue'

const props = withDefaults(defineProps<{
  title?: string
  subtitle?: string
  providers: readonly SignInProviderDefinition[]
  pendingProvider?: OAuthProvider | null
  error?: string | null
}>(), {
  title: 'Sign in to AIJADE',
  subtitle: 'Choose a provider to continue your authorization flow.',
  pendingProvider: null,
  error: null,
})

const emit = defineEmits<{
  select: [provider: OAuthProvider]
}>()

const termsHref = 'https://aijade.ai/docs/en/about/terms'
const privacyHref = 'https://aijade.ai/docs/en/about/privacy'

const hasProviders = computed(() => props.providers.length > 0)

function handleSelect(provider: OAuthProvider) {
  if (props.pendingProvider)
    return

  emit('select', provider)
}
</script>

<template>
  <section
    :class="[
      'relative overflow-hidden rounded-[2rem] border border-$hairline bg-$surface-1 p-6 shadow-[0_24px_80px_-40px_rgba(15,23,42,0.45)] backdrop-blur-xl',
      'border-$hairline bg-$surface-1',
    ]"
  >
    <div
      :class="[
        'pointer-events-none absolute inset-x-0 top-0 h-36 bg-gradient-to-br from-primary-300/35 via-sky-200/20 to-transparent blur-2xl',
        'from-primary-500/15 via-cyan-500/12',
      ]"
    />

    <div :class="['relative flex flex-col gap-6']">
      <div :class="['flex flex-col gap-4']">
        <Callout theme="primary" label="Server sign-in">
          Continue with one of your connected identity providers to complete access.
        </Callout>

        <div :class="['space-y-3']">
          <div :class="['inline-flex h-13 w-13 items-center justify-center rounded-2xl bg-$surface-1 text-xl text-$text-primary shadow-lg', 'bg-$surface-1 text-neutral-950']">
            Ai
          </div>

          <div :class="['space-y-2']">
            <h1 :class="['text-balance text-3xl font-semibold tracking-tight text-neutral-950 text-neutral-25']">
              {{ title }}
            </h1>
            <p :class="['max-w-sm text-sm leading-6 text-$text-secondary text-$text-primary']">
              {{ subtitle }}
            </p>
          </div>
        </div>
      </div>

      <Alert v-if="error" type="error">
        <template #title>
          Sign-in failed
        </template>
        <template #content>
          {{ error }}
        </template>
      </Alert>

      <div v-if="hasProviders" :class="['flex flex-col gap-3']">
        <Button
          v-for="provider in providers"
          :key="provider.id"
          variant="secondary"
          size="lg"
          block
          :icon="provider.icon"
          :loading="pendingProvider === provider.id"
          :disabled="Boolean(pendingProvider)"
          :class="[
            '!justify-start rounded-2xl px-5 py-4 text-base font-medium',
            'shadow-[0_12px_30px_-24px_rgba(15,23,42,0.6)]',
          ]"
          @click="handleSelect(provider.id)"
        >
          <span :class="['truncate']">Continue with {{ provider.name }}</span>
        </Button>
      </div>

      <Alert v-else type="warning">
        <template #title>
          No providers available
        </template>
        <template #content>
          The sign-in page is not configured with any providers yet.
        </template>
      </Alert>

      <footer :class="['text-xs leading-5 text-$text-secondary text-$text-muted']">
        By continuing, you agree to our
        <a :href="termsHref" :class="['font-medium text-$text-primary underline-offset-4 hover:underline text-$text-primary']">
          Terms
        </a>
        and
        <a :href="privacyHref" :class="['font-medium text-$text-primary underline-offset-4 hover:underline text-$text-primary']">
          Privacy Policy
        </a>
        .
      </footer>
    </div>
  </section>
</template>
