using System.Text.Json;

using Aijade.Core.Random;
using Aijade.Research.Statistics;

namespace Aijade.Tests;

/// <summary>
/// The statistics must reproduce the recorded golden values on fixed inputs, which pin the published RQ-C numbers.
/// The PRNG is compared exactly; everything else within 1e-12 relative (last-ulp differences in exp/log
/// between the JavaScript engine and .NET are allowed, nothing more).
/// </summary>
public class StatsGoldenTests
{
    private static readonly JsonElement Golden = JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "stats-golden.json"))).RootElement;

    private static double Num(JsonElement e) => e.ValueKind == JsonValueKind.String
        ? e.GetString() switch { "NaN" => double.NaN, "Infinity" => double.PositiveInfinity, "-Infinity" => double.NegativeInfinity, var s => throw new FormatException(s) }
        : e.GetDouble();

    private static void Close(double expected, double actual, string what)
    {
        if (double.IsNaN(expected))
        {
            Assert.True(double.IsNaN(actual), $"{what}: expected NaN, got {actual}");
            return;
        }
        if (double.IsInfinity(expected))
        {
            Assert.Equal(expected, actual);
            return;
        }
        var tolerance = 1e-12 * Math.Max(1e-300, Math.Abs(expected)) + 1e-300;
        Assert.True(Math.Abs(expected - actual) <= tolerance, $"{what}: expected {expected:R}, got {actual:R}");
    }

    private static double[] Values => Golden.GetProperty("values").EnumerateArray().Select(Num).ToArray();

    private static SkillCount[] Skills => Enumerable.Range(0, 50).Select(i => new SkillCount(i * 7 % 5, 1 + (i * 3 % 5))).ToArray();

    [Fact]
    public void Mulberry32_reproduces_the_javascript_sequence_exactly()
    {
        var g = new Mulberry32(42);
        foreach (var expected in Golden.GetProperty("mulberry32_42_first5").EnumerateArray())
            Assert.Equal(expected.GetDouble(), g.Next());
        var h = new Mulberry32(0xFFFFFFFF);
        foreach (var expected in Golden.GetProperty("mulberry32_seedmax_first3").EnumerateArray())
            Assert.Equal(expected.GetDouble(), h.Next());
        Assert.Equal(Golden.GetProperty("r2").GetDouble(), new Mulberry32(Stats.DefaultBootstrapSeed).Next());
    }

    [Fact]
    public void Normal_distribution_functions_match()
    {
        foreach (var pair in Golden.GetProperty("normalSf").EnumerateArray())
            Close(Num(pair[1]), Stats.NormalSf(Num(pair[0])), $"normalSf({pair[0]})");
        foreach (var pair in Golden.GetProperty("normalCdf").EnumerateArray())
            Close(Num(pair[1]), Stats.NormalCdf(Num(pair[0])), $"normalCdf({pair[0]})");
        foreach (var pair in Golden.GetProperty("normalQuantile").EnumerateArray())
            Close(Num(pair[1]), Stats.NormalQuantile(Num(pair[0])), $"normalQuantile({pair[0]})");
    }

    [Fact]
    public void Contingency_tests_match()
    {
        foreach (var c in Golden.GetProperty("chiSquare").EnumerateArray())
        {
            var t = c.GetProperty("t").EnumerateArray().Select(x => x.GetInt32()).ToArray();
            foreach (var (key, yates) in new[] { ("yates", true), ("plain", false) })
            {
                var r = Stats.ChiSquare2x2(t[0], t[1], t[2], t[3], yates);
                Close(Num(c.GetProperty(key).GetProperty("statistic")), r.Statistic, $"chi2 {key} stat {string.Join(',', t)}");
                Close(Num(c.GetProperty(key).GetProperty("p")), r.P, $"chi2 {key} p {string.Join(',', t)}");
            }
        }
        foreach (var c in Golden.GetProperty("logOdds").EnumerateArray())
        {
            var t = c.GetProperty("t").EnumerateArray().Select(x => x.GetDouble()).ToArray();
            var r = Stats.LogOddsInteraction(t[0], t[1], t[2], t[3]);
            var e = c.GetProperty("r");
            Close(Num(e.GetProperty("estimate")), r.Estimate, "logOdds estimate");
            Close(Num(e.GetProperty("se")), r.Se, "logOdds se");
            Close(Num(e.GetProperty("z")), r.Z, "logOdds z");
            Close(Num(e.GetProperty("p")), r.P, "logOdds p");
        }
        foreach (var c in Golden.GetProperty("mcnemar").EnumerateArray())
        {
            var t = c.GetProperty("t").EnumerateArray().Select(x => x.GetInt32()).ToArray();
            var r = Stats.McNemarExactOrChi(t[0], t[1], t[2], t[3]);
            var e = c.GetProperty("r");
            Close(Num(e.GetProperty("chiSquare")), r.ChiSquare, "mcnemar chi2");
            Close(Num(e.GetProperty("p")), r.P, $"mcnemar p {string.Join(',', t)}");
            Assert.Equal(e.GetProperty("usedExact").GetBoolean(), r.UsedExact);
        }
    }

    [Fact]
    public void Effect_sizes_and_risk_difference_intervals_match()
    {
        var e = Golden.GetProperty("effect");
        Close(Num(e.GetProperty("or")), Stats.OddsRatio(12, 5, 3, 9), "or");
        Close(Num(e.GetProperty("or0")), Stats.OddsRatio(0, 5, 3, 9), "or0");
        Close(Num(e.GetProperty("rd")), Stats.RiskDifference(12, 5, 3, 9), "rd");
        Close(Num(e.GetProperty("v")), Stats.CramersV(6.5, 120), "v");
        Close(Num(e.GetProperty("h")), Stats.CohensH(0.83, 0.79), "h");
        foreach (var c in Golden.GetProperty("rdci").EnumerateArray())
        {
            var t = c.GetProperty("t").EnumerateArray().Select(x => x.GetDouble()).ToArray();
            var r = Stats.RiskDifferenceInterval(t[0], t[1], t[2], t[3]);
            Close(Num(c.GetProperty("r").GetProperty("estimate")), r.Estimate, "rdci est");
            Close(Num(c.GetProperty("r").GetProperty("lo")), r.Lo, "rdci lo");
            Close(Num(c.GetProperty("r").GetProperty("hi")), r.Hi, "rdci hi");
        }
    }

    [Fact]
    public void Holm_step_down_matches_including_untestable_entries()
    {
        double[] ps = [0.9704, 0.0137, 0.7505, 2.383057066402795e-7, 0.0263, double.NaN, 0.0056];
        var r = Stats.HolmBonferroni(ps, 0.05, ["a", "b", "c", "d", "e", "f", "g"]);
        var expected = Golden.GetProperty("holm").EnumerateArray().ToArray();
        for (var i = 0; i < ps.Length; i++)
        {
            Assert.Equal(expected[i].GetProperty("label").GetString(), r[i].Label);
            Close(Num(expected[i].GetProperty("adjustedP")), r[i].AdjustedP, $"holm {i}");
            Assert.Equal(expected[i].GetProperty("reject").GetBoolean(), r[i].Reject);
        }
    }

    private static void SameCi(JsonElement e, ConfidenceInterval ci, string what)
    {
        Close(Num(e.GetProperty("mean")), ci.Mean, $"{what} mean");
        Close(Num(e.GetProperty("lo")), ci.Lo, $"{what} lo");
        Close(Num(e.GetProperty("hi")), ci.Hi, $"{what} hi");
    }

    [Fact]
    public void Seeded_bootstraps_match()
    {
        var v = Values;
        SameCi(Golden.GetProperty("bootstrap"), Stats.BootstrapCi(v, 2000), "bootstrap");
        SameCi(Golden.GetProperty("bca"), Stats.BcaBootstrapCi(v, 2000, seed: 7), "bca");
        SameCi(Golden.GetProperty("bcaBinary"), Stats.BcaBootstrapCi(v.Select(x => x > 0.4 ? 1.0 : 0.0).ToArray(), 2000), "bcaBinary");
        SameCi(Golden.GetProperty("pooled"), Stats.BootstrapPooledPrecision(Skills, 3000), "pooled");

        var s = Skills;
        var pd = Stats.PooledDifferenceInDifferences(s[..12], s[12..25], s[25..37], s[37..], 1500);
        var epd = Golden.GetProperty("pooledDid");
        Close(Num(epd.GetProperty("estimate")), pd.Estimate, "pooledDid estimate");
        SameCi(epd.GetProperty("ci"), pd.Ci, "pooledDid");

        var dd = Stats.DifferenceInDifferences(v[..9], v[9..18], v[18..27], v[27..], 1500, 11);
        var edd = Golden.GetProperty("did");
        Close(Num(edd.GetProperty("estimate")), dd.Estimate, "did estimate");
        SameCi(edd.GetProperty("ci"), dd.Ci, "did");
    }

    [Fact]
    public void Power_analysis_matches()
    {
        foreach (var pair in Golden.GetProperty("mde").EnumerateArray())
            Close(Num(pair[1]), Stats.MinDetectableEffectProportion(Num(pair[0])), $"mde({pair[0]})");
        foreach (var t in Golden.GetProperty("power").EnumerateArray())
            Close(Num(t[2]), Stats.PowerForEffectProportion(Num(t[0]), Num(t[1])), $"power({t[0]},{t[1]})");
    }
}
