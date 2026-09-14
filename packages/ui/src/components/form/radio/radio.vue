<script setup lang="ts">
withDefaults(defineProps<{
  id: string
  name: string
  value: string
  title: string
  deprecated?: boolean
}>(), {
  deprecated: false,
})

const modelValue = defineModel<string>({ required: true })
</script>

<template>
  <label
    :key="id"
    :class="[
      'form_radio relative flex cursor-pointer items-start rounded-xl p-3 pr-[20px]',
      'transition-all duration-200 ease-in-out',
      'border-2 border-solid',
      modelValue === value
        ? 'bg-primary-50 bg-primary-900/20 border-primary-100 border-primary-900 hover:border-primary-500/30 hover:border-primary-400/30'
        : 'bg-$surface-1 bg-$surface-1 border-$hairline border-$hairline hover:border-primary-500/30 hover:border-primary-400/30',
      modelValue === value
        ? 'form_radio-active'
        : '',
      deprecated ? 'opacity-60' : '',
    ]"
  >
    <input
      v-model="modelValue"
      :checked="modelValue === value"
      type="radio"
      :name="name"
      :value="value"
      :class="['absolute opacity-0']"
    >
    <div :class="['relative mr-3 mt-0.5 flex-shrink-0']">
      <div
        :class="[
          'size-5 border-2 rounded-full transition-colors duration-200',
          modelValue === value
            ? 'border-primary-500 border-primary-400'
            : 'border-$hairline border-$hairline',
        ]"
      >
        <div
          :class="[
            'absolute left-1/2 top-1/2 size-3 rounded-full transition-opacity duration-200 -translate-x-1/2 -translate-y-1/2',
            modelValue === value
              ? 'opacity-100 bg-primary-500 bg-primary-400'
              : 'opacity-0',
          ]"
        />
      </div>
    </div>
    <div :class="['w-full flex flex-col gap-2']">
      <div :class="['flex items-center']">
        <span
          :class="[
            'line-clamp-1 font-medium',
            modelValue === value
              ? 'text-$text-primary text-$text-primary'
              : 'text-$text-primary text-$text-muted',
          ]"
        >
          {{ title }}
        </span>
      </div>
    </div>
  </label>
</template>

<style scoped>
.form_radio {
  position: relative;
  overflow: hidden;
}

.form_radio::before {
  --at-apply: 'bg-gradient-to-r from-primary-500/0 to-primary-500/0 from-primary-400/0 to-primary-400/0';
  content: '';
  position: absolute;
  inset: 0;
  z-index: 0;
  width: 25%;
  height: 100%;
  transition: all 0.35s ease-in-out;
  mask-image: linear-gradient(120deg, white 100%);
  opacity: 0;
}

.form_radio:hover::before,
.form_radio._hover::before {
  --at-apply: 'bg-gradient-to-r from-primary-500/20 via-primary-500/10 to-transparent from-primary-400/20 via-primary-400/10 to-transparent';
  width: 85%;
  opacity: 1;
}

.form_radio-active::before {
  --at-apply: 'bg-gradient-to-r from-primary-500/20 via-primary-500/10 to-transparent from-primary-400/20 via-primary-400/10 to-transparent';
  width: 85%;
  opacity: 0.5;
}
</style>
