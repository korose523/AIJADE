using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Memory.Pgc;
using Aijade.Memory.V9;

namespace Aijade.Tests;

/// <summary>The v9 causal runtime must equal the recorded golden data across perception, learning and video inputs.</summary>
public class V9RuntimeTests
{
    private static readonly JsonElement Golden =
        JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "v9-runtime-golden.json"))).RootElement;

    private static JsonObject Input(string name) => (JsonObject)JsonNode.Parse(Golden.GetProperty("input").GetProperty(name).GetRawText())!;

    private static readonly double[] Risks = [0.1, 0.5, 0.8, 0.2, 0.9, 0.36];

    private static (string EventId, string SessionId, string TraceId, string CorrelationId, double Timestamp, string OriginDevice, int Privacy, double Risk) Base(int i) =>
        ($"ev{i}", "s1", $"tr{i}", $"co{i}", 1_700_000_001_000 + i, "phone", 1, Risks[i]);

    private static async Task<Dictionary<string, V9RuntimeResult>> RunAll(V9CausalRuntime rt)
    {
        var ct = TestContext.Current.CancellationToken;
        var r = new Dictionary<string, V9RuntimeResult>();
        var b = Base(0);
        r["p0"] = await rt.ProcessPerceptionAsync(new(b.EventId, b.SessionId, b.TraceId, b.CorrelationId, b.Timestamp, b.OriginDevice, b.Privacy, b.Risk,
            "chat", "Caroline told me about the support group she joined last week"), ct);
        b = Base(1);
        r["p1"] = await rt.ProcessPerceptionAsync(new(b.EventId, b.SessionId, b.TraceId, b.CorrelationId, b.Timestamp, b.OriginDevice, b.Privacy, b.Risk,
            "mic", new string('x', 900), new Dictionary<StimulusFeature, double> { [StimulusFeature.SkillNeedScore] = 0.8, [StimulusFeature.StimFatigueScore] = 0.6 }, "medium"), ct);
        b = Base(2);
        r["l2"] = await rt.ProcessLearningAsync(new(b.EventId, b.SessionId, b.TraceId, b.CorrelationId, b.Timestamp, b.OriginDevice, b.Privacy, b.Risk, 7, "hh7", Input("sp")), ct);
        b = Base(3);
        r["l3"] = await rt.ProcessLearningAsync(new(b.EventId, b.SessionId, b.TraceId, b.CorrelationId, b.Timestamp, b.OriginDevice, b.Privacy, b.Risk, 8, "hh8", Input("evd")), ct);
        b = Base(4);
        r["v4"] = await rt.ProcessVideoObservationAsync(new(b.EventId, b.SessionId, b.TraceId, b.CorrelationId, b.Timestamp, b.OriginDevice, b.Privacy, b.Risk, 9, "hh9", "pr3",
            Input("web"), "rr", "ap", "av"), ct);
        b = Base(5);
        r["v5"] = await rt.ProcessVideoObservationAsync(new(b.EventId, b.SessionId, b.TraceId, b.CorrelationId, b.Timestamp, b.OriginDevice, b.Privacy, b.Risk, 10, "hh10", "pr4",
            Input("sub"), "rr", "ap", "av"), ct);
        return r;
    }

    [Fact]
    public async Task Runtime_artifacts_match_the_original()
    {
        var store = new InMemoryV9RuntimeStore();
        var results = await RunAll(new V9CausalRuntime(store, time: new FixedTime(1_700_000_000_000)));
        var outs = Golden.GetProperty("out");
        foreach (var (key, result) in results)
        {
            var e = outs.GetProperty(key);
            var a = result.Artifact;
            Assert.Equal(Golden.GetProperty("out").GetProperty("events").GetProperty(key).EnumerateArray().Select(x => x.GetString()), a.Events.Select(x => JsFormat.Stringify(x)));
            var s = e.GetProperty("pgcState").GetProperty("v6State");
            Assert.Equal(new PgcState4(s.GetProperty("a").GetDouble(), s.GetProperty("c").GetDouble(), s.GetProperty("d").GetDouble(), s.GetProperty("f").GetDouble()), a.PgcState.V6State);
            Assert.Equal(e.GetProperty("pgcWritePlan").GetProperty("writePlan")[0].GetProperty("pgcStateSnapshot").GetRawText(),
                JsFormat.Stringify(PgcJson.Snapshot(a.PgcWritePlan.WritePlan[0].PgcStateSnapshot)));
            Assert.Equal(e.GetProperty("memoryTx").GetProperty("status").GetString(), WireName.Of(a.MemoryTx.Status));
            Assert.Equal(e.GetProperty("memoryVersions").EnumerateArray().Select(v => v.GetProperty("contentHashSha256").GetString()), a.MemoryVersions.Select(v => v.ContentHashSha256));
            Assert.Equal(e.GetProperty("evidenceWeave").GetProperty("graphHash").GetString(), a.EvidenceWeave.GraphHash);
            Assert.Equal(e.GetProperty("evidencePack").GetProperty("note").GetString(), a.EvidencePack.Note);
            Assert.Equal(e.GetProperty("evidenceChunk").GetProperty("content").GetString(), a.EvidenceChunk.Content);
        }
        var l2 = outs.GetProperty("l2p");
        Assert.Equal(l2.GetProperty("inputHash").GetString(), results["l2"].Proposal!.InputHash);
        Assert.True(results["l2"].Proposal!.AnchorVerified);
        Assert.Equal(outs.GetProperty("l3p").GetProperty("inputHash").GetString(), results["l3"].Proposal!.InputHash);
        Assert.False(results["l3"].Proposal!.AnchorVerified);
        Assert.All(results.Values.Where(r => r.Proposal is not null), r => Assert.True(ShadowParams.VerifyAnchor(r.Proposal!).Ok));
        Assert.Equal(6, store.Artifacts.Count);
    }

    [Fact]
    public async Task Forged_input_hash_is_rejected_before_anything_is_stored()
    {
        var store = new InMemoryV9RuntimeStore();
        var rt = new V9CausalRuntime(store, time: new FixedTime(1_700_000_000_000));
        var forged = Input("sp");
        forged["payload"]!["input_hash"] = "forged";
        var b = Base(2);
        var e = await Assert.ThrowsAsync<ShadowParamsIntegrityException>(() =>
            rt.ProcessLearningAsync(new("bad", b.SessionId, b.TraceId, b.CorrelationId, b.Timestamp, b.OriginDevice, b.Privacy, b.Risk, 1, "x", forged), TestContext.Current.CancellationToken));
        Assert.Equal(Golden.GetProperty("out").GetProperty("integrity").GetString(), e.Message);
        Assert.Empty(store.Artifacts);
    }

    [Fact]
    public void Tampered_proposals_fail_anchor_verification_and_video_needs_real_refs()
    {
        var p = ShadowParams.FromEvent(Input("sp"));
        Assert.True(ShadowParams.VerifyAnchor(p).Ok);
        Assert.False(ShadowParams.VerifyAnchor(p with { Confidence = 0.1, CandidateParams = new JsonObject { ["x"] = 1 } }).Ok);
        var ev = ShadowParams.FromEvent(Input("evd"));
        Assert.False(ShadowParams.VerifyAnchor(ev with { ClaimText = null }).Ok);
        Assert.False(ShadowParams.VerifyAnchor(ev with { ClaimText = "edited" }).Ok);
        var candidate = VideoObservation.FromWebpage((JsonObject)Input("web")["payload"]!);
        Assert.Equal(0.7, candidate.Confidence, 12);
        Assert.Throws<ArgumentException>(() => VideoObservation.ToEventPayload(candidate, "s", "p", null, "a", "b"));
        Assert.Throws<ArgumentException>(() => VideoObservation.FromWebpage(new JsonObject { ["observation_text"] = " ", ["content_hash"] = "h", ["spans"] = new JsonArray(1) }));
        Assert.Throws<ShadowParamsIntegrityException>(() => ShadowParams.FromEvent(new JsonObject { ["topic"] = "aijade.other", ["payload"] = new JsonObject() }));
    }
}
