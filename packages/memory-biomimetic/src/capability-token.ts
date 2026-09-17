import type { CapabilityGrant } from './contracts'

export interface CapabilityToken {
  token: string
  capability: string
  scope: string
  grantee: { agentId?: string, userScope?: string }
  issuedAt: number
  expiresAt?: number
  grantId: string
}

export interface CapabilityTokenSigner {
  sign: (claims: Omit<CapabilityToken, 'token'>) => Promise<string>
  verify: (token: string) => Promise<Omit<CapabilityToken, 'token'>>
}

export interface MemoryWriteGateInput {
  token: string
  capability: string
  scope: string
  now?: number
}

export interface MemoryWriteGate {
  authorize: (input: MemoryWriteGateInput) => Promise<CapabilityToken>
}

/**
 * The kernel never invents credentials. A deployment supplies a signer backed
 * by its auth/KMS layer, while this gate enforces capability, scope and expiry
 * immediately before a memory transaction is committed.
 */
export function createMemoryWriteGate(
  signer: CapabilityTokenSigner,
  grants: readonly CapabilityGrant[],
): MemoryWriteGate {
  return {
    async authorize(input) {
      const claims = await signer.verify(input.token)
      const now = input.now ?? Date.now()
      if (claims.capability !== input.capability)
        throw new Error('memory write denied: capability mismatch')
      if (claims.scope !== input.scope)
        throw new Error('memory write denied: scope mismatch')
      if (claims.issuedAt > now || (claims.expiresAt !== undefined && claims.expiresAt <= now))
        throw new Error('memory write denied: token expired or not yet valid')
      const grant = grants.find(candidate =>
        candidate.id === claims.grantId
        && candidate.capability === claims.capability
        && candidate.scope === claims.scope
        && candidate.issuedAt <= now
        && (candidate.expiresAt === undefined || candidate.expiresAt > now),
      )
      if (!grant)
        throw new Error('memory write denied: no active capability grant')
      return { token: input.token, ...claims }
    },
  }
}
