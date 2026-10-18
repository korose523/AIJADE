using System.Text.Json.Nodes;

using Aijade.Memory;
using Aijade.Memory.Beliefs;
using Aijade.Memory.Experiments;
using Aijade.Memory.Interventions;
using Aijade.Memory.Model;
using Aijade.Memory.Replay;
using Aijade.Memory.Storage;

namespace Aijade.Tests;

/// <summary>Store-level interventions, CBR and the evidence fabric.</summary>
public class StoreResearchTests
{
    private static readonly EpisodeContext Calendar = new(null, null, null, ["calendar"]);

    private static InterventionPlan Plan(string id) => Interventions.BaselinePlans.First(p => p.Id == id);

    private static MemoryConfig InterventionConfig() => MemoryConfig.Default with { Intervention = new InterventionConfig(true) };

    private static Dictionary<string, double> State(double fill) => "avdnscb".ToDictionary(k => k.ToString(), _ => fill);

    private static ReplayBundle Bundle(string id = "b1") => new(id, ["e1", "e2"], State(0.2), ["m1"], "sha256:abc",
        new ModelManifest("qwythos:latest", new JsonObject { ["temperature"] = 0 }), ["retrieve", "answer"], [new JsonObject { ["ok"] = true }],
        [new SpeechEvent(0, "the answer is four")], [new SemanticMotion(0, "nod")], new UserFeedback(0.5, "F"), State(0.6));

    [Fact]
    public void Interventions_are_opt_in_and_drive_switch_queries()
    {
        var plain = new BioticMemory(MemoryConfig.Default, 0);
        Assert.Null(plain.InterventionFingerprint);
        Assert.Equal(Interventions.DefaultSwitches["long_term_memory"], plain.InterventionEnabled("long_term_memory"));
        Assert.Null(plain.ApplyIntervention(Plan("B0")));

        var m = new BioticMemory(InterventionConfig(), 0);
        Assert.Null(m.InterventionFingerprint);
        var (resolved, registered) = m.ApplyIntervention(Plan("B0"))!.Value;
        Assert.Null(registered);
        Assert.Equal(resolved.Fingerprint, m.InterventionFingerprint);
        Assert.False(m.InterventionEnabled("long_term_memory"));
        Assert.True(m.InterventionEnabled("salience_threshold"));
        m.ApplyIntervention(Plan("A1"));
        Assert.True(m.InterventionEnabled("long_term_memory") && m.InterventionEnabled("hac_state") && !m.InterventionEnabled("hac_random_write"));
        m.ApplyIntervention(Plan("B1"));
        Assert.Equal("window(8)", m.InterventionBypass("long_term_memory"));
    }

    [Fact]
    public void Interventions_persist_and_can_be_registered()
    {
        var adapter = new InMemoryStorageAdapter();
        var fp = new BioticMemory(InterventionConfig() with { Storage = adapter }, 0).ApplyIntervention(Plan("B0"))!.Value.Resolved.Fingerprint;
        var m2 = new BioticMemory(InterventionConfig() with { Storage = adapter }, 0);
        Assert.Equal(fp, m2.InterventionFingerprint);
        Assert.False(m2.InterventionEnabled("long_term_memory"));

        var path = Path.Combine(Path.GetTempPath(), $"aijade-registry-{Guid.NewGuid():N}.json");
        try
        {
            var r = new BioticMemory(InterventionConfig(), 0).ApplyIntervention(Plan("B0"), registry: new ExperimentRegistry(path))!.Value;
            Assert.Equal("intervention:B0", r.Registered!.Manifest.Id);
        }
        finally
        {
            File.Delete(path);
        }
    }

    [Fact]
    public void Cbr_logs_bundles_estimates_ite_and_persists()
    {
        var plain = new BioticMemory(MemoryConfig.Default, 0);
        Assert.Null(plain.CbrLogBundle(Bundle()));
        Assert.Empty(plain.CbrBundles);

        var config = MemoryConfig.Default with { Cbr = new CbrConfig(true) };
        var m = new BioticMemory(config, 0);
        Assert.True(m.CbrLogBundle(Bundle())!.Value.Ok);
        Assert.False(m.CbrLogBundle(Bundle())!.Value.Ok);
        Assert.False(m.CbrLogBundle(Bundle("b2") with { EventIds = [], StateAfter = State(0.1) })!.Value.Ok);
        Assert.Single(m.CbrBundles);
        Assert.Null(m.CbrGetBundle("missing"));
        m.CbrLogBundle(Bundle("b2"));
        var big = m.CbrEstimateIte(new Dictionary<string, double> { ["b1"] = 1, ["b2"] = 1 }, new Dictionary<string, double> { ["b1"] = 0, ["b2"] = 0 })!;
        Assert.True(big.N == 2 && big.Significant);
        Assert.Equal(1, big.Mean, 6);
        Assert.False(m.CbrEstimateIte(new Dictionary<string, double> { ["b1"] = 0.5, ["b2"] = 0.5 }, new Dictionary<string, double> { ["b1"] = 0.5, ["b2"] = 0.5 })!.Significant);

        var adapter = new InMemoryStorageAdapter();
        var m1 = new BioticMemory(config with { Storage = adapter }, 0);
        m1.CbrLogBundle(Bundle("b1"));
        m1.CbrLogBundle(Bundle("b2"));
        var m2 = new BioticMemory(config with { Storage = adapter }, 0);
        Assert.Equal(2, m2.CbrBundles.Count);
        Assert.Equal(0, m2.CbrGetBundle("b1")!.ModelManifest.Sampling["temperature"]!.GetValue<int>());
    }

    [Fact]
    public void Provenance_graph_traces_and_explains()
    {
        var mem = new BioticMemory(MemoryConfig.Default, 0);
        mem.Encode(new EncodeInput("e1", "deadline tomorrow", 1, Calendar));
        mem.Encode(new EncodeInput("e2", "project kickoff", 2, new EpisodeContext(null, null, null, ["work"])));
        var (_, belief, _) = mem.ProposeBelief(new BeliefProposal("user cares about deadlines", ["e1", "e2"]));
        mem.ReviseBelief(belief!.Id, [new EvidenceEntry("e2", 1, 0.5)]);
        mem.ProposeBelief(new BeliefProposal("unsourced", []));
        var g = Provenance.Build(mem);
        var node = g.Nodes.First(n => n.Kind == ProvenanceKind.Belief);
        Assert.Equal(["e1", "e2"], g.Edges.Where(e => e.From == node.Ref && e.Relation == "evidenced-by").Select(e => e.To).Distinct());
        Assert.Single(g.Edges, e => e.Relation == "revision-of");
        Assert.Contains(g.Nodes, n => n.Kind == ProvenanceKind.Rejection && n.Ref == "rej_0_0");
        Assert.Contains("e1", Provenance.Trace(g, node.Ref).Select(n => n.Ref));

        var simple = Assert.IsType<SimpleExplanation>(Provenance.Explain(belief.Id, false, mem));
        Assert.Contains("deadlines", simple.Text, StringComparison.Ordinal);
        var research = Assert.IsType<ResearchExplanation>(Provenance.Explain(belief.Id, true, mem));
        Assert.NotEmpty(research.Chain);
        Assert.Null(research.Scores);
        var scored = Assert.IsType<ResearchExplanation>(Provenance.Explain("e1", true, mem, "deadline"));
        Assert.True(scored.Scores!.Similarity >= 0);
        Assert.StartsWith("No provenance node", Assert.IsType<SimpleExplanation>(Provenance.Explain("nope", false, mem)).Text, StringComparison.Ordinal);
    }
}
