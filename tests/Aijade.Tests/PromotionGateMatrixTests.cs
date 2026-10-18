using System.Text.Json.Nodes;

using Aijade.Memory.Contracts;
using Aijade.Memory.Pgc;
using Aijade.Memory.V9;
using Aijade.Server.V9;

using Microsoft.Extensions.DependencyInjection;

namespace Aijade.Tests;

/// <summary>
/// The promotion tamper matrix (P1 §5.5): one legitimate control, eleven tampered candidates across the three gates
/// (integrity, evidence, PGC) and four irrelevant-axis probes, each run through the real PromotionService against PostgreSQL.
/// A tampered candidate must be refused with nothing written; the control and the probes must be promoted (an evolution spec
/// and an eval report). Probes record axes that by design do not bear on a gate, so that "the gate missed it" and "that axis
/// is not load-bearing" are told apart. The per-case log also drives the gate-mutation experiment (tools/Aijade.Mutation
/// with gate-mutants.json): a mutant is killed when any line turns to FAIL.
/// </summary>
public class PromotionGateMatrixTests
{
    private sealed record Case(string Gate, string Kind, string Name, PromotionJob Job);

    private static readonly PgcState4 Neutral = new(0, 0, 0, 0);

    private static ShadowParamsProposal Proposal(string id, JsonObject? candidate = null, string? inputHash = "auto", bool anchorVerified = true)
    {
        var session = $"session-{id}";
        var honest = new JsonObject { ["lr"] = 0.01 };
        var hash = inputHash == "auto" ? ShadowParams.ComputeLearningInputHash(session, id, honest) : inputHash!;
        return new ShadowParamsProposal(id, session, hash, ShadowParamsAnchorKind.ShadowParams, anchorVerified, candidate ?? honest, 0.9);
    }

    private static EvaluationEvidencePack Pack(string id) => new($"pack-{id}", id, new CoreTestGate(true, 10, 0), 0, TraceId: $"trace-{id}");

    private static PromotionJob Job(string id, EvaluationEvidencePack? pack = null, PgcState4? state = null, ShadowParamsProposal? proposal = null, string? headerHash = null)
    {
        var p = proposal ?? Proposal(id);
        return new PromotionJob($"control-job-{id}", id, p.SessionId, $"trace-{id}", 7, headerHash ?? p.InputHash, pack ?? Pack(id), p, PgcV6State: state ?? Neutral);
    }

    private static List<Case> Cases()
    {
        var cases = new List<Case> { new("integrity", "legal", "LEGAL (control)", Job("ctl-legal")) };
        cases.Add(new("integrity", "tamper", "parameters changed, hash not updated", Job("int-1", proposal: Proposal("int-1", new JsonObject { ["lr"] = 0.99 }))));
        cases.Add(new("integrity", "tamper", "dangling hash (inputHash = \"\")", Job("int-2", proposal: Proposal("int-2", inputHash: ""))));
        cases.Add(new("integrity", "tamper", "missing hash", Job("int-3", proposal: Proposal("int-3", inputHash: null!))));
        cases.Add(new("integrity", "tamper", "cross-trace (job header hash ≠ proposal hash)", Job("int-4", headerHash: "trace-of-another-job-int-4")));
        cases.Add(new("integrity", "probe", "anchorVerified = false (not load-bearing: the gate recomputes the hash)",
            Job("int-probe", proposal: Proposal("int-probe", anchorVerified: false))));
        (string Name, Func<EvaluationEvidencePack, EvaluationEvidencePack> Patch)[] evidence =
        [
            ("unit/contract/property tests failed", p => p with { UnitContractPropertyTests = new CoreTestGate(false, 10, 3) }),
            ("static analysis failed", p => p with { StaticAnalysis = new GateResult(false) }),
            ("security sandbox escape", p => p with { SecuritySandbox = new GateResult(false, 2) }),
            ("adversarial evaluation failed", p => p with { AdversarialEval = new GateResult(false) }),
            ("historical replay regression", p => p with { HistoricalReplay = new GateResult(false) }),
        ];
        for (var i = 0; i < evidence.Length; i++)
            cases.Add(new("evidence", "tamper", evidence[i].Name, Job($"evi-{i}", evidence[i].Patch(Pack($"evi-{i}")))));
        // The v6 commit verdict is driven by the f axis; a, c and d do not bear on it.
        cases.Add(new("pgc", "tamper", "f high (load-bearing axis)", Job("pgc-f", state: new PgcState4(0, 0, 0, 0.95))));
        cases.Add(new("pgc", "tamper", "all axes high", Job("pgc-all", state: new PgcState4(0.95, 0.95, 0.95, 0.95))));
        cases.Add(new("pgc", "probe", "a high (not load-bearing)", Job("pgcp-a", state: new PgcState4(0.95, 0, 0, 0))));
        cases.Add(new("pgc", "probe", "c high (not load-bearing)", Job("pgcp-c", state: new PgcState4(0, 0.95, 0, 0))));
        cases.Add(new("pgc", "probe", "d high (not load-bearing)", Job("pgcp-d", state: new PgcState4(0, 0, 0.95, 0))));
        return cases;
    }

    [Fact]
    public async Task Tampered_candidates_are_refused_without_writes_and_the_control_and_probes_are_promoted()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync();
        var promotion = host.App.Services.GetRequiredService<PromotionService>();
        async Task<long> Writes() => await host.CountAsync("SELECT count(*) FROM evolution_specs") + await host.CountAsync("SELECT count(*) FROM eval_reports");
        var log = new List<string>();
        var cases = Cases();
        foreach (var c in cases)
        {
            var before = await Writes();
            var result = await promotion.ProcessAsync(c.Job, ct);
            var writes = await Writes() - before;
            var pass = c.Kind == "tamper" ? !result.Ok && writes == 0 : result.Ok && writes == 2;
            log.Add($"{(pass ? "PASS" : "FAIL")} [{c.Kind}] {c.Gate}: {c.Name} — promoted={result.Ok} writes={writes} stage={result.Stage}");
        }
        if (Environment.GetEnvironmentVariable("AIJADE_MATRIX_LOG") is { Length: > 0 } logPath)
            await File.WriteAllLinesAsync(logPath, log, ct);
        Assert.Equal((16, 11, 4), (cases.Count, cases.Count(c => c.Kind == "tamper"), cases.Count(c => c.Kind == "probe")));
        Assert.All(log, l => Assert.StartsWith("PASS", l, StringComparison.Ordinal));
    }
}
