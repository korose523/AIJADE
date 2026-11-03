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
/// (send_private_msg). Only private messages from the owner's QQ number are answered; group messages and other people are
/// counted and ignored. A voice message is fetched from NapCat as WAV (get_record) and transcribed when the host gives a
/// transcriber (OneBot:Voice, through the server's speech recognition), and its words join the message's text. A message
/// with no words after that (a picture, a sticker, or a voice message that is not transcribed) is answered with MOSAIC's
/// fixed line <see cref="OnlyTextReply"/>, without the model. A post without the right signature is refused (403). The secret
/// and the token need at least 16 characters each. NapCat itself, under its own licence, is installed and run by the
/// author; nothing here downloads it. GET /health gives counts only, never what was said.
/// </summary>
public sealed class OneBotConnector : IChannelConnector, IProactiveConnector
{
    public const int MaxEventBytes = 1 << 20;

    /// <summary>Longest text sent as one QQ message; a longer reply is split.</summary>
    public const int MaxText = 3000;

    /// <summary>
    /// MOSAIC's answer to a message without words (ONLY_TEXT_REPLY of tools/companion_qq.py, r601). The shared contract leaves
    /// it out for AIJADE's channels, which serve many users in several languages; this connector answers only its owner.
    /// </summary>
    public const string OnlyTextReply = "我现在只看得懂文字和语音哦。";

    /// <summary>Largest answer taken from NapCat for a voice message (MOSAIC reads at most 8 MiB).</summary>
    public const int MaxRecordBytes = 8 << 20;

    private readonly int port;
    private readonly Uri napcat;
    private readonly string token;
    private readonly string secret;
    private readonly string owner;
    private readonly HttpClient http;
    private readonly Func<byte[], CancellationToken, Task<string>>? transcribe;
    private int messages, answered, ignored, heard;

    /// <param name="port">The port on 127.0.0.1 where NapCat posts its events.</param>
    /// <param name="napcat">NapCat's OneBot 11 HTTP server, a plain http:// address.</param>
    /// <param name="token">NapCat's access token (at least 16 characters).</param>
    /// <param name="secret">The secret NapCat signs its events with (at least 16 characters).</param>
    /// <param name="owner">The owner's QQ number: the one person answered.</param>
    /// <param name="http">For NapCat's actions.</param>
    /// <param name="transcribe">Turns a voice message's WAV into words; without it voice messages are not heard.</param>
    public OneBotConnector(int port, Uri napcat, string token, string secret, string owner, HttpClient http,
        Func<byte[], CancellationToken, Task<string>>? transcribe = null)
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
        this.transcribe = transcribe;
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

    /// <summary>A private message from the owner: its text, the files of its voice messages, how many other segments it has.</summary>
    public sealed record OwnerMessage(string Text, IReadOnlyList<string> Voices, int Other, string Name);

    /// <summary>
    /// A private message from the owner, as MOSAIC's owner_message reads it: the text segments joined (a "string" message
    /// format is plain text), the voice segments' files, and a count of everything else (pictures, stickers, …). Null for
    /// anything that is not a private message from the owner.
    /// </summary>
    public static OwnerMessage? ReadOwnerMessage(JsonObject evt, string owner)
    {
        if (Text(evt["post_type"]) != "message" || Text(evt["message_type"]) != "private" || evt["user_id"]?.ToString() != owner)
            return null;
        var name = Text(evt["sender"]?["nickname"]) is { Length: > 0 } nick ? nick : owner;
        if (evt["message"] is JsonValue v && v.TryGetValue<string>(out var plain))
            return new OwnerMessage(plain.Trim(), [], 0, name);
        var text = new StringBuilder();
        var voices = new List<string>();
        var other = 0;
        foreach (var segment in (evt["message"] as JsonArray ?? []).OfType<JsonObject>())
        {
            var data = segment["data"] as JsonObject;
            var file = data?["file"]?.ToString();
            switch (Text(segment["type"]))
            {
                case "text":
                    text.Append(data?["text"]?.ToString() ?? "");
                    break;
                case "record" when file is { Length: > 0 }:
                    voices.Add(file);
                    break;
                default:
                    other++;
                    break;
            }
        }
        return new OwnerMessage(text.ToString().Trim(), voices, other, name);
    }

    /// <summary>A private text message from the owner as a channel message; null for anything else and for a message without words.</summary>
    public static ChannelMessage? ToChannelMessage(JsonObject evt, string owner) =>
        ReadOwnerMessage(evt, owner) is { Text.Length: > 0 } m ? new ChannelMessage("qq", owner, owner, m.Name, m.Text, IsDirect: true, AddressesBot: true) : null;

    private static string? Text(JsonNode? node) => node is JsonValue v && v.TryGetValue<string>(out var s) ? s : null;

    public JsonObject Health() => new() { ["ok"] = true, ["messages"] = messages, ["answered"] = answered, ["ignored"] = ignored, ["voicesHeard"] = heard };

    public async Task RunAsync(Func<ChannelMessage, CancellationToken, Task<ChannelReply?>> handle, CancellationToken ct)
    {
        using var listener = new HttpListener();
        listener.Prefixes.Add($"http://127.0.0.1:{port}/");
        listener.Start();
        using var stop = ct.Register(listener.Stop);
        // Events are acknowledged at once (204) and answered in order by one worker, as in MOSAIC's bridge.
        var inbox = Channel.CreateBounded<OwnerMessage>(new BoundedChannelOptions(32) { FullMode = BoundedChannelFullMode.DropWrite });
        var worker = Task.Run(async () =>
        {
            await foreach (var message in inbox.Reader.ReadAllAsync(ct).ConfigureAwait(false))
            {
                try
                {
                    var text = message.Text;
                    if (transcribe is not null)
                    {
                        foreach (var file in message.Voices)
                        {
                            if (await RecordAsync(file, ct).ConfigureAwait(false) is not { } wav)
                                continue;
                            text = (text + " " + await transcribe(wav, ct).ConfigureAwait(false)).Trim();
                            Interlocked.Increment(ref heard);
                        }
                    }
                    if (text.Length == 0)
                    {
                        await SendAsync(owner, OnlyTextReply, ct).ConfigureAwait(false);
                        continue;
                    }
                    if (await handle(new ChannelMessage("qq", owner, owner, message.Name, text, IsDirect: true, AddressesBot: true), ct).ConfigureAwait(false) is { } reply)
                        await SendAsync(owner, reply.Text, ct).ConfigureAwait(false);
                }
                catch (Exception) when (!ct.IsCancellationRequested)
                {
                    // One failed answer (NapCat, recognition or the server unreachable, or too slow: an HttpClient timeout is a
                    // TaskCanceledException) does not stop the next, as in MOSAIC's bridge.
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

    private async Task ServeAsync(HttpListenerContext context, ChannelWriter<OwnerMessage> inbox)
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
            if (ReadOwnerMessage(evt, owner) is { } message)
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

    /// <summary>A voice message as WAV (NapCat get_record, out_format wav), or null when NapCat gives no audio.</summary>
    private async Task<byte[]?> RecordAsync(string file, CancellationToken ct)
    {
        var body = new JsonObject { ["file"] = file, ["out_format"] = "wav" };
        using var req = new HttpRequestMessage(HttpMethod.Post, new Uri(napcat, "get_record"))
        {
            Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json"),
        };
        req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        using var res = await http.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false);
        if (res.Content.Headers.ContentLength > MaxRecordBytes)
            throw new HttpRequestException("NapCat get_record answered more than 8 MiB");
        var answer = JsonNode.Parse(await res.Content.ReadAsStringAsync(ct).ConfigureAwait(false)) as JsonObject;
        var retcode = answer?["retcode"] is JsonValue r && r.TryGetValue<int>(out var code) ? code : 0;
        if (!res.IsSuccessStatusCode || Text(answer?["status"]) != "ok" || retcode != 0)
            throw new HttpRequestException($"NapCat get_record failed ({(int)res.StatusCode})");
        return Text(answer?["data"]?["base64"]) is { Length: > 0 } b64 ? Convert.FromBase64String(b64) : null;
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
