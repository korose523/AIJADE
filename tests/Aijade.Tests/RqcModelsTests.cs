using Aijade.Research.RqC;

namespace Aijade.Tests;

/// <summary>The model-based RQ-C analysis must agree with closed forms where they exist.</summary>
public class RqcModelsTests
{
    private static List<SkillState> Skills(int[,,] counts, int tasks = 6)
    {
        // counts[sv, ef, y]: skills with that outcome; spread round-robin over tasks and trials.
        var list = new List<SkillState>();
        var id = 0;
        for (var sv = 0; sv < 2; sv++)
        {
            for (var ef = 0; ef < 2; ef++)
            {
                for (var y = 0; y < 2; y++)
                {
                    for (var i = 0; i < counts[sv, ef, y]; i++)
                    {
                        var s = new SkillState($"s{id}", sv == 1, ef == 1, id % 5, $"task{id % tasks}") { CallCount = 2, SuccessCount = y == 1 ? 2 : 0 };
                        list.Add(s);
                        id++;
                    }
                }
            }
        }
        return list;
    }

    [Fact]
    public void A_saturated_logistic_regression_reproduces_the_closed_form_log_odds_interaction()
    {
        int[,,] n = { { { 20, 40 }, { 15, 45 } }, { { 25, 35 }, { 18, 42 } } };
        var r = RqcModels.Analyze(Skills(n));
        var wald = r["skillLevelInteraction"]!;
        double Lg(int sv, int ef) => Math.Log((double)n[sv, ef, 1] / n[sv, ef, 0]);
        var expected = Lg(1, 1) - Lg(1, 0) - Lg(0, 1) + Lg(0, 0);
        var expectedSe = Math.Sqrt(Enumerable.Range(0, 8).Sum(i => 1.0 / n[i / 4, (i / 2) % 2, i % 2]));
        Assert.Equal(expected, wald["estimate"]!.GetValue<double>(), 10);
        Assert.Equal(expectedSe, wald["se"]!.GetValue<double>(), 10);
        var glm = r["logisticRegression"]!["modelBased"]!["interaction"]!;
        Assert.Equal(expected, glm["estimate"]!.GetValue<double>(), 6);
        Assert.Equal(expectedSe, glm["se"]!.GetValue<double>(), 6);
        Assert.Equal(240, r["nSkills"]!.GetValue<int>());
    }

    [Fact]
    public void Gauss_Hermite_nodes_integrate_low_moments_exactly()
    {
        var (x, w) = RqcModels.Hermite(40);
        Assert.Equal(Math.Sqrt(Math.PI), w.Sum(), 10);
        Assert.Equal(Math.Sqrt(Math.PI) / 2, x.Zip(w).Sum(p => p.First * p.First * p.Second), 10);
        Assert.Equal(3 * Math.Sqrt(Math.PI) / 4, x.Zip(w).Sum(p => Math.Pow(p.First, 4) * p.Second), 9);
    }

    [Fact]
    public void Without_task_heterogeneity_the_mixed_model_collapses_to_the_logistic_regression()
    {
        // Every task has the same composition, so the task variance estimate is (near) zero.
        int[,,] n = { { { 12, 24 }, { 6, 30 } }, { { 18, 18 }, { 12, 24 } } };
        var r = RqcModels.Analyze(Skills(n, tasks: 6));
        var mixed = r["mixedLogistic"]!;
        Assert.True(mixed["sigmaTask"]!.GetValue<double>() < 0.05, $"sigma {mixed["sigmaTask"]}");
        Assert.Equal(r["logisticRegression"]!["modelBased"]!["interaction"]!["estimate"]!.GetValue<double>(),
            mixed["fixedEffects"]!["interaction"]!["estimate"]!.GetValue<double>(), 2);
    }

    [Fact]
    public void Without_task_heterogeneity_conditional_logit_agrees_with_the_logistic_regression()
    {
        int[,,] n = { { { 12, 24 }, { 6, 30 } }, { { 18, 18 }, { 12, 24 } } };
        var r = RqcModels.Analyze(Skills(n, tasks: 6));
        Assert.Equal(r["logisticRegression"]!["modelBased"]!["interaction"]!["estimate"]!.GetValue<double>(),
            r["conditionalLogistic"]!["effects"]!["interaction"]!["estimate"]!.GetValue<double>(), 1);
    }

    [Fact]
    public void Task_composition_alone_makes_a_marginal_interaction_that_task_adjusted_models_remove()
    {
        // Outcome depends only on the task (easy tasks mostly succeed, hard ones mostly fail), but the cell sv1-ef1 holds
        // many extra skills on hard tasks — as regenerations after failures do. No condition has any effect within a task.
        var skills = new List<SkillState>();
        var id = 0;
        var rng = new Random(7);
        void Add(bool sv, bool ef, string task, double pSuccess, int count)
        {
            for (var i = 0; i < count; i++, id++)
            {
                var ok = rng.NextDouble() < pSuccess;
                skills.Add(new SkillState($"s{id}", sv, ef, id % 30, task) { CallCount = 1, SuccessCount = ok ? 1 : 0 });
            }
        }
        foreach (var (sv, ef) in new[] { (false, false), (false, true), (true, false), (true, true) })
        {
            for (var t = 0; t < 10; t++)
                Add(sv, ef, $"easy{t}", 0.9, 30);
            for (var t = 0; t < 10; t++)
                Add(sv, ef, $"hard{t}", 0.3, sv && ef ? 120 : 30);
        }
        var r = RqcModels.Analyze(skills);
        Assert.True(r["skillLevelInteraction"]!["p"]!.GetValue<double>() < 0.001, "the marginal interaction should be spuriously significant");
        Assert.True(r["conditionalLogistic"]!["effects"]!["interaction"]!["p"]!.GetValue<double>() > 0.05);
        Assert.True(r["mixedLogistic"]!["fixedEffects"]!["interaction"]!["p"]!.GetValue<double>() > 0.05);
    }
    [Fact]
    public void The_slot_level_analysis_keeps_only_the_last_skill_of_each_slot()
    {
        // Two trials × three tasks × four conditions; in the sv1-ef1 cell every slot first holds a failed skill that is then
        // regenerated into a usable one. Per slot the outcome is the regenerated skill, so every cell has six observations.
        var list = new List<SkillState>();
        var id = 0;
        var rng = new Random(7);
        foreach (var sv in new[] { false, true })
        {
            foreach (var ef in new[] { false, true })
            {
                for (var trial = 0; trial < 2; trial++)
                {
                    for (var task = 0; task < 3; task++)
                    {
                        if (sv && ef)
                            list.Add(new SkillState($"s{id++}", sv, ef, trial, $"t{task}") { CallCount = 1, SuccessCount = 0 });
                        var ok = sv && ef || rng.NextDouble() < 0.5;
                        list.Add(new SkillState($"s{id++}", sv, ef, trial, $"t{task}") { CallCount = 1, SuccessCount = ok ? 1 : 0 });
                    }
                }
            }
        }
        var slots = RqcModels.AnalyzeSlots(list);
        Assert.Equal(24, slots["nSkills"]!.GetValue<int>());
        Assert.Equal(6, slots["cells"]!["sv1-ef1"]!["success"]!.GetValue<int>());
        Assert.Equal(0, slots["cells"]!["sv1-ef1"]!["failure"]!.GetValue<int>());
        Assert.Equal(30, RqcModels.Analyze(list)["nSkills"]!.GetValue<int>());
    }
    [Fact]
    public void The_clustered_McNemar_statistic_and_the_diagnostic_counts_match_hand_computation()
    {
        // Task t0: three slots go fail→success (b); task t1: one b and one c; task t2: concordant.
        var list = new List<SkillState>();
        var id = 0;
        void Pair(string task, int trial, bool off, bool on)
        {
            list.Add(new SkillState($"s{id++}", false, false, trial, task) { CallCount = 1, SuccessCount = off ? 1 : 0, SelfVerdict = "fail", LastExecutionOk = off });
            list.Add(new SkillState($"s{id++}", false, true, trial, task) { CallCount = 1, SuccessCount = on ? 1 : 0, SelfVerdict = "pass", LastExecutionOk = on });
        }
        Pair("t0", 0, false, true);
        Pair("t0", 1, false, true);
        Pair("t0", 2, false, true);
        Pair("t1", 0, false, true);
        Pair("t1", 1, true, false);
        Pair("t2", 0, true, true);
        var m = RqcModels.ClusteredMcNemar(list);
        Assert.Equal(4, m["b"]!.GetValue<int>());
        Assert.Equal(1, m["c"]!.GetValue<int>());
        Assert.Equal(2, m["tasksWithDiscordantPairs"]!.GetValue<int>());
        // X² = (Σ(b_k − c_k))² / Σ(b_k − c_k)² = (3 + 0)² / (9 + 0) = 1
        Assert.Equal(1.0, m["clusteredChiSquare"]!.GetValue<double>(), 12);
        var d = RqcModels.Diagnostics(list, iterations: 2000);
        // self-PASS skills are the six feedback-on ones (five usable, one not); self-FAIL skills are the six off ones (two usable):
        // TP 5, FP 1, FN 2, TN 4. The estimands condition on the oracle, the predictive values on the self-verdict.
        int[] Ratio(string name) => [d[name]!["numerator"]!.GetValue<int>(), d[name]!["denominator"]!.GetValue<int>()];
        Assert.Equal([1, 5], Ratio("hallucinationRate"));   // P(self-pass | unusable) = FP / (FP + TN)
        Assert.Equal([2, 7], Ratio("missRate"));            // P(self-fail | usable) = FN / (FN + TP)
        Assert.Equal([9, 12], Ratio("agreement"));
        Assert.Equal([1, 6], Ratio("falseDiscoveryRate"));  // P(unusable | self-pass)
        Assert.Equal([2, 6], Ratio("falseOmissionRate"));   // P(usable | self-fail)
        Assert.Equal((2.0 / 7) - (1.0 / 5), d["missMinusHallucination"]!["estimate"]!.GetValue<double>(), 12);
        // BCa: an interval around the estimate
        var bca = d["agreement"]!["taskBootstrapBca95"]!.AsArray().Select(x => x!.GetValue<double>()).ToArray();
        Assert.True(bca[0] <= 0.75 && 0.75 <= bca[1], $"BCa [{bca[0]}, {bca[1]}]");
    }
    [Fact]
    public void The_simulated_positive_control_recovers_the_injected_self_verification_error_rates()
    {
        // The mock backend passes an unusable candidate with probability 0.30 and fails a usable one with probability 0.10
        // (MockBackend defaults). The estimands, conditioned on the oracle's verdict, must recover both; the predictive values,
        // conditioned on the self-verdict, depend on how many usable skills there are and need not.
        var dir = Path.Combine(RqcReanalysisTests.RunsDirectory(), "rq-c-s42-mock-t30-r5");
        var skills = RqcAnalysis.ReplaySkills(StepRecord.ReadJsonl(Path.Combine(dir, "trials.jsonl")), new RqcConfig(42));
        var d = RqcModels.Diagnostics(skills, iterations: 200);
        double[] Wilson(string name) => [.. d[name]!["wilson95"]!.AsArray().Select(x => x!.GetValue<double>())];
        var hal = Wilson("hallucinationRate");
        var miss = Wilson("missRate");
        Assert.True(hal[0] <= 0.30 && 0.30 <= hal[1], $"hallucinationRate interval [{hal[0]}, {hal[1]}] misses the injected 0.30");
        Assert.True(miss[0] <= 0.10 && 0.10 <= miss[1], $"missRate interval [{miss[0]}, {miss[1]}] misses the injected 0.10");
        var fdr = Wilson("falseDiscoveryRate");
        Assert.False(fdr[0] <= 0.30 && 0.30 <= fdr[1], "the false discovery rate is not the injected hallucination rate");
    }
    [Fact]
    public void Only_recoveries_with_changed_code_count_as_feedback_reaching_the_generator()
    {
        static StepRecord Step(string task, bool regenerated, bool ok, bool reused = false) =>
            new("sv1-ef0", 0, 0, task, "s", reused, 0, false, false, regenerated, null, ok);
        // t0: first attempt fails, regenerated with new code that works (a real recovery).
        // t1: first attempt works but was rejected; regenerated unchanged, it "recovers" with the same code.
        // t2: regenerated with new code that still fails.
        StepRecord[] steps = [Step("t0", false, false), Step("t0", true, true), Step("t1", false, true), Step("t1", true, true),
            Step("t2", false, false), Step("t2", true, false), Step("t0", false, true, reused: true)];
        string?[] codes = ["a", "b", "c", "c", "d", "e", "b"];
        var loop = RqcModels.ChangedCodeRecoveries(steps, codes);
        Assert.Equal(3, loop["regenerations"]!.GetValue<int>());
        Assert.Equal(2, loop["regenerationsWithChangedCode"]!.GetValue<int>());
        Assert.Equal(2, loop["recoveries"]!.GetValue<int>());
        Assert.Equal(1, loop["recoveriesWithChangedCode"]!.GetValue<int>());
    }
    [Fact]
    public void The_guard_credits_only_recoveries_with_changed_code_when_the_log_has_fingerprints()
    {
        static StepRecord Step(string task, bool regenerated, bool ok, string? hash) =>
            new("sv1-ef1", 0, 0, task, "s", false, 0, false, false, regenerated, null, ok, hash);
        // a working candidate rejected by the self-verifier and regenerated unchanged: a recovery, but not through feedback
        StepRecord[] unchanged = [Step("t0", false, true, "a"), Step("t0", true, true, "a")];
        Assert.Equal(0, RqcAnalysis.ChangedCodeRecoveries(unchanged));
        var (reachable, note) = RqcAnalysis.Guard(false, 1, 1, RqcAnalysis.ChangedCodeRecoveries(unchanged));
        Assert.False(reachable);
        Assert.StartsWith("INERT LOOP", note, StringComparison.Ordinal);
        StepRecord[] changed = [Step("t0", false, false, "a"), Step("t0", true, true, "b")];
        Assert.True(RqcAnalysis.Guard(false, 1, 1, RqcAnalysis.ChangedCodeRecoveries(changed)).Reachable);
        // logs written before fingerprints keep the original rule
        StepRecord[] old = [Step("t0", false, true, null), Step("t0", true, true, null)];
        Assert.Null(RqcAnalysis.ChangedCodeRecoveries(old));
        Assert.True(RqcAnalysis.Guard(false, 1, 1, null).Reachable);
        Assert.StartsWith("NULL BY CONSTRUCTION", RqcAnalysis.Guard(true, 1, 1, 1).Note, StringComparison.Ordinal);
    }
}
