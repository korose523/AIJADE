import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    name: '@proj-aijade/core-agent',
    include: ['src/**/*.test.ts'],
  },
})
