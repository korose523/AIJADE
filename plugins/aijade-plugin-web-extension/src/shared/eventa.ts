import type { FetchOidcTokensResult } from './oidc'
import type { ExtensionSettings, ExtensionStatus } from './types'

import { defineEventa, defineInvokeEventa } from '@moeru/eventa'

export const popupGetStatus = defineInvokeEventa<ExtensionStatus>('eventa:invoke:web-extension:popup:get-status')
export const popupUpdateSettings = defineInvokeEventa<ExtensionStatus, Partial<ExtensionSettings>>('eventa:invoke:web-extension:popup:update-settings')
export const popupToggleEnabled = defineInvokeEventa<ExtensionStatus, boolean>('eventa:invoke:web-extension:popup:toggle-enabled')
export const popupRequestVisionFrame = defineInvokeEventa<ExtensionStatus>('eventa:invoke:web-extension:popup:request-vision-frame')
export const popupClearError = defineInvokeEventa<ExtensionStatus>('eventa:invoke:web-extension:popup:clear-error')

/** 发起 OIDC PKCE 登录流程（background 跑 `chrome.identity.launchWebAuthFlow`）。返回可判别的结果。 */
export const popupStartOidcLogin = defineInvokeEventa<FetchOidcTokensResult>('eventa:invoke:web-extension:popup:start-oidc-login')
/** 登出：清除 OIDC 令牌与登录态。 */
export const popupLogoutOidc = defineInvokeEventa<{ ok: true }>('eventa:invoke:web-extension:popup:logout-oidc')
/** 读取当前 OIDC 登录态（popup 挂载时用来决定显示登录/登出）。 */
export const popupGetOidcStatus = defineInvokeEventa<OidcStatus>('eventa:invoke:web-extension:popup:get-oidc-status')

export interface OidcStatus {
  loggedIn: boolean
  accessTokenPresent: boolean
  expiresAt: number | null
}

export const backgroundStatusChanged = defineEventa<ExtensionStatus>('eventa:event:web-extension:background:status')
