using System.Globalization;
using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Memory.Contracts;

namespace Aijade.Memory.Identity;

// v7 §11 Constrained Developmental Identity: Constitutional / Character / Expressive layers, updated only through
//   evidence window → candidate → constraint solver → shadow evaluation → drift report → approval → signed version.
// Identity never drives memory durability or salience (the H2c guard applies here as it does to HAC).

public enum IdentityLayer
{
    Constitutional,
    Character,
    Expressive,
}

public enum IdentitySource
{
    User,
    Agent,
    World,
    Observation,
}

/// <summary>How evidence arose — a single user-emotion event may not drive identity.</summary>
public enum EvidenceTrigger
{
    Deliberate,
    Observation,
    Emotion,
}

/// <summary>A point in identity space: each layer is a named numeric vector, kept in insertion order.</summary>
public sealed class IdentityState
{
    public OrderedDictionary<string, double> Constitutional { get; init; } = [];
    public OrderedDictionary<string, double> Character { get; init; } = [];
    public OrderedDictionary<string, double> Expressive { get; init; } = [];

    public OrderedDictionary<string, double> this[IdentityLayer layer] => layer switch
    {
        IdentityLayer.Constitutional => Constitutional,
        IdentityLayer.Character => Character,
        _ => Expressive,
    };

    public IdentityState Clone() => new()
    {
        Constitutional = new(Constitutional),
        Character = new(Character),
        Expressive = new(Expressive),
    };

    public static IdentityState Default => new()
    {
        Constitutional = new() { ["safetyBoundary"] = 0.5, ["userConsent"] = 0.5, ["harmThreshold"] = 0.5 },
        Character = new() { ["verbosity"] = 0.5, ["formality"] = 0.5, ["curiosity"] = 0.5 },
        Expressive = new() { ["warmth"] = 0.5, ["energy"] = 0.5 },
    };

    /// <summary>The JSON object that is signed (camelCase layer names).</summary>
    public JsonObject ToJson()
    {
        static JsonObject Layer(OrderedDictionary<string, double> d)
        {
            var o = new JsonObject();
            foreach (var (k, v) in d)
                o[k] = v;
            return o;
        }
        return new JsonObject { ["constitutional"] = Layer(Constitutional), ["character"] = Layer(Character), ["expressive"] = Layer(Expressive) };
    }
}

public sealed record IdentityEvidence(string EpisodeId, IdentitySource Source, bool Traceable, string Kind, EvidenceTrigger Trigger);

/// <summary>Contract #6 — a proposed identity change and its evidence. Only the named keys change (added to current).</summary>
public sealed record IdentityCandidate(
    string CandidateId, IdentitySource ProposedBy, IReadOnlyList<IdentityEvidence> Evidence,
    IReadOnlyDictionary<IdentityLayer, OrderedDictionary<string, double>> Delta, bool ExplicitUpgrade = false, string? Justification = null)
{
    public const string SchemaId = "aijade.identity_candidate@1";
}

public sealed record CdiConfig(
    double Epsilon, int MinIndependentEpisodes, IReadOnlyDictionary<string, (double Min, double Max)> SafetyBounds, string ConsentParam,
    (double Lo, double Hi) ConsentRange)
{
    /// <summary>
    /// Whether the consent parameter is governed by C_consent alone (the default). When it also sits in the safety bounds
    /// with the same range, the safety check runs first and the consent stage can never fire (P1 Appendix A.7, case ④);
    /// <see cref="ConsentAlsoSafetyBound"/> is that configuration.
    /// </summary>
    public bool ConsentOwnsParameter { get; init; } = true;

    public static CdiConfig Default { get; } = new(0.5, 2,
        new Dictionary<string, (double, double)> { ["safetyBoundary"] = (0, 1), ["userConsent"] = (0, 1), ["harmThreshold"] = (0, 1) },
        "userConsent", (0, 1));

    /// <summary>The consent parameter also carries a safety bound, which makes the consent stage unreachable.</summary>
    public static CdiConfig ConsentAlsoSafetyBound { get; } = Default with { ConsentOwnsParameter = false };
}

public sealed record DriftReport(IReadOnlyDictionary<IdentityLayer, double> PerLayer, double Total, IReadOnlyList<IdentityLayer> TouchedLayers)
{
    public bool TouchesConstitutional => TouchedLayers.Contains(IdentityLayer.Constitutional);
}

public enum SolveStage
{
    Validation,
    Constraint,
    Safety,
    Consent,
}

public sealed record SolveResult(bool Ok, IdentityState? Next = null, DriftReport? Drift = null, SolveStage? Stage = null, string? Reason = null);

public sealed record IdentityVersion(int Version, string Signature, IReadOnlyList<string> Parents, IdentityState Params, IdentitySource ApprovedBy, double CreatedAt, bool RolledBack);

public static class Cdi
{
    private static readonly IdentityLayer[] Layers = [IdentityLayer.Constitutional, IdentityLayer.Character, IdentityLayer.Expressive];

    /// <summary>Deterministic 32-bit checksum (FNV-1a computed in double precision) of the canonical state.</summary>
    public static string Hash(IdentityState s) => JsFormat.Fnv1aJsDouble(JsFormat.CanonicalJson(s.ToJson()));

    public static double L2(IReadOnlyDictionary<IdentityLayer, OrderedDictionary<string, double>> delta)
    {
        var acc = 0.0;
        foreach (var layer in Layers)
        {
            if (!delta.TryGetValue(layer, out var d))
                continue;
            foreach (var (_, v) in d)
                acc += v * v;
        }
        return Math.Sqrt(acc);
    }

    public static IdentityState Apply(IdentityState current, IReadOnlyDictionary<IdentityLayer, OrderedDictionary<string, double>> delta)
    {
        var next = current.Clone();
        foreach (var layer in Layers)
        {
            if (!delta.TryGetValue(layer, out var d))
                continue;
            foreach (var (k, v) in d)
                next[layer][k] = next[layer].GetValueOrDefault(k) + v;
        }
        return next;
    }

    public static DriftReport Drift(IdentityCandidate candidate)
    {
        var perLayer = new Dictionary<IdentityLayer, double>();
        var touched = new List<IdentityLayer>();
        foreach (var layer in Layers)
        {
            if (!candidate.Delta.TryGetValue(layer, out var d))
                continue;
            var sum = 0.0;
            foreach (var (_, v) in d)
                sum += v * v;
            perLayer[layer] = Math.Sqrt(sum);
            touched.Add(layer);
        }
        var total = 0.0;
        foreach (var layer in touched)
            total += perLayer[layer] * perLayer[layer];
        return new DriftReport(perLayer, Math.Sqrt(total), touched);
    }

    public static IdentityEvidence EvidenceFromFeedback(FeedbackEvent feedback, string episodeId, bool traceable = true)
    {
        var explicitFeedback = feedback.Type == "explicit";
        return new IdentityEvidence(episodeId, explicitFeedback ? IdentitySource.User : IdentitySource.Observation, traceable,
            explicitFeedback ? "feedback" : "observation", explicitFeedback ? EvidenceTrigger.Deliberate : EvidenceTrigger.Observation);
    }

    /// <summary>A single-layer, small-step candidate from one feedback event.</summary>
    public static IdentityCandidate CandidateFromFeedback(
        FeedbackEvent feedback, string episodeId, IdentityLayer layer, string paramKey, double deltaValue,
        IdentitySource proposedBy = IdentitySource.World, bool explicitUpgrade = false, string? justification = null, bool traceable = true) =>
        new($"fb_{feedback.Id}", proposedBy, [EvidenceFromFeedback(feedback, episodeId, traceable)],
            new Dictionary<IdentityLayer, OrderedDictionary<string, double>> { [layer] = new() { [paramKey] = deltaValue } }, explicitUpgrade, justification);

    /// <summary>HAC → CDI bridge: a frozen state snapshot becomes world observation evidence (never a write).</summary>
    public static IdentityEvidence EvidenceFromSnapshot(StateSnapshot snapshot, string episodeId, bool traceable = true) =>
        new(episodeId, IdentitySource.World, traceable, "observation", EvidenceTrigger.Observation);

    /// <summary>§6 / §11.2 admissibility gate.</summary>
    public static Validation Validate(IdentityCandidate c, CdiConfig cfg)
    {
        if (c.Evidence.Count == 0)
            return Validation.Fail("IdentityCandidate must carry evidence (v7 §6)");
        if (c.Evidence.Any(e => !e.Traceable))
            return Validation.Fail("untraceable evidence forbidden (v7 §6)");
        if (c.Evidence.Select(e => e.EpisodeId).Distinct().Count() < cfg.MinIndependentEpisodes)
            return Validation.Fail($"evidence must span ≥{cfg.MinIndependentEpisodes} independent episodes");
        if (c.Evidence.All(e => e.Trigger == EvidenceTrigger.Emotion))
            return Validation.Fail("a single user-emotion event cannot drive identity change (§11.2)");
        if (c.Delta.TryGetValue(IdentityLayer.Constitutional, out var constitutional) && constitutional.Count > 0)
        {
            if (c.ProposedBy == IdentitySource.Agent)
                return Validation.Fail("constitutional layer is not model-writable (§11.1)");
            if (!c.ExplicitUpgrade)
                return Validation.Fail("constitutional change requires explicitUpgrade (§11.1)");
        }
        return Validation.Pass;
    }

    /// <summary>Pure constraint solver: validation, ‖Δp‖₂ ≤ ε, safety bounds, consent range.</summary>
    public static SolveResult Solve(IdentityState current, IdentityCandidate candidate, CdiConfig cfg)
    {
        var v = Validate(candidate, cfg);
        if (!v.Ok)
            return new SolveResult(false, Stage: SolveStage.Validation, Reason: v.Reason);
        var drift = Drift(candidate);
        if (drift.Total > cfg.Epsilon)
        {
            return new SolveResult(false, Drift: drift, Stage: SolveStage.Constraint,
                Reason: $"drift bound violated (‖Δp‖={drift.Total.ToString("F3", CultureInfo.InvariantCulture)} > ε={JsFormat.Number(cfg.Epsilon)})");
        }
        var next = Apply(current, candidate.Delta);
        foreach (var (key, (min, max)) in cfg.SafetyBounds)
        {
            if (cfg.ConsentOwnsParameter && key == cfg.ConsentParam)
                continue; // checked by C_consent below
            if (next.Constitutional.TryGetValue(key, out var val) && (val < min || val > max))
                return new SolveResult(false, Stage: SolveStage.Safety, Reason: $"safety bound violated on \"{key}\" (C_safety)");
        }
        if (next.Constitutional.TryGetValue(cfg.ConsentParam, out var consent) && (consent < cfg.ConsentRange.Lo || consent > cfg.ConsentRange.Hi))
            return new SolveResult(false, Stage: SolveStage.Consent, Reason: "consent out of range (C_consent)");
        return new SolveResult(true, next, drift);
    }

    /// <summary>Core Stability: 1 while the constitutional layer is untouched, falling with its drift.</summary>
    public static double CoreStability(IdentityState current, IdentityState baseline)
    {
        var d = 0.0;
        foreach (var (k, a) in baseline.Constitutional)
        {
            var b = current.Constitutional.GetValueOrDefault(k);
            d += (a - b) * (a - b);
        }
        return Math.Max(0, 1 - Math.Sqrt(d));
    }

    public static int CountDriftViolations(IEnumerable<SolveResult> results) => results.Count(r => !r.Ok && r.Stage == SolveStage.Constraint);

    public static double RollbackRecoveryRate(IdentityState current, IdentityState target)
    {
        var d = 0.0;
        foreach (var layer in Layers)
        {
            foreach (var (k, a) in target[layer])
            {
                var b = current[layer].GetValueOrDefault(k);
                d += (a - b) * (a - b);
            }
        }
        return Math.Max(0, 1 - Math.Sqrt(d));
    }
}

/// <summary>Holds the current identity and the append-only signed version history.</summary>
public sealed class IdentityController(CdiConfig config, IdentityState? initial = null, Func<double>? clock = null, IEnumerable<IdentityVersion>? history = null)
{
    private readonly Func<double> _clock = clock ?? (() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
    private readonly List<IdentityVersion> _versions = history?.Select(v => v with { Params = v.Params.Clone() }).ToList() ?? [];
    private IdentityState _current = (initial ?? IdentityState.Default).Clone();

    public IdentityState State => _current.Clone();

    public IReadOnlyList<IdentityVersion> History => _versions.Select(v => v with { Params = v.Params.Clone() }).ToList();

    /// <summary>Evaluate without committing (the shadow path).</summary>
    public SolveResult Shadow(IdentityCandidate candidate) => Cdi.Solve(_current, candidate, config);

    /// <summary>Commit an admissible candidate as a new signed version.</summary>
    public (IdentityVersion? Version, SolveResult Result) Apply(IdentityCandidate candidate, IdentitySource? approvedBy = null)
    {
        var r = Cdi.Solve(_current, candidate, config);
        if (!r.Ok)
            return (null, r);
        var version = new IdentityVersion(_versions.Count + 1, Cdi.Hash(r.Next!), _versions.Count > 0 ? [_versions[^1].Signature] : [],
            r.Next!, approvedBy ?? candidate.ProposedBy, _clock(), false);
        _versions.Add(version);
        _current = r.Next!;
        return (version, r);
    }

    /// <summary>Restore a prior signed version and record the rollback as a new version.</summary>
    public IdentityVersion RollbackTo(string signature, IdentitySource approvedBy = IdentitySource.User)
    {
        var target = _versions.Find(v => v.Signature == signature) ?? throw new InvalidOperationException("unknown version signature");
        var version = new IdentityVersion(_versions.Count + 1, Cdi.Hash(target.Params), [target.Signature], target.Params.Clone(), approvedBy, _clock(), true);
        _versions.Add(version);
        _current = target.Params.Clone();
        return version;
    }
}
