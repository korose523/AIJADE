using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

namespace Aijade.Client.Chat;

/// <summary>A single JSON value requested explicitly in a product chat turn.</summary>
public static partial class StrictJsonReply
{
    internal const int MaxTokens = 2048;
    internal const int MaxResponseCharacters = 32_768;
    internal const string Instruction = "For this reply, emit exactly one complete JSON value using the user's requested shape and content. " +
        "Start with the value and end with the value. Omit Markdown fences, headings, commentary and performance markers outside the value.";

    public static bool IsRequested(string text) => RequestDirective().IsMatch(text);

    [GeneratedRegex(@"^\s*(?:/json(?:\s|$)" +
        @"|(?:请\s*)?(?:仅|只|只能)\s*(?:输出|返回|回复)\s*(?:(?:这?一行|一个|一份|有效的|合法的|严格的|纯)\s*){0,4}JSON(?:对象|数组|值|格式)?(?:[\s:：,，。]|$)" +
        @"|(?:please\s+)?(?:(?:return|output|respond\s+with|reply\s+with)\s+only\s+(?:valid\s+|raw\s+|strict\s+)?JSON\b" +
        @"|only\s+(?:return|output)\s+(?:valid\s+|raw\s+|strict\s+)?JSON\b" +
        @"|(?:return\s+|output\s+|respond\s+with\s+|reply\s+with\s+)?(?:valid\s+|raw\s+|strict\s+)?JSON\s+only\b))",
        RegexOptions.IgnoreCase | RegexOptions.CultureInvariant | RegexOptions.NonBacktracking)]
    private static partial Regex RequestDirective();

    internal static string? GetContent(JsonNode? completion)
    {
        if (completion is not JsonObject envelope || envelope["choices"] is not JsonArray { Count: 1 } choices ||
            choices[0] is not JsonObject choice || choice["message"] is not JsonObject message ||
            message["content"] is not JsonValue content || !content.TryGetValue<string>(out var raw) ||
            raw.Length > MaxResponseCharacters || message["tool_calls"] is not (null or JsonArray { Count: 0 }) || message["function_call"] is not null ||
            (message["refusal"] is { } refusal && (refusal is not JsonValue refusalValue ||
                !refusalValue.TryGetValue<string>(out var refusalText) || !string.IsNullOrWhiteSpace(refusalText))) ||
            (choice["finish_reason"] is { } finish && (finish is not JsonValue reason ||
                !reason.TryGetValue<string>(out var value) || value != "stop")))
            return null;

        var candidate = raw.Trim(' ', '\t', '\r', '\n');
        if (candidate.StartsWith("```", StringComparison.Ordinal))
        {
            // Recover only a whole-response fence with distinct lines. Mixed prose and partial fences stay invalid.
            var start = candidate.IndexOf('\n', StringComparison.Ordinal);
            var end = candidate.LastIndexOf('\n');
            if (start < 0 || end <= start || candidate[(end + 1)..] != "```")
                return null;
            var tag = candidate[..start].TrimEnd('\r', '\t', ' ');
            if (tag != "```" && !tag.Equals("```json", StringComparison.OrdinalIgnoreCase))
                return null;
            candidate = candidate[(start + 1)..end].Trim(' ', '\t', '\r', '\n');
        }

        try
        {
            using var parsed = JsonDocument.Parse(candidate, new JsonDocumentOptions { MaxDepth = 64, AllowDuplicateProperties = false });
            return candidate;
        }
        catch (JsonException)
        {
            return null;
        }
    }
}
