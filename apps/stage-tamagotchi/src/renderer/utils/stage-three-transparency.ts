import type { StageModelRenderer } from '@proj-aijade/stage-ui/stores/settings'

export type StageComponentState = 'pending' | 'loading' | 'mounted'

export function shouldSampleStageTransparency(params: {
  componentState: StageComponentState
  fadeOnHoverEnabled: boolean
  stageModelRenderer: StageModelRenderer
  stagePaused: boolean
}) {
  return params.fadeOnHoverEnabled
    && !params.stagePaused
    && params.componentState === 'mounted'
    && params.stageModelRenderer === 'vrm'
}
