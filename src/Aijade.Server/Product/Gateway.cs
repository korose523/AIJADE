using System.Collections.Concurrent;
using System.Diagnostics;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Server.Auth;
using Aijade.Server.Infrastructure;
using Aijade.Server.V9;

using Microsoft.AspNetCore.DataProtection;

using Npgsql;

namespace Aijade.Server.Product;

// An OpenAI-compatible gateway, designed for this server. Clients call a model alias; the server holds the route (upstream
// base URL, upstream model, a pool of upstream keys, a flux price) in config_kv["gateway.routes"]. Keys are encrypted at
// rest and rotated round-robin; a key answered with 401/403/429 cools down and the next one is tried. Streaming responses
// are relayed chunk by chunk. Every request is metered in flux (by reported token usage, else estimated), logged, and
// tracked as a product event; a user without flux is refused before anything is sent upstream.

public sealed record GatewayRoute(string Alias, string Upstream, string Model, IReadOnlyList<string> Keys, double FluxPerThousand);

public sealed class GatewayRoutes(NpgsqlDataSource db, IDataProtectionProvider dp)
{
    public const string ConfigKey = "gateway.routes";

    /// <summary>Sections holding one route each (beside the per-alias "models"); their keys are encrypted and masked alike.</summary>
    public static IReadOnlyList<string> SingleRouteSections { get; } = ["speech", "images", "embeddings", "transcription"];
    private const string Purpose = "Aijade.GatewayKey.v1";

    private IDataProtector Protector => dp.CreateProtector(Purpose);

    /// <summary>The stored document with keys decrypted; null when unconfigured.</summary>
    public async Task<JsonObject?> LoadAsync(CancellationToken ct)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        var rows = await Sql.QueryAsync(conn, null, "SELECT value::text FROM config_kv WHERE key = $1", r => r.GetString(0), ct, Sql.Text(ConfigKey)).ConfigureAwait(false);
        return rows.Count == 0 ? null : JsonNode.Parse(rows[0]) as JsonObject;
    }

    private GatewayRoute? Route(JsonObject? doc, string section, string alias)
    {
        var node = section == "models" ? doc?["models"]?[alias] : doc?[section];
        if (node is not JsonObject o)
            return null;
        var keys = (o["keys"] as JsonArray ?? []).Select(k => Protector.Unprotect(k!.GetValue<string>())).ToList();
        return new GatewayRoute(alias, o["upstream"]!.GetValue<string>().TrimEnd('/'), o["model"]?.GetValue<string>() ?? alias, keys,
            o["fluxPer1k"] is JsonValue f && f.TryGetValue<double>(out var price) ? price : 0);
    }

    public async Task<GatewayRoute?> ChatRouteAsync(string alias, CancellationToken ct) => Route(await LoadAsync(ct).ConfigureAwait(false), "models", alias);

    /// <summary>The image route with its keys decrypted, plus the whole section for backend-specific settings.</summary>
    public async Task<(GatewayRoute Route, JsonObject Section)?> ImagesRouteAsync(CancellationToken ct)
    {
        var doc = await LoadAsync(ct).ConfigureAwait(false);
        if (doc?["images"] is not JsonObject section || Route(doc, "images", "images") is not { } route)
            return null;
        return (route, section);
    }

    /// <summary>A single-route section ("speech", "embeddings", "transcription") with its keys decrypted, plus the raw section.</summary>
    public async Task<(GatewayRoute Route, JsonObject Section)?> SectionAsync(string name, CancellationToken ct)
    {
        var doc = await LoadAsync(ct).ConfigureAwait(false);
        return doc?[name] is JsonObject section && Route(doc, name, name) is { } route ? (route, section) : null;
    }

    public async Task<GatewayRoute?> SpeechRouteAsync(CancellationToken ct) => Route(await LoadAsync(ct).ConfigureAwait(false), "speech", "speech");

    public async Task<IReadOnlyList<string>> AliasesAsync(CancellationToken ct) =>
        (await LoadAsync(ct).ConfigureAwait(false))?["models"] is JsonObject m ? m.Select(kv => kv.Key).ToList() : [];

    /// <summary>
    /// Admin edits start from the masked document, so a key given in its masked form ("…" + last four characters) means
    /// "keep the stored key of this route that ends that way". Any other string is a new plaintext key. A masked key that
    /// matches nothing stored for that route is rejected rather than saved as a broken key.
    /// </summary>
    public async Task<JsonObject> ResolveMaskedKeysAsync(JsonObject doc, CancellationToken ct)
    {
        var existing = await LoadAsync(ct).ConfigureAwait(false);
        var resolved = (JsonObject)doc.DeepClone();
        void Resolve(JsonNode? route, JsonNode? before, string where)
        {
            if (route is not JsonObject r || r["keys"] is not JsonArray keys)
                return;
            var stored = (before?["keys"] as JsonArray ?? []).Select(k => Protector.Unprotect(k!.GetValue<string>())).ToList();
            r["keys"] = new JsonArray([.. keys.Select(k =>
            {
                var value = k!.GetValue<string>();
                if (!value.StartsWith('…'))
                    return (JsonNode)value;
                var suffix = value[1..];
                var match = stored.Where(p => (p.Length > 4 ? p[^4..] : "") == suffix).ToList();
                return match.Count == 1
                    ? (JsonNode)match[0]
                    : throw ApiException.BadRequest($"{where}: masked key '{value}' does not identify one stored key; enter the full key", "INVALID_REQUEST");
            })]);
        }
        foreach (var (alias, route) in resolved["models"] as JsonObject ?? [])
            Resolve(route, existing?["models"]?[alias], $"models.{alias}");
        foreach (var section in SingleRouteSections)
            Resolve(resolved[section], existing?[section], section);
        return resolved;
    }

    /// <summary>Save a document whose keys are plaintext; they are encrypted before storage.</summary>
    public async Task SaveAsync(JsonObject doc, CancellationToken ct)
    {
        var stored = (JsonObject)doc.DeepClone();
        void Protect(JsonNode? route)
        {
            if (route is JsonObject r && r["keys"] is JsonArray keys)
                r["keys"] = new JsonArray([.. keys.Select(k => (JsonNode)Protector.Protect(k!.GetValue<string>()))]);
        }
        foreach (var (_, route) in stored["models"] as JsonObject ?? [])
            Protect(route);
        foreach (var section in SingleRouteSections)
            Protect(stored[section]);
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        await Sql.ExecAsync(conn, null, "INSERT INTO config_kv (key, value) VALUES ($1,$2) ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()", ct,
            Sql.Text(ConfigKey), Sql.Jsonb(stored)).ConfigureAwait(false);
    }

    /// <summary>The stored document for administrators: keys masked to their last four characters.</summary>
    public async Task<JsonObject> MaskedAsync(CancellationToken ct)
    {
        var doc = await LoadAsync(ct).ConfigureAwait(false) ?? [];
        void Mask(JsonNode? route)
        {
            if (route is JsonObject r && r["keys"] is JsonArray keys)
            {
                r["keys"] = new JsonArray([.. keys.Select(k =>
                {
                    var plain = Protector.Unprotect(k!.GetValue<string>());
                    return (JsonNode)$"…{(plain.Length > 4 ? plain[^4..] : "")}";
                })]);
            }
        }
        foreach (var (_, route) in doc["models"] as JsonObject ?? [])
            Mask(route);
        foreach (var section in SingleRouteSections)
            Mask(doc[section]);
        return doc;
    }
}

/// <summary>Round-robin over a route's keys, skipping keys in cool-down after an auth or rate-limit refusal.</summary>
public sealed class KeyRotator(TimeProvider time)
{
    private readonly ConcurrentDictionary<string, int> cursor = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, DateTimeOffset> cooling = new(StringComparer.Ordinal);

    public static TimeSpan Cooldown { get; } = TimeSpan.FromSeconds(60);

    /// <summary>The keys in the order to try: available ones round-robin first, cooling ones last.</summary>
    public IReadOnlyList<string> Order(GatewayRoute route)
    {
        if (route.Keys.Count == 0)
            return [];
        var start = cursor.AddOrUpdate(route.Alias, 0, (_, v) => (v + 1) % route.Keys.Count) % route.Keys.Count;
        var rotated = route.Keys.Skip(start).Concat(route.Keys.Take(start)).ToList();
        var now = time.GetUtcNow();
        return [.. rotated.Where(k => !cooling.TryGetValue(k, out var until) || until <= now), .. rotated.Where(k => cooling.TryGetValue(k, out var until) && until > now)];
    }

    public void Penalize(string key) => cooling[key] = time.GetUtcNow() + Cooldown;
}

public static class GatewayEndpoints
{
    public const string HttpClientName = "gateway";

    private static long Charge(double tokensOrChars, double pricePerThousand) =>
        pricePerThousand <= 0 || tokensOrChars <= 0 ? 0 : Math.Max(1, (long)Math.Ceiling(tokensOrChars / 1000 * pricePerThousand));

    private static async Task LogAsync(NpgsqlDataSource db, string userId, string model, string upstream, int status, int? prompt, int? completion, long flux, long ms, bool stream, string? error,
        CancellationToken ct)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        await Sql.ExecAsync(conn, null,
            "INSERT INTO llm_request_logs (id, user_id, model, upstream, status, prompt_tokens, completion_tokens, flux_charged, duration_ms, stream, error) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)",
            ct, Sql.Text(Ids.New()), Sql.Text(userId), Sql.Text(model), Sql.Text(new Uri(upstream).Host), Sql.P(status), Sql.P(prompt), Sql.P(completion), Sql.P(flux), Sql.P((int)ms),
            Sql.P(stream), Sql.Text(error)).ConfigureAwait(false);
    }

    /// <summary>Send with key rotation; returns the first response that is not an auth / rate-limit refusal (or the last one).</summary>
    internal static async Task<HttpResponseMessage> SendAsync(HttpClient http, KeyRotator keys, GatewayRoute route, string path, Func<HttpContent> content, CancellationToken ct,
        Action<HttpRequestMessage, string>? authorize = null)
    {
        var order = keys.Order(route);
        if (order.Count == 0)
            throw new ApiException(503, "GATEWAY_UNCONFIGURED", $"no upstream key configured for '{route.Alias}'");
        HttpResponseMessage? last = null;
        foreach (var key in order)
        {
            last?.Dispose();
            using var req = new HttpRequestMessage(HttpMethod.Post, $"{route.Upstream}{path}") { Content = content() };
            if (authorize is null)
                req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", key);
            else
                authorize(req, key);
            try
            {
                last = await http.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false);
            }
            catch (HttpRequestException)
            {
                throw new ApiException(502, "UPSTREAM_UNREACHABLE", "The upstream model provider could not be reached");
            }
            if (last.StatusCode is not (System.Net.HttpStatusCode.Unauthorized or System.Net.HttpStatusCode.Forbidden or System.Net.HttpStatusCode.TooManyRequests))
                return last;
            keys.Penalize(key);
        }
        return last!;
    }

    public static void Map(IEndpointRouteBuilder app)
    {
        var g = app.MapGroup("/api/v1/openai/v1").RequireAuthorization();
        g.MapGet("/models", async (GatewayRoutes routes, CancellationToken ct) => Results.Json(new JsonObject
        {
            ["object"] = "list",
            ["data"] = new JsonArray([.. (await routes.AliasesAsync(ct).ConfigureAwait(false)).Select(a => (JsonNode)new JsonObject { ["id"] = a, ["object"] = "model", ["owned_by"] = "aijade" })]),
        }));
        g.MapPost("/chat/completions", ChatCompletionsAsync);
        g.MapPost("/audio/speech", SpeechAsync);
        ModelServices.Map(g);
    }

    private static async Task ChatCompletionsAsync(HttpContext c, GatewayRoutes routes, KeyRotator keys, IHttpClientFactory factory, FluxLedger flux, ProductEvents events,
        NpgsqlDataSource db, CancellationToken ct)
    {
        var userId = c.User.UserId();
        var body = await V9Endpoints.ReadJsonAsync(c.Request, "INVALID_COMPLETION_REQUEST", ct).ConfigureAwait(false) as JsonObject
            ?? throw ApiException.BadRequest("JSON object body required", "INVALID_COMPLETION_REQUEST");
        var alias = body["model"]?.GetValue<string>() ?? throw ApiException.BadRequest("model is required", "INVALID_COMPLETION_REQUEST");
        if (body["messages"] is not JsonArray { Count: > 0 })
            throw ApiException.BadRequest("messages must be a non-empty array", "INVALID_COMPLETION_REQUEST");
        var route = await routes.ChatRouteAsync(alias, ct).ConfigureAwait(false) ?? throw new ApiException(404, "MODEL_NOT_FOUND", $"unknown model '{alias}'");
        if (route.FluxPerThousand > 0 && await flux.BalanceAsync(userId, ct).ConfigureAwait(false) <= 0)
            throw new ApiException(402, "INSUFFICIENT_FLUX", "Insufficient flux");
        var stream = body["stream"] is JsonValue sv && sv.TryGetValue<bool>(out var s) && s;
        body["model"] = route.Model;
        if (stream)
            body["stream_options"] = new JsonObject { ["include_usage"] = true };
        await events.TrackAsync(userId, "gen_ai_chat", "completion_requested", "started", "openai.chat.completions", alias, ct: ct).ConfigureAwait(false);

        var sw = Stopwatch.StartNew();
        var http = factory.CreateClient(HttpClientName);
        using var res = await SendAsync(http, keys, route, "/chat/completions", () => new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json"), ct).ConfigureAwait(false);
        if (!res.IsSuccessStatusCode)
        {
            var detail = await res.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
            await LogAsync(db, userId, alias, route.Upstream, (int)res.StatusCode, null, null, 0, sw.ElapsedMilliseconds, stream, detail.Length > 500 ? detail[..500] : detail, ct).ConfigureAwait(false);
            await events.TrackAsync(userId, "gen_ai_chat", "completion_failed", "failed", "openai.chat.completions", alias, reason: $"upstream_{(int)res.StatusCode}", ct: ct).ConfigureAwait(false);
            throw (int)res.StatusCode >= 500
                ? new ApiException(502, "UPSTREAM_ERROR", "The upstream model provider failed")
                : new ApiException((int)res.StatusCode, "UPSTREAM_REJECTED", "The upstream model provider rejected the request");
        }

        int? prompt = null, completion = null;
        var chars = 0;
        if (!stream)
        {
            var json = JsonNode.Parse(await res.Content.ReadAsStringAsync(ct).ConfigureAwait(false))!.AsObject();
            prompt = json["usage"]?["prompt_tokens"]?.GetValue<int>();
            completion = json["usage"]?["completion_tokens"]?.GetValue<int>();
            chars = json.ToJsonString().Length;
            json["model"] = alias;
            await SettleAsync().ConfigureAwait(false);
            c.Response.StatusCode = 200;
            await c.Response.WriteAsJsonAsync(json, ct).ConfigureAwait(false);
            return;
        }

        c.Response.StatusCode = 200;
        c.Response.ContentType = "text/event-stream";
        c.Response.Headers.CacheControl = "no-cache";
        await using (var upstream = await res.Content.ReadAsStreamAsync(ct).ConfigureAwait(false))
        using (var reader = new StreamReader(upstream, Encoding.UTF8))
        {
            while (await reader.ReadLineAsync(ct).ConfigureAwait(false) is { } line)
            {
                if (line.StartsWith("data: ", StringComparison.Ordinal) && line != "data: [DONE]")
                {
                    try
                    {
                        if (JsonNode.Parse(line[6..]) is JsonObject chunk)
                        {
                            if (chunk["usage"] is JsonObject u)
                            {
                                prompt = u["prompt_tokens"]?.GetValue<int>();
                                completion = u["completion_tokens"]?.GetValue<int>();
                            }
                            if (chunk["choices"] is JsonArray { Count: > 0 } choices)
                                chars += choices[0]?["delta"]?["content"]?.GetValue<string>()?.Length ?? 0;
                            chunk["model"] = alias;
                            line = "data: " + chunk.ToJsonString();
                        }
                    }
                    catch (JsonException)
                    {
                    }
                }
                await c.Response.WriteAsync(line + "\n", ct).ConfigureAwait(false);
                if (line.Length == 0)
                    await c.Response.Body.FlushAsync(ct).ConfigureAwait(false);
            }
        }
        await SettleAsync().ConfigureAwait(false);

        async Task SettleAsync()
        {
            // Reported usage when present; otherwise an estimate of ~4 characters per token, so no completion is free by omission.
            var tokens = prompt is not null || completion is not null ? (prompt ?? 0) + (completion ?? 0) : Math.Ceiling(chars / 4.0);
            var cost = Charge(tokens, route.FluxPerThousand);
            if (cost > 0)
            {
                try
                {
                    await flux.ApplyAsync(userId, -cost, "usage", $"chat:{alias}", meta: new JsonObject { ["tokens"] = tokens }, ct: CancellationToken.None).ConfigureAwait(false);
                }
                catch (ApiException)
                {
                    // The balance ran out mid-request: the answer was delivered; the ledger records what could be charged.
                    var left = await flux.BalanceAsync(userId, CancellationToken.None).ConfigureAwait(false);
                    if (left > 0)
                        await flux.ApplyAsync(userId, -left, "usage", $"chat:{alias} (partial)", ct: CancellationToken.None).ConfigureAwait(false);
                    cost = left;
                }
            }
            await LogAsync(db, userId, alias, route.Upstream, 200, prompt, completion, cost, sw.ElapsedMilliseconds, stream, null, CancellationToken.None).ConfigureAwait(false);
            await events.TrackAsync(userId, "gen_ai_chat", "completion_succeeded", "succeeded", "openai.chat.completions", alias, ct: CancellationToken.None).ConfigureAwait(false);
        }
    }

    private static async Task SpeechAsync(HttpContext c, GatewayRoutes routes, KeyRotator keys, IHttpClientFactory factory, FluxLedger flux, ProductEvents events,
        IConfiguration config, CancellationToken ct)
    {
        var userId = c.User.UserId();
        var body = await V9Endpoints.ReadJsonAsync(c.Request, "INVALID_SPEECH_REQUEST", ct).ConfigureAwait(false) as JsonObject
            ?? throw ApiException.BadRequest("JSON object body required", "INVALID_SPEECH_REQUEST");
        var input = body["input"]?.GetValue<string>();
        if (string.IsNullOrWhiteSpace(input))
            throw ApiException.BadRequest("input is required", "INVALID_SPEECH_REQUEST");
        var route = await routes.SpeechRouteAsync(ct).ConfigureAwait(false) ?? throw new ApiException(503, "GATEWAY_UNCONFIGURED", "speech is not configured");
        var cost = Charge(input.Length, route.FluxPerThousand);
        if (cost > 0 && await flux.BalanceAsync(userId, ct).ConfigureAwait(false) < cost)
            throw new ApiException(402, "INSUFFICIENT_FLUX", "Insufficient flux");
        body["model"] ??= route.Model;
        var section = (await routes.SectionAsync("speech", ct).ConfigureAwait(false))?.Section;
        var kind = section?["kind"]?.GetValue<string>() ?? "openai";
        var elevenLabs = kind == "elevenlabs";
        var operation = kind switch { "elevenlabs" => "elevenlabs.tts", AliyunSpeech.QwenTts => "dashscope.qwen_tts", AliyunSpeech.CosyVoice => "dashscope.cosyvoice", _ => "openai.audio.speech" };
        await events.TrackAsync(userId, "tts", "speech_requested", "started", operation, route.Model, ct: ct).ConfigureAwait(false);
        // ElevenLabs: POST /v1/text-to-speech/{voice id} with the key in xi-api-key. Voice names are provider-specific: clients
        // send an OpenAI-style name by default, so for any other provider the route's configured voice takes precedence.
        var requested = body["voice"]?.GetValue<string>() is { Length: > 0 } v ? v : null;
        var configured = section?["voice"]?.GetValue<string>() is { Length: > 0 } cv ? cv : null;
        var voice = (kind == "openai" ? requested ?? configured : configured ?? requested) ?? "";
        if (kind is AliyunSpeech.QwenTts or AliyunSpeech.CosyVoice)
        {
            SynthesizedSpeech speech;
            try
            {
                speech = kind == AliyunSpeech.QwenTts
                    ? await AliyunSpeech.QwenTtsAsync(factory.CreateClient(HttpClientName), keys, route, input, voice, ct).ConfigureAwait(false)
                    : await AliyunSpeech.CosyVoiceAsync(keys, route, section!, input, voice,
                        TimeSpan.FromSeconds(int.TryParse(config["Aijade:SpeechTimeoutSeconds"], out var secs) && secs > 0 ? secs : 60), AliyunSpeech.ConnectAsync, ct).ConfigureAwait(false);
            }
            catch (ApiException e)
            {
                await events.TrackAsync(userId, "tts", "speech_failed", "failed", operation, route.Model, reason: e.Code, ct: ct).ConfigureAwait(false);
                throw;
            }
            if (cost > 0)
                await flux.ApplyAsync(userId, -cost, "usage", "speech", meta: new JsonObject { ["characters"] = input.Length }, ct: ct).ConfigureAwait(false);
            c.Response.StatusCode = 200;
            c.Response.ContentType = speech.Mime;
            await c.Response.Body.WriteAsync(speech.Audio, ct).ConfigureAwait(false);
            await events.TrackAsync(userId, "tts", "speech_succeeded", "succeeded", operation, route.Model, ct: CancellationToken.None).ConfigureAwait(false);
            return;
        }
        using var res = elevenLabs
            ? await SendAsync(factory.CreateClient(HttpClientName), keys, route, $"/v1/text-to-speech/{Uri.EscapeDataString(voice)}",
                () => new StringContent(new JsonObject { ["text"] = input, ["model_id"] = route.Model }.ToJsonString(), Encoding.UTF8, "application/json"), ct,
                (req, key) => req.Headers.Add("xi-api-key", key)).ConfigureAwait(false)
            : await SendAsync(factory.CreateClient(HttpClientName), keys, route, "/audio/speech",
                () => new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json"), ct).ConfigureAwait(false);
        if (!res.IsSuccessStatusCode)
        {
            await events.TrackAsync(userId, "tts", "speech_failed", "failed", "openai.audio.speech", route.Model, reason: $"upstream_{(int)res.StatusCode}", ct: ct).ConfigureAwait(false);
            throw new ApiException(502, "UPSTREAM_ERROR", "The upstream speech provider failed");
        }
        if (cost > 0)
            await flux.ApplyAsync(userId, -cost, "usage", "speech", meta: new JsonObject { ["characters"] = input.Length }, ct: ct).ConfigureAwait(false);
        c.Response.StatusCode = 200;
        c.Response.ContentType = res.Content.Headers.ContentType?.ToString() ?? "audio/mpeg";
        await res.Content.CopyToAsync(c.Response.Body, ct).ConfigureAwait(false);
        await events.TrackAsync(userId, "tts", "speech_succeeded", "succeeded", "openai.audio.speech", route.Model, ct: CancellationToken.None).ConfigureAwait(false);
    }
}
