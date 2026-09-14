/**
 * Tiny dependency-free logger so agent packages don't depend on a specific
 * logging library's API surface. Mirrors the shape AIJADE's other packages use
 * (`debug` / `info` / `warn` / `error`).
 */
export interface Logger {
  debug: (...args: unknown[]) => void
  info: (...args: unknown[]) => void
  warn: (...args: unknown[]) => void
  error: (...args: unknown[]) => void
}

export function createLogger(name: string): Logger {
  const prefix = `[${name}]`
  return {
    debug: (...args: unknown[]) => console.debug(prefix, ...args),
    info: (...args: unknown[]) => console.info(prefix, ...args),
    warn: (...args: unknown[]) => console.warn(prefix, ...args),
    error: (...args: unknown[]) => console.error(prefix, ...args),
  }
}
