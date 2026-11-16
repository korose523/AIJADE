using System.Collections.Concurrent;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Server.Auth;
using Aijade.Server.Infrastructure;
using Aijade.Server.V9;

using Microsoft.AspNetCore.DataProtection;

using Npgsql;

namespace Aijade.Server.Product;

// Characters, chats (with server-side message sync pushed to every open connection of the owner) and provider
// configurations (secrets encrypted with ASP.NET Core data protection; never returned to clients).

public sealed class ChatHub
{
    private readonly ConcurrentDictionary<string, ConcurrentDictionary<Guid, WebSocket>> sockets = new(StringComparer.Ordinal);

    public void Add(string userId, Guid id, WebSocket socket) => sockets.GetOrAdd(userId, _ => new())[id] = socket;

    public void Remove(string userId, Guid id)
    {
        if (sockets.TryGetValue(userId, out var set))
            set.TryRemove(id, out _);
    }

    public int Connections(string userId) => sockets.TryGetValue(userId, out var set) ? set.Count : 0;

    /// <summary>Send to every open socket of the user; a dead socket is dropped.</summary>
    public async Task BroadcastAsync(string userId, JsonNode message, CancellationToken ct)
    {
        if (!sockets.TryGetValue(userId, out var set))
            return;
        var bytes = Encoding.UTF8.GetBytes(message.ToJsonString());
        foreach (var (id, socket) in set)
        {
            try
            {
                if (socket.State == WebSocketState.Open)
                    await socket.SendAsync(bytes, WebSocketMessageType.Text, true, ct).ConfigureAwait(false);
            }
            catch (WebSocketException)
            {
                set.TryRemove(id, out _);
            }
        }
    }
}

public static class LibraryEndpoints
{
    private static string? S(JsonNode? b, string k) => b?[k] is JsonValue v && v.TryGetValue<string>(out var s) ? s : null;

    private static string Req(JsonNode? b, string k) => S(b, k) is { Length: > 0 } s ? s : throw ApiException.BadRequest($"{k} is required", "INVALID_REQUEST");

    private static JsonObject Row(System.Data.Common.DbDataReader r)
    {
        var o = new JsonObject();
        for (var i = 0; i < r.FieldCount; i++)
        {
            var key = JsonNamingPolicy.CamelCase.ConvertName(string.Concat(r.GetName(i).Split('_').Select((p, k) => k == 0 ? p : char.ToUpperInvariant(p[0]) + p[1..])));
            o[key] = r.IsDBNull(i) ? null
                : r.GetDataTypeName(i) == "jsonb" ? JsonNode.Parse(r.GetString(i))
                : r.GetValue(i) is string[] arr ? new JsonArray([.. arr.Select(x => (JsonNode)x)])
                : r.GetFieldType(i) == typeof(DateTime) ? JsonValue.Create(new DateTimeOffset(DateTime.SpecifyKind(r.GetDateTime(i), DateTimeKind.Utc)))
                : JsonValue.Create(r.GetValue(i));
        }
        return o;
    }

    private static async Task<List<JsonObject>> QueryAsync(NpgsqlDataSource db, string sql, CancellationToken ct, params NpgsqlParameter[] ps)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        return await Sql.QueryAsync(conn, null, sql, Row, ct, ps).ConfigureAwait(false);
    }

    private static async Task<JsonObject> OneAsync(NpgsqlDataSource db, string sql, CancellationToken ct, params NpgsqlParameter[] ps) =>
        (await QueryAsync(db, sql, ct, ps).ConfigureAwait(false)).FirstOrDefault() ?? throw ApiException.NotFound();

    private static JsonArray Arr(IEnumerable<JsonObject> rows) => new([.. rows.Select(r => (JsonNode)r)]);

    private const string CharacterColumns = "id, owner_id, name, description, persona, greeting, model_ref, avatar_ref, tags, visibility, created_at, updated_at";

    public static void Map(IEndpointRouteBuilder app)
    {
        var characters = app.MapGroup("/api/v1/characters").RequireAuthorization();
        characters.MapGet("/", async (HttpContext c, NpgsqlDataSource db, CancellationToken ct) => Results.Json(new JsonObject
        {
            ["characters"] = Arr(await QueryAsync(db, $"SELECT {CharacterColumns} FROM characters WHERE deleted_at IS NULL AND (owner_id = $1 OR visibility = 'public') ORDER BY updated_at DESC",
                ct, Sql.Text(c.User.UserId())).ConfigureAwait(false)),
        }));
        characters.MapGet("/{id}", async (string id, HttpContext c, NpgsqlDataSource db, CancellationToken ct) => Results.Json(await OneAsync(db,
            $"SELECT {CharacterColumns} FROM characters WHERE id = $1 AND deleted_at IS NULL AND (owner_id = $2 OR visibility = 'public')", ct, Sql.Text(id), Sql.Text(c.User.UserId())).ConfigureAwait(false)));
        characters.MapPost("/", async (HttpContext c, NpgsqlDataSource db, CancellationToken ct) =>
        {
            var b = await V9Endpoints.ReadJsonAsync(c.Request, "INVALID_REQUEST", ct).ConfigureAwait(false);
            var visibility = S(b, "visibility") ?? "private";
            if (visibility is not ("private" or "public"))
                throw ApiException.BadRequest("visibility must be private or public", "INVALID_REQUEST");
            var tags = b?["tags"] is JsonArray ta ? ta.Select(t => t!.GetValue<string>()).ToArray() : [];
            var row = await OneAsync(db,
                $"INSERT INTO characters (id, owner_id, name, description, persona, greeting, model_ref, avatar_ref, tags, visibility) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10) RETURNING {CharacterColumns}", ct,
                Sql.Text(Ids.New()), Sql.Text(c.User.UserId()), Sql.Text(Req(b, "name")), Sql.Text(S(b, "description") ?? ""), Sql.Text(S(b, "persona") ?? ""), Sql.Text(S(b, "greeting") ?? ""),
                Sql.Text(S(b, "modelRef")), Sql.Text(S(b, "avatarRef")), Sql.TextArray(tags), Sql.Text(visibility)).ConfigureAwait(false);
            return Results.Json(row, statusCode: 201);
        });
        characters.MapPatch("/{id}", async (string id, HttpContext c, NpgsqlDataSource db, CancellationToken ct) =>
        {
            var b = await V9Endpoints.ReadJsonAsync(c.Request, "INVALID_REQUEST", ct).ConfigureAwait(false);
            var row = await OneAsync(db,
                "UPDATE characters SET name = COALESCE($3, name), description = COALESCE($4, description), persona = COALESCE($5, persona), greeting = COALESCE($6, greeting), " +
                "model_ref = COALESCE($7, model_ref), avatar_ref = COALESCE($8, avatar_ref), visibility = COALESCE($9, visibility), updated_at = now() " +
                $"WHERE id = $1 AND owner_id = $2 AND deleted_at IS NULL RETURNING {CharacterColumns}", ct,
                Sql.Text(id), Sql.Text(c.User.UserId()), Sql.Text(S(b, "name")), Sql.Text(S(b, "description")), Sql.Text(S(b, "persona")), Sql.Text(S(b, "greeting")),
                Sql.Text(S(b, "modelRef")), Sql.Text(S(b, "avatarRef")), Sql.Text(S(b, "visibility"))).ConfigureAwait(false);
            return Results.Json(row);
        });
        characters.MapDelete("/{id}", async (string id, HttpContext c, NpgsqlDataSource db, CancellationToken ct) =>
        {
            await OneAsync(db, "UPDATE characters SET deleted_at = now() WHERE id = $1 AND owner_id = $2 AND deleted_at IS NULL RETURNING id", ct, Sql.Text(id), Sql.Text(c.User.UserId())).ConfigureAwait(false);
            return Results.NoContent();
        });

        var chats = app.MapGroup("/api/v1/chats").RequireAuthorization();
        chats.MapGet("/", async (HttpContext c, NpgsqlDataSource db, CancellationToken ct) => Results.Json(new JsonObject
        {
            ["chats"] = Arr(await QueryAsync(db, "SELECT id, character_id, title, created_at, updated_at FROM chats WHERE owner_id = $1 AND deleted_at IS NULL ORDER BY updated_at DESC",
                ct, Sql.Text(c.User.UserId())).ConfigureAwait(false)),
        }));
        chats.MapPost("/", async (HttpContext c, NpgsqlDataSource db, ProductEvents events, CancellationToken ct) =>
        {
            var b = await V9Endpoints.ReadJsonAsync(c.Request, "INVALID_REQUEST", ct).ConfigureAwait(false);
            var row = await OneAsync(db, "INSERT INTO chats (id, owner_id, character_id, title) VALUES ($1,$2,$3,$4) RETURNING id, character_id, title, created_at, updated_at", ct,
                Sql.Text(Ids.New()), Sql.Text(c.User.UserId()), Sql.Text(S(b, "characterId")), Sql.Text(S(b, "title") ?? "")).ConfigureAwait(false);
            await events.TrackAsync(c.User.UserId(), "chat", "session_started", "succeeded", "chats.create", ct: ct).ConfigureAwait(false);
            return Results.Json(row, statusCode: 201);
        });
        chats.MapDelete("/{id}", async (string id, HttpContext c, NpgsqlDataSource db, CancellationToken ct) =>
        {
            await OneAsync(db, "UPDATE chats SET deleted_at = now() WHERE id = $1 AND owner_id = $2 AND deleted_at IS NULL RETURNING id", ct, Sql.Text(id), Sql.Text(c.User.UserId())).ConfigureAwait(false);
            return Results.NoContent();
        });
        chats.MapGet("/{id}/messages", async (string id, long? after, HttpContext c, NpgsqlDataSource db, CancellationToken ct) =>
        {
            await OneAsync(db, "SELECT id FROM chats WHERE id = $1 AND owner_id = $2 AND deleted_at IS NULL", ct, Sql.Text(id), Sql.Text(c.User.UserId())).ConfigureAwait(false);
            return Results.Json(new JsonObject
            {
                ["messages"] = Arr(await QueryAsync(db, "SELECT id, seq, role, content, meta, created_at FROM chat_messages WHERE chat_id = $1 AND seq > $2 ORDER BY seq", ct,
                    Sql.Text(id), Sql.P(after ?? 0)).ConfigureAwait(false)),
            });
        });
        chats.MapPost("/{id}/messages", async (string id, HttpContext c, NpgsqlDataSource db, ChatHub hub, ProductEvents events, CancellationToken ct) =>
        {
            var b = await V9Endpoints.ReadJsonAsync(c.Request, "INVALID_REQUEST", ct).ConfigureAwait(false);
            var message = await AppendMessageAsync(db, hub, c.User.UserId(), id, Req(b, "role"), Req(b, "content"), b?["meta"] as JsonObject, ct).ConfigureAwait(false);
            await events.TrackAsync(c.User.UserId(), "chat", "message_pushed", "succeeded", "chats.messages", ct: ct).ConfigureAwait(false);
            return Results.Json(message, statusCode: 201);
        });
        app.Map("/api/v1/ws/chats", async (HttpContext c, NpgsqlDataSource db, ChatHub hub) =>
        {
            if (!c.WebSockets.IsWebSocketRequest)
                throw ApiException.BadRequest("WebSocket upgrade required", "WEBSOCKET_REQUIRED");
            var userId = c.User.UserId();
            using var socket = await c.WebSockets.AcceptWebSocketAsync().ConfigureAwait(false);
            var id = Guid.NewGuid();
            hub.Add(userId, id, socket);
            try
            {
                var buffer = new byte[64 * 1024];
                while (socket.State == WebSocketState.Open)
                {
                    var result = await socket.ReceiveAsync(buffer, c.RequestAborted).ConfigureAwait(false);
                    if (result.MessageType == WebSocketMessageType.Close)
                    {
                        // Complete the close handshake; leaving without answering makes the client's close fail.
                        await socket.CloseOutputAsync(WebSocketCloseStatus.NormalClosure, "closing", CancellationToken.None).ConfigureAwait(false);
                        break;
                    }
                    JsonNode? msg;
                    try
                    {
                        msg = JsonNode.Parse(Encoding.UTF8.GetString(buffer, 0, result.Count));
                    }
                    catch (JsonException)
                    {
                        continue;
                    }
                    if (S(msg, "type") == "push" && S(msg, "chatId") is { } chatId && S(msg, "role") is { } role && S(msg, "content") is { } content)
                    {
                        try
                        {
                            await AppendMessageAsync(db, hub, userId, chatId, role, content, msg!["meta"] as JsonObject, c.RequestAborted).ConfigureAwait(false);
                        }
                        catch (ApiException e)
                        {
                            await socket.SendAsync(Encoding.UTF8.GetBytes(new JsonObject { ["type"] = "error", ["error"] = e.Code, ["message"] = e.Message }.ToJsonString()),
                                WebSocketMessageType.Text, true, c.RequestAborted).ConfigureAwait(false);
                        }
                    }
                }
            }
            catch (OperationCanceledException)
            {
            }
            catch (WebSocketException)
            {
            }
            finally
            {
                hub.Remove(userId, id);
            }
        }).RequireAuthorization();

        var providers = app.MapGroup("/api/v1/providers").RequireAuthorization();
        providers.MapGet("/", async (HttpContext c, NpgsqlDataSource db, CancellationToken ct) => Results.Json(new JsonObject
        {
            ["providers"] = Arr(await QueryAsync(db, "SELECT id, kind, name, base_url, (secret_protected IS NOT NULL) AS has_secret, options, created_at, updated_at FROM provider_configs WHERE owner_id = $1 ORDER BY name",
                ct, Sql.Text(c.User.UserId())).ConfigureAwait(false)),
        }));
        providers.MapPost("/", async (HttpContext c, NpgsqlDataSource db, IDataProtectionProvider dp, CancellationToken ct) =>
        {
            var b = await V9Endpoints.ReadJsonAsync(c.Request, "INVALID_REQUEST", ct).ConfigureAwait(false);
            var secret = S(b, "apiKey");
            var row = await OneAsync(db,
                "INSERT INTO provider_configs (id, owner_id, kind, name, base_url, secret_protected, options) VALUES ($1,$2,$3,$4,$5,$6,$7) " +
                "RETURNING id, kind, name, base_url, (secret_protected IS NOT NULL) AS has_secret, options, created_at, updated_at", ct,
                Sql.Text(Ids.New()), Sql.Text(c.User.UserId()), Sql.Text(Req(b, "kind")), Sql.Text(Req(b, "name")), Sql.Text(S(b, "baseUrl")),
                Sql.Text(secret is null ? null : dp.CreateProtector(ProviderSecretPurpose).Protect(secret)), Sql.Jsonb(b?["options"] as JsonObject ?? [])).ConfigureAwait(false);
            return Results.Json(row, statusCode: 201);
        });
        providers.MapDelete("/{id}", async (string id, HttpContext c, NpgsqlDataSource db, CancellationToken ct) =>
        {
            await OneAsync(db, "DELETE FROM provider_configs WHERE id = $1 AND owner_id = $2 RETURNING id", ct, Sql.Text(id), Sql.Text(c.User.UserId())).ConfigureAwait(false);
            return Results.NoContent();
        });

        var flux = app.MapGroup("/api/v1/flux").RequireAuthorization();
        flux.MapGet("/", async (HttpContext c, FluxLedger ledger, CancellationToken ct) => Results.Json(new JsonObject
        {
            ["balance"] = await ledger.BalanceAsync(c.User.UserId(), ct).ConfigureAwait(false),
            ["transactions"] = JsonSerializer.SerializeToNode(await ledger.HistoryAsync(c.User.UserId(), 50, ct).ConfigureAwait(false), JsonSerializerOptions.Web),
        }));
    }

    public const string ProviderSecretPurpose = "Aijade.ProviderSecret.v1";

    public static async Task<JsonObject> AppendMessageAsync(NpgsqlDataSource db, ChatHub hub, string userId, string chatId, string role, string content, JsonObject? meta, CancellationToken ct)
    {
        if (role is not ("system" or "user" or "assistant" or "tool"))
            throw ApiException.BadRequest("role must be system, user, assistant or tool", "INVALID_REQUEST");
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        await using var tx = await conn.BeginTransactionAsync(ct).ConfigureAwait(false);
        var owned = await Sql.CountAsync(conn, tx, "SELECT count(*) FROM chats WHERE id = $1 AND owner_id = $2 AND deleted_at IS NULL", ct, Sql.Text(chatId), Sql.Text(userId)).ConfigureAwait(false);
        if (owned == 0)
            throw ApiException.NotFound("chat not found");
        var message = (await Sql.QueryAsync(conn, tx, "INSERT INTO chat_messages (id, chat_id, role, content, meta) VALUES ($1,$2,$3,$4,$5) RETURNING id, seq, role, content, meta, created_at",
            Row, ct, Sql.Text(Ids.New()), Sql.Text(chatId), Sql.Text(role), Sql.Text(content), Sql.Jsonb(meta)).ConfigureAwait(false))[0];
        await Sql.ExecAsync(conn, tx, "UPDATE chats SET updated_at = now() WHERE id = $1", ct, Sql.Text(chatId)).ConfigureAwait(false);
        await tx.CommitAsync(ct).ConfigureAwait(false);
        await hub.BroadcastAsync(userId, new JsonObject { ["type"] = "message", ["chatId"] = chatId, ["message"] = message.DeepClone() }, ct).ConfigureAwait(false);
        return message;
    }
}
