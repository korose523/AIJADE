using System.Globalization;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;

using Aijade.Core.Js;

namespace Aijade.Research.Telemetry;

// Per-turn experiment telemetry —
// session runner, ablation conditions, dynamics-parameter sweeps, render audit, and CSV / JSONL export with summaries.
// File formats are unchanged (sessions.jsonl, turns.jsonl, the same CSV columns), so existing study data keeps loading.
// Fingerprints sort keys with the ICU root collation, (stable across platforms).

public sealed record PersonaVectorSnapshot(
    double Openness, double Warmth, double Curiosity, double Patience, double Formality, double Playfulness, double Caution, double Confidence,
    double Empathy, double Spontaneity, double Diligence, double Assertiveness, double Stability);

public sealed record EndocrineSnapshot(double Dopamine, double Serotonin, double Cortisol, double Oxytocin, double Adrenaline);

public sealed record PadSnapshot(double Pleasure, double Arousal, double Dominance);

public sealed record BigFiveSnapshot(
    [property: JsonPropertyName("O")] double O, [property: JsonPropertyName("C")] double C, [property: JsonPropertyName("E")] double E,
    [property: JsonPropertyName("A")] double A, [property: JsonPropertyName("N")] double N);

public sealed record IntimacySnapshot(double Warmth, double Trust, double Dependence, double Security, double Familiarity, double Longing);

public sealed record PersonaSnapshot(
    PersonaVectorSnapshot Vector, EndocrineSnapshot Endocrine, PadSnapshot Pad, BigFiveSnapshot BigFive, IntimacySnapshot Intimacy,
    string? MoodLabel = null, string? MoodEmoji = null);

public sealed record LatencyBreakdown(double? Vad = null, double? Asr = null, double? Llm = null, double? Tts = null, double? Lipsync = null, double? MemoryRetrieval = null, double? Total = null);

public sealed record TokenUsage(double? Prompt = null, double? Completion = null, double? MemoryInjected = null);

/// <summary>The manipulated dynamics variables (Gap #2); baseline and coupling are partial maps, in insertion order.</summary>
public sealed record DynamicsParameters(
    double? RelaxationMs = null, OrderedDictionary<string, double>? Baseline = null, OrderedDictionary<string, double>? HormoneCoupling = null,
    double? NoiseSigma = null, double? TickIntervalMs = null, double? InteractionGain = null)
{
    public static DynamicsParameters Empty { get; } = new();
}

public enum TurnRole
{
    User,
    Assistant,
    System,
}

public enum ContradictionGate
{
    Reject,
    Clamp,
    Allow,
}

/// <summary>What was actually written to a render: renderer, model, asset version and the applied channel values.</summary>
public sealed record RenderAuditEntry(
    string SessionId, int TurnIndex, double Timestamp, string WallClock, string Renderer, string DisplayModelId, string AssetVersionHash,
    string AppliedParamsHash, OrderedDictionary<string, JsonValue> AppliedParams, string? PgcStateId = null, string? EvidencePackId = null,
    ContradictionGate? ContradictionGate = null, int? Tick = null, double? Seed = null);

/// <summary>One turn; the field order is the turns.jsonl format.</summary>
public sealed record TurnRecord(string SessionId, int TurnIndex, double Timestamp, string WallClock, TurnRole Role)
{
    public PersonaSnapshot? Persona { get; init; }
    public int? SkillLibrarySize { get; init; }
    public int? SkillsCreatedThisTurn { get; init; }
    public int? SkillsRejectedThisTurn { get; init; }
    public LatencyBreakdown? Latency { get; init; }
    public TokenUsage? Tokens { get; init; }
    public int? MemoryHits { get; init; }
    public int? TextLength { get; init; }
    public DynamicsParameters? Parameters { get; init; }
    public JsonObject? Metadata { get; init; }
    public RenderAuditEntry? Render { get; init; }
}

/// <summary>Which components run; all on is the baseline.</summary>
public sealed record AblationConfig(bool PersonaDynamics = true, bool HormoneCoupling = true, bool MemoryRetrieval = true, bool SkillForge = true, bool DiscourseMemory = true)
{
    public static AblationConfig Full { get; } = new();

    internal IEnumerable<(string Key, bool On)> Entries() =>
        [("personaDynamics", PersonaDynamics), ("hormoneCoupling", HormoneCoupling), ("memoryRetrieval", MemoryRetrieval), ("skillForge", SkillForge), ("discourseMemory", DiscourseMemory)];
}

public sealed record AblationCondition(string Name, AblationConfig Config, string? Description = null);

public sealed record SessionMeta(
    string SessionId, string Condition, string ConfigFingerprint, double StartedAt, string? ParticipantId = null, DynamicsParameters? Parameters = null,
    string? ParameterFingerprint = null, IReadOnlyDictionary<string, string>? Tags = null);

public sealed record ExperimentSession(SessionMeta Meta, double EndedAt, int TurnCount);

public static class TelemetryJson
{
    /// <summary>camelCase, absent fields omitted, enums lower-case, numbers formatted as JavaScript writes them.</summary>
    public static JsonSerializerOptions Options { get; } = new(JsonSerializerDefaults.Web)
    {
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        Encoder = System.Text.Encodings.Web.JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
        Converters = { new JsonStringEnumConverter(JsonNamingPolicy.CamelCase), new JsNumberJsonConverter() },
    };

    /// <summary>new Date(ms).toISOString().</summary>
    public static string IsoTime(double ms) =>
        DateTimeOffset.FromUnixTimeMilliseconds((long)ms).UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss.fff'Z'", CultureInfo.InvariantCulture);
}

public static class Fingerprints
{
    /// <summary>localeCompare ordering (ICU root collation).</summary>
    public static StringComparer KeyOrder { get; } = StringComparer.InvariantCulture;

    /// <summary>Number(n.toFixed(6)).toString().</summary>
    public static string Round6(double n) => JsFormat.Number(double.Parse(JsFormat.ToFixed(n, 6), CultureInfo.InvariantCulture));

    /// <summary>"discourseMemory:1|hormoneCoupling:0|…" — the stable identity of an ablation configuration.</summary>
    public static string Config(AblationConfig c) =>
        string.Join("|", c.Entries().OrderBy(e => e.Key, KeyOrder).Select(e => $"{e.Key}:{(e.On ? "1" : "0")}"));

    /// <summary>The scalar axes in fixed order, then baseline{…} and coupling{…} with sorted keys, values rounded to 6 decimals.</summary>
    public static string Parameters(DynamicsParameters p)
    {
        var parts = new List<string>();
        foreach (var (key, v) in new[] { ("relaxationMs", p.RelaxationMs), ("noiseSigma", p.NoiseSigma), ("interactionGain", p.InteractionGain), ("tickIntervalMs", p.TickIntervalMs) })
        {
            if (v is { } x)
                parts.Add($"{key}={Round6(x)}");
        }
        if (p.Baseline is { } b)
            parts.Add($"baseline{{{string.Join(",", b.OrderBy(kv => kv.Key, KeyOrder).Select(kv => $"{kv.Key}={Round6(kv.Value)}"))}}}");
        if (p.HormoneCoupling is { } h)
            parts.Add($"coupling{{{string.Join(",", h.OrderBy(kv => kv.Key, KeyOrder).Select(kv => $"{kv.Key}={Round6(kv.Value)}"))}}}");
        return string.Join("|", parts);
    }

    /// <summary>The canonical text of the applied render parameters: sorted keys, numbers to 6 decimals, b:0/1, s:text.</summary>
    public static string AppliedParams(IEnumerable<KeyValuePair<string, JsonValue>> applied) =>
        string.Join("|", applied.OrderBy(kv => kv.Key, KeyOrder).Select(kv => $"{kv.Key}={Scalar(kv.Value)}"));

    private static string Scalar(JsonValue v) => v.GetValueKind() switch
    {
        JsonValueKind.True => "b:1",
        JsonValueKind.False => "b:0",
        JsonValueKind.Number => Round6(v.GetValue<double>()),
        _ => $"s:{v.GetValue<string>()}",
    };

    public static RenderAuditEntry BuildRenderAuditEntry(RenderAuditEntry input) => input with { AppliedParamsHash = AppliedParams(input.AppliedParams) };
}

public static class Ablations
{
    public static IReadOnlyDictionary<string, string> EnvKeys { get; } = new Dictionary<string, string>
    {
        ["personaDynamics"] = "AIJADE_ABLATION_PERSONA_DYNAMICS",
        ["hormoneCoupling"] = "AIJADE_ABLATION_HORMONE_COUPLING",
        ["memoryRetrieval"] = "AIJADE_ABLATION_MEMORY_RETRIEVAL",
        ["skillForge"] = "AIJADE_ABLATION_SKILL_FORGE",
        ["discourseMemory"] = "AIJADE_ABLATION_DISCOURSE_MEMORY",
    };

    /// <summary>An unset or empty variable keeps the default (on); otherwise only 1 / true / on / yes enable.</summary>
    public static AblationConfig FromEnv(IReadOnlyDictionary<string, string?>? env = null)
    {
        bool Read(string key)
        {
            var raw = env is null ? Environment.GetEnvironmentVariable(key) : env.GetValueOrDefault(key);
            if (string.IsNullOrEmpty(raw))
                return true;
            var v = Aijade.Core.Js.JsText.Lower(Aijade.Core.Js.JsText.Trim(raw));
            return v is "1" or "true" or "on" or "yes";
        }
        return new AblationConfig(Read(EnvKeys["personaDynamics"]), Read(EnvKeys["hormoneCoupling"]), Read(EnvKeys["memoryRetrieval"]), Read(EnvKeys["skillForge"]), Read(EnvKeys["discourseMemory"]));
    }

    public static IReadOnlyList<AblationCondition> DefaultConditions { get; } =
    [
        new("baseline", AblationConfig.Full, "All components enabled. Reference condition."),
        new("no-persona-dynamics", AblationConfig.Full with { PersonaDynamics = false }, "Isolates the contribution of any affective dynamics at all."),
        new("no-hormone-coupling", AblationConfig.Full with { HormoneCoupling = false },
            "Isolates the endocrine→persona coupling term inside drift. Directly probes Gap #2 (which dynamics parameters actually matter when they drive generation)."),
        new("no-memory-retrieval", AblationConfig.Full with { MemoryRetrieval = false }, "Isolates memory retrieval; also yields its latency/token cost for Gap #3."),
        new("no-skill-forge", AblationConfig.Full with { SkillForge = false }, "Isolates automatic skill creation (RQ-C)."),
        new("no-discourse-memory", AblationConfig.Full with { DiscourseMemory = false }, "Isolates the bounded recent-turn buffer."),
    ];

    /// <summary>The named condition, else the baseline.</summary>
    public static AblationCondition Resolve(string name, IReadOnlyList<AblationCondition>? conditions = null)
    {
        var cs = conditions ?? DefaultConditions;
        return cs.FirstOrDefault(c => c.Name == name) ?? cs.FirstOrDefault(c => c.Name == "baseline") ?? new AblationCondition("baseline", AblationConfig.Full);
    }

    public static string Describe(AblationConfig c)
    {
        var off = c.Entries().Where(e => !e.On).Select(e => e.Key).ToList();
        return off.Count == 0 ? "baseline (all on)" : $"disabled: {string.Join(", ", off)}";
    }
}

public enum SweepAxis
{
    RelaxationMs,
    NoiseSigma,
    InteractionGain,
    TickIntervalMs,
}

public sealed record SweepPoint(string Name, DynamicsParameters Parameters);

public static class Sweeps
{
    private static string Slug(SweepAxis a) => a switch
    {
        SweepAxis.RelaxationMs => "relax",
        SweepAxis.NoiseSigma => "noise",
        SweepAxis.InteractionGain => "gain",
        _ => "tick",
    };

    private static string Format(double v) => Math.Floor(v) == v && double.IsFinite(v)
        ? JsFormat.Number(v)
        : JsFormat.Number(double.Parse(JsFormat.ToFixed(v, 4), CultureInfo.InvariantCulture));

    private static DynamicsParameters With(DynamicsParameters p, SweepAxis axis, double v) => axis switch
    {
        SweepAxis.RelaxationMs => p with { RelaxationMs = v },
        SweepAxis.NoiseSigma => p with { NoiseSigma = v },
        SweepAxis.InteractionGain => p with { InteractionGain = v },
        _ => p with { TickIntervalMs = v },
    };

    private static double? Get(DynamicsParameters p, SweepAxis axis) => axis switch
    {
        SweepAxis.RelaxationMs => p.RelaxationMs,
        SweepAxis.NoiseSigma => p.NoiseSigma,
        SweepAxis.InteractionGain => p.InteractionGain,
        _ => p.TickIntervalMs,
    };

    public static IReadOnlyList<SweepPoint> Axis(SweepAxis axis, IEnumerable<double> values, DynamicsParameters? baseParams = null) =>
        values.Select(v => new SweepPoint($"{Slug(axis)}-{Format(v)}", With(baseParams ?? DynamicsParameters.Empty, axis, v))).ToList();

    /// <summary>The Cartesian product of the axes, in the order given, each point named axis-value_axis-value.</summary>
    public static IReadOnlyList<SweepPoint> Grid(IReadOnlyList<(SweepAxis Axis, IReadOnlyList<double> Values)> axes, DynamicsParameters? baseParams = null)
    {
        var b = baseParams ?? DynamicsParameters.Empty;
        if (axes.Count == 0)
            return [new SweepPoint("base", b)];
        IEnumerable<DynamicsParameters> combos = [b];
        foreach (var (axis, values) in axes)
            combos = combos.SelectMany(c => values.Select(v => With(c, axis, v))).ToList();
        return combos.Select(p => new SweepPoint(string.Join("_", axes.Select(a => $"{Slug(a.Axis)}-{Format(Get(p, a.Axis) ?? 0)}")), p)).ToList();
    }

    /// <summary>Five points around a centre relaxation time: ×¼, ×½, ×1, ×2, ×4.</summary>
    public static IReadOnlyList<SweepPoint> DefaultRelaxation(double centreMs, DynamicsParameters? baseParams = null) =>
        Axis(SweepAxis.RelaxationMs, [centreMs * 0.25, centreMs * 0.5, centreMs, centreMs * 2, centreMs * 4], baseParams);
}
