using Aijade.Core.Js;
using Aijade.Memory.Model;

namespace Aijade.Memory.Dynamics;

// Retrieval-triggered destabilise → restabilise (Nader et al., 2000). Opt-in: a no-op unless enabled, and the default
// detector never mutates, so the default memory path is unchanged.

public sealed record ReconsolidationConfig(bool Enabled = false, double LabileWindowMs = 60 * 60 * 1000, double CooldownMs = 60 * 1000, int MaxVersions = 10)
{
    public static ReconsolidationConfig Default { get; } = new();
}

public enum ReconsolidationKind
{
    None,
    Contradiction,
    Update,
}

public sealed record ReconsolidationVerdict(ReconsolidationKind Kind, double Confidence, string? ProposedContent = null, double? ProposedConfidence = null);

public sealed record ReconsolidationEvent(double Timestamp, string FactId, int FromVersion, int ToVersion, ReconsolidationKind Kind, string Summary);

public sealed record ReconsolidatedFact(SemanticFact Fact, int Version, double LastUpdatedAt);

public interface IContradictionDetector
{
    ReconsolidationVerdict Evaluate(SemanticFact existing, string candidate);
}

/// <summary>Safe default: never proposes a change.</summary>
public sealed class NoOpDetector : IContradictionDetector
{
    public static NoOpDetector Instance { get; } = new();

    public ReconsolidationVerdict Evaluate(SemanticFact existing, string candidate) => new(ReconsolidationKind.None, 0);
}

public sealed class ReconsolidationEngine(ReconsolidationConfig? config = null, IContradictionDetector? detector = null)
{
    private readonly ReconsolidationConfig _config = config ?? ReconsolidationConfig.Default;
    private readonly IContradictionDetector _detector = detector ?? NoOpDetector.Instance;
    private readonly Dictionary<string, double> _labile = [];
    private readonly Dictionary<string, double> _lastApplied = [];
    private readonly Dictionary<string, int> _versions = [];
    private readonly List<ReconsolidationEvent> _audit = [];

    public IReadOnlyList<ReconsolidationEvent> AuditTrail => _audit;

    /// <summary>Open the lability window after retrieval.</summary>
    public void MarkLabile(string factId, double now)
    {
        if (_config.Enabled)
            _labile[factId] = now + _config.LabileWindowMs;
    }

    public bool IsLabile(string factId, double now)
    {
        if (!_labile.TryGetValue(factId, out var until))
            return false;
        if (now > until)
        {
            _labile.Remove(factId);
            return false;
        }
        return true;
    }

    /// <summary>
    /// Update a retrieved fact only when the engine is on, the fact is labile, the detector proposes a change, the
    /// cooldown has elapsed and the version cap is not reached. Returns null when nothing changed.
    /// </summary>
    public (ReconsolidatedFact? Updated, ReconsolidationEvent? Event) Reconsolidate(SemanticFact fact, string candidate, double now)
    {
        if (!_config.Enabled || !IsLabile(fact.Id, now))
            return (null, null);
        var verdict = _detector.Evaluate(fact, candidate);
        if (verdict.Kind == ReconsolidationKind.None)
            return (null, null);
        if (_lastApplied.TryGetValue(fact.Id, out var last) && now - last < _config.CooldownMs)
            return (null, null);
        var from = _versions.GetValueOrDefault(fact.Id);
        if (from >= _config.MaxVersions)
            return (null, null);

        var to = from + 1;
        _versions[fact.Id] = to;
        _lastApplied[fact.Id] = now;
        var updated = new SemanticFact
        {
            Id = fact.Id,
            Content = verdict.ProposedContent ?? fact.Content,
            DerivedFrom = fact.DerivedFrom,
            CreatedAt = fact.CreatedAt,
            LastAccessedAt = fact.LastAccessedAt,
            AccessCount = fact.AccessCount,
            Confidence = verdict.ProposedConfidence ?? fact.Confidence,
            BaseStrength = fact.BaseStrength,
            Durability = fact.Durability,
            ContextTags = fact.ContextTags,
            Salience = fact.Salience,
            Affect = fact.Affect,
            MemoryType = fact.MemoryType,
            Status = fact.Status,
            ValidTime = fact.ValidTime,
        };
        var kind = verdict.Kind == ReconsolidationKind.Contradiction ? "contradiction" : "update";
        var ev = new ReconsolidationEvent(now, fact.Id, from, to, verdict.Kind,
            $"{kind} applied (conf {JsFormat.Number(fact.Confidence)}→{JsFormat.Number(updated.Confidence)})");
        _audit.Add(ev);
        return (new ReconsolidatedFact(updated, to, now), ev);
    }
}
