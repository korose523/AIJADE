using System.Globalization;
using System.Text.Json.Nodes;

using Aijade.Client.Companion;
using Aijade.Server.Auth;
using Aijade.Server.Infrastructure;

using Npgsql;

namespace Aijade.Server.Product;

public sealed partial class CompanionSyncStore
{
    private sealed record DeliveryItem(DeliveryAttempt Attempt, string Actor, string? Grant);
    private sealed record DeliveryDocument(long Pruned = 0, IReadOnlyList<DeliveryItem>? Items = null);
    private static string DeliveryKey(string owner, string? character) => Key(owner, character) + ".deliveries";
    private static ApiException DeliveryConflict(string message) => new(409, "DELIVERY_CONFLICT", message);

    private static DeliveryDocument ExpireDeliveries(DeliveryDocument doc, DateTimeOffset now) => doc with
    {
        Items = [.. (doc.Items ?? []).Select(item => item.Attempt.FinishedAt is null && item.Attempt.StartedAt.AddMinutes(10) <= now
            ? item with { Attempt = item.Attempt with { State = "unknown", FinishedAt = now, FinishReason = "expired",
                Parts = [.. (item.Attempt.Parts ?? []).Select(p => p.Outcome == "sending" ? p with { Outcome = "unknown" } : p)] } }
            : item)],
    };

    public async Task<DeliveryLog> DeliveriesAsync(string owner, string? character, CancellationToken ct)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        _ = await CardAsync(conn, owner, character, ct).ConfigureAwait(false);
        var doc = ExpireDeliveries(await ReadAsync<DeliveryDocument>(conn, null, DeliveryKey(owner, character), ct).ConfigureAwait(false) ?? new(), time.GetUtcNow());
        return new(doc.Pruned, [.. (doc.Items ?? []).Select(i => i.Attempt).OrderByDescending(i => i.StartedAt)]);
    }

    private async Task<T> ChangeDeliveryAsync<T>(string owner, string? character,
        Func<DeliveryDocument, NpgsqlConnection, NpgsqlTransaction, Task<(DeliveryDocument Document, T Result)>> change, CancellationToken ct)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        _ = await CardAsync(conn, owner, character, ct).ConfigureAwait(false);
        await using var tx = await conn.BeginTransactionAsync(ct).ConfigureAwait(false);
        var key = DeliveryKey(owner, character);
        await LockAsync(conn, tx, key, ct).ConfigureAwait(false);
        var doc = ExpireDeliveries(await ReadAsync<DeliveryDocument>(conn, tx, key, ct).ConfigureAwait(false) ?? new(), time.GetUtcNow());
        var (updated, result) = await change(doc, conn, tx).ConfigureAwait(false);
        await SaveAsync(conn, tx, key, updated, ct).ConfigureAwait(false);
        await tx.CommitAsync(ct).ConfigureAwait(false);
        return result;
    }

    public Task<DeliveryStart> BeginDeliveryAsync(string owner, string actor, string? grant, string? character, string message, string destination, CancellationToken ct)
    {
        if (destination.Length > 20 || !destination.All(char.IsAsciiDigit) || !long.TryParse(destination, NumberStyles.None, CultureInfo.InvariantCulture, out var number) || number <= 0)
            throw Invalid("A private QQ destination is required");
        return ChangeDeliveryAsync(owner, character, async (doc, conn, tx) =>
        {
            if (grant is not null)
            {
                var link = await ReadAsync<CompanionLink>(conn, tx, "companion.binding." + grant, ct).ConfigureAwait(false);
                if (link is null || link.RelayId != actor || link.OwnerId != owner || link.Subject != destination || link.Platform != "qq") throw ApiException.NotFound();
            }
            var sources = await Sql.QueryAsync(conn, tx,
                "SELECT m.content,c.character_id FROM chat_messages m JOIN chats c ON c.id=m.chat_id " +
                "WHERE m.id=$1 AND m.role='assistant' AND c.owner_id=$2 AND c.deleted_at IS NULL",
                r => (Text: r.GetString(0), Character: r.IsDBNull(1) ? null : r.GetString(1)), ct, Sql.Text(message), Sql.Text(actor)).ConfigureAwait(false);
            if (sources.Count != 1 || (actor == owner && sources[0].Character != character) || (sources[0].Character is not null && sources[0].Character != character))
                throw ApiException.NotFound();
            var id = Hash(message + ":qq:" + destination);
            var items = (doc.Items ?? []).ToList();
            if (items.FirstOrDefault(i => i.Attempt.Id == id) is { } existing) return (doc, new DeliveryStart(existing.Attempt, false));
            var pruned = doc.Pruned;
            if (items.Count >= 128)
            {
                var oldest = items.Where(i => i.Attempt.FinishedAt is not null).MinBy(i => i.Attempt.StartedAt)
                    ?? throw DeliveryConflict("Too many unfinished delivery records");
                items.Remove(oldest); pruned++;
            }
            var attempt = new DeliveryAttempt(id, message, Hash(sources[0].Text), destination, time.GetUtcNow(), Parts: []);
            items.Add(new(attempt, actor, grant));
            return (new DeliveryDocument(pruned, items), new DeliveryStart(attempt, true));
        }, ct);
    }

    private Task<T> ChangeAttemptAsync<T>(string owner, string actor, string? grant, string? character, string attempt,
        Func<DeliveryAttempt, (DeliveryAttempt Updated, T Result)> change, CancellationToken ct) =>
        ChangeDeliveryAsync(owner, character, (doc, _, _) =>
        {
            var items = (doc.Items ?? []).ToList();
            var index = items.FindIndex(i => i.Attempt.Id == attempt && i.Actor == actor && i.Grant == grant);
            if (index < 0) throw ApiException.NotFound();
            var (updated, result) = change(items[index].Attempt);
            items[index] = items[index] with { Attempt = updated };
            return Task.FromResult((doc with { Items = items }, result));
        }, ct);

    public Task<DeliveryPartStart> StartDeliveryPartAsync(string owner, string actor, string? grant, string? character, string attempt, int index, string kind, string digest, CancellationToken ct)
    {
        if (index is < 0 or >= 64 || kind is not ("text" or "image" or "record") || digest.Length != 64 || !digest.All(c => char.IsAsciiHexDigitLower(c)))
            throw Invalid("A bounded part with a SHA-256 digest is required");
        return ChangeAttemptAsync(owner, actor, grant, character, attempt, a =>
        {
            var parts = (a.Parts ?? []).ToList();
            if (parts.FirstOrDefault(p => p.Index == index) is { } existing)
            {
                if (existing.Kind != kind || existing.PayloadSha256 != digest) throw DeliveryConflict("The part identity changed");
                return (a, new DeliveryPartStart(existing, false));
            }
            if (a.FinishedAt is not null || index != parts.Count || parts.Any(p => p.Outcome != "acknowledged")) throw DeliveryConflict("The attempt cannot dispatch another part");
            var part = new DeliveryPart(index, kind, digest, time.GetUtcNow()); parts.Add(part);
            return (a with { State = "sending", Parts = parts }, new DeliveryPartStart(part, true));
        }, ct);
    }

    public Task<int> CompleteDeliveryPartAsync(string owner, string actor, string? grant, string? character, string attempt, int index, DeliveryReceipt receipt, CancellationToken ct)
    {
        if (receipt.Outcome is not ("acknowledged" or "rejected" or "unknown") || receipt.HttpStatus is < 100 or > 599 || receipt.PlatformMessageId?.Length > 128)
            throw Invalid("Invalid delivery observation");
        if (receipt.Outcome == "acknowledged" && (receipt.HttpStatus is null or < 200 or >= 300 || receipt.Retcode != 0 ||
            !long.TryParse(receipt.PlatformMessageId, NumberStyles.AllowLeadingSign, CultureInfo.InvariantCulture, out _)))
            throw Invalid("Acknowledgement requires HTTP success, retcode zero and a numeric platform message identity");
        if (receipt.Outcome != "acknowledged" && receipt.PlatformMessageId is not null) throw Invalid("An unconfirmed observation cannot claim a platform identity");
        if (receipt.Outcome == "rejected" && !(receipt.HttpStatus is >= 400 and < 500 and not 408 ||
            receipt.HttpStatus is >= 200 and < 300 && receipt.Retcode is not null and not 0 and not 1))
            throw Invalid("Rejection requires an explicit failure observation");
        return ChangeAttemptAsync(owner, actor, grant, character, attempt, a =>
        {
            var parts = (a.Parts ?? []).ToList(); var at = parts.FindIndex(p => p.Index == index);
            if (at < 0) throw ApiException.NotFound();
            var part = parts[at];
            if (part.Outcome != "sending")
            {
                if (new DeliveryReceipt(part.Outcome, part.PlatformMessageId, part.HttpStatus, part.Retcode) != receipt) throw DeliveryConflict("A recorded observation cannot be rewritten");
                return (a, 0);
            }
            if (a.FinishedAt is not null) throw DeliveryConflict("The attempt has ended");
            parts[at] = part with { Outcome = receipt.Outcome, PlatformMessageId = receipt.PlatformMessageId, HttpStatus = receipt.HttpStatus, Retcode = receipt.Retcode };
            return (a with { Parts = parts }, 0);
        }, ct);
    }

    public Task<int> FinishDeliveryAsync(string owner, string actor, string? grant, string? character, string attempt, string reason, CancellationToken ct)
    {
        if (reason is not ("completed" or "interrupted" or "failed")) throw Invalid("Invalid finish reason");
        return ChangeAttemptAsync(owner, actor, grant, character, attempt, a =>
        {
            if (a.FinishedAt is not null)
            {
                if (a.FinishReason != reason) throw DeliveryConflict("The attempt has ended");
                return (a, 0);
            }
            var parts = (a.Parts ?? []).Select(p => p.Outcome == "sending" ? p with { Outcome = "unknown" } : p).ToList();
            var state = parts.Any(p => p.Outcome == "unknown") ? "unknown" : parts.Any(p => p.Outcome == "rejected") ? "rejected" :
                reason == "completed" && parts.Count > 0 ? "acknowledged" : "interrupted";
            return (a with { State = state, Parts = parts, FinishReason = reason, FinishedAt = time.GetUtcNow() }, 0);
        }, ct);
    }

    private static string DeliveryString(JsonObject body, string key) => body[key] is JsonValue v && v.TryGetValue<string>(out var s) && s.Length is > 0 and <= 128 ? s : throw Invalid("Short delivery identities required");
    private static void MapDelivery(RouteGroupBuilder group)
    {
        static string? Grant(HttpContext c) => c.Request.RouteValues["linkId"]?.ToString();
        group.MapGet("/characters/{id}/deliveries", async (string id, HttpContext c, CompanionSyncStore store, CancellationToken ct) =>
            await store.DeliveriesAsync(await ScopeAsync(c, store, ct).ConfigureAwait(false), CharacterId(id), ct).ConfigureAwait(false));
        group.MapPost("/characters/{id}/deliveries", async (string id, HttpContext c, CompanionSyncStore store, CancellationToken ct) =>
        {
            var owner = await ScopeAsync(c, store, ct).ConfigureAwait(false); var b = await BodyAsync(c, ct).ConfigureAwait(false);
            return await store.BeginDeliveryAsync(owner, c.User.UserId(), Grant(c), CharacterId(id), DeliveryString(b, "messageId"), DeliveryString(b, "destination"), ct).ConfigureAwait(false);
        });
        group.MapPost("/characters/{id}/deliveries/{attempt}/parts", async (string id, string attempt, HttpContext c, CompanionSyncStore store, CancellationToken ct) =>
        {
            var owner = await ScopeAsync(c, store, ct).ConfigureAwait(false); var b = await BodyAsync(c, ct).ConfigureAwait(false);
            var index = b["index"] is JsonValue v && v.TryGetValue<int>(out var i) ? i : throw Invalid("Part index required");
            return await store.StartDeliveryPartAsync(owner, c.User.UserId(), Grant(c), CharacterId(id), attempt, index, DeliveryString(b, "kind"), DeliveryString(b, "payloadSha256"), ct).ConfigureAwait(false);
        });
        group.MapPost("/characters/{id}/deliveries/{attempt}/parts/{index:int}", async (string id, string attempt, int index, HttpContext c, CompanionSyncStore store, CancellationToken ct) =>
        {
            var owner = await ScopeAsync(c, store, ct).ConfigureAwait(false); var b = await BodyAsync(c, ct).ConfigureAwait(false);
            static int? Number(JsonObject b, string key) => b[key] is null ? null : b[key] is JsonValue v && v.TryGetValue<int>(out var n) ? n : throw Invalid("Integer receipt fields required");
            var receipt = new DeliveryReceipt(DeliveryString(b, "outcome"), b["platformMessageId"] is null ? null : DeliveryString(b, "platformMessageId"), Number(b, "httpStatus"), Number(b, "retcode"));
            await store.CompleteDeliveryPartAsync(owner, c.User.UserId(), Grant(c), CharacterId(id), attempt, index, receipt, ct).ConfigureAwait(false);
            return Results.NoContent();
        });
        group.MapPost("/characters/{id}/deliveries/{attempt}/finish", async (string id, string attempt, HttpContext c, CompanionSyncStore store, CancellationToken ct) =>
        {
            var owner = await ScopeAsync(c, store, ct).ConfigureAwait(false); var b = await BodyAsync(c, ct).ConfigureAwait(false);
            await store.FinishDeliveryAsync(owner, c.User.UserId(), Grant(c), CharacterId(id), attempt, DeliveryString(b, "reason"), ct).ConfigureAwait(false);
            return Results.NoContent();
        });
    }
}
