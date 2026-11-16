using System.Runtime.CompilerServices;
using System.Text.Json.Nodes;

using Aijade.Client.Api;

namespace Aijade.Client.Chat;

/// <summary>The bounded tool worker. It runs only for a requested chat turn, with no automatic replay of effects.</summary>
internal sealed class ToolConversation(AijadeApi api, OrchestratorOptions options)
{
    public async IAsyncEnumerable<CompletionDelta> ReplyAsync(List<(string Role, string Content)> messages,
        [EnumeratorCancellation] CancellationToken ct)
    {
        // A zero budget means conversation only: do not even discover tools or switch away from streaming.
        var tools = options.MaxToolCalls <= 0 || options.MaxToolRounds <= 0 ? null : await ToolDefinitionsAsync(ct).ConfigureAwait(false);
        var stream = tools is { Count: > 0 } ? ToolRoundsAsync(messages, tools, ct)
            : api.StreamChatAsync(options.Model, messages, options.Temperature, ct);
        await foreach (var delta in stream.ConfigureAwait(false))
            yield return delta;
    }

    private async Task<JsonArray?> ToolDefinitionsAsync(CancellationToken ct)
    {
        try
        {
            var list = await api.ToolsAsync(ct).ConfigureAwait(false);
            return [.. list.Select(t => (JsonNode)new JsonObject
            {
                ["type"] = "function",
                ["function"] = new JsonObject { ["name"] = t.Name, ["description"] = t.Description, ["parameters"] = t.Parameters.DeepClone() },
            })];
        }
        catch (Exception e) when (e is AijadeApiException or HttpRequestException)
        {
            return null; // no tools for this account (or none configured): answer without them
        }
    }

    /// <summary>
    /// Let the model call tools (non-streaming rounds through the gateway, each call run by the server), then yield its
    /// final answer as one chunk. A tool's error is given back to the model as the tool's result, so it can recover.
    /// </summary>
    private async IAsyncEnumerable<CompletionDelta> ToolRoundsAsync(List<(string Role, string Content)> start, JsonArray tools,
        [EnumeratorCancellation] CancellationToken ct)
    {
        var messages = new JsonArray([.. start.Select(m => (JsonNode)new JsonObject { ["role"] = m.Role, ["content"] = m.Content })]);
        var rounds = Math.Clamp(options.MaxToolRounds, 0, 16);
        var budget = Math.Clamp(options.MaxToolCalls, 0, 64);
        var uncertain = false;
        var names = tools.Select(t => t?["function"]?["name"]?.GetValue<string>() ?? "").ToHashSet(StringComparer.Ordinal);
        for (var round = 0; ; round++)
        {
            var offered = round < rounds && budget > 0 && !uncertain ? tools : null;
            var raw = await api.CompleteChatAsync(options.Model, messages, tools: offered, ct: ct).ConfigureAwait(false);
            var message = raw?["choices"]?[0]?["message"] as JsonObject;
            if (message?["tool_calls"] is JsonArray { Count: > 0 } calls && offered is not null)
            {
                messages.Add(new JsonObject { ["role"] = "assistant", ["content"] = message["content"]?.DeepClone(), ["tool_calls"] = calls.DeepClone() });
                foreach (var call in calls)
                {
                    var function = (call as JsonObject)?["function"] as JsonObject;
                    var name = String(function?["name"]) ?? "";
                    JsonObject? args = null;
                    try
                    {
                        // OpenAI function arguments are an encoded JSON object, never an arbitrary JSON node.
                        if (String(function?["arguments"]) is { } encoded)
                            args = JsonNode.Parse(encoded) as JsonObject;
                    }
                    catch (System.Text.Json.JsonException) { }
                    string content;
                    if (uncertain)
                        content = "Error: a prior tool outcome is unknown. No further tools were executed this turn; do not claim success or retry automatically.";
                    else if (budget <= 0)
                        content = "Error: the tool-call budget for this turn has been used.";
                    else if (!names.Contains(name))
                        content = "Error: that tool was not offered for this turn.";
                    else if (args is null)
                        content = "Error: tool arguments must be a valid JSON object; nothing was executed.";
                    else
                    {
                        budget--;
                        (content, uncertain) = await ExecuteAsync(name, args, ct).ConfigureAwait(false);
                    }
                    if (options.PromptBudget is { } limit && !uncertain)
                        content = PromptBudget.Limit(content, limit.ToolResultCharacters);
                    messages.Add(new JsonObject { ["role"] = "tool", ["tool_call_id"] = String((call as JsonObject)?["id"]) ?? name, ["content"] = content });
                }
                continue;
            }
            var text = message?["content"]?.GetValue<string>() ?? "";
            yield return new CompletionDelta(text, raw?["usage"]?["prompt_tokens"]?.GetValue<int>(), raw?["usage"]?["completion_tokens"]?.GetValue<int>());
            yield break;
        }
    }

    private static string? String(JsonNode? node) => node is JsonValue value && value.TryGetValue<string>(out var text) ? text : null;

    private async Task<(string Content, bool Uncertain)> ExecuteAsync(string name, JsonObject arguments, CancellationToken ct)
    {
        using var deadline = CancellationTokenSource.CreateLinkedTokenSource(ct);
        deadline.CancelAfter(TimeSpan.FromSeconds(Math.Clamp(options.ToolTimeoutSeconds, 1, 300)));
        try
        {
            // WaitAsync also bounds a transport that ignores cancellation. Cancelling the wait cannot undo a remote effect.
            var result = await api.CallToolAsync(name, arguments, deadline.Token).WaitAsync(deadline.Token).ConfigureAwait(false);
            return (result.IsError ? $"Error: {result.Content}" : result.Content, false);
        }
        catch (AijadeApiException e) when (e.Status < 500 && e.Status != 408)
        {
            return ($"Error: {e.Message}", false);
        }
        catch (Exception e) when (!ct.IsCancellationRequested && e is AijadeApiException or HttpRequestException or OperationCanceledException or System.Text.Json.JsonException)
        {
            return ("Error: tool outcome unknown after a timeout or transport/server failure. The action may already have happened. " +
                "Do not claim success or repeat it automatically; ask the user to verify its state.", true);
        }
    }
}
