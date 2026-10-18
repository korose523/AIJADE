// Inline fixture arrays read better than hoisted fields in these one-shot golden scenarios.
#pragma warning disable CA1861
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Growth;
using Aijade.Growth.Benchmark;
using Aijade.Growth.Metrics;
using Aijade.Growth.Pilot;

namespace Aijade.Tests;

/// <summary>Metrics, the synthetic benchmark and the pilot runner against the recorded golden data.</summary>
public class GrowthPilotTests
{
    private static string GoldenPath(string name) => Path.Combine(AppContext.BaseDirectory, "Golden", "growth", name);

    private static readonly JsonNode Golden = JsonNode.Parse(File.ReadAllText(GoldenPath("metrics.json")))!;

    private static double D(JsonNode? n) => n!.GetValue<double>();

    [Fact]
    public void Benchmark_is_byte_identical_to_the_original()
    {
        var bench = SyntheticLongitudinal.Generate(1);
        Assert.Equal(Golden["benchSha"]!.GetValue<string>(), JsFormat.Sha256Hex(JsFormat.Stringify(bench.ToJson())));
        var bench7 = SyntheticLongitudinal.Generate(7, BenchmarkScale.Default with { Datasets = 2 });
        Assert.Equal(Golden["bench7Sha"]!.GetValue<string>(), JsFormat.Sha256Hex(JsFormat.Stringify(bench7.ToJson())));
        Assert.Equal(Golden["bench7"]!.ToJsonString(), JsFormat.Stringify(bench7.ToJson()));
    }

    [Fact]
    public void Statistics_match_the_original()
    {
        var rng = Stats.Mulberry32(42);
        Assert.Equal(Golden["rng"]!.AsArray().Select(D), Enumerable.Range(0, 8).Select(_ => rng()));
        var ci = Stats.BootstrapCI([0.1, 0.5, 0.9, 0.3, 0.7], 11, 500);
        Assert.Equal((D(Golden["ci"]![0]), D(Golden["ci"]![1])), ci);
        Assert.Equal((0.0, 0.0), Stats.BootstrapCI([], 1));
        Assert.Equal(Golden["d"]!.AsArray().Select(D), [Stats.CohensD([1, 2, 3], [2, 3, 5]), Stats.CohensD([1], [2, 3]), Stats.CohensD([1, 1], [1, 1])]);
        var (alpha, rejected) = Stats.Bonferroni([0.001, 0.02, 0.5], 0.05);
        Assert.Equal(D(Golden["bonf"]!["correctedAlpha"]), alpha);
        Assert.Equal(Golden["bonf"]!["rejected"]!.AsArray().Select(b => b!.GetValue<bool>()), rejected);
    }

    [Fact]
    public void Formulas_match_the_original()
    {
        Assert.Equal(Golden["fub"]!.AsArray().Select(D),
            [Formulas.FutureUtilityAtBudget(10, 3, [new(1, 1), new(3, 0.2)]), Formulas.FutureUtilityAtBudget(0, 3, [])]);
        var ep = Formulas.EffectiveProactivity(5, 2, 1);
        Assert.Equal((D(Golden["ep"]![0]!["net"]), D(Golden["ep"]![0]!["rate"]), D(Golden["ep"]![0]!["activeCount"])), (ep.Net, ep.Rate, ep.ActiveCount));
        Assert.Equal(new ProactivityResult(0, 0, 0), Formulas.EffectiveProactivity(0, 0, 0));
        Assert.Equal(Golden["gc"]!.AsArray().Select(D), [Formulas.GrowthCoherence(0, 0), Formulas.GrowthCoherence(7, 3)]);
        var pr = Formulas.EvidencePrecisionRecall([true, false], 3);
        Assert.Equal((D(Golden["pr"]![0]!["precision"]), D(Golden["pr"]![0]!["recall"])), (pr.Precision, pr.Recall));
        Assert.Equal(new PrecisionRecall(0, 1), Formulas.EvidencePrecisionRecall([], 0));
        Assert.Equal(Golden["cr"]!.AsArray().Select(D), [Formulas.ContradictionRetention(0, 0), Formulas.ContradictionRetention(4, 1)]);
        Assert.Equal(Golden["fcr"]!.AsArray().Select(D), [Formulas.FalseConsolidationRate(0, 0), Formulas.FalseConsolidationRate(3, 2)]);
        var c = new IdentityCounts(10, 2, 3, 1, 4);
        Assert.Equal(Golden["idm"]!.AsArray().Select(D),
            [IdentityMetrics.IdentityDrift(c), IdentityMetrics.CoreStability(c), IdentityMetrics.SkillRetention(c), IdentityMetrics.CoreStability(c with { CorePersona = 1, Destabilizing = 5 })]);
    }

    [Fact]
    public void Locators_encode_and_decode_like_the_original()
    {
        Assert.Equal(Golden["loc"]!.GetValue<string>(),
            MemoryPolicies.EncodeLocator(new MemoryMeta("st_5", 3, false, "poison", false, true, "st_1", "st_1", 0.05, 0.7)));
        var decoded = new[]
        {
            "stmt:st_5|meta:s=3&t=0&r=poison&d=0&c=1&ct=st_1&tp=st_1&fv=0.05&imp=0.7", "stmt:x|meta:s=abc&junk&fv=", "nope", "stmt:|meta:s=1",
        }.Select(MemoryPolicies.DecodeLocator).Select(m => m is null ? null : JsonSerializer.SerializeToNode(m, GrowthJson.Options));
        var diffs = new List<string>();
        JsonEquivalence.Collect(Golden["dec"], new JsonArray([.. decoded]), "$", diffs);
        Assert.True(diffs.Count == 0, string.Join("\n", diffs));
    }

    [Fact]
    public async Task Pilot_reproduces_the_archived_result_files_byte_for_byte()
    {
        var dir = Directory.CreateTempSubdirectory("aijade-pilot-").FullName;
        try
        {
            var run = await PilotRunner.RunAsync(1, dir, TestContext.Current.CancellationToken);
            Assert.Equal(10, run.Results.Count);
            Assert.Equal(await File.ReadAllTextAsync(GoldenPath("pilot-results.json"), TestContext.Current.CancellationToken),
                await File.ReadAllTextAsync(Path.Combine(dir, PilotRunner.JsonFileName), TestContext.Current.CancellationToken));
            Assert.Equal(await File.ReadAllTextAsync(GoldenPath("pilot-results.md"), TestContext.Current.CancellationToken),
                await File.ReadAllTextAsync(Path.Combine(dir, PilotRunner.MarkdownFileName), TestContext.Current.CancellationToken));
        }
        finally
        {
            Directory.Delete(dir, recursive: true);
        }
    }
}
