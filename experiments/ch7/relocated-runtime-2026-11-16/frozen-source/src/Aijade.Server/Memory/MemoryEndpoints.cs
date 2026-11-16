using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Server.Auth;
using Aijade.Server.Infrastructure;
using Aijade.Server.V9;

namespace Aijade.Server.Memory;


public static class MemoryEndpoints
{
    private static string S(JsonNode? body, string key) => body?[key]?.GetValue<string>() ?? throw ApiException.BadRequest($"{key} is required", "INVALID_MEMORY_REQUEST");

    private static int I(JsonNode? body, string key) => body?[key] is JsonValue v && v.TryGetValue<double>(out var d) && Math.Floor(d) == d
        ? (int)d : throw ApiException.BadRequest($"{key} must be an integer", "INVALID_MEMORY_REQUEST");

    public static void Map(IEndpointRouteBuilder app)
    {
        var g = app.MapGroup("/api/v1/memory").RequireAuthorization();
        g.MapPost("/persona-snapshots", async (HttpContext c, LongTermMemoryService m, CancellationToken ct) =>
        {
            var b = await V9Endpoints.ReadJsonAsync(c.Request, "INVALID_MEMORY_REQUEST", ct).ConfigureAwait(false);
            var snapshot = await m.SavePersonaSnapshotAsync(c.User.UserId(), new PersonaSnapshotInput(S(b, "deviceId"), I(b, "privacyLevel"),
                b?["persona"] as JsonObject ?? throw ApiException.BadRequest("persona is required", "INVALID_MEMORY_REQUEST"), I(b, "version"), b?["id"]?.GetValue<string>()), ct).ConfigureAwait(false);
            return Results.Json(snapshot, statusCode: 201);
        });
        g.MapPost("/persona-snapshots/from-memory", async (HttpContext c, LongTermMemoryService m, CancellationToken ct) =>
        {
            var b = await V9Endpoints.ReadJsonAsync(c.Request, "INVALID_MEMORY_REQUEST", ct).ConfigureAwait(false);
            try
            {
                var (snapshot, intent) = await m.DeriveForSessionAsync(new DeriveInput(c.User.UserId(), S(b, "sessionId"), S(b, "deviceId"), I(b, "privacyLevel"),
                    S(b, "agentId"), S(b, "userScope")), ct).ConfigureAwait(false);
                return Results.Json(new JsonObject { ["snapshot"] = snapshot, ["intent"] = intent }, statusCode: 201);
            }
            catch (NoEvidenceException)
            {
                throw new ApiException(422, "NO_EVIDENCE", "no committed long-term memory found for session");
            }
        });
        g.MapPost("/performance-intents", async (HttpContext c, LongTermMemoryService m, CancellationToken ct) =>
        {
            var b = await V9Endpoints.ReadJsonAsync(c.Request, "INVALID_MEMORY_REQUEST", ct).ConfigureAwait(false);
            var timeMarked = b?["timeMarked"] is JsonValue tv && tv.TryGetValue<double>(out var tm) ? tm : throw ApiException.BadRequest("timeMarked is required", "INVALID_MEMORY_REQUEST");
            var intent = await m.SavePerformanceIntentAsync(c.User.UserId(), new PerformanceIntentInput(S(b, "deviceId"), I(b, "privacyLevel"), S(b, "personaSnapshotRef"),
                b?["intent"] as JsonObject ?? throw ApiException.BadRequest("intent is required", "INVALID_MEMORY_REQUEST"), timeMarked, b?["id"]?.GetValue<string>()), ct).ConfigureAwait(false);
            return Results.Json(intent, statusCode: 201);
        });
        g.MapGet("/sync", async (HttpContext c, string? deviceId, LongTermMemoryService m, CancellationToken ct) =>
            string.IsNullOrEmpty(deviceId)
                ? Results.Json(new JsonObject { ["error"] = "deviceId is required" }, statusCode: 400)
                : Results.Json(new JsonObject { ["items"] = new JsonArray([.. (await m.PullForDeviceAsync(c.User.UserId(), deviceId, ct).ConfigureAwait(false)).Select(x => (JsonNode)x)]) }));
        g.MapGet("/notifications", async (HttpContext c, LongTermMemoryService m, CancellationToken ct) =>
            Results.Json(new JsonObject { ["notifications"] = new JsonArray([.. (await m.ListNotificationsAsync(c.User.UserId(), ct).ConfigureAwait(false)).Select(x => (JsonNode)x)]) }));
        g.MapPost("/notifications", async (HttpContext c, LongTermMemoryService m, CancellationToken ct) =>
        {
            var b = await V9Endpoints.ReadJsonAsync(c.Request, "INVALID_MEMORY_REQUEST", ct).ConfigureAwait(false);
            var id = b?["candidateId"]?.GetValue<string>() ?? S(b, "id");
            var score = b?["score"] is JsonValue sv && sv.TryGetValue<double>(out var sc) ? sc : throw ApiException.BadRequest("score is required", "INVALID_MEMORY_REQUEST");
            var n = await m.QueueShareNotificationAsync(c.User.UserId(), new ShareNotificationInput(id, S(b, "channel"), S(b, "contentRef"), score, I(b, "privacyLevel")), ct).ConfigureAwait(false);
            return Results.Json(n, statusCode: 202);
        });
        _ = CultureInfo.InvariantCulture;
        _ = JsonSerializerOptions.Web;
    }
}
