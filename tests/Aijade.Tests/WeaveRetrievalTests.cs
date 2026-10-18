using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Memory.Pgc;
using Aijade.Memory.V9;

namespace Aijade.Tests;

/// <summary>Weave graph hashes and retrieval gating must equal the recorded golden data.</summary>
public class WeaveRetrievalTests
{
    private static readonly JsonElement Golden =
        JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "weave-golden.json"))).RootElement;

    private static readonly JsonElement Pipeline =
        JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "pgc-tx-golden.json"))).RootElement;

    private static readonly WeaveSpec[] Specs = [new(true, false), new(false, true), new(true, true, "evo-1")];

    private static (MemoryTxEngine Engine, TxResult Result) Commit()
    {
        var decision = PgcTxTestsAccess.Decide(Pipeline, 3, "pgc_policy_v1");
        var engine = new MemoryTxEngine(time: new FixedTime(1_700_000_000_000));
        var r = engine.Commit(new MemoryTxInput("s1", "tw", decision.WritePlan, PgcTxTestsAccess.Payloads(Pipeline), new TxPolicy(TxAtomicity.PerWrite, 20)));
        return (engine, r);
    }

    [Fact]
    public void Weaves_and_their_event_match_the_original()
    {
        var (engine, r) = Commit();
        Assert.Equal(Golden.GetProperty("txId").GetString(), r.TxId);
        Assert.Equal(Golden.GetProperty("committed").GetInt32(), r.Committed.Count);
        var weaves = Specs.Select(s => EvidenceWeave.Build(engine, r.TxId, s)).ToList();
        foreach (var (e, w) in Golden.GetProperty("weaves").EnumerateArray().Zip(weaves))
        {
            Assert.Equal(e.GetProperty("graph_hash").GetString(), w.GraphHash);
            Assert.Equal(e.GetProperty("weave_id").GetString(), w.WeaveId);
            Assert.Equal(e.GetProperty("links").EnumerateArray().Select(l => (l.GetProperty("linkId").GetString(), l.TryGetProperty("hypothesisId", out var h) ? h.GetString() : null)),
                w.Links.Select(l => ((string?)l.LinkId, l.HypothesisId)));
        }
        var envelope = new JsonObject
        {
            ["event_id"] = "evt_w", ["trace_id"] = "tw", ["correlation_id"] = "tw", ["timestamp"] = 1_700_000_000_002, ["producer"] = "weave",
            ["origin_device"] = "dev", ["privacy_level"] = 0, ["evidence_refs"] = new JsonArray(), ["causal_context_refs"] = new JsonArray(),
            ["risk_score"] = 0, ["idempotency_key"] = "kw", ["replay_mode"] = "live", ["risk_level"] = "low",
        };
        Assert.Equal(Golden.GetProperty("event").GetString(), JsFormat.Stringify(EvidenceWeave.BuildCandidateReadyEvent(weaves[1], envelope)));
        Assert.NotEqual(weaves[0].GraphHash, weaves[1].GraphHash);
        Assert.Equal(weaves[0].GraphHash, EvidenceWeave.Build(engine, r.TxId, Specs[0]).GraphHash);
        Assert.Equal(weaves[0].GraphHash, EvidenceWeave.GraphHash(weaves[0].Links.Reverse(), Specs[0]));
    }

    [Fact]
    public void Retrieval_gating_matches_the_original()
    {
        Tau[] taus = [Tau.Episodic, Tau.Affective, Tau.Procedural, Tau.Semantic];
        uint[] seeds = [0, 1, 4294967295, 123456789];
        var expected = Golden.GetProperty("retrieval").EnumerateArray().ToArray();
        for (var i = 0; i < 4; i++)
        {
            var state = new PgcState4(0.3 * i, 0.9 - (0.2 * i), 0.5, 0.1);
            var actual = PgcRetrieval.GateBatch($"q{i}", taus[i], state, seeds[i], [("m1", 0.8), ("m2", 0.123)]);
            foreach (var (e, a) in expected[i].EnumerateArray().Zip(actual))
            {
                Assert.Equal(e.GetProperty("gated_score").GetDouble(), a.GatedScore);
                Assert.Equal(e.GetProperty("noise").GetDouble(), a.Noise);
                Assert.Equal(e.GetProperty("sigma").GetDouble(), a.Sigma);
                Assert.Equal(e.GetProperty("amplification_factor").GetDouble(), a.AmplificationFactor);
                Assert.True(a.RandomSeedRecorded);
            }
        }
    }
}
