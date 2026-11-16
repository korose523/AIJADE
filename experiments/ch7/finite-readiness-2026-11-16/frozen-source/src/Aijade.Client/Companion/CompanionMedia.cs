using System.Globalization;
using System.Text;

using Aijade.Client.Chat;

namespace Aijade.Client.Companion;

/// <summary>Owner media stays in their notebook; a song is available only when an actual recording exists.</summary>
public static class CompanionMedia
{
    public const int MaxBytes = 2 * 1024 * 1024;
    public static void Validate(CompanionAsset a)
    {
        ArgumentNullException.ThrowIfNull(a);
        if (string.IsNullOrWhiteSpace(a.Id) || a.Id.Length > 120 || a.Data is null || a.Description is null || a.Emotion is null || a.Attribution is null || a.Attribution.Length > 2000 ||
            a.Kind is not ("sticker" or "outfit" or "song") || string.IsNullOrWhiteSpace(a.Name) || a.Name.Length > 120 || a.Description.Length > 2000)
            throw new ArgumentException("Choose a sticker, outfit or song and a short name");
        var comma = a.Data.IndexOf(',', StringComparison.Ordinal);
        var mime = a.Kind == "song" ? new[] { "audio/wav", "audio/x-wav", "audio/mpeg", "audio/ogg", "audio/webm", "audio/mp4", "audio/x-m4a", "audio/flac" } : ["image/png", "image/jpeg", "image/webp", "image/gif"];
        if (comma < 0 || !mime.Any(m => a.Data.StartsWith("data:" + m + ";base64,", StringComparison.Ordinal)))
            throw new ArgumentException("Use a PNG/JPEG/WebP/GIF picture or a WAV/MP3/Ogg/WebM/M4A recording");
        if (a.Data.Length > 4L * MaxBytes / 3 + 150 || Convert.FromBase64String(a.Data[(comma + 1)..]).Length > MaxBytes)
            throw new ArgumentException("Media is limited to 2 MiB");
        if (a.Kind == "song" && string.IsNullOrWhiteSpace(a.Attribution))
            throw new ArgumentException("Record the source/permission for this song and voice");
        if (a.Season is not ("all" or "spring" or "summer" or "autumn" or "winter"))
            throw new ArgumentException("Unknown season");
        if (a.Kind == "sticker" && Emotion(a.Emotion) != "neutral" && !Expressions.Table.ContainsKey(Emotion(a.Emotion)))
            throw new ArgumentException("Choose an emotion from the companion's expression vocabulary");
    }

    public static string? Command(string text, string command, string chinese)
    {
        var t = text.Trim();
        if (t == command || t == chinese)
            return "";
        return t.StartsWith(command + " ", StringComparison.OrdinalIgnoreCase) ? t[(command.Length + 1)..].Trim()
            : t.StartsWith(chinese + " ", StringComparison.Ordinal) ? t[(chinese.Length + 1)..].Trim() : null;
    }

    public static CompanionAsset? Song(IReadOnlyList<CompanionAsset> assets, string title) => assets.FirstOrDefault(a => a.Kind == "song" && string.Equals(a.Name, title.Trim(), StringComparison.OrdinalIgnoreCase));
    public static CompanionAsset? Sticker(IReadOnlyList<CompanionAsset> assets, IEnumerable<string> emotions) =>
        emotions.SelectMany(e => assets.Where(a => a.Kind == "sticker" && string.Equals(Emotion(a.Emotion), Emotion(e), StringComparison.OrdinalIgnoreCase))).FirstOrDefault();

    public static string Emotion(string text) => text.Trim().ToLowerInvariant() switch
    {
        "开心" or "快乐" => "joy", "难过" or "伤心" or "sadness" => "sad", "惊讶" or "surprise" => "surprised", "害羞" => "shy",
        "生气" => "angry", "平静" or "neutral" or "普通" => "calm", "好奇" => "curious", "困" => "sleepy", "思考" => "thinking", var value => value,
    };

    public static string Season(string text) => text.Trim().ToLowerInvariant() switch
    {
        "春" or "春季" or "春天" => "spring", "夏" or "夏季" or "夏天" => "summer", "秋" or "秋季" or "秋天" => "autumn",
        "冬" or "冬季" or "冬天" => "winter", "四季" or "全年" => "all", var value => value,
    };

    public static string SongReply(CompanionAsset? song) => song is null ? "这首我还没有练好，也没有可播放的录音。可以在陪伴生活里添加自己的歌声；我不会把普通朗读当成唱歌。" : $"唱一小段《{song.Name}》给你听。";
}

public sealed record PacedMessage(string Text, TimeSpan Delay);

/// <summary>Bounded read/think/type timing; grapheme clusters stay whole and cancellation stops unsent parts.</summary>
public static class CompanionPacing
{
    public static IReadOnlyList<PacedMessage> Plan(string text, bool enabled)
    {
        if (!enabled || text.Length == 0)
            return text.Length == 0 ? [] : [new(text, TimeSpan.Zero)];
        var parts = new List<string>();
        var current = new StringBuilder();
        var elements = StringInfo.GetTextElementEnumerator(text);
        var count = 0;
        while (elements.MoveNext())
        {
            var element = elements.GetTextElement();
            current.Append(element);
            count++;
            if (count >= 80 || (count >= 18 && "。！？!?\n".Contains(element, StringComparison.Ordinal)))
            {
                parts.Add(current.ToString());
                current.Clear(); count = 0;
            }
        }
        if (current.Length > 0)
            parts.Add(current.ToString());
        // Long replies are still delivered, but never accumulate minutes of artificial waiting.
        var budget = 15_000.0;
        return parts.Select((part, i) =>
        {
            var ms = Math.Min(budget, Math.Min(2500, 250 + StringInfo.ParseCombiningCharacters(part).Length * 35) + (i == 0 ? 650 : 0));
            budget -= ms;
            return new PacedMessage(part, TimeSpan.FromMilliseconds(ms));
        }).ToList();
    }
}
