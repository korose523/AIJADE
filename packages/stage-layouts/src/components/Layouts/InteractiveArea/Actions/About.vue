<script setup lang="ts">
import { isStageCapacitor, isStageTamagotchi } from '@proj-aijade/stage-shared'
import { AboutContent, AboutDialog } from '@proj-aijade/stage-ui/components'
import { useBuildInfo } from '@proj-aijade/stage-ui/composables'
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const show = ref(false)
const buildInfo = useBuildInfo()

const aboutLinks = [
  { label: 'Home', href: 'https://aijade.ai/docs/', icon: 'i-solar:home-smile-outline' },
  { label: 'Documentations', href: 'https://aijade.ai/docs/en/docs/overview/', icon: 'i-solar:document-add-outline' },
  { label: 'GitHub', href: 'https://github.com/korose523/AIJADE', icon: 'i-simple-icons:github' },
]

const edition = isStageTamagotchi()
  ? t('base.edition.desktop')
  : isStageCapacitor()
    ? t('base.edition.mobile')
    : t('base.edition.web')
</script>

<template>
  <button
    title="About"
    :class="[
      'w-fit p-2',
      'flex justify-center md:items-center self-end',
      'border-2 border-solid border-$hairline border-$hairline',
      'bg-$surface-1 bg-$surface-2',
      'backdrop-blur-md',
      'rounded-xl',
    ]"
    @click="show = !show"
  >
    <div i-solar:info-circle-outline class="size-5" text="$text-secondary" />
  </button>
  <AboutDialog v-model="show">
    <AboutContent :subtitle="edition" :build-info="buildInfo" :links="aboutLinks" />
  </AboutDialog>
</template>
