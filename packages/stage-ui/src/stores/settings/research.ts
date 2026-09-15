import { useLocalStorageManualReset } from '@proj-aijade/stage-shared/composables'
import { defineStore } from 'pinia'

export const useSettingsResearch = defineStore('settings-research', () => {
  /**
   * Explicit, withdrawable consent to record the **longitudinal persona
   * trajectory** (`@proj-aijade/research-telemetry`).
   *
   * Default is `false` on purpose. A persona trajectory is human-subjects data:
   * recording it without an explicit consent flag would not survive an IRB
   * review, and this study is bound by the Korean Bioethics and Safety Act.
   *
   * Withdrawing consent (flipping this back to false) both stops recording and
   * **erases** what has been recorded so far — see
   * `createPersonaTelemetryRecorder` in `@proj-aijade/agent-continuous-learning`.
   */
  const researchTelemetryConsent = useLocalStorageManualReset<boolean>('settings/research/telemetry-consent', false)

  function resetState() {
    researchTelemetryConsent.reset()
  }

  return {
    researchTelemetryConsent,
    resetState,
  }
})
