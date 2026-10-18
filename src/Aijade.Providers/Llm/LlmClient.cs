using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

using Aijade.Core.Js;

namespace Aijade.Providers.Llm;

// A minimal OpenAI-compatible chat
// client (Ollama's /v1 endpoint by default) shared by the skill forge and continuous learning, with tolerant parsing of
// completions and of JSON embedded in model output.

public enum ChatRole
{
    System,
    User,
    Assistant,
    Tool,
}

public sealed record ChatMessage(ChatRole Role, string Content, string? Name = null);

public sealed record ChatRequestOptions(double? Temperature = null, double? TopP = null, int? MaxTokens = null, IReadOnlyList<string>? Stop = null, TimeSpan? Timeout = null);

public sealed record TokenUsage(double PromptTokens, double CompletionTokens, double TotalTokens);

public sealed record ChatCompletion(string Id, string Model, string Text, string? FinishReason, TokenUsage? Usage, JsonNode? Raw);

/// <summary>The chat surface used by the learning components (an interface, so tests and other providers can stand in).</summary>
public interface IChatClient
{
    string Model { get; }

    Task<ChatCompletion> CompleteAsync(IReadOnlyList<ChatMessage> messages, ChatRequestOptions? options = null, CancellationToken cancellationToken = default);

    /// <summary>Request JSON output and parse it from the completion (tolerating fences and surrounding prose).</summary>
    Task<JsonNode?> JsonCompleteAsync(IReadOnlyList<ChatMessage> messages, ChatRequestOptions? options = null, CancellationToken cancellationToken = default);
}

public sealed class LlmRequestException(string message) : Exception(message);

public static class ChatParsing
{
    /// <summary>Text, model, finish reason and usage of an OpenAI chat response; anything missing degrades to empty / fallback / null.</summary>
    public static ChatCompletion ParseCompletion(JsonNode? raw, string fallbackModel)
    {
        var choice = raw?["choices"] is JsonArray { Count: > 0 } choices ? choices[0] : null;
        var usage = raw?["usage"] is JsonObject u
            ? new TokenUsage(Num(u["prompt_tokens"]), Num(u["completion_tokens"]), Num(u["total_tokens"]))
            : null;
        return new ChatCompletion(Str(raw?["id"]) ?? "", Str(raw?["model"]) ?? fallbackModel, Str(choice?["message"]?["content"]) ?? "", Str(choice?["finish_reason"]), usage, raw);
    }

    private static string? Str(JsonNode? n) => n is JsonValue v && v.TryGetValue<string>(out var s) ? s : null;

    private static double Num(JsonNode? n) => n is JsonValue v && v.GetValueKind() == JsonValueKind.Number ? double.Parse(v.ToJsonString(), System.Globalization.CultureInfo.InvariantCulture) : 0;

    private static readonly Regex Fence = new(@"^```(?:json)?" + JsText.Space + "*([\\s\\S]*?)" + JsText.Space + "*```$", JsText.Options(ignoreCase: true));

    /// <summary>
    /// Parse JSON from model output: strip a ```json fence if the whole text is fenced; if that is not valid JSON, fall back
    /// to the span from the first '{' or '[' to the last '}' or ']'.
    /// </summary>
    public static JsonNode? ParseJsonContent(string text)
    {
        var trimmed = JsText.Trim(text);
        if (trimmed.Length == 0)
            throw new FormatException("Model returned empty content; cannot parse JSON.");
        var m = Fence.Match(trimmed);
        var candidate = m.Success ? JsText.Trim(m.Groups[1].Value) : trimmed;
        try
        {
            return JsonNode.Parse(candidate);
        }
        catch (JsonException)
        {
            var braces = new[] { candidate.IndexOf('{', StringComparison.Ordinal), candidate.IndexOf('[', StringComparison.Ordinal) }.Where(i => i >= 0).ToList();
            var start = braces.Count > 0 ? braces.Min() : -1;
            var end = Math.Max(candidate.LastIndexOf('}'), candidate.LastIndexOf(']'));
            if (start < 0 || end < 0 || end < start)
                throw new FormatException($"Could not extract JSON from model output: {(trimmed.Length > 200 ? trimmed[..200] : trimmed)}");
            return JsonNode.Parse(candidate[start..(end + 1)]);
        }
    }
}

/// <summary>An OpenAI-compatible chat client; defaults to a local Ollama.</summary>
public sealed class OpenAiCompatibleChatClient(HttpClient http, string? baseUrl = null, string model = "default", string? apiKey = null, TimeSpan? defaultTimeout = null) : IChatClient
{
    public string BaseUrl { get; } = (baseUrl ?? "http://localhost:11434").Trim().TrimEnd('/');

    public string Model { get; } = model;

    private readonly TimeSpan _timeout = defaultTimeout ?? TimeSpan.FromMilliseconds(120_000);

    internal JsonObject BuildBody(IReadOnlyList<ChatMessage> messages, ChatRequestOptions? o, bool json)
    {
        var body = new JsonObject
        {
            ["model"] = Model,
            ["stream"] = false,
            ["messages"] = new JsonArray(messages.Select(m =>
            {
                var x = new JsonObject { ["role"] = WireName.Of(m.Role), ["content"] = m.Content };
                if (!string.IsNullOrEmpty(m.Name))
                    x["name"] = m.Name;
                return (JsonNode?)x;
            }).ToArray()),
        };
        if (json)
            body["response_format"] = new JsonObject { ["type"] = "json_object" };
        if (o?.Temperature is { } t)
            body["temperature"] = t;
        if (o?.TopP is { } p)
            body["top_p"] = p;
        if (o?.MaxTokens is { } mt)
            body["max_tokens"] = mt;
        if (o?.Stop is { } stop)
            body["stop"] = new JsonArray(stop.Select(s => (JsonNode?)s).ToArray());
        return body;
    }

    private async Task<JsonNode?> SendAsync(HttpMethod method, string path, JsonObject? body, TimeSpan timeout, CancellationToken ct)
    {
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        cts.CancelAfter(timeout);
        using var req = new HttpRequestMessage(method, new Uri($"{BaseUrl}{path}"));
        if (apiKey is { Length: > 0 })
            req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", apiKey);
        if (body is not null)
            req.Content = new StringContent(JsFormat.Stringify(body), Encoding.UTF8, "application/json");
        using var res = await http.SendAsync(req, cts.Token).ConfigureAwait(false);
        if (!res.IsSuccessStatusCode)
        {
            var text = await res.Content.ReadAsStringAsync(cts.Token).ConfigureAwait(false);
            throw new LlmRequestException($"LLM request failed ({(int)res.StatusCode} {res.ReasonPhrase}): {(text.Length > 500 ? text[..500] : text)}");
        }
        return JsonNode.Parse(await res.Content.ReadAsStringAsync(cts.Token).ConfigureAwait(false));
    }

    public async Task<ChatCompletion> CompleteAsync(IReadOnlyList<ChatMessage> messages, ChatRequestOptions? options = null, CancellationToken cancellationToken = default) =>
        ChatParsing.ParseCompletion(await SendAsync(HttpMethod.Post, "/v1/chat/completions", BuildBody(messages, options, false), options?.Timeout ?? _timeout, cancellationToken).ConfigureAwait(false), Model);

    public async Task<JsonNode?> JsonCompleteAsync(IReadOnlyList<ChatMessage> messages, ChatRequestOptions? options = null, CancellationToken cancellationToken = default)
    {
        var raw = await SendAsync(HttpMethod.Post, "/v1/chat/completions", BuildBody(messages, options, true), options?.Timeout ?? _timeout, cancellationToken).ConfigureAwait(false);
        return ChatParsing.ParseJsonContent(ChatParsing.ParseCompletion(raw, Model).Text);
    }

    /// <summary>The model names the server has pulled.</summary>
    public async Task<IReadOnlyList<string>> ListModelsAsync(CancellationToken cancellationToken = default) =>
        ((await SendAsync(HttpMethod.Get, "/api/tags", null, _timeout, cancellationToken).ConfigureAwait(false))?["models"] as JsonArray ?? [])
            .Select(m => m?["name"]?.GetValue<string>() ?? "").Where(n => n.Length > 0).ToList();
}
