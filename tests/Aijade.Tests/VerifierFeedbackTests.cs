using System.Text.Json.Nodes;

using Aijade.Research.RqC;

namespace Aijade.Tests;

/// <summary>The P2-C analysis (verifier error rates by feedback and round) against hand counts and the simulated positive control.</summary>
public class VerifierFeedbackTests
{
    [Fact]
    public void Rates_differences_consistency_and_within_task_counts_match_hand_computation()
    {
        static StepRecord Step(string condition, int round, string task, string skill, string verdict, bool ok) =>
            new(condition, 0, round, task, skill, false, 0, false, false, false, verdict, ok);
        // ef0: t0 unusable passed (FP), t1 usable passed (TP), t2 usable failed in round 1 (FN)
        // ef1: t0 unusable failed (TN), t1 usable passed (TP), t2 usable passed in round 0 (TP)
        StepRecord[] steps =
        [
            Step("sv1-ef0", 0, "t0", "a0", "pass", false), Step("sv1-ef0", 0, "t1", "a1", "pass", true), Step("sv1-ef0", 1, "t2", "a2", "fail", true),
            Step("sv1-ef1", 0, "t0", "b0", "fail", false), Step("sv1-ef1", 0, "t1", "b1", "pass", true), Step("sv1-ef1", 0, "t2", "b2", "pass", true),
        ];
        // (t0, x) is judged in both conditions with different verdicts, (t1, y) in both alike, t2 has a different code per condition
        string?[] codes = ["x", "y", "z", "x", "y", "w"];
        var r = VerifierFeedback.Analyze(steps, codes, new RqcConfig(), iterations: 200);
        static int[] Ratio(JsonNode cell, string name) => [cell[name]!["numerator"]!.GetValue<int>(), cell[name]!["denominator"]!.GetValue<int>()];
        var f = r["feedback"]!;
        Assert.Equal([1, 1], Ratio(f["ef0"]!, "hallucinationRate"));
        Assert.Equal([1, 2], Ratio(f["ef0"]!, "missRate"));
        Assert.Equal([0, 1], Ratio(f["ef1"]!, "hallucinationRate"));
        Assert.Equal([0, 2], Ratio(f["ef1"]!, "missRate"));
        Assert.Equal(-1.0, f["difference"]!["hallucinationRate"]!["estimate"]!.GetValue<double>(), 12);
        Assert.Equal(-0.5, f["difference"]!["missRate"]!["estimate"]!.GetValue<double>(), 12);
        Assert.True(f["hallucinationComparisonDescriptiveOnly"]!.GetValue<bool>());
        Assert.Equal(4, f["consistency"]!["candidates"]!.GetValue<int>());
        Assert.Equal(2, f["consistency"]!["judgedInBothConditions"]!.GetValue<int>());
        Assert.Equal(1, f["consistency"]!["differentVerdictsInBoth"]!.GetValue<int>());
        var within = r["rounds"]!["withinTaskExploratory"]!["usable"]!.AsArray();
        Assert.Single(within);
        Assert.Equal("t2", within[0]!["task"]!.GetValue<string>());
        Assert.Equal(0, within[0]!["round0"]!["wrong"]!.GetValue<int>());
        Assert.Equal(1, within[0]!["later"]!["wrong"]!.GetValue<int>());
    }

    [Fact]
    public void The_simulated_positive_control_shows_no_feedback_difference_and_recovers_the_injected_rates()
    {
        // The mock verifier's error rates (0.30 false pass, 0.10 false fail) do not depend on feedback.
        var dir = Path.Combine(RqcReanalysisTests.RunsDirectory(), "rq-c-s42-mock-t30-r5");
        var r = VerifierFeedback.Analyze(StepRecord.ReadJsonl(Path.Combine(dir, "trials.jsonl")), null, new RqcConfig(42), iterations: 1000);
        static double[] Interval(JsonNode node) => [.. node["taskBootstrap95"]!.AsArray().Select(x => x!.GetValue<double>())];
        foreach (var rate in new[] { "hallucinationRate", "missRate" })
        {
            var d = Interval(r["feedback"]!["difference"]![rate]!);
            Assert.True(d[0] <= 0 && 0 <= d[1], $"{rate} difference [{d[0]}, {d[1]}] excludes zero");
        }
        foreach (var ef in new[] { "ef0", "ef1" })
        {
            var h = Interval(r["feedback"]![ef]!["hallucinationRate"]!);
            var m = Interval(r["feedback"]![ef]!["missRate"]!);
            Assert.True(h[0] <= 0.30 && 0.30 <= h[1], $"{ef} hallucinationRate [{h[0]}, {h[1]}] misses 0.30");
            Assert.True(m[0] <= 0.10 && 0.10 <= m[1], $"{ef} missRate [{m[0]}, {m[1]}] misses 0.10");
        }
    }
}
