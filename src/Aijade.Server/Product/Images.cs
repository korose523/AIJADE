using System.Net.Http.Headers;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Server.Auth;
using Aijade.Server.Infrastructure;
using Aijade.Server.V9;

using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Routing;
using Microsoft.Extensions.Configuration;

using Npgsql;

namespace Aijade.Server.Product;

// Image generation ("artistry"): the companion can draw. The gateway's "images" section picks one backend:
//   openai    an OpenAI-compatible /images/generations endpoint (OpenAI, most proxies and self-hosted servers)
//   replicate Replicate's model predictions API (model = "owner/name"); waits for the prediction, then downloads the output
//   comfyui   a ComfyUI server: the section's "workflow" (API-format JSON) is queued with every "{{prompt}}" string replaced,
//             the history is polled, and the first output image is fetched from /view
//   gemini    Google AI Studio's native generateContent API (e.g. gemini-2.5-flash-image, "Nano Banana"): the key goes in
//             x-goog-api-key, the size is sent as an aspect ratio, and the image comes back inline as base64
// Results are stored per owner and served only to that owner; each image costs the section's "fluxPerImage".

public sealed record GeneratedImage(byte[] Bytes, string Mime);

public sealed class ImageGenerationException(string message, int status = 502, string code = "UPSTREAM_ERROR") : Exception(message)
{
    public int Status { get; } = status;

    public string Code { get; } = code;
}

public sealed class ImageBackends(IHttpClientFactory factory, KeyRotator keys, IConfiguration config)
{
    public static IReadOnlyList<string> Kinds { get; } = ["openai", "replicate", "comfyui", "gemini"];

    /// <summary>Largest image accepted from an upstream (and stored).</summary>
    public const int MaxBytes = 15 * 1024 * 1024;

    private TimeSpan PollInterval => TimeSpan.FromMilliseconds(int.TryParse(config["Aijade:ImagePollMs"], out var ms) && ms > 0 ? ms : 1000);

    private TimeSpan Deadline => TimeSpan.FromSeconds(int.TryParse(config["Aijade:ImageTimeoutSeconds"], out var s) && s > 0 ? s : 180);

    private HttpClient Http => factory.CreateClient(GatewayEndpoints.HttpClientName);

    public Task<GeneratedImage> GenerateAsync(GatewayRoute route, JsonObject section, string prompt, string? size, CancellationToken ct) =>
        (section["kind"]?.GetValue<string>() ?? "openai") switch
        {
            "openai" => OpenAiAsync(route, prompt, size, ct),
            "replicate" => ReplicateAsync(route, section, prompt, ct),
            "comfyui" => ComfyUiAsync(route, section, prompt, ct),
            "gemini" => GeminiAsync(route, section, prompt, size, ct),
            var other => throw new ImageGenerationException($"unknown image backend '{other}'", 503, "GATEWAY_UNCONFIGURED"),
        };

    /// <summary>Send with the route's keys in rotation (no key: one unauthenticated try, as local servers expect).</summary>
    private async Task<HttpResponseMessage> SendAsync(GatewayRoute route, Func<HttpRequestMessage> build, CancellationToken ct, Action<HttpRequestMessage, string>? authorize = null)
    {
        IReadOnlyList<string?> order = route.Keys.Count == 0 ? [null] : [.. keys.Order(route)];
        HttpResponseMessage? last = null;
        foreach (var key in order)
        {
            last?.Dispose();
            using var req = build();
            if (key is not null)
            {
                if (authorize is not null)
                    authorize(req, key);
                else
                    req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", key);
            }
            try
            {
                last = await Http.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false);
            }
            catch (HttpRequestException)
            {
                throw new ImageGenerationException("The image provider could not be reached", 502, "UPSTREAM_UNREACHABLE");
            }
            if (key is null || last.StatusCode is not (System.Net.HttpStatusCode.Unauthorized or System.Net.HttpStatusCode.Forbidden or System.Net.HttpStatusCode.TooManyRequests))
                return last;
            keys.Penalize(key);
        }
        return last!;
    }

    private static async Task<JsonNode> JsonOrFailAsync(HttpResponseMessage res, string what, CancellationToken ct)
    {
        using (res)
        {
            if (!res.IsSuccessStatusCode)
                throw new ImageGenerationException($"{what} failed upstream ({(int)res.StatusCode})");
            try
            {
                return JsonNode.Parse(await res.Content.ReadAsStringAsync(ct).ConfigureAwait(false)) ?? throw new ImageGenerationException($"{what}: empty response");
            }
            catch (System.Text.Json.JsonException)
            {
                throw new ImageGenerationException($"{what}: the provider did not return JSON");
            }
        }
    }

    private async Task<GeneratedImage> DownloadAsync(GatewayRoute route, string url, bool sendKey, CancellationToken ct)
    {
        using var res = sendKey
            ? await SendAsync(route, () => new HttpRequestMessage(HttpMethod.Get, url), ct).ConfigureAwait(false)
            : await GetAsync(url, ct).ConfigureAwait(false);
        if (!res.IsSuccessStatusCode)
            throw new ImageGenerationException($"downloading the image failed ({(int)res.StatusCode})");
        if (res.Content.Headers.ContentLength > MaxBytes)
            throw new ImageGenerationException("the generated image is too large");
        var bytes = await res.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false);
        if (bytes.Length > MaxBytes)
            throw new ImageGenerationException("the generated image is too large");
        return new GeneratedImage(bytes, Mime(res.Content.Headers.ContentType?.MediaType, bytes));
    }

    private async Task<HttpResponseMessage> GetAsync(string url, CancellationToken ct)
    {
        try
        {
            return await Http.GetAsync(url, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false);
        }
        catch (HttpRequestException)
        {
            throw new ImageGenerationException("The image could not be downloaded", 502, "UPSTREAM_UNREACHABLE");
        }
    }

    /// <summary>The declared type when it is an image, else sniffed from the magic bytes (PNG / JPEG / WebP / GIF).</summary>
    public static string Mime(string? declared, byte[] b)
    {
        if (declared is { } d && d.StartsWith("image/", StringComparison.Ordinal))
            return d;
        if (b.Length >= 8 && b[0] == 0x89 && b[1] == 0x50 && b[2] == 0x4E && b[3] == 0x47)
            return "image/png";
        if (b.Length >= 3 && b[0] == 0xFF && b[1] == 0xD8 && b[2] == 0xFF)
            return "image/jpeg";
        if (b.Length >= 12 && Encoding.ASCII.GetString(b, 0, 4) == "RIFF" && Encoding.ASCII.GetString(b, 8, 4) == "WEBP")
            return "image/webp";
        if (b.Length >= 6 && Encoding.ASCII.GetString(b, 0, 3) == "GIF")
            return "image/gif";
        throw new ImageGenerationException("the provider returned something that is not an image");
    }

    private async Task<GeneratedImage> OpenAiAsync(GatewayRoute route, string prompt, string? size, CancellationToken ct)
    {
        var body = new JsonObject { ["model"] = route.Model, ["prompt"] = prompt, ["n"] = 1, ["response_format"] = "b64_json" };
        if (size is not null)
            body["size"] = size;
        var json = await JsonOrFailAsync(await SendAsync(route, () => new HttpRequestMessage(HttpMethod.Post, $"{route.Upstream}/images/generations")
        {
            Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json"),
        }, ct).ConfigureAwait(false), "image generation", ct).ConfigureAwait(false);
        var first = json["data"]?[0];
        if (first?["b64_json"]?.GetValue<string>() is { Length: > 0 } b64)
        {
            byte[] bytes;
            try
            {
                bytes = Convert.FromBase64String(b64);
            }
            catch (FormatException)
            {
                throw new ImageGenerationException("image generation: invalid base64 image");
            }
            if (bytes.Length > MaxBytes)
                throw new ImageGenerationException("the generated image is too large");
            return new GeneratedImage(bytes, Mime(null, bytes));
        }
        if (first?["url"]?.GetValue<string>() is { Length: > 0 } url)
            return await DownloadAsync(route, url, sendKey: false, ct).ConfigureAwait(false);
        throw new ImageGenerationException("image generation: no image in the response");
    }

    /// <summary>Gemini sizes are aspect ratios; the OpenAI-style sizes the client sends map onto the nearest one.</summary>
    internal static string AspectRatio(string? size) => size switch
    {
        "1792x1024" or "1536x1024" => "16:9",
        "1024x1792" or "1024x1536" => "9:16",
        _ => "1:1",
    };

    private async Task<GeneratedImage> GeminiAsync(GatewayRoute route, JsonObject section, string prompt, string? size, CancellationToken ct)
    {
        var generation = new JsonObject
        {
            ["responseModalities"] = section["responseModalities"] is JsonArray modalities ? modalities.DeepClone() : new JsonArray("IMAGE"),
            ["imageConfig"] = new JsonObject { ["aspectRatio"] = size is null && section["aspectRatio"]?.GetValue<string>() is { } fixedRatio ? fixedRatio : AspectRatio(size) },
        };
        var body = new JsonObject
        {
            ["contents"] = new JsonArray(new JsonObject { ["parts"] = new JsonArray(new JsonObject { ["text"] = prompt }) }),
            ["generationConfig"] = generation,
        };
        var json = await JsonOrFailAsync(await SendAsync(route, () => new HttpRequestMessage(HttpMethod.Post, $"{route.Upstream}/models/{Uri.EscapeDataString(route.Model)}:generateContent")
        {
            Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json"),
        }, ct, (req, key) => req.Headers.TryAddWithoutValidation("x-goog-api-key", key)).ConfigureAwait(false), "image generation", ct).ConfigureAwait(false);
        var candidate = json["candidates"]?[0];
        foreach (var part in candidate?["content"]?["parts"] as JsonArray ?? [])
        {
            var inline = part?["inlineData"] ?? part?["inline_data"];
            if (inline?["data"]?.GetValue<string>() is not { Length: > 0 } b64)
                continue;
            byte[] bytes;
            try
            {
                bytes = Convert.FromBase64String(b64);
            }
            catch (FormatException)
            {
                throw new ImageGenerationException("image generation: invalid base64 image");
            }
            if (bytes.Length > MaxBytes)
                throw new ImageGenerationException("the generated image is too large");
            return new GeneratedImage(bytes, Mime((inline["mimeType"] ?? inline["mime_type"])?.GetValue<string>(), bytes));
        }
        // No image: say why when the provider does (a blocked prompt, a safety stop, or a text-only answer).
        var why = json["promptFeedback"]?["blockReason"]?.GetValue<string>() is { } blocked ? $"prompt blocked ({blocked})"
            : candidate?["finishReason"]?.GetValue<string>() is { } finish and not "STOP" ? $"stopped ({finish})"
            : "no image in the response";
        throw new ImageGenerationException($"image generation: {why}", 422, "UPSTREAM_REFUSED");
    }

    private async Task<GeneratedImage> ReplicateAsync(GatewayRoute route, JsonObject section, string prompt, CancellationToken ct)
    {
        var input = section["input"] is JsonObject extra ? (JsonObject)extra.DeepClone() : [];
        input["prompt"] = prompt;
        var prediction = await JsonOrFailAsync(await SendAsync(route, () =>
        {
            var req = new HttpRequestMessage(HttpMethod.Post, $"{route.Upstream}/models/{route.Model}/predictions")
            {
                Content = new StringContent(new JsonObject { ["input"] = input }.ToJsonString(), Encoding.UTF8, "application/json"),
            };
            req.Headers.TryAddWithoutValidation("Prefer", "wait");
            return req;
        }, ct).ConfigureAwait(false), "image generation", ct).ConfigureAwait(false);
        var until = DateTimeOffset.UtcNow + Deadline;
        while (prediction["status"]?.GetValue<string>() is "starting" or "processing")
        {
            if (DateTimeOffset.UtcNow > until)
                throw new ImageGenerationException("image generation timed out", 504, "UPSTREAM_TIMEOUT");
            await Task.Delay(PollInterval, ct).ConfigureAwait(false);
            var poll = prediction["urls"]?["get"]?.GetValue<string>() ?? throw new ImageGenerationException("image generation: no polling URL");
            prediction = await JsonOrFailAsync(await SendAsync(route, () => new HttpRequestMessage(HttpMethod.Get, poll), ct).ConfigureAwait(false), "image generation", ct)
                .ConfigureAwait(false);
        }
        if (prediction["status"]?.GetValue<string>() != "succeeded")
            throw new ImageGenerationException($"image generation {prediction["status"]?.GetValue<string>() ?? "failed"}: {prediction["error"]?.ToJsonString() ?? "no detail"}");
        var output = prediction["output"] is JsonArray a ? a.FirstOrDefault() : prediction["output"];
        var url = output?.GetValue<string>() ?? throw new ImageGenerationException("image generation: no output");
        return await DownloadAsync(route, url, sendKey: false, ct).ConfigureAwait(false);
    }

    /// <summary>A copy of the workflow with every string value "{{prompt}}" (whole or embedded) filled in.</summary>
    public static JsonNode FillWorkflow(JsonNode workflow, string prompt)
    {
        var copy = workflow.DeepClone();
        void Walk(JsonNode? n)
        {
            switch (n)
            {
                case JsonObject o:
                    foreach (var key in o.Select(kv => kv.Key).ToList())
                    {
                        if (o[key] is JsonValue v && v.TryGetValue<string>(out var s) && s.Contains("{{prompt}}", StringComparison.Ordinal))
                            o[key] = s.Replace("{{prompt}}", prompt, StringComparison.Ordinal);
                        else
                            Walk(o[key]);
                    }
                    break;
                case JsonArray arr:
                    for (var i = 0; i < arr.Count; i++)
                    {
                        if (arr[i] is JsonValue v && v.TryGetValue<string>(out var s) && s.Contains("{{prompt}}", StringComparison.Ordinal))
                            arr[i] = s.Replace("{{prompt}}", prompt, StringComparison.Ordinal);
                        else
                            Walk(arr[i]);
                    }
                    break;
            }
        }
        Walk(copy);
        return copy;
    }

    private async Task<GeneratedImage> ComfyUiAsync(GatewayRoute route, JsonObject section, string prompt, CancellationToken ct)
    {
        if (section["workflow"] is not JsonObject workflow)
            throw new ImageGenerationException("the ComfyUI route has no workflow", 503, "GATEWAY_UNCONFIGURED");
        var queued = await JsonOrFailAsync(await SendAsync(route, () => new HttpRequestMessage(HttpMethod.Post, $"{route.Upstream}/prompt")
        {
            Content = new StringContent(new JsonObject { ["prompt"] = FillWorkflow(workflow, prompt), ["client_id"] = "aijade" }.ToJsonString(), Encoding.UTF8, "application/json"),
        }, ct).ConfigureAwait(false), "image generation", ct).ConfigureAwait(false);
        var id = queued["prompt_id"]?.GetValue<string>() ?? throw new ImageGenerationException("ComfyUI did not accept the workflow");
        var until = DateTimeOffset.UtcNow + Deadline;
        while (true)
        {
            var history = await JsonOrFailAsync(await SendAsync(route, () => new HttpRequestMessage(HttpMethod.Get, $"{route.Upstream}/history/{Uri.EscapeDataString(id)}"), ct)
                .ConfigureAwait(false), "image generation", ct).ConfigureAwait(false);
            if (history[id] is JsonObject entry)
            {
                if (entry["status"]?["status_str"]?.GetValue<string>() == "error")
                    throw new ImageGenerationException("ComfyUI reported an error running the workflow");
                var image = (entry["outputs"] as JsonObject ?? []).Select(kv => kv.Value?["images"]?[0]).FirstOrDefault(i => i is not null);
                if (image is not null)
                {
                    var query = $"filename={Uri.EscapeDataString(image["filename"]!.GetValue<string>())}&subfolder={Uri.EscapeDataString(image["subfolder"]?.GetValue<string>() ?? "")}" +
                                $"&type={Uri.EscapeDataString(image["type"]?.GetValue<string>() ?? "output")}";
                    return await DownloadAsync(route, $"{route.Upstream}/view?{query}", sendKey: true, ct).ConfigureAwait(false);
                }
            }
            if (DateTimeOffset.UtcNow > until)
                throw new ImageGenerationException("image generation timed out", 504, "UPSTREAM_TIMEOUT");
            await Task.Delay(PollInterval, ct).ConfigureAwait(false);
        }
    }
}

public static class ImageEndpoints
{
    public const int MaxPromptLength = 2000;

    /// <summary>Reject an "images" section the backends could not use (called by the admin route editor).</summary>
    public static void Validate(JsonObject doc)
    {
        if (doc["images"] is not JsonObject images)
            return;
        var kind = images["kind"]?.GetValue<string>() ?? "openai";
        if (!ImageBackends.Kinds.Contains(kind))
            throw ApiException.BadRequest($"images.kind must be one of {string.Join(", ", ImageBackends.Kinds)}", "INVALID_REQUEST");
        if (images["upstream"] is not JsonValue u || !Uri.TryCreate(u.GetValue<string>(), UriKind.Absolute, out _))
            throw ApiException.BadRequest("images.upstream must be an absolute URL", "INVALID_REQUEST");
        if (kind == "comfyui" && images["workflow"] is not JsonObject)
            throw ApiException.BadRequest("images.workflow (ComfyUI API-format JSON) is required for comfyui", "INVALID_REQUEST");
    }

    public static void Map(IEndpointRouteBuilder app)
    {
        // What this server can do beyond chat, so clients only offer features that will work.
        app.MapGet("/api/v1/capabilities", async (GatewayRoutes routes, CancellationToken ct) =>
        {
            var doc = await routes.LoadAsync(ct).ConfigureAwait(false);
            return Results.Json(new JsonObject
            {
                ["chatModels"] = new JsonArray([.. (doc?["models"] as JsonObject ?? []).Select(kv => (JsonNode)kv.Key)]),
                ["speech"] = doc?["speech"] is JsonObject,
                ["images"] = doc?["images"] is JsonObject,
            });
        }).RequireAuthorization();

        var g = app.MapGroup("/api/v1/images").RequireAuthorization();
        g.MapPost("", async (HttpContext c, GatewayRoutes routes, ImageBackends backends, FluxLedger flux, ProductEvents events, NpgsqlDataSource db, CancellationToken ct) =>
        {
            var userId = c.User.UserId();
            var body = await V9Endpoints.ReadJsonAsync(c.Request, "INVALID_IMAGE_REQUEST", ct).ConfigureAwait(false);
            var prompt = body?["prompt"]?.GetValue<string>()?.Trim();
            if (string.IsNullOrEmpty(prompt) || prompt.Length > MaxPromptLength)
                throw ApiException.BadRequest($"prompt is required (at most {MaxPromptLength} characters)", "INVALID_IMAGE_REQUEST");
            var size = body?["size"]?.GetValue<string>();
            if (size is not null && !System.Text.RegularExpressions.Regex.IsMatch(size, @"^\d{2,4}x\d{2,4}$"))
                throw ApiException.BadRequest("size must look like 1024x1024", "INVALID_IMAGE_REQUEST");
            var (route, section) = await routes.ImagesRouteAsync(ct).ConfigureAwait(false) ?? throw new ApiException(503, "GATEWAY_UNCONFIGURED", "image generation is not configured");
            var cost = section["fluxPerImage"] is JsonValue p && p.TryGetValue<long>(out var price) && price > 0 ? price : 0;
            if (cost > 0 && await flux.BalanceAsync(userId, ct).ConfigureAwait(false) < cost)
                throw new ApiException(402, "INSUFFICIENT_FLUX", "Insufficient flux");
            var kind = section["kind"]?.GetValue<string>() ?? "openai";
            await events.TrackAsync(userId, "artistry", "image_requested", "started", kind, route.Model, ct: ct).ConfigureAwait(false);
            GeneratedImage image;
            try
            {
                image = await backends.GenerateAsync(route, section, prompt, size, ct).ConfigureAwait(false);
            }
            catch (ImageGenerationException e)
            {
                await events.TrackAsync(userId, "artistry", "image_failed", "failed", kind, route.Model, reason: e.Code, ct: CancellationToken.None).ConfigureAwait(false);
                throw new ApiException(e.Status, e.Code, e.Message);
            }
            var id = Ids.New();
            await using (var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false))
            {
                await Sql.ExecAsync(conn, null, "INSERT INTO generated_images (id, owner_id, prompt, mime, bytes, provider, model) VALUES ($1,$2,$3,$4,$5,$6,$7)", ct,
                    Sql.Text(id), Sql.Text(userId), Sql.Text(prompt), Sql.Text(image.Mime), Sql.P(image.Bytes), Sql.Text(kind), Sql.Text(route.Model)).ConfigureAwait(false);
            }
            if (cost > 0)
                await flux.ApplyAsync(userId, -cost, "usage", "image", meta: new JsonObject { ["imageId"] = id }, ct: CancellationToken.None).ConfigureAwait(false);
            await events.TrackAsync(userId, "artistry", "image_succeeded", "succeeded", kind, route.Model, ct: CancellationToken.None).ConfigureAwait(false);
            return Results.Json(new JsonObject { ["id"] = id, ["url"] = $"/api/v1/images/{id}", ["mime"] = image.Mime, ["prompt"] = prompt, ["fluxCharged"] = cost }, statusCode: 201);
        });
        g.MapGet("", async (HttpContext c, NpgsqlDataSource db, CancellationToken ct) =>
        {
            await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
            var rows = await Sql.QueryAsync(conn, null,
                "SELECT id, prompt, mime, created_at FROM generated_images WHERE owner_id = $1 ORDER BY created_at DESC LIMIT 200",
                r => (JsonNode)new JsonObject
                {
                    ["id"] = r.GetString(0), ["prompt"] = r.GetString(1), ["mime"] = r.GetString(2), ["url"] = $"/api/v1/images/{r.GetString(0)}",
                    ["createdAt"] = new DateTimeOffset(DateTime.SpecifyKind(r.GetDateTime(3), DateTimeKind.Utc)),
                }, ct, Sql.Text(c.User.UserId())).ConfigureAwait(false);
            return Results.Json(new JsonObject { ["images"] = new JsonArray([.. rows]) });
        });
        g.MapGet("/{id}", async (string id, HttpContext c, NpgsqlDataSource db, CancellationToken ct) =>
        {
            await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
            var rows = await Sql.QueryAsync(conn, null, "SELECT mime, bytes FROM generated_images WHERE id = $1 AND owner_id = $2",
                r => (Mime: r.GetString(0), Bytes: (byte[])r.GetValue(1)), ct, Sql.Text(id), Sql.Text(c.User.UserId())).ConfigureAwait(false);
            if (rows.Count == 0)
                throw ApiException.NotFound("image not found");
            c.Response.Headers.CacheControl = "private, max-age=31536000, immutable";
            return Results.Bytes(rows[0].Bytes, rows[0].Mime);
        });
        g.MapDelete("/{id}", async (string id, HttpContext c, NpgsqlDataSource db, CancellationToken ct) =>
        {
            await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
            if (await Sql.ExecAsync(conn, null, "DELETE FROM generated_images WHERE id = $1 AND owner_id = $2", ct, Sql.Text(id), Sql.Text(c.User.UserId())).ConfigureAwait(false) == 0)
                throw ApiException.NotFound("image not found");
            return Results.NoContent();
        });
    }
}
