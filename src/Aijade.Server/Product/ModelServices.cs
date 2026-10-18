using System.Net.Http.Headers;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Server.Auth;
using Aijade.Server.Infrastructure;

using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Routing;

namespace Aijade.Server.Product;

// The gateway's other model services:
//   embeddings     OpenAI-compatible /embeddings: text → vectors, for semantic memory search (and any client that wants them)
//   transcription  OpenAI-compatible /audio/transcriptions: a recorded utterance → text, for devices without built-in speech
//                  recognition (the Android app's web view has none)
// Each is one route in the gateway document ("embeddings" / "transcription": upstream, model, keys, fluxPer1k), priced per
// thousand tokens (embeddings) or per minute of audio as reported by the client's duration hint (transcription, fluxPer1k
// applied per 1000 seconds).

public sealed class EmbeddingService(GatewayRoutes routes, KeyRotator keys, IHttpClientFactory factory, FluxLedger flux)
{
    public const int MaxInputs = 64;

    public async Task<bool> AvailableAsync(CancellationToken ct) => await routes.SectionAsync("embeddings", ct).ConfigureAwait(false) is not null;

    /// <summary>The upstream model of the embeddings route (stored with each vector), or null.</summary>
    public async Task<string?> ModelAsync(CancellationToken ct) => (await routes.SectionAsync("embeddings", ct).ConfigureAwait(false))?.Route.Model;

    /// <summary>Vectors for the inputs (in order), charged to <paramref name="userId"/>; null when no embeddings route is configured.</summary>
    public async Task<float[][]?> EmbedAsync(string userId, IReadOnlyList<string> inputs, CancellationToken ct)
    {
        if (await routes.SectionAsync("embeddings", ct).ConfigureAwait(false) is not { } configured)
            return null;
        var route = configured.Route;
        if (route.FluxPerThousand > 0 && await flux.BalanceAsync(userId, ct).ConfigureAwait(false) <= 0)
            throw new ApiException(402, "INSUFFICIENT_FLUX", "Insufficient flux");
        var result = new float[inputs.Count][];
        long tokens = 0;
        for (var start = 0; start < inputs.Count; start += MaxInputs)
        {
            var batch = inputs.Skip(start).Take(MaxInputs).ToList();
            var body = new JsonObject { ["model"] = route.Model, ["input"] = new JsonArray([.. batch.Select(i => (JsonNode)i)]) };
            using var res = await GatewayEndpoints.SendAsync(factory.CreateClient(GatewayEndpoints.HttpClientName), keys, route, "/embeddings",
                () => new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json"), ct).ConfigureAwait(false);
            if (!res.IsSuccessStatusCode)
                throw new ApiException(502, "UPSTREAM_ERROR", $"the embedding provider failed ({(int)res.StatusCode})");
            var json = JsonNode.Parse(await res.Content.ReadAsStringAsync(ct).ConfigureAwait(false));
            foreach (var item in json?["data"] as JsonArray ?? [])
            {
                var index = item!["index"]?.GetValue<int>() ?? 0;
                if (index >= 0 && index < batch.Count)
                    result[start + index] = [.. (item["embedding"] as JsonArray ?? []).Select(v => v!.GetValue<float>())];
            }
            tokens += json?["usage"]?["total_tokens"]?.GetValue<long>() ?? batch.Sum(b => (long)Math.Max(1, b.Length / 4));
        }
        if (result.Any(r => r is null))
            throw new ApiException(502, "UPSTREAM_ERROR", "the embedding provider returned fewer vectors than inputs");
        var cost = route.FluxPerThousand <= 0 ? 0 : Math.Max(1, (long)Math.Ceiling(tokens / 1000.0 * route.FluxPerThousand));
        if (cost > 0)
            await flux.ApplyAsync(userId, -cost, "usage", "embeddings", meta: new JsonObject { ["tokens"] = tokens }, ct: CancellationToken.None).ConfigureAwait(false);
        return result;
    }

    public static double Cosine(float[] a, float[] b)
    {
        if (a.Length != b.Length || a.Length == 0)
            return 0;
        double dot = 0, na = 0, nb = 0;
        for (var i = 0; i < a.Length; i++)
        {
            dot += a[i] * b[i];
            na += a[i] * a[i];
            nb += b[i] * b[i];
        }
        return na == 0 || nb == 0 ? 0 : dot / Math.Sqrt(na * nb);
    }
}

public static class ModelServices
{
    public const long MaxAudioBytes = 25 * 1024 * 1024;

    public static void Map(RouteGroupBuilder g)
    {
        g.MapPost("/embeddings", async (HttpContext c, EmbeddingService embeddings, CancellationToken ct) =>
        {
            var b = await V9.V9Endpoints.ReadJsonAsync(c.Request, "INVALID_REQUEST", ct).ConfigureAwait(false);
            List<string> inputs = b?["input"] switch
            {
                JsonValue v when v.TryGetValue<string>(out var one) => [one],
                JsonArray a => [.. a.Select(x => x?.GetValue<string>() ?? "")],
                _ => throw ApiException.BadRequest("input must be a string or an array of strings", "INVALID_REQUEST"),
            };
            if (inputs.Count is 0 or > 2048 || inputs.Any(i => i.Length is 0 or > 32_000))
                throw ApiException.BadRequest("1-2048 non-empty inputs of at most 32000 characters", "INVALID_REQUEST");
            var vectors = await embeddings.EmbedAsync(c.User.UserId(), inputs, ct).ConfigureAwait(false)
                ?? throw new ApiException(503, "GATEWAY_UNCONFIGURED", "embeddings are not configured");
            return Results.Json(new JsonObject
            {
                ["object"] = "list",
                ["data"] = new JsonArray([.. vectors.Select((v, i) => (JsonNode)new JsonObject { ["object"] = "embedding", ["index"] = i, ["embedding"] = new JsonArray([.. v.Select(x => (JsonNode)x)]) })]),
            });
        });

        g.MapPost("/audio/transcriptions", async (HttpContext c, GatewayRoutes routes, KeyRotator keys, IHttpClientFactory factory, FluxLedger flux, ProductEvents events,
            CancellationToken ct) =>
        {
            var userId = c.User.UserId();
            if (!c.Request.HasFormContentType)
                throw ApiException.BadRequest("multipart/form-data with a file is required", "INVALID_TRANSCRIPTION_REQUEST");
            var form = await c.Request.ReadFormAsync(ct).ConfigureAwait(false);
            var file = form.Files["file"] ?? throw ApiException.BadRequest("file is required", "INVALID_TRANSCRIPTION_REQUEST");
            if (file.Length is 0 or > MaxAudioBytes)
                throw ApiException.BadRequest("the audio must be 1 byte to 25 MB", "INVALID_TRANSCRIPTION_REQUEST");
            if (await routes.SectionAsync("transcription", ct).ConfigureAwait(false) is not { } configured)
                throw new ApiException(503, "GATEWAY_UNCONFIGURED", "speech recognition is not configured");
            var route = configured.Route;
            var seconds = double.TryParse(form["duration"], System.Globalization.CultureInfo.InvariantCulture, out var d) && d > 0 ? d : file.Length / 16_000.0;
            var cost = route.FluxPerThousand <= 0 ? 0 : Math.Max(1, (long)Math.Ceiling(seconds / 1000 * route.FluxPerThousand));
            if (cost > 0 && await flux.BalanceAsync(userId, ct).ConfigureAwait(false) < cost)
                throw new ApiException(402, "INSUFFICIENT_FLUX", "Insufficient flux");
            var audio = new byte[file.Length];
            await using (var s = file.OpenReadStream())
                await s.ReadExactlyAsync(audio, ct).ConfigureAwait(false);
            HttpContent Build()
            {
                var content = new MultipartFormDataContent();
                var part = new ByteArrayContent(audio);
                part.Headers.ContentType = MediaTypeHeaderValue.TryParse(file.ContentType, out var type) ? type : new MediaTypeHeaderValue("application/octet-stream");
                content.Add(part, "file", string.IsNullOrEmpty(file.FileName) ? "speech.webm" : Path.GetFileName(file.FileName));
                content.Add(new StringContent(route.Model), "model");
                if (form["language"].ToString() is { Length: > 0 } language)
                    content.Add(new StringContent(language), "language");
                return content;
            }
            await events.TrackAsync(userId, "asr", "transcription_requested", "started", "openai.audio.transcriptions", route.Model, ct: ct).ConfigureAwait(false);
            using var res = await GatewayEndpoints.SendAsync(factory.CreateClient(GatewayEndpoints.HttpClientName), keys, route, "/audio/transcriptions", Build, ct).ConfigureAwait(false);
            if (!res.IsSuccessStatusCode)
            {
                await events.TrackAsync(userId, "asr", "transcription_failed", "failed", "openai.audio.transcriptions", route.Model, reason: $"upstream_{(int)res.StatusCode}", ct: ct).ConfigureAwait(false);
                throw new ApiException(502, "UPSTREAM_ERROR", "the speech recognition provider failed");
            }
            var json = JsonNode.Parse(await res.Content.ReadAsStringAsync(ct).ConfigureAwait(false));
            if (cost > 0)
                await flux.ApplyAsync(userId, -cost, "usage", "transcription", meta: new JsonObject { ["seconds"] = seconds }, ct: CancellationToken.None).ConfigureAwait(false);
            return Results.Json(new JsonObject { ["text"] = json?["text"]?.GetValue<string>() ?? "" });
        }).DisableAntiforgery();
    }
}
