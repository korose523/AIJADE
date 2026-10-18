using System.Text.Json;

using Aijade.Core.Js;
using Aijade.Memory;
using Aijade.Memory.Experiments;
using Aijade.Memory.Interventions;
using Aijade.Memory.Model;

namespace Aijade.Tests;

/// <summary>Selections and reports must equal the recorded golden data.</summary>
public class FaultInjectionTests
{
    private static readonly JsonElement Golden =
        JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "fault-golden.json"))).RootElement;

    private static ScoredCandidate Cand(string id, CandidateKind kind = CandidateKind.Episode, string? content = null) =>
        new(kind, id, content ?? $"content-{id}", 1, new ScoreParts { Similarity = 1, Strength = 1, Recency = 1, Context = 1 });

    private static FaultInjectionConfig Cfg(FaultKind kind, double rate = 1, double seed = 0, string? target = null, double maxLatencyMs = 500) =>
        new(true, kind, rate, seed, target, maxLatencyMs);

    private static readonly ScoredCandidate[] GoldenCandidates = Golden.GetProperty("cands").EnumerateArray()
        .Select(c => Cand(c[1].GetString()!, c[0].GetString() == "fact" ? CandidateKind.Fact : CandidateKind.Episode, c[2].GetString()!)).ToArray();

    [Theory]
    [InlineData("drop", FaultKind.MessageDrop, 0.4, 11.0, null, 500.0)]
    [InlineData("dropTarget", FaultKind.MessageDrop, 0.9, 11.0, "m1", 500.0)]
    [InlineData("dup", FaultKind.DuplicateEvent, 0.4, 2.5, null, 500.0)]
    [InlineData("corrupt", FaultKind.ValueCorruption, 0.4, 11.0, null, 500.0)]
    [InlineData("latency", FaultKind.LatencyInjection, 0.4, 123456789.0, null, 900.0)]
    public void Matches_the_original_harness(string name, FaultKind kind, double rate, double seed, string? target, double maxLatencyMs)
    {
        var expected = Golden.GetProperty(name);
        var (output, report) = new FaultInjector(Cfg(kind, rate, seed, target, maxLatencyMs)).Apply(GoldenCandidates);
        Assert.Equal(expected.GetProperty("ids").EnumerateArray().Select(x => x.GetString()), output.Select(c => c.Id));
        // Compared as JSON text: the reversed payloads contain lone surrogates, which a JSON reader rejects.
        Assert.Equal(expected.GetProperty("contents").EnumerateArray().Select(x => x.GetRawText()), output.Select(c => JsFormat.JsonString(c.Content)));
        var r = expected.GetProperty("report");
        Assert.Equal(r.GetProperty("applied").GetInt32(), report.Applied);
        Assert.Equal(r.GetProperty("total").GetInt32(), report.Total);
        Assert.Equal(r.GetProperty("detail").GetString(), report.Detail);
        if (r.TryGetProperty("latencyMs", out var lat))
            Assert.Equal(lat.GetDouble(), report.LatencyMs);
    }

    [Fact]
    public void Rate_one_drops_everything_and_rate_zero_nothing()
    {
        ScoredCandidate[] cs = [Cand("a"), Cand("b"), Cand("c")];
        Assert.Empty(new FaultInjector(Cfg(FaultKind.MessageDrop)).Apply(cs).Candidates);
        Assert.Equal(3, new FaultInjector(Cfg(FaultKind.MessageDrop, rate: 0)).Apply(cs).Candidates.Count);
    }

    [Fact]
    public void Duplicates_corruption_and_latency_behave_as_declared()
    {
        ScoredCandidate[] cs = [Cand("a"), Cand("b")];
        var dup = new FaultInjector(Cfg(FaultKind.DuplicateEvent)).Apply(cs).Candidates;
        Assert.Equal(4, dup.Count);
        Assert.Matches("^a:dup:[0-9a-f]{8}$", dup[2].Id);
        Assert.Equal("a-tnetnoc", new FaultInjector(Cfg(FaultKind.ValueCorruption)).Apply(cs).Candidates[0].Content);
        var (same, report) = new FaultInjector(Cfg(FaultKind.LatencyInjection)).Apply(cs);
        Assert.Same(cs, same);
        Assert.InRange(report.LatencyMs!.Value, 0, 499);
    }

    [Fact]
    public void Component_crash_throws_naming_the_component()
    {
        var e = Assert.Throws<FaultInjectedException>(() => new FaultInjector(Cfg(FaultKind.ComponentCrash)).Apply([Cand("f", CandidateKind.Fact), Cand("e")]));
        Assert.Equal(CandidateKind.Episode, e.Component);
        Assert.Equal(1, e.Report.Applied);
        Assert.Contains("\"episode\" crashed", e.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Selection_is_deterministic_seeded_and_input_order_independent()
    {
        var cs = Enumerable.Range(0, 40).Select(i => Cand($"c{i}")).ToArray();
        var ids = (double seed, IEnumerable<ScoredCandidate> input) =>
            new FaultInjector(Cfg(FaultKind.MessageDrop, 0.5, seed)).Apply(input.ToList()).Candidates.Select(c => c.Id).Order(StringComparer.Ordinal).ToList();
        Assert.Equal(ids(1, cs), ids(1, cs));
        Assert.NotEqual(ids(1, cs), ids(2, cs));
        Assert.Equal(ids(1, cs), ids(1, cs.Reverse()));
    }

    private const string Query = "Caroline went to the support group with my sister";

    private static readonly string[] Items =
    [
        "Caroline went to the support group with my sister yesterday",
        "the weather was rainy and the dog barked at the mailman on tuesday",
        "we ordered takeout and watched a movie about the ocean and the stars",
        "my brother called to say the train was delayed by the snow storm",
    ];

    private static BioticMemory Store(FaultInjectionConfig? fault = null)
    {
        var m = new BioticMemory(MemoryConfig.Default with { FaultInjection = fault }, 0);
        for (var i = 0; i < Items.Length; i++)
            m.Encode(new EncodeInput($"e{i}", Items[i], 0, new EpisodeContext(null, null, null, [])));
        return m;
    }

    [Fact]
    public void Store_is_untouched_by_default_and_by_rate_zero()
    {
        var plain = Store();
        var baseline = plain.Retrieve(Query, 10, false).Select(c => c.Id).ToList();
        Assert.NotEmpty(baseline);
        Assert.Null(plain.LastFaultReport);
        var faulted = Store(Cfg(FaultKind.MessageDrop, rate: 0));
        Assert.Equal(baseline, faulted.Retrieve(Query, 10, false).Select(c => c.Id));
        Assert.Equal(0, faulted.LastFaultReport!.Applied);
    }

    [Fact]
    public void Store_fails_closed_on_component_crash_and_reports_faults()
    {
        var dropped = Store(Cfg(FaultKind.MessageDrop));
        Assert.Empty(dropped.Retrieve(Query, 10, false));
        Assert.Equal(Items.Length, dropped.LastFaultReport!.Applied);

        var crashed = Store(Cfg(FaultKind.ComponentCrash, target: "episode"));
        Assert.All(crashed.Retrieve(Query, 10, false), c => Assert.NotEqual(CandidateKind.Episode, c.Kind));
        Assert.Equal(CandidateKind.Episode, crashed.LastFaultReport!.CrashedComponent);
        Assert.Equal(Items.Length, crashed.LastFaultReport.Applied);

        var corrupted = Store(Cfg(FaultKind.ValueCorruption)).Retrieve(Query, 10, false);
        Assert.Equal(Items.Length, corrupted.Count);
        Assert.NotEqual(Items[0], corrupted[0].Content);
        Assert.Equal("e0", corrupted[0].Id);
    }

    [Fact]
    public void Registers_a_fault_scenario()
    {
        var path = Path.Combine(Path.GetTempPath(), $"aijade-registry-{Guid.NewGuid():N}.json");
        try
        {
            var manifest = FaultInjection.Register(Cfg(FaultKind.MessageDrop, 0.3, 5), new ExperimentRegistry(path));
            Assert.Equal("fault:message_drop", manifest.Id);
            var text = File.ReadAllText(path);
            Assert.Contains("\"target\": null", text, StringComparison.Ordinal);
            Assert.Contains("\"rate\": 0.3", text, StringComparison.Ordinal);
        }
        finally
        {
            File.Delete(path);
        }
    }
}
