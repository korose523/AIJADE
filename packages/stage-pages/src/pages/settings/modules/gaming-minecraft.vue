<script setup lang="ts">
import { GamingMinecraft } from '@proj-aijade/stage-ui/components'
</script>

<template>
  <GamingMinecraft />
</template>

<route lang="yaml">
meta:
  layout: settings
  titleKey: settings.pages.modules.gaming-minecraft.title
  subtitleKey: settings.title
  stageTransition:
    name: slide
    pageSpecificAvailable: true
</route>
