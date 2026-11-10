using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Companion;
using Aijade.Server.Auth;
using Aijade.Server.Infrastructure;
using Aijade.Server.V9;

using Npgsql;

namespace Aijade.Server.Product;

/// <summary>Account/character documents in the existing configuration store; mutations serialize in PostgreSQL.</summary>
public sealed partial class CompanionSyncStore(NpgsqlDataSource db, TimeProvider time)
{
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    private sealed record Selection(string? CharacterId = null, long Revision = 0);
    private sealed record Document
    {
        public CompanionProfile Profile { get; init; } = new();
        public CompanionNotebookData Notebook { get; init; } = new();
        public long ProfileRevision { get; init; }
        public long DataRevision { get; init; }
        public long AssetRevision { get; init; }
        public IReadOnlyList<string> Imports { get; init; } = [];
    }
    private static string Hash(string s) => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(s)));
    private static string Prefix(string owner) => "companion.user." + Hash(owner) + ".";
    private static string Key(string owner, string? character) => Prefix(owner) + "state." + Hash(character ?? "default");
    private static string Root(string owner) => Prefix(owner) + "selection";
    private static string? CharacterId(string id) => id == "default" ? null : id;
    private static ApiException Invalid(string message) => ApiException.BadRequest(message, "INVALID_COMPANION_STATE");

    private static async Task<T?> ReadAsync<T>(NpgsqlConnection conn, NpgsqlTransaction? tx, string key, CancellationToken ct)
    {
        var rows = await Sql.QueryAsync(conn, tx, "SELECT value::text FROM config_kv WHERE key = $1", r => r.GetString(0), ct, Sql.Text(key)).ConfigureAwait(false);
        return rows.Count == 0 ? default : JsonSerializer.Deserialize<T>(rows[0], Json);
    }
    private static Task<int> SaveAsync<T>(NpgsqlConnection conn, NpgsqlTransaction tx, string key, T data, CancellationToken ct) =>
        Sql.ExecAsync(conn, tx, "INSERT INTO config_kv(key,value) VALUES ($1,$2) ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value, updated_at=now()", ct,
            Sql.Text(key), Sql.Jsonb(JsonSerializer.SerializeToNode(data, Json)!));
    private static Task<int> LockAsync(NpgsqlConnection conn, NpgsqlTransaction tx, string key, CancellationToken ct) =>
        Sql.ExecAsync(conn, tx, "SELECT pg_advisory_xact_lock(hashtextextended($1,0))", ct, Sql.Text(key));

    private static async Task<Character?> CardAsync(NpgsqlConnection conn, string owner, string? character, CancellationToken ct)
    {
        if (character is null) return null;
        var rows = await Sql.QueryAsync(conn, null,
            "SELECT id,owner_id,name,description,persona,greeting,model_ref,avatar_ref,tags,visibility FROM characters WHERE id=$1 AND deleted_at IS NULL AND (owner_id=$2 OR visibility='public')",
            r => new Character(r.GetString(0), r.GetString(1), r.GetString(2), r.GetString(3), r.GetString(4), r.GetString(5),
                r.IsDBNull(6) ? null : r.GetString(6), r.IsDBNull(7) ? null : r.GetString(7), r.GetFieldValue<string[]>(8), r.GetString(9)), ct, Sql.Text(character), Sql.Text(owner)).ConfigureAwait(false);
        return rows.FirstOrDefault() ?? throw ApiException.NotFound();
    }

    public async Task<SharedCompanionState> StateAsync(string owner, string? character, bool current, bool media, CancellationToken ct)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        var selection = await ReadAsync<Selection>(conn, null, Root(owner), ct).ConfigureAwait(false) ?? new();
        if (current) character = selection.CharacterId;
        Character? card;
        try { card = await CardAsync(conn, owner, character, ct).ConfigureAwait(false); }
        catch (ApiException e) when (current && e.Status == 404) { character = null; card = null; }
        var doc = await ReadAsync<Document>(conn, null, Key(owner, character), ct).ConfigureAwait(false) ?? new();
        var notebook = media ? doc.Notebook : doc.Notebook with { Assets = [.. doc.Notebook.Assets.Select(a => a with { Data = "" })] };
        var zone = EffectiveZone(string.IsNullOrWhiteSpace(doc.Profile.TimeZone) ? time.LocalTimeZone : doc.Profile.Zone);
        return new(owner, character, card, doc.Profile, notebook, doc.ProfileRevision, doc.DataRevision, doc.AssetRevision, selection.Revision, zone);
    }

    private static string EffectiveZone(TimeZoneInfo zone)
    {
        // Host aliases such as ROK and Windows zone names are absent from the browser's compact time-zone data.
        if (!zone.HasIanaId && TimeZoneInfo.TryConvertWindowsIdToIanaId(zone.Id, out var iana)) return iana;
        if (!zone.Id.Contains('/', StringComparison.Ordinal) && TimeZoneInfo.TryConvertIanaIdToWindowsId(zone.Id, out var windows) &&
            TimeZoneInfo.TryConvertWindowsIdToIanaId(windows, out iana)) return iana;
        return zone.Id;
    }

    public async Task SelectAsync(string owner, string? character, CancellationToken ct)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        _ = await CardAsync(conn, owner, character, ct).ConfigureAwait(false);
        await using var tx = await conn.BeginTransactionAsync(ct).ConfigureAwait(false);
        await LockAsync(conn, tx, Root(owner), ct).ConfigureAwait(false);
        var before = await ReadAsync<Selection>(conn, tx, Root(owner), ct).ConfigureAwait(false) ?? new();
        await SaveAsync(conn, tx, Root(owner), new Selection(character, before.Revision + 1), ct).ConfigureAwait(false);
        await tx.CommitAsync(ct).ConfigureAwait(false);
    }

    private async Task MutateAsync(string owner, string? character, Func<Document, NpgsqlConnection, NpgsqlTransaction, Task<Document>> change, CancellationToken ct)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        _ = await CardAsync(conn, owner, character, ct).ConfigureAwait(false);
        await using var tx = await conn.BeginTransactionAsync(ct).ConfigureAwait(false);
        var key = Key(owner, character);
        await LockAsync(conn, tx, key, ct).ConfigureAwait(false);
        var doc = await ReadAsync<Document>(conn, tx, key, ct).ConfigureAwait(false) ?? new();
        await SaveAsync(conn, tx, key, await change(doc, conn, tx).ConfigureAwait(false), ct).ConfigureAwait(false);
        await tx.CommitAsync(ct).ConfigureAwait(false);
    }

    public Task ProfileAsync(string owner, string? character, CompanionProfile profile, long revision, CancellationToken ct)
    {
        ValidateProfile(profile);
        return MutateAsync(owner, character, (doc, _, _) =>
        {
            if (revision != doc.ProfileRevision) throw new ApiException(409, "COMPANION_CONFLICT", "The profile changed on another client; refresh before saving");
            return Task.FromResult(doc with { Profile = profile, ProfileRevision = doc.ProfileRevision + 1 });
        }, ct);
    }
    private static void ValidateProfile(CompanionProfile profile)
    {
        try { profile.ValidateLocation(); }
        catch (Exception e) when (e is ArgumentException or TimeZoneNotFoundException or InvalidTimeZoneException) { throw Invalid("Invalid companion location or time zone"); }
        if (new[] { profile.Home, profile.City, profile.TimeZone, profile.Appearance, profile.Interests, profile.MusicPreferences, profile.Friends, profile.Hairstyles }.Any(s => s is null || s.Length > 4096))
            throw Invalid("Companion settings must be short text values");
    }
    public Task AssetAsync(string owner, string? character, CompanionAsset asset, CancellationToken ct)
    {
        try { CompanionMedia.Validate(asset); }
        catch (Exception e) when (e is ArgumentException or FormatException) { throw Invalid("Invalid companion media"); }
        if (asset.Id.Length is < 1 or > 120) throw Invalid("Invalid asset identity");
        return MutateAsync(owner, character, (doc, _, _) =>
        {
            if (doc.Notebook.Assets.Any(a => a.Id == asset.Id && a != asset))
                throw new ApiException(409, "COMPANION_CONFLICT", "An item already uses this identity");
            if (doc.Notebook.Assets.Any(a => a.Id == asset.Id)) return Task.FromResult(doc);
            if (doc.Notebook.Assets.Count >= 32) throw Invalid("The collection is full; remove an item first");
            return Task.FromResult(doc with { Notebook = doc.Notebook with { Assets = [.. doc.Notebook.Assets, asset] }, DataRevision = doc.DataRevision + 1, AssetRevision = doc.AssetRevision + 1 });
        }, ct);
    }
    public Task RemoveAsync(string owner, string? character, string asset, CancellationToken ct) => MutateAsync(owner, character, (doc, _, _) =>
        Task.FromResult(doc with { Notebook = doc.Notebook with { Assets = [.. doc.Notebook.Assets.Where(a => a.Id != asset)] }, DataRevision = doc.DataRevision + 1, AssetRevision = doc.AssetRevision + 1 }), ct);

    public Task ObserveAsync(string owner, string actor, string? character, string message, CancellationToken ct) => MutateAsync(owner, character, async (doc, conn, tx) =>
    {
        var rows = await Sql.QueryAsync(conn, tx,
            "SELECT m.content FROM chat_messages m JOIN chats c ON c.id=m.chat_id WHERE m.id=$1 AND m.role='user' AND c.owner_id=$2 AND c.deleted_at IS NULL",
            r => r.GetString(0), ct, Sql.Text(message), Sql.Text(actor)).ConfigureAwait(false);
        if (rows.Count == 0) throw ApiException.NotFound();
        var receipt = Key(owner, character) + ".turn." + Hash(message);
        if (await ReadAsync<JsonObject>(conn, tx, receipt, ct).ConfigureAwait(false) is not null) return doc;
        await SaveAsync(conn, tx, receipt, new { message, at = time.GetUtcNow() }, ct).ConfigureAwait(false);
        if (!doc.Profile.Enabled) return doc;
        return doc with { Notebook = doc.Notebook with { Relationship = CompanionRelationship.Observe(doc.Notebook.Relationship, rows[0], message, time.GetUtcNow()) }, DataRevision = doc.DataRevision + 1 };
    }, ct);

    public async Task ImportAsync(string owner, string? character, string source, CompanionProfile profile, CompanionNotebookData notebook, bool activate, CancellationToken ct)
    {
        if (source.Length is < 1 or > 200) throw Invalid("Invalid import identity");
        ValidateProfile(profile);
        if (notebook.Assets.Count > 32) throw Invalid("Too many legacy items");
        foreach (var asset in notebook.Assets)
        {
            try { CompanionMedia.Validate(asset); } catch (Exception e) when (e is ArgumentException or FormatException) { throw Invalid("Invalid legacy media"); }
        }
        await MutateAsync(owner, character, (doc, _, _) =>
        {
            if (doc.Imports.Contains(source, StringComparer.Ordinal)) return Task.FromResult(doc);
            if (doc.Imports.Count >= 128) throw Invalid("Too many legacy import sources");
            var items = doc.Notebook.Assets.ToList();
            foreach (var asset in notebook.Assets)
            {
                if (items.Any(a => a.Id == asset.Id && a != asset)) throw new ApiException(409, "COMPANION_CONFLICT", "Legacy item conflicts; the source was preserved");
                if (items.All(a => a.Id != asset.Id)) items.Add(asset);
            }
            if (items.Count > 32) throw Invalid("The merged collection would exceed 32 items; the source was preserved");
            var relation = doc.Notebook.Relationship.Interactions == 0 ? notebook.Relationship : doc.Notebook.Relationship;
            if (!double.IsFinite(relation.Affection) || relation.Affection is < 0 or > 100 || !double.IsFinite(relation.Mood) || relation.Mood is < -1 or > 1 || relation.Interactions < 0)
                throw Invalid("Invalid legacy relationship");
            return Task.FromResult(doc with { Profile = doc.ProfileRevision == 0 ? profile : doc.Profile,
                ProfileRevision = Math.Max(1, doc.ProfileRevision), Notebook = doc.Notebook with { Assets = items, Relationship = relation },
                DataRevision = doc.DataRevision + 1, AssetRevision = doc.AssetRevision + 1, Imports = [.. doc.Imports, source] });
        }, ct).ConfigureAwait(false);
        if (activate)
        {
            await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
            await using var tx = await conn.BeginTransactionAsync(ct).ConfigureAwait(false);
            await LockAsync(conn, tx, Root(owner), ct).ConfigureAwait(false);
            var selection = await ReadAsync<Selection>(conn, tx, Root(owner), ct).ConfigureAwait(false) ?? new();
            if (selection.Revision == 0) await SaveAsync(conn, tx, Root(owner), new Selection(character, 1), ct).ConfigureAwait(false);
            await tx.CommitAsync(ct).ConfigureAwait(false);
        }
    }

    public async Task<JsonObject> CodeAsync(string owner, CancellationToken ct)
    {
        var code = Convert.ToHexStringLower(RandomNumberGenerator.GetBytes(16));
        var expires = time.GetUtcNow().AddMinutes(10);
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        await using var tx = await conn.BeginTransactionAsync(ct).ConfigureAwait(false);
        await SaveAsync(conn, tx, "companion.pair." + Hash(code), new JsonObject { ["owner"] = owner, ["expires"] = expires }, ct).ConfigureAwait(false);
        await tx.CommitAsync(ct).ConfigureAwait(false);
        return new JsonObject { ["code"] = code, ["expiresAt"] = expires };
    }
    public async Task<CompanionLink> PairAsync(string actor, string code, string subject, CancellationToken ct)
    {
        if (code.Length != 32 || subject.Length is < 5 or > 20 || !subject.All(char.IsAsciiDigit)) throw Invalid("Invalid pairing input");
        var pairKey = "companion.pair." + Hash(code.Trim().ToLowerInvariant());
        var lookup = "companion.lookup." + Hash(actor + ":qq:" + subject);
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        await using var tx = await conn.BeginTransactionAsync(ct).ConfigureAwait(false);
        await LockAsync(conn, tx, pairKey, ct).ConfigureAwait(false);
        var pending = await ReadAsync<JsonObject>(conn, tx, pairKey, ct).ConfigureAwait(false);
        if (pending is null || pending["expires"]!.GetValue<DateTimeOffset>() < time.GetUtcNow()) throw new ApiException(409, "PAIRING_EXPIRED", "The pairing code expired or was already used");
        await LockAsync(conn, tx, lookup, ct).ConfigureAwait(false);
        var previous = await ReadAsync<CompanionLink>(conn, tx, lookup, ct).ConfigureAwait(false);
        if (previous is not null) await Sql.ExecAsync(conn, tx, "DELETE FROM config_kv WHERE key=$1", ct, Sql.Text("companion.binding." + previous.Id)).ConfigureAwait(false);
        var link = new CompanionLink(Ids.New(), "qq", subject, pending["owner"]!.GetValue<string>(), actor);
        await SaveAsync(conn, tx, lookup, link, ct).ConfigureAwait(false);
        await SaveAsync(conn, tx, "companion.binding." + link.Id, link, ct).ConfigureAwait(false);
        await Sql.ExecAsync(conn, tx, "DELETE FROM config_kv WHERE key=$1", ct, Sql.Text(pairKey)).ConfigureAwait(false);
        await tx.CommitAsync(ct).ConfigureAwait(false);
        return link;
    }
    public async Task<CompanionLink?> ResolveAsync(string actor, string subject, CancellationToken ct)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        var link = await ReadAsync<CompanionLink>(conn, null, "companion.lookup." + Hash(actor + ":qq:" + subject), ct).ConfigureAwait(false);
        return link is null ? null : await ReadAsync<CompanionLink>(conn, null, "companion.binding." + link.Id, ct).ConfigureAwait(false);
    }
    public async Task<string> OwnerAsync(string actor, string? linkId, CancellationToken ct)
    {
        if (linkId is null) return actor;
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        var link = await ReadAsync<CompanionLink>(conn, null, "companion.binding." + linkId, ct).ConfigureAwait(false) ?? throw ApiException.NotFound();
        if (link.RelayId != actor) throw ApiException.NotFound();
        if (await Sql.CountAsync(conn, null, "SELECT count(*) FROM users WHERE id=$1 AND deleted_at IS NULL AND banned=false", ct, Sql.Text(link.OwnerId)).ConfigureAwait(false) == 0)
            throw ApiException.NotFound();
        return link.OwnerId;
    }
    public async Task<IReadOnlyList<CompanionLink>> LinksAsync(string owner, CancellationToken ct)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        return await Sql.QueryAsync(conn, null, "SELECT value::text FROM config_kv WHERE key LIKE 'companion.binding.%' AND value->>'ownerId'=$1 ORDER BY updated_at",
            r => JsonSerializer.Deserialize<CompanionLink>(r.GetString(0), Json)!, ct, Sql.Text(owner)).ConfigureAwait(false);
    }
    public async Task UnlinkAsync(string owner, string id, CancellationToken ct)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        await Sql.ExecAsync(conn, null, "DELETE FROM config_kv WHERE key=$1 AND (value->>'ownerId'=$2 OR value->>'relayId'=$2)", ct, Sql.Text("companion.binding." + id), Sql.Text(owner)).ConfigureAwait(false);
    }

    public static void Map(IEndpointRouteBuilder app)
    {
        var root = app.MapGroup("/api/v1/companion").RequireAuthorization();
        root.MapPost("/pairing-code", (HttpContext c, CompanionSyncStore store, CancellationToken ct) => store.CodeAsync(c.User.UserId(), ct));
        root.MapPost("/pair", async (HttpContext c, CompanionSyncStore store, CancellationToken ct) =>
        {
            var b = await BodyAsync(c, ct).ConfigureAwait(false);
            if (b["platform"]?.GetValue<string>() != "qq") throw Invalid("Only private QQ pairing is supported");
            return await store.PairAsync(c.User.UserId(), b["code"]?.GetValue<string>() ?? "", b["subject"]?.GetValue<string>() ?? "", ct).ConfigureAwait(false);
        });
        root.MapGet("/resolve", (string subject, HttpContext c, CompanionSyncStore store, CancellationToken ct) => store.ResolveAsync(c.User.UserId(), subject, ct));
        root.MapGet("/links", (HttpContext c, CompanionSyncStore store, CancellationToken ct) => store.LinksAsync(c.User.UserId(), ct));
        root.MapDelete("/links/{id}", (string id, HttpContext c, CompanionSyncStore store, CancellationToken ct) => store.UnlinkAsync(c.User.UserId(), id, ct));
        MapScope(root);
        MapScope(root.MapGroup("/linked/{linkId}"));
    }
    private static async Task<JsonObject> BodyAsync(HttpContext c, CancellationToken ct) =>
        await V9Endpoints.ReadJsonAsync(c.Request, "INVALID_COMPANION_STATE", ct).ConfigureAwait(false) as JsonObject ?? throw Invalid("JSON object required");
    private static void MapScope(RouteGroupBuilder group)
    {
        MapDiary(group);
        group.MapGet("", async (HttpContext c, CompanionSyncStore store, CancellationToken ct) =>
            await store.StateAsync(await ScopeAsync(c, store, ct).ConfigureAwait(false), null, true, false, ct).ConfigureAwait(false));
        group.MapPost("/selection", async (HttpContext c, CompanionSyncStore store, CancellationToken ct) =>
        {
            var owner = await ScopeAsync(c, store, ct).ConfigureAwait(false); var b = await BodyAsync(c, ct).ConfigureAwait(false);
            await store.SelectAsync(owner, b["characterId"]?.GetValue<string>(), ct).ConfigureAwait(false);
            return await store.StateAsync(owner, null, true, false, ct).ConfigureAwait(false);
        });
        group.MapGet("/characters/{id}", async (string id, bool? media, HttpContext c, CompanionSyncStore store, CancellationToken ct) =>
            await store.StateAsync(await ScopeAsync(c, store, ct).ConfigureAwait(false), CharacterId(id), false, media == true, ct).ConfigureAwait(false));
        group.MapPut("/characters/{id}/profile", async (string id, HttpContext c, CompanionSyncStore store, CancellationToken ct) =>
        {
            var owner = await ScopeAsync(c, store, ct).ConfigureAwait(false); var b = await BodyAsync(c, ct).ConfigureAwait(false);
            var profile = b["profile"]?.Deserialize<CompanionProfile>(Json) ?? throw Invalid("Profile required");
            await store.ProfileAsync(owner, CharacterId(id), profile, b["expectedRevision"]?.GetValue<long>() ?? -1, ct).ConfigureAwait(false);
            return await store.StateAsync(owner, CharacterId(id), false, false, ct).ConfigureAwait(false);
        });
        group.MapPost("/characters/{id}/observe", async (string id, HttpContext c, CompanionSyncStore store, CancellationToken ct) =>
        {
            var owner = await ScopeAsync(c, store, ct).ConfigureAwait(false); var b = await BodyAsync(c, ct).ConfigureAwait(false);
            await store.ObserveAsync(owner, c.User.UserId(), CharacterId(id), b["messageId"]?.GetValue<string>() ?? "", ct).ConfigureAwait(false);
            return Results.NoContent();
        });
        group.MapPost("/characters/{id}/assets", async (string id, HttpContext c, CompanionSyncStore store, CancellationToken ct) =>
        {
            var owner = await ScopeAsync(c, store, ct).ConfigureAwait(false); var b = await BodyAsync(c, ct).ConfigureAwait(false);
            await store.AssetAsync(owner, CharacterId(id), b.Deserialize<CompanionAsset>(Json) ?? throw Invalid("Asset required"), ct).ConfigureAwait(false);
            return Results.NoContent();
        });
        group.MapDelete("/characters/{id}/assets/{asset}", async (string id, string asset, HttpContext c, CompanionSyncStore store, CancellationToken ct) =>
        {
            await store.RemoveAsync(await ScopeAsync(c, store, ct).ConfigureAwait(false), CharacterId(id), asset, ct).ConfigureAwait(false);
            return Results.NoContent();
        });
        group.MapGet("/characters/{id}/assets/{asset}", async (string id, string asset, HttpContext c, CompanionSyncStore store, CancellationToken ct) =>
        {
            var state = await store.StateAsync(await ScopeAsync(c, store, ct).ConfigureAwait(false), CharacterId(id), false, true, ct).ConfigureAwait(false);
            return state.Notebook.Assets.FirstOrDefault(a => a.Id == asset) ?? throw ApiException.NotFound();
        });
        group.MapPost("/characters/{id}/import", async (string id, HttpContext c, CompanionSyncStore store, CancellationToken ct) =>
        {
            var owner = await ScopeAsync(c, store, ct).ConfigureAwait(false); var b = await BodyAsync(c, ct).ConfigureAwait(false);
            await store.ImportAsync(owner, CharacterId(id), b["source"]?.GetValue<string>() ?? "", b["profile"]?.Deserialize<CompanionProfile>(Json) ?? new(),
                b["notebook"]?.Deserialize<CompanionNotebookData>(Json) ?? new(), b["activateIfUnset"]?.GetValue<bool>() ?? false, ct).ConfigureAwait(false);
            return await store.StateAsync(owner, CharacterId(id), false, false, ct).ConfigureAwait(false);
        }).WithMetadata(new Microsoft.AspNetCore.Mvc.RequestSizeLimitAttribute(100 * 1024 * 1024));
    }
    private static Task<string> ScopeAsync(HttpContext c, CompanionSyncStore store, CancellationToken ct) =>
        store.OwnerAsync(c.User.UserId(), c.Request.RouteValues["linkId"]?.ToString(), ct);
}
