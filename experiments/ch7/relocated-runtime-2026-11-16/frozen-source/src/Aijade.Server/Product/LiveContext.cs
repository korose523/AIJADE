using System.Text.Json.Nodes;

using Aijade.Server.Auth;
using Aijade.Server.Infrastructure;
using Aijade.Server.V9;

using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Routing;

using Npgsql;

namespace Aijade.Server.Product;

/// <summary>
/// "What I am looking at": the browser extension reports the page or video in front of the user (title, address, the
/// subtitle line on screen); clients fetch it as context for the next turn. Only the latest report per source is kept.
/// </summary>
public static class LiveContextEndpoints
{
    public const int MaxText = 2000;

    public static void Map(IEndpointRouteBuilder app)
    {
        var g = app.MapGroup("/api/v1/context").RequireAuthorization();
        g.MapPut("/{source}", async (string source, HttpContext c, NpgsqlDataSource db, CancellationToken ct) =>
        {
            if (source is not ("browser" or "ide"))
                throw ApiException.BadRequest("source must be browser or ide", "INVALID_REQUEST");
            var b = await V9Endpoints.ReadJsonAsync(c.Request, "INVALID_REQUEST", ct).ConfigureAwait(false) as JsonObject
                ?? throw ApiException.BadRequest("JSON object body required", "INVALID_REQUEST");
            string? Field(string name, int max) => b[name]?.GetValue<string>() is { } v ? (v.Length > max ? v[..max] : v) : null;
            var payload = new JsonObject
            {
                ["title"] = Field("title", 300), ["url"] = Field("url", 1000), ["site"] = Field("site", 100), ["kind"] = Field("kind", 40),
                ["text"] = Field("text", MaxText), ["position"] = Field("position", 40),
            };
            await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
            await Sql.ExecAsync(conn, null,
                "INSERT INTO live_context (user_id, source, payload) VALUES ($1,$2,$3) ON CONFLICT (user_id, source) DO UPDATE SET payload = EXCLUDED.payload, updated_at = now()", ct,
                Sql.Text(c.User.UserId()), Sql.Text(source), Sql.Jsonb(payload)).ConfigureAwait(false);
            return Results.NoContent();
        });
        g.MapGet("/{source}", async (string source, HttpContext c, NpgsqlDataSource db, CancellationToken ct) =>
        {
            await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
            var rows = await Sql.QueryAsync(conn, null, "SELECT payload::text, updated_at FROM live_context WHERE user_id = $1 AND source = $2",
                r => (Payload: JsonNode.Parse(r.GetString(0)), At: new DateTimeOffset(DateTime.SpecifyKind(r.GetDateTime(1), DateTimeKind.Utc))), ct,
                Sql.Text(c.User.UserId()), Sql.Text(source)).ConfigureAwait(false);
            return rows.Count == 0 ? Results.NoContent() : Results.Json(new JsonObject { ["context"] = rows[0].Payload, ["updatedAt"] = rows[0].At });
        });
        g.MapDelete("/{source}", async (string source, HttpContext c, NpgsqlDataSource db, CancellationToken ct) =>
        {
            await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
            await Sql.ExecAsync(conn, null, "DELETE FROM live_context WHERE user_id = $1 AND source = $2", ct, Sql.Text(c.User.UserId()), Sql.Text(source)).ConfigureAwait(false);
            return Results.NoContent();
        });
    }
}
