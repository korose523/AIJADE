<script setup lang="ts">
import { signOut } from '@proj-aijade/stage-ui/libs/auth'
import { useAuthStore } from '@proj-aijade/stage-ui/stores/auth'
import { onClickOutside } from '@vueuse/core'
import { storeToRefs } from 'pinia'
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'

const authStore = useAuthStore()
const { isAuthenticated, user, credits } = storeToRefs(authStore)

const userName = computed(() => user.value?.name)
const userAvatar = computed(() => user.value?.image)
const showDropdown = ref(false)
const dropdownRef = ref(null)

// Fall back to the user-icon placeholder when the avatar URL fails to load
// (broken/expired host, network error, hot-linked image taken down). Without
// this the header pill renders the browser's default broken-image glyph,
// which looks worse than the explicit placeholder we already ship.
// Reset on URL change so a fixed URL re-attempts loading.
const avatarLoadError = ref(false)
watch(userAvatar, () => {
  avatarLoadError.value = false
})

const formattedCredits = computed(() => credits.value.toLocaleString())

onClickOutside(dropdownRef, () => {
  showDropdown.value = false
})
</script>

<template>
  <div flex items-center gap-2>
    <!-- Non-authenticated: Settings & Sign in -->
    <!-- NOTICE: The avatar is stored in the localstorage, it will be shown at the first time of the page load, so we do not need the skeleton loading here -->
    <template v-if="!isAuthenticated">
      <RouterLink
        border="$hairline"
        bg="$surface-1"
        w-fit flex items-center justify-center rounded-xl p-2 backdrop-blur-md
        title="Settings"
        to="/settings"
      >
        <div i-solar:settings-minimalistic-bold-duotone size-5 text="$text-secondary" />
      </RouterLink>

      <button
        border="$hairline"
        bg="$surface-1"
        w-fit flex items-center justify-center rounded-xl p-2 backdrop-blur-md
        title="Sign in"
        type="button"
        @click="authStore.needsLogin = true"
      >
        <div i-solar:user-bold-duotone />
      </button>
    </template>

    <!-- Authenticated: Avatar Dropdown -->
    <div v-else ref="dropdownRef" class="relative">
      <button
        type="button"
        class="flex items-center gap-2 border-2 border-$hairline border-$hairline rounded-full bg-$surface-1 bg-$surface-2 p-1 pl-1 pr-3 backdrop-blur-md transition hover:bg-$surface-1 hover:bg-$surface-2"
        :class="{ 'ring-2 ring-primary-500/20': showDropdown }"
        aria-haspopup="true"
        :aria-expanded="showDropdown ? 'true' : 'false'"
        @click="showDropdown = !showDropdown"
      >
        <img
          v-if="userAvatar && !avatarLoadError"
          :src="userAvatar"
          :alt="userName"
          class="h-7 w-7 rounded-full object-cover"
          @error="avatarLoadError = true"
        >
        <div
          v-else
          class="h-7 w-7 flex items-center justify-center rounded-full bg-$surface-1 bg-$surface-3 text-$text-muted text-$text-secondary"
        >
          <div class="i-solar:user-bold-duotone text-lg" />
        </div>

        <span v-if="userName" class="max-w-[100px] truncate text-sm text-$text-primary text-$text-primary font-medium hidden sm:block">
          {{ userName }}
        </span>
        <div
          class="i-solar:alt-arrow-down-linear text-$text-muted transition-transform duration-200"
          :class="{ 'rotate-180': showDropdown }"
        />
      </button>

      <Transition
        enter-active-class="transition duration-200 ease-out"
        enter-from-class="translate-y-1 opacity-0"
        enter-to-class="translate-y-0 opacity-100"
        leave-active-class="transition duration-150 ease-in"
        leave-from-class="translate-y-0 opacity-100"
        leave-to-class="translate-y-1 opacity-0"
      >
        <div
          v-if="showDropdown"
          class="absolute right-0 top-full z-50 mt-2 w-60 origin-top-right border border-$hairline border-$hairline rounded-xl bg-$surface-1 bg-$surface-1 p-1 shadow-xl backdrop-blur-xl divide-y divide-$hairline divide-$hairline"
        >
          <div class="px-3 py-2">
            <p class="text-xs text-$text-muted text-$text-secondary">
              Signed in as
            </p>
            <p class="truncate text-sm text-$text-primary text-$text-primary font-medium">
              {{ userName }}
            </p>
            <div class="mt-1 flex items-center gap-1.5 text-xs text-primary-400 text-primary-600 font-medium">
              <div class="i-solar:battery-charge-bold-duotone text-sm" />
              <span>{{ formattedCredits }} Flux</span>
            </div>
          </div>

          <div class="py-1">
            <RouterLink
              to="/settings/account"
              class="group w-full flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-$text-primary text-$text-primary transition hover:bg-$surface-1 hover:bg-$surface-2"
              @click="showDropdown = false"
            >
              <div class="i-solar:user-id-bold-duotone text-lg text-$text-muted transition group-hover:text-primary-500" />
              Profile
            </RouterLink>

            <RouterLink
              to="/settings/flux"
              class="group w-full flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-$text-primary text-$text-primary transition hover:bg-$surface-1 hover:bg-$surface-2"
              @click="showDropdown = false"
            >
              <div class="i-solar:battery-charge-bold-duotone text-lg text-$text-muted transition group-hover:text-primary-500" />
              Flux
            </RouterLink>

            <RouterLink
              to="/settings"
              class="group w-full flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-$text-primary text-$text-primary transition hover:bg-$surface-1 hover:bg-$surface-2"
              @click="showDropdown = false"
            >
              <div class="i-solar:settings-minimalistic-bold-duotone text-lg text-$text-muted transition group-hover:text-primary-500" />
              Settings
            </RouterLink>
          </div>

          <div class="py-1">
            <button
              class="group w-full flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-[var(--danger)] transition hover:bg-[color-mix(in_oklab,var(--danger)_10%,transparent)]"
              @click="signOut"
            >
              <div class="i-solar:logout-3-bold-duotone text-lg transition group-hover:text-[var(--danger)]" />
              Sign out
            </button>
          </div>
        </div>
      </Transition>
    </div>
  </div>
</template>
