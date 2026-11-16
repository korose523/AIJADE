using System.Runtime.CompilerServices;
using System.Text.Json.Nodes;

using Meai = Microsoft.Extensions.AI;

namespace Aijade.Providers.Llm;

// Bridges to Microsoft.Extensions.AI, the common .NET chat abstraction, in both directions:
//   MeaiChatClient          any Microsoft.Extensions.AI client (OpenAI, Azure OpenAI, Ollama, ONNX GenAI …) as an AIJADE
//                           IChatClient, so skill forging and continuous learning can run on it;
//   AijadeChatClientAsMeai  an AIJADE IChatClient (e.g. the server gateway) as a Microsoft.Extensions.AI client, so the
//                           ecosystem's middleware (caching, telemetry, function invocation) and tools can use it.

public static class MeaiMapping
{
    public static Meai.ChatRole ToMeai(ChatRole role) => role switch
    {
        ChatRole.System => Meai.ChatRole.System,
        ChatRole.Assistant => Meai.ChatRole.Assistant,
        ChatRole.Tool => Meai.ChatRole.Tool,
        _ => Meai.ChatRole.User,
    };

    public static ChatRole FromMeai(Meai.ChatRole role) =>
        role == Meai.ChatRole.System ? ChatRole.System
        : role == Meai.ChatRole.Assistant ? ChatRole.Assistant
        : role == Meai.ChatRole.Tool ? ChatRole.Tool
        : ChatRole.User;

    public static Meai.ChatMessage ToMeai(ChatMessage m) => new(ToMeai(m.Role), m.Content) { AuthorName = m.Name };

    /// <summary>Text content only: AIJADE messages are text; other content (images, tool calls) has no counterpart here.</summary>
    public static ChatMessage FromMeai(Meai.ChatMessage m) => new(FromMeai(m.Role), m.Text, m.AuthorName);

    public static Meai.ChatOptions? ToMeai(ChatRequestOptions? o, string? model = null) =>
        o is null && model is null
            ? null
            : new Meai.ChatOptions
            {
                ModelId = model,
                Temperature = o?.Temperature is { } t ? (float)t : null,
                TopP = o?.TopP is { } p ? (float)p : null,
                MaxOutputTokens = o?.MaxTokens,
                StopSequences = o?.Stop is { Count: > 0 } stop ? [.. stop] : null,
            };

    public static ChatRequestOptions? FromMeai(Meai.ChatOptions? o) =>
        o is null ? null : new ChatRequestOptions(o.Temperature, o.TopP, o.MaxOutputTokens, o.StopSequences is { Count: > 0 } s ? [.. s] : null);
}

/// <summary>A Microsoft.Extensions.AI chat client used through AIJADE's chat surface.</summary>
public sealed class MeaiChatClient(Meai.IChatClient inner, string? model = null) : IChatClient
{
    public string Model => model ?? (inner.GetService(typeof(Meai.ChatClientMetadata)) as Meai.ChatClientMetadata)?.DefaultModelId ?? "default";

    public async Task<ChatCompletion> CompleteAsync(IReadOnlyList<ChatMessage> messages, ChatRequestOptions? options = null, CancellationToken cancellationToken = default)
    {
        Meai.ChatResponse response;
        using var timeout = options?.Timeout is { } t ? new CancellationTokenSource(t) : null;
        using var linked = timeout is null ? null : CancellationTokenSource.CreateLinkedTokenSource(cancellationToken, timeout.Token);
        try
        {
            response = await inner.GetResponseAsync([.. messages.Select(MeaiMapping.ToMeai)], MeaiMapping.ToMeai(options, model), linked?.Token ?? cancellationToken)
                .ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (timeout?.IsCancellationRequested == true && !cancellationToken.IsCancellationRequested)
        {
            throw new LlmRequestException($"LLM request timed out after {options!.Timeout!.Value.TotalMilliseconds} ms");
        }
        var usage = response.Usage is { } u
            ? new TokenUsage(u.InputTokenCount ?? 0, u.OutputTokenCount ?? 0, u.TotalTokenCount ?? (u.InputTokenCount ?? 0) + (u.OutputTokenCount ?? 0))
            : null;
        return new ChatCompletion(response.ResponseId ?? "", response.ModelId ?? Model, response.Text, response.FinishReason?.Value, usage, null);
    }

    public async Task<JsonNode?> JsonCompleteAsync(IReadOnlyList<ChatMessage> messages, ChatRequestOptions? options = null, CancellationToken cancellationToken = default) =>
        ChatParsing.ParseJsonContent((await CompleteAsync(messages, options, cancellationToken).ConfigureAwait(false)).Text);
}

/// <summary>An AIJADE chat client offered as a Microsoft.Extensions.AI client (text in, text out; no tool calls).</summary>
public sealed class AijadeChatClientAsMeai(IChatClient inner) : Meai.IChatClient
{
    private readonly Meai.ChatClientMetadata metadata = new("aijade", null, inner.Model);

    public async Task<Meai.ChatResponse> GetResponseAsync(IEnumerable<Meai.ChatMessage> messages, Meai.ChatOptions? options = null, CancellationToken cancellationToken = default)
    {
        var completion = await inner.CompleteAsync([.. messages.Select(MeaiMapping.FromMeai)], MeaiMapping.FromMeai(options), cancellationToken).ConfigureAwait(false);
        return new Meai.ChatResponse(new Meai.ChatMessage(Meai.ChatRole.Assistant, completion.Text))
        {
            ResponseId = completion.Id,
            ModelId = completion.Model,
            FinishReason = completion.FinishReason is { } f ? new Meai.ChatFinishReason(f) : null,
            Usage = completion.Usage is { } u
                ? new Meai.UsageDetails { InputTokenCount = (long)u.PromptTokens, OutputTokenCount = (long)u.CompletionTokens, TotalTokenCount = (long)u.TotalTokens }
                : null,
        };
    }

    /// <summary>The underlying client is not streaming; the whole reply arrives as one update.</summary>
    public async IAsyncEnumerable<Meai.ChatResponseUpdate> GetStreamingResponseAsync(IEnumerable<Meai.ChatMessage> messages, Meai.ChatOptions? options = null,
        [EnumeratorCancellation] CancellationToken cancellationToken = default)
    {
        var response = await GetResponseAsync(messages, options, cancellationToken).ConfigureAwait(false);
        foreach (var update in response.ToChatResponseUpdates())
            yield return update;
    }

    public object? GetService(Type serviceType, object? serviceKey = null) =>
        serviceKey is not null ? null
        : serviceType == typeof(Meai.ChatClientMetadata) ? metadata
        : serviceType.IsInstanceOfType(this) ? this
        : serviceType.IsInstanceOfType(inner) ? inner
        : null;

    public void Dispose()
    {
    }
}
