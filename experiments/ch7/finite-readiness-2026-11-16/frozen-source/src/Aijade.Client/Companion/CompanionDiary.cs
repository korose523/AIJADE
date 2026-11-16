using System.Globalization;

namespace Aijade.Client.Companion;

/// <summary>A saved excerpt of a stored message. Its digest covers the complete original, not just the excerpt.</summary>
public sealed record DiaryQuote(string MessageId, DateTimeOffset At, string Text, string Sha256, bool Truncated);

/// <summary>Evidence of what was said, never evidence that the narrated activity occurred in the physical world.</summary>
public sealed record CompanionDiaryEntry(string Id, string ChatId, DateOnly Day, string TimeZone, DateTimeOffset SavedAt,
    DiaryQuote User, DiaryQuote Assistant);

public sealed record CompanionDiaryDay(DateOnly Day, string TimeZone, long Revision, IReadOnlyList<CompanionDiaryEntry> Entries);

/// <summary>Optional shared notebook capability. Local-only legacy notebooks do not silently acquire shared storage.</summary>
public interface ICompanionDiary
{
    Task<CompanionDiaryDay> ReadDiaryAsync(DateOnly? day = null, CancellationToken ct = default);
    Task<CompanionDiaryDay> SaveExchangeAsync(string userMessageId, string assistantMessageId, CancellationToken ct = default);
}

public static class CompanionDiary
{
    public static bool TryDay(string text, out DateOnly day) =>
        DateOnly.TryParseExact(text, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out day);

    public static string Describe(CompanionDiaryDay diary)
    {
        var lines = new List<string> { $"共同日记 · {diary.Day:yyyy-MM-dd} · 修订 {diary.Revision}",
            "以下是主动保存的对话摘录，只说明当时说过什么，不证明现实中的活动。" };
        if (diary.Entries.Count == 0)
            lines.Add("这一天还没有保存的对话。聊完一轮后发送 /diary save，可以把那段对话加入共同日记。");
        foreach (var entry in diary.Entries.TakeLast(5))
        {
            lines.Add($"你：{Excerpt(entry.User.Text, 180)}\n我：{Excerpt(entry.Assistant.Text, 180)}\n来源：{entry.User.MessageId} / {entry.Assistant.MessageId}");
        }
        if (diary.Entries.Count > 5)
            lines.Add("这里只显示最近五段，完整摘录可以在网页的陪伴生活中查看。");
        return string.Join("\n\n", lines);
    }

    private static string Excerpt(string text, int limit)
    {
        if (text.Length <= limit) return text;
        if (char.IsHighSurrogate(text[limit - 1]) && char.IsLowSurrogate(text[limit])) limit--;
        return text[..limit] + "…";
    }
}
