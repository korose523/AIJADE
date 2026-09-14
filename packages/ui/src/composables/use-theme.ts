import { useDark, useToggle } from '@vueuse/core'

import { LocalStorageShim } from '../utils'

const STORAGE_KEY = 'vueuse-color-scheme'

const storage = 'localStorage' in globalThis && localStorage != null && 'getItem' in localStorage && typeof localStorage.getItem === 'function'
  ? localStorage
  : new LocalStorageShim()

const isDark = useDark({
  disableTransition: true,
  storageKey: STORAGE_KEY,
  // NOTICE: for histoire, used in packages/stage-ui, localStorage global variable exists but `storage.getItem is not a function` will
  // be thrown, here we added LocalStorageShim to avoid this issue, and it will fallback to real localStorage when it's available.
  storage,
})

// Default to LIGHT on a first visit (when no stored user choice exists), while
// still honoring an explicit stored value ('light' | 'dark' | 'auto').
if (storage.getItem(STORAGE_KEY) == null) {
  isDark.value = false
}

const toggleDark = useToggle(isDark)

export function useTheme() {
  return {
    isDark,
    toggleDark,
  }
}
