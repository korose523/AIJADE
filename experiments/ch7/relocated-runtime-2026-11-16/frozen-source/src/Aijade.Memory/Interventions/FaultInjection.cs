using Aijade.Core.Js;
using Aijade.Memory.Contracts;
using Aijade.Memory.Experiments;
using Aijade.Memory.Model;

namespace Aijade.Memory.Interventions;

// v7 §38 opt-in fault injection on the memory-retrieval path, using the AgentChaos taxonomy. Default off; the
// selection is drawn from the §38 intervention RNG in id-sorted order, so the same (config, candidates) always gives the
// same perturbation. component_crash throws so the store's fail-closed degradation is exercised.
// Scope (stated): it perturbs retrieval results, not the event bus or scheduler.

public enum FaultKind
{
    MessageDrop,
    LatencyInjection,
    ValueCorruption,
    ComponentCrash,
    DuplicateEvent,
}

/// <summary>
/// Default off. <c>Rate</c> is the fraction of eligible candidates perturbed; <c>Seed</c> drives the §38 RNG. <c>Target</c>: for
/// component_crash, a candidate kind ("episode", "fact", "procedural", "working"; default: the first kind present); for other
/// faults, an optional substring of candidate ids (default: every candidate is eligible).
/// </summary>
public sealed record FaultInjectionConfig(bool Enabled, FaultKind Kind, double Rate, double Seed, string? Target = null, double MaxLatencyMs = 500)
{
    public static FaultInjectionConfig Default { get; } = new(false, FaultKind.MessageDrop, 0.2, 0);
}

public sealed record FaultReport(FaultKind Kind, double Seed, int Applied, int Total, string Detail, double? LatencyMs = null, CandidateKind? CrashedComponent = null);

/// <summary>Thrown by component_crash; the store catches it and serves the remaining healthy stores.</summary>
public sealed class FaultInjectedException(CandidateKind component, FaultReport report)
    : Exception($"fault-injection: component \"{FaultInjection.KindName(component)}\" crashed (fail-closed engaged)")
{
    public CandidateKind Component { get; } = component;

    public FaultReport Report { get; } = report;
}

public static class FaultInjection
{
    /// <summary>The wire names of the fault kinds.</summary>
    public static string WireName(FaultKind kind) => kind switch
    {
        FaultKind.MessageDrop => "message_drop",
        FaultKind.LatencyInjection => "latency_injection",
        FaultKind.ValueCorruption => "value_corruption",
        FaultKind.ComponentCrash => "component_crash",
        FaultKind.DuplicateEvent => "duplicate_event",
        _ => throw new ArgumentOutOfRangeException(nameof(kind)),
    };

    public static string KindName(CandidateKind kind) => kind.ToString().ToLowerInvariant();

    internal static CandidateKind? ParseKind(string? s) =>
        Enum.GetValues<CandidateKind>().Cast<CandidateKind?>().FirstOrDefault(k => KindName(k!.Value) == s);

    /// <summary>Register a fault scenario as a §38 ExperimentManifest, on the same chain as every other experiment.</summary>
    public static ExperimentManifest Register(FaultInjectionConfig config, ExperimentRegistry registry, IReadOnlyList<string>? metrics = null)
    {
        var kind = WireName(config.Kind);
        var manifest = ExperimentManifests.Build(new ManifestSpec(
            $"fault:{kind}",
            $"Fault injection ({kind})",
            [new ExperimentCondition(kind, "AgentChaos-style fault injected into the memory-retrieval result.", new OrderedDictionary<string, object?>
            {
                ["kind"] = kind,
                ["target"] = config.Target,
                ["rate"] = config.Rate,
                ["seed"] = config.Seed,
                ["maxLatencyMs"] = config.MaxLatencyMs,
            })],
            metrics ?? ["fault.kind", "fault.rate", "fault.applied"],
            Seed: config.Seed,
            Notes: "§38 fault-injection harness (AgentChaos taxonomy). Opt-in, default-off, deterministic via interventionRng(seed)."));
        registry.Register(manifest);
        return manifest;
    }
}

/// <summary>Deterministic injector: pure with respect to (config, candidate list).</summary>
public sealed class FaultInjector(FaultInjectionConfig config)
{
    public (IReadOnlyList<ScoredCandidate> Candidates, FaultReport Report) Apply(IReadOnlyList<ScoredCandidate> candidates)
    {
        var eligible = Eligible(candidates);
        return config.Kind switch
        {
            FaultKind.MessageDrop => Drop(candidates, eligible),
            FaultKind.DuplicateEvent => Duplicate(candidates, eligible),
            FaultKind.ValueCorruption => Corrupt(candidates, eligible),
            FaultKind.LatencyInjection => Latency(candidates, eligible.Count),
            FaultKind.ComponentCrash => Crash(candidates),
            _ => throw new ArgumentOutOfRangeException(nameof(candidates), $"unknown fault kind: {config.Kind}"),
        };
    }

    private List<ScoredCandidate> Eligible(IReadOnlyList<ScoredCandidate> candidates)
    {
        var t = config.Target;
        if (!string.IsNullOrEmpty(t) && FaultInjection.ParseKind(t) is null)
            return candidates.Where(c => c.Id.Contains(t, StringComparison.Ordinal)).ToList();
        return candidates.ToList();
    }

    /// <summary>Draw in id-sorted order, so the selection does not depend on input order.</summary>
    private HashSet<string> Draw(List<ScoredCandidate> eligible)
    {
        var rng = Interventions.Rng(config.Seed);
        var selected = new HashSet<string>(StringComparer.Ordinal);
        foreach (var c in eligible.OrderBy(c => c.Id, StringComparer.Ordinal))
        {
            if (rng() < config.Rate)
                selected.Add(c.Id);
        }
        return selected;
    }

    private (IReadOnlyList<ScoredCandidate>, FaultReport) Drop(IReadOnlyList<ScoredCandidate> candidates, List<ScoredCandidate> eligible)
    {
        var drop = Draw(eligible);
        return (candidates.Where(c => !drop.Contains(c.Id)).ToList(),
            new FaultReport(FaultKind.MessageDrop, config.Seed, drop.Count, eligible.Count,
                $"dropped {drop.Count}/{eligible.Count} candidates (rate={JsFormat.Number(config.Rate)})"));
    }

    private (IReadOnlyList<ScoredCandidate>, FaultReport) Duplicate(IReadOnlyList<ScoredCandidate> candidates, List<ScoredCandidate> eligible)
    {
        var dup = Draw(eligible);
        // A hash of (seed, id) makes each duplicate distinguishable yet reproducible.
        var extra = candidates.Where(c => dup.Contains(c.Id))
            .Select(c => c with { Id = $"{c.Id}:dup:{JsFormat.Fnv1a($"{JsFormat.Number(config.Seed)}:{c.Id}")[..8]}" });
        return ([.. candidates, .. extra],
            new FaultReport(FaultKind.DuplicateEvent, config.Seed, dup.Count, eligible.Count, $"duplicated {dup.Count}/{eligible.Count} candidates"));
    }

    private (IReadOnlyList<ScoredCandidate>, FaultReport) Corrupt(IReadOnlyList<ScoredCandidate> candidates, List<ScoredCandidate> eligible)
    {
        var corrupt = Draw(eligible);
        // Reverse UTF-16 code units, as content.split('').reverse() does: the consumer must cope with a garbled value.
        var output = candidates.Select(c => corrupt.Contains(c.Id) ? c with { Content = new string(c.Content.Reverse().ToArray()) } : c).ToList();
        return (output, new FaultReport(FaultKind.ValueCorruption, config.Seed, corrupt.Count, eligible.Count, $"corrupted {corrupt.Count}/{eligible.Count} payloads"));
    }

    private (IReadOnlyList<ScoredCandidate>, FaultReport) Latency(IReadOnlyList<ScoredCandidate> candidates, int total)
    {
        // Modelled latency in [0, max): a delivery property, so the candidates are not changed and nothing sleeps.
        var latencyMs = Math.Floor(Interventions.Rng(config.Seed)() * config.MaxLatencyMs);
        return (candidates, new FaultReport(FaultKind.LatencyInjection, config.Seed, total, total,
            $"modelled {JsFormat.Number(latencyMs)}ms delivery latency (not a real sleep)", LatencyMs: latencyMs));
    }

    private (IReadOnlyList<ScoredCandidate>, FaultReport) Crash(IReadOnlyList<ScoredCandidate> candidates)
    {
        var component = FaultInjection.ParseKind(config.Target)
            ?? Enum.GetValues<CandidateKind>().Cast<CandidateKind?>().FirstOrDefault(k => candidates.Any(c => c.Kind == k))
            ?? throw new InvalidOperationException("component_crash: no candidates to crash");
        var report = new FaultReport(FaultKind.ComponentCrash, config.Seed, candidates.Count(c => c.Kind == component), candidates.Count,
            $"component \"{FaultInjection.KindName(component)}\" crashed; store must serve remaining stores", CrashedComponent: component);
        throw new FaultInjectedException(component, report);
    }
}
