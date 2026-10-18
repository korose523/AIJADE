using System.Text.Json;

using Aijade.Learning.Skills;

namespace Aijade.Tests;

/// <summary>The skill library must equal the recorded golden data and read its JSONL.</summary>
public class SkillLibraryTests
{
    private static readonly JsonElement Golden =
        JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "skills-golden.json"))).RootElement;

    private static readonly List<SkillRecord> Records =
        Golden.GetProperty("recs").EnumerateArray().Select(r => JsonSerializer.Deserialize<SkillRecord>(r.GetRawText(), JsonlSkillStore.JsonOptions)!).ToList();

    /// <summary>JSON.stringify writes NaN as null.</summary>
    private static double N(JsonElement e) => e.ValueKind == JsonValueKind.Null ? double.NaN : e.GetDouble();

    [Fact]
    public void Metrics_tables_and_diagnostics_match_the_original()
    {
        var m = SkillMetrics.Compute(Records);
        var e = Golden.GetProperty("metrics");
        Assert.Equal((e.GetProperty("active").GetInt32(), e.GetProperty("retired").GetInt32(), e.GetProperty("rejected").GetInt32()), (m.Active, m.Retired, m.Rejected));
        Assert.Equal((e.GetProperty("selfPass").GetInt32(), e.GetProperty("selfFail").GetInt32(), e.GetProperty("selfVerificationDisabled").GetInt32()), (m.SelfPass, m.SelfFail, m.SelfVerificationDisabled));
        Assert.Equal((e.GetProperty("executed").GetInt32(), e.GetProperty("execSuccess").GetInt32(), e.GetProperty("execFail").GetInt32()), (m.Executed, m.ExecSuccess, m.ExecFail));
        Assert.Equal(N(e.GetProperty("precision")), m.Precision);
        Assert.Equal(N(e.GetProperty("meanCallsPerSkill")), m.MeanCallsPerSkill);
        Assert.Equal(N(e.GetProperty("selfVerificationHallucinationRate")), m.SelfVerificationHallucinationRate);
        Assert.Equal(N(e.GetProperty("selfVerificationMissRate")), m.SelfVerificationMissRate);
        Assert.Equal(N(e.GetProperty("selfEnvironmentAgreement")), m.SelfEnvironmentAgreement);
        Assert.Equal(e.GetProperty("byDomain").GetProperty("synthetic").GetInt32(), m.ByDomain[SkillDomain.Synthetic]);

        foreach (var (key, table) in new[] { ("loop", SkillMetrics.LearningLoopTable(Records)), ("loopGame", SkillMetrics.LearningLoopTable(Records, SkillDomain.Game)) })
        {
            foreach (var (c, a) in Golden.GetProperty(key).EnumerateArray().Zip(table))
            {
                Assert.Equal((c.GetProperty("selfVerificationEnabled").GetBoolean(), c.GetProperty("envFeedbackEnabled").GetBoolean(), c.GetProperty("count").GetInt32()),
                    (a.SelfVerificationEnabled, a.EnvFeedbackEnabled, a.Count));
                Assert.Equal(N(c.GetProperty("precision")), a.Precision);
                Assert.Equal(N(c.GetProperty("retiredRate")), a.RetiredRate);
                Assert.Equal(N(c.GetProperty("meanCallsPerSkill")), a.MeanCallsPerSkill);
            }
        }
        var d = SkillMetrics.SelfVerificationDiagnostics(Records);
        var ed = Golden.GetProperty("diag");
        Assert.Equal(ed.GetProperty("n").GetInt32(), d.N);
        Assert.Equal((N(ed.GetProperty("hallucinationRate")), N(ed.GetProperty("missRate")), N(ed.GetProperty("agreement"))), (d.HallucinationRate, d.MissRate, d.Agreement));
    }

    [Fact]
    public async Task Jsonl_store_reads_the_original_files_and_round_trips()
    {
        var ct = TestContext.Current.CancellationToken;
        var file = Path.Combine(Path.GetTempPath(), $"skills-{Guid.NewGuid():N}.jsonl");
        try
        {
            await File.WriteAllTextAsync(file, Golden.GetProperty("jsonl").GetString(), ct);
            using var store = new JsonlSkillStore(file);
            var j1 = (await store.GetAsync("j1", ct))!;
            Assert.Equal((SkillLifecycle.Retired, RetirementReason.LowPrecision, 3, 0), (j1.Status, j1.RetirementReason!.Value, j1.CallCount, j1.SuccessCount));
            Assert.Equal(("no tool", 12.5), (j1.Execution!.Detail, j1.Execution.DurationMs!.Value));
            Assert.Equal("qwen", j1.SelfVerification!.Model);
            Assert.Equal(3, j1.Trigger!.TurnIndex);
            Assert.Equal("a", j1.Metadata!["标签"]![0]!.GetValue<string>());
            Assert.Equal(RetirementReason.Manual, (await store.GetAsync("j2", ct))!.RetirementReason);

            var registry = new SkillRegistry(store, () => 5);
            await registry.RecordExecutionAsync("j2", new ExecutionOutcome(true), ct);
            using var reopened = new JsonlSkillStore(file);
            var all = await reopened.AllAsync(ct);
            Assert.Equal(["j1", "j2"], all.Select(r => r.SkillId));
            Assert.Equal(1, all[1].SuccessCount);
            Assert.Contains("\"retirementReason\":\"low-precision\"", await File.ReadAllTextAsync(file, ct), StringComparison.Ordinal);
        }
        finally
        {
            File.Delete(file);
        }
    }

    private static SkillRegistry Reg() => new(new MemorySkillStore(), () => 1_700_000_000_000);

    [Fact]
    public async Task Counters_precision_and_self_verification()
    {
        var ct = TestContext.Current.CancellationToken;
        var store = new MemorySkillStore();
        await new SkillRegistry(store).CreateAsync(new CreateSkillOptions("craft_table", SkillDomain.Game, SkillId: "k1"), ct);
        Assert.NotNull(await new SkillRegistry(store).GetAsync("k1", ct));

        var r = Reg();
        await r.CreateAsync(new CreateSkillOptions("mine", SkillDomain.Game, SkillId: "k1"), ct);
        foreach (var ok in new[] { true, false, true })
            await r.RecordExecutionAsync("k1", new ExecutionOutcome(ok), ct);
        var rec = (await r.GetAsync("k1", ct))!;
        Assert.Equal((3, 2, 1), (rec.CallCount, rec.SuccessCount, rec.FailureCount));
        Assert.Equal(2.0 / 3, (await r.MetricsAsync(ct)).Precision, 5);

        var never = Reg();
        await never.CreateAsync(new CreateSkillOptions("never_used", SkillDomain.Game, SkillId: "k1"), ct);
        Assert.True(double.IsNaN((await never.MetricsAsync(ct)).Precision));

        var h = Reg();
        await h.CreateAsync(new CreateSkillOptions("good", SkillDomain.Game, SkillId: "k1"), ct);
        await h.SetSelfVerificationAsync("k1", SkillVerdict.Pass, 0.95, cancellationToken: ct);
        await h.RecordExecutionAsync("k1", new ExecutionOutcome(true), ct);
        await h.CreateAsync(new CreateSkillOptions("bad", SkillDomain.Game, SkillId: "k2"), ct);
        await h.SetSelfVerificationAsync("k2", SkillVerdict.Pass, 0.88, cancellationToken: ct);
        await h.RecordExecutionAsync("k2", new ExecutionOutcome(false, "tool missing"), ct);
        var m = await h.MetricsAsync(ct);
        Assert.Equal((2, 1), (m.SelfPass, m.ExecFail));
        Assert.Equal(0.5, m.SelfVerificationHallucinationRate, 5);
        Assert.Equal(0.5, m.SelfEnvironmentAgreement, 5);

        var miss = Reg();
        await miss.CreateAsync(new CreateSkillOptions("underrated", SkillDomain.Game, SkillId: "k1"), ct);
        await miss.SetSelfVerificationAsync("k1", SkillVerdict.Fail, 0.2, cancellationToken: ct);
        await miss.RecordExecutionAsync("k1", new ExecutionOutcome(true), ct);
        Assert.Equal(1, (await miss.MetricsAsync(ct)).SelfVerificationMissRate);
        Assert.Equal(SkillLifecycle.Rejected, (await miss.GetAsync("k1", ct))!.Status);
    }

    [Fact]
    public async Task Retirement_pruning_and_oracle_guard()
    {
        var ct = TestContext.Current.CancellationToken;
        var r = Reg();
        await r.CreateAsync(new CreateSkillOptions("doomed", SkillDomain.Game, SkillId: "k1"), ct);
        await r.RecordExecutionAsync("k1", new ExecutionOutcome(false), ct);
        await r.RecordExecutionAsync("k1", new ExecutionOutcome(false), ct);
        Assert.Equal(SkillLifecycle.Active, (await r.GetAsync("k1", ct))!.Status);
        await r.RecordExecutionAsync("k1", new ExecutionOutcome(false), ct);
        Assert.Equal((SkillLifecycle.Retired, RetirementReason.LowPrecision), ((await r.GetAsync("k1", ct))!.Status, (await r.GetAsync("k1", ct))!.RetirementReason!.Value));

        var p = Reg();
        for (var i = 0; i < 4; i++)
        {
            await p.CreateAsync(new CreateSkillOptions($"s{i}", SkillDomain.Game, SkillId: $"k{i}"), ct);
            await p.RecordExecutionAsync($"k{i}", new ExecutionOutcome(true), ct);
            await p.RecordExecutionAsync($"k{i}", new ExecutionOutcome(i == 0), ct);
            await p.RecordExecutionAsync($"k{i}", new ExecutionOutcome(i == 0), ct);
        }
        Assert.Equal(0, (await p.MetricsAsync(ct)).Retired);
        Assert.Equal(["k1", "k2", "k3"], (await p.PruneLowPrecisionAsync(0.5, 3, ct)).Select(x => x.SkillId).Order(StringComparer.Ordinal));
        var m = await p.MetricsAsync(ct);
        Assert.Equal((1, 3), (m.Active, m.Retired));
        Assert.Equal(0.5, m.Precision, 5);

        var t = Reg();
        await t.CreateAsync(new CreateSkillOptions("mine", SkillDomain.Game, SkillId: "g1"), ct);
        await t.SetSelfVerificationAsync("g1", SkillVerdict.Pass, cancellationToken: ct);
        await t.RecordExecutionAsync("g1", new ExecutionOutcome(false), ct);
        var chat = await t.CreateAsync(new CreateSkillOptions("comfort_user", SkillDomain.Conversation, SelfVerification: new SelfVerification(SkillVerdict.Pass, true), SkillId: "c1"), ct);
        var cells = await t.TwoByTwoAsync(ct);
        Assert.Equal(1, cells.First(c => c.Domain == SkillDomain.Game && c.SelfVerificationEnabled).HallucinationRate);
        Assert.True(double.IsNaN(cells.First(c => c.Domain == SkillDomain.Conversation && c.SelfVerificationEnabled).HallucinationRate));
        Assert.Contains("no environmental oracle", Assert.Throws<NoOracleException>(() => SkillRegistry.AssertOracleAvailable(chat)).Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Learning_loop_cells_are_finite_and_default_pools_oracle_domains()
    {
        static SkillRecord Make(string id, SkillDomain d, int calls, int successes, bool sv = false, bool ef = false, SkillLifecycle status = SkillLifecycle.Active) =>
            new(id, id, 1, d)
            {
                CallCount = calls,
                SuccessCount = successes,
                Status = status,
                SelfVerification = sv ? new SelfVerification(SkillVerdict.Pass, true) : null,
                EnvFeedback = ef ? new EnvFeedback(true) : null,
            };
        SkillRecord[] executable = [Make("e1", SkillDomain.Executable, 2, 1), Make("e2", SkillDomain.Executable, 2, 2, ef: true),
            Make("e3", SkillDomain.Executable, 3, 3, sv: true), Make("e4", SkillDomain.Executable, 3, 3, sv: true, ef: true)];
        var cells = SkillMetrics.LearningLoopTable(executable);
        Assert.Equal(4, cells.Count);
        Assert.All(cells, c => Assert.True(double.IsFinite(c.Precision) && !double.IsNaN(c.RetiredRate) && c.Count > 0));

        SkillRecord[] game = [Make("a", SkillDomain.Game, 2, 1), Make("b", SkillDomain.Game, 2, 2, sv: true), Make("c", SkillDomain.Game, 2, 1, ef: true),
            Make("d", SkillDomain.Game, 2, 2, sv: true, ef: true, status: SkillLifecycle.Retired)];
        var g = SkillMetrics.LearningLoopTable(game);
        double Col(bool ef) => g.Where(c => c.EnvFeedbackEnabled == ef).Sum(c => c.RetiredRate * c.Count) / g.Where(c => c.EnvFeedbackEnabled == ef).Sum(c => c.Count);
        Assert.True(Col(true) > Col(false));
    }
}
