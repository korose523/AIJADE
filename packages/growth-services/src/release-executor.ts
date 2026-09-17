import type { SignedRelease, VseRouteDecision, VseRoutingIdentity } from '@proj-aijade/memory-biomimetic'

import type { SchedulerPort, StoragePort } from './ports'

import { stableVseBucket } from '@proj-aijade/memory-biomimetic'

import { genId } from './util'

export interface ReleaseExecutor {
  activate: (release: SignedRelease, now?: number) => Promise<void>
  rollback: (releaseId: string, reason: string, now?: number) => Promise<void>
  active: () => Promise<SignedRelease | undefined>
  /** Resolve the release for a real user/session at a service entry point. */
  select: (identity: VseRoutingIdentity, traceId?: string) => Promise<VseRouteDecision>
}

interface ReleaseState {
  releaseId: string
  version: string
  canaryRatio: number
  status: 'canary' | 'active' | 'rolled_back'
  updatedAt: number
  reason?: string
}

const STATE_KEY = 'current'
const KIND = 'release_execution'
const TRACE_KIND = 'release_routing_trace'

/**
 * The runtime executor for signed releases. It persists the rollout state
 * before exposing a version as active, and rollback is an explicit durable
 * transition rather than a log-only operation.
 */
export function createReleaseExecutor(
  deps: { storage: StoragePort, scheduler: SchedulerPort },
): ReleaseExecutor {
  const loadActive = async (): Promise<SignedRelease | undefined> => {
    const state = await deps.storage.get<ReleaseState>(KIND, STATE_KEY)
    if (!state || state.status === 'rolled_back')
      return undefined
    return deps.storage.get<SignedRelease>(KIND, state.releaseId)
  }

  return {
    async activate(release, now = deps.scheduler.now()) {
      if (!release.rollbackAvailable)
        throw new Error('release activation denied: rollback is unavailable')
      const state: ReleaseState = {
        releaseId: release.id,
        version: release.version,
        canaryRatio: release.canaryRatio,
        status: release.canaryRatio < 1 ? 'canary' : 'active',
        updatedAt: now,
      }
      await deps.storage.put(KIND, STATE_KEY, state)
      if (state.status === 'canary')
        return
      await deps.storage.put(KIND, STATE_KEY, { ...state, status: 'active', updatedAt: now })
    },
    async rollback(releaseId, reason, now = deps.scheduler.now()) {
      if (!reason.trim())
        throw new Error('release rollback requires a reason')
      const current = await deps.storage.get<ReleaseState>(KIND, STATE_KEY)
      if (!current || current.releaseId !== releaseId)
        throw new Error('release rollback denied: release is not active')
      await deps.storage.put(KIND, STATE_KEY, {
        ...current,
        status: 'rolled_back',
        reason,
        updatedAt: now,
      })
    },
    async active() {
      return loadActive()
    },
    async select(identity, traceId = genId('vse')) {
      const bucket = stableVseBucket(identity)
      const activeRelease = await loadActive()
      const canaryRatio = activeRelease?.canaryRatio ?? 0
      const eligible = !!activeRelease && bucket < canaryRatio
      const decision: VseRouteDecision = {
        traceId,
        releaseId: eligible ? activeRelease.id : undefined,
        version: eligible ? activeRelease.version : undefined,
        bucket,
        canaryRatio,
        eligible,
        identityKind: identity.userId?.trim() ? 'user' : 'session',
      }
      await deps.storage.put(TRACE_KIND, traceId, {
        ...decision,
        userId: identity.userId,
        sessionId: identity.sessionId,
        recordedAt: deps.scheduler.now(),
      })
      return decision
    },
  }
}
