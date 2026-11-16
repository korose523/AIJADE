using System.Text.Json.Nodes;

using Aijade.Client.Api;

namespace Aijade.Client.Chat;

/// <summary>
/// What the user is reading or watching, as their browser extension (or IDE) last reported it, offered to the companion
/// while fresh. Off unless the user enables it.
/// </summary>
public sealed class LiveContextProvider(AijadeApi api, Func<bool> enabled, string source = "browser", TimeProvider? time = null) : IContextProvider
{
    public static TimeSpan Freshness { get; } = TimeSpan.FromMinutes(2);

    private readonly TimeProvider clock = time ?? TimeProvider.System;

    public static string Describe(JsonNode context, string source)
    {
        var parts = new List<string>();
        var what = source == "ide" ? "is working on" : context["kind"]?.GetValue<string>() == "video" ? "is watching" : "is reading";
        parts.Add($"The user {what}: \"{context["title"]?.GetValue<string>() ?? "(untitled)"}\"{(context["site"]?.GetValue<string>() is { } site ? $" on {site}" : "")}" +
                  $"{(context["position"]?.GetValue<string>() is { } at ? $", at {at}" : "")}.");
        if (context["text"]?.GetValue<string>() is { Length: > 0 } text)
            parts.Add($"{(context["kind"]?.GetValue<string>() == "video" ? "Current subtitles" : "Selected text")}: {text}");
        return string.Join(" ", parts);
    }

    public async Task<string?> SupplyAsync(TurnContext turn, CancellationToken ct)
    {
        if (!enabled())
            return null;
        try
        {
            if (await api.SendAsync(HttpMethod.Get, $"/api/v1/context/{source}", ct: ct).ConfigureAwait(false) is not JsonObject r || r["context"] is not { } context)
                return null;
            var at = r["updatedAt"]!.GetValue<DateTimeOffset>();
            return clock.GetUtcNow() - at > Freshness ? null : Describe(context, source);
        }
        catch (AijadeApiException)
        {
            return null;
        }
    }
}
