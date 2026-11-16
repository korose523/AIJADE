using System.Net.WebSockets;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Server.Infrastructure;

namespace Aijade.Server.Product;

// Alibaba Cloud Model Studio (DashScope) speech synthesis through its native APIs, for the gateway's "speech" section:
//   aliyun-qwen-tts    POST {upstream}/services/aigc/multimodal-generation/generation (Qwen-TTS); the answer carries the audio
//                      either inline (base64) or as a short-lived URL that is downloaded at once.
//                      upstream default: https://dashscope.aliyuncs.com/api/v1
//   aliyun-cosyvoice   the duplex WebSocket task protocol (CosyVoice): run-task → task-started → continue-task (the text) →
//                      finish-task; audio arrives as binary frames until task-finished (or task-failed).
//                      upstream default: wss://dashscope.aliyuncs.com/api-ws/v1/inference
// Keys rotate as for every gateway route: an authentication failure penalizes the key and the next one is tried.

public sealed record SynthesizedSpeech(byte[] Audio, string Mime);

public static class AliyunSpeech
{
    public const string QwenTts = "aliyun-qwen-tts";
    public const string CosyVoice = "aliyun-cosyvoice";

    /// <summary>Largest audio accepted from the provider.</summary>
    public const int MaxBytes = 25 * 1024 * 1024;

    public static async Task<SynthesizedSpeech> QwenTtsAsync(HttpClient http, KeyRotator keys, GatewayRoute route, string text, string voice, CancellationToken ct)
    {
        var body = new JsonObject
        {
            ["model"] = route.Model,
            ["input"] = new JsonObject { ["text"] = text, ["voice"] = voice.Length > 0 ? voice : "Cherry" },
        };
        using var res = await GatewayEndpoints.SendAsync(http, keys, route, "/services/aigc/multimodal-generation/generation",
            () => new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json"), ct).ConfigureAwait(false);
        var raw = await res.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
        if (!res.IsSuccessStatusCode)
            throw new ApiException(502, "UPSTREAM_ERROR", $"The upstream speech provider failed ({(int)res.StatusCode}{ErrorDetail(raw)})");
        JsonNode? json;
        try
        {
            json = JsonNode.Parse(raw);
        }
        catch (System.Text.Json.JsonException)
        {
            throw new ApiException(502, "UPSTREAM_ERROR", "The upstream speech provider did not return JSON");
        }
        var audio = json?["output"]?["audio"];
        if (audio?["data"]?.GetValue<string>() is { Length: > 0 } b64)
        {
            try
            {
                return Checked(Convert.FromBase64String(b64), "audio/wav");
            }
            catch (FormatException)
            {
                throw new ApiException(502, "UPSTREAM_ERROR", "The upstream speech provider returned invalid audio data");
            }
        }
        if (audio?["url"]?.GetValue<string>() is not { Length: > 0 } url || !Uri.TryCreate(url, UriKind.Absolute, out var uri) || uri.Scheme is not ("https" or "http"))
            throw new ApiException(502, "UPSTREAM_ERROR", "The upstream speech provider returned no audio");
        // The URL is signed and short-lived; it is fetched without the API key.
        using var download = await http.GetAsync(uri, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false);
        if (!download.IsSuccessStatusCode)
            throw new ApiException(502, "UPSTREAM_ERROR", $"Downloading the synthesized audio failed ({(int)download.StatusCode})");
        if (download.Content.Headers.ContentLength > MaxBytes)
            throw new ApiException(502, "UPSTREAM_ERROR", "The synthesized audio is too large");
        var bytes = await download.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false);
        var mime = download.Content.Headers.ContentType?.MediaType is { } m && m.StartsWith("audio/", StringComparison.Ordinal) ? m : "audio/wav";
        return Checked(bytes, mime);
    }

    /// <summary>
    /// CosyVoice over the duplex WebSocket task protocol. <paramref name="connect"/> opens the socket (tests point it at a
    /// local server); the key is sent as a bearer token in the handshake.
    /// </summary>
    public static async Task<SynthesizedSpeech> CosyVoiceAsync(KeyRotator keys, GatewayRoute route, JsonObject section, string text, string voice, TimeSpan timeout,
        Func<Uri, string, CancellationToken, Task<WebSocket>> connect, CancellationToken ct)
    {
        var order = keys.Order(route);
        if (order.Count == 0)
            throw new ApiException(503, "GATEWAY_UNCONFIGURED", $"no upstream key configured for '{route.Alias}'");
        if (!Uri.TryCreate(route.Upstream, UriKind.Absolute, out var endpoint) || endpoint.Scheme is not ("wss" or "ws"))
            throw new ApiException(503, "GATEWAY_UNCONFIGURED", "speech.upstream must be a ws:// or wss:// URL for aliyun-cosyvoice");
        var format = section["format"]?.GetValue<string>() is { Length: > 0 } f ? f : "mp3";
        var sampleRate = section["sampleRate"]?.GetValue<int>() ?? 22050;
        ApiException? last = null;
        foreach (var key in order)
        {
            try
            {
                using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
                cts.CancelAfter(timeout);
                return await CosyVoiceOnceAsync(endpoint, key, route.Model, voice.Length > 0 ? voice : section["voice"]?.GetValue<string>() ?? "longxiaochun_v2",
                    format, sampleRate, text, connect, cts.Token).ConfigureAwait(false);
            }
            catch (CosyVoiceAuthException e)
            {
                keys.Penalize(key);
                last = new ApiException(502, "UPSTREAM_ERROR", $"The upstream speech provider refused the key ({e.Message})");
            }
            catch (OperationCanceledException) when (!ct.IsCancellationRequested)
            {
                throw new ApiException(504, "UPSTREAM_TIMEOUT", "The upstream speech provider timed out");
            }
            catch (WebSocketException e)
            {
                throw new ApiException(502, "UPSTREAM_UNREACHABLE", $"The upstream speech provider could not be reached ({e.Message})");
            }
        }
        throw last!;
    }

    private sealed class CosyVoiceAuthException(string message) : Exception(message);

    private static async Task<SynthesizedSpeech> CosyVoiceOnceAsync(Uri endpoint, string key, string model, string voice, string format, int sampleRate, string text,
        Func<Uri, string, CancellationToken, Task<WebSocket>> connect, CancellationToken ct)
    {
        WebSocket ws;
        try
        {
            ws = await connect(endpoint, key, ct).ConfigureAwait(false);
        }
        catch (WebSocketException e) when (e.Message.Contains("401", StringComparison.Ordinal) || e.Message.Contains("403", StringComparison.Ordinal))
        {
            throw new CosyVoiceAuthException(e.Message);
        }
        using (ws)
        {
            var taskId = Guid.NewGuid().ToString("N");
            JsonObject Header(string action) => new() { ["action"] = action, ["task_id"] = taskId, ["streaming"] = "duplex" };
            await SendAsync(ws, new JsonObject
            {
                ["header"] = Header("run-task"),
                ["payload"] = new JsonObject
                {
                    ["task_group"] = "audio",
                    ["task"] = "tts",
                    ["function"] = "SpeechSynthesizer",
                    ["model"] = model,
                    ["parameters"] = new JsonObject { ["text_type"] = "PlainText", ["voice"] = voice, ["format"] = format, ["sample_rate"] = sampleRate, ["volume"] = 50, ["rate"] = 1, ["pitch"] = 1 },
                    ["input"] = new JsonObject(),
                },
            }, ct).ConfigureAwait(false);

            using var audio = new MemoryStream();
            var started = false;
            var buffer = new byte[64 * 1024];
            using var message = new MemoryStream();
            while (true)
            {
                message.SetLength(0);
                WebSocketReceiveResult r;
                do
                {
                    r = await ws.ReceiveAsync(buffer, ct).ConfigureAwait(false);
                    if (r.MessageType == WebSocketMessageType.Close)
                        throw new ApiException(502, "UPSTREAM_ERROR", "The upstream speech provider closed the connection before finishing");
                    message.Write(buffer, 0, r.Count);
                    if (audio.Length + message.Length > MaxBytes)
                        throw new ApiException(502, "UPSTREAM_ERROR", "The synthesized audio is too large");
                }
                while (!r.EndOfMessage);

                if (r.MessageType == WebSocketMessageType.Binary)
                {
                    message.Position = 0;
                    await message.CopyToAsync(audio, ct).ConfigureAwait(false);
                    continue;
                }
                var header = JsonNode.Parse(Encoding.UTF8.GetString(message.GetBuffer(), 0, (int)message.Length))?["header"];
                switch (header?["event"]?.GetValue<string>())
                {
                    case "task-started" when !started:
                        started = true;
                        await SendAsync(ws, new JsonObject { ["header"] = Header("continue-task"), ["payload"] = new JsonObject { ["input"] = new JsonObject { ["text"] = text } } }, ct).ConfigureAwait(false);
                        await SendAsync(ws, new JsonObject { ["header"] = Header("finish-task"), ["payload"] = new JsonObject { ["input"] = new JsonObject() } }, ct).ConfigureAwait(false);
                        break;
                    case "task-finished":
                        await CloseQuietlyAsync(ws).ConfigureAwait(false);
                        return Checked(audio.ToArray(), format switch { "wav" => "audio/wav", "pcm" => "audio/L16", "opus" => "audio/ogg", _ => "audio/mpeg" });
                    case "task-failed":
                        var code = header["error_code"]?.GetValue<string>() ?? "";
                        var detail = header["error_message"]?.GetValue<string>() ?? "task failed";
                        await CloseQuietlyAsync(ws).ConfigureAwait(false);
                        if (code.Contains("ApiKey", StringComparison.OrdinalIgnoreCase) || code.Contains("Auth", StringComparison.OrdinalIgnoreCase))
                            throw new CosyVoiceAuthException($"{code}: {detail}");
                        throw new ApiException(502, "UPSTREAM_ERROR", $"The upstream speech provider failed ({code}: {detail})");
                    default:
                        break; // result-generated and other progress events
                }
            }
        }
    }

    private static Task SendAsync(WebSocket ws, JsonObject message, CancellationToken ct) =>
        ws.SendAsync(Encoding.UTF8.GetBytes(message.ToJsonString()), WebSocketMessageType.Text, true, ct);

    private static async Task CloseQuietlyAsync(WebSocket ws)
    {
        try
        {
            using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(2));
            await ws.CloseOutputAsync(WebSocketCloseStatus.NormalClosure, "done", cts.Token).ConfigureAwait(false);
        }
        catch (Exception e) when (e is WebSocketException or OperationCanceledException or ObjectDisposedException)
        {
        }
    }

    /// <summary>Open a client WebSocket with the key as a bearer token (the production connector).</summary>
    public static async Task<WebSocket> ConnectAsync(Uri endpoint, string key, CancellationToken ct)
    {
        var ws = new ClientWebSocket();
        ws.Options.SetRequestHeader("Authorization", $"bearer {key}");
        try
        {
            await ws.ConnectAsync(endpoint, ct).ConfigureAwait(false);
            return ws;
        }
        catch
        {
            ws.Dispose();
            throw;
        }
    }

    private static SynthesizedSpeech Checked(byte[] bytes, string mime)
    {
        if (bytes.Length == 0)
            throw new ApiException(502, "UPSTREAM_ERROR", "The upstream speech provider returned empty audio");
        if (bytes.Length > MaxBytes)
            throw new ApiException(502, "UPSTREAM_ERROR", "The synthesized audio is too large");
        return new SynthesizedSpeech(bytes, mime);
    }

    private static string ErrorDetail(string raw)
    {
        try
        {
            return JsonNode.Parse(raw)?["code"]?.GetValue<string>() is { } code ? $", {code}" : "";
        }
        catch (System.Text.Json.JsonException)
        {
            return "";
        }
    }
}
