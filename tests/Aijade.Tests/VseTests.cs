using System.Text.Json;

using Aijade.Memory.Contracts;
using Aijade.Memory.Development;

namespace Aijade.Tests;

/// <summary>Routing buckets and objectives must equal the recorded golden data.</summary>
public class VseTests
{
    private static readonly JsonElement Golden =
        JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "vse-golden.json"))).RootElement;

    private static CandidateVersion Cand(string id = "v1", double quality = 0.5, double safety = 0.9, bool invariants = true, bool rollback = true) =>
        new(id, quality, 0.1, 0.1, 0.1, 0.1, 0.1, safety, 0.8, invariants, rollback);

    private static readonly double[] Qualities = [0.1, 0.37, 1.9];

    private static EvaluationEvidencePack Pack() => new("eep-1", "ep-1", new CoreTestGate(true, 10, 0), 1000);

    [Fact]
    public void Buckets_and_objectives_match_the_original()
    {
        double[] buckets =
        [
            Vse.StableBucket(new VseRoutingIdentity("user-1")),
            Vse.StableBucket(new VseRoutingIdentity("  用户😀 ", "s")),
            Vse.StableBucket(new VseRoutingIdentity(" ", "session-a")),
            Vse.StableBucket(new VseRoutingIdentity(SessionId: " x　")),
            Vse.StableBucket(new VseRoutingIdentity("u"), "other-ns"),
        ];
        Assert.Equal(Golden.GetProperty("buckets").EnumerateArray().Select(x => x.GetDouble()), buckets);
        Assert.Equal(Golden.GetProperty("obj").EnumerateArray().Select(x => x.GetDouble()),
            Qualities.Select(q => Vse.Objective(new CandidateVersion("v", q, 0.13, 0.07, 0.11, 0.3, 0.09, 1, 1, true, true))));
    }

    [Fact]
    public void Routing_is_stable_per_user_and_needs_an_identity()
    {
        var user = Vse.StableBucket(new VseRoutingIdentity("user-1", "session-a"));
        Assert.Equal(user, Vse.StableBucket(new VseRoutingIdentity("user-1", "session-b")));
        Assert.NotEqual(user, Vse.StableBucket(new VseRoutingIdentity(SessionId: "session-a")));
        Assert.InRange(user, 0, 0.9999999999);
        Assert.Contains("userId or sessionId", Assert.Throws<ArgumentException>(() => Vse.StableBucket(new VseRoutingIdentity())).Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Grades_bound_what_the_agent_may_change()
    {
        Assert.Equal(AutomationLevel.Auto, Vse.AutomationAllowed(EvolutionGrade.E0));
        Assert.Equal(AutomationLevel.SandboxSignGray, Vse.AutomationAllowed(EvolutionGrade.E2));
        Assert.Equal(AutomationLevel.FullTestReview, Vse.AutomationAllowed(EvolutionGrade.E3));
        Assert.Equal(AutomationLevel.HumanReviewRequired, Vse.AutomationAllowed(EvolutionGrade.E4));
        Assert.Equal(AutomationLevel.Forbidden, Vse.AutomationAllowed(EvolutionGrade.E5));
        Assert.True(Vse.AssertEvolvable(EvolutionGrade.E1).Ok && Vse.AssertEvolvable(EvolutionGrade.E3).Ok);
        Assert.Contains("human review", Vse.AssertEvolvable(EvolutionGrade.E4).Reason, StringComparison.Ordinal);
        Assert.Contains("never", Vse.AssertEvolvable(EvolutionGrade.E5).Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Pipeline_advances_in_order_and_ends_kept_or_rolled_back()
    {
        var s = EvolutionStage.CapabilityGap;
        for (var i = 0; i < 15; i++)
            s = Vse.NextStage(s, EvolutionEvent.Advance)!.Value;
        Assert.Equal(EvolutionStage.RuntimeMonitoring, s);
        Assert.Null(Vse.NextStage(s, EvolutionEvent.Advance));
        Assert.Null(Vse.NextStage(EvolutionStage.ShadowMode, EvolutionEvent.Keep));
        Assert.Equal(EvolutionStage.Kept, Vse.NextStage(s, EvolutionEvent.Keep));
        Assert.Equal(EvolutionStage.RolledBack, Vse.NextStage(EvolutionStage.CandidatePatch, EvolutionEvent.Rollback));
        Assert.Null(Vse.NextStage(EvolutionStage.Kept, EvolutionEvent.Rollback));
        Assert.Null(Vse.NextStage(EvolutionStage.RolledBack, EvolutionEvent.Advance));
    }

    [Fact]
    public void Promotion_requires_every_gate_present_to_pass()
    {
        Assert.True(Vse.CanPromote(Pack()).Ok);
        Assert.True(Vse.CanPromote(Pack() with { SecuritySandbox = new GateResult(true, 0) }).Ok);
        Assert.False(Vse.CanPromote(Pack() with { UnitContractPropertyTests = new CoreTestGate(false, 10, 3) }).Ok);
        Assert.False(Vse.CanPromote(Pack() with { SecuritySandbox = new GateResult(false, 1) }).Ok);
        Assert.False(Vse.CanPromote(Pack() with { AdversarialEval = new GateResult(false, 2) }).Ok);
        Assert.False(Vse.CanPromote(Pack() with { HistoricalReplay = new GateResult(false, 1) }).Ok);
        Assert.False(Vse.CanPromote(Pack() with { DependencyLicenseScan = (false, ["GPL-3.0"]) }).Ok);
    }

    [Fact]
    public void Candidate_selection_keeps_the_hard_constraints()
    {
        Assert.Equal("v2", Vse.SelectCandidate([Cand(), Cand("v2", 0.9)])!.Id);
        Assert.Equal("ok", Vse.SelectCandidate([Cand("bad", 99, safety: 0.5), Cand("ok")])!.Id);
        Assert.Null(Vse.SelectCandidate([Cand("a", 99, invariants: false), Cand("b", 99, rollback: false)]));
        Assert.True(Vse.SatisfiesConstraints(Cand()));
        Assert.False(Vse.SatisfiesConstraints(Cand(safety: 0.1)));
    }
}
