using System.Text.Json.Nodes;

using Aijade.Client.Companion;
using Aijade.Server.Auth;
using Aijade.Server.Infrastructure;

using Npgsql;

namespace Aijade.Server.Product;

public sealed partial class CompanionSyncStore
{
    // Separate, lazy documents: ordinary chat/profile reads never load diary excerpts. No new database or worker.
    private sealed record DiaryDocument(long Revision = 0, IReadOnlyList<CompanionDiaryEntry>? Entries = null)
    {
        [System.Text.Json.Serialization.JsonIgnore]
        public IReadOnlyList<CompanionDiaryEntry> Items => Entries ?? [];
    }
    private sealed record DiarySource(string Id, string Chat, string Role, string Content, long Seq, DateTimeOffset At, JsonObject? Meta, string? Character);
    private static string DiaryKey(string owner, string? character) => Key(owner, character) + ".diary";

    private async Task<TimeZoneInfo> DiaryZoneAsync(NpgsqlConnection conn, NpgsqlTransaction? tx, string owner, string? character, CancellationToken ct)
    {
        var doc = await ReadAsync<Document>(conn, tx, Key(owner, character), ct).ConfigureAwait(false) ?? new();
        return string.IsNullOrWhiteSpace(doc.Profile.TimeZone) ? time.LocalTimeZone : doc.Profile.Zone;
    }

    public async Task<CompanionDiaryDay> DiaryAsync(string owner, string? character, DateOnly? day, CancellationToken ct)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        _ = await CardAsync(conn, owner, character, ct).ConfigureAwait(false);
        var zone = await DiaryZoneAsync(conn, null, owner, character, ct).ConfigureAwait(false);
        var date = day ?? DateOnly.FromDateTime(TimeZoneInfo.ConvertTime(time.GetUtcNow(), zone).DateTime);
        var doc = await ReadAsync<DiaryDocument>(conn, null, DiaryKey(owner, character), ct).ConfigureAwait(false) ?? new();
        return new(date, EffectiveZone(zone), doc.Revision, [.. doc.Items.Where(e => e.Day == date).OrderBy(e => e.User.At)]);
    }

    public async Task<CompanionDiaryDay> SaveDiaryAsync(string owner, string actor, string? character, string userId, string assistantId, CancellationToken ct)
    {
        var key = DiaryKey(owner, character);
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        _ = await CardAsync(conn, owner, character, ct).ConfigureAwait(false);
        await using var tx = await conn.BeginTransactionAsync(ct).ConfigureAwait(false);
        await LockAsync(conn, tx, key, ct).ConfigureAwait(false);
        var sources = await Sql.QueryAsync(conn, tx,
            "SELECT m.id,m.chat_id,m.role,m.content,m.seq,m.created_at,m.meta::text,c.character_id " +
            "FROM chat_messages m JOIN chats c ON c.id=m.chat_id WHERE (m.id=$1 OR m.id=$2) AND c.owner_id=$3 AND c.deleted_at IS NULL",
            r => new DiarySource(r.GetString(0), r.GetString(1), r.GetString(2), r.GetString(3), r.GetInt64(4), r.GetFieldValue<DateTimeOffset>(5),
                r.IsDBNull(6) ? null : JsonNode.Parse(r.GetString(6)) as JsonObject, r.IsDBNull(7) ? null : r.GetString(7)),
            ct, Sql.Text(userId), Sql.Text(assistantId), Sql.Text(actor)).ConfigureAwait(false);
        var user = sources.FirstOrDefault(s => s.Id == userId && s.Role == "user");
        var assistant = sources.FirstOrDefault(s => s.Id == assistantId && s.Role == "assistant");
        if (user is null || assistant is null || user.Chat != assistant.Chat || user.Seq >= assistant.Seq)
            throw ApiException.NotFound();
        // Owner chats carry their role. Paired relay chats may have no character_id because the owner card is private.
        if ((actor == owner && user.Character != character) || (user.Character is not null && user.Character != character))
            throw Invalid("The exchange belongs to another character");
        var between = await Sql.QueryAsync(conn, tx,
            "SELECT count(*) FROM chat_messages WHERE chat_id=$1 AND seq>$2 AND seq<$3 AND role IN ('user','assistant')",
            r => r.GetInt64(0), ct, Sql.Text(user.Chat), Sql.P(user.Seq), Sql.P(assistant.Seq)).ConfigureAwait(false);
        if (between[0] != 0 || CompanionMediaTurn.IsRequest(user.Content) || assistant.Meta?.ContainsKey("initiative") == true || assistant.Meta?.ContainsKey("reminder") == true)
            throw Invalid("Choose one completed ordinary exchange, not a command or an unsolicited message");
        var doc = await ReadAsync<DiaryDocument>(conn, tx, key, ct).ConfigureAwait(false) ?? new();
        var id = Hash(user.Id + ":" + assistant.Id);
        var entry = doc.Items.FirstOrDefault(e => e.Id == id);
        if (entry is null)
        {
            if (doc.Items.Count >= 128) throw Invalid("The diary is full; remove an entry before saving another");
            var zone = await DiaryZoneAsync(conn, tx, owner, character, ct).ConfigureAwait(false);
            var date = DateOnly.FromDateTime(TimeZoneInfo.ConvertTime(user.At, zone).DateTime);
            entry = new(id, user.Chat, date, EffectiveZone(zone), time.GetUtcNow(), Quote(user), Quote(assistant));
            doc = new(doc.Revision + 1, [.. doc.Items, entry]);
            await SaveAsync(conn, tx, key, doc, ct).ConfigureAwait(false);
        }
        await tx.CommitAsync(ct).ConfigureAwait(false);
        return await DiaryAsync(owner, character, entry.Day, ct).ConfigureAwait(false);
    }

    private static DiaryQuote Quote(DiarySource source)
    {
        const int max = 1_000;
        var end = Math.Min(max, source.Content.Length);
        if (end < source.Content.Length && end > 0 && char.IsHighSurrogate(source.Content[end - 1]) && char.IsLowSurrogate(source.Content[end])) end--;
        return new(source.Id, source.At, source.Content[..end], Hash(source.Content), end != source.Content.Length);
    }

    public async Task RemoveDiaryAsync(string owner, string? character, string entry, long revision, CancellationToken ct)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        _ = await CardAsync(conn, owner, character, ct).ConfigureAwait(false);
        await using var tx = await conn.BeginTransactionAsync(ct).ConfigureAwait(false);
        var key = DiaryKey(owner, character);
        await LockAsync(conn, tx, key, ct).ConfigureAwait(false);
        var doc = await ReadAsync<DiaryDocument>(conn, tx, key, ct).ConfigureAwait(false) ?? new();
        if (revision != doc.Revision) throw new ApiException(409, "COMPANION_CONFLICT", "The diary changed; refresh before removing an entry");
        if (doc.Items.Any(e => e.Id == entry))
            await SaveAsync(conn, tx, key, new DiaryDocument(doc.Revision + 1, [.. doc.Items.Where(e => e.Id != entry)]), ct).ConfigureAwait(false);
        await tx.CommitAsync(ct).ConfigureAwait(false);
    }

    private static void MapDiary(RouteGroupBuilder group)
    {
        group.MapGet("/characters/{id}/diary", async (string id, string? day, HttpContext c, CompanionSyncStore store, CancellationToken ct) =>
        {
            DateOnly? date = null;
            if (day is not null) date = CompanionDiary.TryDay(day, out var parsed) ? parsed : throw Invalid("Use an ISO date: yyyy-MM-dd");
            return await store.DiaryAsync(await ScopeAsync(c, store, ct).ConfigureAwait(false), CharacterId(id), date, ct).ConfigureAwait(false);
        });
        group.MapPost("/characters/{id}/diary", async (string id, HttpContext c, CompanionSyncStore store, CancellationToken ct) =>
        {
            var owner = await ScopeAsync(c, store, ct).ConfigureAwait(false); var body = await BodyAsync(c, ct).ConfigureAwait(false);
            static string Source(JsonObject body, string key) => body[key] is JsonValue v && v.TryGetValue<string>(out var s) && s.Length is > 0 and <= 128 ? s : throw Invalid("Stored message identities required");
            return await store.SaveDiaryAsync(owner, c.User.UserId(), CharacterId(id), Source(body, "userMessageId"), Source(body, "assistantMessageId"), ct).ConfigureAwait(false);
        });
        group.MapDelete("/characters/{id}/diary/{entry}", async (string id, string entry, long expectedRevision, HttpContext c, CompanionSyncStore store, CancellationToken ct) =>
        {
            await store.RemoveDiaryAsync(await ScopeAsync(c, store, ct).ConfigureAwait(false), CharacterId(id), entry, expectedRevision, ct).ConfigureAwait(false);
            return Results.NoContent();
        });
    }
}
