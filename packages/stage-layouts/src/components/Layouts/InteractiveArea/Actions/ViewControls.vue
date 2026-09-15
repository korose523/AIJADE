<script lang="ts" setup>
import { defaultControlConfig as threeCtrlConf, supportedControl as threeSupportedControl, useThreeViewControl } from '@proj-aijade/stage-ui-three'
import { defaultControlConfig as l2dCtrlConf, supportedControl as l2dSupportedCtrl, useL2dViewControl } from '@proj-aijade/stage-ui/stores/live2d'
import { useSettingsStageModel } from '@proj-aijade/stage-ui/stores/settings/stage-model'
import { Button } from '@proj-aijade/ui'
import { storeToRefs } from 'pinia'
import { computed } from 'vue'

const { stageModelRenderer } = storeToRefs(useSettingsStageModel())
const { viewControlsEnabled: l2dViewCtrlEnabled, viewControlMode: l2dCtrlMode, set: l2dSet } = useL2dViewControl()
const { viewControlsEnabled: threeSliderCtrlEnabled, viewControlMode: threeCtrlMode, set: threeSet } = useThreeViewControl()
const controlEnabled = computed(() => {
  if (stageModelRenderer.value === 'live2d')
    return { enabled: l2dViewCtrlEnabled, mode: l2dCtrlMode, supported: l2dSupportedCtrl, conf: l2dCtrlConf, reset: l2dSet }
  // MMD shares the three.js camera-control store with VRM — both render through
  // ThreeScene, so the same orbit/zoom controls apply.
  if (stageModelRenderer.value === 'vrm' || stageModelRenderer.value === 'mmd')
    return { enabled: threeSliderCtrlEnabled, mode: threeCtrlMode, supported: threeSupportedControl, conf: threeCtrlConf, reset: threeSet }
  return null
})

function handleViewControlsToggle(targetMode: string) {
  if (!controlEnabled.value || !controlEnabled.value.supported.includes(targetMode as any))
    return
  if (controlEnabled.value.mode.value === targetMode) {
    controlEnabled.value.reset(controlEnabled.value.mode.value as any)
    return
  }
  controlEnabled.value.mode.value = targetMode as any
}
</script>

<template>
  <div w-full flex flex-1 items-center self-end justify-end gap-2>
    <Transition name="fade">
      <div v-if="controlEnabled?.enabled.value" w-full flex justify-between gap-2>
        <Button
          v-for="control in controlEnabled.supported" :key="control" variant="secondary-muted"
          :toggled="controlEnabled.mode.value === control" w-full @click="handleViewControlsToggle(control)"
        >
          {{ (controlEnabled.conf as any)[control].buttonText }}
        </Button>
      </div>
    </Transition>
    <button
      w-fit flex items-center self-end justify-center justify-self-end rounded-xl p-2 backdrop-blur-md
      border="$hairline" bg="$surface-1" title="View"
      text="$text-secondary"
      @click="controlEnabled && (controlEnabled.enabled.value = !controlEnabled.enabled.value)"
    >
      <Transition name="fade" mode="out-in">
        <div v-if="controlEnabled?.enabled.value" i-solar:alt-arrow-right-outline size-5 />
        <div v-else i-solar:tuning-outline size-5 />
      </Transition>
    </button>
  </div>
</template>

<style scoped>
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.2s ease-in-out;
}

.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}

.fade-enter-to,
.fade-leave-from {
  opacity: 1;
}
</style>
