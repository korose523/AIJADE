import type { Ref } from 'vue'

import { useLocalStorageManualReset } from '@proj-aijade/stage-shared/composables'
import { watch } from 'vue'
import { useI18n } from 'vue-i18n'

/**
 * Manages language sync between renderer and main process, guarding
 * against Electron localStorage flush issues on restart.
 *
 * Use when:
 * - Electron restarts and renderer localStorage may not have been flushed
 *
 * Expects:
 * - `language` is the reactive language ref from the settings store
 * - `getMainLocale` returns the raw locale persisted in main-process config
 *   (`undefined` when no config exists yet, a string when user saved one)
 * - `setLocale` syncs the renderer locale back to main process
 *
 * Returns:
 * - `restore()` to be called during component onMounted
 */
export function useLanguage(
  language: Ref<string>,
  getMainLocale: () => Promise<unknown>,
  setLocale: (locale: string) => Promise<unknown> | unknown,
) {
  const i18n = useI18n()
  const persistedLanguage = useLocalStorageManualReset<string>('settings/language', '')
  const hasPersistedLanguage = persistedLanguage.value !== ''
  let isLocaleSynced = false

  // Guard: do not propagate the store's navigator.language fallback back
  // to main-process config before we have verified the correct locale.
  // Default to Simplified Chinese instead of browser/system language.
  watch(language, () => {
    i18n.locale.value = language.value || 'zh-Hans'
    if (isLocaleSynced) {
      void setLocale(language.value || 'zh-Hans')
    }
  })

  async function restore() {
    const DEFAULT_LOCALE = 'zh-Hans'

    // Ask the main process for any explicitly-saved language.
    let mainLocale: unknown
    try {
      mainLocale = await getMainLocale()
    }
    catch (error) {
      console.warn('[useLanguage] Failed to get locale from main process, using fallback:', error)
    }
    const mainHasLanguage = typeof mainLocale === 'string' && mainLocale !== ''

    if (!hasPersistedLanguage) {
      // True first launch: default to Simplified Chinese.
      language.value = DEFAULT_LOCALE
    }
    else if (!mainHasLanguage && (language.value || '').startsWith('en')) {
      // Legacy migration: an old build stored the OS-detected `en` as the
      // default when the user never explicitly picked a language. Treat that
      // residual `en` as a legacy default and switch to Chinese.
      language.value = DEFAULT_LOCALE
    }
    else if (mainHasLanguage && mainLocale !== language.value) {
      // Main process holds an explicit choice — honor it.
      language.value = mainLocale as string
    }

    isLocaleSynced = true
    void setLocale(language.value || DEFAULT_LOCALE)
  }

  return { restore }
}
