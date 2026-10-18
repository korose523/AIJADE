using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Research.Telemetry;

namespace Aijade.Tests;

/// <summary>Telemetry must equal the recorded golden data.</summary>
public class TelemetryTests
{
    private static readonly JsonElement Golden =
        JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "telemetry-golden.json"))).RootElement;

    private static OrderedDictionary<string, double>? Map(JsonElement p, string name) => p.TryGetProperty(name, out var o)
        ? new OrderedDictionary<string, double>(o.EnumerateObject().Select(kv => KeyValuePair.Create(kv.Name, kv.Value.GetDouble())))
        : null;

    private static double? D(JsonElement p, string name) => p.TryGetProperty(name, out var v) ? v.GetDouble() : null;

    private static DynamicsParameters Params(JsonElement p) =>
        new(D(p, "relaxationMs"), Map(p, "baseline"), Map(p, "hormoneCoupling"), D(p, "noiseSigma"), D(p, "tickIntervalMs"), D(p, "interactionGain"));

    [Fact]
    public void Fingerprints_sweeps_and_ablations_match_the_original()
    {
        var applied = Golden.GetProperty("applied").EnumerateObject().Select(kv => KeyValuePair.Create(kv.Name, (JsonValue)JsonNode.Parse(kv.Value.GetRawText())!));
        Assert.Equal(Golden.GetProperty("fp1").GetString(), Fingerprints.AppliedParams(applied));
        Assert.Equal(Golden.GetProperty("fps").EnumerateArray().Select(x => x.GetString()), Golden.GetProperty("params").EnumerateArray().Select(p => Fingerprints.Parameters(Params(p))));
        Assert.Equal(Golden.GetProperty("grid").EnumerateArray().Select(x => x.GetString()),
            Sweeps.Grid([(SweepAxis.RelaxationMs, [100, 250.5]), (SweepAxis.NoiseSigma, [0.01, 1.0 / 3])], new DynamicsParameters(InteractionGain: 2)).Select(p => p.Name));
        Assert.Equal(Golden.GetProperty("relax").EnumerateArray().Select(x => (x[0].GetString(), x[1].GetDouble())),
            Sweeps.DefaultRelaxation(1000).Select(p => ((string?)p.Name, p.Parameters.RelaxationMs!.Value)));
        Assert.Equal(Golden.GetProperty("cfgFp").EnumerateArray().Select(x => (x[0].GetString(), x[1].GetString(), x[2].GetString())),
            Ablations.DefaultConditions.Select(c => ((string?)c.Name, (string?)Fingerprints.Config(c.Config), (string?)Ablations.Describe(c.Config))));
        var env = Ablations.FromEnv(new Dictionary<string, string?> { ["AIJADE_ABLATION_SKILL_FORGE"] = " Off ", ["AIJADE_ABLATION_MEMORY_RETRIEVAL"] = "YES", ["AIJADE_ABLATION_PERSONA_DYNAMICS"] = "" });
        var e = Golden.GetProperty("env");
        Assert.Equal(new AblationConfig(e.GetProperty("personaDynamics").GetBoolean(), e.GetProperty("hormoneCoupling").GetBoolean(), e.GetProperty("memoryRetrieval").GetBoolean(),
            e.GetProperty("skillForge").GetBoolean(), e.GetProperty("discourseMemory").GetBoolean()), env);
        var r = Fingerprints.BuildRenderAuditEntry(new RenderAuditEntry("s", 1, 1, "w", "mmd", "m", "h", "",
            new OrderedDictionary<string, JsonValue> { ["mouth"] = JsonValue.Create(0.5), ["blink"] = JsonValue.Create(true), ["expr"] = JsonValue.Create("smile") }));
        Assert.Equal(Golden.GetProperty("render").GetProperty("appliedParamsHash").GetString(), r.AppliedParamsHash);
    }

    private static PersonaSnapshot Persona(double warmth) => new(
        new PersonaVectorSnapshot(0.5, warmth, 0.7, 0.4, 0.3, 0.2, 0.1, 0.9, 0.8, 0.35, 0.45, 0.55, 0.65),
        new EndocrineSnapshot(0.1, 0.2, 0.3, 0.4, 0.5), new PadSnapshot(-0.2, 0.3, 0.1), new BigFiveSnapshot(0.1, 0.2, 0.3, 0.4, 0.5),
        new IntimacySnapshot(0.1, 0.2, 0.3, 0.4, 0.5, 0.6), "calm, \"ok\"\nnext");

    private static async Task<(ExperimentSessionRunner Runner, IReadOnlyList<TurnRecord> Turns, ExperimentSession Closed)> RunSession(ITelemetryStorage storage)
    {
        var ct = TestContext.Current.CancellationToken;
        double t = 1_700_000_000_000;
        var parameters = Params(Golden.GetProperty("params")[1]);
        var runner = await ExperimentSessionRunner.StartAsync(new ExperimentSessionRunner("no-hormone-coupling", participantId: "p1", parameters: parameters, storage: storage, sessionId: "sess-1", now: () => t++), ct);
        await runner.RecordTurnAsync(new RecordTurnInput(TurnRole.User) { TextLength = 12, Latency = new LatencyBreakdown(Llm: 120.5, Total: 300), Metadata = new JsonObject { ["k"] = 1 } }, ct);
        await runner.RecordTurnAsync(new RecordTurnInput(TurnRole.Assistant) { Persona = Persona(0.6), SkillLibrarySize = 3, Tokens = new TokenUsage(10, 20), MemoryHits = 2 }, ct);
        await runner.RecordTurnAsync(new RecordTurnInput(TurnRole.Assistant) { Persona = Persona(0.9), Parameters = new DynamicsParameters(NoiseSigma: 0.5) }, ct);
        var closed = await runner.CloseAsync(ct);
        return (runner, await storage.ReadTurnsAsync("sess-1", ct), closed);
    }

    private static string Canonical(string jsonl) => string.Join("\n", jsonl.Split('\n', StringSplitOptions.RemoveEmptyEntries).Select(l => JsFormat.CanonicalJson(JsonNode.Parse(l))));

    [Fact]
    public async Task Session_export_and_summary_match_the_original()
    {
        var (runner, turns, closed) = await RunSession(new MemoryTelemetryStorage());
        Assert.Equal(Canonical(Golden.GetProperty("jsonl").GetString()!), Canonical(TelemetryExport.ToJsonl(turns)));
        Assert.Equal(Golden.GetProperty("csv").GetString(), TelemetryExport.ToCsv(turns));
        var c = Golden.GetProperty("closed");
        Assert.Equal((c.GetProperty("configFingerprint").GetString(), c.GetProperty("parameterFingerprint").GetString(), c.GetProperty("turnCount").GetInt32(), c.GetProperty("endedAt").GetDouble()),
            ((string?)closed.Meta.ConfigFingerprint, closed.Meta.ParameterFingerprint, closed.TurnCount, closed.EndedAt));
        Assert.False(runner.IsEnabled("hormoneCoupling"));
        await Assert.ThrowsAsync<InvalidOperationException>(() => runner.RecordTurnAsync(new RecordTurnInput(TurnRole.User), TestContext.Current.CancellationToken));

        var (columns, drift) = TelemetryExport.Summarize(turns);
        var s = Golden.GetProperty("summary");
        foreach (var col in s.GetProperty("columns").EnumerateObject())
        {
            var a = columns[col.Name];
            static double N(JsonElement e) => e.ValueKind == JsonValueKind.String ? double.NaN : e.GetDouble();
            Assert.Equal((col.Value.GetProperty("count").GetInt32(), N(col.Value.GetProperty("min")), N(col.Value.GetProperty("max")), N(col.Value.GetProperty("mean")), N(col.Value.GetProperty("sd"))),
                (a.Count, a.Min, a.Max, a.Mean, a.Sd));
        }
        Assert.Equal(s.GetProperty("drift").EnumerateObject().Select(kv => (kv.Name, kv.Value.GetDouble())).OrderBy(x => x.Name, StringComparer.Ordinal),
            drift.Select(kv => (kv.Key, kv.Value)).OrderBy(x => x.Key, StringComparer.Ordinal));
    }

    [Fact]
    public async Task File_storage_round_trips_the_original_format()
    {
        var dir = Path.Combine(Path.GetTempPath(), $"telemetry-{Guid.NewGuid():N}");
        try
        {
            using var storage = new FileTelemetryStorage(dir);
            var (_, turns, _) = await RunSession(storage);
            Assert.Equal(3, turns.Count);
            Assert.Equal(Canonical(Golden.GetProperty("jsonl").GetString()!), Canonical(await File.ReadAllTextAsync(Path.Combine(dir, "turns.jsonl"), TestContext.Current.CancellationToken)));
            var sessions = await storage.ReadSessionsAsync(TestContext.Current.CancellationToken);
            Assert.Single(sessions);
            Assert.Equal(JsFormat.CanonicalJson(JsonNode.Parse(Golden.GetProperty("sessions")[0].GetRawText())),
                JsFormat.CanonicalJson(JsonSerializer.SerializeToNode(sessions[0], TelemetryJson.Options)));
            await storage.ClearAsync(TestContext.Current.CancellationToken);
            Assert.Empty(await storage.ReadTurnsAsync("sess-1", TestContext.Current.CancellationToken));
        }
        finally
        {
            if (Directory.Exists(dir))
                Directory.Delete(dir, true);
        }
    }
}
