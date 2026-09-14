import messages from '@proj-aijade/i18n/locales'

import { resolveSupportedLocale } from '@proj-aijade/i18n'
import { createI18n } from 'vue-i18n'

function getLocale() {
  let language = 'zh-Hans'
  // NOTICE: histoire doesn't have localStorage during collection, directly accessing it causes error.
  if ('localStorage' in globalThis && localStorage != null && 'getItem' in localStorage && typeof localStorage.getItem === 'function') {
    language = localStorage.getItem('settings/language') || 'zh-Hans'
  }

  if (!language) {
    // Default to Simplified Chinese
    language = 'zh-Hans'
  }

  return resolveSupportedLocale(language, Object.keys(messages!))
}

export const i18n = createI18n({
  legacy: false,
  locale: getLocale(),
  fallbackLocale: 'en',
  messages,
})
