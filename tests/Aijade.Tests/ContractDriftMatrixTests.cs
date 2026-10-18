using System.Text.Json.Nodes;

using Aijade.Memory.Kernel;
using Aijade.Server.V9;

namespace Aijade.Tests;

/// <summary>
/// P1 v10 contract-drift regression matrix, run against the server on real PostgreSQL. Per topic it proves: (1) both ends agree —
/// a valid payload is accepted by the kernel schema and by the independently written HTTP boundary; (2) the boundary is
/// load-bearing — a missing field, blank string or unknown extra field is a 400 and nothing is written; (3) a refused
/// request changes neither events nor render_traces. The assertion log must equal the recorded baseline (Golden/p1) line by line.
/// </summary>
public class ContractDriftMatrixTests
{
    private sealed record Fixture(
        string Topic, bool V10, Func<int, JsonObject> Payload, (string Name, Func<JsonObject, JsonObject> Mutate)[] Negatives,
        (string Name, Func<int, JsonObject> Payload)[]? ExtraPositives = null);

    private const string SeedRenderRef = "seed-render-ref";
    private const string SeedAppliedHash = "seed-applied-hash";
    private const string SeedAssetHash = "seed-asset-hash";

    private static readonly string[] EnvelopeRequired =
        ["event_id", "trace_id", "correlation_id", "timestamp", "producer", "origin_device", "privacy_level", "evidence_refs", "causal_context_refs", "risk_score",
         "idempotency_key", "replay_mode", "risk_level"];

    private static readonly string[] EnvelopeOptional = ["tick", "causality", "core_state_node"];

    private static Func<JsonObject, JsonObject> Drop(string key) => p =>
    {
        var n = (JsonObject)p.DeepClone();
        n.Remove(key);
        return n;
    };

    private static Func<JsonObject, JsonObject> Blank(string key) => p => With(p, key, "");

    private static Func<JsonObject, JsonObject> Surprise() => p => With(p, "surprise_unknown_field", "x");

    private static JsonObject With(JsonObject p, string key, JsonNode? value)
    {
        var n = (JsonObject)p.DeepClone();
        n[key] = value;
        return n;
    }

    private static readonly Fixture[] Fixtures =
    [
        new("aijade.active_learning.requested", false, i => new JsonObject
        {
            ["session_id"] = $"s-{i}", ["trace_id"] = $"t-{i}", ["requested_at"] = 1, ["quest_ref"] = $"quest-{i}",
            ["resource_budget"] = new JsonObject { ["allocated"] = 10, ["spent"] = 0, ["unit"] = "queries" }, ["stop_conditions"] = new JsonArray("budget-exhausted"),
        }, [("missing quest_ref", Drop("quest_ref")), ("blank quest_ref", Blank("quest_ref")), ("empty stop_conditions", p => With(p, "stop_conditions", new JsonArray())), ("unknown field", Surprise())]),
        new("aijade.active_learning.completed", false, i => new JsonObject { ["session_id"] = $"s-{i}", ["trace_id"] = $"t-{i}", ["completed_at"] = 2, ["quest_ref"] = $"quest-{i}" },
            [("missing quest_ref", Drop("quest_ref")), ("blank quest_ref", Blank("quest_ref")), ("unknown field", Surprise())]),
        new("aijade.evidence.weave_candidate_ready", false,
            i => new JsonObject { ["tx_id"] = $"tx-{i}", ["weave_id"] = $"w-{i}", ["graph_hash"] = $"g-{i}", ["candidate_memory_write_ids"] = new JsonArray($"mw-{i}") },
            [("missing graph_hash", Drop("graph_hash")), ("blank graph_hash", Blank("graph_hash")), ("unknown field", Surprise())]),
        new("aijade.pgc.write_plan_ready", false, i => new JsonObject { ["pgc_state_id"] = $"pgc-{i}", ["write_plan_size"] = 1, ["policy_version"] = "pgc_policy_v1" },
            [("missing pgc_state_id", Drop("pgc_state_id")), ("negative write_plan_size", p => With(p, "write_plan_size", -1)), ("unknown field", Surprise())]),
        new("aijade.memory_tx.committed", false,
            i => new JsonObject { ["tx_id"] = $"tx-{i}", ["trace_id"] = $"t-{i}", ["committed_count"] = 1, ["rejected_count"] = 0, ["throttled_count"] = 0 },
            [("missing committed_count", Drop("committed_count")), ("negative committed_count", p => With(p, "committed_count", -1)), ("unknown field", Surprise())]),
        new("aijade.persona.render_requested", false, i => new JsonObject { ["session_id"] = $"s-{i}", ["persona_snapshot_ref"] = $"snap-{i}", ["intent_ref"] = $"intent-{i}" },
            [("missing persona_snapshot_ref", Drop("persona_snapshot_ref")), ("missing intent_ref", Drop("intent_ref")), ("blank intent_ref", Blank("intent_ref")), ("unknown field", Surprise())]),
        new("aijade.lpm.render_ready", false,
            i => new JsonObject { ["session_id"] = $"s-{i}", ["render_ref"] = $"render-{i}", ["applied_params_hash"] = $"applied-{i}", ["asset_version_hash"] = $"asset-{i}" },
            [("missing render_ref", Drop("render_ref")), ("blank render_ref", Blank("render_ref")), ("blank applied_params_hash", Blank("applied_params_hash")),
             ("blank asset_version_hash", Blank("asset_version_hash")), ("unknown field", Surprise())],
            [("asset_version_hash absent (optional per kernel)", i => new JsonObject { ["session_id"] = $"s-{i}", ["render_ref"] = $"render-{i}", ["applied_params_hash"] = $"applied-{i}" })]),
        new("aijade.video.observation.webpage_text", true, i => new JsonObject
        {
            ["session_id"] = $"s-{i}", ["source_url"] = $"https://example.com/{i}", ["content_hash"] = $"ch-{i}",
            ["spans"] = new JsonArray(new JsonObject { ["start_offset"] = 0, ["end_offset"] = 5, ["label"] = "p" }), ["observation_text"] = $"text-{i}",
        }, [("missing session_id", Drop("session_id")), ("blank session_id", Blank("session_id")), ("missing source_url", Drop("source_url")),
            ("blank observation_text", Blank("observation_text")), ("empty spans", p => With(p, "spans", new JsonArray())), ("unknown field", Surprise())]),
        new("aijade.video.observation.video_transcript", true, i => new JsonObject
        {
            ["session_id"] = $"s-{i}", ["video_id"] = $"v-{i}", ["transcript_hash"] = $"th-{i}",
            ["time_spans"] = new JsonArray(new JsonObject { ["start_ms"] = 0, ["end_ms"] = 100, ["text"] = $"cap-{i}" }), ["caption_text"] = $"cap-{i}",
        }, [("missing session_id", Drop("session_id")), ("blank session_id", Blank("session_id")), ("missing video_id", Drop("video_id")),
            ("empty time_spans", p => With(p, "time_spans", new JsonArray())), ("unknown field", Surprise())]),
        new("aijade.learning.proposed.shadow_params", true, i => new JsonObject
        {
            ["session_id"] = $"s-{i}", ["proposal_id"] = $"prop-{i}", ["render_ref"] = SeedRenderRef, ["applied_params_hash"] = SeedAppliedHash,
            ["asset_version_hash"] = SeedAssetHash, ["input_hash"] = $"ih-{i}", ["candidate_params"] = new JsonObject { ["emotion.preset"] = "happy" }, ["confidence"] = 0.5,
        }, [("missing input_hash", Drop("input_hash")), ("blank proposal_id", Blank("proposal_id")), ("confidence out of range", p => With(p, "confidence", 1.5)), ("unknown field", Surprise())]),
        new("aijade.learning.proposed.evidence", true, i => new JsonObject
        {
            ["session_id"] = $"s-{i}", ["proposal_id"] = $"prop-{i}", ["render_ref"] = SeedRenderRef, ["applied_params_hash"] = SeedAppliedHash,
            ["asset_version_hash"] = SeedAssetHash, ["evidence_hash"] = $"eh-{i}", ["claim_text"] = $"claim-{i}", ["confidence"] = 0.4,
        }, [("missing evidence_hash", Drop("evidence_hash")), ("blank claim_text", Blank("claim_text")), ("unknown field", Surprise())]),
        new("aijade.learning.constraint.opinion_evaluation", true, i => new JsonObject
        {
            ["evaluation_target"] = $"ch-{i}", ["claims"] = new JsonArray(new JsonObject { ["claim_text"] = $"claim-{i}", ["confidence"] = 0.6 }),
            ["uncertainty_notes"] = "可能误读原文",
        }, [("missing uncertainty_notes", Drop("uncertainty_notes")), ("empty claims", p => With(p, "claims", new JsonArray())), ("unknown field", Surprise())]),
    ];

    private static JsonObject Envelope(Fixture f, int i, JsonObject payload)
    {
        var e = new JsonObject
        {
            ["event_id"] = $"evt-{f.Topic}-{i}", ["trace_id"] = $"trace-{f.Topic}-{i}", ["correlation_id"] = $"trace-{f.Topic}-{i}", ["timestamp"] = 1_700_000_000_000,
            ["producer"] = "contract-matrix", ["origin_device"] = "test", ["privacy_level"] = 1, ["evidence_refs"] = new JsonArray(),
            ["causal_context_refs"] = new JsonArray($"trace-{f.Topic}-{i}"), ["risk_score"] = 0, ["idempotency_key"] = $"idem-{f.Topic}-{i}", ["replay_mode"] = "live",
            ["risk_level"] = "low",
        };
        if (f.V10)
        {
            e["tick"] = i;
            e["causality"] = new JsonObject { ["inputHash"] = $"input-{f.Topic}-{i}" };
        }
        e["topic"] = f.Topic;
        e["payload"] = payload;
        return e;
    }

    private static bool KernelAccepts(JsonObject env) => AijadeEvents.IsValid(env);

    /// <summary>The whole matrix against <paramref name="host"/>; returns the assertion log ("ok   …" / "FAIL …").</summary>
    internal static async Task<List<string>> RunAsync(ServerTestHost host)
    {
        var log = new List<string>();
        void Check(bool cond, string msg) => log.Add($"{(cond ? "ok  " : "FAIL")} {msg}");

        var covered = Fixtures.Select(f => f.Topic).ToHashSet(StringComparer.Ordinal);
        var uncovered = V9Boundary.Topics.Where(t => !covered.Contains(t)).ToList();
        Check(uncovered.Count == 0, $"every server topic has a fixture (uncovered: {(uncovered.Count == 0 ? "none" : string.Join(", ", uncovered))})");
        var stale = covered.Where(t => !V9Boundary.Topics.Contains(t)).ToList();
        Check(stale.Count == 0, $"no stale fixture for a removed topic (stale: {(stale.Count == 0 ? "none" : string.Join(", ", stale))})");
        var kernelSet = AijadeEvents.Topics.ToHashSet(StringComparer.Ordinal);
        var serverSet = V9Boundary.Topics.ToHashSet(StringComparer.Ordinal);
        var onlyKernel = kernelSet.Where(t => !serverSet.Contains(t)).ToList();
        var onlyServer = serverSet.Where(t => !kernelSet.Contains(t)).ToList();
        Check(onlyKernel.Count == 0 && onlyServer.Count == 0,
            $"kernel/server topic sets agree (kernel-only: {(onlyKernel.Count == 0 ? "none" : string.Join(", ", onlyKernel))}; server-only: {(onlyServer.Count == 0 ? "none" : string.Join(", ", onlyServer))})");
        var kernelFields = AijadeEvents.EnvelopeFields.Keys.Order(StringComparer.Ordinal).ToList();
        Check(string.Join(",", kernelFields) == string.Join(",", EnvelopeRequired.Concat(EnvelopeOptional).Order(StringComparer.Ordinal)),
            $"kernel envelope declares exactly {EnvelopeRequired.Length} required + {EnvelopeOptional.Length} optional fields (got: {string.Join(", ", kernelFields)})");

        await host.ExecAsync(
            "INSERT INTO render_traces (id, session_id, trace_id, correlation_id, event_id, persona_snapshot_ref, intent_ref, render_ref, applied_params_hash, asset_version_hash, " +
            "render_ready_event_id, persona_render_requested_event_id, projection_status) VALUES ('seed-projection','seed-session','seed-trace','seed-trace','seed-event'," +
            "'seed-snapshot','seed-intent',$1,$2,$3,'seed-render-ready-event','seed-persona-request-event','paired')", SeedRenderRef, SeedAppliedHash, SeedAssetHash);

        async Task<(long Events, long Traces)> Counts() =>
            (await host.CountAsync("SELECT count(*) FROM events"), await host.CountAsync("SELECT count(*) FROM render_traces"));
        Task<(int Status, JsonNode? Body)> Post(JsonObject env) => host.PostAsync("/api/v1/v9/events", env);

        foreach (var f in Fixtures)
        {
            var positives = new List<(string Label, int Index, JsonObject Payload)> { ("valid payload", 0, f.Payload(0)) };
            positives.AddRange((f.ExtraPositives ?? []).Select((v, k) => (v.Name, 200 + k, v.Payload(200 + k))));
            foreach (var (label, index, payload) in positives)
            {
                var env = Envelope(f, index, payload);
                var tag = $"{f.Topic} / {label}";
                Check(KernelAccepts(env), $"[kernel] {tag}: valid payload accepted");
                if (KernelAccepts(env))
                {
                    try
                    {
                        AijadeEvents.AssertV10RequiredFields(env);
                        Check(true, $"[kernel] {tag}: v10 envelope fields present");
                    }
                    catch (Exception e) when (e is InvalidOperationException or ArgumentException)
                    {
                        Check(false, $"[kernel] {tag}: assertV10RequiredFields threw on the valid fixture ({e.Message})");
                    }
                }
                var res = await Post(env);
                Check(res.Status == 201, $"[http] {tag}: valid payload -> 201 (got {res.Status})");
            }
        }

        foreach (var f in Fixtures)
        {
            for (var index = 0; index < f.Negatives.Length; index++)
            {
                var (name, mutate) = f.Negatives[index];
                var i = 100 + index;
                var env = Envelope(f, i, mutate(f.Payload(i)));
                var before = await Counts();
                var res = await Post(env);
                var after = await Counts();
                Check(res.Status == 400, $"[http] {f.Topic} / {name}: must be 400 (got {res.Status})");
                Check(!KernelAccepts(env), $"[kernel] {f.Topic} / {name}: kernel must reject too");
                Check(after.Events == before.Events, $"[no-write] {f.Topic} / {name}: events unchanged ({before.Events} -> {after.Events})");
                Check(after.Traces == before.Traces, $"[no-write] {f.Topic} / {name}: render_traces unchanged ({before.Traces} -> {after.Traces})");
            }
        }

        // §11.2 self-reference: a ref pointing at the envelope's own identifiers must be a 400 with no write; the kernel's
        // payload schema structurally accepts it (a cross-field rule only the boundary can enforce).
        var selfCases = Fixtures.Where(f => f.Topic.StartsWith("aijade.learning.proposed.", StringComparison.Ordinal)).Select(f => (f.Topic, Replace: "render_ref"))
            .Append((Topic: "aijade.persona.render_requested", Replace: "intent_ref")).ToList();
        for (var k = 0; k < selfCases.Count; k++)
        {
            var f = Fixtures.First(x => x.Topic == selfCases[k].Topic);
            var i = 700 + k;
            var payload = With(f.Payload(i), selfCases[k].Replace, Envelope(f, i, f.Payload(i))["trace_id"]!.GetValue<string>());
            var env = Envelope(f, i, payload);
            var before = await Counts();
            var res = await Post(env);
            var after = await Counts();
            Check(res.Status == 400, $"[http] {f.Topic} / {selfCases[k].Replace} self-reference: must be 400 (got {res.Status})");
            Check(after.Events == before.Events, $"[no-write] {f.Topic} / {selfCases[k].Replace} self-reference: events unchanged ({before.Events} -> {after.Events})");
            Check(after.Traces == before.Traces, $"[no-write] {f.Topic} / {selfCases[k].Replace} self-reference: render_traces unchanged ({before.Traces} -> {after.Traces})");
            Check(KernelAccepts(env), $"[kernel] {f.Topic} / {selfCases[k].Replace} self-reference: kernel accepts (shape is legal; only the boundary can reject it)");
        }

        foreach (var field in EnvelopeRequired)
        {
            var i = 900 + Array.IndexOf(EnvelopeRequired, field);
            var env = Envelope(Fixtures[0], i, Fixtures[0].Payload(i));
            env.Remove(field);
            var before = await Counts();
            var res = await Post(env);
            var after = await Counts();
            Check(!KernelAccepts(env), $"[kernel] envelope missing \"{field}\": must be rejected");
            Check(res.Status == 400, $"[http] envelope missing \"{field}\": must be 400 (got {res.Status})");
            Check(after.Events == before.Events, $"[no-write] envelope missing \"{field}\": events unchanged ({before.Events} -> {after.Events})");
        }

        {
            var env = Envelope(Fixtures[0], 980, Fixtures[0].Payload(980));
            env["surprise_unknown_envelope_field"] = "x";
            var before = await Counts();
            var res = await Post(env);
            var after = await Counts();
            Check(!KernelAccepts(env), "[kernel] envelope with unknown extra field: must be rejected");
            Check(res.Status == 400, $"[http] envelope with unknown extra field: must be 400 (got {res.Status})");
            Check(after.Events == before.Events, $"[no-write] envelope with unknown extra field: events unchanged ({before.Events} -> {after.Events})");
        }
        {
            var env = Envelope(Fixtures[0], 981, Fixtures[0].Payload(981));
            env["tick"] = 2_147_483_648L;
            var before = await Counts();
            var res = await Post(env);
            var after = await Counts();
            Check(!KernelAccepts(env), "[kernel] tick beyond int32: must be rejected");
            Check(res.Status == 400, $"[http] tick beyond int32: must be 400 (got {res.Status})");
            Check(after.Events == before.Events, $"[no-write] tick beyond int32: events unchanged ({before.Events} -> {after.Events})");
        }
        foreach (var field in EnvelopeOptional)
        {
            var i = 950 + Array.IndexOf(EnvelopeOptional, field);
            var env = Envelope(Fixtures[0], i, Fixtures[0].Payload(i));
            env.Remove(field);
            Check(KernelAccepts(env), $"[kernel] envelope without optional \"{field}\": must still be accepted");
        }
        return log;
    }

    [Fact]
    public async Task Matrix_log_equals_the_recorded_baseline_line_by_line()
    {
        // The boundary alone, without observation dispatch: the matrix asserts the contract, not the learning pipeline.
        await using var host = await ServerTestHost.StartAsync(new Dictionary<string, string?> { ["Aijade:DispatchObservations"] = "false" }, worker: false);
        var log = await RunAsync(host);
        // The mutation experiment (tools/Aijade.Mutation) reads the full assertion log of a mutated build from here.
        if (Environment.GetEnvironmentVariable("AIJADE_MATRIX_LOG") is { Length: > 0 } logPath)
            await File.WriteAllLinesAsync(logPath, log, TestContext.Current.CancellationToken);
        var golden = await File.ReadAllLinesAsync(Path.Combine(AppContext.BaseDirectory, "Golden", "p1", "contract-drift.txt"), TestContext.Current.CancellationToken);
        Assert.DoesNotContain(log, l => l.StartsWith("FAIL", StringComparison.Ordinal));
        Assert.Equal(golden, log);
    }
}
