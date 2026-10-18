using System.Text.Json.Nodes;

using Aijade.Memory.Contracts;
using Aijade.Memory.Development;
using Aijade.Memory.Pgc;
using Aijade.Memory.V9;
using Aijade.Server.Infrastructure;

using Npgsql;

namespace Aijade.Server.V9;

// v10 §3 shadow-param promotion. A candidate is promoted (written as an evolution spec plus an eval report) only after:
//  0. the integrity gate — the proposal's input hash is recomputed from its own fields (a proposal read back from a queue is
//     not trusted) and must match the job header;
//  1. the EvidenceGate — the evaluation pack passes CanPromote;
//  2. the PGC write gate — the proposal, as a PGC candidate, gets commit_possible.
// Every gate fails closed: a refusal writes nothing and invents no memory version.

public sealed record PromotionJob(
    string JobId, string ProposalId, string SessionId, string TraceId, int Tick, string InputHash, EvaluationEvidencePack EvaluationPack,
    ShadowParamsProposal Proposal, CandidateVersion? CandidateVersion = null, PgcState4? PgcV6State = null);

public sealed record PromotionResult(bool Ok, string? Stage = null, string? Reason = null, string? EvolutionSpecId = null, string? EvalReportId = null);

public sealed class PromotionService(NpgsqlDataSource db, TimeProvider? time = null)
{
    private readonly TimeProvider clock = time ?? TimeProvider.System;

    private static double Num(JsonNode? n) => double.Parse(n!.ToJsonString(), System.Globalization.CultureInfo.InvariantCulture);

    private static GateResult? Gate(JsonNode? n) => n is JsonObject o ? new GateResult(o["passed"]!.GetValue<bool>(), o["findings"]?.GetValue<int>()) : null;

    /// <summary>Parse a job document (the queue's JSON); malformed jobs throw so they are parked as dead letters.</summary>
    public static PromotionJob ParseJob(JsonNode job)
    {
        var input = job["input"] as JsonObject ?? throw new InvalidOperationException("invalid v9 promotion job payload");
        var packJson = input["evaluationPack"] as JsonObject ?? throw new InvalidOperationException("invalid v9 promotion job payload");
        var core = packJson["unitContractPropertyTests"] as JsonObject
            ?? throw new InvalidOperationException("invalid v9 promotion job payload: missing unitContractPropertyTests");
        var dep = packJson["dependencyLicenseScan"] as JsonObject;
        var bench = packJson["benchmarkComparison"] as JsonObject;
        var pack = new EvaluationEvidencePack(packJson["id"]!.GetValue<string>(), packJson["proposalRef"]!.GetValue<string>(),
            new CoreTestGate(core["passed"]!.GetValue<bool>(), core["total"]!.GetValue<int>(), core["failed"]!.GetValue<int>()), Num(packJson["createdAt"]),
            Gate(packJson["staticAnalysis"]), dep is null ? null : (dep["passed"]!.GetValue<bool>(), dep["violations"]?.AsArray().Select(v => v!.GetValue<string>()).ToList()),
            Gate(packJson["securitySandbox"]), Gate(packJson["historicalReplay"]), Gate(packJson["adversarialEval"]),
            bench is null ? null : (bench["improved"]!.GetValue<bool>(), null));
        var proposal = ShadowParamsProposal.FromJson(input["proposal"] as JsonObject ?? throw new InvalidOperationException("invalid v9 promotion job payload"));
        CandidateVersion? candidate = input["candidateVersion"] is JsonObject c
            ? new CandidateVersion(c["id"]!.GetValue<string>(), Num(c["deltaQuality"]), Num(c["deltaLatency"]), Num(c["deltaCost"]), Num(c["risk"]),
                Num(c["complexity"]), Num(c["drift"]), Num(c["safety"]), Num(c["baselineSafety"]), c["coreInvariantsHold"]!.GetValue<bool>(),
                c["rollbackAvailable"]!.GetValue<bool>())
            : null;
        PgcState4? v6 = input["pgcV6State"] is JsonObject s ? V9RuntimeStore.ParseState(s) : null;
        return new PromotionJob(job["jobId"]!.GetValue<string>(), input["proposalId"]!.GetValue<string>(), input["sessionId"]!.GetValue<string>(),
            input["traceId"]!.GetValue<string>(), input["tick"]!.GetValue<int>(), input["inputHash"]!.GetValue<string>(), pack, proposal, candidate, v6);
    }

    private static JsonObject GateSummary(EvaluationEvidencePack p) => new()
    {
        ["unitContractPropertyTests"] = p.UnitContractPropertyTests.Passed,
        ["staticAnalysis"] = p.StaticAnalysis?.Passed,
        ["dependencyLicenseScan"] = p.DependencyLicenseScan?.Passed,
        ["securitySandbox"] = p.SecuritySandbox?.Passed,
        ["historicalReplay"] = p.HistoricalReplay?.Passed,
        ["adversarialEval"] = p.AdversarialEval?.Passed,
    };

    public async Task<PromotionResult> ProcessAsync(PromotionJob job, CancellationToken ct = default)
    {
        var anchor = ShadowParams.VerifyAnchor(job.Proposal);
        if (!anchor.Ok)
            return new PromotionResult(false, "integrity_gate", anchor.Reason);
        if (job.InputHash != job.Proposal.InputHash)
            return new PromotionResult(false, "integrity_gate", $"job inputHash disagrees with proposal: job={job.InputHash} proposal={job.Proposal.InputHash}");

        var evidenceGate = Vse.CanPromote(job.EvaluationPack);
        if (!evidenceGate.Ok)
            return new PromotionResult(false, "evidence_gate", evidenceGate.Reason);

        // The neutral policy for the sufficiency sub-check, so the decisive gate is the v6 commit verdict, not a count threshold.
        var decision = PgcGate.Decide(new PgcInput(job.SessionId, job.TraceId, [ShadowParams.AsPgcCandidate(job.Proposal)],
            new PgcReadContext(clock.GetUtcNow().ToUnixTimeMilliseconds(), [], V6State: job.PgcV6State), PgcGate.NeutralPolicy.Version));
        var entry = decision.WritePlan.Count > 0 ? decision.WritePlan[0] : null;
        var v6 = entry?.PgcStateSnapshot.V6;
        var commitPossible = v6 is not null ? v6.CommitPossible : entry?.Decision == PgcDecision.Commit;
        var commitReason = v6 is not null ? Core.Js.WireName.Of(v6.CommitReason) : entry is not null ? Core.Js.WireName.Of(entry.Decision) : "unknown";
        if (!commitPossible)
            return new PromotionResult(false, "pgc_gate", $"pgc commit rejected: {commitReason}");

        // Candidate selection is metadata (v8 §51.4), not a third gate.
        var selected = job.CandidateVersion is { } cv ? Vse.SelectCandidate([cv]) : null;
        var specId = $"evospec_{job.ProposalId}";
        var reportId = $"evalrep_{job.ProposalId}";
        var gates = GateSummary(job.EvaluationPack);
        var pgc = new JsonObject { ["commit_possible"] = true, ["commit_reason"] = commitReason };
        var spec = new JsonObject
        {
            ["proposalId"] = job.ProposalId,
            ["sessionId"] = job.SessionId,
            ["traceId"] = job.TraceId,
            ["tick"] = job.Tick,
            ["inputHash"] = job.InputHash,
            ["proposal"] = job.Proposal.ToJson(),
            ["candidateVersion"] = job.CandidateVersion is null ? null : System.Text.Json.JsonSerializer.SerializeToNode(job.CandidateVersion, System.Text.Json.JsonSerializerOptions.Web),
            ["selectedCandidateVersionId"] = selected?.Id,
            ["gates"] = gates,
            ["pgc"] = pgc,
        };
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        await using var tx = await conn.BeginTransactionAsync(ct).ConfigureAwait(false);
        var now = clock.GetUtcNow();
        await Sql.ExecAsync(conn, tx, "INSERT INTO evolution_specs (id, name, spec, created_at) VALUES ($1,$2,$3,$4)", ct,
            Sql.Text(specId), Sql.Text($"shadow-promotion:{job.ProposalId}"), Sql.Jsonb(spec), Sql.Time(now)).ConfigureAwait(false);
        await Sql.ExecAsync(conn, tx, "INSERT INTO eval_reports (id, name, metric, result, created_at) VALUES ($1,$2,$3,$4,$5)", ct,
            Sql.Text(reportId), Sql.Text($"shadow-eval:{job.ProposalId}"), Sql.Jsonb(new JsonObject { ["gates"] = gates.DeepClone(), ["pgc"] = pgc.DeepClone() }),
            Sql.Jsonb(new JsonObject { ["promoted"] = true, ["evolutionSpecId"] = specId, ["evalReportId"] = reportId }), Sql.Time(now)).ConfigureAwait(false);
        await tx.CommitAsync(ct).ConfigureAwait(false);
        return new PromotionResult(true, "promoted", "promoted", specId, reportId);
    }
}
