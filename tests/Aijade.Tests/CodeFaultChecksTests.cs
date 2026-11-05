using System.Text.Json.Nodes;

using Aijade.Server.V9;

namespace Aijade.Tests;

/// <summary>
/// What experiments/p1/code_fault_driver.py runs on a mutated copy for the code faults of P1-A, besides the two matrices. Both are skipped
/// unless their variables are set. The liberal matrix writes its log for the driver to compare; the workload posts the chain's inputs to one
/// configuration and counts only refusals, server errors and, in configuration 4, the audit's list: reading stored rows would be a check
/// that the configuration does not have.
/// </summary>
public class CodeFaultChecksTests
{
    private static JsonObject Env(string id, string trace, string topic, JsonObject payload)
    {
        var e = new JsonObject
        {
            ["event_id"] = $"evt-{id}", ["trace_id"] = trace, ["correlation_id"] = $"corr-{id}", ["timestamp"] = 1_760_000_000_000L, ["producer"] = "p1a-workload",
            ["origin_device"] = "host", ["privacy_level"] = 1, ["evidence_refs"] = new JsonArray(), ["causal_context_refs"] = new JsonArray(), ["risk_score"] = 0.1,
            ["idempotency_key"] = $"key-{id}", ["replay_mode"] = "live", ["risk_level"] = "low", ["topic"] = topic, ["payload"] = payload,
        };
        if (topic.StartsWith("aijade.learning.", StringComparison.Ordinal) || topic.StartsWith("aijade.video.", StringComparison.Ordinal))
        {
            e["tick"] = 1;
            e["causality"] = new JsonObject { ["inputHash"] = $"hash-{id}" };
        }
        return e;
    }

    private static IEnumerable<JsonObject> Chain()
    {
        foreach (var n in new[] { "a", "b" })
        {
            yield return Env($"{n}-req", $"trace-{n}", "aijade.persona.render_requested", new JsonObject { ["session_id"] = "s", ["persona_snapshot_ref"] = $"snap-{n}", ["intent_ref"] = $"intent-{n}" });
            yield return Env($"{n}-rec", $"trace-{n}", "aijade.lpm.render_ready", new JsonObject { ["session_id"] = "s", ["render_ref"] = $"render-{n}", ["applied_params_hash"] = $"applied-{n}", ["asset_version_hash"] = $"asset-{n}" });
        }
        yield return Env("obs", "trace-obs", "aijade.video.observation.webpage_text", new JsonObject
        {
            ["session_id"] = "s", ["source_url"] = "https://example.test/a", ["content_hash"] = "content", ["spans"] = new JsonArray(new JsonObject { ["start_offset"] = 0, ["end_offset"] = 4 }), ["observation_text"] = "some text",
        });
        yield return Env("prop", "trace-prop", "aijade.learning.proposed.evidence", new JsonObject
        {
            ["session_id"] = "s", ["proposal_id"] = "p-prop", ["render_ref"] = "render-a", ["applied_params_hash"] = "applied-a", ["asset_version_hash"] = "asset-a",
            ["evidence_hash"] = "e", ["claim_text"] = "a claim", ["confidence"] = 0.5,
        });
        yield return Env("op", "trace-op", "aijade.learning.constraint.opinion_evaluation", new JsonObject
        {
            ["evaluation_target"] = "t", ["claims"] = new JsonArray(new JsonObject { ["claim_text"] = "c", ["confidence"] = .5 }), ["uncertainty_notes"] = "n",
        });
    }

    [Fact]
    public async Task Liberal_matrix_writes_its_log()
    {
        var path = Environment.GetEnvironmentVariable("AIJADE_P1A_LIBERAL_LOG") ?? "";
        if (path.Length == 0)
            Assert.Skip("AIJADE_P1A_LIBERAL_LOG not set");
        await using var host = await ServerTestHost.StartAsync(new Dictionary<string, string?> { ["Aijade:DispatchObservations"] = "false", [V9Alternative.ConfigKey] = "liberal" }, worker: false);
        await File.WriteAllLinesAsync(path, await ContractDriftMatrixTests.RunAsync(host), TestContext.Current.CancellationToken);
    }

    [Fact]
    public async Task Workload_posts_the_chain_to_one_configuration()
    {
        var path = Environment.GetEnvironmentVariable("AIJADE_P1A_WORKLOAD_OUT") ?? "";
        if (path.Length == 0)
            Assert.Skip("AIJADE_P1A_WORKLOAD_OUT not set");
        var setting = Environment.GetEnvironmentVariable("AIJADE_P1A_SETTING") ?? "";
        await using var host = await ServerTestHost.StartAsync(new Dictionary<string, string?> { [V9Alternative.ConfigKey] = setting }, worker: false);
        var statuses = new JsonArray();
        var refused = "";
        foreach (var input in Chain())
        {
            var (status, _) = await host.PostAsync("/api/v1/v9/events", input);
            statuses.Add(status);
            if (status >= 400 && refused.Length == 0)
                refused = input["event_id"]!.GetValue<string>();
        }
        var audit = setting == "lineage" ? await V9Alternative.AuditAsync(host.Db, TestContext.Current.CancellationToken) : [];
        var report = new JsonObject
        {
            ["statuses"] = statuses, ["refused"] = refused, ["audit"] = new JsonArray([.. audit.Select(a => (JsonNode)a)]),
            ["eventsWritten"] = await host.CountAsync("SELECT count(*) FROM events"), ["tracesWritten"] = await host.CountAsync("SELECT count(*) FROM render_traces"),
        };
        await File.WriteAllTextAsync(path, report.ToJsonString(), TestContext.Current.CancellationToken);
    }
}
