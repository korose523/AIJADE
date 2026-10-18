using System.Text.Json;

using Aijade.Memory.Locomo;
using Aijade.Research.MemoryEval;

namespace Aijade.Tests;

/// <summary>
/// P4's central numbers must come out of the memory kernel from the raw corpus. LoCoMo is not redistributed: set
/// AIJADE_LOCOMO to a local locomo10.json (SHA-256 checked); the test is skipped when no copy is available.
/// </summary>
public class WeightAblationTests
{
    private static string? LocomoPath()
    {
        var candidates = new[]
        {
            Environment.GetEnvironmentVariable("AIJADE_LOCOMO"),
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), ".local", "share", "aijade-data", "locomo10.json"),
        };
        return candidates.FirstOrDefault(p => !string.IsNullOrEmpty(p) && File.Exists(p));
    }

    [Fact]
    public void Weight_ablation_reproduces_the_recorded_artifact()
    {
        var path = LocomoPath();
        if (path is null)
            Assert.Skip("LoCoMo corpus not available (set AIJADE_LOCOMO)");
        Assert.Equal(LocomoCorpus.Sha256, LocomoCorpus.FileSha256(path));

        var result = WeightAblation.Run(LocomoCorpus.Load(path));

        var archived = JsonDocument.Parse(File.ReadAllText(Path.Combine(RqcReanalysisTests.RepoRoot(), "experiments", "memory", "weight-ablation.json"))).RootElement;
        Assert.Equal(1986, result.Questions);
        foreach (var weights in archived.GetProperty("recallByWeights").EnumerateObject())
        {
            foreach (var k in weights.Value.EnumerateObject())
                Assert.Equal(k.Value.GetDouble(), result.RecallByWeights[weights.Name][int.Parse(k.Name, System.Globalization.CultureInfo.InvariantCulture)], 12);
        }
        var bias = archived.GetProperty("recencyBias");
        Assert.Equal(bias.GetProperty("scanned").GetInt32(), result.RecencyBias.Scanned);
        Assert.Equal(bias.GetProperty("evidenceMissing").GetInt32(), result.RecencyBias.EvidenceMissing);
        Assert.Equal(bias.GetProperty("meanNewerInTopK").GetDouble(), result.RecencyBias.MeanNewerInTopK, 12);
        Assert.Equal(bias.GetProperty("baselineIfUnbiased").GetDouble(), result.RecencyBias.BaselineIfUnbiased, 12);
        Assert.Equal(bias.GetProperty("meanSlotAgePercentile").GetDouble(), result.RecencyBias.MeanSlotAgePercentile, 12);
    }

    [Fact]
    public void Pools_of_several_sizes_come_from_one_ranking_and_a_larger_pool_covers_at_least_as_much()
    {
        var path = LocomoPath();
        if (path is null)
            Assert.Skip("LoCoMo corpus not available (set AIJADE_LOCOMO)");
        var two = LocomoCorpus.Load(path).Take(2).ToList();

        var variants = WeightAblation.RunVariants(two, null, [(WeightAblation.RerankPool, true), (1, false), (WeightAblation.RerankPool, false), (int.MaxValue, false)]);
        var direct = WeightAblation.Run(two);

        // the published variant is the plain ablation
        foreach (var (arm, byK) in direct.RecallByWeights)
        {
            foreach (var (k, v) in byK)
                Assert.Equal(v, variants[0].RecallByWeights[arm][k], 12);
        }
        Assert.Equal(direct.RecencyBias.MeanNewerInTopK, variants[0].RecencyBias.MeanNewerInTopK, 12);
        Assert.Equal(direct.PoolCoverage, variants[0].PoolCoverage, 12);
        // a one-candidate pool covers exactly the questions every arm hits at K = 1
        Assert.Equal(variants[1].PoolCoverage, variants[1].RecallByWeights["current"][1], 12);
        Assert.Equal(variants[1].PoolCoverage, variants[1].RecallByWeights["sim-only"][1], 12);
        // coverage grows with the pool and bounds every arm's recall
        Assert.True(variants[1].PoolCoverage <= variants[2].PoolCoverage && variants[2].PoolCoverage <= variants[3].PoolCoverage);
        foreach (var v in variants)
            Assert.All(v.RecallByWeights.Values, byK => Assert.True(byK[8] <= v.PoolCoverage + 1e-12));
    }

    [Fact]
    public void The_delivery_check_at_the_default_penalty_reproduces_the_archived_delivered_recall()
    {
        var path = LocomoPath();
        if (path is null)
            Assert.Skip("LoCoMo corpus not available (set AIJADE_LOCOMO)");
        var rows = RetrievalAblation.DeliveryCheck(LocomoCorpus.Load(path));
        var archived = JsonDocument.Parse(File.ReadAllText(Path.Combine(RqcReanalysisTests.RepoRoot(), "experiments", "memory", "gating-interference.json")))
            .RootElement.GetProperty("byScoreMode");
        foreach (var (mode, name) in new[] { (Aijade.Memory.Model.RetrievalScoreMode.Additive, "additive"), (Aijade.Memory.Model.RetrievalScoreMode.Standardized, "standardized") })
        {
            var atDefault = rows.Single(r => r.Mode == mode && r.ConflictPenalty == Aijade.Memory.Model.MemoryConfig.Default.ConflictPenalty);
            Assert.Equal(archived.GetProperty(name).GetProperty("recall").GetProperty("8").GetProperty("off").GetDouble(), atDefault.MacroRecall8, 12);
            // with the penalty off nothing is demoted, so the penalised items are still flagged in the top 8
            var off = rows.Single(r => r.Mode == mode && r.ConflictPenalty == 1.0);
            Assert.True(off.PenalizedShareOfTop8 >= atDefault.PenalizedShareOfTop8);
        }
    }
}
