using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;

using Aijade.Memory.Model;

namespace Aijade.Memory.Locomo;

/// <summary>
/// LongMemEval (Wu et al., ICLR 2025), the cleaned "_s" release, read into the LoCoMo shapes so that the memory experiments
/// run on it unchanged. Every question comes with its own haystack of sessions, so each question becomes one conversation
/// with a single question; its gold evidence is the turns the release marks with <c>has_answer</c>. The store's "now" is the
/// question date. LongMemEval is third-party data (MIT licence) and is not part of the repository.
/// </summary>
public static class LongMemEvalCorpus
{
    /// <summary>SHA-256 of longmemeval_s_cleaned.json (huggingface.co/datasets/xiaowu0162/longmemeval-cleaned).</summary>
    public const string Sha256 = "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442";

    private static readonly Regex Date = new(@"(\d{4})/(\d{2})/(\d{2})\s*\(\w+\)\s*(\d{2}):(\d{2})", RegexOptions.CultureInvariant);

    /// <summary>"2023/05/20 (Sat) 02:21" → Unix milliseconds (UTC); null when unparseable.</summary>
    public static double? ParseDate(string s)
    {
        var m = Date.Match(s);
        if (!m.Success)
            return null;
        int I(int g) => int.Parse(m.Groups[g].Value, CultureInfo.InvariantCulture);
        return (new DateTime(I(1), I(2), I(3), I(4), I(5), 0, DateTimeKind.Utc) - DateTime.UnixEpoch).TotalMilliseconds;
    }

    /// <summary>One question and its haystack as a conversation; null when the release marks no evidence turn (abstention questions).</summary>
    public static LocomoConversation? ParseQuestion(JsonElement q)
    {
        var dates = q.GetProperty("haystack_dates").EnumerateArray().Select(d => d.GetString() ?? "").ToList();
        var sessionIds = q.GetProperty("haystack_session_ids").EnumerateArray().Select(d => d.GetString() ?? "").ToList();
        var episodes = new List<Episode>();
        var evidence = new HashSet<string>(StringComparer.Ordinal);
        var s = 0;
        foreach (var session in q.GetProperty("haystack_sessions").EnumerateArray())
        {
            var sid = s < sessionIds.Count ? sessionIds[s] : $"session_{s}";
            var start = (s < dates.Count ? ParseDate(dates[s]) : null) ?? LocomoCorpus.DateUtc(2023, 0, 1) + (s * LocomoCorpus.Day);
            var j = 0;
            foreach (var turn in session.EnumerateArray())
            {
                var id = $"{s}:{sid}#{j}";   // the position keeps ids unique when a haystack repeats a session
                if (turn.TryGetProperty("has_answer", out var ha) && ha.ValueKind == JsonValueKind.True)
                    evidence.Add(id);
                episodes.Add(new Episode
                {
                    Id = id,
                    Content = turn.TryGetProperty("content", out var c) ? c.GetString() ?? "" : "",
                    CreatedAt = start + (j * 60_000),
                    LastAccessedAt = start,
                    Encoding = new Encoding(0.25, 0.15, 0.5, new Affect(0.5, 0.4, 0.5)),
                    Context = new EpisodeContext(sid, turn.TryGetProperty("role", out var r) ? r.GetString() : null, null, []),
                });
                j++;
            }
            s++;
        }
        if (evidence.Count == 0)
            return null;
        var question = new LocomoQuestion(q.GetProperty("question").GetString() ?? "",
            q.TryGetProperty("answer", out var a) ? a.ValueKind == JsonValueKind.String ? a.GetString()! : a.GetRawText() : "", [.. evidence], 0);
        var now = q.TryGetProperty("question_date", out var qd) ? ParseDate(qd.GetString() ?? "") : null;
        return new LocomoConversation(q.GetProperty("question_id").GetString()!, episodes, [question], evidence,
            now ?? (episodes.Count > 0 ? episodes.Max(e => e.CreatedAt) : 0));
    }

    /// <summary>All questions with marked evidence, in file order.</summary>
    public static IReadOnlyList<LocomoConversation> Load(string path)
    {
        using var doc = JsonDocument.Parse(File.ReadAllBytes(path));
        return [.. doc.RootElement.EnumerateArray().Select(ParseQuestion).Where(c => c is not null).Select(c => c!)];
    }
}
