using Aijade.Memory.Contracts;

namespace Aijade.Tests;

/// <summary>Behaviour of the v8 contracts.</summary>
public class ContractV8Tests
{
    private static InterestThread Thread() => new("t1", "agent", "user", "tea", ["evt-1"], ["why oolong?"], 0.6, 0.5, 0.7, 0.4, ["oxidation"], [],
        0.2, new Budget(60, 10, "minutes"), "active", 0);

    [Fact]
    public void Interest_thread_needs_history_bounded_values_budget_and_abandon_reason()
    {
        Assert.True(ContractValidationV8.Validate(Thread()).Ok);
        Assert.Contains("origin event", ContractValidationV8.Validate(Thread() with { OriginEventIds = [] }).Reason, StringComparison.Ordinal);
        Assert.False(ContractValidationV8.Validate(Thread() with { Progress = 1.1 }).Ok);
        Assert.False(ContractValidationV8.Validate(Thread() with { AttentionBudget = new Budget(10, 11, "minutes") }).Ok);
        Assert.Contains("abandonedReason", ContractValidationV8.Validate(Thread() with { Status = "abandoned" }).Reason, StringComparison.Ordinal);
        Assert.True(ContractValidationV8.Validate(Thread() with { Status = "abandoned", AbandonedReason = "saturated" }).Ok);
    }

    private static LearningQuest Quest() => new("q1", "agent", "user", "t1", "why oolong?", "compare oxidation ranges", [], 0.5,
        new SourcePlan("factual", ["paper"], 5), new Budget(20, 0, "queries"), "public", ["info gain < 0.05"], ["answered"], ["learning_note"],
        "exp-1", "active", 0);

    [Fact]
    public void Learning_quest_must_be_bounded_before_it_starts()
    {
        Assert.True(ContractValidationV8.Validate(Quest()).Ok);
        Assert.Contains("stop condition", ContractValidationV8.Validate(Quest() with { StopConditions = [] }).Reason, StringComparison.Ordinal);
        Assert.False(ContractValidationV8.Validate(Quest() with { ExpectedInformationGain = 2 }).Ok);
        Assert.False(ContractValidationV8.Validate(Quest() with { ExperimentManifestRef = " " }).Ok);
    }

    [Fact]
    public void Source_record_claim_map_and_artifact_keep_provenance()
    {
        var src = new SourceRecord("s", "https://x", "paper", new SourceQuality(0.9, 0.8, 0.7, 0.6, 0.5), [], "abc", 0);
        Assert.True(ContractValidationV8.Validate(src).Ok);
        Assert.False(ContractValidationV8.Validate(src with { ContentHash = "" }).Ok);
        var claims = new ClaimMap("c", "agent", "user", "q1", [new Claim("oolong is partly oxidised", "source_statement", ["s"], [], 0.8)], 0);
        Assert.True(ContractValidationV8.Validate(claims).Ok);
        Assert.False(ContractValidationV8.Validate(claims with { Claims = [new Claim("x", "source_statement", [], [], 0.8)] }).Ok);
        var art = new KnowledgeArtifact("k", "agent", "user", "learning_note", "q1", null, "dgm:1", [new SourceRef("s", true)], 0);
        Assert.True(ContractValidationV8.Validate(art).Ok);
        Assert.False(ContractValidationV8.Validate(art with { Sources = [] }).Ok);
        Assert.False(ContractValidationV8.Validate(art with { Kind = "tweet" }).Ok);
    }

    [Fact]
    public void Associations_keep_their_path_and_high_tier_transfers_are_validated()
    {
        var a = new AssociationPath("a", "agent", "user", "tea", "chemistry", "causal", ["oxidation is a reaction"], 0.4, [], 0);
        Assert.True(ContractValidationV8.Validate(a).Ok);
        Assert.Contains("pathless", ContractValidationV8.Validate(a with { Path = [] }).Reason, StringComparison.Ordinal);
        var t = new TransferRecord("tr", "agent", "user", "chess", "go", [], [], "", "", 0, "T2", false, 0);
        Assert.False(ContractValidationV8.Validate(t).Ok);
        Assert.True(ContractValidationV8.Validate(t with { Validated = true }).Ok);
        Assert.True(ContractValidationV8.Validate(t with { Tier = "T1" }).Ok);
    }

    [Fact]
    public void Journal_and_share_candidates_are_policy_bound()
    {
        var j = new LifeJournalEntry("j", "agent", "user", "2026-10-08", [], [], [], [], [], [], [], "diary_only", [], 0);
        Assert.True(ContractValidationV8.Validate(j).Ok);
        Assert.False(ContractValidationV8.Validate(j with { Date = "2026/10/08" }).Ok);
        Assert.False(ContractValidationV8.Validate(j with { SharePolicy = "broadcast" }).Ok);
        var s = new ShareCandidate("sc", "agent", "user", "j", new ShareUtility(0.5, 0.5, 0.5, 0.5, 0.1, 0.2, 0.1, 0), 0.3, "light_hint", 0);
        Assert.True(ContractValidationV8.Validate(s).Ok);
        Assert.False(ContractValidationV8.Validate(s with { Channel = "push" }).Ok);
        Assert.False(ContractValidationV8.Validate(s with { Utility = s.Utility with { PrivacyRisk = 2 } }).Ok);
    }

    private static EvolutionProposal Proposal() => new("p", "agent", ["timeouts"], ["planner"], "E2", "v1.0.0", "raise budget", "diff", "vse",
        [new ProposalTest("unit", true)], "revert to v1.0.0", "user-approve", "sig", 0);

    [Fact]
    public void Evolution_is_recoverable_tested_and_signed()
    {
        Assert.True(ContractValidationV8.Validate(Proposal()).Ok);
        Assert.Contains("rollback", ContractValidationV8.Validate(Proposal() with { RollbackPlan = "" }).Reason, StringComparison.Ordinal);
        Assert.False(ContractValidationV8.Validate(Proposal() with { Tests = [] }).Ok);
        Assert.False(ContractValidationV8.Validate(Proposal() with { Grade = "E9" }).Ok);
        var pack = new EvaluationEvidencePack("e", "p", new CoreTestGate(true, 10, 1), 0);
        Assert.Contains("failing", ContractValidationV8.Validate(pack).Reason, StringComparison.Ordinal);
        Assert.True(ContractValidationV8.Validate(pack with { UnitContractPropertyTests = new CoreTestGate(true, 10, 0) }).Ok);
        var rel = new SignedRelease("r", "1.1.0", "p", "e", "user", 0, "sig", 0.1, true);
        Assert.True(ContractValidationV8.Validate(rel).Ok);
        Assert.False(ContractValidationV8.Validate(rel with { RollbackAvailable = false }).Ok);
        Assert.False(ContractValidationV8.Validate(rel with { CanaryRatio = 1.5 }).Ok);
    }

    [Fact]
    public void Performance_intent_is_bounded_and_identity_anchored()
    {
        var i = new PerformanceIntent("pi", "agent", "user", "persona@3", 0, new ExpressionVector(-0.4, 0.5, 0.5, 0.6, 0.7, 0.8, 0.3, 0.2, 0.1), 800);
        Assert.True(ContractValidationV8.Validate(i).Ok);
        Assert.False(ContractValidationV8.Validate(i with { PersonaSnapshotRef = "" }).Ok);
        Assert.False(ContractValidationV8.Validate(i with { Expression = i.Expression with { Valence = -1.5 } }).Ok);
        Assert.False(ContractValidationV8.Validate(i with { Expression = i.Expression with { Curiosity = 1.2 } }).Ok);
        Assert.False(ContractValidationV8.Validate(i with { Duration = -1 }).Ok);
    }
}
