namespace Aijade.Client.Chat;

/// <summary>
/// Product prompt limits in UTF-16 characters, not model tokens. Persona, current input and channel instructions remain
/// intact; older history and optional context are bounded. Archived direct orchestrator callers opt in explicitly.
/// </summary>
public sealed record PromptBudget
{
    public int ModuleCharacters { get; init; } = 4_000;
    public int SupplementCharacters { get; init; } = 12_000;
    public int HistoryCharacters { get; init; } = 24_000;
    public int ToolResultCharacters { get; init; } = 8_000;

    internal static int Bound(int value) => Math.Clamp(value, 0, 128_000);

    internal static string Limit(string text, int characters)
    {
        var limit = Bound(characters);
        if (text.Length <= limit)
            return text;
        const string marker = "\n[Truncated by the product character budget.]";
        // A tiny budget carries no partial assertion. Never split a Unicode surrogate pair.
        if (limit <= marker.Length)
            return "";
        var end = limit - marker.Length;
        if (char.IsHighSurrogate(text[end - 1]) && char.IsLowSurrogate(text[end]))
            end--;
        return text[..end] + marker;
    }

    internal IReadOnlyList<(string Role, string Content)> History(IEnumerable<(string Role, string Content)> history)
    {
        var selected = new List<(string Role, string Content)>();
        var remaining = Bound(HistoryCharacters);
        foreach (var message in history.Reverse())
        {
            if (message.Content.Length > remaining)
            {
                // Keep a bounded excerpt of the newest message when it alone is too large. Otherwise keep whole messages.
                if (selected.Count == 0 && Limit(message.Content, remaining) is { Length: > 0 } excerpt)
                    selected.Add((message.Role, excerpt));
                break;
            }
            selected.Add(message);
            remaining -= message.Content.Length;
        }
        selected.Reverse();
        return selected;
    }
}
