using System.Text.Json.Nodes;

using Aijade.Core.Js;

namespace Aijade.Providers.Substrate;


public enum SeedStrategy
{
    Fixed,
    Varied,
}

public sealed record DeterminismRun(int Index, double Seed, string Hash, int Chars, string Text);

public sealed record DeterminismReport(bool Identical, int Runs, SeedStrategy SeedStrategy, int UniqueOutputs, IReadOnlyList<DeterminismRun> PerRun, string Fingerprint);

public enum SamplingControlVerdict
{
    Divergent,
    Identical,
    Indeterminate,
}

public sealed record SamplingControlReport(
    SamplingControlVerdict Verdict, string Reason, int Runs, int UniqueOutputs, IReadOnlyList<DeterminismRun> PerRun, SamplingConfig Sampling, string SamplingHash, string? Error = null);

public enum DeterminismAuditVerdict
{
    Pass,
    NonDeterministic,
    FalsePositiveRisk,
    InconclusiveControl,
}

public sealed record DeterminismAudit(DeterminismAuditVerdict Verdict, bool Discriminative, bool FalsePositiveRisk, string Reason, DeterminismReport Check, SamplingControlReport Control);

public sealed class NonDeterministicSubstrateException(string message) : Exception(message);

/// <summary>Repeat the same request and compare output hashes; a positive control with the sampler wide open must diverge.</summary>
public static class Determinism
{
    /// <summary>What the control widens: temperature, top_k, top_p (everything else is kept).</summary>
    public static JsonObject ControlOverrides => new() { ["temperature"] = 1, ["top_k"] = 40, ["top_p"] = 0.95 };

    public static string HashText(string text) => JsFormat.Fnv1a(text);

    public static async Task<DeterminismReport> MeasureAsync(ISubstrate substrate, IReadOnlyList<ChatMessage> messages, int runs = 5, SeedStrategy strategy = SeedStrategy.Fixed, CancellationToken ct = default)
    {
        ArgumentNullException.ThrowIfNull(substrate);
        runs = Math.Max(2, runs);
        var baseFp = await substrate.FingerprintAsync(null, ct).ConfigureAwait(false);
        var perRun = new List<DeterminismRun>();
        var last = baseFp.Fingerprint;
        for (var i = 0; i < runs; i++)
        {
            var seed = strategy == SeedStrategy.Varied ? baseFp.Sampling.Seed + (i * 7919) : baseFp.Sampling.Seed;
            var result = await substrate.GenerateAsync(new GenerateOptions(messages, baseFp.Sampling with { Seed = seed }), ct).ConfigureAwait(false);
            last = result.Fingerprint.Fingerprint;
            perRun.Add(new DeterminismRun(i, seed, HashText(result.Text), result.Text.Length, result.Text));
        }
        var unique = perRun.Select(r => r.Hash).Distinct(StringComparer.Ordinal).Count();
        return new DeterminismReport(unique == 1, runs, strategy, unique, perRun, last);
    }

    public static async Task<DeterminismReport> AssertAsync(ISubstrate substrate, IReadOnlyList<ChatMessage> messages, int runs = 5, SeedStrategy strategy = SeedStrategy.Fixed, CancellationToken ct = default)
    {
        var report = await MeasureAsync(substrate, messages, runs, strategy, ct).ConfigureAwait(false);
        if (!report.Identical)
        {
            var summary = string.Join("\n  ", report.PerRun.Select(r => $"run {r.Index} seed={JsFormat.Number(r.Seed)} hash={r.Hash} chars={r.Chars}"));
            throw new NonDeterministicSubstrateException($"Non-deterministic decoding: {report.UniqueOutputs} distinct outputs across {report.Runs} runs.\n  {summary}\n"
                + "Refusing to run an experiment on a substrate that cannot reproduce itself.");
        }
        return report;
    }

    /// <summary>
    /// The positive control: the sampler opened (and a different seed every run). Divergent = sampling is honoured;
    /// identical = sampling is ignored (a matching main check would be a false positive); indeterminate = refused or empty.
    /// </summary>
    public static async Task<SamplingControlReport> RunControlAsync(ISubstrate substrate, IReadOnlyList<ChatMessage> messages, int runs = 5,
        ISubstrate? controlSubstrate = null, JsonObject? samplingOverrides = null, CancellationToken ct = default)
    {
        runs = Math.Max(2, runs);
        var control = controlSubstrate ?? substrate;
        var baseFp = await control.FingerprintAsync(null, ct).ConfigureAwait(false);
        var sampling = baseFp.Sampling.With(ControlOverrides);
        if (samplingOverrides is not null)
            sampling = sampling.With(samplingOverrides);
        var hash = SubstrateFingerprint.HashSampling(sampling);
        var perRun = new List<DeterminismRun>();
        int Unique() => perRun.Select(r => r.Hash).Distinct(StringComparer.Ordinal).Count();
        for (var i = 0; i < runs; i++)
        {
            var seed = sampling.Seed + (i * 7919);
            string text;
            try
            {
                text = (await control.GenerateAsync(new GenerateOptions(messages, sampling with { Seed = seed }), ct).ConfigureAwait(false)).Text;
            }
#pragma warning disable CA1031 // A refused control request is a verdict (indeterminate), not a crash.
            catch (Exception e) when (e is not OperationCanceledException)
#pragma warning restore CA1031
            {
                return new SamplingControlReport(SamplingControlVerdict.Indeterminate,
                    $"Positive control aborted on run {i} of {runs}: the substrate refused the wide-open sampling request. "
                    + "Sampling sensitivity is UNKNOWN — this is not evidence that the main check passed.", runs, Unique(), perRun, sampling, hash, e.Message);
            }
            perRun.Add(new DeterminismRun(i, seed, HashText(text), text.Length, text));
        }
        if (perRun.All(r => r.Chars == 0))
        {
            return new SamplingControlReport(SamplingControlVerdict.Indeterminate,
                "Positive control returned an empty completion on every run (all hashes identical only because \"\" is). "
                + "This is the reasoning-model `think` trap, not a result. Re-run with \"think\": false.", runs, Unique(), perRun, sampling, hash, "all control completions were empty");
        }
        if (Unique() > 1)
        {
            return new SamplingControlReport(SamplingControlVerdict.Divergent,
                $"Positive control produced {Unique()} distinct outputs across {runs} runs with the sampler wide open. "
                + "The substrate demonstrably responds to sampling parameters, so a matching main check reflects real greedy decoding.", runs, Unique(), perRun, sampling, hash);
        }
        return new SamplingControlReport(SamplingControlVerdict.Identical,
            $"FALSE-POSITIVE ALARM: the positive control produced 1 distinct output across {runs} runs even with "
            + $"{JsFormat.Stringify(samplingOverrides ?? ControlOverrides)} and a different seed every run. "
            + "Sampling parameters are being ignored on this substrate, so the main check cannot tell genuine greedy "
            + "decoding from a dropped sampling config. Do NOT report the main check as a determinism pass.", runs, Unique(), perRun, sampling, hash);
    }

    /// <summary>Only a matching main check on a substrate whose control diverged is a pass.</summary>
    public static async Task<DeterminismAudit> AuditAsync(ISubstrate substrate, IReadOnlyList<ChatMessage> messages, int runs = 5, SeedStrategy strategy = SeedStrategy.Fixed,
        ISubstrate? controlSubstrate = null, int? controlRuns = null, JsonObject? controlSampling = null, CancellationToken ct = default)
    {
        var check = await MeasureAsync(substrate, messages, runs, strategy, ct).ConfigureAwait(false);
        var control = await RunControlAsync(substrate, messages, controlRuns ?? runs, controlSubstrate, controlSampling, ct).ConfigureAwait(false);
        if (control.Verdict == SamplingControlVerdict.Indeterminate)
        {
            return new DeterminismAudit(DeterminismAuditVerdict.InconclusiveControl, false, check.Identical,
                $"Determinism is UNDECIDED on this substrate. {control.Reason}", check, control);
        }
        if (control.Verdict == SamplingControlVerdict.Identical)
        {
            return new DeterminismAudit(check.Identical ? DeterminismAuditVerdict.FalsePositiveRisk : DeterminismAuditVerdict.NonDeterministic, false, check.Identical,
                check.Identical ? control.Reason
                    : $"{control.Reason} Note: the main check did diverge ({check.UniqueOutputs} distinct outputs across "
                      + $"{check.Runs} runs), so the substrate is non-reproducible regardless — but the blind control means the "
                      + "underlying cause (sampling config dropped vs. genuine run-to-run nondeterminism) is still unknown.", check, control);
        }
        if (!check.Identical)
        {
            return new DeterminismAudit(DeterminismAuditVerdict.NonDeterministic, true, false,
                $"Genuinely non-deterministic: {check.UniqueOutputs} distinct outputs across {check.Runs} runs, on a substrate "
                + "whose positive control confirms sampling parameters are honoured.", check, control);
        }
        return new DeterminismAudit(DeterminismAuditVerdict.Pass, true, false,
            $"Deterministic and verified: 1 distinct output across {check.Runs} {WireName.Of(check.SeedStrategy)}-seed runs, on a substrate "
            + "whose positive control diverged — so the match reflects real greedy decoding, not ignored sampling parameters.", check, control);
    }

    public static async Task<DeterminismAudit> AssertAuditAsync(ISubstrate substrate, IReadOnlyList<ChatMessage> messages, int runs = 5, SeedStrategy strategy = SeedStrategy.Fixed, CancellationToken ct = default)
    {
        var audit = await AuditAsync(substrate, messages, runs, strategy, ct: ct).ConfigureAwait(false);
        if (audit.Verdict == DeterminismAuditVerdict.Pass)
            return audit;
        var hashes = string.Join(", ", audit.Control.PerRun.Select(r => r.Hash));
        var detail = string.Join("\n  ",
            $"control verdict    {WireName.Of(audit.Control.Verdict)}",
            $"control sampling   {JsFormat.Stringify(audit.Control.Sampling.ToJson())}",
            $"control samplingHash {audit.Control.SamplingHash}",
            $"control hashes     {(hashes.Length > 0 ? hashes : "(none completed)")}");
        throw new NonDeterministicSubstrateException($"Determinism audit did not pass ({Kebab(audit.Verdict)}).\n{audit.Reason}\n  {detail}\n"
            + "Refusing to treat an unverified or contradicted determinism check as a pass.");
    }

    /// <summary>The verdict's wire name: pass, non-deterministic, false-positive-risk, inconclusive-control.</summary>
    public static string Kebab(DeterminismAuditVerdict v) => WireName.Of(v).Replace('_', '-');
}
