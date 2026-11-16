using Aijade.Core.Js;
using Aijade.Memory.Dynamics;
using Aijade.Memory.Model;

namespace Aijade.Memory.Lifecycle;

// Two-stage auditable forgetting (v3 §5 / v4 §7.4). Stage one, soft forgetting: strength decays and a weak memory is
// demoted a tier (hot → warm → cold), never deleted. Stage two, hard forgetting: a cold memory never accessed for
// T days becomes a deletion *candidate*, which can be previewed, retained by id, or committed with an audit record.
// Nothing is ever deleted silently.

public enum MemoryTier
{
    Hot,
    Warm,
    Cold,
}

/// <summary>Demote below <see cref="DemoteBelow"/>, hot from <see cref="HotAbove"/>, deletion candidate after <see cref="ColdDwellDays"/> cold and unaccessed.</summary>
public sealed record ForgettingThresholds(double DemoteBelow = 0.25, double HotAbove = 0.6, double ColdDwellDays = 30)
{
    public static ForgettingThresholds Default { get; } = new();
}

public sealed record SweepInput(string Id, double CreatedAt, double LastAccessedAt, int AccessCount, double BaseStrength, double Durability, MemoryTier? Tier = null);

public sealed record SweepResult(string Id, double Strength, MemoryTier Tier, bool Demoted, bool DeletionCandidate, string? Reason = null);

public enum DeletionResolution
{
    Deleted,
    Retained,
}

/// <summary>The gate that made the decision, recorded for audit (v4 §5.5 gate_snapshot).</summary>
public sealed record GateSnapshot(double DecayMultiplier, double RetrievalNoise);

public sealed class DeletionLedgerEntry(string id, double queuedAt, string reason, GateSnapshot gateSnapshot)
{
    public string Id { get; } = id;
    public double QueuedAt { get; } = queuedAt;
    public string Reason { get; } = reason;
    public GateSnapshot GateSnapshot { get; } = gateSnapshot;
    public double? ResolvedAt { get; internal set; }
    public DeletionResolution? Resolution { get; internal set; }
}

public static class ForgettingSweep
{
    private const double DayMs = 86_400_000;

    /// <summary>Strength → tier; depends on strength only, not on access.</summary>
    public static MemoryTier TierOf(double strength, ForgettingThresholds? thresholds = null)
    {
        var t = thresholds ?? ForgettingThresholds.Default;
        return strength >= t.HotAbove ? MemoryTier.Hot : strength >= t.DemoteBelow ? MemoryTier.Warm : MemoryTier.Cold;
    }

    /// <summary>
    /// One forgetting sweep of one memory. Tiers only go down within a sweep (an access raises strength, so the memory
    /// warms up again on a later sweep; promoting mid-sweep would make the result depend on sweep order).
    /// </summary>
    public static SweepResult Sweep(SweepInput item, double now, ForgettingConfig f, double decayMultiplier, ForgettingThresholds? thresholds = null)
    {
        var t = thresholds ?? ForgettingThresholds.Default;
        var dtDays = Math.Max(0, now - item.CreatedAt) / DayMs;
        var spacing = Math.Pow(1 + item.AccessCount, f.SpacingBeta);
        var decayed = item.BaseStrength * item.Durability * spacing * Math.Exp(-dtDays * f.BaseDecay * decayMultiplier);
        var strength = Math.Max(0, decayed);

        var next = TierOf(strength, t);
        var prev = item.Tier ?? next;
        var tier = next > prev ? next : prev;
        var demoted = tier > prev;

        var dwellDays = (now - item.LastAccessedAt) / DayMs;
        if (tier == MemoryTier.Cold && item.AccessCount == 0 && dwellDays >= t.ColdDwellDays)
        {
            return new SweepResult(item.Id, strength, tier, demoted, true,
                $"cold tier, accessCount=0, dwell={JsFormat.ToFixed(dwellDays, 1)}d >= {JsFormat.Number(t.ColdDwellDays)}d");
        }
        return new SweepResult(item.Id, strength, tier, demoted, false);
    }

    /// <summary>Sweep with the decay multiplier of the gate derived from the coefficients and state.</summary>
    public static SweepResult SweepWithGate(SweepInput item, double now, ForgettingConfig f, GatingCoefficients g, PhysiologicalState state, ForgettingThresholds? thresholds = null) =>
        Sweep(item, now, f, Plasticity.GateFromCoefficients(g, state).DecayMultiplier, thresholds);
}

/// <summary>The deletion ledger. <see cref="Commit"/> is the only path by which anything disappears, and it always leaves a record.</summary>
public sealed class DeletionLedger
{
    private readonly List<DeletionLedgerEntry> _entries = [];

    private DeletionLedgerEntry? Open(string id) => _entries.Find(e => e.Id == id && e.Resolution is null);

    /// <summary>Queue a candidate (stage two). Deletes nothing; an id already pending is not queued twice.</summary>
    public void Enqueue(string id, string reason, double now, GateSnapshot gate)
    {
        if (Open(id) is null)
            _entries.Add(new DeletionLedgerEntry(id, now, reason, gate));
    }

    /// <summary>Retain by id (withdraw the candidate).</summary>
    public bool Retain(string id, double now) => Resolve(id, now, DeletionResolution.Retained);

    /// <summary>Delete for real, with an audit record.</summary>
    public bool Commit(string id, double now) => Resolve(id, now, DeletionResolution.Deleted);

    private bool Resolve(string id, double now, DeletionResolution resolution)
    {
        if (Open(id) is not { } e)
            return false;
        e.Resolution = resolution;
        e.ResolvedAt = now;
        return true;
    }

    public IReadOnlyList<DeletionLedgerEntry> Pending() => _entries.Where(e => e.Resolution is null).ToList();

    public IReadOnlyList<DeletionLedgerEntry> All() => _entries;
}
