using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Memory.Contracts;
using Aijade.Memory.Development;

namespace Aijade.Growth.Services;

// §51 VSE promotion gate: no signed release unless the proposal and evidence pack validate, every evaluation gate is
// green, and a rollback plan exists. Only then is a SignedRelease produced with a clamped canary ratio and a signature.

public sealed record ReleaseResult(bool Ok, string? Reason = null, SignedRelease? Release = null);

public sealed class TrustedReleaseController(GrowthPorts ports, string agentId)
{
    public const string Kind = "signed_release";

    /// <param name="proposal">The evolution proposal to release.</param>
    /// <param name="evidencePack">Its evaluation evidence.</param>
    /// <param name="approvedBy">Approver (defaults to the agent).</param>
    /// <param name="canaryRatio">Canary fraction, clamped to [0, 1] (default 0.1).</param>
    /// <param name="cancellationToken">Cancellation.</param>
    public async Task<ReleaseResult> ReleaseAsync(
        EvolutionProposal proposal, EvaluationEvidencePack evidencePack, string? approvedBy = null, double? canaryRatio = null,
        CancellationToken cancellationToken = default)
    {
        var pCheck = ContractValidationV8.Validate(proposal);
        if (!pCheck.Ok)
            return new ReleaseResult(false, $"proposal invalid: {pCheck.Reason}");
        var eCheck = ContractValidationV8.Validate(evidencePack);
        if (!eCheck.Ok)
            return new ReleaseResult(false, $"evidence pack invalid: {eCheck.Reason}");
        var promote = Vse.CanPromote(evidencePack);
        if (!promote.Ok)
            return new ReleaseResult(false, $"promotion blocked: {promote.Reason}");
        if (JsText.Trim(proposal.RollbackPlan ?? "").Length == 0)
            return new ReleaseResult(false, "rollback plan required for a trusted release");

        var canary = Math.Min(1, Math.Max(0, canaryRatio ?? 0.1));
        var version = $"{proposal.BaselineVersion}-rc-{ports.IdGen.NewId("v")}";
        var id = ports.IdGen.NewId("sr");
        var signature = ports.RequireSigning.Sign(new JsonObject
        {
            ["proposalRef"] = proposal.Id,
            ["evidencePackRef"] = evidencePack.Id,
            ["version"] = version,
            ["canaryRatio"] = canary,
            ["rollbackAvailable"] = true,
        });
        var release = new SignedRelease(id, version, proposal.Id, evidencePack.Id, approvedBy ?? agentId, ports.Scheduler.Now(), signature, canary, true);
        var check = ContractValidationV8.Validate(release);
        if (!check.Ok)
            return new ReleaseResult(false, $"signed release invalid: {check.Reason}");
        await ports.Storage.PutAsync(Kind, release.Id, release, cancellationToken).ConfigureAwait(false);
        return new ReleaseResult(true, Release: release);
    }
}
