using Aijade.Client.Api;

namespace Aijade.Client.Companion;

/// <summary>What the records of one local day say: how often the user spoke, what she began, and which way her mood went.</summary>
public sealed record CompanionDay(DateOnly Day, int OwnerTurns, int FirstLines, int FirstLinesAnswered, int Selfies, int Reminders, double MoodStart, double MoodEnd)
{
    /// <summary>-1 falling, 0 about the same, 1 rising.</summary>
    public int MoodTrend => MoodEnd - MoodStart > CompanionLife.TrendMargin ? 1 : MoodStart - MoodEnd > CompanionLife.TrendMargin ? -1 : 0;
}

/// <summary>
/// Her day and her mood, only from what is stored (ADR-003, third batch: MOSAIC's mosaic/life/model.py, which draws on the
/// "a whole life for her" projects: dsh-dafeiyu-life, BlueWhaleLife and dafeiyu-astrbot keep the record apart from any
/// performance and write nothing that did not happen). AIJADE's stage has no home to live in, so nothing here makes her act:
/// the chat's stored lines are the record, and a day shows only what they hold. The mood fades to its base with MOSAIC's half-life and
/// moves with MOSAIC's amounts when the user speaks and when a line she began stays unanswered; it does not enter the prompt.
/// </summary>
public static class CompanionLife
{
    public const double MoodBase = .2, MoodHalfLifeHours = 3, OwnerSpoke = .08, LeftUnanswered = -.05, TrendMargin = .05;

    /// <summary>How long a line she began waits for an answer (MOSAIC: ten minutes).</summary>
    public const double AnswerWindowSeconds = 600;

    public static double Fade(double mood, double hours) => MoodBase + ((mood - MoodBase) * Math.Pow(.5, Math.Max(0, hours) / MoodHalfLifeHours));

    /// <summary>The days the messages cover, newest first, at most <paramref name="days"/> of them.</summary>
    public static IReadOnlyList<CompanionDay> Days(IEnumerable<StoredMessage> messages, int days = 7, TimeZoneInfo? zone = null)
    {
        var ordered = messages.OrderBy(m => m.CreatedAt).ToList();
        DateOnly DayOf(DateTimeOffset t) => DateOnly.FromDateTime(TimeZoneInfo.ConvertTime(t, zone ?? TimeZoneInfo.Local).DateTime);

        // what moves the mood, in time order: the user speaking at once, an unanswered line once its wait has run out
        var moves = new List<(DateTimeOffset At, double By)>();
        for (var i = 0; i < ordered.Count; i++)
        {
            var m = ordered[i];
            if (m.Role == "user")
                moves.Add((m.CreatedAt, OwnerSpoke));
            else if (Kind(m) == LineKind.First && !Answered(ordered, i))
                moves.Add((m.CreatedAt.AddSeconds(AnswerWindowSeconds), LeftUnanswered));
        }
        moves.Sort((a, b) => a.At.CompareTo(b.At));

        var result = new List<CompanionDay>();
        foreach (var group in ordered.Select((m, i) => (m, i)).GroupBy(x => DayOf(x.m.CreatedAt)))
        {
            var first = group.First().m.CreatedAt;
            var last = group.Last().m.CreatedAt;
            var firstLines = group.Where(x => Kind(x.m) == LineKind.First).ToList();
            result.Add(new CompanionDay(group.Key, group.Count(x => x.m.Role == "user"), firstLines.Count, firstLines.Count(x => Answered(ordered, x.i)),
                group.Count(x => Kind(x.m) == LineKind.Selfie), group.Count(x => Kind(x.m) == LineKind.Reminder), MoodAt(moves, first), MoodAt(moves, last.AddTicks(1))));
        }
        return [.. result.OrderByDescending(d => d.Day).Take(days)];
    }

    private static double MoodAt(List<(DateTimeOffset At, double By)> moves, DateTimeOffset when)
    {
        var mood = MoodBase;
        DateTimeOffset? at = null;
        foreach (var (time, by) in moves.Where(x => x.At < when))
        {
            mood = Math.Clamp(Fade(mood, at is { } previous ? (time - previous).TotalHours : 0) + by, -1, 1);
            at = time;
        }
        return at is { } lastMove ? Fade(mood, (when - lastMove).TotalHours) : mood;
    }

    private static bool Answered(List<StoredMessage> ordered, int index)
    {
        var deadline = ordered[index].CreatedAt.AddSeconds(AnswerWindowSeconds);
        for (var j = index + 1; j < ordered.Count && ordered[j].CreatedAt <= deadline; j++)
        {
            if (ordered[j].Role == "user")
                return true;
        }
        return false;
    }

    private enum LineKind
    {
        None,
        First,
        Selfie,
        Reminder,
    }

    private static LineKind Kind(StoredMessage m) =>
        m.Role != "assistant" ? LineKind.None
        : Selfies.IsSelfie(m) ? LineKind.Selfie
        : m.Meta?["reminder"] is not null ? LineKind.Reminder
        : Initiative.IsProactive(m) ? LineKind.First
        : LineKind.None;

    /// <summary>
    /// One step of a page's minute loop: whatever goes wrong in it is reported and the loop goes on, so that one failed check does
    /// not end the reminders and her first lines until the page is reloaded. The page being closed still ends the loop.
    /// </summary>
    public static async Task MinuteStepAsync(Func<Task> step, Action<Exception> report)
    {
        try
        {
            await step().ConfigureAwait(false);
        }
#pragma warning disable CA1031 // the loop must outlive any failure of one step; it is reported
        catch (Exception e) when (e is not ObjectDisposedException)
        {
            report(e);
        }
#pragma warning restore CA1031
    }
}
