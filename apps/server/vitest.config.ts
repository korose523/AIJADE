import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    environment: 'node',
    globals: true,
    // PGlite (in-memory Postgres WASM) used by mockDB() in integration tests
    // needs more than the 10s default to finish WASM init + schema push.
    hookTimeout: 120000,
    testTimeout: 120000,
    coverage: {
      provider: 'v8',
      include: [
        'src/**/*.ts',
      ],
      reporter: [
        'text',
        'json',
        'html',
      ],
      thresholds: {
        lines: 100,
        functions: 100,
        branches: 100,
        statements: 100,
      },
    },
  },
})
