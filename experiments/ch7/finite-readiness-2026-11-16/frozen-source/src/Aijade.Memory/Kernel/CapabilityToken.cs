using Aijade.Memory.Contracts;

namespace Aijade.Memory.Kernel;


/// <summary>The verified claims of a capability token (the token string itself is carried separately).</summary>
public sealed record CapabilityClaims(string GrantId, string Capability, string Scope, Grantee Grantee, double IssuedAt, double? ExpiresAt = null);

public sealed record CapabilityToken(string Token, CapabilityClaims Claims);

/// <summary>Signs and verifies capability tokens. Supplied by the deployment (auth / KMS layer); the kernel never invents credentials.</summary>
public interface ICapabilityTokenSigner
{
    Task<string> SignAsync(CapabilityClaims claims, CancellationToken cancellationToken = default);

    /// <summary>Returns the claims of a genuine token; throws if the token is forged or malformed.</summary>
    Task<CapabilityClaims> VerifyAsync(string token, CancellationToken cancellationToken = default);
}

public sealed class MemoryWriteDeniedException(string message) : Exception(message);

/// <summary>Enforces capability, scope and expiry immediately before a memory transaction is committed.</summary>
public sealed class MemoryWriteGate(ICapabilityTokenSigner signer, IReadOnlyList<CapabilityGrant> grants, TimeProvider? time = null)
{
    private readonly TimeProvider _time = time ?? TimeProvider.System;

    /// <summary>Verify the token and check it against the active grants; <paramref name="now"/> is ms since the Unix epoch (default: current time).</summary>
    public async Task<CapabilityToken> AuthorizeAsync(string token, string capability, string scope, double? now = null, CancellationToken cancellationToken = default)
    {
        var claims = await signer.VerifyAsync(token, cancellationToken).ConfigureAwait(false);
        var t = now ?? _time.GetUtcNow().ToUnixTimeMilliseconds();
        if (claims.Capability != capability)
            throw new MemoryWriteDeniedException("memory write denied: capability mismatch");
        if (claims.Scope != scope)
            throw new MemoryWriteDeniedException("memory write denied: scope mismatch");
        if (claims.IssuedAt > t || (claims.ExpiresAt is { } exp && exp <= t))
            throw new MemoryWriteDeniedException("memory write denied: token expired or not yet valid");
        var active = grants.Any(g =>
            g.Id == claims.GrantId
            && g.Capability == claims.Capability
            && g.Scope == claims.Scope
            && g.IssuedAt <= t
            && (g.ExpiresAt is not { } gexp || gexp > t));
        if (!active)
            throw new MemoryWriteDeniedException("memory write denied: no active capability grant");
        return new CapabilityToken(token, claims);
    }
}
