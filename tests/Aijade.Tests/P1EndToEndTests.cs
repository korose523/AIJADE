using System.Text.Json.Nodes;

using Aijade.Memory.Contracts;
using Aijade.Memory.Development;
using Aijade.Memory.V9;
using Aijade.P1;
using Aijade.Server.V9;

using Microsoft.Extensions.DependencyInjection;

namespace Aijade.Tests;

/// <summary>P1 end-to-end flows (main flow and negative fork) and the v9 services, on real PostgreSQL.</summary>
public class P1EndToEndTests
{
    private static Target TargetOf(ServerTestHost h) => new(h.Client, h.Db, ServerTestHost.Token);

    private static string Report(IEnumerable<CheckResult> rs) => string.Join("\n", rs.Select(r => $"{(r.Pass ? "PASS" : "FAIL")} {r.Name} — {r.Detail}"));

    [Fact]
    public async Task Main_flow_passes_every_check()
    {
        await using var host = await ServerTestHost.StartAsync();
        var results = await Scenarios.MainFlowAsync(TargetOf(host), TimeSpan.FromSeconds(10), TestContext.Current.CancellationToken);
        Assert.Equal(18, results.Count);
        Assert.True(results.All(r => r.Pass), Report(results));
    }

    [Fact]
    public async Task Negative_fork_never_forges_a_render_identity()
    {
        await using var host = await ServerTestHost.StartAsync();
        var results = await Scenarios.NegativeForkAsync(TargetOf(host), TimeSpan.FromMilliseconds(500), TestContext.Current.CancellationToken);
        Assert.Equal(9, results.Count);
        Assert.True(results.All(r => r.Pass), Report(results));
    }

    [Fact]
    public async Task Ingest_bench_reports_nearest_rank_percentiles_with_raw_samples()
    {
        await using var host = await ServerTestHost.StartAsync();
        var result = await Scenarios.BenchIngestAsync(TargetOf(host), "both", 20, 3, TestContext.Current.CancellationToken);
        foreach (var run in new[] { "sequential", "concurrent" })
        {
            var r = result["runs"]![run]!;
            Assert.True(r["errors"]!.GetValue<int>() == 0, $"{run}: {r["errorDetail"]!.ToJsonString()}");
            Assert.Equal(20, r["n"]!.GetValue<int>());
            Assert.Equal(20, r["raw"]!.AsArray().Count);
        }
        Assert.Equal(46, await host.CountAsync("SELECT count(*) FROM events"));
        Assert.Equal(3.0, Scenarios.Percentile([1, 2, 3, 4], 75));
        Assert.Equal(1.0, Scenarios.Percentile([1, 2, 3, 4], 1));
        Assert.Null(Scenarios.Percentile([], 50));
    }

    private static JsonObject Perception(string id, string session, string content) => new()
    {
        ["event_id"] = id, ["session_id"] = session, ["trace_id"] = $"trace-{id}", ["correlation_id"] = $"corr-{id}", ["timestamp"] = 1_700_000_000_000,
        ["origin_device"] = "desk-1", ["privacy_level"] = 1, ["risk_score"] = 0.42, ["source"] = "chat", ["content"] = content,
    };

    [Fact]
    public async Task Perception_persists_the_causal_chain_and_replay_recomputes_it()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync();
        var (status, body) = await host.PostAsync("/api/v1/v9/perception", Perception("p1", "sess-1", "I moved to Seoul last spring and I love the food here."));
        Assert.Equal(201, status);
        Assert.Equal(1, await host.CountAsync("SELECT count(*) FROM memory_txs WHERE id = $1", body!["txId"]!.GetValue<string>()));
        Assert.True(await host.CountAsync("SELECT count(*) FROM events WHERE trace_id = 'trace-p1'") >= 3);
        // Observation context is the caller's, never synthesised (device name, continuous risk score).
        Assert.Equal(0, await host.CountAsync("SELECT count(*) FROM events WHERE trace_id = 'trace-p1' AND (origin_device <> 'desk-1' OR abs(risk_score - 0.42) > 1e-6)"));
        Assert.Equal(1, await host.CountAsync("SELECT count(*) FROM pgc_states WHERE session_id = 'sess-1'"));

        // A second perception of the same session reads the previous PGC state back from the database.
        Assert.Equal(201, (await host.PostAsync("/api/v1/v9/perception", Perception("p2", "sess-1", "Today I visited a market in Seoul."))).Status);
        Assert.Equal(2, await host.CountAsync("SELECT count(*) FROM pgc_states WHERE session_id = 'sess-1'"));

        // Learning path: a real render receipt, an observation, then replay of that observation's input snapshot.
        Assert.Equal(201, (await host.PostAsync("/api/v1/v9/events", Scenarios.Envelope("aijade.persona.render_requested",
            new JsonObject { ["session_id"] = "s", ["persona_snapshot_ref"] = "snap", ["intent_ref"] = "intent-1" }, "trace-r"))).Status);
        Assert.Equal(201, (await host.PostAsync("/api/v1/v9/events", Scenarios.Envelope("aijade.lpm.render_ready",
            new JsonObject { ["session_id"] = "s", ["render_ref"] = "render-1", ["applied_params_hash"] = "hash-1", ["asset_version_hash"] = "asset-1" }, "trace-r"))).Status);
        Assert.Equal(201, (await host.PostAsync("/api/v1/v9/events", Scenarios.Envelope("aijade.video.observation.video_transcript", new JsonObject
        {
            ["session_id"] = "ext-1", ["video_id"] = "v1", ["transcript_hash"] = "th1",
            ["time_spans"] = new JsonArray(new JsonObject { ["start_ms"] = 0, ["end_ms"] = 900, ["text"] = "Water boils at 100 degrees at sea level." }),
            ["caption_text"] = "Water boils at 100 degrees at sea level.",
        }, "trace-obs", extra: new JsonObject { ["tick"] = 77, ["causality"] = new JsonObject { ["inputHash"] = "ih-77" }, ["core_state_node"] = "S2" }))).Status);
        Assert.Equal(1, await host.CountAsync("SELECT count(*) FROM events WHERE topic = 'aijade.learning.proposed.evidence' AND payload->>'render_ref' = 'render-1'"));

        var (rs, replay) = await host.PostAsync("/api/v1/v9/replay", new JsonObject { ["tick"] = 77, ["inputHash"] = "ih-77" });
        Assert.Equal(200, rs);
        Assert.True(replay!["ok"]!.GetValue<bool>(), replay.ToJsonString());
        Assert.True(replay["checked"]!.GetValue<int>() >= 1);
        Assert.Empty(replay["mismatches"]!.AsArray());

        // Drift is detected: relabel a recorded node and the replay must fail (not a tautology).
        await host.ExecAsync("UPDATE events SET core_state_node = 'S0' WHERE tick = 77 AND causality->>'inputHash' = 'ih-77' AND core_state_node IS NOT NULL AND topic LIKE 'aijade.learning.%'");
        var (_, drift) = await host.PostAsync("/api/v1/v9/replay", new JsonObject { ["tick"] = 77, ["inputHash"] = "ih-77" });
        Assert.False(drift!["ok"]!.GetValue<bool>());
        Assert.Equal("mismatch", drift["reason"]!.GetValue<string>());

        var (nf, none) = await host.PostAsync("/api/v1/v9/replay", new JsonObject { ["tick"] = 1, ["inputHash"] = "nope" });
        Assert.Equal(404, nf);
        Assert.Equal("no_events_for_snapshot", none!["reason"]!.GetValue<string>());
        Assert.Equal(400, (await host.PostAsync("/api/v1/v9/replay", new JsonObject { ["tick"] = -1, ["inputHash"] = "x" })).Status);
        _ = ct;
    }

    [Fact]
    public async Task Persona_derive_refuses_without_evidence_and_persists_a_validated_kernel_intent()
    {
        await using var host = await ServerTestHost.StartAsync();
        var req = new JsonObject { ["session_id"] = "sess-2", ["device_id"] = "dev", ["agent_id"] = "agent", ["user_scope"] = "scope", ["privacy_level"] = 1 };
        var (s0, b0) = await host.PostAsync("/api/v1/v9/persona/derive", req);
        Assert.Equal(422, s0);
        Assert.Equal("NO_EVIDENCE", b0!["error"]!.GetValue<string>());
        Assert.Equal(400, (await host.PostAsync("/api/v1/v9/persona/derive", new JsonObject { ["session_id"] = "x", ["extra"] = 1 })).Status);

        Assert.Equal(201, (await host.PostAsync("/api/v1/v9/perception", Perception("p3", "sess-2", "Is it going to rain tomorrow?"))).Status);
        var (s1, b1) = await host.PostAsync("/api/v1/v9/persona/derive", req);
        Assert.Equal(200, s1);
        var intent = b1!["intent"]!;
        Assert.Equal("aijade.performance_intent@1", intent["schema"]!.GetValue<string>());
        Assert.Equal(b1["persona_snapshot_ref"]!.GetValue<string>(), intent["personaSnapshotRef"]!.GetValue<string>());
        Assert.Equal("yield", intent["turnTaking"]!.GetValue<string>()); // '?' in the evidence ⇒ a question act
        Assert.Equal(1, await host.CountAsync("SELECT count(*) FROM performance_intents WHERE id = $1", b1["intent_ref"]!.GetValue<string>()));
    }

    private static ShadowParamsProposal Proposal(string id)
    {
        var candidate = new JsonObject { ["emotion.preset"] = "happy" };
        return new ShadowParamsProposal(id, "sess", ShadowParams.ComputeLearningInputHash("sess", id, candidate), ShadowParamsAnchorKind.ShadowParams, true, candidate, 0.9,
            "render-1", "hash-1", "asset-1");
    }

    private static PromotionJob Job(string id, ShadowParamsProposal p, CoreTestGate? core = null, GateResult? staticAnalysis = null) =>
        new($"job-{id}", id, "sess", "trace", 1, p.InputHash, new EvaluationEvidencePack($"pack-{id}", id, core ?? new CoreTestGate(true, 10, 0), 0, staticAnalysis), p);

    [Fact]
    public async Task Promotion_requires_integrity_evidence_and_pgc_gates_and_writes_nothing_on_refusal()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync();
        var promotion = host.App.Services.GetRequiredService<PromotionService>();

        var tampered = Proposal("t1") with { CandidateParams = new JsonObject { ["emotion.preset"] = "angry" } };
        var r1 = await promotion.ProcessAsync(Job("t1", tampered), ct);
        Assert.Equal("integrity_gate", r1.Stage);
        var r2 = await promotion.ProcessAsync(Job("t2", Proposal("t2")) with { InputHash = "other" }, ct);
        Assert.Equal("integrity_gate", r2.Stage);
        var r3 = await promotion.ProcessAsync(Job("t3", Proposal("t3"), new CoreTestGate(false, 10, 1)), ct);
        Assert.Equal("evidence_gate", r3.Stage);
        var r4 = await promotion.ProcessAsync(Job("t4", Proposal("t4"), staticAnalysis: new GateResult(false)), ct);
        Assert.Equal("evidence_gate", r4.Stage);
        Assert.Equal(0, await host.CountAsync("SELECT count(*) FROM evolution_specs"));
        Assert.Equal(0, await host.CountAsync("SELECT count(*) FROM eval_reports"));

        var ok = await promotion.ProcessAsync(Job("t5", Proposal("t5")), ct);
        Assert.True(ok.Ok, $"{ok.Stage}: {ok.Reason}");
        Assert.Equal("evospec_t5", ok.EvolutionSpecId);
        Assert.Equal(1, await host.CountAsync("SELECT count(*) FROM evolution_specs WHERE id = 'evospec_t5'"));
        Assert.Equal(1, await host.CountAsync("SELECT count(*) FROM eval_reports WHERE id = 'evalrep_t5'"));

        // Through the queue: a job document is parsed (the proposal re-verified) and processed by the worker.
        var jobJson = new JsonObject
        {
            ["jobId"] = "q1",
            ["input"] = new JsonObject
            {
                ["proposalId"] = "t6", ["sessionId"] = "sess", ["traceId"] = "trace", ["tick"] = 1, ["inputHash"] = Proposal("t6").InputHash,
                ["evaluationPack"] = new JsonObject
                {
                    ["id"] = "pack-t6", ["proposalRef"] = "t6", ["createdAt"] = 0,
                    ["unitContractPropertyTests"] = new JsonObject { ["passed"] = true, ["total"] = 3, ["failed"] = 0 },
                },
                ["proposal"] = Proposal("t6").ToJson(),
            },
        };
        var parsed = PromotionService.ParseJob(jobJson);
        Assert.True((await promotion.ProcessAsync(parsed, ct)).Ok);
        Assert.Throws<InvalidOperationException>(() => PromotionService.ParseJob(new JsonObject { ["jobId"] = "bad", ["input"] = new JsonObject() }));
    }

    [Fact]
    public async Task Render_trace_backfill_pairs_history_idempotently_and_never_invents_identity()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync();
        // History written before the projection existed: events only.
        async Task Raw(string id, string trace, string topic, JsonObject payload, long ts) => await host.ExecAsync(
            "INSERT INTO events (id, event_id, trace_id, correlation_id, \"timestamp\", producer, origin_device, privacy_level, topic, payload, idempotency_key, replay_mode, risk_level) " +
            "VALUES ($1,$1,$2,$2,to_timestamp($5::double precision / 1000),'old','dev',1,$3,$4::jsonb,$1,'live','low')", id, trace, topic, payload.ToJsonString(), ts);
        await Raw("e1", "tA", "aijade.persona.render_requested", new JsonObject { ["session_id"] = "s", ["persona_snapshot_ref"] = "snap", ["intent_ref"] = "i-A" }, 1);
        await Raw("e2", "tA", "aijade.lpm.render_ready", new JsonObject { ["session_id"] = "s", ["render_ref"] = "r-A", ["applied_params_hash"] = "h-A" }, 2);
        await Raw("e3", "tB", "aijade.persona.render_requested", new JsonObject { ["session_id"] = "s", ["persona_snapshot_ref"] = "snap", ["intent_ref"] = "i-B" }, 3);
        await Raw("e4", "tC", "aijade.persona.render_requested", new JsonObject { ["session_id"] = "s1", ["persona_snapshot_ref"] = "snap", ["intent_ref"] = "i-C" }, 4);
        await Raw("e5", "tC", "aijade.lpm.render_ready", new JsonObject { ["session_id"] = "s2", ["render_ref"] = "r-C", ["applied_params_hash"] = "h-C" }, 5);
        await Raw("e6", "tD", "aijade.lpm.render_ready", new JsonObject { ["session_id"] = "s", ["render_ref"] = "r-D", ["applied_params_hash"] = "h-D" }, 6);

        var dry = await RenderTraceBackfill.RunAsync(host.Db, dryRun: true, ct);
        Assert.Equal((6, 2, 0), (dry.ScannedEvents, dry.PlannedRows, dry.Inserted));
        Assert.Equal(0, await host.CountAsync("SELECT count(*) FROM render_traces"));

        var run = await RenderTraceBackfill.RunAsync(host.Db, ct: ct);
        Assert.Equal(2, run.Inserted);
        Assert.Equal(["tB"], run.Incomplete.Select(g => g.TraceId));
        Assert.Equal(["tC"], run.Conflicts.Select(g => g.TraceId));
        Assert.Equal("paired", await host.ScalarAsync("SELECT projection_status FROM render_traces WHERE trace_id = 'tA'"));
        Assert.Equal("partial", await host.ScalarAsync("SELECT projection_status FROM render_traces WHERE trace_id = 'tD'"));
        var again = await RenderTraceBackfill.RunAsync(host.Db, ct: ct);
        Assert.Equal((0, 2), (again.Inserted, again.SkippedExisting));
    }

    [Fact]
    public async Task Evidence_domain_lists_a_sessions_references_and_flags_dangling_ones()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync();
        Assert.Equal(201, (await host.PostAsync("/api/v1/v9/perception", Perception("p9", "sess-9", "My sister is a nurse in Busan."))).Status);
        var domain = await host.App.Services.GetRequiredService<EvidenceDomainService>().GetAsync("sess-9", ct);
        Assert.Single(domain.EvidencePackIds);
        Assert.Single(domain.EvidenceChunkIds);
        var verified = EvidenceDomainService.Verify([.. domain.EvidencePackIds, .. domain.GraphHashes, "ghost-ref", "ghost-ref"], domain);
        Assert.False(verified.Ok);
        Assert.Equal(["ghost-ref"], verified.Missing);
        Assert.True(EvidenceDomainService.Verify(domain.EvidenceChunkIds, domain).Ok);
        using var res = await host.Client.GetAsync(new Uri("/api/v1/v9/evidence-domain/sess-9", UriKind.Relative), ct);
        Assert.Equal(System.Net.HttpStatusCode.OK, res.StatusCode);
    }
}
