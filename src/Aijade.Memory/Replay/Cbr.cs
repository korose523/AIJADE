using System.Text.Json.Nodes;

using Aijade.Memory.Contracts;
using Aijade.Memory.Lexical;

namespace Aijade.Memory.Replay;

// v7 §12 Causal Embodied Replay and the §25 #13 ReplayBundle contract. Correlation across samples cannot support a
// causal claim, so a key interaction is stored whole and the *same* bundle is run under the intervention (gate = 1) and
// the control (gate = 0): ITE = Y(do(gate=1)) − Y(do(gate=0)) is a paired difference on one bundle. The falsification
// point: if the 95% CI of the paired differences spans 0, "gating has a causal effect" is refuted.
// Opt-in, pure; it never touches memory durability / salience (H2c guard).

public sealed record CbrConfig(bool Enabled);

public sealed record SemanticMotion(double T, string Motion, double? Intensity = null);

public sealed record SpeechEvent(double T, string Text);

public sealed record ModelManifest(string Model, JsonObject Sampling, string? Digest = null);

public sealed record UserFeedback(double Valence, string Signal);

/// <summary>
/// The 13-field research replay bundle. <see cref="StateBefore"/> and <see cref="StateAfter"/> are same-named numeric
/// vectors (HAC z_t, CDI identity layers, …) and must share their key set, or the before / after comparison is confounded.
/// </summary>
public sealed record ReplayBundle(
    string BundleId,
    IReadOnlyList<string> EventIds,
    IReadOnlyDictionary<string, double> StateBefore,
    IReadOnlyList<string> MemoryIdsRetrieved,
    string PromptDigest,
    ModelManifest ModelManifest,
    IReadOnlyList<string> ActionPlan,
    IReadOnlyList<JsonObject> ToolResults,
    IReadOnlyList<SpeechEvent> SpeechTimeline,
    IReadOnlyList<SemanticMotion> SemanticMotion,
    UserFeedback UserFeedback,
    IReadOnlyDictionary<string, double> StateAfter,
    string Schema = ReplayBundle.SchemaId)
{
    public const string SchemaId = "aijade.replay_bundle@1";
}

/// <summary>One observed replay outcome Y (higher is better; defined by the caller).</summary>
public sealed record ReplayRun(ReplayBundle Bundle, double Outcome);

/// <summary>§12 interventional replay: replace the state, the retrieved memories and/or the model.</summary>
public sealed record ReplayIntervention(
    IReadOnlyDictionary<string, double>? StateBefore = null, IReadOnlyList<string>? MemoryIdsRetrieved = null, ModelManifest? ModelManifest = null);

public sealed record ReplayConsistency(double Speech, double Motion, double Overall);

public sealed record ItePair(string BundleId, double Treated, double Control);

/// <summary>Paired-difference mean with a normal-approximation 95% CI. Significant iff the CI excludes 0.</summary>
public sealed record IteEstimate(int N, double Mean, double Sd, double Se, double CiLow, double CiHigh, bool Significant, IReadOnlyList<ItePair> PerPair);

/// <summary>Unmatched bundles are reported (the pairing rate is itself a measured signal), never silently dropped.</summary>
public sealed record PairingResult(IReadOnlyList<ItePair> Pairs, IReadOnlyList<string> Unmatched, double PairingRate);

public static class Cbr
{
    private const double Z95 = 1.96;

    private static double Mean(List<double> a)
    {
        if (a.Count == 0)
            return 0;
        var s = 0.0;
        foreach (var x in a)
            s += x;
        return s / a.Count;
    }

    /// <summary>Sample standard deviation (n − 1).</summary>
    private static double SampleSd(List<double> a)
    {
        if (a.Count < 2)
            return 0;
        var m = Mean(a);
        var s = 0.0;
        foreach (var x in a)
            s += (x - m) * (x - m);
        return Math.Sqrt(s / (a.Count - 1));
    }

    private static string KeySet(IReadOnlyDictionary<string, double> o) => string.Join(",", o.Keys.Order(StringComparer.Ordinal));

    /// <summary>The hard replayability invariants. Never throws.</summary>
    public static Validation Validate(ReplayBundle b)
    {
        if (b.Schema != ReplayBundle.SchemaId)
            return Validation.Fail($"ReplayBundle schema must be \"{ReplayBundle.SchemaId}\"");
        if (string.IsNullOrEmpty(b.BundleId))
            return Validation.Fail("ReplayBundle requires a bundleId");
        if (b.EventIds.Count == 0)
            return Validation.Fail("ReplayBundle requires ≥1 event_id (a replay must replay events)");
        if (string.IsNullOrEmpty(b.PromptDigest))
            return Validation.Fail("ReplayBundle requires a prompt_digest (replay must be content-addressed)");
        if (string.IsNullOrEmpty(b.ModelManifest.Model))
            return Validation.Fail("ReplayBundle requires model_manifest.model (replay must name the model)");
        if (KeySet(b.StateBefore) != KeySet(b.StateAfter))
            return Validation.Fail("state_before and state_after must share the same key set (comparability)");
        var v = b.UserFeedback.Valence;
        if (!double.IsFinite(v) || v < -1 || v > 1)
            return Validation.Fail("user_feedback.valence must be a finite number in [-1,1]");
        return Validation.Pass;
    }

    /// <summary>A new bundle with the patch applied. Bundle id and events are kept, so the pair stays matchable; the input is never changed.</summary>
    public static ReplayBundle Intervene(ReplayBundle b, ReplayIntervention patch) => b with
    {
        StateBefore = patch.StateBefore ?? new Dictionary<string, double>(b.StateBefore),
        MemoryIdsRetrieved = patch.MemoryIdsRetrieved ?? [.. b.MemoryIdsRetrieved],
        ModelManifest = patch.ModelManifest ?? b.ModelManifest with { Sampling = (JsonObject)b.ModelManifest.Sampling.DeepClone() },
    };

    /// <summary>§12 embodied-replay agreement: speech by token F1, motion by Jaccard of the motion sets. Symmetric, deterministic.</summary>
    public static ReplayConsistency Consistency(ReplayBundle a, ReplayBundle b)
    {
        var speech = Tokenizer.TokenF1(string.Join(" ", a.SpeechTimeline.Select(s => s.Text)), string.Join(" ", b.SpeechTimeline.Select(s => s.Text)));
        var ma = a.SemanticMotion.Select(m => m.Motion).ToHashSet(StringComparer.Ordinal);
        var mb = b.SemanticMotion.Select(m => m.Motion).ToHashSet(StringComparer.Ordinal);
        var inter = ma.Count(mb.Contains);
        var union = ma.Count + mb.Count - inter;
        var motion = union == 0 ? 1 : (double)inter / union;
        return new ReplayConsistency(speech, motion, (speech + motion) / 2);
    }

    /// <summary>Pair treated and control runs of the same event bundle: same bundle id *and* identical event ids.</summary>
    public static PairingResult Pair(IReadOnlyList<ReplayRun> treated, IReadOnlyList<ReplayRun> control)
    {
        var ctrl = new Dictionary<string, ReplayRun>(StringComparer.Ordinal);
        foreach (var c in control)
            ctrl[c.Bundle.BundleId] = c;
        var pairs = new List<ItePair>();
        var unmatched = new List<string>();
        foreach (var t in treated)
        {
            if (!ctrl.TryGetValue(t.Bundle.BundleId, out var c) || string.Join(" ", c.Bundle.EventIds) != string.Join(" ", t.Bundle.EventIds))
            {
                unmatched.Add(t.Bundle.BundleId);
                continue;
            }
            pairs.Add(new ItePair(t.Bundle.BundleId, t.Outcome, c.Outcome));
        }
        return new PairingResult(pairs, unmatched, treated.Count > 0 ? (double)pairs.Count / treated.Count : 0);
    }

    /// <summary>ITE_i = Y_i(do(gate=1)) − Y_i(do(gate=0)); empty input gives zeros and not significant.</summary>
    public static IteEstimate EstimateIte(IReadOnlyList<ItePair> pairs)
    {
        var diffs = pairs.Select(p => p.Treated - p.Control).ToList();
        var m = Mean(diffs);
        var sd = SampleSd(diffs);
        var se = pairs.Count > 0 ? sd / Math.Sqrt(pairs.Count) : 0;
        var half = Z95 * se;
        var lo = m - half;
        var hi = m + half;
        return new IteEstimate(pairs.Count, m, sd, se, lo, hi, lo > 0 || hi < 0, pairs);
    }
}

/// <summary>Append-only replay log: a bundle is evidence, not cache, so an existing bundle id is never overwritten.</summary>
public sealed class ReplayLog
{
    private readonly OrderedDictionary<string, ReplayBundle> _bundles = new(StringComparer.Ordinal);

    public Validation Add(ReplayBundle b)
    {
        var v = Cbr.Validate(b);
        if (!v.Ok)
            return v;
        if (!_bundles.TryAdd(b.BundleId, b))
            return Validation.Fail($"ReplayBundle \"{b.BundleId}\" already logged (replay log is append-only)");
        return Validation.Pass;
    }

    public ReplayBundle? Get(string bundleId) => _bundles.GetValueOrDefault(bundleId);

    public IReadOnlyList<ReplayBundle> All() => [.. _bundles.Values];

    public int Count => _bundles.Count;
}
