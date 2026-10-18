using System.Text.Json.Nodes;

using Aijade.Server.Auth;
using Aijade.Server.Infrastructure;
using Aijade.Server.Product;
using Aijade.Server.V9;

using Npgsql;

namespace Aijade.Server.Memory;

// Browsing, searching, forgetting, exporting and importing the caller's long-term memory (the evidence the v9 pipeline
// committed for the caller's sessions). Forgetting removes the evidence pack and every memory version derived from it, and
// leaves an audit entry; weave links that pointed at it become dangling on purpose (the evidence domain reports them).

public static class MemoryLibrary
{
    /// <summary>Claim a session for a user on first write; false when another user already owns it.</summary>
    public static async Task<bool> ClaimSessionAsync(NpgsqlDataSource db, string sessionId, string userId, CancellationToken ct)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        await Sql.ExecAsync(conn, null, "INSERT INTO memory_session_owners (session_id, user_id) VALUES ($1,$2) ON CONFLICT DO NOTHING", ct, Sql.Text(sessionId), Sql.Text(userId)).ConfigureAwait(false);
        var owner = (await Sql.QueryAsync(conn, null, "SELECT user_id FROM memory_session_owners WHERE session_id = $1", r => r.GetString(0), ct, Sql.Text(sessionId)).ConfigureAwait(false))[0];
        return owner == userId;
    }

    private const string ItemQuery =
        "SELECT p.id, p.session_id, p.source, c.content, p.created_at, (SELECT count(*) FROM memory_versions v WHERE v.evidence_pack_id = p.id) AS versions " +
        "FROM evidence_packs p JOIN evidence_chunks c ON c.pack_id = p.id JOIN memory_session_owners o ON o.session_id = p.session_id WHERE o.user_id = $1";

    private static JsonNode Item(System.Data.Common.DbDataReader r) => new JsonObject
    {
        ["id"] = r.GetString(0), ["sessionId"] = r.GetString(1), ["source"] = r.GetString(2), ["content"] = r.GetString(3),
        ["createdAt"] = new DateTimeOffset(DateTime.SpecifyKind(r.GetDateTime(4), DateTimeKind.Utc)), ["memoryVersions"] = r.GetInt64(5),
    };

    /// <summary>The caller's memory items, newest first; <paramref name="session"/> narrows them to one memory session (e.g. one
    /// person a bot account talks to), null = all of the caller's.</summary>
    public static async Task<JsonArray> ItemsAsync(NpgsqlDataSource db, string userId, string? query, int limit, CancellationToken ct, string? session = null)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        var rows = await Sql.QueryAsync(conn, null,
            ItemQuery + " AND ($2::text IS NULL OR c.content ILIKE '%' || $2 || '%') AND ($4::text IS NULL OR p.session_id = $4) ORDER BY p.created_at DESC LIMIT $3",
            Item, ct, Sql.Text(userId), Sql.Text(string.IsNullOrWhiteSpace(query) ? null : query.Trim()), Sql.P(Math.Clamp(limit, 1, 500)),
            Sql.Text(string.IsNullOrWhiteSpace(session) ? null : session)).ConfigureAwait(false);
        return new JsonArray([.. rows]);
    }

    /// <summary>Similarity below which a memory is not offered as related (cosine, after the exact-text bonus).</summary>
    public const double MinSimilarity = 0.3;

    /// <summary>
    /// Search by meaning when an embeddings route is configured: chunks without a vector (or with one from another model)
    /// are embedded first, then items are ranked by cosine similarity to the query, with a bonus for containing it verbatim.
    /// Without embeddings, or if they fail (unreachable, out of flux), the text search answers instead.
    /// </summary>
    public static async Task<JsonArray> SearchAsync(NpgsqlDataSource db, EmbeddingService embeddings, string userId, string? query, int limit, CancellationToken ct,
        string? session = null)
    {
        if (string.IsNullOrWhiteSpace(query) || await embeddings.ModelAsync(ct).ConfigureAwait(false) is not { } model)
            return await ItemsAsync(db, userId, query, limit, ct, session).ConfigureAwait(false);
        try
        {
            await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
            var rows = await Sql.QueryAsync(conn, null,
                ItemQuery.Replace("SELECT p.id,", "SELECT c.id AS chunk_id, c.embedding, c.embedding_model, p.id,", StringComparison.Ordinal) +
                " AND ($2::text IS NULL OR p.session_id = $2) ORDER BY p.created_at DESC LIMIT 2000",
                r => (Chunk: r.GetString(0), Vector: r.IsDBNull(1) ? null : (float[])r.GetValue(1), Model: Sql.NullableString(r, 2),
                    Item: (JsonObject)new JsonObject
                    {
                        ["id"] = r.GetString(3), ["sessionId"] = r.GetString(4), ["source"] = r.GetString(5), ["content"] = r.GetString(6),
                        ["createdAt"] = new DateTimeOffset(DateTime.SpecifyKind(r.GetDateTime(7), DateTimeKind.Utc)), ["memoryVersions"] = r.GetInt64(8),
                    }),
                ct, Sql.Text(userId), Sql.Text(string.IsNullOrWhiteSpace(session) ? null : session)).ConfigureAwait(false);
            var missing = rows.Where(r => r.Vector is null || r.Model != model).ToList();
            var fresh = new Dictionary<string, float[]>(StringComparer.Ordinal);
            if (missing.Count > 0)
            {
                var vectors = (await embeddings.EmbedAsync(userId, [.. missing.Select(m => m.Item["content"]!.GetValue<string>())], ct).ConfigureAwait(false))!;
                for (var i = 0; i < missing.Count; i++)
                {
                    fresh[missing[i].Chunk] = vectors[i];
                    await Sql.ExecAsync(conn, null, "UPDATE evidence_chunks SET embedding = $2, embedding_model = $3 WHERE id = $1", ct,
                        Sql.Text(missing[i].Chunk), new NpgsqlParameter { Value = vectors[i], NpgsqlDbType = NpgsqlTypes.NpgsqlDbType.Array | NpgsqlTypes.NpgsqlDbType.Real },
                        Sql.Text(model)).ConfigureAwait(false);
                }
            }
            var q = (await embeddings.EmbedAsync(userId, [query.Trim()], ct).ConfigureAwait(false))![0];
            var ranked = rows
                .Select(r => (r.Item, Score: EmbeddingService.Cosine(fresh.GetValueOrDefault(r.Chunk) ?? r.Vector!, q)
                    + (r.Item["content"]!.GetValue<string>().Contains(query.Trim(), StringComparison.OrdinalIgnoreCase) ? 0.15 : 0)))
                .Where(r => r.Score >= MinSimilarity)
                .OrderByDescending(r => r.Score)
                .Take(Math.Clamp(limit, 1, 500))
                .Select(r =>
                {
                    r.Item["score"] = Math.Round(r.Score, 4);
                    return (JsonNode)r.Item;
                });
            return new JsonArray([.. ranked]);
        }
        catch (ApiException)
        {
            return await ItemsAsync(db, userId, query, limit, ct, session).ConfigureAwait(false);
        }
    }

    public static void Map(IEndpointRouteBuilder app)
    {
        var g = app.MapGroup("/api/v1/memory/items").RequireAuthorization();
        g.MapGet("/", async (string? q, int? limit, string? session, HttpContext c, NpgsqlDataSource db, EmbeddingService embeddings, CancellationToken ct) =>
            Results.Json(new JsonObject { ["items"] = await SearchAsync(db, embeddings, c.User.UserId(), q, limit ?? 100, ct, session).ConfigureAwait(false) }));
        g.MapDelete("/{id}", async (string id, HttpContext c, NpgsqlDataSource db, TimeProvider time, CancellationToken ct) =>
        {
            await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
            await using var tx = await conn.BeginTransactionAsync(ct).ConfigureAwait(false);
            var owned = await Sql.CountAsync(conn, tx, "SELECT count(*) FROM evidence_packs p JOIN memory_session_owners o ON o.session_id = p.session_id WHERE p.id = $1 AND o.user_id = $2", ct,
                Sql.Text(id), Sql.Text(c.User.UserId())).ConfigureAwait(false);
            if (owned == 0)
                throw ApiException.NotFound("memory item not found");
            var versions = await Sql.ExecAsync(conn, tx, "DELETE FROM memory_versions WHERE evidence_pack_id = $1", ct, Sql.Text(id)).ConfigureAwait(false);
            await Sql.ExecAsync(conn, tx, "DELETE FROM evidence_packs WHERE id = $1", ct, Sql.Text(id)).ConfigureAwait(false);
            await Sql.ExecAsync(conn, tx, "INSERT INTO audit_log_entries (id, tx_id, actor, action, before_hash, after_hash, at) VALUES ($1,$2,$3,'memory_forgotten',$2,NULL,$4)", ct,
                Sql.Text(Ids.New()), Sql.Text(id), Sql.Text(c.User.UserId()), Sql.Time(time.GetUtcNow())).ConfigureAwait(false);
            await tx.CommitAsync(ct).ConfigureAwait(false);
            return Results.Json(new JsonObject { ["forgotten"] = id, ["memoryVersionsRemoved"] = versions });
        });
        g.MapGet("/export", async (HttpContext c, NpgsqlDataSource db, CancellationToken ct) => Results.Json(new JsonObject
        {
            ["format"] = "aijade.memory.v1",
            ["exportedAt"] = DateTimeOffset.UtcNow,
            ["items"] = await ItemsAsync(db, c.User.UserId(), null, 500, ct).ConfigureAwait(false),
        }));
        // Import replays each item through the v9 pipeline as a perception: imported memory is re-gated, never written directly.
        g.MapPost("/import", async (HttpContext c, NpgsqlDataSource db, ServerRuntime runtime, CancellationToken ct) =>
        {
            var b = await V9Endpoints.ReadJsonAsync(c.Request, "INVALID_MEMORY_IMPORT", ct).ConfigureAwait(false);
            if (b?["format"]?.GetValue<string>() != "aijade.memory.v1" || b["items"] is not JsonArray items)
                throw ApiException.BadRequest("not an AIJADE memory export", "INVALID_MEMORY_IMPORT");
            var sessionId = $"import-{c.User.UserId()}";
            if (!await ClaimSessionAsync(db, sessionId, c.User.UserId(), ct).ConfigureAwait(false))
                throw ApiException.Forbidden();
            var imported = 0;
            foreach (var item in items.OfType<JsonObject>())
            {
                if (item["content"]?.GetValue<string>() is not { Length: > 0 } content)
                    continue;
                var id = Ids.New();
                await runtime.Runtime.ProcessPerceptionAsync(new Aijade.Memory.V9.V9PerceptionInput($"import-{id}", sessionId, $"trace-import-{id}", $"trace-import-{id}",
                    DateTimeOffset.UtcNow.ToUnixTimeMilliseconds(), "import", 1, 0, item["source"]?.GetValue<string>() ?? "import", content), ct).ConfigureAwait(false);
                imported++;
            }
            return Results.Json(new JsonObject { ["imported"] = imported });
        });
    }
}
