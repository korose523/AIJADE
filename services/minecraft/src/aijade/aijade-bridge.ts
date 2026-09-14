import type { Client, ContextUpdate, ModuleAnnouncedEvent } from '@proj-aijade/server-sdk'

import type { EventBus } from '../cognitive/event-bus'

import { useLogg } from '@guiiai/logg'
import { ContextUpdateStrategy } from '@proj-aijade/server-sdk'
import { nanoid } from 'nanoid'

interface SparkCommandData {
  commandId: string
  intent: 'plan' | 'proposal' | 'action' | 'pause' | 'resume' | 'reroute' | 'context'
  interrupt: 'force' | 'soft' | false
  priority: 'critical' | 'high' | 'normal' | 'low'
  guidance?: {
    options?: Array<{ label: string, steps: string[] }>
  }
}

export class AijadeBridge {
  private readonly logger = useLogg('aijade-bridge').useGlobalConfig()
  private commandHandler: ((event: { data: SparkCommandData }) => void) | null = null
  private contextUpdateHandler: ((event: { data: ContextUpdate }) => void) | null = null
  private moduleAnnouncedHandler: ((event: { data: ModuleAnnouncedEvent }) => void) | null = null
  private readonly moduleAnnouncedListeners = new Set<(event: ModuleAnnouncedEvent) => void>()

  constructor(
    private readonly client: Client,
    private readonly eventBus: EventBus,
  ) {}

  init(): void {
    this.commandHandler = (event) => {
      const cmd = event.data
      this.logger.log('Received spark:command', { intent: cmd.intent, commandId: cmd.commandId })

      // Acknowledge receipt
      this.client.send({
        type: 'spark:emit',
        data: {
          id: nanoid(),
          eventId: cmd.commandId,
          state: 'queued',
          note: 'Command received',
        },
      } as Parameters<typeof this.client.send>[0])

      // Route by intent
      if (cmd.intent === 'context') {
        this.handleContextIntent(cmd)
      }
      else {
        this.handleActionIntent(cmd)
      }
    }

    this.contextUpdateHandler = (event) => {
      const ctx = event.data
      this.logger.log('Received context:update', { lane: ctx.lane, preview: ctx.text.slice(0, 80) })

      this.eventBus.emit({
        type: 'signal:aijade_context',
        payload: Object.freeze({
          type: 'aijade_context' as const,
          description: ctx.text,
          sourceId: 'aijade',
          confidence: 1.0,
          timestamp: Date.now(),
          metadata: {
            source: 'aijade',
            contextId: ctx.contextId,
            lane: ctx.lane ?? 'general',
            hints: ctx.hints ?? [],
          },
        }),
        source: { component: 'aijade', id: 'bridge' },
      })
    }

    this.moduleAnnouncedHandler = (event) => {
      const moduleAnnouncement = event.data
      this.logger.log('Received module:announced', { name: moduleAnnouncement.name, pluginId: moduleAnnouncement.identity?.plugin?.id })
      for (const listener of this.moduleAnnouncedListeners) {
        listener(moduleAnnouncement)
      }
    }

    this.client.onEvent('spark:command', this.commandHandler as Parameters<typeof this.client.onEvent<'spark:command'>>[1])
    this.client.onEvent('context:update', this.contextUpdateHandler as Parameters<typeof this.client.onEvent<'context:update'>>[1])
    this.client.onEvent('module:announced', this.moduleAnnouncedHandler as Parameters<typeof this.client.onEvent<'module:announced'>>[1])
    this.logger.log('AijadeBridge initialized, listening for spark:command, context:update, and module:announced')
  }

  destroy(): void {
    if (this.commandHandler) {
      this.client.offEvent('spark:command', this.commandHandler as Parameters<typeof this.client.offEvent<'spark:command'>>[1])
      this.commandHandler = null
    }
    if (this.contextUpdateHandler) {
      this.client.offEvent('context:update', this.contextUpdateHandler as Parameters<typeof this.client.offEvent<'context:update'>>[1])
      this.contextUpdateHandler = null
    }
    if (this.moduleAnnouncedHandler) {
      this.client.offEvent('module:announced', this.moduleAnnouncedHandler as Parameters<typeof this.client.offEvent<'module:announced'>>[1])
      this.moduleAnnouncedHandler = null
    }
    this.moduleAnnouncedListeners.clear()
    this.logger.log('AijadeBridge destroyed')
  }

  sendNotify(headline: string, note?: string, urgency: 'immediate' | 'soon' | 'later' = 'soon'): void {
    this.client.send({
      type: 'spark:notify',
      data: {
        id: nanoid(),
        eventId: nanoid(),
        kind: 'ping',
        urgency,
        headline,
        note,
        destinations: ['proj-aijade:stage-*'],
      },
    } as Parameters<typeof this.client.send>[0])
    this.logger.log('Sent spark:notify', { headline, urgency })
  }

  sendContextUpdate(text: string, hints?: string[], lane?: string): void
  sendContextUpdate(update: ContextUpdate): void
  sendContextUpdate(textOrUpdate: string | Omit<ContextUpdate, 'strategy' | 'id' | 'contextId'> & { contextId?: string }, hints?: string[], lane = 'game'): void {
    const update = typeof textOrUpdate === 'string'
      ? {
        text: textOrUpdate,
        hints,
        lane,
        strategy: ContextUpdateStrategy.AppendSelf,
      } satisfies Omit<ContextUpdate, 'id' | 'contextId'> & { contextId?: string }
      : {
          strategy: ContextUpdateStrategy.AppendSelf,
          ...textOrUpdate,
        }

    const contextId = update.contextId ?? nanoid()
    this.client.send({
      type: 'context:update',
      data: {
        id: nanoid(),
        contextId,
        lane: update.lane,
        text: update.text,
        hints: update.hints,
        strategy: update.strategy,
        destinations: update.destinations,
      },
    } as Parameters<typeof this.client.send>[0])
    this.logger.log('Sent context:update', { lane: update.lane, preview: update.text.slice(0, 80), contextId })
  }

  sendEmit(eventId: string, state: 'queued' | 'working' | 'done' | 'dropped', note?: string): void {
    this.client.send({
      type: 'spark:emit',
      data: {
        id: nanoid(),
        eventId,
        state,
        note,
      },
    } as Parameters<typeof this.client.send>[0])
    this.logger.log('Sent spark:emit', { eventId, state })
  }

  onModuleAnnounced(listener: (event: ModuleAnnouncedEvent) => void) {
    this.moduleAnnouncedListeners.add(listener)

    return () => {
      this.moduleAnnouncedListeners.delete(listener)
    }
  }

  private handleActionIntent(cmd: SparkCommandData): void {
    const steps = cmd.guidance?.options?.[0]?.steps ?? []
    const instructionText = steps.length > 0
      ? steps.join('\n')
      : `${cmd.intent} command received`

    this.eventBus.emit({
      type: 'signal:aijade_command',
      payload: Object.freeze({
        type: 'aijade_command' as const,
        description: `[AIJADE] Instruction: ${instructionText}`,
        sourceId: 'aijade',
        confidence: 1.0,
        timestamp: Date.now(),
        metadata: {
          source: 'aijade',
          commandId: cmd.commandId,
          intent: cmd.intent,
          interrupt: cmd.interrupt,
          priority: cmd.priority,
        },
      }),
      source: { component: 'aijade', id: 'bridge' },
    })
  }

  private handleContextIntent(cmd: SparkCommandData): void {
    const steps = cmd.guidance?.options?.[0]?.steps ?? []
    const contextText = steps.length > 0
      ? steps.join('\n')
      : 'Context update from AIJADE'

    this.eventBus.emit({
      type: 'signal:aijade_context',
      payload: Object.freeze({
        type: 'aijade_context' as const,
        description: contextText,
        sourceId: 'aijade',
        confidence: 1.0,
        timestamp: Date.now(),
        metadata: {
          source: 'aijade',
          commandId: cmd.commandId,
        },
      }),
      source: { component: 'aijade', id: 'bridge' },
    })
  }
}
