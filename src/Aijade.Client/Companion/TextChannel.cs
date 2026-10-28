namespace Aijade.Client.Companion;

/// <summary>
/// Rules for a chat channel where she has no body (text messages on Discord, Telegram, X or a platform relayed by Satori),
/// from the companion contract (<c>configs/companion/contract.json</c>, 1.2.0) as MOSAIC tested them over QQ on llama3.1:8b:
/// a note before each message that she cannot move there, a second note when the message asks for a movement, and, when her
/// reply still does not put the movement off, a sentence that does. Held to the vectors read from MOSAIC's QQ bridge.
/// </summary>
public static class TextChannel
{
    /// <summary>The note before each message; <c>{medium}</c> names the channel ("Telegram text messages").</summary>
    public const string ChannelNoteTemplate =
        "This conversation is {medium}, not the live scene: here you have no body and cannot move, dance, walk or make gestures. " +
        "If they ask for one, say kindly that you can do it when they are at the screen.";

    /// <summary>The note added when the message asks for a movement; <c>{channel}</c> names the channel ("Telegram").</summary>
    public const string MovementNoteTemplate =
        "They ask you to move, and over {channel} you cannot. Do not agree to do it now and do not describe doing it; say kindly, " +
        "in a few words, that you will do it for them when they are back at the screen.";

    /// <summary>The sentence added to a reply that does not put a movement off.</summary>
    public const string Later = "等你回到屏幕前，我再做给你看。";

    /// <summary>Words that ask for a movement (a hug in words, 抱抱, is fine in a text chat and is not here).</summary>
    public static IReadOnlyList<string> MovementWords { get; } =
        ["跳舞", "跳个舞", "跳支舞", "跳一段", "跳一支", "来一段舞", "鞠躬", "鞠个躬", "挥手", "挥挥手", "转一圈", "转个圈", "散步", "走一走", "点头", "比心", "动一动"];

    /// <summary>Words that show a reply already puts the movement off.</summary>
    public static IReadOnlyList<string> PutOffWords { get; } = ["屏幕", "等你", "回来", "回到", "不能", "没法", "没办法", "做不到", "下次"];

    public static string ChannelNote(string medium) => ChannelNoteTemplate.Replace("{medium}", medium, StringComparison.Ordinal);

    public static string MovementNote(string channel) => MovementNoteTemplate.Replace("{channel}", channel, StringComparison.Ordinal);

    public static bool AsksToMove(string text) => MovementWords.Any(w => text.Contains(w, StringComparison.Ordinal));

    /// <summary>The notes that go just before the user's message: the channel note, and the movement note when it asks for one.</summary>
    public static IReadOnlyList<string> Notes(string channel, string text) =>
        AsksToMove(text) ? [ChannelNote($"{channel} text messages"), MovementNote(channel)] : [ChannelNote($"{channel} text messages")];

    /// <summary>
    /// The reply as sent: when the message asked for a movement and the reply has no word that puts it off, the reply ends
    /// its sentence and gets <see cref="Later"/>. The stored reply is not changed, as in MOSAIC.
    /// </summary>
    public static string PutOff(string text, string reply)
    {
        if (!AsksToMove(text) || PutOffWords.Any(w => reply.Contains(w, StringComparison.Ordinal)))
            return reply;
        var trimmed = reply.TrimEnd();
        var ended = trimmed.Length > 0 && "。！!？?~".Contains(trimmed[^1], StringComparison.Ordinal);
        return trimmed + (ended ? "" : "。") + Later;
    }

    /// <summary>
    /// The channel's name for the notes on a platform where she has no body, or null where she may have one (a live stage on
    /// Bilibili, an avatar in Minecraft). Platforms relayed by Satori are named by the platform behind it.
    /// </summary>
    public static string? BodilessChannel(string platform) => platform switch
    {
        "discord" => "Discord",
        "telegram" => "Telegram",
        "x" => "X",
        _ when platform.StartsWith("satori-", StringComparison.Ordinal) => platform["satori-".Length..] switch
        {
            "qq" => "QQ",
            "kook" => "KOOK",
            "" => "chat",
            var p => char.ToUpperInvariant(p[0]) + p[1..],
        },
        _ => null,
    };
}
