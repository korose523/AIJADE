using System.Net.Http.Headers;
using System.Text;
using System.Text.Json.Nodes;

namespace Aijade.Integrations;

/// <summary>
/// X (Twitter) API v2: polls the bot account's mentions and replies to each. Needs an OAuth 2.0 user-context access token
/// of the bot account with tweet.read, tweet.write and users.read (posting is not possible with an app-only token). Every
/// mention is addressed to the bot, so each is answered (rate-limited per author by the bridge); replies are cut to 280.
/// </summary>
public sealed class XConnector(string accessToken, HttpClient http, TimeSpan? pollInterval = null) : IChannelConnector
{
    public const int MaxText = 280;
    private static readonly Uri Api = new("https://api.x.com/2/");

    public string Platform => "x";

    private async Task<JsonNode?> CallAsync(HttpMethod method, string path, JsonNode? body, CancellationToken ct)
    {
        using var req = new HttpRequestMessage(method, new Uri(Api, path));
        req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", accessToken);
        if (body is not null)
            req.Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json");
        using var res = await http.SendAsync(req, ct).ConfigureAwait(false);
        var text = await res.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
        if ((int)res.StatusCode == 429)
            throw new HttpRequestException("X rate limit reached", null, res.StatusCode);
        return res.IsSuccessStatusCode ? JsonNode.Parse(text) : throw new HttpRequestException($"X API {(int)res.StatusCode}: {text[..Math.Min(200, text.Length)]}", null, res.StatusCode);
    }

    /// <summary>Mentions as channel messages: each tweet is its own conversation thread, keyed by conversation_id.</summary>
    public static IReadOnlyList<(ChannelMessage Message, string TweetId)> ToChannelMessages(JsonNode? page, string selfId, string selfUsername)
    {
        var users = (page?["includes"]?["users"] as JsonArray ?? []).ToDictionary(u => u!["id"]!.GetValue<string>(), u => u!["name"]?.GetValue<string>() ?? u["username"]!.GetValue<string>());
        var list = new List<(ChannelMessage, string)>();
        foreach (var t in page?["data"] as JsonArray ?? [])
        {
            var author = t!["author_id"]?.GetValue<string>() ?? "";
            if (author.Length == 0 || author == selfId)
                continue;
            var text = (t["text"]?.GetValue<string>() ?? "").Replace($"@{selfUsername}", "", StringComparison.OrdinalIgnoreCase).Trim();
            if (text.Length == 0)
                continue;
            var conversation = t["conversation_id"]?.GetValue<string>() ?? t["id"]!.GetValue<string>();
            list.Add((new ChannelMessage("x", conversation, author, users.GetValueOrDefault(author, author), System.Net.WebUtility.HtmlDecode(text), false, true), t["id"]!.GetValue<string>()));
        }
        list.Reverse(); // the API lists newest first; answer in order
        return list;
    }

    public async Task RunAsync(Func<ChannelMessage, CancellationToken, Task<ChannelReply?>> handle, CancellationToken ct)
    {
        var me = await CallAsync(HttpMethod.Get, "users/me", null, ct).ConfigureAwait(false);
        var selfId = me!["data"]!["id"]!.GetValue<string>();
        var username = me["data"]!["username"]!.GetValue<string>();
        string? sinceId = null;
        var first = true;
        while (!ct.IsCancellationRequested)
        {
            var query = $"users/{selfId}/mentions?max_results=20&tweet.fields=author_id,conversation_id&expansions=author_id&user.fields=name" +
                        (sinceId is null ? "" : $"&since_id={sinceId}");
            var page = await CallAsync(HttpMethod.Get, query, null, ct).ConfigureAwait(false);
            if (page?["meta"]?["newest_id"]?.GetValue<string>() is { } newest)
                sinceId = newest;
            // Mentions from before the bot started are history, not questions waiting for an answer.
            if (!first)
            {
                foreach (var (message, tweetId) in ToChannelMessages(page, selfId, username))
                {
                    if (await handle(message, ct).ConfigureAwait(false) is { } reply && reply.Text.Length > 0)
                    {
                        var text = reply.Text.Length <= MaxText ? reply.Text : reply.Text[..(MaxText - 1)] + "…";
                        await CallAsync(HttpMethod.Post, "tweets", new JsonObject { ["text"] = text, ["reply"] = new JsonObject { ["in_reply_to_tweet_id"] = tweetId } }, ct).ConfigureAwait(false);
                    }
                }
            }
            first = false;
            await Task.Delay(pollInterval ?? TimeSpan.FromMinutes(1), ct).ConfigureAwait(false);
        }
    }
}
