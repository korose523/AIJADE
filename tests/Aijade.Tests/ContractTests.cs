using System.Text.Json;

using Aijade.Memory.Contracts;

namespace Aijade.Tests;

/// <summary>Behaviour of the memory contracts.</summary>
public class ContractTests
{
    private static readonly SourceRef Src = new("evt-1", true, "default");

    [Fact]
    public void Memory_candidate_requires_a_source()
    {
        var c = new MemoryCandidate("m1", "likes tea", "semantic", [Src], 1);
        Assert.True(ContractValidation.Validate(c).Ok);
        Assert.Contains("source", ContractValidation.Validate(c with { Sources = [] }).Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Experiment_manifest_needs_seed_conditions_and_metrics()
    {
        var m = new ExperimentManifest("e1", "h2", "1.0.0", 42, [new ExperimentCondition("on", "gating on")], ["recall@8"], 0);
        Assert.True(ContractValidation.Validate(m).Ok);
        Assert.False(ContractValidation.Validate(m with { Seed = double.NaN }).Ok);
        Assert.False(ContractValidation.Validate(m with { Conditions = [] }).Ok);
        Assert.Contains("falsifiable", ContractValidation.Validate(m with { Metrics = [] }).Reason, StringComparison.Ordinal);
    }

    private static Appraisal Appraisal() =>
        new("a1", "evt-1", "agent", "user", new AppraisalDimensions(0.2, 0.5, 0.7, 0.3, 0, 0.1), 0.8, "model", 10);

    [Fact]
    public void Appraisal_is_bounded()
    {
        Assert.True(ContractValidation.Validate(Appraisal()).Ok);
        Assert.False(ContractValidation.Validate(Appraisal() with { EventRef = "" }).Ok);
        Assert.False(ContractValidation.Validate(Appraisal() with { Confidence = 1.2 }).Ok);
        Assert.False(ContractValidation.Validate(Appraisal() with { Dimensions = Appraisal().Dimensions with { Valence = 1.5 } }).Ok);
        Assert.False(ContractValidation.Validate(Appraisal() with { AppraisedAt = double.PositiveInfinity }).Ok);
    }

    private static readonly EndogenousStateVector State = new(0.5, 0.25, 1, 0, 0.75, 0.1, 1e-7);

    [Fact]
    public void State_snapshot_is_frozen_fingerprinted_and_bounded()
    {
        var fp = ContractValidation.StateSnapshotFingerprint(State, "hac", 1791428571829);
        var s = new StateSnapshot("s1", "agent", "user", 1791428571829, State, "hac", true, fp);
        Assert.True(ContractValidation.Validate(s).Ok);
        Assert.Contains("frozen", ContractValidation.Validate(s with { Frozen = false }).Reason, StringComparison.Ordinal);
        Assert.False(ContractValidation.Validate(s with { Fingerprint = "" }).Ok);
        Assert.False(ContractValidation.Validate(s with { State = State with { Safety = 1.5 } }).Ok);
    }

    [Fact]
    public void Snapshot_fingerprint_is_deterministic_and_matches_the_typescript_implementation()
    {
        var golden = JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "js-format-golden.json"))).RootElement;
        var fp = ContractValidation.StateSnapshotFingerprint(State, "hac", 1791428571829);
        Assert.Equal(golden.GetProperty("snapshot").GetString(), fp);
        Assert.Equal(fp, ContractValidation.StateSnapshotFingerprint(State, "hac", 1791428571829));
        Assert.NotEqual(fp, ContractValidation.StateSnapshotFingerprint(State with { Drive = 0.9 }, "hac", 1791428571829));
    }

    private static FeedbackEvent Feedback() => new("f1", "agent", "user", "s", "resp-1", "explicit", "accept", 5, Valence: 0.5);

    [Fact]
    public void Feedback_binds_to_a_target_and_declares_its_kind()
    {
        Assert.True(ContractValidation.Validate(Feedback()).Ok);
        Assert.True(ContractValidation.Validate(Feedback() with { Type = "implicit", Evidence = new Dictionary<string, double> { ["dwellMs"] = 1200 } }).Ok);
        Assert.False(ContractValidation.Validate(Feedback() with { TargetRef = "" }).Ok);
        Assert.False(ContractValidation.Validate(Feedback() with { Type = "telepathic" }).Ok);
        Assert.False(ContractValidation.Validate(Feedback() with { Valence = -2 }).Ok);
    }

    private static GoalRecord Goal() => new("g1", "agent", "user", "learn chess", Src, "active", new GoalBudget(100, 10, "steps"), 0);

    [Fact]
    public void Goal_has_source_status_and_a_budget_that_is_not_overspent()
    {
        Assert.True(ContractValidation.Validate(Goal()).Ok);
        Assert.False(ContractValidation.Validate(Goal() with { Source = null }).Ok);
        Assert.False(ContractValidation.Validate(Goal() with { Status = "dreaming" }).Ok);
        Assert.Contains("exceed", ContractValidation.Validate(Goal() with { Budget = new GoalBudget(10, 11, "steps") }).Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Plan_graph_rejects_dangling_dependencies_and_cycles()
    {
        PlanNode N(string id, params string[] deps) => new(id, "action", id, deps);
        PlanGraph P(params PlanNode[] nodes) => new("p", "agent", "user", nodes, 0);
        Assert.True(ContractValidation.Validate(P(N("a"), N("b", "a"), N("c", "b"))).Ok);
        Assert.Contains("unknown node", ContractValidation.Validate(P(N("a", "zzz"))).Reason, StringComparison.Ordinal);
        Assert.Contains("cycle", ContractValidation.Validate(P(N("a", "c"), N("b", "a"), N("c", "b"))).Reason, StringComparison.Ordinal);
        Assert.True(ContractValidation.Validate(P(N("a"), new PlanNode("undo", "action", "undo a", ["a"], ["a"]))).Ok);
    }

    private static CapabilityGrant Grant() => new("c1", new Grantee(AgentId: "agent"), "web.search", "public", "user", 10, "explicit-opt-in", [Src]);

    [Fact]
    public void Capability_grant_needs_source_consent_and_a_later_expiry()
    {
        Assert.True(ContractValidation.Validate(Grant()).Ok);
        Assert.False(ContractValidation.Validate(Grant() with { Source = [] }).Ok);
        Assert.False(ContractValidation.Validate(Grant() with { ConsentPolicy = "  " }).Ok);
        Assert.False(ContractValidation.Validate(Grant() with { ExpiresAt = 10 }).Ok);
    }

    private static ActionRecord Action() => new("r1", "agent", "user", "send", new Dictionary<string, object?>(), "ok", "evt-1", 1);

    [Fact]
    public void Action_record_is_traceable_to_an_episode_and_an_actor()
    {
        Assert.True(ContractValidation.Validate(Action()).Ok);
        Assert.False(ContractValidation.Validate(Action() with { EpisodeRef = "" }).Ok);
        Assert.False(ContractValidation.Validate(Action() with { AgentId = "", UserScope = "" }).Ok);
    }

    private static SemanticMotion Motion() => new("mo", "agent", "user", "s1", "s2", null, 0.3, "embedding", 1, [Src]);

    [Fact]
    public void Semantic_motion_is_non_trivial_non_negative_and_sourced()
    {
        Assert.True(ContractValidation.Validate(Motion()).Ok);
        Assert.False(ContractValidation.Validate(Motion() with { ToRef = "s1" }).Ok);
        Assert.False(ContractValidation.Validate(Motion() with { Magnitude = -0.1 }).Ok);
        Assert.False(ContractValidation.Validate(Motion() with { Source = [] }).Ok);
    }

    private static SkillPackage Skill() => new("sk", "sum", "1.2.3", "math.sum",
        new SkillManifest(new Dictionary<string, object?> { ["xs"] = "number[]" }, new Dictionary<string, object?> { ["sum"] = "number" }, "(xs)=>sum"),
        "skills/sum.js", "agent", [Src]);

    [Fact]
    public void Skill_package_has_semver_capability_manifest_and_source()
    {
        Assert.True(ContractValidation.Validate(Skill()).Ok);
        Assert.True(ContractValidation.Validate(Skill() with { Version = "1.0.0-rc.1+build.5" }).Ok);
        Assert.False(ContractValidation.Validate(Skill() with { Version = "v1" }).Ok);
        Assert.False(ContractValidation.Validate(Skill() with { CapabilityRef = "" }).Ok);
        Assert.False(ContractValidation.Validate(Skill() with { Manifest = new SkillManifest(null, null, "") }).Ok);
    }
}
