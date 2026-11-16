using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;

using Aijade.Client.Api;
using Aijade.Client.Chat;

namespace Aijade.Client.Companion;

public sealed record SharedCompanionState(string OwnerId, string? CharacterId, Character? Character, CompanionProfile Profile,
    CompanionNotebookData Notebook, long ProfileRevision, long DataRevision, long AssetRevision, long SelectionRevision, string EffectiveTimeZone)
{
    /// <summary>A blank editable zone follows the shared server clock, including on hosts in different zones.</summary>
    [JsonIgnore]
    public CompanionProfile RuntimeProfile => Profile with { TimeZone = EffectiveTimeZone };
}

public sealed record CompanionLink(string Id, string Platform, string Subject, string OwnerId, string RelayId);

public interface ICompanionNotebook
{
    Task<CompanionNotebookData> ReadAsync(bool includeMedia = false, CancellationToken ct = default);
    Task<CompanionAsset?> AssetAsync(string id, CancellationToken ct = default);
    Task AddAsync(CompanionAsset asset, CancellationToken ct = default);
    Task RemoveAsync(string id, CancellationToken ct = default);
    Task ObserveAsync(TurnContext turn, DateTimeOffset now, CancellationToken ct = default);
}

/// <summary>One authenticated server scope, optionally delegated by a revocable QQ pairing.</summary>
public sealed class CompanionSync(AijadeApi api, string? linkId = null)
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    private string Prefix => linkId is null ? "/api/v1/companion" : "/api/v1/companion/linked/" + Uri.EscapeDataString(linkId);
    public static string CharacterKey(string? id) => Uri.EscapeDataString(id ?? "default");
    private string Path(string? id) => Prefix + "/characters/" + CharacterKey(id);
    private static SharedCompanionState State(JsonNode? node) => node?.Deserialize<SharedCompanionState>(Json) ?? throw new JsonException("Missing companion state");

    public async Task<SharedCompanionState> CurrentAsync(CancellationToken ct = default) => State(await api.SendAsync(HttpMethod.Get, Prefix, ct: ct).ConfigureAwait(false));
    public async Task<SharedCompanionState> ReadAsync(string? id, bool media = false, CancellationToken ct = default) =>
        State(await api.SendAsync(HttpMethod.Get, Path(id) + (media ? "?media=true" : ""), ct: ct).ConfigureAwait(false));
    public async Task<SharedCompanionState> SelectAsync(string? id, CancellationToken ct = default) =>
        State(await api.SendAsync(HttpMethod.Post, Prefix + "/selection", new JsonObject { ["characterId"] = id }, ct).ConfigureAwait(false));
    public async Task<SharedCompanionState> SaveProfileAsync(string? id, CompanionProfile profile, long revision, CancellationToken ct = default) =>
        State(await api.SendAsync(HttpMethod.Put, Path(id) + "/profile", new JsonObject { ["profile"] = JsonSerializer.SerializeToNode(profile, Json), ["expectedRevision"] = revision }, ct).ConfigureAwait(false));
    public async Task<SharedCompanionState> ImportAsync(string? id, string source, CompanionProfile profile, CompanionNotebookData notebook, bool activate = false, CancellationToken ct = default) =>
        State(await api.SendAsync(HttpMethod.Post, Path(id) + "/import", new JsonObject { ["source"] = source, ["profile"] = JsonSerializer.SerializeToNode(profile, Json),
            ["notebook"] = JsonSerializer.SerializeToNode(notebook, Json), ["activateIfUnset"] = activate }, ct).ConfigureAwait(false));
    public async Task<CompanionAsset?> AssetAsync(string? id, string asset, CancellationToken ct = default)
    {
        try { return (await api.SendAsync(HttpMethod.Get, Path(id) + "/assets/" + Uri.EscapeDataString(asset), ct: ct).ConfigureAwait(false))?.Deserialize<CompanionAsset>(Json); }
        catch (AijadeApiException e) when (e.Status == 404) { return null; } // removed between metadata selection and delivery
    }
    public Task AddAsync(string? id, CompanionAsset asset, CancellationToken ct = default) => api.SendAsync(HttpMethod.Post, Path(id) + "/assets", JsonSerializer.SerializeToNode(asset, Json), ct);
    public Task RemoveAsync(string? id, string asset, CancellationToken ct = default) => api.SendAsync(HttpMethod.Delete, Path(id) + "/assets/" + Uri.EscapeDataString(asset), ct: ct);
    public Task ObserveAsync(string? id, string messageId, CancellationToken ct = default) =>
        api.SendAsync(HttpMethod.Post, Path(id) + "/observe", new JsonObject { ["messageId"] = messageId }, ct);
    public async Task<CompanionDiaryDay> ReadDiaryAsync(string? id, DateOnly? day = null, CancellationToken ct = default) =>
        (await api.SendAsync(HttpMethod.Get, Path(id) + "/diary" + (day is { } date ? "?day=" + date.ToString("yyyy-MM-dd", System.Globalization.CultureInfo.InvariantCulture) : ""), ct: ct).ConfigureAwait(false))!.Deserialize<CompanionDiaryDay>(Json)!;
    public async Task<CompanionDiaryDay> SaveExchangeAsync(string? id, string userMessageId, string assistantMessageId, CancellationToken ct = default) =>
        (await api.SendAsync(HttpMethod.Post, Path(id) + "/diary", new JsonObject { ["userMessageId"] = userMessageId, ["assistantMessageId"] = assistantMessageId }, ct).ConfigureAwait(false))!.Deserialize<CompanionDiaryDay>(Json)!;
    public async Task RemoveDiaryEntryAsync(string? id, string entry, long revision, CancellationToken ct = default) =>
        _ = await api.SendAsync(HttpMethod.Delete, Path(id) + "/diary/" + Uri.EscapeDataString(entry) + "?expectedRevision=" + revision.ToString(System.Globalization.CultureInfo.InvariantCulture), ct: ct).ConfigureAwait(false);
    public async Task<DeliveryLog> DeliveriesAsync(string? id, CancellationToken ct = default) =>
        (await api.SendAsync(HttpMethod.Get, Path(id) + "/deliveries", ct: ct).ConfigureAwait(false))!.Deserialize<DeliveryLog>(Json)!;
    public async Task<DeliveryStart> BeginDeliveryAsync(string? id, string messageId, string destination, CancellationToken ct = default) =>
        (await api.SendAsync(HttpMethod.Post, Path(id) + "/deliveries", new { messageId, destination }, ct).ConfigureAwait(false))!.Deserialize<DeliveryStart>(Json)!;
    public async Task<DeliveryPartStart> StartDeliveryPartAsync(string? id, string attempt, int index, string kind, string payloadSha256, CancellationToken ct = default) =>
        (await api.SendAsync(HttpMethod.Post, Path(id) + "/deliveries/" + Uri.EscapeDataString(attempt) + "/parts", new { index, kind, payloadSha256 }, ct).ConfigureAwait(false))!.Deserialize<DeliveryPartStart>(Json)!;
    public Task CompleteDeliveryPartAsync(string? id, string attempt, int index, DeliveryReceipt receipt, CancellationToken ct = default) =>
        api.SendAsync(HttpMethod.Post, Path(id) + "/deliveries/" + Uri.EscapeDataString(attempt) + "/parts/" + index.ToString(System.Globalization.CultureInfo.InvariantCulture), receipt, ct);
    public Task FinishDeliveryAsync(string? id, string attempt, string reason, CancellationToken ct = default) =>
        api.SendAsync(HttpMethod.Post, Path(id) + "/deliveries/" + Uri.EscapeDataString(attempt) + "/finish", new { reason }, ct);
    public Task<JsonNode?> PairingCodeAsync(CancellationToken ct = default) => api.SendAsync(HttpMethod.Post, "/api/v1/companion/pairing-code", new JsonObject(), ct);
    public async Task<CompanionLink> PairAsync(string code, string subject, CancellationToken ct = default) =>
        (await api.SendAsync(HttpMethod.Post, "/api/v1/companion/pair", new JsonObject { ["code"] = code, ["subject"] = subject, ["platform"] = "qq" }, ct).ConfigureAwait(false))!.Deserialize<CompanionLink>(Json)!;
    public async Task<CompanionLink?> ResolveAsync(string subject, CancellationToken ct = default) =>
        (await api.SendAsync(HttpMethod.Get, "/api/v1/companion/resolve?subject=" + Uri.EscapeDataString(subject), ct: ct).ConfigureAwait(false))?.Deserialize<CompanionLink>(Json);
    public async Task<IReadOnlyList<CompanionLink>> LinksAsync(CancellationToken ct = default) =>
        (await api.SendAsync(HttpMethod.Get, "/api/v1/companion/links", ct: ct).ConfigureAwait(false))!.Deserialize<List<CompanionLink>>(Json)!;
    public Task UnlinkAsync(string id, CancellationToken ct = default) => api.SendAsync(HttpMethod.Delete, "/api/v1/companion/links/" + Uri.EscapeDataString(id), ct: ct);
}

/// <summary>Reads the same server document on both clients. Media is loaded only for display or delivery.</summary>
public sealed class SyncedCompanionNotebook(CompanionSync sync, string? characterId, SharedCompanionState? initial = null) : ICompanionNotebook, ICompanionDiary, ICompanionDelivery
{
    public SharedCompanionState? Latest { get; private set; } = initial;
    public async Task<CompanionNotebookData> ReadAsync(bool includeMedia = false, CancellationToken ct = default)
    {
        Latest = await sync.ReadAsync(characterId, includeMedia, ct).ConfigureAwait(false);
        return Latest.Notebook;
    }
    public Task<CompanionAsset?> AssetAsync(string id, CancellationToken ct = default) => sync.AssetAsync(characterId, id, ct);
    public Task AddAsync(CompanionAsset asset, CancellationToken ct = default) => sync.AddAsync(characterId, asset, ct);
    public Task RemoveAsync(string id, CancellationToken ct = default) => sync.RemoveAsync(characterId, id, ct);
    public Task<CompanionDiaryDay> ReadDiaryAsync(DateOnly? day = null, CancellationToken ct = default) => sync.ReadDiaryAsync(characterId, day, ct);
    public Task<CompanionDiaryDay> SaveExchangeAsync(string userMessageId, string assistantMessageId, CancellationToken ct = default) =>
        sync.SaveExchangeAsync(characterId, userMessageId, assistantMessageId, ct);
    public Task<DeliveryStart> BeginDeliveryAsync(string messageId, string destination, CancellationToken ct = default) => sync.BeginDeliveryAsync(characterId, messageId, destination, ct);
    public Task<DeliveryPartStart> StartDeliveryPartAsync(string attempt, int index, string kind, string payloadSha256, CancellationToken ct = default) =>
        sync.StartDeliveryPartAsync(characterId, attempt, index, kind, payloadSha256, ct);
    public Task CompleteDeliveryPartAsync(string attempt, int index, DeliveryReceipt receipt, CancellationToken ct = default) => sync.CompleteDeliveryPartAsync(characterId, attempt, index, receipt, ct);
    public Task FinishDeliveryAsync(string attempt, string reason, CancellationToken ct = default) => sync.FinishDeliveryAsync(characterId, attempt, reason, ct);
    public Task ObserveAsync(TurnContext turn, DateTimeOffset now, CancellationToken ct = default) =>
        turn.UserMessageId is { } id ? sync.ObserveAsync(characterId, id, ct) : throw new InvalidOperationException("A synchronized relationship needs a stored user-message identity");
}
