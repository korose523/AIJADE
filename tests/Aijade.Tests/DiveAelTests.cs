using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Memory.Contracts;
using Aijade.Memory.Development;
using Aijade.Memory.Kernel;

namespace Aijade.Tests;

/// <summary>DIVE and AEL must equal the recorded golden data.</summary>
public class DiveAelTests
{
    private static readonly JsonElement Golden =
        JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "dive-ael-golden.json"))).RootElement;

    private static InterestComponents Comp(double novelty = 0.5, double gap = 0.5, double identity = 0.5, double challenge = 0.5, double user = 0.5,
        double utility = 0.5, double cost = 0.5, double risk = 0.5, double repetition = 0.5) => new(novelty, gap, identity, challenge, user, utility, cost, risk, repetition);

    [Fact]
    public void Values_portfolios_and_clusters_match_the_original()
    {
        var comps = Golden.GetProperty("comps").EnumerateArray().Select(v => v.EnumerateArray().Select(x => x.GetDouble()).ToArray()).ToArray();
        Assert.Equal(Golden.GetProperty("iv").EnumerateArray().Select(x => x.GetDouble()),
            comps.Select(v => Dive.IntrinsicValue(new(v[0], v[1], v[2], v[3], v[4], v[5], v[6] * 0.3, v[7] * 0.2, v[8] * 0.2))));
        Assert.Equal(Golden.GetProperty("ec").EnumerateArray().Select(x => x.GetDouble()),
            comps.Select(v => Ael.EvidenceConfidence(new(v[0], v[1], v[2], v[3], v[4], v[5] * 0.5))));

        var cands = Golden.GetProperty("cands").EnumerateArray().Select(c => new PortfolioCandidate(c.GetProperty("id").GetString()!, c.GetProperty("subject").GetString()!,
            c.GetProperty("intrinsicValue").GetDouble(), c.GetProperty("identityRelevance").GetDouble(), c.GetProperty("userRelevance").GetDouble())).ToList();
        PortfolioSelection[] actual =
        [
            Dive.SelectPortfolio(cands, new PortfolioOptions(6, IdentityReserve: 0.5, ForbiddenSubjects: [" CRYPTO"])),
            Dive.SelectPortfolio(cands, new PortfolioOptions(20)),
            Dive.SelectPortfolio(cands, new PortfolioOptions(4, DiversityWeight: 0.05, RedundancyWeight: 0.01, IdentityReserve: 0)),
        ];
        foreach (var (e, a) in Golden.GetProperty("port").EnumerateArray().Zip(actual))
        {
            Assert.Equal(e.GetProperty("selected").EnumerateArray().Select(x => x.GetString()), a.Selected);
            Assert.Equal(e.GetProperty("identityReserved").EnumerateArray().Select(x => x.GetString()), a.IdentityReserved);
            Assert.Equal(e.GetProperty("forbidden").EnumerateArray().Select(x => x.GetString()), a.Forbidden);
        }

        SourceRecord[] sources = [Src("a", "h1"), Src("b", "h2", "x"), Src("c", "h3", "a"), Src("d", "h1"), Src("e", "h4", "y"), Src("f", "h5", "x", "y"), Src("g", "h6")];
        Assert.Equal(Golden.GetProperty("clusters").EnumerateArray().Select(c => c.EnumerateArray().Select(x => x.GetString()!).ToList()),
            Ael.SharedOriginClusters(sources).Select(c => c.ToList()));
    }

    [Fact]
    public void Lifecycle_events_are_byte_identical_to_the_original()
    {
        var quest = Quest() with { ResourceBudget = new Budget(10.5, 0, "queries"), StopConditions = ["信息增益低于阈值", "budget"] };
        Assert.Equal(Golden.GetProperty("requested").GetString(), JsFormat.Stringify(Ael.BuildActiveLearningRequestedEvent(quest, "session-1", Envelope())));
        Assert.Equal(Golden.GetProperty("completed").GetString(), JsFormat.Stringify(Ael.BuildActiveLearningCompletedEvent(quest, "session-1", Envelope(), "ka_1")));
    }

    private static SourceRecord Src(string id, string hash, params string[] upstream) =>
        new(id, id, "web", new SourceQuality(1, 1, 1, 1, 1), upstream, hash, 0);

    [Fact]
    public void Intrinsic_value_needs_both_attraction_and_inhibition()
    {
        var attractive = Dive.IntrinsicValue(Comp(0.4, 0.3, 0, 0, 0, 0, 0, 0, 0));
        var inhibited = Dive.IntrinsicValue(Comp(0.4, 0.3, 0, 0, 0, 0, 0.5, 0.5, 0));
        Assert.True(attractive > inhibited);
        Assert.Equal(0, inhibited);
        Assert.Equal(1, Dive.IntrinsicValue(Comp(1, 1, 1, 1, 1, 1, 0, 0, 0)));
        Assert.True(Dive.IntrinsicValue(Comp(0.6, 0.6, 0.6, 0.5, 0.5, 0.5, 0.2, 0.2, 0.2)) > Dive.IntrinsicValue(Comp(1, 0, 0, 0, 0, 0, 0.8, 0.8, 0.8)));
        var risky = Comp(risk: 1, cost: 0, repetition: 0);
        Assert.True(Dive.IntrinsicValue(risky, new InterestWeights(WRisk: 5)) < Dive.IntrinsicValue(risky, new InterestWeights(WRisk: 0.1)));
    }

    [Theory]
    [InlineData("active", InterestSignal.Seed, "latent")]
    [InlineData("latent", InterestSignal.Probe, "active")]
    [InlineData("active", InterestSignal.Deepen, "active")]
    [InlineData("incubating", InterestSignal.Revisit, "active")]
    [InlineData("active", InterestSignal.Incubate, "incubating")]
    [InlineData("latent", InterestSignal.Incubate, null)]
    [InlineData("active", InterestSignal.Satisfy, "satisfied")]
    [InlineData("incubating", InterestSignal.Saturate, "satisfied")]
    [InlineData("latent", InterestSignal.Satisfy, null)]
    [InlineData("incubating", InterestSignal.Abandon, "abandoned")]
    [InlineData("satisfied", InterestSignal.Abandon, null)]
    [InlineData("abandoned", InterestSignal.Probe, null)]
    public void Interest_lifecycle(string current, InterestSignal signal, string? expected) => Assert.Equal(expected, Dive.NextStatus(current, signal));

    private static PortfolioCandidate C(string id, string subject, double value, double identity = 0.3, double user = 0.7) => new(id, subject, value, identity, user);

    [Fact]
    public void Portfolio_respects_budget_forbidden_subjects_reserve_and_diversity()
    {
        Assert.True(Dive.SelectPortfolio([C("1", "a", 0.9), C("2", "b", 0.8), C("3", "c", 0.7)], new PortfolioOptions(2, IdentityReserve: 0)).Selected.Count <= 2);
        var f = Dive.SelectPortfolio([C("1", "crypto", 0.99), C("2", "bci", 0.5)], new PortfolioOptions(2, IdentityReserve: 0, ForbiddenSubjects: ["crypto"]));
        Assert.Equal(["1"], f.Forbidden);
        Assert.Equal(["2"], f.Selected);
        var r = Dive.SelectPortfolio([C("u1", "user-task", 0.9, 0.2, 0.9), C("id1", "agent-history", 0.5, 0.9, 0.1)], new PortfolioOptions(2, IdentityReserve: 0.5));
        Assert.Equal(["id1"], r.IdentityReserved);
        Assert.Equal(["id1", "u1"], r.Selected);
        var d = Dive.SelectPortfolio([C("1", "bci", 0.9), C("2", "bci", 0.85), C("3", "neuro", 0.8)], new PortfolioOptions(2, 0.5, 0.5, 0));
        Assert.Equal(["1", "3"], d.Selected);
    }

    [Fact]
    public void Quest_pipeline_runs_in_order_and_completes_after_reflect()
    {
        var s = new QuestState(QuestStage.Observe);
        int requested = 0, completed = 0;
        for (var guard = 0; guard < Ael.PipelineLength + 4; guard++)
        {
            var next = Ael.Transition(s, QuestEvent.Advance);
            if (Ael.ShouldRequestActiveLearning(s.Stage, next?.Stage))
                requested++;
            if (Ael.ShouldCompleteActiveLearning(s.Stage, next?.Stage))
                completed++;
            if (next is null)
                break;
            Assert.Equal(s.Stage + 1, next.Stage);
            s = next;
        }
        Assert.Equal(QuestStage.Reflect, s.Stage);
        Assert.Equal((1, 1), (requested, completed));
    }

    [Fact]
    public void Exceptional_states_resume_or_terminate()
    {
        var paused = Ael.Transition(new QuestState(QuestStage.Search), QuestEvent.Pause);
        Assert.Equal(new QuestState(QuestStage.Paused, QuestStage.Search), paused);
        Assert.Equal(new QuestState(QuestStage.Search), Ael.Transition(paused!, QuestEvent.Resume));
        var consent = Ael.Transition(new QuestState(QuestStage.Acquire), QuestEvent.NeedConsent)!;
        Assert.Equal(new QuestState(QuestStage.Acquire), Ael.Transition(consent, QuestEvent.GrantConsent));
        Assert.Null(Ael.Transition(new QuestState(QuestStage.Search), QuestEvent.GrantConsent));
        Assert.Null(Ael.Transition(new QuestState(QuestStage.Paused, QuestStage.Search), QuestEvent.GrantConsent));
        var contradicted = Ael.Transition(new QuestState(QuestStage.CrossValidate), QuestEvent.Contradict)!;
        Assert.Equal(new QuestState(QuestStage.CrossValidate), Ael.Transition(contradicted, QuestEvent.Resume));
        var failed = Ael.Transition(new QuestState(QuestStage.Search), QuestEvent.Fail)!;
        Assert.Null(Ael.Transition(failed, QuestEvent.Advance));
        Assert.Null(Ael.Transition(Ael.Transition(new QuestState(QuestStage.Search), QuestEvent.Abandon)!, QuestEvent.Resume));
        Assert.Null(Ael.Transition(new QuestState(QuestStage.Search), QuestEvent.Resume));
        Assert.Null(Ael.Transition(new QuestState(QuestStage.Paused, QuestStage.Search), QuestEvent.Advance));
        Assert.False(Ael.ShouldCompleteActiveLearning(QuestStage.Search, QuestStage.Failed));
        Assert.False(Ael.ShouldRequestActiveLearning(QuestStage.FormQuestion, QuestStage.ScopeAndBudget));
    }

    [Fact]
    public void Sources_quarantine_and_origins()
    {
        Assert.Contains("reproduction_code", Ael.PlanSources(QuestionType.Academic).SourceTypes);
        Assert.True(Ael.PlanSources(QuestionType.SubjectiveCulture) is { PreservePerspectives: true, CrossValidate: false });
        Assert.True(Ael.CanBeSystemInstruction(ContentOrigin.System));
        Assert.False(Ael.CanBeSystemInstruction(ContentOrigin.Web) || Ael.CanBeSystemInstruction(ContentOrigin.Model) || Ael.CanBeSystemInstruction(ContentOrigin.Tool));
        Assert.False(Ael.CanBeIndependentEvidence(ContentOrigin.Model, true));
        Assert.True(Ael.CanBeIndependentEvidence(ContentOrigin.Web, false));
        Assert.Equal(2, Ael.IndependentOriginCount([Src("a", "same"), Src("b", "same"), Src("c", "other")]));
        Assert.Equal(1, Ael.IndependentOriginCount([Src("a", "1", "root"), Src("b", "2", "root")]));
        Assert.Equal(0.9, Ael.EvidenceConfidence(new(1, 1, 1, 1, 1, 0)), 5);
        Assert.Equal(0, Ael.EvidenceConfidence(new(0, 0, 0, 0, 0, 1)));
    }

    private static LearningQuest Quest() => new("q1", "agent-1", "user-1", "it1", "PGC 消融是否改变 recall@K？", "同一语料下 K=10 的命中率差", [], 0.5,
        new SourcePlan("academic", ["paper"], 5), new Budget(10, 0, "queries"), "public", ["信息增益低于阈值"], ["结论可复现"], ["claim_map"], "em1", "active", 1);

    private static JsonObject Envelope() => new()
    {
        ["event_id"] = "evt_ael_1",
        ["trace_id"] = "tr_ael_1",
        ["correlation_id"] = "cor_ael_1",
        ["timestamp"] = 1_700_000_000_000,
        ["producer"] = "ael",
        ["origin_device"] = "test-device",
        ["privacy_level"] = 1,
        ["evidence_refs"] = new JsonArray(),
        ["causal_context_refs"] = new JsonArray("tr_ael_1"),
        ["risk_score"] = 0,
        ["idempotency_key"] = "idem_ael_1",
        ["replay_mode"] = "live",
        ["risk_level"] = "low",
    };

    [Fact]
    public void Lifecycle_events_validate_before_emitting()
    {
        var ev = Ael.BuildActiveLearningRequestedEvent(Quest(), "session-1", Envelope());
        Assert.True(AijadeEvents.IsValid(ev));
        Assert.Equal(1_700_000_000_000, ev["payload"]!["requested_at"]!.GetValue<long>());
        Assert.Contains("§48.2", Assert.Throws<ArgumentException>(() => Ael.BuildActiveLearningRequestedEvent(Quest() with { StopConditions = [] }, "s", Envelope())).Message, StringComparison.Ordinal);
        Assert.Contains("§48.2", Assert.Throws<ArgumentException>(() => Ael.BuildActiveLearningRequestedEvent(Quest() with { ResourceBudget = new Budget(5, 6, "queries") }, "s", Envelope())).Message, StringComparison.Ordinal);
        Assert.Contains("§48.2", Assert.Throws<ArgumentException>(() => Ael.BuildActiveLearningRequestedEvent(Quest() with { ExperimentManifestRef = "" }, "s", Envelope())).Message, StringComparison.Ordinal);
        var done = Ael.BuildActiveLearningCompletedEvent(Quest(), "session-1", Envelope());
        Assert.True(AijadeEvents.IsValid(done));
        Assert.False(((JsonObject)done["payload"]!).ContainsKey("result_ref"));
        Assert.Throws<EventValidationException>(() => Ael.BuildActiveLearningCompletedEvent(Quest(), "", Envelope()));
    }
}
