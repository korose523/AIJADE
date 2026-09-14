<script setup lang="ts">
defineProps<{
  title: string
  description: string
  icon?: string
  iconTemplate?: boolean
  to: string
}>()
</script>

<template>
  <RouterLink
    box="border"
    flex="~ row"
    bg="$surface-1"
    border="$hairline"
    drop-shadow="none hover:[0px_4px_4px_rgba(220,220,220,0.4)] active:[0px_0px_0px_rgba(220,220,220,0.25)] hover:none"
    class="menu-icon-item"
    transition="all ease-in-out duration-400"
    relative w-full items-center overflow-hidden rounded-lg p-5 text-left
    cursor="pointer"
    :to="to"
  >
    <div z-1 flex-1>
      <div text-lg font-normal class="menu-icon-item-title" transition="all ease-in-out duration-400">
        {{ title }}
      </div>
      <div
        text="$text-secondary"
        class="menu-icon-item-description"
        transition="all ease-in-out duration-400"
      >
        <span>{{ description }}</span>
      </div>
    </div>
    <template v-if="typeof icon === 'string'">
      <div
        class="menu-icon-item-icon"
        transition="all ease-in-out duration-400"
        absolute right-0 size-24
        translate-y-4
        text="$text-muted"
        :class="[icon]"
      />
    </template>
    <template v-if="iconTemplate">
      <slot name="icon" />
    </template>
  </RouterLink>
</template>

<style scoped>
.menu-icon-item {
  position: relative;
  overflow: hidden;
}

.menu-icon-item::before {
  --at-apply: 'bg-gradient-to-r from-primary-500/0 to-primary-500/0 from-primary-400/0 to-primary-400/0';
  content: '';
  position: absolute;
  inset: 0;
  z-index: -1;
  width: 25%;
  height: 100%;
  mask-image: linear-gradient(120deg, white 30%, transparent 50%);
  opacity: 0;
  transition: all 0.4s ease-in-out;
}

.menu-icon-item:hover::before,
.menu-icon-item._hover::before {
  --at-apply: 'bg-gradient-to-r from-primary-500/20 via-primary-500/10 to-transparent from-primary-400/20 via-primary-400/10 to-transparent';
  width: 85%;
  opacity: 1;
}

.menu-icon-item::after {
  --at-apply: 'bg-dotted-[neutral-200/60] hover:bg-dotted-[primary-300/50] bg-dotted-[neutral-700/25] hover:bg-dotted-[primary-200/20]';
  position: absolute;
  inset: 0;
  z-index: -2;
  width: 100%;
  height: 100%;
  background-size: 10px 10px;
  content: '';
  mask-image: linear-gradient(165deg, white 30%, transparent 50%);
  transition: all 0.4s ease-in-out;
}

.menu-icon-item-icon {
  opacity: 0.5;
}

.menu-icon-item:hover .menu-icon-item-title,
.menu-icon-item._hover .menu-icon-item-title {
  --at-apply: text-primary-600;
}

.menu-icon-item:hover .menu-icon-item-description,
.menu-icon-item._hover .menu-icon-item-description {
  --at-apply: text-primary-600;
  opacity: 0.8;
}

.menu-icon-item:hover .menu-icon-item-icon,
.menu-icon-item._hover .menu-icon-item-icon {
  --at-apply: text-primary-500;
  scale: 1.2;
}

.dark .menu-icon-item:hover .menu-icon-item-title,
.dark .menu-icon-item._hover .menu-icon-item-title {
  --at-apply: text-primary-300;
}

.dark .menu-icon-item:hover .menu-icon-item-description,
.dark .menu-icon-item._hover .menu-icon-item-description {
  --at-apply: text-primary-300;
  opacity: 0.8;
}

.dark .menu-icon-item:hover .menu-icon-item-icon,
.dark .menu-icon-item._hover .menu-icon-item-icon {
  --at-apply: text-primary-400;
}
</style>
