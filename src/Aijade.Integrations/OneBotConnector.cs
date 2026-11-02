using System.Net;
using System.Net.Http.Headers;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Channels;

namespace Aijade.Integrations;

/// <summary>
/// QQ through OneBot 11 and NapCatQQ, the way the author's MOSAIC project reaches its owner (tools/companion_qq.py, r601;
/// ADR-003, migration batch 1). NapCat POSTs every event to this connector's address on 127.0.0.1, signed with the HMAC-SHA1
/// of the body under a shared secret ("X-Signature: sha1=…"), and takes actions on its own HTTP server with a bearer token
/// (send_private_msg). Only private text messages from the owner's QQ number are answered; group messages and other people
/// are counted and ignored. A post without the right signature is refused (403). The secret and the token need at least
/// 16 characters each. NapCat itself, under its own licence, is installed and run by the author; nothing here downloads it.
/// GET /health gives counts only, never what was said.
/// </summary>
public sealed class OneBotConnector : IChannelConnector, IProactiveConnector
{
    public const int MaxEventBytes = 1 << 20;

    /// <summary>Longest text sent as one QQ message; a longer reply is split.</summary>
    public const int MaxText = 3000;

    private readonly int port;
    private readonly Uri napcat;
    private readonly string token;
    private readonly string secret;
    private readonly string owner;
    private readonly HttpClient http;
    private int messages, answered, ignored;

    public OneBotConnector(int port, Uri napcat, string token, string secret, string owner, HttpClient http)
    {
        if (token.Length < 16 || secret.Length < 16)
            throw new ArgumentException("the NapCat token and the event secret need at least 16 characters each");
        if (napcat.Scheme != Uri.UriSchemeHttp || !string.IsNullOrEmpty(napcat.UserInfo) || !string.IsNullOrEmpty(napcat.Query))
            throw new ArgumentException("NapCat must be a plain http:// address");
        if (owner.Length == 0 || !owner.All(char.IsAsciiDigit))
            throw new ArgumentException("the owner's QQ number is required");
        this.port = port;
        this.napcat = new Uri(napcat.ToString().TrimEnd('/') + "/");
        this.token = token;
        this.secret = secret;
        this.owner = owner;
        this.http = http;
    }

    public string Platform => "qq";

    /// <summary>The OneBot 11 signature: "sha1=" and the hex HMAC-SHA1 of the raw body under the secret, compared in fixed time.</summary>
    public static bool HasValidSignature(byte[] body, string? header, string secret)
    {
        if (string.IsNullOrWhiteSpace(header))
            return false;
#pragma warning disable CA5350 // OneBot 11 defines the event signature as HMAC-SHA1; the protocol fixes the algorithm.
        var expected = "sha1=" + Convert.ToHexStringLower(HMACSHA1.HashData(Encoding.UTF8.GetBytes(secret), body));
#pragma warning restore CA5350
        return CryptographicOperations.FixedTimeEquals(Encoding.ASCII.GetBytes(header.Trim().ToLowerInvariant()), Encoding.ASCII.GetBytes(expected));
    }

    /// <summary>
    /// A private message from the owner as a channel message: its text segments joined (a "string" message format is taken
    /// as plain text). Null for anything else, and for a message without text (a picture or a voice message alone).
    /// </summary>
    public static ChannelMessage? ToChannelMessage(JsonObject evt, string owner)
    {
        if (Text(evt["post_type"]) != "message" || Text(evt["message_type"]) != "private" || evt["user_id"]?.ToString() != owner)
            return null;
        var text = evt["message"] switch
        {
            JsonValue v when v.TryGetValue<string>(out var s) => s,
            JsonArray segments => string.Concat(segments.OfType<JsonObject>().Where(s => Text(s["type"]) == "text").Select(s => s["data"]?["text"]?.ToString() ?? "")),
            _ => "",
        };
        text = text.Trim();
        if (text.Length == 0)
            return null;
        var name = Text(evt["sender"]?["nickname"]) is { Length: > 0 } nick ? nick : owner;
        return new ChannelMessage("qq", owner, owner, name, text, IsDirect: true, AddressesBot: true);
    }

    private static string? Text(JsonNode? node) => node is JsonValue v && v.TryGetValue<string>(out var s) ? s : null;

    public JsonObject Health() => new() { ["ok"] = true, ["messages"] = messages, ["answered"] = answered, ["ignored"] = ignored };

    public async Task RunAsync(Func<ChannelMessage, CancellationToken, Task<ChannelReply?>> handle, CancellationToken ct)
    {
        using var listener = new HttpListener();
        listener.Prefixes.Add($"http://127.0.0.1:{port}/");
        listener.Start();
        using var stop = ct.Register(listener.Stop);
        // Events are acknowledged at once (204) and answered in order by one worker, as in MOSAIC's bridge.
        var inbox = Channel.CreateBounded<ChannelMessage>(new BoundedChannelOptions(32) { FullMode = BoundedChannelFullMode.DropWrite });
        var worker = Task.Run(async () =>
        {
            await foreach (var message in inbox.Reader.ReadAllAsync(ct).ConfigureAwait(false))
            {
                try
                {
                    if (await handle(message, ct).ConfigureAwait(false) is { } reply)
                        await SendAsync(owner, reply.Text, ct).ConfigureAwait(false);
                }
                catch (Exception e) when (e is HttpRequestException or JsonException or InvalidOperationException)
                {
                    // One failed answer does not stop the next.
                }
            }
        }, ct);
        while (!ct.IsCancellationRequested)
        {
            HttpListenerContext context;
            try
            {
                context = await listener.GetContextAsync().ConfigureAwait(false);
            }
            catch (Exception e) when (ct.IsCancellationRequested && e is HttpListenerException or ObjectDisposedException or InvalidOperationException)
            {
                break;
            }
            await ServeAsync(context, inbox.Writer).ConfigureAwait(false);
        }
        inbox.Writer.TryComplete();
        try
        {
            await worker.ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
        }
    }

    private async Task ServeAsync(HttpListenerContext context, ChannelWriter<ChannelMessage> inbox)
    {
        var (req, res) = (context.Request, context.Response);
        try
        {
            if (req.HttpMethod == "GET" && req.Url?.AbsolutePath == "/health")
            {
                var health = Encoding.UTF8.GetBytes(Health().ToJsonString());
                res.ContentType = "application/json";
                await res.OutputStream.WriteAsync(health).ConfigureAwait(false);
                return;
            }
            if (req.HttpMethod != "POST")
            {
                res.StatusCode = 404;
                return;
            }
            using var buffer = new MemoryStream();
            var chunk = new byte[16 * 1024];
            int read;
            while ((read = await req.InputStream.ReadAsync(chunk).ConfigureAwait(false)) > 0)
            {
                if (buffer.Length + read > MaxEventBytes)
                {
                    res.StatusCode = 413;
                    return;
                }
                buffer.Write(chunk, 0, read);
            }
            var body = buffer.ToArray();
            if (!HasValidSignature(body, req.Headers["X-Signature"], secret))
            {
                res.StatusCode = 403;
                return;
            }
            res.StatusCode = 204; // no quick operation: the answer goes out on its own
            JsonObject? evt;
            try
            {
                evt = JsonNode.Parse(body) as JsonObject;
            }
            catch (JsonException)
            {
                return;
            }
            if (evt is null)
                return;
            if (ToChannelMessage(evt, owner) is { } message)
            {
                Interlocked.Increment(ref messages);
                inbox.TryWrite(message);
            }
            else if (Text(evt["post_type"]) == "message")
            {
                Interlocked.Increment(ref ignored);
            }
        }
        finally
        {
            res.Close();
        }
    }

    /// <summary>A message to the owner, the one conversation here (a reminder she promised, or a reply), split if long.</summary>
    public async Task SendAsync(string conversationId, string text, CancellationToken ct)
    {
        if (conversationId != owner)
            throw new InvalidOperationException("only the owner's private conversation is reached");
        foreach (var part in ChannelText.Split(text, MaxText))
            await PostAsync(part, ct).ConfigureAwait(false);
    }

    private async Task PostAsync(string text, CancellationToken ct)
    {
        var body = new JsonObject
        {
            ["user_id"] = long.Parse(owner, System.Globalization.CultureInfo.InvariantCulture),
            ["message"] = new JsonArray(new JsonObject { ["type"] = "text", ["data"] = new JsonObject { ["text"] = text } }),
        };
        using var req = new HttpRequestMessage(HttpMethod.Post, new Uri(napcat, "send_private_msg"))
        {
            Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json"),
        };
        req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        using var res = await http.SendAsync(req, ct).ConfigureAwait(false);
        var answer = JsonNode.Parse(await res.Content.ReadAsStringAsync(ct).ConfigureAwait(false)) as JsonObject;
        var retcode = answer?["retcode"] is JsonValue r && r.TryGetValue<int>(out var code) ? code : 0;
        if (!res.IsSuccessStatusCode || Text(answer?["status"]) != "ok" || retcode != 0)
            throw new HttpRequestException($"NapCat send_private_msg failed ({(int)res.StatusCode})");
        Interlocked.Increment(ref answered);
    }
}
