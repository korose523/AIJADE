using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;

namespace Aijade.Client.Companion;

/// <summary>
/// Reminders she promised (ADR-003, migration batch 1): AIJADE's port of MOSAIC's companion_reminders (r383), checked case by
/// case against vectors made by MOSAIC's own module (configs/companion/reminder-vectors.json). As there, the request is found
/// by fixed words and the time by fixed patterns, not by the language model, so the app knows for sure what it promised:
/// "十分钟后提醒我喝水", "半小时后叫我", "明天早上八点叫醒我", "下午3点半提醒我开会". A request without a usable time is
/// answered with a question; "取消提醒" cancels. 叫我 and 喊我 count only with a time ("你可以叫我小青" is a nickname). Times
/// are epoch seconds; clock words are read in the given time zone (the local one by default).
/// </summary>
public static partial class Reminders
{
    public static IReadOnlyList<string> Ask { get; } = ["提醒我", "提醒一下", "记得提醒", "帮我提醒", "别让我忘", "叫醒我", "叫我起床", "喊我起床"];
    public static IReadOnlyList<string> AskWithTime { get; } = ["叫我", "喊我"];
    public static IReadOnlyList<string> Query { get; } = ["提醒我什么", "提醒什么", "几点提醒", "什么时候提醒", "提醒了吗", "有什么提醒", "有没有提醒"];
    public static IReadOnlyList<string> Cancel { get; } = ["取消提醒", "不用提醒", "别提醒", "不要提醒", "提醒取消", "不用叫我", "别叫我"];
    public const double MinAheadS = 30, MaxAheadS = 7 * 86400;

    /// <summary>A reminder the app was not running for, longer ago than this, is let go, not said late.</summary>
    public const double LateS = 6 * 3600;

    /// <summary>A claim (one place saying it) older than this belongs to a process that stopped: the reminder is due again.</summary>
    public const double ClaimS = 300;

    /// <summary>The user's line of a due reminder, after which she speaks.</summary>
    public const string DueCue = "（约好的提醒时间到了）";

    private const string Number = @"\d{1,3}|[零一二两三四五六七八九十]{1,3}";

    [GeneratedRegex(@"(半|(?:" + Number + @")(?:个)?(?:半)?)(?:个)?(秒钟?|分钟?|小时|钟头)(?:以后|之后|后)")]
    private static partial Regex RelativeTime();

    [GeneratedRegex(@"(今天|今晚|明天|明早|明晚|后天)?\s*(早上|早晨|上午|中午|下午|傍晚|晚上|夜里|凌晨)?\s*(" + Number + @")\s*(?:点|时|:|：)\s*(半|一刻|三刻|(?:" + Number + @")(?:分)?)?")]
    private static partial Regex ClockTime();

    private static readonly Dictionary<char, int> Digits = new() { ['零'] = 0, ['一'] = 1, ['二'] = 2, ['两'] = 2, ['三'] = 3, ['四'] = 4, ['五'] = 5, ['六'] = 6, ['七'] = 7, ['八'] = 8, ['九'] = 9 };
    private static readonly Dictionary<string, int> UnitS = new() { ["秒"] = 1, ["秒钟"] = 1, ["分"] = 60, ["分钟"] = 60, ["小时"] = 3600, ["钟头"] = 3600 };
    private static readonly Dictionary<string, int> Day = new() { ["今天"] = 0, ["今晚"] = 0, ["明天"] = 1, ["明早"] = 1, ["明晚"] = 1, ["后天"] = 2 };
    private static readonly string[] Evening = ["下午", "傍晚", "晚上", "夜里"];

    /// <summary>An integer from digits or Chinese numerals up to 99 (十, 十五, 二十, 二十五, 两); null otherwise.</summary>
    public static int? ZhNumber(string s)
    {
        if (s.Length > 0 && s.All(char.IsDigit))
            return s.Aggregate(0, (n, c) => n * 10 + (int)char.GetNumericValue(c));
        if (s.Length == 0 || s.Any(c => !Digits.ContainsKey(c) && c != '十'))
            return null;
        if (!s.Contains('十', StringComparison.Ordinal))
            return s.Length == 1 ? Digits[s[0]] : null;
        var at = s.IndexOf('十', StringComparison.Ordinal);
        var (tens, ones) = (s[..at], s[(at + 1)..]);
        if (tens.Length > 1 || ones.Length > 1 || ones.Contains('十', StringComparison.Ordinal))
            return null;
        return (tens.Length > 0 ? Digits[tens[0]] : 1) * 10 + (ones.Length > 0 ? Digits[ones[0]] : 0);
    }

    private static DateTime Local(double epoch, TimeZoneInfo zone) => TimeZoneInfo.ConvertTime(DateTimeOffset.FromUnixTimeMilliseconds((long)Math.Round(epoch * 1000)), zone).DateTime;

    private static double Epoch(DateTime local, TimeZoneInfo zone)
    {
        var unspecified = DateTime.SpecifyKind(local, DateTimeKind.Unspecified);
        if (zone.IsInvalidTime(unspecified))
            unspecified = unspecified.AddHours(1); // a clock time skipped by a daylight-saving change
        return new DateTimeOffset(TimeZoneInfo.ConvertTimeToUtc(unspecified, zone)).ToUnixTimeMilliseconds() / 1000.0;
    }

    private static (double Due, string Words)? Relative(string text, double now)
    {
        var m = RelativeTime().Match(text);
        if (!m.Success)
            return null;
        var (amount, unit) = (m.Groups[1].Value, m.Groups[2].Value);
        double value;
        if (amount == "半")
        {
            value = .5;
        }
        else
        {
            var half = amount.EndsWith('半');
            if (ZhNumber(amount.TrimEnd('半').TrimEnd('个')) is not { } n)
                return null;
            value = n + (half ? .5 : 0);
        }
        return (now + value * UnitS[unit], m.Value);
    }

    private static (double Due, string Words)? Clock(string text, double now, TimeZoneInfo zone)
    {
        var m = ClockTime().Match(text);
        if (!m.Success)
            return null;
        var day = m.Groups[1].Success ? m.Groups[1].Value : null;
        var period = m.Groups[2].Success ? m.Groups[2].Value : null;
        var minuteWords = m.Groups[4].Success ? m.Groups[4].Value : null;
        var hour = ZhNumber(m.Groups[3].Value);
        int? minute = minuteWords switch { null => 0, "半" => 30, "一刻" => 15, "三刻" => 45, _ => ZhNumber(minuteWords.TrimEnd('分')) };
        if (hour is not { } h || minute is not { } mm || h is < 0 or > 24 || mm is < 0 or > 59)
            return null;
        if (day is "今晚" or "明晚" && period is null)
            period = "晚上";
        if (day == "明早" && period is null)
            period = "早上";
        if (period is not null && Evening.Contains(period) && h < 12)
            h += 12;
        else if (period is not null && Evening.Contains(period) && h == 12)
            h = 24; // 晚上十二点 is midnight, not noon
        else if (period == "中午" && h < 11)
            h += 12;
        var today = Local(now, zone).Date;
        double At(int days, int hours) => Epoch(today.AddDays(days).AddHours(hours).AddMinutes(mm), zone);
        if (day is not null)
            return (At(Day[day], h), m.Value);
        var candidates = new List<double> { At(0, h) };
        if (period is null && h < 12)
            candidates.Add(At(0, h + 12));
        candidates.Add(At(1, h));
        var future = candidates.Where(c => c > now + MinAheadS).ToList();
        return future.Count > 0 ? (future.Min(), m.Value) : null;
    }

    /// <summary>The due time and the words that said it, for the first time expression in the text; null for none.</summary>
    public static (double Due, string Words)? ParseWhen(string text, double now, TimeZoneInfo? zone = null) =>
        Relative(text, now) ?? Clock(text, now, zone ?? TimeZoneInfo.Local);

    /// <summary>What a message asks about reminders: set (with its due time), unclear, cancel, or null when it asks nothing.</summary>
    public static ReminderRequest? Request(string text, double now, TimeZoneInfo? zone = null)
    {
        if (Cancel.Any(w => text.Contains(w, StringComparison.Ordinal)))
            return new ReminderRequest(ReminderKind.Cancel);
        var strong = Ask.Any(w => text.Contains(w, StringComparison.Ordinal));
        if (!strong && !AskWithTime.Any(w => text.Contains(w, StringComparison.Ordinal)))
            return null;
        if (ParseWhen(text, now, zone) is { } found && found.Due - now is >= MinAheadS and <= MaxAheadS)
            return new ReminderRequest(ReminderKind.Set, found.Due, found.Words);
        if (Query.Any(w => text.Contains(w, StringComparison.Ordinal)))
            return null; // "你要提醒我什么来着": the list of pending ones answers it
        return strong ? new ReminderRequest(ReminderKind.Unclear) : null;
    }

    public static bool AsksWhatIsSet(string text) => Query.Any(w => text.Contains(w, StringComparison.Ordinal));

    /// <summary>The time as she would say it: 今天 10:15, 明天 08:00, 后天 09:30, or 10月30日 08:00.</summary>
    public static string SpokenTime(double due, double now, TimeZoneInfo? zone = null)
    {
        zone ??= TimeZoneInfo.Local;
        var (d, n) = (Local(due, zone), Local(now, zone));
        var days = Math.Round((Epoch(d.Date.AddHours(12), zone) - Epoch(n.Date.AddHours(12), zone)) / 86400, MidpointRounding.ToEven);
        var day = days switch { 0 => "今天", 1 => "明天", 2 => "后天", _ => $"{d.Month}月{d.Day}日" };
        return string.Create(CultureInfo.InvariantCulture, $"{day} {d.Hour:00}:{d.Minute:00}");
    }

    /// <summary>The note placed before the user's message for this reply.</summary>
    public static string Note(ReminderRequest found, string? when = null, int cancelled = 0) => found.Kind switch
    {
        ReminderKind.Set => $"The app has scheduled a reminder: at {when} you will remind them of what they ask here, on your own. Confirm it "
            + "in a few words and say the time; do not say you cannot set reminders.",
        ReminderKind.Unclear => "They ask you to remind them, but without a time the app can use (such as \"十分钟后\" or \"明天早上八点\"). Ask them "
            + "when, in a few words; do not promise a reminder yet.",
        _ when cancelled > 0 => $"The app has cancelled their pending reminders ({cancelled}). Tell them in a few words that you will not remind them.",
        _ => "There was no pending reminder to cancel. Tell them so in a few words.",
    };

    /// <summary>
    /// Her note when a reminder is due: why she speaks (they asked for it), in at most one short sentence. Quoting her promise
    /// keeps her from saying it again (MOSAIC found llama3.1:8b answering a due wake-up call with the promise itself).
    /// </summary>
    public static string DueNote(string said, string askedAt, string dueAt, double lateS, string promised = "")
    {
        var late = lateS > 300 ? " It is later than agreed, because the app was not running then: say you are a little late." : "";
        var earlier = promised.Length > 0 ? $" Back then you answered \"{Take(promised, 80)}\": do not say that again, the time is now." : "";
        return $"The time has come for a reminder they asked you for. At {askedAt} they said: \"{Take(said, 120)}\". The time agreed was "
            + $"{dueAt}.{earlier}{late} Tell them now, in one short sentence (at most 30 Chinese characters), that it is time to do "
            + "what they asked, as a friend reminding them, and that this is the reminder they wanted. Do not greet them, do not invent "
            + "anything else, and ask at most one question. Use the language of the conversation.";
    }

    /// <summary>The note that lists the pending reminders, for a message that asks what is set (AIJADE's wording).</summary>
    public static string PendingNote(IEnumerable<Reminder> pending, double now, TimeZoneInfo? zone = null)
    {
        var items = pending.OrderBy(r => r.Due).Take(5).Select(r => $"{SpokenTime(r.Due, now, zone)}: \"{Take(r.Said, 120)}\"").ToList();
        return items.Count == 0
            ? "You have no pending reminder for them. If they ask, say so in a few words."
            : "Reminders you have promised them and not yet given, with when and what they asked: " + string.Join("; ", items) + ".";
    }

    /// <summary>The first <paramref name="count"/> characters (code points, as Python slices them).</summary>
    private static string Take(string s, int count)
    {
        var builder = new StringBuilder();
        foreach (var rune in s.EnumerateRunes().Take(count))
            builder.Append(rune.ToString());
        return builder.ToString();
    }
}

public enum ReminderKind
{
    Set,
    Unclear,
    Cancel,
}

public sealed record ReminderRequest(ReminderKind Kind, double Due = 0, string WhenWords = "");

/// <summary>One promised reminder. Status: pending, claimed, done, missed or cancelled.</summary>
public sealed record Reminder(string Id, string Conversation, double Created, double Due, string Said, string Status, double? Claimed = null, string Promised = "");

/// <summary>
/// The reminders of one place (a device's chat, or the bridge's conversations), as MOSAIC keeps them in its database: set and
/// cancelled from messages, claimed when due so that only one caller says one, done once said, released when the line failed,
/// missed when the app was not running for more than <see cref="Reminders.LateS"/> after the time.
/// </summary>
public sealed class ReminderBook(IEnumerable<Reminder>? reminders = null)
{
    private readonly List<Reminder> items = [.. reminders ?? []];

    public IReadOnlyList<Reminder> All => items;

    /// <summary>What is worth keeping: pending and claimed reminders, and closed ones for a week.</summary>
    public IReadOnlyList<Reminder> Kept(double now) => [.. items.Where(r => r.Status is "pending" or "claimed" || r.Due > now - 7 * 86400)];

    public IEnumerable<Reminder> Pending(string conversation) => items.Where(r => r.Conversation == conversation && r.Status is "pending" or "claimed");

    /// <summary>
    /// Read a user's message: set or cancel a reminder of this conversation and return the notes for the reply (none when the
    /// message says nothing about reminders). A set reminder is returned so that her answer can be kept as its promise.
    /// </summary>
    public (IReadOnlyList<string> Notes, Reminder? Set) Read(string conversation, string text, double now, TimeZoneInfo? zone = null)
    {
        var found = Reminders.Request(text, now, zone);
        if (found is null)
            return Reminders.AsksWhatIsSet(text) ? ([Reminders.PendingNote(Pending(conversation), now, zone)], null) : ([], null);
        switch (found.Kind)
        {
            case ReminderKind.Set:
                var set = new Reminder(Guid.NewGuid().ToString("n"), conversation, now, found.Due, text, "pending");
                items.Add(set);
                return ([Reminders.Note(found, Reminders.SpokenTime(found.Due, now, zone))], set);
            case ReminderKind.Cancel:
                var cancelled = 0;
                for (var i = 0; i < items.Count; i++)
                {
                    if (items[i].Conversation == conversation && items[i].Status == "pending")
                    {
                        items[i] = items[i] with { Status = "cancelled" };
                        cancelled++;
                    }
                }
                return ([Reminders.Note(found, null, cancelled)], null);
            default:
                return ([Reminders.Note(found)], null);
        }
    }

    /// <summary>Keep her answer to a reminder she just set, so that the due line does not repeat it.</summary>
    public void Promise(string id, string answer)
    {
        var i = items.FindIndex(r => r.Id == id);
        if (i >= 0)
            items[i] = items[i] with { Promised = answer };
    }

    /// <summary>
    /// The reminder due now in one of the given conversations (null: any), claimed; stale claims are let go and reminders more
    /// than <see cref="Reminders.LateS"/> overdue become missed. Null when none is due.
    /// </summary>
    public Reminder? ClaimDue(double now, Func<string, bool>? conversations = null)
    {
        for (var i = 0; i < items.Count; i++)
        {
            if (items[i].Status == "claimed" && items[i].Claimed < now - Reminders.ClaimS)
                items[i] = items[i] with { Status = "pending", Claimed = null };
            if (items[i].Status == "pending" && items[i].Due < now - Reminders.LateS)
                items[i] = items[i] with { Status = "missed" };
        }
        var due = items.Where(r => r.Status == "pending" && r.Due <= now && (conversations is null || conversations(r.Conversation))).OrderBy(r => r.Due).FirstOrDefault();
        if (due is null)
            return null;
        var claimed = due with { Status = "claimed", Claimed = now };
        items[items.IndexOf(due)] = claimed;
        return claimed;
    }

    public void Done(string id) => Set(id, "done");

    /// <summary>Her line could not be made: the reminder is due again at the next check.</summary>
    public void Release(string id) => Set(id, "pending");

    private void Set(string id, string status)
    {
        var i = items.FindIndex(r => r.Id == id);
        if (i >= 0)
            items[i] = items[i] with { Status = status, Claimed = null };
    }
}
