using System.Net;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Server.Infrastructure;
using Aijade.Server.V9;

namespace Aijade.Server.Product;

/// <summary>Editable local service settings, health checks, and AIJADE's optional /sing → WAV adapter.</summary>
public static class CompanionLocalServices
{
    public const int MaxAudioBytes = 8 * 1024 * 1024;
    private static ApiException BadRequest(string message) => ApiException.BadRequest(message, "INVALID_LOCAL_SERVICE");
    public static IReadOnlyList<string> Sections { get; } = ["speech", "transcription", "alignment", "singing"];
    private static readonly string[] Editable = ["enabled", "upstream", "model", "voice", "modelPath", "datasetPath", "permissionNote", "healthPath"];

    public static void ValidateSections(JsonObject document)
    {
        foreach (var key in Sections)
        {
            if (document[key] is not JsonObject section || section["kind"]?.GetValue<string>() != LocalVoice.Kind)
                continue;
            if (section["enabled"] is { } flag && (flag is not JsonValue value || !value.TryGetValue<bool>(out _)))
                throw BadRequest($"{key}.enabled must be true or false");
            foreach (var field in Editable.Where(f => f != "enabled"))
                if (section[field] is { } node && (node is not JsonValue v || !v.TryGetValue<string>(out var text) || text.Length > 4096))
                    throw BadRequest($"{key}.{field} must be a short text value");
            var enabled = section["enabled"]?.GetValue<bool>() ?? true;
            var upstream = section["upstream"]?.GetValue<string>() ?? "";
            if ((enabled || upstream.Length > 0) && !ValidAddress(upstream))
                throw BadRequest($"{key}: use an http(s) service address without credentials, query or fragment");
            if (section["healthPath"]?.GetValue<string>() is { Length: > 0 } path && !ValidHealthPath(path))
                throw BadRequest($"{key}: health path must start with one slash and stay on this service");
        }
    }

    private static bool ValidAddress(string value) => Uri.TryCreate(value, UriKind.Absolute, out var uri) && uri.Scheme is "http" or "https" &&
        uri.UserInfo.Length == 0 && uri.Query.Length == 0 && uri.Fragment.Length == 0;
    private static bool ValidHealthPath(string value) => value.StartsWith('/') && !value.StartsWith("//", StringComparison.Ordinal) &&
        !value.Contains('\\', StringComparison.Ordinal) && !value.Contains('#', StringComparison.Ordinal) && !value.Contains("..", StringComparison.Ordinal) && !value.Contains('%', StringComparison.Ordinal);

    public static void Map(IEndpointRouteBuilder app)
    {
        app.MapPut("/api/v1/admin/gateway/local-services", SaveAsync).RequireAuthorization(AdminEndpoints.Policy);
        app.MapPost("/api/v1/admin/gateway/local-services/check", CheckAsync).RequireAuthorization(AdminEndpoints.Policy);
        app.MapPost("/api/v1/openai/v1/audio/singing", SingAsync).RequireAuthorization();
    }

    private static async Task<IResult> SaveAsync(HttpContext context, GatewayRoutes routes, CancellationToken ct)
    {
        var changes = await V9Endpoints.ReadJsonAsync(context.Request, "INVALID_REQUEST", ct).ConfigureAwait(false) as JsonObject
            ?? throw BadRequest("JSON object required");
        if (changes.Count == 0 || changes.Any(pair => !Sections.Contains(pair.Key, StringComparer.Ordinal)))
            throw BadRequest("Choose a local speech, transcription, alignment or singing service");
        // Merge on the server: a form for one service must not replace the other gateway sections or their keys.
        var document = await routes.MaskedAsync(ct).ConfigureAwait(false);
        foreach (var (key, node) in changes)
        {
            if (node is not JsonObject patch || patch.Any(p => !Editable.Contains(p.Key, StringComparer.Ordinal)))
                throw BadRequest("Unknown local service setting");
            var section = document[key] as JsonObject ?? new JsonObject();
            section["kind"] = LocalVoice.Kind;
            foreach (var (field, value) in patch)
                section[field] = value?.DeepClone();
            document[key] = section.Parent is null ? section : section.DeepClone();
        }
        ValidateSections(document);
        await routes.SaveAsync(await routes.ResolveMaskedKeysAsync(document, ct).ConfigureAwait(false), ct).ConfigureAwait(false);
        return Results.Json(new JsonObject { ["ok"] = true, ["trainingVerified"] = false });
    }

    private static async Task<IResult> CheckAsync(HttpContext context, IHttpClientFactory factory, CancellationToken ct)
    {
        var body = await V9Endpoints.ReadJsonAsync(context.Request, "INVALID_REQUEST", ct).ConfigureAwait(false) as JsonObject
            ?? throw BadRequest("JSON object required");
        var upstream = body["upstream"]?.GetValue<string>() ?? "";
        var path = body["healthPath"]?.GetValue<string>() is { Length: > 0 } health ? health : "/health";
        if (upstream.Length == 0)
            return Results.Json(new JsonObject { ["status"] = "not_configured", ["trainingVerified"] = false });
        if (!ValidAddress(upstream) || !ValidHealthPath(path))
            throw BadRequest("Invalid service address or health path");
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
        timeout.CancelAfter(TimeSpan.FromSeconds(5));
        var result = new JsonObject { ["upstream"] = upstream, ["checkedAt"] = DateTimeOffset.UtcNow, ["trainingVerified"] = false };
        try
        {
            using var response = await factory.CreateClient(GatewayEndpoints.HttpClientName).GetAsync(upstream.TrimEnd('/') + path, HttpCompletionOption.ResponseHeadersRead, timeout.Token).ConfigureAwait(false);
            result["status"] = response.IsSuccessStatusCode ? "reachable" : "unreachable";
            result["httpStatus"] = (int)response.StatusCode;
        }
        catch (Exception e) when (!ct.IsCancellationRequested && e is HttpRequestException or OperationCanceledException)
        {
            result["status"] = "unreachable";
        }
        return Results.Json(result);
    }

    private static async Task SingAsync(HttpContext context, GatewayRoutes routes, IHttpClientFactory factory, CancellationToken ct)
    {
        var body = await V9Endpoints.ReadJsonAsync(context.Request, "INVALID_REQUEST", ct).ConfigureAwait(false) as JsonObject
            ?? throw BadRequest("JSON object required");
        var title = body["song"]?.GetValue<string>()?.Trim() ?? "";
        if (title.Length is < 1 or > 120)
            throw BadRequest("Choose a song title of at most 120 characters");
        var configured = await routes.SectionAsync("singing", ct).ConfigureAwait(false)
            ?? throw new ApiException(503, "GATEWAY_UNCONFIGURED", "singing is not configured");
        if (configured.Section["kind"]?.GetValue<string>() != LocalVoice.Kind)
            throw BadRequest("Singing uses the local /sing WAV protocol");
        var payload = new JsonObject { ["song"] = title };
        if (configured.Section["voice"]?.GetValue<string>() is { Length: > 0 } voice)
            payload["voice"] = voice;
        using var request = new HttpRequestMessage(HttpMethod.Post, configured.Route.Upstream.TrimEnd('/') + "/sing")
        {
            Content = new StringContent(payload.ToJsonString(), Encoding.UTF8, "application/json"),
        };
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
        timeout.CancelAfter(TimeSpan.FromSeconds(90));
        try
        {
            using var response = await factory.CreateClient(GatewayEndpoints.HttpClientName).SendAsync(request, HttpCompletionOption.ResponseHeadersRead, timeout.Token).ConfigureAwait(false);
            if (response.StatusCode is HttpStatusCode.NotFound or HttpStatusCode.UnprocessableEntity)
                throw new ApiException(422, "SONG_UNAVAILABLE", "The local service does not have this song");
            if (!response.IsSuccessStatusCode)
                throw new ApiException(502, "SINGING_UNAVAILABLE", "The local singing service failed");
            if (response.Content.Headers.ContentLength > MaxAudioBytes)
                throw new ApiException(502, "INVALID_SINGING_AUDIO", "The recording is too large");
            await using var stream = await response.Content.ReadAsStreamAsync(timeout.Token).ConfigureAwait(false);
            using var buffer = new MemoryStream();
            var chunk = new byte[16384];
            int read;
            while ((read = await stream.ReadAsync(chunk, timeout.Token).ConfigureAwait(false)) > 0)
            {
                if (buffer.Length + read > MaxAudioBytes)
                    throw new ApiException(502, "INVALID_SINGING_AUDIO", "The recording is too large");
                await buffer.WriteAsync(chunk.AsMemory(0, read), timeout.Token).ConfigureAwait(false);
            }
            var audio = buffer.ToArray();
            if (!LocalVoice.IsWav(audio))
                throw new ApiException(502, "INVALID_SINGING_AUDIO", "The service did not return WAV audio");
            context.Response.ContentType = "audio/wav";
            await context.Response.Body.WriteAsync(audio, ct).ConfigureAwait(false);
        }
        catch (Exception e) when (!ct.IsCancellationRequested && e is HttpRequestException or OperationCanceledException)
        {
            throw new ApiException(502, "SINGING_UNAVAILABLE", "The local singing service could not be reached");
        }
    }
}
