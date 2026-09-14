<script setup lang="ts">
import type { AboutBuildInfo, AboutLink } from './types'

import { computed } from 'vue'

const props = withDefaults(defineProps<{
  title?: string
  highlight?: string
  subtitle?: string
  buildInfo?: AboutBuildInfo
  links?: AboutLink[]
}>(), {
  title: 'Project',
  highlight: 'AIJADE',
  subtitle: '',
  links: () => ([
    { label: 'Home', href: 'https://aijade.ai/docs/', icon: 'i-solar:home-smile-outline' },
    { label: 'Documentations', href: 'https://aijade.ai/docs/en/docs/overview/', icon: 'i-solar:document-add-outline' },
    { label: 'GitHub', href: 'https://github.com/moeru-ai/airi', icon: 'i-simple-icons:github' },
  ]),
})

const hasBuildInfo = computed(() => {
  const info = props.buildInfo
  if (!info)
    return false

  return Boolean(info.branch || info.commit || info.builtOn || info.version)
})
</script>

<template>
  <div :class="['max-w-[min(960px,calc(100%-2rem))]', 'mx-auto', 'h-full', 'flex', 'flex-col', 'pt-14']">
    <div class="mb-14 text-center font-sans-rounded">
      <div class="text-5xl">
        <span class="text-$text-muted text-$text-primary">{{ title }}</span>
        <span class="text-pink-300/90 text-pink-400">&nbsp;{{ highlight }}</span>
      </div>
      <div v-if="subtitle" class="mt-2 text-base text-$text-muted text-$text-secondary">
        {{ subtitle }}
      </div>
    </div>

    <slot name="before-build-info" />

    <div v-if="hasBuildInfo" :class="['flex-1']">
      <div :class="['text-$text-secondary text-$text-muted']">
        Application build information
      </div>
      <div :class="['mt-4', 'grid grid-cols-[120px_1fr]', 'gap-2', 'text-sm']">
        <template v-if="buildInfo?.version">
          <div :class="['text-$text-secondary text-$text-muted']">
            Version
          </div>
          <div :class="['font-mono']">
            {{ buildInfo.version }}
          </div>
        </template>
        <template v-if="buildInfo?.branch">
          <div :class="['text-$text-secondary text-$text-muted']">
            Branch
          </div>
          <div :class="['font-mono']">
            {{ buildInfo.branch }}
          </div>
        </template>
        <template v-if="buildInfo?.commit">
          <div :class="['text-$text-secondary text-$text-muted']">
            Commit
          </div>
          <div :class="['font-mono']">
            {{ buildInfo.commit }}
          </div>
        </template>
        <template v-if="buildInfo?.builtOn">
          <div :class="['text-$text-secondary text-$text-muted']">
            Built on
          </div>
          <div :class="['font-mono']">
            {{ buildInfo.builtOn }}
          </div>
        </template>
      </div>
    </div>

    <slot name="after-build-info" />

    <div :class="['my-10']">
      <div :class="['text-$text-secondary text-$text-muted']">
        About
      </div>
      <div :class="['mt-4 flex flex-col gap-2']">
        <a
          v-for="link in links"
          :key="link.href"
          :class="[
            'block',
            'flex items-center gap-2',
            'rounded-xl',
            'px-3 py-2',
            'lg:px-5 lg:py-3',
            'outline-none',
            'backdrop-blur-md',
            'active:scale-98',
            'focus:outline-none',
            'text-nowrap',
            'text-sm md:text-base',
            'text-$text-primary text-$text-primary',
            'bg-$scrim',
            'transition-colors transition-transform duration-200 ease-in-out',
            'hover:bg-$scrim',
            'bg-$scrim hover:bg-$surface-1',
          ]"
          :href="link.href"
          target="_blank"
        >
          <div :class="link.icon" />
          <div>{{ link.label }}</div>
        </a>
      </div>
    </div>
  </div>
</template>
