using System.Text.Json.Nodes;

using Aijade.Memory.Development;
using Aijade.Memory.V9;
using Aijade.Research.Integration;
using Aijade.Research.SkillBench;

namespace Aijade.Tests;

/// <summary>Admission provenance and concurrent/revoked authority controls, separate from the declared renderer batch.</summary>
public partial class ResearchEvidenceTests
{
    private const string Code = "function solve(xs) { return xs.reduce((a,b)=>a+b,0); }";

    private static SkillEvidence Evidence => new("skill", SkillEvidence.HashCode(Code), "arr-sum", Bench.ManifestSha256,
        "exec", "intent", "session", "asset", "intent", "asset", SkillEvidence.AppliedStage, SkillEvidence.AppliedStage, true, 5, 5, "pass");

    private static ShadowParamsProposal Proposal(string id)
    {
        var parameters = new JsonObject { ["emotion.preset"] = "comfort" };
        return new(id, "session", ShadowParams.ComputeLearningInputHash("session", id, parameters), ShadowParamsAnchorKind.ShadowParams,
            true, parameters, 0.9, "render", "applied", "asset");
    }

    private static JsonObject Envelope(string topic, string id, JsonObject payload) => new()
    {
        ["event_id"] = id, ["trace_id"] = "render-trace", ["correlation_id"] = "corr-" + id, ["timestamp"] = 1_794_412_800_000L,
        ["producer"] = "ch7-unit", ["origin_device"] = "test", ["privacy_level"] = 1, ["evidence_refs"] = new JsonArray(),
        ["causal_context_refs"] = new JsonArray(), ["risk_score"] = 0.1, ["idempotency_key"] = "idem-" + id,
        ["replay_mode"] = "live", ["risk_level"] = "low", ["topic"] = topic, ["payload"] = payload,
        ["tick"] = 1, ["causality"] = new JsonObject { ["inputHash"] = payload["input_hash"]?.GetValue<string>() ?? "unused" },
    };

    private static async Task AdmitAsync(ServerTestHost host)
    {
        Assert.Equal(201, (await host.PostAsync("/api/v1/v9/events", Envelope("aijade.persona.render_requested", "req", new JsonObject
        {
            ["session_id"] = "session", ["persona_snapshot_ref"] = "persona", ["intent_ref"] = "intent",
        }))).Status);
        Assert.Equal(201, (await host.PostAsync("/api/v1/v9/events", Envelope("aijade.lpm.render_ready", "ready", new JsonObject
        {
            ["session_id"] = "session", ["render_ref"] = "render", ["applied_params_hash"] = "applied", ["asset_version_hash"] = "asset",
        }))).Status);
        Assert.Equal(201, (await host.PostAsync("/api/v1/v9/events", Envelope("aijade.learning.proposed.shadow_params", "admitted", new JsonObject
        {
            ["session_id"] = "session", ["render_ref"] = "render", ["applied_params_hash"] = "applied", ["asset_version_hash"] = "asset",
            ["proposal_id"] = "p", ["input_hash"] = Proposal("p").InputHash,
            ["candidate_params"] = Proposal("p").CandidateParams.DeepClone(), ["confidence"] = 0.9,
        }))).Status);
    }

    [Fact]
    public void Unknown_or_failed_execution_cannot_become_verified_from_a_pass_verdict()
    {
        Assert.Null(Evidence.Refusal());
        Assert.Equal(SkillEvidenceState.Unknown, (Evidence with { ExecutionOk = null }).State);
        Assert.Equal(SkillEvidenceState.Failed, (Evidence with { ExecutionOk = false, Passed = 4 }).State);
        Assert.Equal("execution_failed", (Evidence with { Passed = 4 }).Refusal());
        Assert.Equal("execution_intent_mismatch", (Evidence with { ReceiptIntentId = "borrowed" }).Refusal());
        Assert.Equal("receipt_stage_insufficient", (Evidence with { ClaimedStage = "pixels_observed" }).Refusal());
        Assert.Throws<ArgumentOutOfRangeException>(() => ResearchIntentMapper.Map(DialogueAct.Refuse, "intent", "persona"));
        Assert.Throws<ArgumentOutOfRangeException>(() => ResearchIntentMapper.Map((DialogueAct)999, "intent", "persona"));
    }

    [Fact]
    public async Task A_caller_cannot_replace_an_admitted_event_with_a_boolean_or_another_proposal()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(worker: false);
        await ResearchLoopAdapter.InitializeAsync(host);
        var adapter = new ResearchLoopAdapter(host);
        var missing = await adapter.CommitAsync("absent", Evidence, Proposal("p1"), "does-not-exist", ct);
        Assert.Equal("admission_refused", missing.Outcome.Reason);
        Assert.False(missing.Outcome.Promoted);
        await AdmitAsync(host);
        var mismatched = await adapter.CommitAsync("mismatch", Evidence, Proposal("p2") with { RenderRef = "other-render" }, "admitted", ct);
        Assert.Equal("admission_proposal_mismatch", mismatched.Outcome.Reason);
        Assert.Equal(0, await host.CountAsync("SELECT count(*) FROM evolution_specs"));
    }

    [Fact]
    public async Task Concurrent_replay_promotes_once_and_old_evidence_cannot_restore_revocation()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(worker: false);
        await ResearchLoopAdapter.InitializeAsync(host);
        await AdmitAsync(host);
        var adapter = new ResearchLoopAdapter(host);
        var calls = await Task.WhenAll(adapter.CommitAsync("once", Evidence, Proposal("p"), "admitted", ct),
            adapter.CommitAsync("once", Evidence, Proposal("p"), "admitted", ct));
        Assert.Single(calls, c => c.Duplicate);
        Assert.Equal(1, await host.CountAsync("SELECT count(*) FROM evolution_specs"));
        Assert.Equal(1, await host.CountAsync("SELECT count(*) FROM eval_reports"));
        Assert.Equal(1, await host.CountAsync("SELECT count(*) FROM research_outbox"));
        await Assert.ThrowsAsync<InvalidOperationException>(() => adapter.CommitAsync("once", Evidence with { IntentId = "changed" }, Proposal("p"), "admitted", ct));
        await adapter.RevokeAsync(Evidence.SkillId, ct);
        var old = await adapter.CommitAsync("new-delivery-of-old-evidence", Evidence, Proposal("p2"), "admitted", ct);
        Assert.Equal("revoked", old.Outcome.State);
        Assert.False(old.Outcome.Promoted);
        Assert.Equal(1, await host.CountAsync("SELECT count(*) FROM evolution_specs"));
    }
}
