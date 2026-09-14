import { errorMessageFrom } from '@moeru/std'

interface AijadeClientLike {
  connect: () => Promise<void>
}

interface LoggerLike {
  log: (message: string) => void
  warn: (message: string) => void
  withFields: (fields: Record<string, unknown>) => LoggerLike
}

export function startAijadeClientConnection(client: AijadeClientLike, deps: {
  logger: LoggerLike
  url: string
}) {
  let unavailableReported = false

  const reportUnavailable = (error: unknown) => {
    if (unavailableReported)
      return

    unavailableReported = true
    deps.logger.withFields({
      url: deps.url,
      error: errorMessageFrom(error) ?? 'Unknown error',
    }).warn('AIJADE server is unavailable; continuing startup without AIJADE and retrying in background')
  }

  const reportDisconnected = () => {
    deps.logger.withFields({
      url: deps.url,
    }).warn('AIJADE server connection closed; retrying in background')
  }

  void client.connect()
    .then(() => {
      deps.logger.withFields({
        url: deps.url,
      }).log(
        unavailableReported
          ? 'Connected to AIJADE server after background retry'
          : 'Connected to AIJADE server',
      )
      unavailableReported = false
    })
    .catch((error) => {
      deps.logger.withFields({
        url: deps.url,
        error: errorMessageFrom(error) ?? 'Unknown error',
      }).warn('AIJADE client stopped retrying')
    })

  return {
    reportUnavailable,
    reportDisconnected,
  }
}
