using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Server.V9;

using Microsoft.Extensions.DependencyInjection;

namespace Aijade.Tests;

/// <summary>
/// P1 §4.4, the admission (ingestion-time) reference check of learning proposals, on the real event service and PostgreSQL:
/// an honest proposal and five tampered variants, each against a stored render trace. A case is "admitted" when its event is
/// written; otherwise the contract failure it was refused with is recorded and the event must not exist. With
/// AIJADE_EXPERIMENT_DIR set, the cases are written to {dir}/admission-checks.json (the paper's evidence).
/// </summary>
public class AdmissionChecksTests
{
    private static JsonObject Envelope(string topic, string eventId, string traceId, JsonObject payload) => new()
    {
        ["event_id"] = eventId, ["trace_id"] = traceId, ["correlation_id"] = $"corr-{eventId}", ["timestamp"] = 1_760_000_000_000L,
        ["producer"] = "admission-check", ["origin_device"] = "test-host", ["privacy_level"] = 1, ["evidence_refs"] = new JsonArray(),
        ["causal_context_refs"] = new JsonArray(), ["risk_score"] = 0.1, ["idempotency_key"] = $"idem-{eventId}", ["replay_mode"] = "live",
        ["risk_level"] = "low", ["topic"] = topic, ["payload"] = payload,
    };

    [Fact]
    public async Task Tampered_learning_proposals_are_refused_before_anything_is_written()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(worker: false);
        var events = host.App.Services.GetRequiredService<V9EventService>();

        // A paired render trace (request then receipt) and an unpaired one (a receipt with no request-side intent).
        Assert.Equal(201, (await host.PostAsync("/api/v1/v9/events", Envelope("aijade.persona.render_requested", "evt-req", "trace-render",
            new JsonObject { ["session_id"] = "s", ["persona_snapshot_ref"] = "snap-1", ["intent_ref"] = "intent-1" }))).Status);
        Assert.Equal(201, (await host.PostAsync("/api/v1/v9/events", Envelope("aijade.lpm.render_ready", "evt-ready", "trace-render",
            new JsonObject { ["session_id"] = "s", ["render_ref"] = "render-1", ["applied_params_hash"] = "applied-1", ["asset_version_hash"] = "asset-1" }))).Status);
        Assert.Equal(201, (await host.PostAsync("/api/v1/v9/events", Envelope("aijade.lpm.render_ready", "evt-ready-2", "trace-unpaired",
            new JsonObject { ["session_id"] = "s", ["render_ref"] = "render-unpaired", ["applied_params_hash"] = "applied-2", ["asset_version_hash"] = "asset-2" }))).Status);

        static JsonObject Proposal(string renderRef = "render-1", string applied = "applied-1", string asset = "asset-1") => new()
        {
            ["session_id"] = "s", ["render_ref"] = renderRef, ["applied_params_hash"] = applied, ["asset_version_hash"] = asset,
        };
        (string Name, string Expected, string EventId, JsonObject Payload)[] cases =
        [
            ("honest proposal", "admitted", "evt-p0", Proposal()),
            ("reference to a render that does not exist", "render_ref_not_found", "evt-p1", Proposal(renderRef: "render-nowhere")),
            ("reference to an unpaired trace (no request-side intent)", "intent_ref_missing", "evt-p2", Proposal(renderRef: "render-unpaired", applied: "applied-2", asset: "asset-2")),
            ("tampered parameter fingerprint", "applied_params_hash_mismatch", "evt-p3", Proposal(applied: "applied-forged")),
            ("tampered asset version", "asset_version_hash_mismatch", "evt-p4", Proposal(asset: "asset-forged")),
            ("self-reference (render_ref = own trace id)", "self_reference", "evt-p5", Proposal(renderRef: "trace-p5")),
        ];
        var results = new JsonArray();
        foreach (var (name, expected, eventId, payload) in cases)
        {
            var env = Envelope("aijade.learning.proposed.shadow_params", eventId, $"trace-{eventId[4..]}", payload);
            string got;
            try
            {
                await events.AppendEventAsync(V9EventInput.FromEnvelope(env, payload), ct);
                got = "admitted";
            }
            catch (RenderTraceContractException e)
            {
                got = WireName.Of(e.Reason);
            }
            var written = await host.CountAsync("SELECT count(*) FROM events WHERE event_id = $1", eventId);
            var asExpected = got == expected && written == (expected == "admitted" ? 1 : 0);
            results.Add(new JsonObject { ["case"] = name, ["expected"] = expected, ["got"] = got, ["eventsWritten"] = written, ["asExpected"] = asExpected });
        }
        if (Environment.GetEnvironmentVariable("AIJADE_EXPERIMENT_DIR") is { Length: > 0 } dir)
        {
            Directory.CreateDirectory(dir);
            var report = new JsonObject
            {
                ["generatedBy"] = "tests/Aijade.Tests/AdmissionChecksTests.cs (V9EventService on PostgreSQL)",
                ["cases"] = results.Count,
                ["asExpected"] = results.Count(r => r!["asExpected"]!.GetValue<bool>()),
                ["results"] = results,
            };
            await File.WriteAllTextAsync(Path.Combine(dir, "admission-checks.json"), JsFormat.Stringify(report, 2) + "\n", ct);
        }
        Assert.All(results, r => Assert.True(r!["asExpected"]!.GetValue<bool>(), r.ToJsonString()));
    }
}
