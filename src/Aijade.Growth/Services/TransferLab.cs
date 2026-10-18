using Aijade.Memory.Contracts;

namespace Aijade.Growth.Services;

// §49.3: a source → target TransferRecord. A validated transfer (explicitly, or carried from a prior transfer) is T2,
// which the contract requires to be validated; otherwise T1 and unvalidated. The negative-transfer signal defaults to 0.

/// <param name="SourceDomain">Domain the knowledge comes from.</param>
/// <param name="TargetDomain">Domain it is applied to.</param>
/// <param name="Path">The reasoning path that produced the transfer.</param>
/// <param name="PriorTransfer">A prior transfer whose validation is carried forward.</param>
/// <param name="Validated">Explicit validation (defaults to the prior transfer's).</param>
/// <param name="InvariantsPreserved">Invariants that carried over.</param>
/// <param name="BrokenConditions">Conditions that broke.</param>
/// <param name="PredictedOutcome">Predicted outcome (default "pending").</param>
/// <param name="MeasuredOutcome">Measured outcome (default "pending").</param>
/// <param name="NegativeTransferSignal">Negative-transfer signal in [0, 1] (default 0).</param>
public sealed record ProposeTransferInput(
    string SourceDomain, string TargetDomain, AssociationPath? Path = null, TransferRecord? PriorTransfer = null, bool? Validated = null,
    IReadOnlyList<string>? InvariantsPreserved = null, IReadOnlyList<string>? BrokenConditions = null, string? PredictedOutcome = null,
    string? MeasuredOutcome = null, double? NegativeTransferSignal = null);

public sealed class TransferLab(GrowthPorts ports, string agentId, string userScope)
{
    public const string Kind = "transfer_record";

    public async Task<TransferRecord> ProposeAsync(ProposeTransferInput input, CancellationToken cancellationToken = default)
    {
        var validated = input.Validated ?? input.PriorTransfer?.Validated ?? false;
        var record = new TransferRecord(ports.IdGen.NewId("tr"), agentId, userScope, input.SourceDomain, input.TargetDomain,
            input.InvariantsPreserved ?? [], input.BrokenConditions ?? [], input.PredictedOutcome ?? "pending", input.MeasuredOutcome ?? "pending",
            input.NegativeTransferSignal ?? 0, validated ? "T2" : "T1", validated, ports.Scheduler.Now());
        var check = ContractValidationV8.Validate(record);
        if (!check.Ok)
            throw new InvalidOperationException($"TransferRecord rejected: {check.Reason}");
        await ports.Storage.PutAsync(Kind, record.Id, record, cancellationToken).ConfigureAwait(false);
        return record;
    }

    public Task<TransferRecord?> GetAsync(string id, CancellationToken cancellationToken = default) =>
        ports.Storage.GetAsync<TransferRecord>(Kind, id, cancellationToken);
}
