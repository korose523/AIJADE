using System.Net.Http.Json;
using System.Text.Json.Nodes;

using Aijade.Server.Infrastructure;
using Aijade.Server.V9;

using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Routing;

namespace Aijade.Server.Product;

/// <summary>
/// The owner's stage in MOSAIC's home (docs/STAGE-MOSAIC.md, plan A step 2; ADR-002 supplement 4): relays the chat's stage
/// commands to MOSAIC's live-scene workbench and reads back whether the scene runs, where she is, her posture and the
/// motions she has learned lately (contract 1.4.0 A; ADR-002 supplement 5).
/// <list type="bullet">
/// <item>Off unless <c>Stage:WorkbenchUrl</c> is set; the address must be a loopback one, because the workbench has no
/// authentication and is never reached over a network. A non-loopback address stops the server at start.</item>
/// <item>Admins only: it drives a device on the server's machine.</item>
/// <item>Only the commands the chat sends pass (表情, 说, 去, 起来, 走路, 跳舞, 手势).</item>
/// <item>Of the learned motions only the contract's fields are relayed; the video's title and uploader reach only the owner's
/// client, which does not give them to a model.</item>
/// </list>
/// </summary>
public static class StageEndpoints
{
    public const string HttpClientName = "stage";

    public const string ConfigKey = "Stage:WorkbenchUrl";

    /// <summary>The longest command line relayed.</summary>
    public const int MaxCommand = 4000;

    /// <summary>The fields of a learned motion (contract 1.4.0 A); anything else in an item is not relayed.</summary>
    public static IReadOnlyList<string> LearnedFields { get; } = ["day", "skill", "skill_words", "kept_seconds", "novel_seconds", "video_title", "uploader", "source"];

    /// <summary>The most learned motions relayed; MOSAIC gives at most five, newest first.</summary>
    public const int MaxLearned = 5;

    /// <summary>The first words of the commands the chat sends.</summary>
    public static IReadOnlySet<string> Heads { get; } = new HashSet<string>(StringComparer.Ordinal) { "表情", "说", "去", "起来", "走路", "跳舞", "手势" };

    /// <summary>The workbench address, or null when none is set; throws when it is not an http(s) loopback address.</summary>
    public static Uri? Workbench(string? url)
    {
        if (string.IsNullOrWhiteSpace(url))
            return null;
        if (!Uri.TryCreate(url, UriKind.Absolute, out var uri) || uri.Scheme is not ("http" or "https") || !uri.IsLoopback)
            throw new InvalidOperationException($"{ConfigKey} must be an http(s) address on this machine (localhost, 127.0.0.1 or [::1]): the workbench has no authentication");
        return uri;
    }

    /// <summary>
    /// The workbench's learned motions as relayed: the contract's fields of the first <see cref="MaxLearned"/> items, each
    /// value a string, a number or null; an empty array when there are none.
    /// </summary>
    public static JsonArray Learned(JsonNode? learned)
    {
        var items = new JsonArray();
        foreach (var item in (learned as JsonArray ?? []).OfType<JsonObject>().Take(MaxLearned))
        {
            var copy = new JsonObject();
            foreach (var field in LearnedFields)
            {
                if (item[field] is JsonValue v && (v.GetValueKind() is System.Text.Json.JsonValueKind.String or System.Text.Json.JsonValueKind.Number))
                    copy[field] = v.DeepClone();
                else if (item.ContainsKey(field) && item[field] is null)
                    copy[field] = null;
            }
            items.Add(copy);
        }
        return items;
    }

    /// <summary>The first command of the line whose first word is not one the chat sends, or null when all pass.</summary>
    public static string? Refused(string line)
    {
        foreach (var command in line.Split([';', '；', '\n'], StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries))
        {
            var head = command.Split([' ', '\t', '，', ','], 2, StringSplitOptions.RemoveEmptyEntries)[0];
            if (!Heads.Contains(head))
                return command;
        }
        return null;
    }

    public static void Map(IEndpointRouteBuilder app)
    {
        var g = app.MapGroup("/api/v1/stage").RequireAuthorization(AdminEndpoints.Policy);
        g.MapGet("", async (IConfiguration config, IHttpClientFactory http, CancellationToken ct) =>
        {
            var workbench = Workbench(config[ConfigKey]) ?? throw ApiException.NotFound("no stage is configured");
            JsonObject? state;
            try
            {
                state = await http.CreateClient(HttpClientName).GetFromJsonAsync<JsonObject>(new Uri(workbench, "/api/v1/live-scene"), ct).ConfigureAwait(false);
            }
            catch (Exception e) when (e is HttpRequestException or TaskCanceledException or System.Text.Json.JsonException)
            {
                return Results.Json(new JsonObject { ["running"] = false, ["reachable"] = false, ["learned"] = new JsonArray() });
            }
            var running = state?["running"]?.GetValue<bool>() == true;
            return Results.Json(new JsonObject
            {
                ["running"] = running, ["reachable"] = true,
                ["where"] = running ? state?["where"]?.GetValue<string>() : null,
                ["posture"] = running ? state?["posture"]?.GetValue<string>() : null,
                ["learned"] = running ? Learned(state?["learned"]) : new JsonArray(),
            });
        });
        g.MapPost("/command", async (HttpContext c, IConfiguration config, IHttpClientFactory http, CancellationToken ct) =>
        {
            var workbench = Workbench(config[ConfigKey]) ?? throw ApiException.NotFound("no stage is configured");
            var b = await V9Endpoints.ReadJsonAsync(c.Request, "INVALID_REQUEST", ct).ConfigureAwait(false);
            var text = b?["text"]?.GetValue<string>()?.Trim();
            if (string.IsNullOrEmpty(text) || text.Length > MaxCommand)
                throw ApiException.BadRequest($"text must be 1-{MaxCommand} characters", "INVALID_REQUEST");
            if (Refused(text) is { } refused)
                throw ApiException.BadRequest($"not a stage command: {refused}", "STAGE_COMMAND_REFUSED");
            HttpResponseMessage res;
            try
            {
                res = await http.CreateClient(HttpClientName).PostAsJsonAsync(new Uri(workbench, "/api/v1/live-scene/command"), new { text }, ct).ConfigureAwait(false);
            }
            catch (Exception e) when (e is HttpRequestException or TaskCanceledException)
            {
                throw new ApiException(502, "STAGE_UNREACHABLE", "the stage's workbench does not answer");
            }
            using (res)
            {
                if (!res.IsSuccessStatusCode)
                {
                    string? error = null;
                    try
                    {
                        error = JsonNode.Parse(await res.Content.ReadAsStringAsync(ct).ConfigureAwait(false))?["error"]?.GetValue<string>();
                    }
                    catch (Exception e) when (e is System.Text.Json.JsonException or InvalidOperationException)
                    {
                    }
                    throw ApiException.BadRequest(error ?? $"the workbench refused the command ({(int)res.StatusCode})", "STAGE_COMMAND_REFUSED");
                }
            }
            return Results.Json(new JsonObject { ["ok"] = true });
        });
    }
}
