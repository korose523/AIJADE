import type { ExtensionSettings, ExtensionStatus } from '../../../src/shared/types'

import { createGlobalState } from '@vueuse/core'
import { computed, reactive, ref, watch } from 'vue'

import { clearError, getOidcStatus, logoutOidc, onBackgroundStatus, requestStatus, requestVisionFrame, startOidcLogin, toggleEnabled, updateSettings } from '../../../src/popup/bridge'

const STORAGE_KEY = 'aijade-popup-settings'

export interface PopupOidcState {
  loggedIn: boolean
  accessTokenPresent: boolean
  expiresAt: number | null
}

export const usePopupStore = createGlobalState(() => {
  const status = ref<ExtensionStatus | null>(null)
  const syncing = ref(true)
  const initialized = ref(false)

  // OIDC 登录态（popup 本地视图状态，真实真源在 background / storage）。
  const oidc = reactive<PopupOidcState>({ loggedIn: false, accessTokenPresent: false, expiresAt: null })
  const oidcBusy = ref(false)
  const oidcError = ref<string | null>(null)

  const form = reactive<ExtensionSettings>({
    wsUrl: '',
    token: '',
    restBaseUrl: '',
    bearerToken: '',
    enabled: true,
    sendPageContext: true,
    sendVideoContext: true,
    sendSubtitles: true,
    sendSparkNotify: true,
    enableVision: false,
  })

  const connected = computed(() => status.value?.connected ?? false)
  const lastVideo = computed(() => status.value?.lastVideo)
  const lastSubtitle = computed(() => status.value?.lastSubtitle)
  const lastError = computed(() => status.value?.lastError)

  function hydrate(next: ExtensionStatus) {
    status.value = next
    Object.assign(form, next.settings)
  }

  function loadStoredSettings() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY)
      if (!raw)
        return
      const parsed = JSON.parse(raw) as Partial<ExtensionSettings>
      Object.assign(form, parsed)
    }
    catch {
      localStorage.removeItem(STORAGE_KEY)
    }
  }

  function persistSettings() {
    const payload: ExtensionSettings = { ...form }
    localStorage.setItem(STORAGE_KEY, JSON.stringify(payload))
  }

  async function refresh() {
    syncing.value = true
    try {
      const next = await requestStatus()
      hydrate(next)
    }
    finally {
      syncing.value = false
    }
  }

  async function applySettings() {
    syncing.value = true
    try {
      const next = await updateSettings({ ...form })
      hydrate(next)
    }
    finally {
      syncing.value = false
    }
  }

  async function toggle() {
    syncing.value = true
    try {
      const next = await toggleEnabled(!form.enabled)
      hydrate(next)
    }
    finally {
      syncing.value = false
    }
  }

  async function captureFrame() {
    syncing.value = true
    try {
      const next = await requestVisionFrame()
      hydrate(next)
    }
    finally {
      syncing.value = false
    }
  }

  async function clearLastError() {
    const next = await clearError()
    hydrate(next)
  }

  async function refreshOidc() {
    const next = await getOidcStatus()
    Object.assign(oidc, next)
  }

  async function loginOidc() {
    oidcBusy.value = true
    oidcError.value = null
    try {
      const result = await startOidcLogin()
      if (result.ok) {
        oidc.loggedIn = true
        oidc.accessTokenPresent = true
        oidc.expiresAt = result.expiresAt
      }
      else {
        // 可区分的错误原因（invalid_client / cancelled / unauthorized ...）。
        oidc.loggedIn = false
        oidcError.value = `${result.kind}: ${result.message}`
      }
    }
    finally {
      oidcBusy.value = false
    }
  }

  async function logoutOidcAction() {
    await logoutOidc()
    oidc.loggedIn = false
    oidc.accessTokenPresent = false
    oidc.expiresAt = null
    oidcError.value = null
  }

  function init() {
    if (initialized.value)
      return
    initialized.value = true
    loadStoredSettings()
    watch(form, persistSettings, { deep: true })
    void refresh()
    void refreshOidc()
    onBackgroundStatus(hydrate)
  }

  return {
    status,
    syncing,
    form,
    connected,
    lastVideo,
    lastSubtitle,
    lastError,
    oidc,
    oidcBusy,
    oidcError,
    init,
    refresh,
    applySettings,
    toggle,
    captureFrame,
    clearLastError,
    refreshOidc,
    loginOidc,
    logoutOidc: logoutOidcAction,
  }
})
