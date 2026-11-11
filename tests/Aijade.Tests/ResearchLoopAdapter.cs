using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Memory.Contracts;
using Aijade.Memory.Pgc;
using Aijade.Memory.V9;
using Aijade.Research.Integration;
using Aijade.Research.SkillBench;
using Aijade.Server.V9;

using Microsoft.Extensions.DependencyInjection;

using Npgsql;

namespace Aijade.Tests;

// Chapter 7 research-only adapter, deliberately not a server registration or a product automatic-learning path.
// The authority and outbox belong to an isolated test database. Outcome HTTP delivery is after the atomic DB transaction.
internal enum ResearchConstraintCondition
{
    ModuleLocal,
    CrossModule,
}

internal sealed class ResearchLoopAdapter(ServerTestHost host, ResearchConstraintCondition condition = ResearchConstraintCondition.CrossModule)
{
    internal sealed record Outcome(string OutcomeId, string SkillId, int Revision, string State, string Reason, string CodeSha256, string Scope,
        string IntentId, string ExecutionId, bool Promoted, string? SpecId, string? ReportId);

    internal sealed record CommitResult(Outcome Outcome, bool Duplicate, PromotionResult? Promotion, PromotionJob? Job);

    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    private int invocation;

    internal List<JsonObject> PromotionAttempts { get; } = [];

    // Both arms fail closed on the execution module's own evidence. C1 omits
    // only the joins to a different module's intent/asset/stage claim.
    private static string? LocalExecutionRefusal(SkillEvidence evidence)
    {
        if (string.IsNullOrWhiteSpace(evidence.SkillId) || string.IsNullOrWhiteSpace(evidence.TaskId) ||
            string.IsNullOrWhiteSpace(evidence.IntentId) || string.IsNullOrWhiteSpace(evidence.SessionId) ||
            string.IsNullOrWhiteSpace(evidence.AssetVersion) || string.IsNullOrWhiteSpace(evidence.ExecutionId) ||
            evidence.CodeSha256.Length != 64 || !evidence.CodeSha256.All(Uri.IsHexDigit) ||
            evidence.BenchSha256.Length != 64 || !evidence.BenchSha256.All(Uri.IsHexDigit))
            return "evidence_identity_missing";
        if (evidence.ExecutionOk is null)
            return "execution_unknown";
        if (evidence.ExecutionOk != true || evidence.Passed != evidence.Total || evidence.Total <= 0)
            return "execution_failed";
        return null;
    }

    internal static async Task InitializeAsync(ServerTestHost host) => await host.ExecAsync("""
        CREATE TABLE research_skill_authority (
            skill_id text PRIMARY KEY, revision integer NOT NULL, state text NOT NULL,
            code_sha256 text NOT NULL, body jsonb NOT NULL);
        CREATE TABLE research_outcomes (
            outcome_id text PRIMARY KEY, evidence_sha256 text NOT NULL, body jsonb NOT NULL);
        CREATE TABLE research_outbox (
            outcome_id text PRIMARY KEY REFERENCES research_outcomes(outcome_id),
            body jsonb NOT NULL, status text NOT NULL DEFAULT 'pending', response jsonb);
        CREATE TABLE research_reuses (outcome_id text PRIMARY KEY, execution_ok boolean NOT NULL);
        """);

    private static async Task<int> ExecAsync(NpgsqlConnection conn, NpgsqlTransaction tx, string sql, CancellationToken ct, params object[] values)
    {
        await using var cmd = new NpgsqlCommand(sql, conn, tx);
        foreach (var value in values)
            cmd.Parameters.Add(new NpgsqlParameter { Value = value });
        return await cmd.ExecuteNonQueryAsync(ct);
    }

    private static async Task<string?> ScalarAsync(NpgsqlConnection conn, NpgsqlTransaction tx, string sql, CancellationToken ct, params object[] values)
    {
        await using var cmd = new NpgsqlCommand(sql, conn, tx);
        foreach (var value in values)
            cmd.Parameters.Add(new NpgsqlParameter { Value = value });
        var result = await cmd.ExecuteScalarAsync(ct);
        return result is null or DBNull ? null : Convert.ToString(result, System.Globalization.CultureInfo.InvariantCulture);
    }

    internal async Task<CommitResult> CommitAsync(string outcomeId, SkillEvidence evidence, ShadowParamsProposal proposal,
        string admissionEventId, CancellationToken ct)
    {
        var call = Interlocked.Increment(ref invocation);
        var evidenceHash = JsFormat.ContentHash(new JsonObject
        {
            ["evidence"] = JsonSerializer.SerializeToNode(evidence, Json), ["proposal"] = proposal.ToJson(), ["admissionEventId"] = admissionEventId,
        });
        await using var conn = await host.Db.OpenConnectionAsync(ct);
        await using var tx = await conn.BeginTransactionAsync(ct);
        await ExecAsync(conn, tx, "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", ct, evidence.SkillId);
        var old = await ScalarAsync(conn, tx, "SELECT body::text FROM research_outcomes WHERE outcome_id=$1", ct, outcomeId);
        if (old is not null)
        {
            var oldHash = await ScalarAsync(conn, tx, "SELECT evidence_sha256 FROM research_outcomes WHERE outcome_id=$1", ct, outcomeId);
            if (oldHash != evidenceHash)
                throw new InvalidOperationException("replay_identity_mismatch");
            await tx.CommitAsync(ct);
            return new CommitResult(JsonSerializer.Deserialize<Outcome>(old, Json)!, true, null, null);
        }
        var priorText = await ScalarAsync(conn, tx, "SELECT body::text FROM research_skill_authority WHERE skill_id=$1 FOR UPDATE", ct, evidence.SkillId);
        var prior = priorText is null ? null : JsonSerializer.Deserialize<Outcome>(priorText, Json);
        var admittedText = await ScalarAsync(conn, tx,
            "SELECT payload::text FROM events WHERE event_id=$1 AND topic='aijade.learning.proposed.shadow_params'", ct, admissionEventId);
        var admitted = admittedText is null ? null : JsonNode.Parse(admittedText);
        var proposalBound = admitted?["session_id"]?.GetValue<string>() == evidence.SessionId && proposal.SessionId == evidence.SessionId &&
            admitted?["render_ref"]?.GetValue<string>() == proposal.RenderRef && admitted?["applied_params_hash"]?.GetValue<string>() == proposal.AppliedParamsHash &&
            admitted?["asset_version_hash"]?.GetValue<string>() == proposal.AssetVersionHash &&
            admitted?["proposal_id"]?.GetValue<string>() == proposal.ProposalId && admitted?["input_hash"]?.GetValue<string>() == proposal.InputHash &&
            admitted?["candidate_params"] is JsonObject admittedParams && JsFormat.ContentHash(admittedParams) == JsFormat.ContentHash(proposal.CandidateParams);
        var reason = admitted is null ? "admission_refused" : !proposalBound ? "admission_proposal_mismatch" :
            condition == ResearchConstraintCondition.CrossModule ? evidence.Refusal() : LocalExecutionRefusal(evidence);
        if (prior?.State == "revoked")
            reason = "skill_revoked";
        else if (prior is not null && prior.CodeSha256 != evidence.CodeSha256)
            reason = "skill_code_changed";
        var state = reason == "skill_revoked" ? "revoked" : reason is null ? "verified" :
            evidence.ExecutionOk == false ? "failed" : "unknown";
        PromotionResult? promoted = null;
        PromotionJob? job = null;
        if (reason is null)
        {
            var pack = new EvaluationEvidencePack("pack-" + outcomeId, proposal.ProposalId,
                new CoreTestGate(true, evidence.Total, 0), 0, TraceId: evidence.ExecutionId);
            job = new PromotionJob("job-" + outcomeId, proposal.ProposalId, evidence.SessionId, evidence.ExecutionId, 1,
                proposal.InputHash, pack, proposal, PgcV6State: new PgcState4(0, 0, 0, 0));
            var observation = new JsonObject
            {
                ["invocation"] = call, ["job"] = JsonSerializer.SerializeToNode(job, Json),
                ["transactionMode"] = condition == ResearchConstraintCondition.CrossModule ? "caller_owned" : "service_owned",
            };
            PromotionAttempts.Add(observation);
            var service = host.App.Services.GetRequiredService<PromotionService>();
            promoted = condition == ResearchConstraintCondition.CrossModule
                ? await service.ProcessAsync(job, conn, tx, ct)
                : await service.ProcessAsync(job, ct);
            observation["serviceResult"] = JsonSerializer.SerializeToNode(promoted, Json);
            if (!promoted.Ok)
            {
                state = "unknown";
                reason = "promotion_" + promoted.Stage;
            }
        }
        var outcome = new Outcome(outcomeId, evidence.SkillId, (prior?.Revision ?? 0) + 1, state, reason ?? "qualified",
            evidence.CodeSha256, evidence.Scope, evidence.IntentId, evidence.ExecutionId, promoted?.Ok == true,
            promoted?.EvolutionSpecId, promoted?.EvalReportId);
        var body = JsonSerializer.Serialize(outcome, Json);
        await ExecAsync(conn, tx, """
            INSERT INTO research_skill_authority(skill_id,revision,state,code_sha256,body) VALUES($1,$2,$3,$4,$5::jsonb)
            ON CONFLICT(skill_id) DO UPDATE SET revision=excluded.revision,state=excluded.state,code_sha256=excluded.code_sha256,body=excluded.body
            """, ct, evidence.SkillId, outcome.Revision, outcome.State, outcome.CodeSha256, body);
        await ExecAsync(conn, tx, "INSERT INTO research_outcomes VALUES($1,$2,$3::jsonb)", ct, outcomeId, evidenceHash, body);
        var perception = Perception("outcome-" + outcomeId, evidence.SessionId, "ch7_outcome " + outcomeId + " " + body);
        await ExecAsync(conn, tx, "INSERT INTO research_outbox(outcome_id,body) VALUES($1,$2::jsonb)", ct, outcomeId, perception.ToJsonString());
        await tx.CommitAsync(ct);
        return new CommitResult(outcome, false, promoted, job);
    }

    internal static JsonObject Perception(string eventId, string session, string content) => new()
    {
        ["event_id"] = eventId, ["session_id"] = session, ["trace_id"] = "trace-" + eventId, ["correlation_id"] = "corr-" + eventId,
        ["timestamp"] = 1_794_412_800_000L, ["origin_device"] = "ch7-research", ["privacy_level"] = 1, ["risk_score"] = 0.1,
        ["source"] = "chat", ["content"] = content,
    };

    internal async Task<JsonObject> DeliverAsync(string outcomeId)
    {
        var status = await host.ScalarAsync("SELECT status FROM research_outbox WHERE outcome_id=$1", outcomeId);
        if (status == "accepted")
            return new JsonObject { ["duplicate"] = true, ["status"] = "accepted" };
        var body = await host.ScalarAsync("SELECT body::text FROM research_outbox WHERE outcome_id=$1", outcomeId);
        if (body is null)
            return new JsonObject { ["status"] = "absent" };
        var (code, response) = await host.PostAsync("/api/v1/v9/perception", JsonNode.Parse(body)!);
        var accepted = code is >= 200 and < 300;
        var record = new JsonObject { ["status"] = accepted ? "accepted" : "refused", ["httpStatus"] = code, ["request"] = JsonNode.Parse(body), ["response"] = response };
        await host.ExecAsync("UPDATE research_outbox SET status=$2,response=$3::jsonb WHERE outcome_id=$1", outcomeId, accepted ? "accepted" : "refused", record.ToJsonString());
        return record;
    }

    internal async Task RevokeAsync(string skillId, CancellationToken ct)
    {
        await using var conn = await host.Db.OpenConnectionAsync(ct);
        await using var tx = await conn.BeginTransactionAsync(ct);
        await ExecAsync(conn, tx, "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", ct, skillId);
        var body = await ScalarAsync(conn, tx, "SELECT body::text FROM research_skill_authority WHERE skill_id=$1 FOR UPDATE", ct, skillId)
            ?? throw new InvalidOperationException("unknown_skill");
        var old = JsonSerializer.Deserialize<Outcome>(body, Json)!;
        var next = old with { State = "revoked", Reason = "explicit_revocation", Revision = old.Revision + 1 };
        await ExecAsync(conn, tx, "UPDATE research_skill_authority SET revision=$2,state='revoked',body=$3::jsonb WHERE skill_id=$1", ct,
            skillId, next.Revision, JsonSerializer.Serialize(next, Json));
        await tx.CommitAsync(ct);
    }

    internal async Task<JsonObject> Round2Async(string outcomeId, string skillId, string code, BenchTask task, CancellationToken ct)
    {
        var path = "/api/v1/memory/items/?q=" + Uri.EscapeDataString("ch7_outcome " + outcomeId) + "&limit=6";
        var (status, response) = await host.SendAsync(HttpMethod.Get, path);
        var items = response?["items"]?.AsArray() ?? [];
        var item = items.FirstOrDefault(i => i?["content"]?.GetValue<string>().StartsWith("ch7_outcome " + outcomeId + " ", StringComparison.Ordinal) == true);
        var observation = new JsonObject { ["requestPath"] = path, ["status"] = status, ["response"] = response, ["retrieved"] = item is not null, ["executed"] = false };
        if (item is null)
        {
            observation["reason"] = "outcome_not_retrieved";
            return observation;
        }
        var prefix = "ch7_outcome " + outcomeId + " ";
        var memory = JsonSerializer.Deserialize<Outcome>(item["content"]!.GetValue<string>()[prefix.Length..], Json)!;
        await using var conn = await host.Db.OpenConnectionAsync(ct);
        await using var tx = await conn.BeginTransactionAsync(ct);
        await ExecAsync(conn, tx, "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", ct, skillId);
        var raw = await ScalarAsync(conn, tx, "SELECT body::text FROM research_skill_authority WHERE skill_id=$1 FOR UPDATE", ct, skillId);
        var current = raw is null ? null : JsonSerializer.Deserialize<Outcome>(raw, Json);
        string? refusal = current?.State != "verified" ? "authority_" + (current?.State ?? "absent") :
            memory.SkillId != skillId || memory.OutcomeId != outcomeId || memory.CodeSha256 != SkillEvidence.HashCode(code) ||
            memory.State != "verified" || memory.Revision != current.Revision || memory.Scope != current.Scope || memory.ExecutionId != current.ExecutionId ||
            memory.IntentId != current.IntentId || memory.OutcomeId != current.OutcomeId ? "memory_authority_mismatch" : null;
        if (refusal is null && await ScalarAsync(conn, tx, "SELECT outcome_id FROM research_reuses WHERE outcome_id=$1", ct, outcomeId) is not null)
            refusal = "reuse_already_recorded";
        if (refusal is null)
        {
            var execution = new Sandbox { IsolateArguments = true }.RunTask(code, task);
            observation["executed"] = true;
            observation["execution"] = JsonSerializer.SerializeToNode(execution, Json);
            await ExecAsync(conn, tx, "INSERT INTO research_reuses VALUES($1,$2)", ct, outcomeId, execution.Ok);
        }
        observation["reason"] = refusal ?? "verified_reuse";
        observation["authority"] = current is null ? null : JsonSerializer.SerializeToNode(current, Json);
        observation["memoryOutcome"] = JsonSerializer.SerializeToNode(memory, Json);
        await tx.CommitAsync(ct);
        return observation;
    }

    internal async Task<JsonObject> SnapshotAsync() => new()
    {
        ["specs"] = await host.CountAsync("SELECT count(*) FROM evolution_specs"),
        ["reports"] = await host.CountAsync("SELECT count(*) FROM eval_reports"),
        ["specRows"] = JsonNode.Parse(await host.ScalarAsync("SELECT coalesce(jsonb_agg(jsonb_build_object('id',id,'spec',spec)),'[]'::jsonb)::text FROM evolution_specs") ?? "[]"),
        ["reportRows"] = JsonNode.Parse(await host.ScalarAsync("SELECT coalesce(jsonb_agg(jsonb_build_object('id',id,'metric',metric,'result',result)),'[]'::jsonb)::text FROM eval_reports") ?? "[]"),
        ["authority"] = JsonNode.Parse(await host.ScalarAsync("SELECT coalesce(jsonb_agg(body),'[]'::jsonb)::text FROM research_skill_authority") ?? "[]"),
        ["outcomes"] = JsonNode.Parse(await host.ScalarAsync("SELECT coalesce(jsonb_agg(body),'[]'::jsonb)::text FROM research_outcomes") ?? "[]"),
        ["outboxCount"] = await host.CountAsync("SELECT count(*) FROM research_outbox"),
        ["outcomeMemoryCount"] = await host.CountAsync("SELECT count(*) FROM evidence_packs WHERE id LIKE 'ep_outcome-%'"),
        ["reuseCount"] = await host.CountAsync("SELECT count(*) FROM research_reuses"),
    };
}
