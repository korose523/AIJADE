using System.Net.Http.Headers;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace Aijade.Integrations;

/// <summary>
/// Satori (the cross-platform chatbot protocol of Koishi and others): events over WebSocket at {base}/v1/events (signals
/// IDENTIFY 3 → READY 4, PING 1 / PONG 2 every 10 s, EVENT 0), replies with POST {base}/v1/message.create. Direct
/// channels (type 1) are always answered; elsewhere when the bot is &lt;at&gt;-mentioned or quoted.
/// </summary>
public sealed partial class SatoriConnector(Uri baseUrl, string? token, HttpClient http) : IChannelConnector
{
    public string Platform => "satori";

    [GeneratedRegex("<at\\s+id=\"([^\"]+)\"[^>]*/?>", RegexOptions.CultureInvariant)]
    private static partial Regex At();

    [GeneratedRegex("<[^>]+>", RegexOptions.CultureInvariant)]
    private static partial Regex Tag();

    /// <summary>Satori message elements to plain text (mentions of the bot removed, other tags dropped, entities decoded).</summary>
    public static string PlainText(string content, string selfId) =>
        System.Net.WebUtility.HtmlDecode(Tag().Replace(At().Replace(content, m => m.Groups[1].Value == selfId ? "" : "@" + m.Groups[1].Value), "")).Trim();

    /// <summary>A message-created event as a channel message (null for anything else, or the bot's own messages).</summary>
    public static (ChannelMessage Message, string Platform, string SelfId, string ChannelId)? ToChannelMessage(JsonObject body)
    {
        if (body["type"]?.GetValue<string>() != "message-created" || body["message"] is not JsonObject message || body["channel"] is not JsonObject channel)
            return null;
        var selfId = body["self_id"]?.ToString() ?? body["login"]?["user"]?["id"]?.ToString() ?? "";
        var user = body["user"] as JsonObject ?? message["user"] as JsonObject;
        var userId = user?["id"]?.ToString() ?? "";
        if (userId.Length == 0 || userId == selfId)
            return null;
        var content = message["content"]?.GetValue<string>() ?? "";
        var text = PlainText(content, selfId);
        if (text.Length == 0)
            return null;
        var platform = body["platform"]?.GetValue<string>() ?? body["login"]?["platform"]?.GetValue<string>() ?? "satori";
        var channelId = channel["id"]!.ToString();
        var direct = channel["type"]?.GetValue<int>() == 1;
        var mentioned = At().Matches(content).Any(m => m.Groups[1].Value == selfId) || message["quote"]?["user"]?["id"]?.ToString() == selfId;
        var name = body["member"]?["nick"]?.GetValue<string>() ?? user?["nick"]?.GetValue<string>() ?? user?["name"]?.GetValue<string>() ?? userId;
        return (new ChannelMessage($"satori-{platform}", channelId, userId, name, text, direct, mentioned), platform, selfId, channelId);
    }

    private async Task SendAsync(string platform, string selfId, string channelId, string content, CancellationToken ct)
    {
        using var req = new HttpRequestMessage(HttpMethod.Post, new Uri(baseUrl, "v1/message.create"))
        {
            Content = new StringContent(new JsonObject { ["channel_id"] = channelId, ["content"] = content }.ToJsonString(), Encoding.UTF8, "application/json"),
        };
        if (token is { Length: > 0 })
            req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        req.Headers.Add("Satori-Platform", platform);
        req.Headers.Add("Satori-User-ID", selfId);
        req.Headers.Add("X-Platform", platform); // older Satori servers
        req.Headers.Add("X-Self-ID", selfId);
        using var res = await http.SendAsync(req, ct).ConfigureAwait(false);
        res.EnsureSuccessStatusCode();
    }

    public async Task RunAsync(Func<ChannelMessage, CancellationToken, Task<ChannelReply?>> handle, CancellationToken ct)
    {
        using var ws = new ClientWebSocket();
        var events = new UriBuilder(new Uri(baseUrl, "v1/events")) { Scheme = baseUrl.Scheme == "https" ? "wss" : "ws" }.Uri;
        await ws.ConnectAsync(events, ct).ConfigureAwait(false);
        await SendSignalAsync(ws, new JsonObject { ["op"] = 3, ["body"] = new JsonObject { ["token"] = token ?? "" } }, ct).ConfigureAwait(false);
        using var heartbeat = CancellationTokenSource.CreateLinkedTokenSource(ct);
        var ping = Task.Run(async () =>
        {
            while (!heartbeat.IsCancellationRequested)
            {
                await Task.Delay(TimeSpan.FromSeconds(10), heartbeat.Token).ConfigureAwait(false);
                await SendSignalAsync(ws, new JsonObject { ["op"] = 1 }, heartbeat.Token).ConfigureAwait(false);
            }
        }, heartbeat.Token);
        try
        {
            while (ws.State == WebSocketState.Open && !ct.IsCancellationRequested)
            {
                if (await ReceiveAsync(ws, ct).ConfigureAwait(false) is not JsonObject signal)
                    break;
                if (signal["op"]?.GetValue<int>() != 0 || signal["body"] is not JsonObject body || ToChannelMessage(body) is not { } incoming)
                    continue;
                _ = Task.Run(async () =>
                {
                    if (await handle(incoming.Message, ct).ConfigureAwait(false) is { } reply)
                    {
                        var content = System.Net.WebUtility.HtmlEncode(reply.Text);
                        if (reply.Image is { } image)
                            content = $"<img src=\"{System.Net.WebUtility.HtmlEncode(image.Url)}\"/>" + content;
                        await SendAsync(incoming.Platform, incoming.SelfId, incoming.ChannelId, content, ct).ConfigureAwait(false);
                    }
                }, ct);
            }
        }
        finally
        {
            await heartbeat.CancelAsync().ConfigureAwait(false);
            try
            {
                await ping.ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
            }
        }
    }

    private static Task SendSignalAsync(ClientWebSocket ws, JsonObject signal, CancellationToken ct) =>
        ws.SendAsync(Encoding.UTF8.GetBytes(signal.ToJsonString()), WebSocketMessageType.Text, true, ct);

    private static async Task<JsonNode?> ReceiveAsync(ClientWebSocket ws, CancellationToken ct)
    {
        var buffer = new byte[8192];
        using var text = new MemoryStream();
        while (true)
        {
            var r = await ws.ReceiveAsync(buffer, ct).ConfigureAwait(false);
            if (r.MessageType == WebSocketMessageType.Close)
                return null;
            text.Write(buffer, 0, r.Count);
            if (r.EndOfMessage)
                return JsonNode.Parse(text.ToArray());
        }
    }
}
