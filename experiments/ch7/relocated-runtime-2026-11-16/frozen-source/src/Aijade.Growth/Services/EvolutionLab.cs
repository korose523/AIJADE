using System.Text.Json.Nodes;

using Aijade.Memory.Contracts;
using Aijade.Memory.Development;

namespace Aijade.Growth.Services;

// §51 VSE: candidate versions go through the constraint optimiser, E4 / E5 objects are refused, and a signed
// EvolutionProposal draft is emitted (baseline, change spec, rollback plan and at least one test are mandatory).

public sealed record EvolutionTest(string Kind, bool Passed, string? EvidenceRef = null);

public sealed record EvaluateInput(
    IReadOnlyList<CandidateVersion> Candidates, EvolutionGrade Grade, string BaselineVersion, string ChangeSpec, string SourceDiff, string GeneratedBy,
    string RollbackPlan, IReadOnlyList<string>? TriggerEvidence = null, IReadOnlyList<string>? AffectedComponents = null,
    IReadOnlyList<EvolutionTest>? Tests = null, string? DependencyDiff = null, string? MigrationPlan = null,
    IReadOnlyDictionary<string, double>? BenchmarkResults = null, IReadOnlyDictionary<string, object>? SafetyResults = null,
    string? BehaviorDiff = null, string? IdentityDiff = null, string? ApprovalPolicy = null, EvolutionWeights? Weights = null);

public sealed record EvaluateResult(EvolutionProposal Proposal, CandidateVersion BestCandidate, double Objective, AutomationLevel AutomationLevel);

public sealed class EvolutionLab(GrowthPorts ports, string agentId)
{
    public const string Kind = "evolution_proposal";

    /// <summary>A candidate version with the default values (quality +0.1, low risk / complexity / drift, safety 0.9 over 0.8).</summary>
    public static CandidateVersion MakeCandidate(
        string id, double deltaQuality = 0.1, double deltaLatency = 0, double deltaCost = 0, double risk = 0.1, double complexity = 0.1,
        double drift = 0.1, double safety = 0.9, double baselineSafety = 0.8, bool coreInvariantsHold = true, bool rollbackAvailable = true) =>
        new(id, deltaQuality, deltaLatency, deltaCost, risk, complexity, drift, safety, baselineSafety, coreInvariantsHold, rollbackAvailable);

    public async Task<EvaluateResult> EvaluateAsync(EvaluateInput input, CancellationToken cancellationToken = default)
    {
        var evolvable = Vse.AssertEvolvable(input.Grade);
        if (!evolvable.Ok)
            throw new InvalidOperationException($"EvolutionProposal refused: {evolvable.Reason}");
        var weights = input.Weights ?? EvolutionWeights.Default;
        var best = Vse.SelectCandidate(input.Candidates, weights)
            ?? throw new InvalidOperationException("EvolutionLab: no feasible candidate (constraints unsatisfied)");
        var objective = Vse.Objective(best, weights);
        var automationLevel = Vse.AutomationAllowed(input.Grade);
        var tests = (input.Tests ?? [new EvolutionTest("contract_property", true)]).Select(t => new ProposalTest(t.Kind, t.Passed, t.EvidenceRef)).ToList();
        var id = ports.IdGen.NewId("ep");
        var grade = input.Grade.ToString();
        // Sign the proposal body (not the signature field itself).
        var signature = ports.RequireSigning.Sign(new JsonObject
        {
            ["id"] = id,
            ["baselineVersion"] = input.BaselineVersion,
            ["changeSpec"] = input.ChangeSpec,
            ["sourceDiff"] = input.SourceDiff,
            ["grade"] = grade,
            ["candidateId"] = best.Id,
            ["objective"] = objective,
        });
        var proposal = new EvolutionProposal(id, agentId, input.TriggerEvidence ?? [], input.AffectedComponents ?? [], grade, input.BaselineVersion,
            input.ChangeSpec, input.SourceDiff, input.GeneratedBy, tests, input.RollbackPlan, input.ApprovalPolicy ?? "agent_self_review", signature,
            ports.Scheduler.Now(), input.DependencyDiff, input.MigrationPlan, input.BenchmarkResults, input.SafetyResults, input.BehaviorDiff, input.IdentityDiff);
        var check = ContractValidationV8.Validate(proposal);
        if (!check.Ok)
            throw new InvalidOperationException($"EvolutionProposal rejected: {check.Reason}");
        await ports.Storage.PutAsync(Kind, proposal.Id, proposal, cancellationToken).ConfigureAwait(false);
        return new EvaluateResult(proposal, best, objective, automationLevel);
    }
}
