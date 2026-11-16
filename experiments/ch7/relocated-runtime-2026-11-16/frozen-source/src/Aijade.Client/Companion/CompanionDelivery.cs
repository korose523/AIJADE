namespace Aijade.Client.Companion;

/// <summary>A relay's observation of one outbound request, not proof that a person received or read it.</summary>
public sealed record DeliveryPart(int Index, string Kind, string PayloadSha256, DateTimeOffset StartedAt,
    string Outcome = "sending", string? PlatformMessageId = null, int? HttpStatus = null, int? Retcode = null);

public sealed record DeliveryAttempt(string Id, string MessageId, string SourceSha256, string Destination,
    DateTimeOffset StartedAt, string State = "preparing", IReadOnlyList<DeliveryPart>? Parts = null,
    DateTimeOffset? FinishedAt = null, string? FinishReason = null, string Kind = "reply", string? TriggerId = null);

public sealed record DeliveryLog(long Pruned, IReadOnlyList<DeliveryAttempt> Entries);
public sealed record DeliveryStart(DeliveryAttempt Attempt, bool Created);
public sealed record DeliveryPartStart(DeliveryPart Part, bool Created);
public sealed record DeliveryReceipt(string Outcome, string? PlatformMessageId = null, int? HttpStatus = null, int? Retcode = null);

/// <summary>Optional capability of a server-backed notebook. Local legacy notebooks acquire no remote side effects.</summary>
public interface ICompanionDelivery
{
    Task<DeliveryStart> BeginDeliveryAsync(string messageId, string destination, CancellationToken ct = default);
    Task<DeliveryPartStart> StartDeliveryPartAsync(string attempt, int index, string kind, string payloadSha256, CancellationToken ct = default);
    Task CompleteDeliveryPartAsync(string attempt, int index, DeliveryReceipt receipt, CancellationToken ct = default);
    Task FinishDeliveryAsync(string attempt, string reason, CancellationToken ct = default);
}
