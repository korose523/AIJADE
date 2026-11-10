using System.Text;
using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Companion;
using Aijade.Memory.Contracts;
using Aijade.Memory.Development;

namespace Aijade.Client.Chat;

/// <summary>Lifts [[emote:name]] markers out of streamed text, including markers split across chunks.</summary>
/// <summary>An inline instruction from the model, e.g. [[emote:joy]] or [[draw: a cat on a windowsill]].</summary>
public sealed record Marker(string Kind, string Value);

/// <summary>
/// Lifts [[kind:value]] markers of the given kinds out of streamed text, even when a marker is split across chunks. Text that
/// merely looks similar ([[not a marker]]) stays visible. Emote values are case-folded; other values keep their case.
/// </summary>
public sealed class MarkerParser(params string[] kinds)
{
    private readonly string[] opens = [.. kinds.Select(k => $"[[{k}:")];
    private readonly StringBuilder pending = new();

    /// <summary>Feed a chunk; returns the visible text and any complete markers.</summary>
    public (string Text, IReadOnlyList<Marker> Markers) Feed(string chunk)
    {
        pending.Append(chunk);
        var s = pending.ToString();
        var visible = new StringBuilder();
        var markers = new List<Marker>();
        var i = 0;
        while (i < s.Length)
        {
            var start = s.IndexOf("[[", i, StringComparison.Ordinal);
            if (start < 0)
            {
                // Keep a trailing '[' that could begin a marker in the next chunk.
                var keep = s.EndsWith('[') ? 1 : 0;
                visible.Append(s, i, s.Length - i - keep);
                i = s.Length - keep;
                break;
            }
            visible.Append(s, i, start - i);
            var rest = s[start..];
            var open = opens.FirstOrDefault(o => rest.StartsWith(o, StringComparison.Ordinal));
            if (open is null)
            {
                if (opens.Any(o => rest.Length < o.Length && o.StartsWith(rest, StringComparison.Ordinal)))
                {
                    i = start; // could still become a marker: wait for more text
                    break;
                }
                visible.Append("[[");
                i = start + 2;
                continue;
            }
            var end = s.IndexOf("]]", start, StringComparison.Ordinal);
            if (end < 0)
            {
                i = start; // incomplete marker: wait for more text
                break;
            }
            var kind = open[2..^1];
            var value = s[(start + open.Length)..end].Trim();
            if (value.Length > 0)
                markers.Add(new Marker(kind, kind == "emote" ? value.ToLowerInvariant() : value));
            i = end + 2;
        }
        pending.Clear();
        if (i < s.Length)
            pending.Append(s, i, s.Length - i);
        return (visible.ToString(), markers);
    }

    /// <summary>Whatever is left at the end of the stream is plain text.</summary>
    public string Flush()
    {
        var rest = pending.ToString();
        pending.Clear();
        return rest;
    }
}

/// <summary>Expression markers only (the stage's vocabulary).</summary>
public sealed class ExpressionMarkerParser
{
    private readonly MarkerParser inner = new("emote");

    public (string Text, IReadOnlyList<string> Markers) Feed(string chunk)
    {
        var (text, markers) = inner.Feed(chunk);
        return (text, [.. markers.Select(m => m.Value)]);
    }

    public string Flush() => inner.Flush();
}

/// <summary>Drawing ("artistry"): the model asks for a picture with a marker; the client has the server draw it.</summary>
public static class Artistry
{
    /// <summary>The image a stored message carries (meta.image), or null for an ordinary message.</summary>
    public static ImageInfo? ImageOf(StoredMessage m) =>
        m.Meta?["image"] is JsonObject i && i["id"]?.GetValue<string>() is { } id
            ? new ImageInfo(id, $"/api/v1/images/{id}", i["mime"]?.GetValue<string>() ?? "image/png", i["prompt"]?.GetValue<string>() ?? m.Content)
            : null;

    /// <summary>
    /// Draw what the model asked for and add the picture to the chat as an assistant message (content = the prompt, which
    /// doubles as alt text; meta.image = the stored image). Failures surface as <see cref="AijadeApiException"/>.
    /// </summary>
    public static async Task<StoredMessage> DrawIntoChatAsync(AijadeApi api, string chatId, string prompt, CancellationToken ct = default)
    {
        var image = await api.GenerateImageAsync(prompt, ct: ct).ConfigureAwait(false);
        return await api.AppendMessageAsync(chatId, "assistant", image.Prompt,
            new JsonObject { ["image"] = new JsonObject { ["id"] = image.Id, ["mime"] = image.Mime, ["prompt"] = image.Prompt } }, ct).ConfigureAwait(false);
    }

    public const int MaxDrawingsPerReply = 1;

    public static string Instruction =>
        "You can draw a picture for the user: write [[draw: a detailed visual description in English]] where it fits, at most once per reply, " +
        "only when a picture genuinely helps or the user asks for one. The marker is replaced by the picture.";
}

public static class Expressions
{
    /// <summary>The expression names the model is told it may use, with their effect on the PEF expression vector.</summary>
    public static IReadOnlyDictionary<string, PartialExpression> Table { get; } = new Dictionary<string, PartialExpression>(StringComparer.Ordinal)
    {
        ["joy"] = new(Valence: 0.7, Arousal: 0.6, Playfulness: 0.6),
        ["calm"] = new(Valence: 0.2, Arousal: 0.2),
        ["sad"] = new(Valence: -0.6, Arousal: 0.3),
        ["angry"] = new(Valence: -0.6, Arousal: 0.85, Dominance: 0.75),
        ["surprised"] = new(Valence: 0.2, Arousal: 0.9, Curiosity: 0.7),
        ["curious"] = new(Curiosity: 0.85, Arousal: 0.55),
        ["shy"] = new(Intimacy: 0.7, Dominance: 0.2, Valence: 0.3),
        ["thinking"] = new(Reflection: 0.85, Arousal: 0.3),
        ["sleepy"] = new(Arousal: 0.1, Valence: 0.1),
    };

    public static string Instruction =>
        $"You may express emotion by writing a marker such as [[emote:joy]] at the point where it applies. Available: {string.Join(", ", Table.Keys)}. Markers are not shown to the user.";

    /// <summary>The dialogue act of a reply, inferred from its text.</summary>
    public static DialogueAct InferAct(string text)
    {
        var t = text.Trim();
        if (t.Length == 0)
            return DialogueAct.Backchannel;
        if (t.EndsWith('?') || t.EndsWith('？'))
            return DialogueAct.Question;
        if (t.Contains('!', StringComparison.Ordinal) || t.Contains('！', StringComparison.Ordinal))
            return DialogueAct.Celebrate;
        var lower = t.ToLowerInvariant();
        if (lower.Contains("sorry", StringComparison.Ordinal) || t.Contains("抱歉", StringComparison.Ordinal) || t.Contains("对不起", StringComparison.Ordinal))
            return DialogueAct.Apologise;
        return DialogueAct.Inform;
    }

    /// <summary>The last cue drives the expressive state; earlier ones were transient.</summary>
    public static PersonaInput Persona(string reply, IReadOnlyList<string> cues, PartialExpression? character = null) =>
        new(InferAct(reply), Character: character,
            ExpressiveState: cues.Count > 0 && Table.TryGetValue(cues[^1], out var e) ? e : null);
}
