import type { WebSocketEventOptionalSource } from '@proj-aijade/server-sdk'

import type { Events } from './types'

import { useLogger } from '@guiiai/logg'
import { ContextUpdateStrategy, Client as ServerClient } from '@proj-aijade/server-sdk'
import { nanoid } from 'nanoid'

export class Client {
  private client: ServerClient<Events> | null = null

  async connect(): Promise<boolean> {
    try {
      this.client = new ServerClient<Events>({ name: 'proj-aijade:plugin-vscode' })
      await this.client.connect()
      useLogger().log('AIJADE connected to Server Channel')
      return true
    }
    catch (error) {
      useLogger().errorWithError('Failed to connect to AIJADE Server Channel:', error)
      return false
    }
  }

  disconnect(): void {
    if (this.client) {
      this.client.close()
      this.client = null
      useLogger().log('AIJADE disconnected')
    }
  }

  private async send(event: WebSocketEventOptionalSource<Events>): Promise<void> {
    if (!this.client) {
      useLogger().warn('Cannot send event: not connected to AIJADE Server Channel')
      return
    }

    try {
      await this.client.connect()
      this.client.send(event)
    }
    catch (error) {
      useLogger().errorWithError('Failed to send event to AIJADE:', error)
    }
  }

  async replaceContext(context: string): Promise<void> {
    const id = nanoid()
    this.send({ type: 'context:update', data: { strategy: ContextUpdateStrategy.ReplaceSelf, text: context, id, contextId: id } })
  }

  async appendContext(context: string): Promise<void> {
    const id = nanoid()
    this.send({ type: 'context:update', data: { strategy: ContextUpdateStrategy.AppendSelf, text: context, id, contextId: id } })
  }

  isConnected(): boolean {
    return !!this.client
  }
}
