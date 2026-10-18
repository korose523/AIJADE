using System.Text.Json;

using Aijade.Memory;
using Aijade.Memory.Beliefs;
using Aijade.Memory.Contracts;
using Aijade.Memory.Hac;
using Aijade.Memory.Identity;
using Aijade.Memory.Model;
using Aijade.Memory.Storage;

namespace Aijade.Tests;

/// <summary>The integrated store must equal the recorded golden data.</summary>
public class StoreTests
{
    private static readonly JsonElement Golden =
        JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "store-golden.json"))).RootElement;

    private static readonly EpisodeContext NoTags = new(null, null, null, []);

    private static MemoryConfig LoopConfig() => MemoryConfig.Default with
    {
        Hac = HacConfig.Default with { Enabled = true },
        Cdi = CdiConfig.Default with { MinIndependentEpisodes = 1 },
    };

    private static HacState Z(double c) => new(0.5, 0.5, 0.5, 0.5, 0.5, c, 0.5);

    private static FeedbackEvent Feedback(string id = "f1") => new(id, "ag", "u", "s", "e1", "explicit", "rating", 1, Value: 4, Valence: 0.5);

    private static Appraisal Appraisal(AppraisalDimensions d) => new("a1", "e1", "ag", "u", d, 1, "agent", 0);

    [Fact]
    public void Integrated_store_matches_the_original()
    {
        var texts = Golden.GetProperty("texts").EnumerateArray().Select(t => t.GetString()!).ToArray();
        var m = new BioticMemory(LoopConfig(), 5000);
        for (var i = 0; i < texts.Length; i++)
            m.Encode(new EncodeInput($"e{i}", texts[i], i * 1000, new EpisodeContext(null, null, null, i % 2 == 1 ? ["work"] : [])));
        m.EncodeProcedural("to restart the server run the deploy script", contextTags: ["work"]);
        m.EncodeWorking("current task: fix the login bug");
        for (var i = 0; i < 5; i++)
            m.StepHac(Z(0.9), Z(0.2));
        m.StepHacAppraisal(Appraisal(new AppraisalDimensions(0.2, 0.8, 0.6, 0.4, -0.2, 0.7)));

        static void AssertRanking(JsonElement expected, IReadOnlyList<ScoredCandidate> actual)
        {
            Assert.Equal(expected.EnumerateArray().Select(c => (c.GetProperty("id").GetString(), c.GetProperty("kind").GetString())),
                actual.Select(c => ((string?)c.Id, (string?)Aijade.Core.Js.WireName.Of(c.Kind))));
            foreach (var (e, a) in expected.EnumerateArray().Zip(actual))
                Assert.Equal(e.GetProperty("score").GetDouble(), a.Score, 12);
        }
        AssertRanking(Golden.GetProperty("r1"), m.Retrieve("server crash login", 10, true));
        AssertRanking(Golden.GetProperty("r2"), m.Retrieve("deploy script restart", 5, false));
        var z = Golden.GetProperty("hac");
        Assert.Equal(new HacState(z.GetProperty("a").GetDouble(), z.GetProperty("v").GetDouble(), z.GetProperty("d").GetDouble(), z.GetProperty("n").GetDouble(),
            z.GetProperty("s").GetDouble(), z.GetProperty("c").GetDouble(), z.GetProperty("b").GetDouble()), m.HacState);
        Assert.Equal(Golden.GetProperty("hacSnapshotId").GetString(), m.HacSnapshot()!.Id);
        Assert.Equal(Golden.GetProperty("procedural")[0].GetProperty("accessCount").GetInt32(), m.Procedural[0].AccessCount);
        Assert.Equal(Golden.GetProperty("working")[0].GetProperty("id").GetString(), m.Working[0].Id);
        foreach (var (e, a) in Golden.GetProperty("episodes").EnumerateArray().Zip(m.Episodes))
        {
            Assert.Equal(e.GetProperty("accessCount").GetInt32(), a.AccessCount);
            Assert.Equal(e.GetProperty("durability").GetDouble(), a.Durability);
        }

        var (ok, belief, _) = m.ProposeBelief(new BeliefProposal("servers crash on fridays", ["e0", "e2"]));
        Assert.True(ok);
        m.ReviseBelief(belief!.Id, [new EvidenceEntry("e3", 0.9, 1.2)], [new EvidenceEntry("e5", 0.4, 0.7)], rationale: "r");
        m.RetractBelief(belief.Id, "superseded");
        Assert.False(m.ProposeBelief(new BeliefProposal("no source", [])).Ok);
        var b = Golden.GetProperty("beliefs")[0];
        Assert.Equal(b.GetProperty("id").GetString(), m.Beliefs[0].Id);
        Assert.Equal(b.GetProperty("logit").GetDouble(), m.Beliefs[0].Logit);
        Assert.Equal(b.GetProperty("supportLogit").GetDouble(), m.Beliefs[0].SupportLogit);
        Assert.Equal(b.GetProperty("counterLogit").GetDouble(), m.Beliefs[0].CounterLogit);
        Assert.Equal(BeliefStatus.Retracted, m.Beliefs[0].Status);
        Assert.Equal(Golden.GetProperty("revisions").EnumerateArray().Select(r => (r.GetProperty("id").GetString(), r.GetProperty("rationale").GetString())),
            m.BeliefRevisions.Select(r => ((string?)r.Id, (string?)r.Rationale)));
        Assert.Equal(Golden.GetProperty("rejections")[0].GetProperty("reason").GetString(), m.BeliefRejections[0].Reason);

        var cdi = m.CdiFromFeedback(Feedback(), new IdentityFeedbackOptions("ep1", IdentityLayer.Character, "curiosity", 0.1))!.Value;
        Assert.Equal(Golden.GetProperty("cdiSig").GetString(), cdi.Version!.Signature);
        Assert.Equal(Golden.GetProperty("curiosity").GetDouble(), m.CdiState!.Character["curiosity"]);
    }

    [Fact]
    public void Quantile_consolidation_matches_the_original()
    {
        var texts = Golden.GetProperty("texts").EnumerateArray().Select(t => t.GetString()!).ToArray();
        var m = new BioticMemory(MemoryConfig.Default with { ConsolidateThreshold = 3 }, 0);
        for (var i = 0; i < texts.Length; i++)
            m.Encode(new EncodeInput($"e{i}", texts[i], i, NoTags));
        var r = m.Consolidate(keepFraction: 0.5);
        var e = Golden.GetProperty("consolidated");
        Assert.Equal(e.GetProperty("consumed").EnumerateArray().Select(x => x.GetString()), r.Consumed);
        Assert.Equal(e.GetProperty("skipped").EnumerateArray().Select(x => (x.GetProperty("episodeIds")[0].GetString(), x.GetProperty("reason").GetString())),
            r.Skipped.Select(x => ((string?)x.EpisodeId, (string?)x.Reason)));
    }

    private const string High = "Caroline went to the LGBTQ support group yesterday with my sister";

    [Fact]
    public void Validity_status_and_conflict_rules()
    {
        var m = new BioticMemory(MemoryConfig.Default, 0);
        m.Encode(new EncodeInput("keep", High, 0, NoTags)).Status = MemoryStatus.Expired;
        Assert.DoesNotContain(m.Retrieve(High, 10, false), c => c.Id == "keep");
        var w = new BioticMemory(MemoryConfig.Default, 1000);
        w.Encode(new EncodeInput("keep", High, 100, NoTags)).ValidTime = new ValidTime(ValidUntil: 500);
        Assert.DoesNotContain(w.Retrieve(High, 10, false), c => c.Id == "keep");

        var c = new BioticMemory(MemoryConfig.Default with { ConflictPenalty = 1 }, 0);
        c.Encode(new EncodeInput("A", "Caroline likes Paris", 0, NoTags));
        c.Encode(new EncodeInput("B", "Caroline doesn't like Paris", 1000, NoTags, BaseStrength: 2));
        var aNoPenalty = c.Retrieve("Caroline Paris", 10, false).First(x => x.Id == "A");
        c.Config = c.Config with { ConflictPenalty = 0.5 };
        var withPenalty = c.Retrieve("Caroline Paris", 10, false);
        var a = withPenalty.First(x => x.Id == "A");
        var b = withPenalty.First(x => x.Id == "B");
        Assert.True(a.Parts.Conflict && !b.Parts.Conflict && b.Score > a.Score);
        Assert.Equal(aNoPenalty.Score * 0.5, a.Score, 9);
        Assert.Equal(2, c.Episodes.Count);
    }

    [Fact]
    public void Hac_is_opt_in_and_its_noise_grows_with_load()
    {
        var plain = new BioticMemory(MemoryConfig.Default, 0);
        Assert.Null(plain.HacState);
        Assert.Null(plain.HacSnapshot());
        plain.Encode(new EncodeInput("e1", "the server crashed", 0, NoTags));
        Assert.Equal(plain.Retrieve("server", 10, false)[0].Score, plain.Retrieve("server", 10, false)[0].Score);

        var config = MemoryConfig.Default with { Hac = HacConfig.Default with { Enabled = true } };
        var low = new BioticMemory(config, 0);
        var high = new BioticMemory(config, 0);
        foreach (var m in new[] { low, high })
        {
            m.Encode(new EncodeInput("e1", "the server crashed at 03:14", 0, NoTags));
            m.Encode(new EncodeInput("e2", "user reported a login bug", 0, NoTags));
        }
        for (var i = 0; i < 30; i++)
        {
            low.StepHac(Z(0), Z(0));
            high.StepHac(Z(1), Z(0));
        }
        static double Variance(BioticMemory m)
        {
            var scores = Enumerable.Range(0, 400).Select(_ => m.Retrieve("server crash")[0].Score).ToList();
            var mean = scores.Average();
            return scores.Average(x => (x - mean) * (x - mean));
        }
        var vLow = Variance(low);
        Assert.True(vLow > 0);
        Assert.True(Variance(high) > vLow);

        var on = new BioticMemory(config, 0);
        var before = on.HacState!.Value.A;
        on.StepHacAppraisal(Appraisal(new AppraisalDimensions(0, 1, 0.5, 0.5, 0, 0.5)));
        Assert.True(on.HacState!.Value.A > before);
        var snap = on.HacSnapshot()!;
        Assert.True(snap.Frozen);
        Assert.Equal("hac", snap.Source);
        Assert.Equal(on.HacState!.Value.A, snap.State.Arousal, 12);
    }

    [Fact]
    public void Cdi_is_part_of_the_opt_in_loop()
    {
        var plain = new BioticMemory(MemoryConfig.Default, 0);
        var opts = new IdentityFeedbackOptions("ep1", IdentityLayer.Character, "curiosity", 0.1);
        Assert.Null(plain.CdiState);
        Assert.Null(plain.CdiFromFeedback(Feedback(), opts));
        Assert.Null(plain.CdiObserveHac("ep1"));

        var m = new BioticMemory(LoopConfig(), 0);
        Assert.True(m.CdiFromFeedback(Feedback("f1"), opts)!.Value.Result.Ok);
        Assert.Equal(0.6, m.CdiState!.Character["curiosity"], 6);
        Assert.Single(m.CdiVersions!);
        Assert.Equal("fb_f2", m.CdiProposalFromFeedback(Feedback("f2"), opts with { EpisodeId = "ep2" })!.CandidateId);
        Assert.False(m.CdiFromFeedback(Feedback("f3"), opts with { Layer = IdentityLayer.Constitutional, ParamKey = "userConsent", ProposedBy = IdentitySource.Agent })!.Value.Result.Ok);

        m.StepHacAppraisal(Appraisal(new AppraisalDimensions(0, 1, 0.5, 0.5, 0, 0.5)));
        var ev = m.CdiObserveHac("ep1")!;
        Assert.Equal((IdentitySource.World, "observation", true), (ev.Source, ev.Kind, ev.Traceable));
    }

    [Fact]
    public void Storage_rehydrates_collections_hac_and_identity()
    {
        var adapter = new InMemoryStorageAdapter();
        var m1 = new BioticMemory(LoopConfig() with { Storage = adapter }, 0);
        m1.Encode(new EncodeInput("e1", "deadline tomorrow", 1, NoTags));
        m1.Encode(new EncodeInput("e2", "project kickoff", 2, NoTags));
        m1.EncodeProcedural("run the tests before merging");
        m1.ProposeBelief(new BeliefProposal("user cares about deadlines", ["e1", "e2"]));
        m1.ProposeBelief(new BeliefProposal("unsourced claim", []));
        m1.StepHac(Z(0.5), new HacState(0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.6));
        var opts = new IdentityFeedbackOptions("ep1", IdentityLayer.Character, "curiosity", 0.1);
        m1.CdiFromFeedback(Feedback("f1"), opts);
        m1.CdiFromFeedback(Feedback("f2"), opts with { EpisodeId = "ep2" });

        var m2 = new BioticMemory(LoopConfig() with { Storage = adapter }, 0);
        Assert.Equal(["e1", "e2"], m2.Episodes.Select(e => e.Id));
        Assert.Single(m2.Procedural);
        Assert.Equal(["user cares about deadlines"], m2.Beliefs.Select(b => b.Proposition));
        Assert.Single(m2.BeliefRejections);
        Assert.Equal(m1.HacState, m2.HacState);
        Assert.NotEqual(HacState.Uniform(0.5), m2.HacState);
        Assert.Equal(0.7, m2.CdiState!.Character["curiosity"], 6);
        Assert.Equal(2, m2.CdiVersions!.Count);
        // The restored store keeps working with the same results.
        Assert.Equal(m1.Retrieve("deadline", 5, false).Select(c => c.Id), m2.Retrieve("deadline", 5, false).Select(c => c.Id));
    }

    [Fact]
    public void Json_file_adapter_persists_and_clears()
    {
        var file = Path.Combine(Path.GetTempPath(), $"mem_snap_{Guid.NewGuid():N}.json");
        var adapter = new JsonFileStorageAdapter(file);
        try
        {
            new BioticMemory(MemoryConfig.Default with { Storage = adapter }, 0).Encode(new EncodeInput("e1", "persisted content", 1, NoTags));
            Assert.Equal(["e1"], new BioticMemory(MemoryConfig.Default with { Storage = adapter }, 0).Episodes.Select(e => e.Id));
            adapter.Clear();
            Assert.Empty(new BioticMemory(MemoryConfig.Default with { Storage = adapter }, 0).Episodes);
        }
        finally
        {
            File.Delete(file);
        }
    }
}

/// <summary>LLM distillation: line per episode, lexical fallback for missing lines and for model failures.</summary>
public class LlmDistillerTests
{
    private sealed class FakeLlm(Func<string, string> reply) : Aijade.Memory.ILlmClient
    {
        public string? LastPrompt { get; private set; }

        public Task<string> GenerateAsync(string prompt, double temperature, int? maxTokens = null, CancellationToken cancellationToken = default)
        {
            LastPrompt = prompt;
            return Task.FromResult(reply(prompt));
        }
    }

    private static BioticMemory Store()
    {
        var m = new BioticMemory(MemoryConfig.Default with { ConsolidateThreshold = 3, Gating = GatingCoefficients.None }, 0);
        string[] texts = ["Caroline joined a support group in May", "Melanie painted a sunrise", "we talked about the weather"];
        for (var i = 0; i < texts.Length; i++)
            m.Encode(new EncodeInput($"e{i}", texts[i], i, new EpisodeContext(null, null, null, [])));
        return m;
    }

    [Fact]
    public async Task Model_lines_replace_content_and_missing_lines_fall_back()
    {
        var llm = new FakeLlm(_ => "  Caroline joined a support group (May).\n\nMelanie painted a sunrise.\n");
        var r = await Store().ConsolidateAsync(new LlmDistiller(llm), cancellationToken: TestContext.Current.CancellationToken);
        Assert.Equal(["Caroline joined a support group (May).", "Melanie painted a sunrise.", "we talked about the weather"], r.Facts.Select(f => f.Content));
        Assert.Equal(["e0"], r.Facts[0].DerivedFrom);
        Assert.StartsWith("Distil the following", llm.LastPrompt, StringComparison.Ordinal);
        Assert.Contains("\n\n- Caroline joined a support group in May\n- Melanie", llm.LastPrompt, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Model_failure_or_empty_reply_keeps_the_lexical_facts()
    {
        var failing = new FakeLlm(_ => throw new InvalidOperationException("model down"));
        var r = await Store().ConsolidateAsync(new LlmDistiller(failing), cancellationToken: TestContext.Current.CancellationToken);
        Assert.Equal("Caroline joined a support group in May", r.Facts[0].Content);
        var empty = await Store().ConsolidateAsync(new LlmDistiller(new FakeLlm(_ => " \n ")), cancellationToken: TestContext.Current.CancellationToken);
        Assert.Equal(3, empty.Facts.Count);
        Assert.Equal("Melanie painted a sunrise", empty.Facts[1].Content);
    }
}
