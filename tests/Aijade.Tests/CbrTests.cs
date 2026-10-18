using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Memory.Lexical;
using Aijade.Memory.Replay;

namespace Aijade.Tests;

/// <summary>ITE statistics and token F1 must equal the recorded golden data; behaviour of case-based replay.</summary>
public class CbrTests
{
    private static readonly JsonElement Golden =
        JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "cbr-golden.json"))).RootElement;

    private static Dictionary<string, double> State(double fill) => "avdnscb".ToDictionary(k => k.ToString(), _ => fill);

    private static ReplayBundle Bundle(string id = "b1", IReadOnlyList<string>? events = null, IReadOnlyList<string>? memories = null) => new(
        id, events ?? ["e1", "e2"], State(0.2), memories ?? ["m1"], "sha256:abc", new ModelManifest("qwythos:latest", new JsonObject { ["temperature"] = 0 }),
        ["retrieve", "answer"], [new JsonObject { ["ok"] = true }], [new SpeechEvent(0, "the answer is four")], [new SemanticMotion(0, "nod")],
        new UserFeedback(0.5, "F"), State(0.6));

    [Fact]
    public void Ite_and_token_f1_match_the_original()
    {
        var pairs = Golden.GetProperty("pairs").EnumerateArray()
            .Select(p => new ItePair(p.GetProperty("bundleId").GetString()!, p.GetProperty("treated").GetDouble(), p.GetProperty("control").GetDouble())).ToList();
        var e = Cbr.EstimateIte(pairs);
        var g = Golden.GetProperty("ite");
        Assert.Equal(g.GetProperty("n").GetInt32(), e.N);
        Assert.Equal(g.GetProperty("mean").GetDouble(), e.Mean);
        Assert.Equal(g.GetProperty("sd").GetDouble(), e.Sd);
        Assert.Equal(g.GetProperty("se").GetDouble(), e.Se);
        Assert.Equal(g.GetProperty("lo").GetDouble(), e.CiLow);
        Assert.Equal(g.GetProperty("hi").GetDouble(), e.CiHigh);
        Assert.Equal(g.GetProperty("significant").GetBoolean(), e.Significant);
        string[][] f1Cases = [["the answer is four", "four is the answer, surely"], ["Caroline painted a sunrise in 2022", "caroline painted the sunrise"], ["", ""], ["dogs", ""]];
        Assert.Equal(Golden.GetProperty("f1").EnumerateArray().Select(x => x.GetDouble()), f1Cases.Select(c => Tokenizer.TokenF1(c[0], c[1])));
    }

    [Fact]
    public void Validation_enforces_the_replayability_invariants()
    {
        Assert.True(Cbr.Validate(Bundle()).Ok);
        Assert.False(Cbr.Validate(Bundle() with { Schema = "x@1" }).Ok);
        Assert.Contains("≥1 event_id", Cbr.Validate(Bundle(events: [])).Reason, StringComparison.Ordinal);
        Assert.Contains("prompt_digest", Cbr.Validate(Bundle() with { PromptDigest = "" }).Reason, StringComparison.Ordinal);
        Assert.Contains("model_manifest.model", Cbr.Validate(Bundle() with { ModelManifest = new ModelManifest("", []) }).Reason, StringComparison.Ordinal);
        Assert.Contains("same key set", Cbr.Validate(Bundle() with { StateAfter = new Dictionary<string, double> { ["a"] = 1 } }).Reason, StringComparison.Ordinal);
        Assert.Contains("valence", Cbr.Validate(Bundle() with { UserFeedback = new UserFeedback(1.5, "F") }).Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Intervention_is_pure_and_keeps_the_pair_matchable()
    {
        var b = Bundle();
        var i = Cbr.Intervene(b, new ReplayIntervention(StateBefore: State(0.9), MemoryIdsRetrieved: ["m9"], ModelManifest: new ModelManifest("other", [])));
        Assert.Equal(b.BundleId, i.BundleId);
        Assert.Equal(b.EventIds, i.EventIds);
        Assert.Equal(0.9, i.StateBefore["a"]);
        Assert.Equal(["m9"], i.MemoryIdsRetrieved);
        Assert.Equal("other", i.ModelManifest.Model);
        Assert.Equal(0.2, b.StateBefore["a"]);
        Assert.Equal(["m1"], b.MemoryIdsRetrieved);
        var copy = Cbr.Intervene(b, new ReplayIntervention());
        copy.ModelManifest.Sampling["temperature"] = 1;
        Assert.Equal(0, b.ModelManifest.Sampling["temperature"]!.GetValue<int>());
    }

    [Fact]
    public void Consistency_is_one_for_identical_zero_for_disjoint_and_symmetric()
    {
        var b = Bundle();
        Assert.Equal(new ReplayConsistency(1, 1, 1), Cbr.Consistency(b, b));
        var other = b with { SpeechTimeline = [new SpeechEvent(0, "completely unrelated words")], SemanticMotion = [new SemanticMotion(0, "frown")] };
        Assert.Equal(new ReplayConsistency(0, 0, 0), Cbr.Consistency(b, other));
        var partial = b with { SpeechTimeline = [new SpeechEvent(0, "the answer is five")], SemanticMotion = [new SemanticMotion(0, "nod"), new SemanticMotion(1, "smile")] };
        var ab = Cbr.Consistency(b, partial);
        Assert.Equal(ab, Cbr.Consistency(partial, b));
        Assert.Equal(0.5, ab.Motion);
        Assert.InRange(ab.Overall, 0, 1);
    }

    [Fact]
    public void Pairing_requires_identical_events_and_reports_unmatched()
    {
        ReplayRun[] treated = [new(Bundle("b1"), 0.8), new(Bundle("b2"), 0.7), new(Bundle("b3"), 0.9)];
        ReplayRun[] control = [new(Bundle("b1"), 0.6), new(Bundle("b2", events: ["e1", "eX"]), 0.6)];
        var r = Cbr.Pair(treated, control);
        Assert.Single(r.Pairs);
        Assert.Equal(["b2", "b3"], r.Unmatched);
        Assert.Equal(1.0 / 3, r.PairingRate);
        Assert.Equal(0, Cbr.Pair([], control).PairingRate);
    }

    [Fact]
    public void Paired_replay_supports_or_falsifies_the_causal_claim()
    {
        static ReplayRun Mk(int i, bool gateOn, double on, double off) =>
            new(Bundle($"b{i}", memories: gateOn ? [$"m{i}"] : [$"m{i}", $"noise{i}"]), gateOn ? on : off);
        var effect = Cbr.EstimateIte(Cbr.Pair([.. Enumerable.Range(1, 4).Select(i => Mk(i, true, 0.8, 0.6))], [.. Enumerable.Range(1, 4).Select(i => Mk(i, false, 0.8, 0.6))]).Pairs);
        Assert.Equal(4, effect.N);
        Assert.Equal(0.2, effect.Mean, 10);
        Assert.True(effect.Significant);
        Assert.True(effect.CiLow > 0);
        var none = Cbr.EstimateIte(Cbr.Pair([Mk(1, true, 0.7, 0.7), Mk(2, true, 0.7, 0.7)], [Mk(1, false, 0.7, 0.7), Mk(2, false, 0.7, 0.7)]).Pairs);
        Assert.Equal(0, none.Mean);
        Assert.False(none.Significant);
        var empty = Cbr.EstimateIte([]);
        Assert.Equal(0, empty.N);
        Assert.False(empty.Significant);
    }

    [Fact]
    public void Replay_log_is_append_only()
    {
        var log = new ReplayLog();
        Assert.True(log.Add(Bundle()).Ok);
        Assert.False(log.Add(Bundle(events: [])).Ok);
        Assert.Contains("append-only", log.Add(Bundle() with { PromptDigest = "sha256:changed" }).Reason, StringComparison.Ordinal);
        Assert.Equal("sha256:abc", log.Get("b1")!.PromptDigest);
        Assert.Equal(1, log.Count);
    }
}
