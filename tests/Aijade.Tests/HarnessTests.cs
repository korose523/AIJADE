using System.Text.Json;

using Aijade.Learning.Skills;
using Aijade.Research.RqC;
using Aijade.Research.SkillBench;
using Aijade.Research.Statistics;

namespace Aijade.Tests;

/// <summary>
/// The RQ-C harness on the Jint sandbox must replay the recorded golden run step for step: the same mock
/// backend draws, sandbox verdicts, registry lifecycle and every statistic of the 2×2 (golden: 6 trials, 1440 steps).
/// </summary>
public class HarnessTests
{
    private static readonly JsonElement Golden =
        JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "harness-mock-t6.json"))).RootElement;

    /// <summary>Non-finite numbers were exported as "__NaN" / "__Infinity".</summary>
    private static double N(JsonElement e) => e.ValueKind == JsonValueKind.String ? double.Parse(e.GetString()![2..], System.Globalization.CultureInfo.InvariantCulture) : e.GetDouble();

    private static void Eq(JsonElement expected, double actual) => Assert.Equal(N(expected), actual, 12);

    [Fact]
    public Task Mock_run_replays_the_original_step_for_step() => Replay(Golden, 6);

    /// <summary>The full preregistered protocol (30 trials, 7200 steps); opt-in via AIJADE_FULL_PARITY=&lt;golden json path&gt;.</summary>
    [Fact]
    public Task Full_preregistered_mock_run_replays_the_original()
    {
        var path = Environment.GetEnvironmentVariable("AIJADE_FULL_PARITY");
        if (string.IsNullOrEmpty(path) || !File.Exists(path))
            Assert.Skip("set AIJADE_FULL_PARITY to a recorded 30-trial golden run");
        return Replay(JsonDocument.Parse(File.ReadAllText(path)).RootElement, 30);
    }

    private static async Task Replay(JsonElement golden, int trials)
    {
        var sandbox = new Sandbox();
        var steps = new List<HarnessStep>();
        var result = await Harness.RunAsync(new RunOptions(new MockBackend(42, sandbox), trials, 5, 42, 12, sandbox, OnStep: steps.Add), TestContext.Current.CancellationToken);

        var expected = golden.GetProperty("steps").EnumerateArray().ToArray();
        Assert.Equal(expected.Length, steps.Count);
        for (var i = 0; i < steps.Count; i++)
        {
            var e = expected[i];
            var a = steps[i];
            var sv = e.GetProperty("selfVerdict");
            Assert.Equal(
                (e.GetProperty("condition").GetString(), e.GetProperty("trial").GetInt32(), e.GetProperty("round").GetInt32(), e.GetProperty("taskId").GetString(),
                    e.GetProperty("skillId").GetString(), e.GetProperty("reused").GetBoolean(), e.GetProperty("attempt").GetInt32(), e.GetProperty("hadEnvFeedback").GetBoolean(),
                    e.GetProperty("hadSelfCritique").GetBoolean(), e.GetProperty("regeneratedFromFailure").GetBoolean(),
                    sv.ValueKind == JsonValueKind.Null ? (bool?)null : sv.GetString() == "pass", e.GetProperty("execOk").GetBoolean()),
                ((string?)a.Condition, a.Trial, a.Round, (string?)a.TaskId, (string?)a.SkillId, a.Reused, a.Attempt, a.HadEnvFeedback, a.HadSelfCritique,
                    a.RegeneratedFromFailure, a.SelfVerdictPass, a.ExecOk));
        }

        foreach (var (eRecs, cond) in golden.GetProperty("records").EnumerateArray().Zip(result.Conditions))
        {
            foreach (var (e, r) in eRecs.EnumerateArray().Zip(cond.Records))
            {
                Assert.Equal((e.GetProperty("id").GetString(), e.GetProperty("status").GetString(), e.GetProperty("calls").GetInt32(), e.GetProperty("succ").GetInt32()),
                    ((string?)r.SkillId, (string?)JsonNamingPolicy.KebabCaseLower.ConvertName(r.Status.ToString()), r.CallCount, r.SuccessCount));
                if (e.GetProperty("score").ValueKind != JsonValueKind.Null)
                {
                    Assert.Equal(e.GetProperty("score").GetDouble(), r.SelfVerification!.Score!.Value);
                    Assert.Equal(e.GetProperty("rationale").GetString(), r.SelfVerification.Rationale);
                }
            }
        }

        var res = golden.GetProperty("result");
        foreach (var (e, c) in res.GetProperty("table").EnumerateArray().Zip(result.Table))
        {
            Assert.Equal(e.GetProperty("count").GetInt32(), c.Count);
            Eq(e.GetProperty("precision"), c.Precision);
            Eq(e.GetProperty("retiredRate"), c.RetiredRate);
            Eq(e.GetProperty("meanCallsPerSkill"), c.MeanCallsPerSkill);
        }
        Assert.Equal(res.GetProperty("nSkills").GetInt32(), result.NSkills);
        Assert.Equal(res.GetProperty("nExecutions").GetInt32(), result.NExecutions);
        foreach (var (e, c) in res.GetProperty("perCellCI").EnumerateArray().Zip(result.PerCellCi))
        {
            var ci = e.GetProperty("ci");
            Eq(ci.GetProperty("mean"), c.Ci.Mean);
            Eq(ci.GetProperty("lo"), c.Ci.Lo);
            Eq(ci.GetProperty("hi"), c.Ci.Hi);
        }
        void Chi(string name, ChiSquareResult r)
        {
            Eq(res.GetProperty(name).GetProperty("statistic"), r.Statistic);
            Eq(res.GetProperty(name).GetProperty("p"), r.P);
        }
        Chi("chiSquare", result.ChiSquare);
        Chi("chiSquareSelfVerification", result.ChiSquareSelfVerification);
        Chi("chiSquareExecutionLevel", result.ChiSquareExecutionLevel);
        var mc = res.GetProperty("mcnemarEnvFeedback");
        Assert.Equal((mc.GetProperty("a").GetInt32(), mc.GetProperty("b").GetInt32(), mc.GetProperty("c").GetInt32(), mc.GetProperty("d").GetInt32()),
            (result.McNemarEnvFeedback.A, result.McNemarEnvFeedback.B, result.McNemarEnvFeedback.C, result.McNemarEnvFeedback.D));
        Eq(mc.GetProperty("p"), result.McNemarEnvFeedback.P);
        var fi = res.GetProperty("factorialInteraction");
        Eq(fi.GetProperty("estimate"), result.FactorialInteraction.Estimate);
        Eq(fi.GetProperty("p"), result.FactorialInteraction.P);
        var did = res.GetProperty("diffInDiff");
        Eq(did.GetProperty("estimate"), result.DiffInDiff.Estimate);
        Eq(did.GetProperty("ci").GetProperty("lo"), result.DiffInDiff.Ci.Lo);
        Eq(did.GetProperty("ci").GetProperty("hi"), result.DiffInDiff.Ci.Hi);
        var es = res.GetProperty("effectSizes");
        Eq(es.GetProperty("oddsRatio"), result.EffectSizes.OddsRatio);
        Eq(es.GetProperty("riskDifference"), result.EffectSizes.RiskDifference);
        Eq(es.GetProperty("cramersV"), result.EffectSizes.CramersV);
        Eq(es.GetProperty("cohensH"), result.EffectSizes.CohensH);
        foreach (var (e, h) in res.GetProperty("multiplicity").GetProperty("adjusted").EnumerateArray().Zip(result.Multiplicity))
        {
            Assert.Equal((e.GetProperty("label").GetString(), e.GetProperty("reject").GetBoolean()), ((string?)h.Label, h.Reject));
            Eq(e.GetProperty("adjustedP"), h.AdjustedP);
        }
        var pw = res.GetProperty("power");
        Assert.Equal(pw.GetProperty("nSkillsPerCell").GetInt32(), result.Power.NSkillsPerCell);
        Eq(pw.GetProperty("minDetectableEffectAt80"), result.Power.MinDetectableEffectAt80);
        Eq(pw.GetProperty("powerAtDelta10pp"), result.Power.PowerAtDelta10pp);
        // The original counted every recovery; the guard now credits only recoveries with changed code. The totals must still
        // match the original, and the verdict must be the one the shared guard gives for them.
        var dg = res.GetProperty("degeneracy");
        Assert.Equal(dg.GetProperty("totalRecoveries").GetInt32(), result.Degeneracy.TotalRecoveries);
        Assert.Equal(dg.GetProperty("totalRegenerations").GetInt32(), result.Degeneracy.TotalRegenerations);
        Assert.Equal(RqcAnalysis.Guard(result.Degeneracy.AllCellsIdenticalPrecision, result.Degeneracy.TotalRegenerations,
            result.Degeneracy.TotalRecoveries, result.Degeneracy.TotalRecoveriesWithChangedCode).Note, result.Degeneracy.Note);
        Assert.InRange(result.Degeneracy.TotalRecoveriesWithChangedCode!.Value, 1, result.Degeneracy.TotalRecoveries);
        Assert.Equal(res.GetProperty("preregistrationDeviation").EnumerateArray().Select(x => x.GetString()), result.PreregistrationDeviation);
        foreach (var (e, l) in golden.GetProperty("loops").EnumerateArray().Zip(result.Conditions.Select(c => c.Loop)))
            Assert.Equal((e.GetProperty("regenerations").GetInt32(), e.GetProperty("regenerationsWithSignal").GetInt32(), e.GetProperty("recoveries").GetInt32()),
                (l.Regenerations, l.RegenerationsWithSignal, l.Recoveries));
    }

    [Fact]
    public void Prompts_and_locked_seed_match_the_original()
    {
        var g = JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "prompts-golden.json"))).RootElement;
        var ctx = new GenerateContext(2, new EnvironmentFeedbackSignal([0, 3], 2, 5, ["TypeError: x is not a function", "Error: boom"]), "wrong edge case", "  function solve(a){ return a }\n\n");
        foreach (var id in new[] { "arr-max", "arr-remove-falsy", "obj-get-nested", "str-slugify" })
        {
            var task = Bench.Tasks.First(t => t.Id == id);
            Assert.Equal(g.GetProperty("generate").GetProperty(id).GetString(), Backends.BuildGeneratePrompt(task, ctx));
            var verify = g.GetProperty("verify").GetProperty(id).GetString()!.Split('\0');
            Assert.Equal(verify[0], Backends.BuildVerifyPrompt(task, "function solve(){}"));
            Assert.Equal(uint.Parse(verify[1], System.Globalization.CultureInfo.InvariantCulture), Backends.DeriveOllamaSeed("qwen2.5-coder:7b", "http://localhost:11434"));
        }
        Assert.StartsWith("You are an expert JavaScript programmer.\nImplement the following function.", Backends.BuildGeneratePrompt(Bench.Tasks[0], new GenerateContext(0)), StringComparison.Ordinal);
    }
    [Fact]
    public void Differential_suites_perturb_arguments_by_type_and_the_reference_agrees_with_itself()
    {
        var variants = DifferentialTesting.Variants("[[1,2,3],\"ab\",4]");
        Assert.InRange(variants.Count, 1, DifferentialTesting.VariantsPerCase);
        Assert.All(variants, v => Assert.Equal(3, System.Text.Json.Nodes.JsonNode.Parse(v)!.AsArray().Count));
        Assert.DoesNotContain("[[1,2,3],\"ab\",4]", variants);
        Assert.Empty(DifferentialTesting.Variants("[undefined]"));   // not plain JSON: left out
        // the reference passes its own hidden suite, which therefore has expected values the reference produces
        var task = Bench.Tasks.First(t => t.Id == "arr-intersection");
        var hidden = DifferentialTesting.HiddenSuite(task, new Sandbox { IsolateArguments = true });
        Assert.NotEmpty(hidden.Tests);
        Assert.True(new Sandbox { IsolateArguments = true }.RunTask(Bench.ReferenceSolutions[task.Id], hidden).Ok);
        // a candidate that sorts instead of keeping the order of the first array passes the original tests but not the suite
        const string sorting = "function intersection(a, b) { return [...new Set(a.filter(x => b.includes(x)))].sort((x, y) => x - y); }";
        Assert.True(new Sandbox().RunTask(sorting, task).Ok);
        Assert.False(new Sandbox { IsolateArguments = true }.RunTask(sorting, hidden).Ok);
    }
}
