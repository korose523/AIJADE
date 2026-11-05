using System.Text.Json.Nodes;

using Aijade.Memory.V9;
using Aijade.Server.V9;

namespace Aijade.Tests;

/// <summary>
/// The consumer expectation tests of configuration 3 of experiments/plans/2026-11-05-p1-a-alternative-designs.md (its addendum): for each
/// component that reads an event or a job, what it reads, written from that component's code. Written after that study's input
/// faults had run and after its code faults were fixed, by the same researcher, so they are not a blind test of anything.
/// </summary>
public class ConsumerExpectationTests
{
    private const string Observation = "aijade.video.observation.webpage_text";
    private const string Proposed = "aijade.learning.proposed.evidence";

    private static JsonObject Env(string id, string trace, string topic, JsonObject payload, double risk = 0.1, long timestamp = 1_760_000_000_000L)
    {
        var e = new JsonObject
        {
            ["event_id"] = $"evt-{id}", ["trace_id"] = trace, ["correlation_id"] = $"corr-{id}", ["timestamp"] = timestamp, ["producer"] = "consumer-test",
            ["origin_device"] = "host", ["privacy_level"] = 1, ["evidence_refs"] = new JsonArray(), ["causal_context_refs"] = new JsonArray(), ["risk_score"] = risk,
            ["idempotency_key"] = $"key-{id}", ["replay_mode"] = "live", ["risk_level"] = "low", ["topic"] = topic, ["payload"] = payload,
        };
        if (topic.StartsWith("aijade.learning.", StringComparison.Ordinal) || topic.StartsWith("aijade.video.", StringComparison.Ordinal))
        {
            e["tick"] = 7;
            e["causality"] = new JsonObject { ["inputHash"] = $"hash-{id}" };
        }
        return e;
    }

    private static async Task Pair(ServerTestHost host, string name)
    {
        Assert.Equal(201, (await host.PostAsync("/api/v1/v9/events", Env($"{name}-req", $"trace-{name}", "aijade.persona.render_requested",
            new JsonObject { ["session_id"] = "s", ["persona_snapshot_ref"] = $"snap-{name}", ["intent_ref"] = $"intent-{name}" }))).Status);
        Assert.Equal(201, (await host.PostAsync("/api/v1/v9/events", Env($"{name}-rec", $"trace-{name}", "aijade.lpm.render_ready",
            new JsonObject { ["session_id"] = "s", ["render_ref"] = $"render-{name}", ["applied_params_hash"] = $"applied-{name}", ["asset_version_hash"] = $"asset-{name}" }))).Status);
    }

    private static JsonObject Proposal(string id, string name, string? applied = null, string? asset = null) => Env(id, $"trace-{id}", Proposed, new JsonObject
    {
        ["session_id"] = "s", ["proposal_id"] = $"p-{id}", ["render_ref"] = $"render-{name}", ["applied_params_hash"] = applied ?? $"applied-{name}",
        ["asset_version_hash"] = asset ?? $"asset-{name}", ["evidence_hash"] = $"e-{id}", ["claim_text"] = "a claim", ["confidence"] = 0.5,
    });

    private static JsonObject Webpage(string id, double risk = 0.1, long timestamp = 1_760_000_000_000L) => Env(id, $"trace-{id}", Observation, new JsonObject
    {
        ["session_id"] = "s", ["source_url"] = "https://example.test/a", ["content_hash"] = $"content-{id}",
        ["spans"] = new JsonArray(new JsonObject { ["start_offset"] = 0, ["end_offset"] = 4 }), ["observation_text"] = "some text",
    }, risk, timestamp);

    // The projection reads the identifiers, fingerprint and asset version of a receipt, and the intent of a request.
    [Fact]
    public async Task Projection_stores_what_the_request_and_receipt_carry()
    {
        await using var host = await ServerTestHost.StartAsync(worker: false);
        await Pair(host, "a");
        Assert.Equal("render-a", await host.ScalarAsync("SELECT render_ref FROM render_traces WHERE trace_id = 'trace-a'"));
        Assert.Equal("intent-a", await host.ScalarAsync("SELECT intent_ref FROM render_traces WHERE trace_id = 'trace-a'"));
        Assert.Equal("snap-a", await host.ScalarAsync("SELECT persona_snapshot_ref FROM render_traces WHERE trace_id = 'trace-a'"));
        Assert.Equal("applied-a", await host.ScalarAsync("SELECT applied_params_hash FROM render_traces WHERE trace_id = 'trace-a'"));
        Assert.Equal("asset-a", await host.ScalarAsync("SELECT asset_version_hash FROM render_traces WHERE trace_id = 'trace-a'"));
    }

    [Fact]
    public async Task Projection_marks_a_trace_paired_only_with_both_sides()
    {
        await using var host = await ServerTestHost.StartAsync(worker: false);
        Assert.Equal(201, (await host.PostAsync("/api/v1/v9/events", Env("half", "trace-half", "aijade.persona.render_requested",
            new JsonObject { ["session_id"] = "s", ["persona_snapshot_ref"] = "snap", ["intent_ref"] = "intent" }))).Status);
        Assert.NotEqual("paired", await host.ScalarAsync("SELECT projection_status FROM render_traces WHERE trace_id = 'trace-half'"));
        await Pair(host, "b");
        Assert.Equal("paired", await host.ScalarAsync("SELECT projection_status FROM render_traces WHERE trace_id = 'trace-b'"));
    }

    [Fact]
    public async Task Projection_refuses_a_second_render_on_one_trace()
    {
        await using var host = await ServerTestHost.StartAsync(worker: false);
        await Pair(host, "c");
        var second = Env("c2", "trace-c", "aijade.lpm.render_ready",
            new JsonObject { ["session_id"] = "s", ["render_ref"] = "render-other", ["applied_params_hash"] = "a", ["asset_version_hash"] = "b" });
        Assert.Equal(400, (await host.PostAsync("/api/v1/v9/events", second)).Status);
        Assert.Equal("render-c", await host.ScalarAsync("SELECT render_ref FROM render_traces WHERE trace_id = 'trace-c'"));
    }

    // The admission check reads the proposal's render, fingerprint and asset version, and compares them with the projection.
    [Fact]
    public async Task Admission_admits_an_honest_proposal_and_refuses_each_mismatch()
    {
        await using var host = await ServerTestHost.StartAsync(worker: false);
        await Pair(host, "d");
        Assert.Equal(201, (await host.PostAsync("/api/v1/v9/events", Proposal("honest", "d"))).Status);
        Assert.Equal(400, (await host.PostAsync("/api/v1/v9/events", Proposal("forged-applied", "d", applied: "forged"))).Status);
        Assert.Equal(400, (await host.PostAsync("/api/v1/v9/events", Proposal("forged-asset", "d", asset: "forged"))).Status);
        Assert.Equal(400, (await host.PostAsync("/api/v1/v9/events", Proposal("nowhere", "nowhere"))).Status);
    }

    // Observation dispatch reads the latest identity and carries the envelope's time, risk, tick and hash into the proposal.
    private static async Task<(int Status, string? Render, string? Tick, string? Risk, string? Ms)> DispatchAsync(ServerTestHost host, JsonObject observation)
    {
        var (status, _) = await host.PostAsync("/api/v1/v9/events", observation);
        var trace = observation["trace_id"]!.GetValue<string>();
        var deadline = DateTime.UtcNow.AddSeconds(10);
        while (await host.CountAsync($"SELECT count(*) FROM events WHERE topic = '{Proposed}' AND trace_id = $1", trace) == 0 && DateTime.UtcNow < deadline)
            await Task.Delay(50, TestContext.Current.CancellationToken);
        const string Where = $"FROM events WHERE topic = '{Proposed}' AND trace_id = $1 LIMIT 1";
        return (status, await host.ScalarAsync($"SELECT payload->>'render_ref' {Where}", trace), await host.ScalarAsync($"SELECT tick::text {Where}", trace),
            await host.ScalarAsync($"SELECT risk_score::text {Where}", trace), await host.ScalarAsync($"SELECT (extract(epoch FROM \"timestamp\") * 1000)::bigint::text {Where}", trace));
    }

    [Fact]
    public async Task Dispatch_uses_the_latest_render_identity()
    {
        await using var host = await ServerTestHost.StartAsync(worker: false);
        await Pair(host, "old");
        await Task.Delay(20, TestContext.Current.CancellationToken);
        await Pair(host, "new");
        Assert.Equal("render-new", (await DispatchAsync(host, Webpage("latest"))).Render);
    }

    [Fact]
    public async Task Dispatch_carries_time_risk_and_tick_into_the_proposal()
    {
        await using var host = await ServerTestHost.StartAsync(worker: false);
        await Pair(host, "e");
        var (status, _, tick, risk, ms) = await DispatchAsync(host, Webpage("carry", risk: 0.2, timestamp: 1_760_000_123_000L));
        Assert.Equal(201, status);
        Assert.Equal("7", tick);
        Assert.Equal(0.2, double.Parse(risk!, System.Globalization.CultureInfo.InvariantCulture), 3);
        Assert.Equal("1760000123000", ms);
    }

    [Fact]
    public async Task Dispatch_skips_learning_with_no_render_identity()
    {
        await using var host = await ServerTestHost.StartAsync(worker: false);
        Assert.Equal(201, (await host.PostAsync("/api/v1/v9/events", Webpage("none"))).Status);
        await Task.Delay(200, TestContext.Current.CancellationToken);
        Assert.Equal(0, await host.CountAsync($"SELECT count(*) FROM events WHERE topic = '{Proposed}'"));
    }

    // The evidence reader reads the text, the hash and how many spans there are.
    private static JsonObject WebpagePayload(int spans)
    {
        var list = new JsonArray();
        for (var i = 0; i < spans; i++)
            list.Add(new JsonObject { ["start_offset"] = i, ["end_offset"] = i + 1 });
        return new JsonObject { ["observation_text"] = "the text", ["content_hash"] = "the-hash", ["spans"] = list };
    }

    [Fact]
    public void Evidence_reader_takes_text_and_hash_from_their_fields()
    {
        var c = VideoObservation.FromWebpage(WebpagePayload(1));
        Assert.Equal("the text", c.ClaimText);
        Assert.Equal("the-hash", c.SourceRef);
        var s = VideoObservation.FromSubtitles(new JsonObject { ["caption_text"] = "caption", ["transcript_hash"] = "t-hash", ["time_spans"] = new JsonArray(new JsonObject { ["start_ms"] = 0, ["end_ms"] = 1, ["text"] = "x" }) });
        Assert.Equal("caption", s.ClaimText);
        Assert.Equal("t-hash", s.SourceRef);
    }

    [Fact]
    public void Evidence_reader_grows_firmer_with_more_spans_up_to_its_cap()
    {
        var one = VideoObservation.FromWebpage(WebpagePayload(1)).Confidence;
        var three = VideoObservation.FromWebpage(WebpagePayload(3)).Confidence;
        var five = VideoObservation.FromWebpage(WebpagePayload(5)).Confidence;
        var nine = VideoObservation.FromWebpage(WebpagePayload(9)).Confidence;
        Assert.True(one < three && three < five, $"{one} {three} {five}");
        Assert.Equal(five, nine);
        Assert.InRange(nine, 0, 1);
    }

    [Fact]
    public void Evidence_reader_refuses_what_it_cannot_read()
    {
        Assert.Throws<ArgumentException>(() => VideoObservation.FromWebpage(new JsonObject { ["observation_text"] = " ", ["content_hash"] = "h", ["spans"] = new JsonArray(new JsonObject()) }));
        Assert.Throws<ArgumentException>(() => VideoObservation.FromWebpage(new JsonObject { ["observation_text"] = "t", ["content_hash"] = " ", ["spans"] = new JsonArray(new JsonObject()) }));
        Assert.Throws<ArgumentException>(() => VideoObservation.FromWebpage(new JsonObject { ["observation_text"] = "t", ["content_hash"] = "h", ["spans"] = new JsonArray() }));
    }

    // The promotion worker's parser reads the job's identifiers, the pack's verdict and counts, and the proposal.
    [Fact]
    public void Job_parser_reads_the_fields_the_gates_use_and_refuses_a_malformed_job()
    {
        var job = new JsonObject
        {
            ["jobId"] = "j1",
            ["input"] = new JsonObject
            {
                ["proposalId"] = "p1", ["sessionId"] = "sess", ["traceId"] = "trace", ["tick"] = 3, ["inputHash"] = "hash",
                ["evaluationPack"] = new JsonObject
                {
                    ["id"] = "pack", ["proposalRef"] = "p1", ["createdAt"] = 5,
                    ["unitContractPropertyTests"] = new JsonObject { ["passed"] = true, ["total"] = 10, ["failed"] = 2 },
                    ["staticAnalysis"] = new JsonObject { ["passed"] = false, ["findings"] = 4 },
                },
                ["proposal"] = new JsonObject
                {
                    ["proposalId"] = "p1", ["sessionId"] = "sess", ["inputHash"] = "hash", ["anchorKind"] = "shadow_params", ["anchorVerified"] = true, ["confidence"] = 0.7,
                },
                ["pgcV6State"] = new JsonObject { ["a"] = 0.1, ["c"] = 0.2, ["d"] = 0.3, ["f"] = 0.4 },
            },
        };
        var parsed = PromotionService.ParseJob(job);
        Assert.Equal(("j1", "p1", "sess", "trace", 3, "hash"), (parsed.JobId, parsed.ProposalId, parsed.SessionId, parsed.TraceId, parsed.Tick, parsed.InputHash));
        Assert.Equal((true, 10, 2), (parsed.EvaluationPack.UnitContractPropertyTests.Passed, parsed.EvaluationPack.UnitContractPropertyTests.Total, parsed.EvaluationPack.UnitContractPropertyTests.Failed));
        Assert.False(parsed.EvaluationPack.StaticAnalysis!.Passed);
        Assert.Equal(0.7, parsed.Proposal.Confidence);
        Assert.Equal(0.4, parsed.PgcV6State!.Value.F);
        Assert.Throws<InvalidOperationException>(() => PromotionService.ParseJob(new JsonObject { ["jobId"] = "bad", ["input"] = new JsonObject() }));
    }
}
