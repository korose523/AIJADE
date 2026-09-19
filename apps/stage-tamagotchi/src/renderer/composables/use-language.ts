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

    // 渲染层已有持久化选择：以渲染层为准，完全不发起 IPC。
    // （Electron 重启时若 localStorage 未刷盘，`hasPersistedLanguage` 为 false，
    //  才会走到下面「回主进程问」的分支——这正是 issue #1658 的场景。）
    if (hasPersistedLanguage) {
      // Legacy migration: an old build stored the OS-detected `en` as the
      // default when the user never explicitly picked a language. Treat that
      // residual `en` as a legacy default and switch to Chinese.
      if ((language.value || '').startsWith('en'))
        language.value = DEFAULT_LOCALE

      isLocaleSynced = true
      void setLocale(language.value || DEFAULT_LOCALE)
      return
    }

    // 无持久化值（可能是首次启动，也可能是 localStorage 未刷盘）：
    // 向主进程询问是否存在显式保存的语言。
    let mainLocale: unknown
    try {
      mainLocale = await getMainLocale()
    }
    catch (error) {
      console.warn('[useLanguage] Failed to get locale from main process, using fallback:', error)
    }

    if (typeof mainLocale === 'string' && mainLocale !== '') {
      // 主进程持有显式选择 —— 以它为准，覆盖渲染层的 OS 兜底值。
      language.value = mainLocale
    }
    else if (!language.value) {
      // 主进程也无配置且渲染层兜底为空：落到简体中文。
      language.value = DEFAULT_LOCALE
    }

    isLocaleSynced = true
    void setLocale(language.value || DEFAULT_LOCALE)
  }

  return { restore }
}
