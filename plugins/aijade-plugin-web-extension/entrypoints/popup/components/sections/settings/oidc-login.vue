<script lang="ts" setup>
import { Button, Callout } from '@proj-aijade/ui'
import { computed } from 'vue'

import { usePopupStore } from '../../../stores'

const popup = usePopupStore()

// 把门面返回的 `kind` 翻译成给用户看的可区分文案；`message` 作为补充细节。
const errorText = computed(() => {
  if (!popup.oidcError.value)
    return null
  const raw = popup.oidcError.value
  if (raw.startsWith('invalid_client'))
    return '客户端未注册（部署配置问题）：服务端尚未注册 OIDC 客户端 "aijade-web-extension"。请联系服务端确认已注册该 first-party 客户端。'
  if (raw.startsWith('cancelled'))
    return '已取消授权登录。'
  if (raw.startsWith('state_mismatch'))
    return '状态校验失败（可能的 CSRF），请重试登录。'
  if (raw.startsWith('unauthorized'))
    return '授权被拒（用户拒绝授权或未登录）。请重试登录。'
  if (raw.startsWith('network'))
    return '网络错误，无法连接授权服务，请检查网络后重试。'
  if (raw.startsWith('malformed'))
    return '授权回调格式错误，请重试登录。'
  return raw
})

function fmtExpiry(): string {
  const t = popup.oidc.expiresAt
  if (!t)
    return ''
  return new Date(t).toLocaleString()
}
</script>

<template>
  <section :class="['rounded-2xl', 'bg-white/6', 'border', 'border-white/10', 'p-3', 'flex', 'flex-col', 'gap-3']">
    <div :class="['flex', 'items-center', 'justify-between']">
      <h2 :class="['text-sm', 'font-600']">
        AIJADE Account
      </h2>
      <span
        :class="[
          'text-xs',
          'px-2',
          'py-0.5',
          'rounded-full',
          popup.oidc.loggedIn ? 'bg-emerald-500/20 text-emerald-300' : 'bg-white/10 text-white/60',
        ]"
      >
        {{ popup.oidc.loggedIn ? 'Signed in' : 'Signed out' }}
      </span>
    </div>

    <div v-if="popup.oidc.loggedIn && popup.oidc.expiresAt" :class="['text-xs', 'opacity-60']">
      Access token 有效期至 {{ fmtExpiry() }}
    </div>

    <div v-if="popup.oidcBusy.value" :class="['text-xs', 'opacity-70']">
      正在登录…
    </div>

    <Callout v-if="errorText" theme="orange" label="Login failed">
      <div :class="['text-xs', 'leading-snug', 'opacity-80']">
        {{ errorText }}
      </div>
    </Callout>

    <Button
      v-if="!popup.oidc.loggedIn"
      variant="primary"
      size="sm"
      :disabled="popup.oidcBusy.value"
      @click="popup.loginOidc"
    >
      Sign in with AIJADE
    </Button>

    <Button
      v-else
      variant="secondary"
      size="sm"
      :disabled="popup.oidcBusy.value"
      @click="popup.logoutOidc"
    >
      Sign out
    </Button>
  </section>
</template>
