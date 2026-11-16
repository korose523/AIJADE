using Aijade.Providers.Llm;

namespace Aijade.Growth.Adapters;

// The LLM port over any OpenAI-compatible chat endpoint (Ollama by default): one user turn in, the text completion out.

public sealed class ChatLlmAdapter(IChatClient client) : ILlmPort
{
    public const string DefaultModel = "qwythos:latest";

    /// <summary>
    /// An Ollama / OpenAI-compatible adapter configured from AIJADE_LLM_BASE_URL, AIJADE_LLM_MODEL and AIJADE_LLM_API_KEY
    /// (defaults: http://localhost:11434, qwythos:latest, no key, 120 s timeout).
    /// </summary>
    public static ChatLlmAdapter CreateDefault(HttpClient http, string? baseUrl = null, string? model = null, string? apiKey = null, TimeSpan? timeout = null) =>
        new(new OpenAiCompatibleChatClient(http,
            baseUrl ?? Environment.GetEnvironmentVariable("AIJADE_LLM_BASE_URL") ?? "http://localhost:11434",
            model ?? Environment.GetEnvironmentVariable("AIJADE_LLM_MODEL") ?? DefaultModel,
            apiKey ?? Environment.GetEnvironmentVariable("AIJADE_LLM_API_KEY"),
            timeout ?? TimeSpan.FromSeconds(120)));

    public async Task<string> CompleteAsync(string prompt, CancellationToken cancellationToken = default) =>
        (await client.CompleteAsync([new ChatMessage(ChatRole.User, prompt)], cancellationToken: cancellationToken).ConfigureAwait(false)).Text;

    /// <summary>Reachability probe: the available model names, or null on failure.</summary>
    public async Task<IReadOnlyList<string>?> ListModelsAsync(CancellationToken cancellationToken = default)
    {
        if (client is not OpenAiCompatibleChatClient http)
            return null;
        try
        {
            return await http.ListModelsAsync(cancellationToken).ConfigureAwait(false);
        }
        catch (Exception e) when (e is HttpRequestException or LlmRequestException or TaskCanceledException)
        {
            return null;
        }
    }
}
