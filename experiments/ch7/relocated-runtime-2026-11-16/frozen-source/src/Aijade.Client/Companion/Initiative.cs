using System.Globalization;
using System.Text;

using Aijade.Client.Api;

namespace Aijade.Client.Companion;

/// <summary>One turn of a user's conversation: something the user said, or a line the companion began herself.</summary>
/// <param name="Created">When the turn was recorded, in seconds on any clock shared with <c>now</c>.</param>
/// <param name="Input">What the user said (empty for her own first lines).</param>
/// <param name="Proactive">A line she began herself, with no user input.</param>
public sealed record InitiativeTurn(double Created, string? Input, bool Proactive);

/// <summary>The weights of the opportunity score.</summary>
public sealed record InitiativeWeights(double Relevance, double Novelty, double Social, double Context, double Interrupt, double Frequency);

/// <summary>Gates, timing and weights of <see cref="Initiative"/>; <see cref="Default"/> holds the shared contract's values.</summary>
public sealed record InitiativeParams(double QuietMinS, double QuietFullS, double CooldownS, int PerHour, double HushS, double RecentS,
    int NightStart, int NightEnd, double Threshold, InitiativeWeights Weights)
{
    /// <summary>The values of <c>configs/companion/contract.json</c> (initiative.params).</summary>
    public static InitiativeParams Default { get; } = new(QuietMinS: 180, QuietFullS: 600, CooldownS: 480, PerHour: 3, HushS: 7200,
        RecentS: 7200, NightStart: 0, NightEnd: 7, Threshold: 0.75, new InitiativeWeights(Relevance: 0.35, Novelty: 0.15, Social: 0.35,
        Context: 0.15, Interrupt: 0.6, Frequency: 0.4));
}

/// <summary>
/// Whether she speaks first, the score and its parts, the reason, the user's last message worth following up, and how long it
/// has been quiet (seconds since the newest turn).
/// </summary>
public sealed record InitiativeDecision(bool Speak, double? Score, IReadOnlyDictionary<string, double> Parts, string Reason, string? FollowUp,
    double? QuietS = null);

/// <summary>One exchange of a chat: a user message and the reply to it, or a line she began herself (<see cref="User"/> null).</summary>
public sealed record InitiativeExchange(StoredMessage? User, StoredMessage Reply, DateTimeOffset Last);

/// <summary>
/// When the companion speaks first: an opportunity score, not a random timer, behind fixed gates (night, a request for quiet,
/// leaving words, unanswered lines, quiet, cooldown, an hourly budget). This is the rule of the shared companion contract
/// (<c>configs/companion/contract.json</c>, <c>docs/COMPANION-CONTRACT.md</c>), held to the vectors generated from MOSAIC's
/// implementation. The chat page asks it once a minute when the setting to speak first is on
/// (<see cref="Chat.ChatOrchestrator.SpeakFirstAsync"/>).
/// </summary>
public static class Initiative
{
    /// <summary>Words that mean the user is leaving or busy (matched in the lower-cased message).</summary>
    public static IReadOnlyList<string> Leaving { get; } =
    [
        "晚安", "再见", "拜拜", "回头见", "待会聊", "待会儿聊", "先走", "去睡", "睡了", "睡觉", "去忙", "忙了", "开会", "上课", "上班了",
        "下线", "出门", "去洗澡", "去吃饭", "去做饭", "good night", "bye", "gotta go", "brb", "talk later",
    ];

    /// <summary>Words that ask her to be quiet (matched in the lower-cased message).</summary>
    public static IReadOnlyList<string> Hush { get; } =
        ["安静点", "安静一点", "别吵", "别说话", "别打扰", "不要打扰", "让我静静", "闭嘴", "be quiet", "shut up", "leave me alone"];

    /// <summary>How many of the latest exchanges go with her first line, as in MOSAIC.</summary>
    public const int HistoryWindow = 4;

    /// <summary>The meta flag of a message she began herself.</summary>
    public const string ProactiveMeta = "proactive";

    /// <summary>Whether a stored message is a line she began herself.</summary>
    public static bool IsProactive(StoredMessage m) =>
        m.Role == "assistant" && m.Meta?[ProactiveMeta] is { } flag && flag.GetValueKind() == System.Text.Json.JsonValueKind.True;

    /// <summary>
    /// A chat (oldest first) as exchanges, oldest first: a user message with the reply that followed it, or a line she began
    /// herself. A further assistant message right after a reply (a picture) belongs to that exchange and dates it. A user
    /// message without a reply is left out, as MOSAIC leaves out turns that were not answered.
    /// </summary>
    public static IReadOnlyList<InitiativeExchange> Exchanges(IReadOnlyList<StoredMessage> history)
    {
        var exchanges = new List<InitiativeExchange>();
        StoredMessage? user = null;
        foreach (var m in history)
        {
            if (m.Role == "user")
            {
                user = m;
            }
            else if (m.Role == "assistant" && (IsProactive(m) || user is not null))
            {
                exchanges.Add(new InitiativeExchange(IsProactive(m) ? null : user, m, m.CreatedAt));
                user = null;
            }
            else if (m.Role == "assistant" && exchanges.Count > 0 && exchanges[^1].User is not null)
            {
                exchanges[^1] = exchanges[^1] with { Last = m.CreatedAt };
            }
        }
        return exchanges;
    }

    /// <summary>The exchanges as initiative turns, newest first, dated by their last message in seconds.</summary>
    public static IReadOnlyList<InitiativeTurn> Turns(IReadOnlyList<InitiativeExchange> exchanges) =>
        [.. exchanges.Reverse().Select(x => new InitiativeTurn(x.Last.ToUnixTimeMilliseconds() / 1000.0, x.User?.Content ?? "", x.User is null))];

    /// <summary>
    /// The instruction for her first line: one new short sentence, a follow-up on what they said or one easy question, nothing
    /// invented. Quoting her last reply keeps the model from repeating it. Word for word the contract's note (MOSAIC's
    /// proactive_note), held to its vectors.
    /// </summary>
    public static string Note(double quietS, string? followUp, string lastReply)
    {
        var topic = followUp is { Length: > 0 }
            ? $"Follow up on what they told you last (\"{Prefix(followUp, 80)}\") with one easy question about it; if it was worrying or " +
              "sad, ask gently how they, or the person they spoke of, are doing now."
            : "Ask one light, easy question about their day or a small preference, or say one warm short line.";
        return $"You speak first now: the user has not said anything for about {Minutes(quietS)} minutes. Say one new short sentence (at most " +
               $"30 Chinese characters). {topic} Your last reply was \"{Prefix(lastReply, 60)}\": say something different, not that again. " +
               "Do not invent anything you did, saw or heard: you have no senses and no life outside this conversation. Do not greet " +
               "them as if they had just arrived, and ask at most one question. Use the language of the conversation.";
    }

    /// <summary>The quiet itself, as the user's turn that her line answers (the contract's silence line).</summary>
    public static string Silence(double quietS) => $"（{Minutes(quietS)} 分钟没有说话）";

    /// <summary>Whole minutes, at least one, rounded half to even as the contract's reference does.</summary>
    private static string Minutes(double quietS) =>
        Math.Max(1, Math.Round(quietS / 60, MidpointRounding.ToEven)).ToString(CultureInfo.InvariantCulture);

    /// <summary>The first <paramref name="count"/> characters, counted in code points.</summary>
    private static string Prefix(string text, int count)
    {
        var b = new StringBuilder();
        foreach (var r in text.EnumerateRunes().Take(count))
            b.Append(r.ToString());
        return b.ToString();
    }

    /// <param name="turns">The user's turns, newest first.</param>
    /// <param name="now">The current time on the clock of <see cref="InitiativeTurn.Created"/>.</param>
    /// <param name="hour">The user's local hour, 0 to 23.</param>
    /// <param name="p">Gates and weights; the contract's values when null.</param>
    public static InitiativeDecision Decide(IReadOnlyList<InitiativeTurn> turns, double now, int hour, InitiativeParams? p = null)
    {
        p ??= InitiativeParams.Default;
        var said = turns.Where(t => !t.Proactive).ToList();
        if (said.Count == 0)
            return new(false, null, new Dictionary<string, double>(), "they have not said anything yet", null);
        var last = said[0];
        var quiet = now - turns[0].Created;
        var text = (last.Input ?? "").ToLowerInvariant();
        var mine = turns.Where(t => t.Proactive).ToList();
        var ignored = turns.TakeWhile(t => t.Proactive).Count();
        var thisHour = mine.Count(t => now - t.Created < 3600);
        var doubled = ignored > 0 ? 2 : 1;

        string? gate = null;
        if (p.NightStart <= hour && hour < p.NightEnd)
            gate = "night hours";
        else if (Hush.Any(text.Contains) && now - last.Created < p.HushS)
            gate = "they asked for quiet";
        else if (Leaving.Any(text.Contains))
            gate = "their last words were leaving or busy";
        else if (ignored >= 2)
            gate = "two of her lines went unanswered: waiting for them";
        else if (quiet < p.QuietMinS * doubled)
            gate = "not quiet long enough";
        else if (mine.Count > 0 && now - mine[0].Created < p.CooldownS * doubled)
            gate = "she spoke first recently";
        else if (thisHour >= p.PerHour)
            gate = "hourly budget used";

        // Length in code points, as the contract counts characters.
        var worth = (last.Input ?? "").Trim().EnumerateRunes().Count() >= 4 && now - last.Created < p.RecentS;
        var parts = new Dictionary<string, double>(StringComparer.Ordinal)
        {
            ["relevance"] = worth ? 1 : 0.3,
            ["novelty"] = ignored > 0 ? 0 : 1,
            ["social"] = Math.Min(1, Math.Max(0, (quiet - p.QuietMinS) / (p.QuietFullS - p.QuietMinS))),
            ["context"] = 1,
            ["interrupt"] = 0,
            ["frequency"] = (double)thisHour / p.PerHour,
        };
        var w = p.Weights;
        var score = w.Relevance * parts["relevance"] + w.Novelty * parts["novelty"] + w.Social * parts["social"] + w.Context * parts["context"]
                    - w.Interrupt * parts["interrupt"] - w.Frequency * parts["frequency"];
        var speak = gate is null && score >= p.Threshold;
        return new(speak, score, parts, gate ?? (speak ? "opportunity" : "score below threshold"), worth ? last.Input : null, quiet);
    }
}
