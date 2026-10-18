using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Research.RqC;

namespace Aijade.Tests;

/// <summary>
/// The RQ-C summaries must be recomputable from the persisted per-execution logs alone. Every analysis field of each
/// recorded summary.json is compared.
/// </summary>
public class RqcReanalysisTests
{
    private static readonly string[] AnalysisFields =
    [
        "analysisUnit", "nSkills", "nExecutions", "conditions", "table", "perCellCI", "diagnostics", "diffInDiff",
        "effectSizes", "multiplicity", "factorialInteraction", "chiSquare", "chiSquareSelfVerification",
        "chiSquareExecutionLevel", "mcnemarEnvFeedback", "power", "powerReference", "degeneracy", "loopDiagnostics",
    ];

    internal static string RepoRoot()
    {
        var dir = new DirectoryInfo(AppContext.BaseDirectory);
        while (dir is not null && !File.Exists(Path.Combine(dir.FullName, "Aijade.slnx")))
            dir = dir.Parent;
        // Build output may live outside the checkout (AIJADE_ARTIFACTS); fall back to the source location.
        return dir?.FullName ?? Path.GetFullPath(Path.Combine(CallerDirectory(), "..", ".."));
    }

    private static string CallerDirectory([System.Runtime.CompilerServices.CallerFilePath] string path = "") => Path.GetDirectoryName(path)!;

    /// <summary>The directory of the recorded RQ-C runs.</summary>
    internal static string RunsDirectory() => Path.Combine(RepoRoot(), "experiments", "rq-c");

    /// <summary>Recorded runs: every analysis field must match.</summary>
    public static TheoryData<string> Runs =>
    [
        "rq-c-s42-mock-t30-r5",
        "rq-c-s42-ollama-t30-r5",
        "redo/rq-c-s42-ollama-t30-r5",
    ];

    [Theory]
    [MemberData(nameof(Runs))]
    public void Recorded_summary_is_recomputed_from_the_step_log(string run) => AssertRecomputed(run, AnalysisFields, pValueTolerance: 0);

    private static void AssertRecomputed(string run, string[] fields, double pValueTolerance)
    {
        var dir = Path.Combine(RunsDirectory(), run);
        var archived = JsonNode.Parse(File.ReadAllText(Path.Combine(dir, "summary.json")))!.AsObject();
        var seed = (uint)archived["config"]!["seed"]!.GetValue<int>();
        var recomputed = RqcAnalysis.Analyze(StepRecord.ReadJsonl(Path.Combine(dir, "trials.jsonl")), new RqcConfig(seed));
        // Summaries written before 2026-10-15 hold the predictive values (conditioned on the self-verdict) under the estimand
        // names; compare them with the predictive values the analysis now reports under their own names.
        if (archived["diagnostics"] is JsonObject old && old["falseDiscoveryRate"] is null)
        {
            archived["diagnostics"] = new JsonObject
            {
                ["n"] = old["n"]?.DeepClone(),
                ["agreement"] = old["agreement"]?.DeepClone(),
                ["falseDiscoveryRate"] = old["hallucinationRate"]?.DeepClone(),
                ["falseOmissionRate"] = old["missRate"]?.DeepClone(),
            };
        }

        var differences = new List<string>();
        foreach (var field in fields)
            Compare(archived[field], recomputed[field], field, differences, pValueTolerance);
        Assert.True(differences.Count == 0, $"{run}: {differences.Count} differences\n" + string.Join('\n', differences.Take(25)));
    }

    private static void Compare(JsonNode? expected, JsonNode? actual, string path, List<string> diffs, double pTol)
    {
        switch (expected)
        {
            case null:
                if (actual is not null)
                    diffs.Add($"{path}: expected null, got {actual.ToJsonString()}");
                return;
            case JsonObject eo:
                if (actual is not JsonObject ao)
                {
                    diffs.Add($"{path}: expected object, got {actual?.ToJsonString() ?? "null"}");
                    return;
                }
                foreach (var (key, value) in eo)
                    Compare(value, ao[key], $"{path}.{key}", diffs, pTol);
                return;
            case JsonArray ea:
                if (actual is not JsonArray aa || aa.Count != ea.Count)
                {
                    diffs.Add($"{path}: array shape differs");
                    return;
                }
                for (var i = 0; i < ea.Count; i++)
                    Compare(ea[i], aa[i], $"{path}[{i}]", diffs, pTol);
                return;
            case JsonValue ev when ev.GetValueKind() == JsonValueKind.Number:
                if (actual is not JsonValue av || av.GetValueKind() != JsonValueKind.Number)
                {
                    diffs.Add($"{path}: expected {ev}, got {actual?.ToJsonString() ?? "null"}");
                    return;
                }
                double e = double.Parse(ev.ToJsonString(), System.Globalization.CultureInfo.InvariantCulture);
                double a = double.Parse(av.ToJsonString(), System.Globalization.CultureInfo.InvariantCulture);
                var tolerance = path.EndsWith(".p", StringComparison.Ordinal) ? Math.Max(pTol, 1e-9) : 1e-9 * Math.Max(1, Math.Abs(e));
                if (Math.Abs(e - a) > tolerance)
                    diffs.Add($"{path}: expected {e:R}, got {a:R}");
                return;
            default:
                if (expected.ToJsonString() != actual?.ToJsonString())
                    diffs.Add($"{path}: expected {expected.ToJsonString()}, got {actual?.ToJsonString() ?? "null"}");
                return;
        }
    }
}
