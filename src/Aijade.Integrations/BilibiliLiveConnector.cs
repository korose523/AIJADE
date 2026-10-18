using System.Buffers.Binary;
using System.IO.Compression;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json.Nodes;

namespace Aijade.Integrations;

/// <summary>
/// Bilibili live-room danmaku over the room's WebSocket ("broadcastlv" protocol): 16-byte big-endian headers
/// [packet length][header length 16][protocol version][operation][sequence]; operation 7 authenticates with the room id and
/// the key from getDanmuInfo, 2 is the 30-second heartbeat (3 answers it), 8 confirms authentication, 5 carries commands —
/// raw JSON (version 0/1) or several packets compressed with zlib (2) or brotli (3). DANMU_MSG commands are viewer messages.
/// Bilibili hides viewers' names and ids from anonymous connections; with the owner's cookie (Bilibili:Cookie) they are
/// real, so memory can be kept per viewer. Replies are sent as danmaku only when that cookie includes bili_jct; otherwise
/// the connector listens. The protocol is Bilibili's and changes from time to time; the codec is tested, the live service is not.
/// </summary>
public sealed class BilibiliLiveConnector(long roomId, string? cookie, HttpClient http) : IChannelConnector
{
    public const int MaxDanmaku = 40;

    public string Platform => "bilibili";

    public const int OpHeartbeat = 2, OpHeartbeatReply = 3, OpMessage = 5, OpAuth = 7, OpAuthReply = 8;

    public static byte[] Encode(int operation, string body, short version = 1)
    {
        var payload = Encoding.UTF8.GetBytes(body);
        var packet = new byte[16 + payload.Length];
        BinaryPrimitives.WriteInt32BigEndian(packet, packet.Length);
        BinaryPrimitives.WriteInt16BigEndian(packet.AsSpan(4), 16);
        BinaryPrimitives.WriteInt16BigEndian(packet.AsSpan(6), version);
        BinaryPrimitives.WriteInt32BigEndian(packet.AsSpan(8), operation);
        BinaryPrimitives.WriteInt32BigEndian(packet.AsSpan(12), 1);
        payload.CopyTo(packet, 16);
        return packet;
    }

    /// <summary>Every (operation, body) in a frame, unpacking compressed batches.</summary>
    public static IEnumerable<(int Operation, byte[] Body)> Decode(byte[] frame)
    {
        var offset = 0;
        while (offset + 16 <= frame.Length)
        {
            var length = BinaryPrimitives.ReadInt32BigEndian(frame.AsSpan(offset));
            var header = BinaryPrimitives.ReadInt16BigEndian(frame.AsSpan(offset + 4));
            var version = BinaryPrimitives.ReadInt16BigEndian(frame.AsSpan(offset + 6));
            var operation = BinaryPrimitives.ReadInt32BigEndian(frame.AsSpan(offset + 8));
            if (length < header || offset + length > frame.Length)
                yield break;
            var body = frame.AsSpan(offset + header, length - header).ToArray();
            if (operation == OpMessage && version is 2 or 3)
            {
                using var input = new MemoryStream(body);
                using Stream unpack = version == 2 ? new ZLibStream(input, CompressionMode.Decompress) : new BrotliStream(input, CompressionMode.Decompress);
                using var output = new MemoryStream();
                unpack.CopyTo(output);
                foreach (var inner in Decode(output.ToArray()))
                    yield return inner;
            }
            else
            {
                yield return (operation, body);
            }
            offset += length;
        }
    }

    /// <summary>A DANMU_MSG command as a channel message (null for other commands). info[1] = text, info[2] = [uid, name, …].</summary>
    public static ChannelMessage? ToChannelMessage(JsonNode? command, long roomId)
    {
        if (command?["cmd"]?.GetValue<string>() is not { } cmd || !cmd.StartsWith("DANMU_MSG", StringComparison.Ordinal) || command["info"] is not JsonArray info || info.Count < 3)
            return null;
        var text = info[1]?.GetValue<string>()?.Trim() ?? "";
        var user = info[2] as JsonArray;
        var uid = user?[0]?.ToString() ?? "0";
        var name = user?[1]?.GetValue<string>() ?? "viewer";
        // Every danmaku is said to the streamer's companion in front of the audience: always addressed, never private.
        return text.Length == 0 ? null : new ChannelMessage("bilibili", roomId.ToString(System.Globalization.CultureInfo.InvariantCulture), uid, name, text, false, true);
    }

    private static string? CookieValue(string? cookie, string name) =>
        cookie?.Split(';').Select(p => p.Trim()).FirstOrDefault(p => p.StartsWith(name + "=", StringComparison.Ordinal))?[(name.Length + 1)..];

    private async Task<(Uri Host, string Key, long Uid)> DanmuInfoAsync(CancellationToken ct)
    {
        using var req = new HttpRequestMessage(HttpMethod.Get, $"https://api.live.bilibili.com/xlive/web-room/v1/index/getDanmuInfo?id={roomId}&type=0");
        if (cookie is { Length: > 0 })
            req.Headers.Add("Cookie", cookie);
        req.Headers.UserAgent.ParseAdd("Mozilla/5.0 AIJADE");
        using var res = await http.SendAsync(req, ct).ConfigureAwait(false);
        var json = JsonNode.Parse(await res.Content.ReadAsStringAsync(ct).ConfigureAwait(false));
        if (json?["code"]?.GetValue<int>() != 0)
            throw new InvalidOperationException($"getDanmuInfo failed: {json?["message"]}");
        var host = json["data"]?["host_list"]?[0];
        var uri = new Uri($"wss://{host?["host"]?.GetValue<string>() ?? "broadcastlv.chat.bilibili.com"}:{host?["wss_port"]?.GetValue<int>() ?? 443}/sub");
        var uid = long.TryParse(CookieValue(cookie, "DedeUserID"), out var u) ? u : 0;
        return (uri, json["data"]?["token"]?.GetValue<string>() ?? "", uid);
    }

    private async Task SendDanmakuAsync(string text, CancellationToken ct)
    {
        if (CookieValue(cookie, "bili_jct") is not { Length: > 0 } csrf)
            return; // listen-only without the owner's login
        var message = text.Length <= MaxDanmaku ? text : text[..(MaxDanmaku - 1)] + "…";
        using var req = new HttpRequestMessage(HttpMethod.Post, "https://api.live.bilibili.com/msg/send")
        {
            Content = new FormUrlEncodedContent(new Dictionary<string, string>
            {
                ["roomid"] = roomId.ToString(System.Globalization.CultureInfo.InvariantCulture), ["msg"] = message, ["color"] = "16777215", ["fontsize"] = "25",
                ["mode"] = "1", ["rnd"] = DateTimeOffset.UtcNow.ToUnixTimeSeconds().ToString(System.Globalization.CultureInfo.InvariantCulture), ["csrf"] = csrf, ["csrf_token"] = csrf,
            }),
        };
        req.Headers.Add("Cookie", cookie);
        using var res = await http.SendAsync(req, ct).ConfigureAwait(false);
        res.EnsureSuccessStatusCode();
    }

    public async Task RunAsync(Func<ChannelMessage, CancellationToken, Task<ChannelReply?>> handle, CancellationToken ct)
    {
        var (host, key, uid) = await DanmuInfoAsync(ct).ConfigureAwait(false);
        using var ws = new ClientWebSocket();
        if (cookie is { Length: > 0 })
            ws.Options.SetRequestHeader("Cookie", cookie);
        await ws.ConnectAsync(host, ct).ConfigureAwait(false);
        var auth = new JsonObject { ["uid"] = uid, ["roomid"] = roomId, ["protover"] = 3, ["platform"] = "web", ["type"] = 2, ["key"] = key };
        if (CookieValue(cookie, "buvid3") is { } buvid)
            auth["buvid"] = buvid;
        await ws.SendAsync(Encode(OpAuth, auth.ToJsonString()), WebSocketMessageType.Binary, true, ct).ConfigureAwait(false);
        using var beat = CancellationTokenSource.CreateLinkedTokenSource(ct);
        var heartbeat = Task.Run(async () =>
        {
            while (!beat.IsCancellationRequested)
            {
                await ws.SendAsync(Encode(OpHeartbeat, ""), WebSocketMessageType.Binary, true, beat.Token).ConfigureAwait(false);
                await Task.Delay(TimeSpan.FromSeconds(30), beat.Token).ConfigureAwait(false);
            }
        }, beat.Token);
        var buffer = new byte[64 * 1024];
        try
        {
            while (ws.State == WebSocketState.Open && !ct.IsCancellationRequested)
            {
                using var frame = new MemoryStream();
                WebSocketReceiveResult r;
                do
                {
                    r = await ws.ReceiveAsync(buffer, ct).ConfigureAwait(false);
                    frame.Write(buffer, 0, r.Count);
                }
                while (!r.EndOfMessage && r.MessageType != WebSocketMessageType.Close);
                if (r.MessageType == WebSocketMessageType.Close)
                    break;
                foreach (var (op, body) in Decode(frame.ToArray()))
                {
                    if (op != OpMessage || ToChannelMessage(JsonNode.Parse(body), roomId) is not { } incoming)
                        continue;
                    if (await handle(incoming, ct).ConfigureAwait(false) is { Text.Length: > 0 } reply)
                        await SendDanmakuAsync(reply.Text, ct).ConfigureAwait(false);
                }
            }
        }
        finally
        {
            await beat.CancelAsync().ConfigureAwait(false);
            try
            {
                await heartbeat.ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
            }
        }
    }
}
