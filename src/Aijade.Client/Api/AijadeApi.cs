using System.Net;
using System.Net.Http.Headers;
using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace Aijade.Client.Api;

// The typed client of the AIJADE server API, shared by the web app, the MAUI app and tools. Authentication is a bearer
// session token kept by an ITokenStore. Streaming chat completions are read as server-sent events chunk by chunk (in the
// browser the response-streaming option is set so the fetch body is not buffered).

public interface ITokenStore
{
    ValueTask<string?> GetAsync();

    ValueTask SetAsync(string? token);
}

public sealed class MemoryTokenStore : ITokenStore
{
    private string? current;

    public ValueTask<string?> GetAsync() => ValueTask.FromResult(current);

    public ValueTask SetAsync(string? token)
    {
        current = token;
        return ValueTask.CompletedTask;
    }
}

/// <summary>A failed API call: status, the server's error code and message.</summary>
public sealed class AijadeApiException(int status, string code, string message) : Exception(message)
{
    public int Status { get; } = status;

    public string Code { get; } = code;
}

public sealed record AccountInfo(string Id, string Email, string Name, string Role)
{
    public bool IsAdmin => Role == "admin";
}

public sealed record ToolInfo(string Name, string Description, JsonObject Parameters);

public sealed record ToolResult(string Content, bool IsError);

public sealed record ServerCapabilities(IReadOnlyList<string> ChatModels, bool Speech, bool Images);

public sealed record ImageInfo(string Id, string Url, string Mime, string Prompt, long FluxCharged = 0);

public sealed record AdminUser(string Id, string Email, string Name, string Role, bool Banned, DateTimeOffset CreatedAt, long Flux)
{
    public bool IsAdmin => Role == "admin";
}

public sealed record Character(
    string Id, string OwnerId, string Name, string Description, string Persona, string Greeting, string? ModelRef, string? AvatarRef,
    IReadOnlyList<string> Tags, string Visibility);

public sealed record ChatSummary(string Id, string? CharacterId, string Title, DateTimeOffset UpdatedAt);

public sealed record StoredMessage(string Id, long Seq, string Role, string Content, DateTimeOffset CreatedAt, JsonObject? Meta = null);

public sealed record MemoryItem(string Id, string SessionId, string Source, string Content, DateTimeOffset CreatedAt, long MemoryVersions);

public sealed record ProviderInfo(string Id, string Kind, string Name, string? BaseUrl, bool HasSecret);

/// <summary>One streamed piece of a completion: text, or the final usage.</summary>
public sealed record CompletionDelta(string Text, int? PromptTokens = null, int? CompletionTokens = null);

public sealed class AijadeApi(HttpClient http, ITokenStore tokens)
{
    private static readonly JsonSerializerOptions Json = JsonSerializerOptions.Web;
    private static readonly HttpRequestOptionsKey<bool> BrowserStreaming = new("WebAssemblyEnableStreamingResponse");

    public HttpClient Http => http;

    private async Task<HttpRequestMessage> RequestAsync(HttpMethod method, string path, object? body = null)
    {
        var req = new HttpRequestMessage(method, path);
        if (body is not null)
            req.Content = new StringContent(body is JsonNode n ? n.ToJsonString() : JsonSerializer.Serialize(body, Json), Encoding.UTF8, "application/json");
        if (await tokens.GetAsync().ConfigureAwait(false) is { Length: > 0 } token)
            req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        return req;
    }

    private static async Task<JsonNode?> ReadAsync(HttpResponseMessage res, CancellationToken ct)
    {
        var text = await res.Content.ReadAsStringAsync(ct).ConfigureAwait(false);
        JsonNode? json = null;
        try
        {
            json = text.Length == 0 ? null : JsonNode.Parse(text);
        }
        catch (JsonException)
        {
        }
        if (!res.IsSuccessStatusCode)
            throw new AijadeApiException((int)res.StatusCode, json?["error"]?.GetValue<string>() ?? res.StatusCode.ToString(), json?["message"]?.GetValue<string>() ?? text);
        return json;
    }

    public async Task<JsonNode?> SendAsync(HttpMethod method, string path, object? body = null, CancellationToken ct = default)
    {
        using var req = await RequestAsync(method, path, body).ConfigureAwait(false);
        using var res = await http.SendAsync(req, ct).ConfigureAwait(false);
        return await ReadAsync(res, ct).ConfigureAwait(false);
    }

    private static T To<T>(JsonNode? n) => n.Deserialize<T>(Json)!;

    // ---- accounts -----------------------------------------------------------------------------------------------------

    public async Task<AccountInfo> SignInAsync(string email, string password, CancellationToken ct = default)
    {
        var r = await SendAsync(HttpMethod.Post, "/api/v1/auth/sign-in/email", new { email, password }, ct).ConfigureAwait(false);
        await tokens.SetAsync(r!["token"]!.GetValue<string>()).ConfigureAwait(false);
        return To<AccountInfo>(r["user"]);
    }

    public async Task<AccountInfo> SignUpAsync(string email, string password, string? name, CancellationToken ct = default)
    {
        var r = await SendAsync(HttpMethod.Post, "/api/v1/auth/sign-up/email", new { email, password, name }, ct).ConfigureAwait(false);
        await tokens.SetAsync(r!["token"]!.GetValue<string>()).ConfigureAwait(false);
        return To<AccountInfo>(r["user"]);
    }

    public async Task SignOutAsync(CancellationToken ct = default)
    {
        try
        {
            await SendAsync(HttpMethod.Post, "/api/v1/auth/sign-out", ct: ct).ConfigureAwait(false);
        }
        finally
        {
            await tokens.SetAsync(null).ConfigureAwait(false);
        }
    }

    /// <summary>The signed-in account, or null when the token is missing or no longer valid.</summary>
    public async Task<AccountInfo?> SessionAsync(CancellationToken ct = default)
    {
        if (await tokens.GetAsync().ConfigureAwait(false) is not { Length: > 0 })
            return null;
        try
        {
            return To<AccountInfo>((await SendAsync(HttpMethod.Get, "/api/v1/auth/session", ct: ct).ConfigureAwait(false))!["user"]);
        }
        catch (AijadeApiException e) when (e.Status == 401)
        {
            return null;
        }
    }

    public Task DeleteAccountAsync(CancellationToken ct = default) => SendAsync(HttpMethod.Delete, "/api/v1/auth/account", ct: ct);

    // ---- library ------------------------------------------------------------------------------------------------------

    public async Task<IReadOnlyList<Character>> CharactersAsync(CancellationToken ct = default) =>
        To<List<Character>>((await SendAsync(HttpMethod.Get, "/api/v1/characters", ct: ct).ConfigureAwait(false))!["characters"]);

    public async Task<Character> CreateCharacterAsync(object character, CancellationToken ct = default) =>
        To<Character>(await SendAsync(HttpMethod.Post, "/api/v1/characters", character, ct).ConfigureAwait(false));

    public async Task<Character> UpdateCharacterAsync(string id, object patch, CancellationToken ct = default) =>
        To<Character>(await SendAsync(HttpMethod.Patch, $"/api/v1/characters/{Uri.EscapeDataString(id)}", patch, ct).ConfigureAwait(false));

    public Task DeleteCharacterAsync(string id, CancellationToken ct = default) => SendAsync(HttpMethod.Delete, $"/api/v1/characters/{Uri.EscapeDataString(id)}", ct: ct);

    public async Task<IReadOnlyList<ChatSummary>> ChatsAsync(CancellationToken ct = default) =>
        To<List<ChatSummary>>((await SendAsync(HttpMethod.Get, "/api/v1/chats", ct: ct).ConfigureAwait(false))!["chats"]);

    public async Task<ChatSummary> CreateChatAsync(string? characterId, string title, CancellationToken ct = default) =>
        To<ChatSummary>(await SendAsync(HttpMethod.Post, "/api/v1/chats", new { characterId, title }, ct).ConfigureAwait(false));

    public Task DeleteChatAsync(string id, CancellationToken ct = default) => SendAsync(HttpMethod.Delete, $"/api/v1/chats/{Uri.EscapeDataString(id)}", ct: ct);

    public async Task<IReadOnlyList<StoredMessage>> MessagesAsync(string chatId, long after = 0, CancellationToken ct = default) =>
        To<List<StoredMessage>>((await SendAsync(HttpMethod.Get, $"/api/v1/chats/{Uri.EscapeDataString(chatId)}/messages?after={after}", ct: ct).ConfigureAwait(false))!["messages"]);

    public async Task<StoredMessage> AppendMessageAsync(string chatId, string role, string content, JsonObject? meta = null, CancellationToken ct = default) =>
        To<StoredMessage>(await SendAsync(HttpMethod.Post, $"/api/v1/chats/{Uri.EscapeDataString(chatId)}/messages", new { role, content, meta }, ct).ConfigureAwait(false));

    public async Task<IReadOnlyList<ProviderInfo>> ProvidersAsync(CancellationToken ct = default) =>
        To<List<ProviderInfo>>((await SendAsync(HttpMethod.Get, "/api/v1/providers", ct: ct).ConfigureAwait(false))!["providers"]);

    public async Task<ProviderInfo> AddProviderAsync(string kind, string name, string? baseUrl, string? apiKey, CancellationToken ct = default) =>
        To<ProviderInfo>(await SendAsync(HttpMethod.Post, "/api/v1/providers", new { kind, name, baseUrl, apiKey }, ct).ConfigureAwait(false));

    public Task DeleteProviderAsync(string id, CancellationToken ct = default) => SendAsync(HttpMethod.Delete, $"/api/v1/providers/{Uri.EscapeDataString(id)}", ct: ct);

    public async Task<long> FluxBalanceAsync(CancellationToken ct = default) =>
        (await SendAsync(HttpMethod.Get, "/api/v1/flux", ct: ct).ConfigureAwait(false))!["balance"]!.GetValue<long>();

    public async Task<IReadOnlyList<string>> ModelsAsync(CancellationToken ct = default) =>
        (await SendAsync(HttpMethod.Get, "/api/v1/openai/v1/models", ct: ct).ConfigureAwait(false))!["data"]!.AsArray().Select(m => m!["id"]!.GetValue<string>()).ToList();

    public Task<JsonNode?> PostEventAsync(JsonObject envelope, CancellationToken ct = default) => SendAsync(HttpMethod.Post, "/api/v1/v9/events", envelope, ct);

    public async Task<IReadOnlyList<MemoryItem>> MemoryItemsAsync(string? query = null, int limit = 100, string? session = null, CancellationToken ct = default) =>
        To<List<MemoryItem>>((await SendAsync(HttpMethod.Get, $"/api/v1/memory/items?limit={limit}{(string.IsNullOrWhiteSpace(query) ? "" : $"&q={Uri.EscapeDataString(query)}")}" +
            $"{(session is null ? "" : $"&session={Uri.EscapeDataString(session)}")}", ct: ct).ConfigureAwait(false))!["items"]);

    public Task ForgetMemoryAsync(string id, CancellationToken ct = default) => SendAsync(HttpMethod.Delete, $"/api/v1/memory/items/{Uri.EscapeDataString(id)}", ct: ct);

    public async Task<JsonObject> ExportMemoryAsync(CancellationToken ct = default) =>
        (JsonObject)(await SendAsync(HttpMethod.Get, "/api/v1/memory/items/export", ct: ct).ConfigureAwait(false))!;

    public async Task<int> ImportMemoryAsync(JsonObject export, CancellationToken ct = default) =>
        (await SendAsync(HttpMethod.Post, "/api/v1/memory/items/import", export, ct).ConfigureAwait(false))!["imported"]!.GetValue<int>();

    public Task<JsonNode?> PostPerceptionAsync(JsonObject perception, CancellationToken ct = default) => SendAsync(HttpMethod.Post, "/api/v1/v9/perception", perception, ct);

    /// <summary>Transcribe one recorded utterance with the server's speech-recognition route.</summary>
    public async Task<string> TranscribeAsync(byte[] audio, string mime, string? language, double seconds, CancellationToken ct = default)
    {
        using var form = new MultipartFormDataContent();
        var file = new ByteArrayContent(audio);
        file.Headers.ContentType = MediaTypeHeaderValue.TryParse(mime, out var type) ? type : new MediaTypeHeaderValue("application/octet-stream");
        form.Add(file, "file", mime.Contains("ogg", StringComparison.Ordinal) ? "speech.ogg" : mime.Contains("mp4", StringComparison.Ordinal) ? "speech.m4a" : "speech.webm");
        if (language is { Length: > 0 })
            form.Add(new StringContent(language), "language");
        form.Add(new StringContent(seconds.ToString("0.###", System.Globalization.CultureInfo.InvariantCulture)), "duration");
        using var req = await RequestAsync(HttpMethod.Post, "/api/v1/openai/v1/audio/transcriptions").ConfigureAwait(false);
        req.Content = form;
        using var res = await http.SendAsync(req, ct).ConfigureAwait(false);
        return (await ReadAsync(res, ct).ConfigureAwait(false))?["text"]?.GetValue<string>() ?? "";
    }

    // ---- tools (MCP servers and built-in integrations, run by the server) ---------------------------------------------

    /// <summary>The tools this account may use, as OpenAI function definitions.</summary>
    public async Task<IReadOnlyList<ToolInfo>> ToolsAsync(CancellationToken ct = default) =>
        To<List<ToolInfo>>((await SendAsync(HttpMethod.Get, "/api/v1/tools", ct: ct).ConfigureAwait(false))!["tools"]);

    public async Task<ToolResult> CallToolAsync(string name, JsonObject arguments, CancellationToken ct = default) =>
        To<ToolResult>(await SendAsync(HttpMethod.Post, "/api/v1/tools/call", new JsonObject { ["name"] = name, ["arguments"] = arguments }, ct).ConfigureAwait(false));

    // ---- capabilities and drawing ---------------------------------------------------------------------------------------

    public async Task<ServerCapabilities> CapabilitiesAsync(CancellationToken ct = default) =>
        To<ServerCapabilities>(await SendAsync(HttpMethod.Get, "/api/v1/capabilities", ct: ct).ConfigureAwait(false));

    /// <summary>Have the server draw a picture; it is stored for this account and costs flux when priced.</summary>
    public async Task<ImageInfo> GenerateImageAsync(string prompt, string? size = null, CancellationToken ct = default) =>
        To<ImageInfo>(await SendAsync(HttpMethod.Post, "/api/v1/images", new { prompt, size }, ct).ConfigureAwait(false));

    /// <summary>The image file (owner only), for display through a blob URL.</summary>
    public async Task<(byte[] Bytes, string Mime)> ImageBytesAsync(string id, CancellationToken ct = default)
    {
        using var req = await RequestAsync(HttpMethod.Get, $"/api/v1/images/{Uri.EscapeDataString(id)}").ConfigureAwait(false);
        using var res = await http.SendAsync(req, ct).ConfigureAwait(false);
        if (!res.IsSuccessStatusCode)
            await ReadAsync(res, ct).ConfigureAwait(false);
        return (await res.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false), res.Content.Headers.ContentType?.MediaType ?? "image/png");
    }

    // ---- administration (role "admin") --------------------------------------------------------------------------------

    public async Task<IReadOnlyList<AdminUser>> AdminUsersAsync(string? query = null, CancellationToken ct = default) =>
        To<List<AdminUser>>((await SendAsync(HttpMethod.Get, "/api/v1/admin/users" + (string.IsNullOrWhiteSpace(query) ? "" : $"?q={Uri.EscapeDataString(query)}"), ct: ct).ConfigureAwait(false))!["users"]);

    /// <summary>Change a user's role and/or ban state (null leaves it unchanged). Banning also ends the user's sessions.</summary>
    public Task AdminUpdateUserAsync(string id, string? role = null, bool? banned = null, string? banReason = null, CancellationToken ct = default) =>
        SendAsync(HttpMethod.Patch, $"/api/v1/admin/users/{Uri.EscapeDataString(id)}", new { role, banned, banReason }, ct);

    /// <summary>Grant (positive) or deduct (negative) flux; the idempotency key makes a double click count once.</summary>
    public Task AdminGrantFluxAsync(string userId, long amount, string? reason, string idempotencyKey, CancellationToken ct = default) =>
        SendAsync(HttpMethod.Post, "/api/v1/admin/flux-grants", new { userId, amount, reason, idempotencyKey }, ct);

    /// <summary>The gateway routing document with upstream keys masked to their last four characters.</summary>
    public async Task<JsonObject> AdminGatewayRoutesAsync(CancellationToken ct = default) =>
        (await SendAsync(HttpMethod.Get, "/api/v1/admin/gateway/routes", ct: ct).ConfigureAwait(false)) as JsonObject ?? [];

    /// <summary>Save the routing document; masked keys keep the stored key they stand for.</summary>
    public Task AdminSaveGatewayRoutesAsync(JsonObject doc, CancellationToken ct = default) => SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", doc, ct);

    public async Task<JsonObject> AdminV9StatsAsync(CancellationToken ct = default) =>
        (await SendAsync(HttpMethod.Get, "/api/v1/admin/v9/stats", ct: ct).ConfigureAwait(false)) as JsonObject ?? [];

    public async Task<JsonArray> AdminProductEventsAsync(DateTimeOffset from, CancellationToken ct = default) =>
        (await SendAsync(HttpMethod.Get, $"/api/v1/admin/analytics/product-events?from={Uri.EscapeDataString(from.ToString("O", System.Globalization.CultureInfo.InvariantCulture))}", ct: ct).ConfigureAwait(false))?["rows"] as JsonArray ?? [];

    public async Task<JsonArray> AdminLlmRequestsAsync(CancellationToken ct = default) =>
        (await SendAsync(HttpMethod.Get, "/api/v1/admin/llm-requests", ct: ct).ConfigureAwait(false))?["requests"] as JsonArray ?? [];

    /// <summary>Rebuild missing render-trace rows from the event log; a dry run only reports what it would insert.</summary>
    public async Task<JsonObject> AdminRenderTraceBackfillAsync(bool dryRun, CancellationToken ct = default) =>
        (await SendAsync(HttpMethod.Post, $"/api/v1/admin/v9/render-trace-backfill?dryRun={(dryRun ? "true" : "false")}", ct: ct).ConfigureAwait(false)) as JsonObject ?? [];

    // ---- generation ---------------------------------------------------------------------------------------------------

    /// <summary>Stream a chat completion from the server gateway (OpenAI-compatible SSE).</summary>
    /// <summary>A non-streaming completion with OpenAI-format messages as given (e.g. multimodal content arrays).</summary>
    public async Task<JsonNode?> CompleteChatAsync(string model, JsonArray messages, int? maxTokens = null, JsonArray? tools = null, CancellationToken ct = default)
    {
        // Copies: callers keep and extend their message list across tool rounds.
        var body = new JsonObject { ["model"] = model, ["messages"] = messages.DeepClone() };
        if (maxTokens is { } n)
            body["max_tokens"] = n;
        if (tools is { Count: > 0 })
            body["tools"] = tools.DeepClone();
        return await SendAsync(HttpMethod.Post, "/api/v1/openai/v1/chat/completions", body, ct).ConfigureAwait(false);
    }

    /// <summary>One non-streaming completion through the gateway; returns the raw OpenAI-shaped response.</summary>
    public async Task<JsonNode?> CompleteChatAsync(string model, IReadOnlyList<(string Role, string Content)> messages, double? temperature = null, int? maxTokens = null,
        CancellationToken ct = default)
    {
        var body = new JsonObject
        {
            ["model"] = model,
            ["messages"] = new JsonArray([.. messages.Select(m => (JsonNode)new JsonObject { ["role"] = m.Role, ["content"] = m.Content })]),
        };
        if (temperature is { } t)
            body["temperature"] = t;
        if (maxTokens is { } n)
            body["max_tokens"] = n;
        return await SendAsync(HttpMethod.Post, "/api/v1/openai/v1/chat/completions", body, ct).ConfigureAwait(false);
    }

    public async IAsyncEnumerable<CompletionDelta> StreamChatAsync(string model, IReadOnlyList<(string Role, string Content)> messages, double? temperature = null,
        [EnumeratorCancellation] CancellationToken ct = default)
    {
        var body = new JsonObject
        {
            ["model"] = model,
            ["stream"] = true,
            ["messages"] = new JsonArray([.. messages.Select(m => (JsonNode)new JsonObject { ["role"] = m.Role, ["content"] = m.Content })]),
        };
        if (temperature is { } t)
            body["temperature"] = t;
        using var req = await RequestAsync(HttpMethod.Post, "/api/v1/openai/v1/chat/completions", body).ConfigureAwait(false);
        req.Options.Set(BrowserStreaming, true);
        using var res = await http.SendAsync(req, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false);
        if (!res.IsSuccessStatusCode)
            await ReadAsync(res, ct).ConfigureAwait(false);
        await using var stream = await res.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
        await foreach (var delta in Sse.ParseCompletionAsync(stream, ct).ConfigureAwait(false))
            yield return delta;
    }

    public async Task<byte[]> SpeechAsync(string input, string voice, CancellationToken ct = default)
    {
        using var req = await RequestAsync(HttpMethod.Post, "/api/v1/openai/v1/audio/speech", new { input, voice }).ConfigureAwait(false);
        using var res = await http.SendAsync(req, ct).ConfigureAwait(false);
        if (!res.IsSuccessStatusCode)
            await ReadAsync(res, ct).ConfigureAwait(false);
        return await res.Content.ReadAsByteArrayAsync(ct).ConfigureAwait(false);
    }

    public static bool IsUnauthorized(Exception e) => e is AijadeApiException { Status: (int)HttpStatusCode.Unauthorized };
}

/// <summary>Server-sent events of an OpenAI-compatible completion stream.</summary>
public static class Sse
{
    public static async IAsyncEnumerable<CompletionDelta> ParseCompletionAsync(Stream stream, [EnumeratorCancellation] CancellationToken ct = default)
    {
        using var reader = new StreamReader(stream, Encoding.UTF8);
        while (await reader.ReadLineAsync(ct).ConfigureAwait(false) is { } line)
        {
            if (!line.StartsWith("data:", StringComparison.Ordinal))
                continue;
            var data = line[5..].Trim();
            if (data == "[DONE]")
                yield break;
            JsonNode? chunk;
            try
            {
                chunk = JsonNode.Parse(data);
            }
            catch (JsonException)
            {
                continue;
            }
            if (chunk?["choices"] is JsonArray { Count: > 0 } choices && choices[0]?["delta"]?["content"] is JsonValue c && c.TryGetValue<string>(out var text) && text.Length > 0)
                yield return new CompletionDelta(text);
            if (chunk?["usage"] is JsonObject u)
                yield return new CompletionDelta("", u["prompt_tokens"]?.GetValue<int>(), u["completion_tokens"]?.GetValue<int>());
        }
    }
}
