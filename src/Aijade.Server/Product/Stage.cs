using System.Text.Json.Nodes;

using Aijade.Server.Infrastructure;
using Aijade.Server.Auth;
using Aijade.Server.V9;

using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Routing;

namespace Aijade.Server.Product;

/// <summary>AIJADE-owned virtual scene endpoints. Legacy command vocabulary is retained, not external execution.</summary>
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

    /// <summary>The longest workbench notice relayed.</summary>
    public const int MaxNotice = 300;

    /// <summary>The workbench's last notice as relayed, cut to <see cref="MaxNotice"/>; null when it has none or it is not a string.</summary>
    public static string? Notice(JsonNode? notice) =>
        notice is JsonValue v && v.TryGetValue<string>(out var s) && s.Length > 0 ? s[..Math.Min(s.Length, MaxNotice)] : null;

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
            var words = command.Split([' ', '\t', '，', ','], 2, StringSplitOptions.RemoveEmptyEntries);
            if (words.Length == 0) return command;
            var head = words[0];
            if (!Heads.Contains(head))
                return command;
        }
        return null;
    }

    public const string NativeEnabledKey = "Stage:Enabled";

    public static void ValidateConfiguration(IConfiguration config)
    {
        if (!string.IsNullOrWhiteSpace(config[ConfigKey]))
            throw new InvalidOperationException("Stage:WorkbenchUrl is retired. Enable the AIJADE-owned virtual scene with Stage:Enabled=true; no external workbench is launched or contacted.");
        if (config[NativeEnabledKey] is { Length: > 0 } value && !bool.TryParse(value, out _))
            throw new InvalidOperationException("Stage:Enabled must be true or false");
    }

    private static void Enabled(IConfiguration config)
    {
        if (!bool.TryParse(config[NativeEnabledKey], out var enabled) || !enabled)
            throw ApiException.NotFound("the AIJADE native virtual scene is disabled");
    }

    public static void Map(IEndpointRouteBuilder app)
    {
        var g = app.MapGroup("/api/v1/stage").RequireAuthorization();
        g.MapGet("", async (HttpContext context, IConfiguration config, CompanionSyncStore companion, NativeStageStore scene, CancellationToken ct) =>
        {
            Enabled(config);
            var owner = context.User.UserId();
            var selected = context.Request.Query.TryGetValue("characterId", out var requested) ? requested.ToString() : null;
            var state = await companion.StateAsync(owner, selected is "default" or "" ? null : selected, current: selected is null, media: false, ct).ConfigureAwait(false);
            return Results.Json(await scene.ReadAsync(owner, state.CharacterId, ct).ConfigureAwait(false));
        });
        g.MapPost("/command", async (HttpContext context, IConfiguration config, CompanionSyncStore companion, NativeStageStore scene, CancellationToken ct) =>
        {
            Enabled(config);
            var node = await V9Endpoints.ReadJsonAsync(context.Request, "INVALID_REQUEST", ct).ConfigureAwait(false);
            if (node is not JsonObject body) throw ApiException.BadRequest("an object is required", "INVALID_REQUEST");
            var text = body["text"] is JsonValue value && value.TryGetValue<string>(out var content) ? content.Trim() : null;
            if (string.IsNullOrWhiteSpace(text) || text.Length > MaxCommand || text.Trim(';', '；', '\n', ' ', '\t').Length == 0)
                throw ApiException.BadRequest($"text must be 1-{MaxCommand} characters", "INVALID_REQUEST");
            if (Refused(text) is { } refused)
                throw ApiException.BadRequest($"not a stage command: {refused}", "STAGE_COMMAND_REFUSED");
            if (body.ContainsKey("commandId") && (body["commandId"] is not JsonValue identifier || !identifier.TryGetValue<string>(out _)))
                throw ApiException.BadRequest("commandId must be a string", "INVALID_REQUEST");
            var id = body["commandId"]?.GetValue<string>() ?? Guid.NewGuid().ToString("N");
            if (id.Length is < 1 or > 80 || id.Any(c => !char.IsAsciiLetterOrDigit(c) && c is not ('-' or '_' or ':')))
                throw ApiException.BadRequest("invalid commandId", "INVALID_REQUEST");
            long? revision = null;
            if (body.ContainsKey("expectedRevision"))
            {
                if (body["expectedRevision"] is not JsonValue r || !r.TryGetValue<long>(out var number) || number < 0)
                    throw ApiException.BadRequest("invalid expectedRevision", "INVALID_REQUEST");
                revision = number;
            }
            if (!body.ContainsKey("characterId") || body["characterId"] is not JsonValue role || !role.TryGetValue<string>(out var selected) || selected.Length is < 1 or > 128)
                throw ApiException.BadRequest("an explicit characterId is required; use default for the default character", "INVALID_REQUEST");
            var owner = context.User.UserId();
            var state = await companion.StateAsync(owner, selected == "default" ? null : selected, current: false, media: false, ct).ConfigureAwait(false);
            return Results.Json(await scene.ApplyAsync(owner, state.CharacterId, text, id, revision, ct).ConfigureAwait(false));
        });
    }
}
