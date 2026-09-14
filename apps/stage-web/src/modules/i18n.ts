import messages from '@proj-aijade/i18n/locales'

import { resolveSupportedLocale } from '@proj-aijade/i18n'
import { createI18n } from 'vue-i18n'

function getLocale() {
  let language = localStorage.getItem('settings/language')

  if (!language) {
    // Default to Simplified Chinese instead of browser language
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
