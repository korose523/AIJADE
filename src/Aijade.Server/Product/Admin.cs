using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Server.Auth;
using Aijade.Server.Infrastructure;
using Aijade.Server.V9;

using Npgsql;

namespace Aijade.Server.Product;

// Administration (role admin): users (role, ban), flux grants, gateway routes, product analytics, the gateway request log,
// and v9 pipeline health (row counts, pairing gaps, projection status) with the render-trace backfill.

public static class AdminEndpoints
{
    public const string Policy = "admin";

    private static readonly string[] V9Tables =
        ["events", "render_traces", "evidence_packs", "pgc_states", "memory_txs", "memory_versions", "evidence_weaves", "evolution_specs", "eval_reports", "audit_log_entries"];

    public static void Map(IEndpointRouteBuilder app)
    {
        var g = app.MapGroup("/api/v1/admin").RequireAuthorization(Policy);
        g.MapGet("/users", async (string? q, NpgsqlDataSource db, CancellationToken ct) =>
        {
            await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
            var rows = await Sql.QueryAsync(conn, null,
                "SELECT u.id, u.email, u.name, u.role, u.banned, u.created_at, COALESCE(f.balance, 0) FROM users u LEFT JOIN flux_accounts f ON f.user_id = u.id " +
                "WHERE u.deleted_at IS NULL AND ($1::text IS NULL OR u.email ILIKE '%' || $1 || '%' OR u.name ILIKE '%' || $1 || '%') ORDER BY u.created_at DESC LIMIT 200",
                r => (JsonNode)new JsonObject
                {
                    ["id"] = r.GetString(0), ["email"] = r.GetString(1), ["name"] = r.GetString(2), ["role"] = r.GetString(3), ["banned"] = r.GetBoolean(4),
                    ["createdAt"] = new DateTimeOffset(DateTime.SpecifyKind(r.GetDateTime(5), DateTimeKind.Utc)), ["flux"] = r.GetInt64(6),
                }, ct, Sql.Text(q)).ConfigureAwait(false);
            return Results.Json(new JsonObject { ["users"] = new JsonArray([.. rows]) });
        });
        g.MapPatch("/users/{id}", async (string id, HttpContext c, NpgsqlDataSource db, CancellationToken ct) =>
        {
            var b = await V9Endpoints.ReadJsonAsync(c.Request, "INVALID_REQUEST", ct).ConfigureAwait(false);
            var role = b?["role"]?.GetValue<string>();
            if (role is not (null or "user" or "admin"))
                throw ApiException.BadRequest("role must be user or admin", "INVALID_REQUEST");
            bool? banned = b?["banned"] is JsonValue bv && bv.TryGetValue<bool>(out var x) ? x : null;
            await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
            var n = await Sql.ExecAsync(conn, null,
                "UPDATE users SET role = COALESCE($2, role), banned = COALESCE($3, banned), ban_reason = CASE WHEN $3 IS TRUE THEN $4 WHEN $3 IS FALSE THEN NULL ELSE ban_reason END, updated_at = now() " +
                "WHERE id = $1 AND deleted_at IS NULL", ct, Sql.Text(id), Sql.Text(role), Sql.P(banned), Sql.Text(b?["banReason"]?.GetValue<string>())).ConfigureAwait(false);
            if (n == 0)
                throw ApiException.NotFound("user not found");
            if (banned == true)
                await Sql.ExecAsync(conn, null, "DELETE FROM auth_sessions WHERE user_id = $1", ct, Sql.Text(id)).ConfigureAwait(false);
            return Results.Json(new JsonObject { ["ok"] = true });
        });
        g.MapPost("/flux-grants", async (HttpContext c, FluxLedger flux, CancellationToken ct) =>
        {
            var b = await V9Endpoints.ReadJsonAsync(c.Request, "INVALID_REQUEST", ct).ConfigureAwait(false);
            var userId = b?["userId"]?.GetValue<string>() ?? throw ApiException.BadRequest("userId is required", "INVALID_REQUEST");
            var amount = b?["amount"] is JsonValue av && av.TryGetValue<long>(out var a) && a != 0 ? a : throw ApiException.BadRequest("amount must be a non-zero integer", "INVALID_REQUEST");
            var tx = await flux.ApplyAsync(userId, amount, amount > 0 ? "grant" : "adjustment", b?["reason"]?.GetValue<string>() ?? $"admin:{c.User.UserId()}",
                b?["idempotencyKey"]?.GetValue<string>(), new JsonObject { ["by"] = c.User.UserId() }, ct).ConfigureAwait(false);
            return Results.Json(JsonSerializer.SerializeToNode(tx, JsonSerializerOptions.Web), statusCode: 201);
        });
        g.MapGet("/gateway/routes", async (GatewayRoutes routes, CancellationToken ct) => Results.Json(await routes.MaskedAsync(ct).ConfigureAwait(false)));
        g.MapPut("/gateway/routes", async (HttpContext c, GatewayRoutes routes, CancellationToken ct) =>
        {
            var b = await V9Endpoints.ReadJsonAsync(c.Request, "INVALID_REQUEST", ct).ConfigureAwait(false) as JsonObject
                ?? throw ApiException.BadRequest("JSON object body required", "INVALID_REQUEST");
            foreach (var (alias, route) in b["models"] as JsonObject ?? [])
            {
                if (route?["upstream"] is not JsonValue u || !Uri.TryCreate(u.GetValue<string>(), UriKind.Absolute, out _))
                    throw ApiException.BadRequest($"models.{alias}.upstream must be an absolute URL", "INVALID_REQUEST");
            }
            ImageEndpoints.Validate(b);
            await routes.SaveAsync(await routes.ResolveMaskedKeysAsync(b, ct).ConfigureAwait(false), ct).ConfigureAwait(false);
            return Results.Json(new JsonObject { ["ok"] = true });
        });
        g.MapGet("/analytics/product-events", async (DateTimeOffset? from, DateTimeOffset? to, ProductEvents events, CancellationToken ct) =>
            Results.Json(new JsonObject { ["rows"] = await events.AggregateAsync(from ?? DateTimeOffset.UtcNow.AddDays(-30), to, ct).ConfigureAwait(false) }));
        g.MapGet("/llm-requests", async (NpgsqlDataSource db, CancellationToken ct) =>
        {
            await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
            var rows = await Sql.QueryAsync(conn, null,
                "SELECT id, user_id, model, upstream, status, prompt_tokens, completion_tokens, flux_charged, duration_ms, stream, created_at FROM llm_request_logs ORDER BY created_at DESC LIMIT 200",
                r => (JsonNode)new JsonObject
                {
                    ["id"] = r.GetString(0), ["userId"] = r.GetString(1), ["model"] = r.GetString(2), ["upstream"] = r.GetString(3), ["status"] = r.GetInt32(4),
                    ["promptTokens"] = r.IsDBNull(5) ? null : r.GetInt32(5), ["completionTokens"] = r.IsDBNull(6) ? null : r.GetInt32(6), ["fluxCharged"] = r.GetInt64(7),
                    ["durationMs"] = r.GetInt32(8), ["stream"] = r.GetBoolean(9), ["createdAt"] = new DateTimeOffset(DateTime.SpecifyKind(r.GetDateTime(10), DateTimeKind.Utc)),
                }, ct).ConfigureAwait(false);
            return Results.Json(new JsonObject { ["requests"] = new JsonArray([.. rows]) });
        });
        g.MapGet("/v9/stats", async (NpgsqlDataSource db, CancellationToken ct) =>
        {
            await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
            var o = new JsonObject();
            foreach (var table in V9Tables)
                o[table] = await Sql.CountAsync(conn, null, $"SELECT count(*) FROM {table}", ct).ConfigureAwait(false);
            o["renderTracesPartial"] = await Sql.CountAsync(conn, null, "SELECT count(*) FROM render_traces WHERE projection_status = 'partial'", ct).ConfigureAwait(false);
            o["pairingGaps"] = await Sql.CountAsync(conn, null, "SELECT count(*) FROM audit_log_entries WHERE action = 'render_ready_without_matching_request'", ct).ConfigureAwait(false);
            return Results.Json(o);
        });
        g.MapPost("/v9/render-trace-backfill", async (bool? dryRun, NpgsqlDataSource db, CancellationToken ct) =>
            Results.Json(JsonSerializer.SerializeToNode(await RenderTraceBackfill.RunAsync(db, dryRun ?? true, ct).ConfigureAwait(false), JsonSerializerOptions.Web)));
    }
}
