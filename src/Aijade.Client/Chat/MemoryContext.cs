using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

using Aijade.Client.Api;

namespace Aijade.Client.Chat;

/// <summary>
/// Recalls the caller's long-term memory items related to the user's words and offers them as context. With
/// <paramref name="session"/> only that memory session is searched (a bot account serving many people recalls only what
/// the current speaker said).
/// </summary>
public sealed partial class MemoryRecallProvider(AijadeApi api, Func<bool> enabled, int maxItems = 5, string? session = null) : IContextProvider
{
    [GeneratedRegex(@"[\p{L}\p{N}]{3,}", RegexOptions.CultureInvariant)]
    private static partial Regex Words();

    /// <summary>The query terms: the longest distinct words (CJK runs count as words).</summary>
    public static IReadOnlyList<string> Terms(string text, int count = 3) =>
        Words().Matches(text).Select(m => m.Value.ToLowerInvariant()).Distinct(StringComparer.Ordinal).OrderByDescending(w => w.Length).Take(count).ToList();

    public async Task<string?> SupplyAsync(TurnContext turn, CancellationToken ct)
    {
        if (!enabled())
            return null;
        var items = new Dictionary<string, MemoryItem>(StringComparer.Ordinal);
        // Callers record the utterance in the background while the turn runs; once stored it matches itself, and that echo
        // must not count as a recalled memory (or it would stand in for the real ones and skip the term search).
        void Add(IEnumerable<MemoryItem> found)
        {
            foreach (var item in found)
            {
                if (!string.Equals(item.Content.Trim(), turn.UserText.Trim(), StringComparison.OrdinalIgnoreCase))
                    items.TryAdd(item.Id, item);
            }
        }
        // The whole utterance first: with semantic search on the server this finds related memories by meaning.
        try
        {
            Add(await api.MemoryItemsAsync(turn.UserText, maxItems + 1, session, ct).ConfigureAwait(false));
        }
        catch (AijadeApiException)
        {
            return null;
        }
        foreach (var term in items.Count > 0 ? [] : Terms(turn.UserText))
        {
            try
            {
                Add(await api.MemoryItemsAsync(term, maxItems + 1, session, ct).ConfigureAwait(false));
            }
            catch (AijadeApiException)
            {
                return null; // recall is best effort: a failure must not block the conversation
            }
        }
        if (items.Count == 0)
            return null;
        return "Things you remember about the user (use only when relevant):\n" +
            string.Join("\n", items.Values.OrderByDescending(i => i.CreatedAt).Take(maxItems).Select(i => $"- {i.Content}"));
    }
}

/// <summary>Writes each user utterance into the v9 perception pipeline (when recording is on), so memory is gated, not dumped.</summary>
public sealed class ConversationRecorder(AijadeApi api, string sessionId, string deviceId, TimeProvider? time = null)
{
    private readonly TimeProvider clock = time ?? TimeProvider.System;

    public async Task<bool> RecordAsync(string userText, CancellationToken ct = default)
    {
        if (string.IsNullOrWhiteSpace(userText))
            return false;
        var id = Guid.NewGuid().ToString("N");
        await api.PostPerceptionAsync(new JsonObject
        {
            ["event_id"] = $"chat-{id}", ["session_id"] = sessionId, ["trace_id"] = $"trace-chat-{id}", ["correlation_id"] = $"trace-chat-{id}",
            ["timestamp"] = clock.GetUtcNow().ToUnixTimeMilliseconds(), ["origin_device"] = deviceId, ["privacy_level"] = 1, ["risk_score"] = 0.1,
            ["source"] = "chat", ["content"] = userText,
        }, ct).ConfigureAwait(false);
        return true;
    }
}
