using System.Text.RegularExpressions;

namespace Aijade.Client.Companion;

/// <summary>What her body does after a reply on MOSAIC's home stage.</summary>
public enum StageActionKind
{
    /// <summary>Walk to a spot in her home and sit, lie or stand there; the argument is the word that named it (沙发, 睡觉…).</summary>
    Place,

    /// <summary>Stand up from sitting or lying.</summary>
    Stand,

    /// <summary>Walk on the spot; the argument is MOSAIC's walk script or goal token (<c>@approach</c>, <c>原地左转 6.3 停 1</c>…).</summary>
    Walk,

    /// <summary>Dance one dance from MOSAIC's dance library.</summary>
    Dance,

    /// <summary>A gesture; the argument is MOSAIC's gesture id (bow, bye, byebye, guide, call, respond, groom).</summary>
    Gesture,
}

/// <summary>The decided action, and in a few words what she will do, for the note before the reply.</summary>
public sealed record StageAction(StageActionKind Kind, string? Argument, string Doing);

/// <summary>A spot in her home (MOSAIC's mosaic-home-v1 layout): name, label, what she does there, room and other words for it.</summary>
public sealed record StageSpot(string Name, string Label, string Activity, string Room, IReadOnlyList<string> Aliases);

/// <summary>
/// The stage rules of the companion contract (<c>configs/companion/contract.json</c>, 1.3.0; docs/STAGE-MOSAIC.md, plan A
/// step 1): as MOSAIC's live-scene workbench does it, fixed words in the user's message, not the model, decide what her body
/// does after the reply (a spot in her home, else a walk, else a dance, else a gesture; a negation, or the speaker going
/// themselves, means none), and the model is told before it replies. Held to the vectors from a compiled copy of MOSAIC's
/// LiveSceneCommands. Not wired to any surface yet.
/// </summary>
public static class Stage
{
    /// <summary>The note before a reply after which the app moves her; <c>{doing}</c> says what (去沙发坐下, 鞠躬…).</summary>
    public const string ActionNoteTemplate =
        "Right after this reply the app will make your body do this, because they asked: {doing}. " +
        "Agree in a few warm words and never say you cannot.";

    /// <summary>The note before a reply after which the app does not move her.</summary>
    public const string NoActionNote = "The app will not move your body after this reply, so do not promise to move.";

    /// <summary>The note on where she is, when the app knows; <c>{where}</c> as MOSAIC says it (在客厅，沙发，坐着).</summary>
    public const string WhereNoteTemplate =
        "Where your body is in your home and what it is doing, from the app: {where}. " +
        "Say it if they ask where you are or what you are doing, and never invent another place or activity.";

    /// <summary>MOSAIC's token for standing up.</summary>
    public const string StandUp = "@up";

    /// <summary>The spots of MOSAIC's home layout (configs/scenes/home-v1.json, mosaic-home-v1).</summary>
    public static IReadOnlyList<StageSpot> Spots { get; } =
    [
        new("sofa", "沙发", "sit", "living", ["沙发", "客厅"]),
        new("tv", "沙发上看电视", "sit", "living", ["电视", "看电视"]),
        new("piano", "钢琴前", "sit", "living", ["钢琴", "弹琴", "弹钢琴"]),
        new("bed", "床上", "lie", "bedroom", ["床", "卧室", "睡觉", "躺"]),
        new("desk", "书桌前", "sit", "bedroom", ["书桌", "学习"]),
        new("dining", "餐桌边", "sit", "kitchen", ["餐桌", "吃饭", "餐厅"]),
        new("kitchen", "灶台前", "stand", "kitchen", ["厨房", "做饭", "灶台"]),
        new("pool", "泳池边", "stand", "yard", ["泳池", "游泳"]),
        new("court", "篮球场", "stand", "yard", ["篮球", "打球", "球场"]),
        new("deck", "运动木台", "stand", "yard", ["运动", "跳舞的地方", "木台", "院子"]),
    ];

    /// <summary>The words for the spots, as MOSAIC lists them: each label, then its aliases, each word once.</summary>
    public static IReadOnlyList<string> PlaceWords { get; } =
        [.. Spots.SelectMany(s => s.Aliases.Prepend(s.Label)).Where(w => w.Length > 0).Distinct(StringComparer.Ordinal)];

    public static IReadOnlyList<string> Negations { get; } = ["不要", "别", "不用", "不许", "don't", "do not", "dont"];

    /// <summary>The speaker going themselves (我去睡觉了): not asking her to go.</summary>
    public static IReadOnlyList<string> SelfGoing { get; } = ["我去", "我要去", "我先去", "我得去", "我该去", "我也去", "我想去"];

    public static IReadOnlyList<string> GoWords { get; } = ["去", "到", "回", "坐到", "躺到"];

    /// <summary>Asking her along or telling her to (我们看电视吧, 陪我弹琴, 该睡觉了).</summary>
    public static IReadOnlyList<string> Invitations { get; } = ["一起", "陪我", "我们", "咱们", "你去", "快去", "该"];

    public static IReadOnlyList<string> StandUpWords { get; } = ["起来", "站起来", "起床", "stand", "stand up", "get up"];

    public static IReadOnlyList<(string[] Keywords, string Script)> Movements { get; } =
    [
        (["转一圈", "转个圈", "spin"], "原地左转 6.3 停 1"),
        (["转过身", "转身", "turn around"], "原地左转 3.15 停 1"),
        (["走过来", "过来", "到我这", "靠近", "come here", "come closer"], "@approach"),
        (["退后", "后退", "往后", "step back"], "@back"),
        (["走开", "离远", "back off", "go away"], "@away"),
        (["走一走", "走两步", "散步", "walk around"], "@stroll"),
    ];

    public static IReadOnlyList<string> DanceKeywords { get; } =
        ["跳舞", "跳个舞", "跳支舞", "跳一支舞", "跳段舞", "跳一段舞", "来段舞", "来支舞", "跳一下", "跳一个", "跳一曲", "来一段", "dance"];

    /// <summary>Gestures the user asks for.</summary>
    public static IReadOnlyList<(string[] Keywords, string Gesture)> Gestures { get; } =
    [
        (["鞠躬", "鞠个躬", "bow"], "bow"),
        (["挥挥手", "挥手", "招招手", "wave"], "bye"),
        (["打招呼", "打个招呼", "say hi"], "call"),
        (["带路", "指路", "show me the way"], "guide"),
        (["举手", "举个手", "raise your hand"], "respond"),
        (["理头发", "理理头发", "拢头发", "整理头发", "fix your hair"], "groom"),
    ];

    /// <summary>Answers to what they say without asking: a farewell, then thanks (a greeting is <see cref="Greeting"/>).</summary>
    public static IReadOnlyList<(string[] Keywords, string Gesture)> SituationalGestures { get; } =
    [
        (["再见", "拜拜", "回头见", "goodbye", "bye"], "byebye"),
        (["谢谢", "多谢", "感谢", "thank"], "bow"),
    ];

    /// <summary>A greeting on word boundaries (你好 but not 你好像), answered with a wave.</summary>
    public static Regex Greeting { get; } = new(
        @"(^|[\s，。！？、,.!?~～])(你好|您好|早上好|早安|中午好|下午好|晚上好|嗨)(?=$|[\s，。！？、,.!?~～呀啊哦吗])|\b(hello|hi|hey|good (morning|afternoon|evening))\b",
        RegexOptions.CultureInvariant);

    /// <summary>In a few words what a walk, a dance or a gesture is, for the note (AIJADE's wording; MOSAIC tells its model only the kind).</summary>
    public static IReadOnlyDictionary<string, string> Doings { get; } = new Dictionary<string, string>(StringComparer.Ordinal)
    {
        ["原地左转 6.3 停 1"] = "转一圈", ["原地左转 3.15 停 1"] = "转过身", ["@approach"] = "走过来", ["@back"] = "往后退一点",
        ["@away"] = "走开", ["@stroll"] = "走一走", ["dance"] = "跳一支舞", ["bow"] = "鞠躬", ["bye"] = "挥手",
        ["byebye"] = "挥手告别", ["call"] = "打招呼", ["guide"] = "带路", ["respond"] = "举手", ["groom"] = "理理头发",
    };

    private static bool Negated(string t) => Negations.Any(n => t.Contains(n, StringComparison.Ordinal));

    /// <summary>
    /// A spot in her home the message sends her to, by the word that named it, or <see cref="StandUp"/> when it only says to
    /// get up, else null: the word after a go-word (去沙发), or a word of two or more characters with an invitation (我们看电视吧).
    /// Longer words first. None when the message has a negation or the speaker is going themselves.
    /// </summary>
    public static string? Place(string text)
    {
        var t = text.ToLowerInvariant();
        if (Negated(t) || SelfGoing.Any(n => t.Contains(n, StringComparison.Ordinal)))
            return null;
        foreach (var place in PlaceWords.OrderByDescending(p => p.Length))
        {
            if (GoWords.Any(g => t.Contains(g + place, StringComparison.Ordinal)))
                return place;
            if (place.Length >= 2 && t.Contains(place, StringComparison.Ordinal) && Invitations.Any(i => t.Contains(i, StringComparison.Ordinal)))
                return place;
        }
        return StandUpWords.Any(w => t.Contains(w, StringComparison.Ordinal)) ? StandUp : null;
    }

    /// <summary>The walk the message asks for (MOSAIC's script or goal token), or null; none under a negation.</summary>
    public static string? Movement(string text)
    {
        var t = text.ToLowerInvariant();
        return Negated(t) ? null : Movements.FirstOrDefault(m => m.Keywords.Any(k => t.Contains(k, StringComparison.Ordinal))).Script;
    }

    /// <summary>Whether the message asks her to dance; not under a negation.</summary>
    public static bool Dance(string text)
    {
        var t = text.ToLowerInvariant();
        return !Negated(t) && DanceKeywords.Any(k => t.Contains(k, StringComparison.Ordinal));
    }

    /// <summary>The gesture the message asks for, or, when <paramref name="situational"/>, answers (a farewell, thanks, a greeting); else null.</summary>
    public static string? Gesture(string text, bool situational = true)
    {
        var t = text.ToLowerInvariant();
        if (Negated(t))
            return null;
        foreach (var (keywords, gesture) in situational ? Gestures.Concat(SituationalGestures) : Gestures)
        {
            if (keywords.Any(k => t.Contains(k, StringComparison.Ordinal)))
                return gesture;
        }
        return situational && Greeting.IsMatch(t) ? "bye" : null;
    }

    /// <summary>What she goes to a spot to do, as MOSAIC tells its model: 去 + label, then 坐下 or 躺下休息 by the spot.</summary>
    public static string? PlaceDoing(string word)
    {
        var spot = Spots.FirstOrDefault(s => s.Label == word || s.Aliases.Contains(word, StringComparer.Ordinal));
        return spot is null ? null : "去" + spot.Label + spot.Activity switch { "sit" => "坐下", "lie" => "躺下休息", _ => "" };
    }

    /// <summary>
    /// What her body does after the reply, in MOSAIC's order: a spot (standing up only when she <paramref name="seated"/> sits
    /// or lies), else a walk, else a dance, else a gesture, situational ones included as when MOSAIC's model does not choose
    /// actions; null when the message asks for none.
    /// </summary>
    public static StageAction? Decide(string text, bool seated)
    {
        var place = Place(text);
        if (place == StandUp)
            return seated ? new StageAction(StageActionKind.Stand, null, "站起来") : null;
        if (place is not null)
            return new StageAction(StageActionKind.Place, place, PlaceDoing(place)!);
        if (Movement(text) is { } walk)
            return new StageAction(StageActionKind.Walk, walk, Doings[walk]);
        if (Dance(text))
            return new StageAction(StageActionKind.Dance, null, Doings["dance"]);
        return Gesture(text) is { } gesture ? new StageAction(StageActionKind.Gesture, gesture, Doings[gesture]) : null;
    }

    public static string ActionNote(StageAction action) => ActionNoteTemplate.Replace("{doing}", action.Doing, StringComparison.Ordinal);

    public static string WhereNote(string where) => WhereNoteTemplate.Replace("{where}", where, StringComparison.Ordinal);

    /// <summary>The notes before the user's message on the stage: the action note or the no-action note, then where she is when known.</summary>
    public static IReadOnlyList<string> Notes(StageAction? action, string? where)
    {
        var note = action is null ? NoActionNote : ActionNote(action);
        return where is { Length: > 0 } ? [note, WhereNote(where)] : [note];
    }
}
