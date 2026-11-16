using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

using Aijade.Core.Js;
using Aijade.Learning.Forge;
using Aijade.Providers.Llm;

namespace Aijade.Learning.Continuous;

// The affect signal of a turn
// (a multilingual lexicon plus typographic energy, or an LLM rating with lexicon fallback), the bounded discourse memory
// (a recent window plus LLM-compressed "sink" sentences), and the learning loop that ties persona, memory and skills together.

public sealed record SignalOptions(
    double BaselineArousal = 0.25, double ValenceScale = 1, double ValenceCap = 1, IReadOnlyList<string>? Positive = null, IReadOnlyList<string>? Negative = null,
    IReadOnlyList<string>? Intensifiers = null);

public static class AffectSignal
{
    // Deliberately multilingual: a monolingual lexicon would score every non-English turn as neutral and leave the persona inert.
    public static IReadOnlyList<string> DefaultPositive { get; } =
    [
        "love", "great", "good", "nice", "happy", "glad", "thanks", "thank", "awesome", "amazing", "wonderful", "excellent", "perfect", "cool", "fun", "enjoy",
        "like", "helpful", "brilliant", "pleased", "delighted", "yay", "yes", "please",
        "喜欢", "爱", "开心", "高兴", "快乐", "谢谢", "感谢", "太好了", "棒", "厉害", "不错", "很好", "真好", "有意思", "有趣", "舒服", "安心", "温暖", "感动", "赞",
        "喜欢你", "陪我", "想你",
        "좋아", "사랑", "고마워", "감사", "행복", "기뻐", "최고", "재미있",
    ];

    public static IReadOnlyList<string> DefaultNegative { get; } =
    [
        "hate", "bad", "awful", "terrible", "horrible", "angry", "mad", "sad", "upset", "annoying", "annoyed", "stupid", "dumb", "useless", "wrong", "broken",
        "failed", "fail", "error", "problem", "hurt", "pain", "tired", "boring", "disappointed", "frustrated", "no", "stop", "shut",
        "讨厌", "恨", "生气", "难过", "伤心", "烦", "无聊", "糟糕", "差", "烂", "失败", "错误", "问题", "不行", "不要", "住口", "闭嘴", "滚", "笨", "蠢", "失望",
        "沮丧", "累", "痛", "害怕", "担心",
        "싫어", "미워", "화나", "슬퍼", "짜증", "최악", "실패", "문제", "그만",
    ];

    public static IReadOnlyList<string> DefaultIntensifiers { get; } =
        ["very", "really", "so", "extremely", "absolutely", "super", "totally", "非常", "特别", "超级", "真的", "太", "十分", "极其", "好", "너무", "정말", "아주"];

    private static readonly string[] PositiveEmoji = ["😊", "😄", "😍", "🥰", "😘", "❤", "💕", "💖", "👍", "🎉", "✨", "🙏", "🤩", "😌"];
    private static readonly string[] NegativeEmoji = ["😠", "😡", "😢", "😭", "😞", "💔", "👎", "😣", "😤", "🙄", "😨", "😰"];

    private static readonly Regex AsciiWord = new("^[a-z]+$", JsText.Options(false));
    private static readonly Regex Exclaim = new("[!！]", JsText.Options(false));
    private static readonly Regex Question = new("[?？]", JsText.Options(false));
    private static readonly Regex NonLetters = new("[^a-z]", JsText.Options(true));
    private static readonly Regex Caps = new(JsText.Boundary + "[A-Z]{2,}" + JsText.Boundary, JsText.Options(false));
    private static readonly Regex Ellipsis = new(@"\.\.\.|…", JsText.Options(false));

    private static int Occurrences(string text, string w)
    {
        var n = 0;
        for (var idx = text.IndexOf(w, StringComparison.Ordinal); idx != -1; idx = text.IndexOf(w, idx + w.Length, StringComparison.Ordinal))
            n++;
        return n;
    }

    /// <summary>ASCII words match on JS word boundaries; everything else (CJK, Hangul) counts non-overlapping occurrences.</summary>
    private static int CountHits(string lower, IEnumerable<string> words) => words.Where(w => w.Length > 0).Sum(w => AsciiWord.IsMatch(w)
        ? Regex.Count(lower, JsText.Boundary + Regex.Escape(w) + JsText.Boundary, JsText.Options(false))
        : Occurrences(lower, w));

    private static double Clamp(double n, double lo, double hi) => Math.Max(lo, Math.Min(hi, n));

    /// <summary>
    /// Valence: (pos − neg) / max(2, total) × 1.5 × intensity, so one stray word does not slam it to the rail; intensifiers
    /// amplify an existing polarity. Arousal: exclamations, questions, ALL-CAPS words, sentiment density, length; an ellipsis calms.
    /// </summary>
    public static InteractionSignal Extract(string? text, SignalOptions? options = null)
    {
        var o = options ?? new SignalOptions();
        var positive = o.Positive is { Count: > 0 } p ? p : DefaultPositive;
        var negative = o.Negative is { Count: > 0 } n ? n : DefaultNegative;
        var intensifiers = o.Intensifiers is { Count: > 0 } x ? x : DefaultIntensifiers;
        var raw = JsText.Trim(text ?? "");
        if (raw.Length == 0)
            return new InteractionSignal(0, 0.05, "empty");
        var lower = JsText.Lower(raw);
        var pos = CountHits(lower, positive) + PositiveEmoji.Sum(e => Occurrences(raw, e));
        var neg = CountHits(lower, negative) + NegativeEmoji.Sum(e => Occurrences(raw, e));
        var intensity = 1 + Math.Min(0.6, CountHits(lower, intensifiers) * 0.2);
        var total = pos + neg;
        var valence = total == 0 ? 0 : Clamp((double)(pos - neg) / Math.Max(2, total) * 1.5 * intensity * o.ValenceScale, -o.ValenceCap, o.ValenceCap);
        var letters = NonLetters.Replace(raw, "");
        var capsRatio = letters.Length >= 4 ? (double)Caps.Count(raw) / Math.Max(1, JsText.SplitOnSpace(raw).Length) : 0;
        var arousal = o.BaselineArousal;
        arousal += Math.Min(0.3, Exclaim.Count(raw) * 0.1);
        arousal += Math.Min(0.1, Question.Count(raw) * 0.05);
        arousal += Math.Min(0.25, capsRatio * 0.5);
        arousal += Math.Min(0.2, (pos + neg) * 0.05);
        arousal += Ellipsis.IsMatch(raw) ? -0.05 : 0;
        arousal += Math.Min(0.1, raw.Length / 2000.0);
        return new InteractionSignal(valence, Clamp(arousal, 0, 1), total == 0 ? "neutral" : pos >= neg ? "positive" : "negative");
    }

    private const string ExtractSystem = """
        You rate a single chat turn's affect.
        Reply with JSON only: {"valence": <number -1..1>, "arousal": <number 0..1>}
        valence: -1 very negative, 0 neutral, +1 very positive.
        arousal: 0 calm/flat, 1 excited/intense.
        No explanation.
        """;

    /// <summary>An LLM affect rating (temperature 0); any failure or non-numeric answer falls back to the lexicon.</summary>
    public static async Task<InteractionSignal> ExtractWithLlmAsync(IChatClient llm, string text, ChatRole role, SignalOptions? options = null, CancellationToken ct = default)
    {
        ArgumentNullException.ThrowIfNull(llm);
        if (JsText.Trim(text ?? "").Length == 0)
            return new InteractionSignal(0, 0.05, "empty");
        try
        {
            var r = await llm.JsonCompleteAsync([new ChatMessage(ChatRole.System, ExtractSystem), new ChatMessage(ChatRole.User, $"[{WireName.Of(role)}] {(text!.Length > 2000 ? text[..2000] : text)}")],
                new ChatRequestOptions(Temperature: 0), ct).ConfigureAwait(false);
            if (r?["valence"] is not JsonValue v || r["arousal"] is not JsonValue a || v.GetValueKind() != System.Text.Json.JsonValueKind.Number || a.GetValueKind() != System.Text.Json.JsonValueKind.Number)
                throw new FormatException("non-numeric affect scores");
            var valence = PersonaDynamics.Num(v);
            return new InteractionSignal(Clamp(valence, -1, 1), Clamp(PersonaDynamics.Num(a), 0, 1), valence >= 0 ? "positive" : "negative");
        }
#pragma warning disable CA1031 // Any model failure falls back to the deterministic lexicon.
        catch (Exception e) when (e is not OperationCanceledException)
#pragma warning restore CA1031
        {
            return Extract(text, options);
        }
    }
}

/// <summary>A bounded recent window; overflow is compressed by the LLM into at most <c>maxChunks</c> one-sentence "sinks".</summary>
public sealed class DiscourseMemory(IChatClient llm, int window = 12, int maxChunks = 3)
{
    private readonly List<ChatMessage> _recent = [];
    private readonly List<string> _chunks = [];
    private Task _compaction = Task.CompletedTask;

    public void Ingest(ChatRole role, string text)
    {
        _recent.Add(new ChatMessage(role, text));
        if (_recent.Count > window * 1.5)
            _compaction = CompactAsync();
    }

    /// <summary>The background compaction started by the last ingest (tests and shutdown can await it).</summary>
    public Task PendingCompaction => _compaction;

    public async Task CompactAsync(CancellationToken ct = default)
    {
        if (_recent.Count <= window)
            return;
        var overflow = _recent.GetRange(0, _recent.Count - window);
        _recent.RemoveRange(0, overflow.Count);
        var transcript = string.Join("\n", overflow.Select(m => $"{WireName.Of(m.Role)}: {m.Content}"));
        try
        {
            var res = await llm.CompleteAsync([
                new ChatMessage(ChatRole.System, "Compress conversation excerpts into ONE dense \"sink\" sentence of <=60 words, preserving durable facts and user preferences. Output only the sentence."),
                new ChatMessage(ChatRole.User, transcript)], cancellationToken: ct).ConfigureAwait(false);
            var sink = JsText.Trim(res.Text);
            if (sink.Length > 0)
            {
                _chunks.Add(sink);
                while (_chunks.Count > maxChunks)
                    _chunks.RemoveAt(0);
            }
        }
#pragma warning disable CA1031 // A failed compaction is skipped; the overflow is dropped either way.
        catch (Exception e) when (e is not OperationCanceledException)
#pragma warning restore CA1031
        {
        }
    }

    public string Context()
    {
        var parts = new List<string>();
        if (_chunks.Count > 0)
            parts.Add($"[long-term sink]\n{string.Join("\n", _chunks)}");
        var tail = RecentMessages();
        if (tail.Count > 0)
            parts.Add($"[recent discourse]\n{string.Join("\n", tail.Select(m => $"{WireName.Of(m.Role)}: {m.Content}"))}");
        return string.Join("\n\n", parts);
    }

    public IReadOnlyList<ChatMessage> RecentMessages() => _recent.Skip(Math.Max(0, _recent.Count - window)).ToList();

    public (int Recent, int Chunks) Stats => (_recent.Count, _chunks.Count);
}

/// <summary>The layered long-term memory the learning loop writes turns into (any store that can ingest and compact).</summary>
public interface IMemoryPort
{
    Task IngestUserAsync(string text, CancellationToken cancellationToken = default);

    Task IngestAssistantAsync(string text, CancellationToken cancellationToken = default);

    Task MaybeCompactAsync(CancellationToken cancellationToken = default);
}

public enum PersonaUpdateCause
{
    Interaction,
    Drift,
}

public sealed record PersonaUpdateEvent(PersonaState State, PersonaUpdateCause Cause, double Timestamp, ChatRole? Role = null, InteractionSignal? Signal = null);

/// <summary>How a turn's signal is obtained when the caller does not supply one; null disables extraction.</summary>
public delegate Task<InteractionSignal> SignalExtractor(string text, ChatRole role);

/// <summary>
/// The continuous-learning loop: every turn feeds discourse memory and long-term memory and moves the persona; ticks drift
/// it; feedback evolves the skill it refers to. Persona updates are announced so telemetry can record them.
/// </summary>
public sealed class ContinuousLearning
{
    private readonly IMemoryPort? _memory;
    private readonly SkillForge? _forge;
    private readonly SignalExtractor? _extractor;
    private readonly Func<double> _now;
    private readonly Func<double>? _noise;
    private double _lastInteraction;

    public ContinuousLearning(IChatClient llm, IMemoryPort? memory = null, SkillForge? forge = null, double personaSeed = 0.5, JsonObject? dynamics = null,
        SignalExtractor? signalExtractor = null, bool disableSignalExtraction = false, Action<PersonaUpdateEvent>? onPersonaUpdate = null, Func<double>? now = null,
        Func<double>? noise = null, Func<double>? jitter = null)
    {
        _memory = memory;
        _forge = forge;
        _now = now ?? (() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
        _noise = noise;
        Dynamics = PersonaDynamics.Resolve(dynamics);
        _extractor = disableSignalExtraction ? null : signalExtractor ?? ((text, _) => Task.FromResult(AffectSignal.Extract(text)));
        OnPersonaUpdate = onPersonaUpdate;
        Persona = Continuous.Persona.Create(personaSeed, jitter, _now());
        Discourse = new DiscourseMemory(llm);
        _lastInteraction = _now();
    }

    public PersonaState Persona { get; private set; }

    public JsonObject Dynamics { get; }

    public DiscourseMemory Discourse { get; }

    public Action<PersonaUpdateEvent>? OnPersonaUpdate { get; }

    private void Apply(InteractionSignal signal, ChatRole role)
    {
        Persona = Continuous.Persona.ApplyInteraction(Persona, signal, Dynamics, _now());
        OnPersonaUpdate?.Invoke(new PersonaUpdateEvent(Persona, PersonaUpdateCause.Interaction, Persona.UpdatedAt, role, signal));
    }

    /// <summary>Record a turn; the persona moves by the given signal or the extracted one.</summary>
    public async Task IngestTurnAsync(ChatRole role, string text, InteractionSignal? signal = null, CancellationToken ct = default)
    {
        Discourse.Ingest(role, text);
        if (_memory is not null)
            await (role == ChatRole.User ? _memory.IngestUserAsync(text, ct) : _memory.IngestAssistantAsync(text, ct)).ConfigureAwait(false);
        var resolved = signal ?? (_extractor is null ? null : await _extractor(text, role).ConfigureAwait(false));
        if (resolved is not null)
            Apply(resolved, role);
        _lastInteraction = _now();
    }

    public void Tick(double dtMs)
    {
        Persona = Continuous.Persona.Drift(Persona, dtMs, Dynamics, _noise, _now());
        OnPersonaUpdate?.Invoke(new PersonaUpdateEvent(Persona, PersonaUpdateCause.Drift, Persona.UpdatedAt));
    }

    public double IdleMs => _now() - _lastInteraction;

    private static readonly Regex NonSlug = new("[^a-z0-9-]", JsText.Options(false));

    /// <summary>
    /// Evolve the skill the feedback is about: one whose name occurs in the text, or whose description contains its first
    /// word. Returns the evolved skill, or null when no forge, no skill, no match, or the evolution failed.
    /// </summary>
    public async Task<SkillPackage?> CaptureFeedbackAsync(string feedback, string? relatedText = null, CancellationToken ct = default)
    {
        if (_forge is null)
            return null;
        var skills = _forge.Registry.List();
        if (skills.Count == 0)
            return null;
        var haystack = JsText.Lower(relatedText ?? feedback);
        var firstWord = NonSlug.Replace(JsText.SplitOnSpace(haystack).FirstOrDefault() ?? "", "");
        var match = skills.FirstOrDefault(s => haystack.Contains(JsText.Lower(s.Frontmatter.Name), StringComparison.Ordinal)
            || (firstWord.Length > 0 && JsText.Lower(s.Frontmatter.Description).Contains(firstWord, StringComparison.Ordinal)));
        if (match is null)
            return null;
        try
        {
            var evolved = await _forge.EvolveSkillAsync(match, feedback, ct).ConfigureAwait(false);
            _forge.Registry.Add(evolved);
            return evolved;
        }
#pragma warning disable CA1031 // A failed evolution leaves the skill as it was.
        catch (Exception e) when (e is not OperationCanceledException)
#pragma warning restore CA1031
        {
            return null;
        }
    }

    /// <summary>Persona summary plus discourse context, for the system prompt.</summary>
    public string ContextSupplement() => JsText.Trim($"{Continuous.Persona.ToContext(Persona)}\n\n{Discourse.Context()}");

    public async Task CompactAsync(CancellationToken ct = default)
    {
        await Discourse.CompactAsync(ct).ConfigureAwait(false);
        if (_memory is not null)
            await _memory.MaybeCompactAsync(ct).ConfigureAwait(false);
    }
}
