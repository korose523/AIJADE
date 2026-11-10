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
        var tools = await ToolDefinitionsAsync(ct).ConfigureAwait(false);
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
        catch (AijadeApiException)
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
        var names = tools.Select(t => t?["function"]?["name"]?.GetValue<string>() ?? "").ToHashSet(StringComparer.Ordinal);
        for (var round = 0; ; round++)
        {
            var offered = round < rounds && budget > 0 ? tools : null;
            var raw = await api.CompleteChatAsync(options.Model, messages, tools: offered, ct: ct).ConfigureAwait(false);
            var message = raw?["choices"]?[0]?["message"] as JsonObject;
            if (message?["tool_calls"] is JsonArray { Count: > 0 } calls && offered is not null)
            {
                messages.Add(new JsonObject { ["role"] = "assistant", ["content"] = message["content"]?.DeepClone(), ["tool_calls"] = calls.DeepClone() });
                foreach (var call in calls)
                {
                    var name = call?["function"]?["name"]?.GetValue<string>() ?? "";
                    JsonObject? args = null;
                    try
                    {
                        args = JsonNode.Parse(call?["function"]?["arguments"]?.GetValue<string>() is { Length: > 0 } a ? a : "{}") as JsonObject;
                    }
                    catch (System.Text.Json.JsonException) { }
                    string content;
                    if (budget <= 0)
                        content = "Error: the tool-call budget for this turn has been used.";
                    else if (!names.Contains(name))
                        content = "Error: that tool was not offered for this turn.";
                    else if (args is null)
                        content = "Error: tool arguments must be a valid JSON object; nothing was executed.";
                    else
                    {
                        budget--;
                        try
                        {
                            var result = await api.CallToolAsync(name, args, ct).ConfigureAwait(false);
                            content = result.IsError ? $"Error: {result.Content}" : result.Content;
                        }
                        catch (AijadeApiException e) { content = $"Error: {e.Message}"; }
                    }
                    messages.Add(new JsonObject { ["role"] = "tool", ["tool_call_id"] = call?["id"]?.GetValue<string>() ?? name, ["content"] = content });
                }
                continue;
            }
            var text = message?["content"]?.GetValue<string>() ?? "";
            yield return new CompletionDelta(text, raw?["usage"]?["prompt_tokens"]?.GetValue<int>(), raw?["usage"]?["completion_tokens"]?.GetValue<int>());
            yield break;
        }
    }

}
