using Aijade.Core.Js;
using Aijade.Memory.Contracts;
using Aijade.Memory.Development;

namespace Aijade.Growth.Services;

// The runtime executor for signed releases: rollout state is persisted before a version is exposed, rollback is a
// durable transition, and every routing decision at a service entry point is recorded as a trace.
//
// activate() stores the release next to its rollout state before exposing it, so active() can load it by id and select()
// can route users into a canary.

public sealed record ReleaseState(string ReleaseId, string Version, double CanaryRatio, string Status, double UpdatedAt, string? Reason = null);

/// <summary>A recorded routing decision.</summary>
public sealed record RoutingTrace(
    string TraceId, double Bucket, double CanaryRatio, bool Eligible, RoutingIdentityKind IdentityKind, double RecordedAt, string? ReleaseId = null,
    string? Version = null, string? UserId = null, string? SessionId = null);

public sealed class ReleaseExecutor(GrowthPorts ports)
{
    public const string Kind = "release_execution";
    public const string TraceKind = "release_routing_trace";
    private const string StateKey = "current";

    private async Task<SignedRelease?> LoadActiveAsync(CancellationToken cancellationToken)
    {
        var state = await ports.Storage.GetAsync<ReleaseState>(Kind, StateKey, cancellationToken).ConfigureAwait(false);
        if (state is null || state.Status == "rolled_back")
            return null;
        return await ports.Storage.GetAsync<SignedRelease>(Kind, state.ReleaseId, cancellationToken).ConfigureAwait(false);
    }

    public async Task ActivateAsync(SignedRelease release, double? now = null, CancellationToken cancellationToken = default)
    {
        var at = now ?? ports.Scheduler.Now();
        if (!release.RollbackAvailable)
            throw new InvalidOperationException("release activation denied: rollback is unavailable");
        var state = new ReleaseState(release.Id, release.Version, release.CanaryRatio, release.CanaryRatio < 1 ? "canary" : "active", at);
        await ports.Storage.PutAsync(Kind, release.Id, release, cancellationToken).ConfigureAwait(false);
        await ports.Storage.PutAsync(Kind, StateKey, state, cancellationToken).ConfigureAwait(false);
        if (state.Status == "canary")
            return;
        await ports.Storage.PutAsync(Kind, StateKey, state with { Status = "active", UpdatedAt = at }, cancellationToken).ConfigureAwait(false);
    }

    public async Task RollbackAsync(string releaseId, string reason, double? now = null, CancellationToken cancellationToken = default)
    {
        var at = now ?? ports.Scheduler.Now();
        if (JsText.Trim(reason).Length == 0)
            throw new InvalidOperationException("release rollback requires a reason");
        var current = await ports.Storage.GetAsync<ReleaseState>(Kind, StateKey, cancellationToken).ConfigureAwait(false);
        if (current is null || current.ReleaseId != releaseId)
            throw new InvalidOperationException("release rollback denied: release is not active");
        await ports.Storage.PutAsync(Kind, StateKey, current with { Status = "rolled_back", Reason = reason, UpdatedAt = at }, cancellationToken).ConfigureAwait(false);
    }

    public Task<SignedRelease?> ActiveAsync(CancellationToken cancellationToken = default) => LoadActiveAsync(cancellationToken);

    /// <summary>Resolve the release for a real user / session at a service entry point.</summary>
    public async Task<VseRouteDecision> SelectAsync(VseRoutingIdentity identity, string? traceId = null, CancellationToken cancellationToken = default)
    {
        var trace = traceId ?? ports.IdGen.NewId("vse");
        var bucket = Vse.StableBucket(identity);
        var active = await LoadActiveAsync(cancellationToken).ConfigureAwait(false);
        var canaryRatio = active?.CanaryRatio ?? 0;
        var eligible = active is not null && bucket < canaryRatio;
        var kind = JsText.Trim(identity.UserId ?? "").Length > 0 ? RoutingIdentityKind.User : RoutingIdentityKind.Session;
        var decision = new VseRouteDecision(trace, bucket, canaryRatio, eligible, kind, eligible ? active!.Id : null, eligible ? active!.Version : null);
        await ports.Storage.PutAsync(TraceKind, trace, new RoutingTrace(trace, bucket, canaryRatio, eligible, kind, ports.Scheduler.Now(), decision.ReleaseId,
            decision.Version, identity.UserId, identity.SessionId), cancellationToken).ConfigureAwait(false);
        return decision;
    }
}
