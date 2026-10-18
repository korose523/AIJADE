using System.Globalization;
using System.Text.Json.Nodes;

using Aijade.Core.Js;

namespace Aijade.Learning.Continuous;

// Persona and endocrine
// dynamics. A conversational turn moves five hormones and a 13-trait persona vector (plus a six-dimension intimacy
// state); time relaxes them toward baselines, with an endocrine → persona coupling term that ablations switch off.
// The configuration is kept as JSON so its deep merge and fingerprint behave as an object spread (later keys override, order kept).

public static class PersonaDims
{
    public static IReadOnlyList<string> Traits { get; } =
        ["openness", "warmth", "curiosity", "patience", "formality", "playfulness", "caution", "confidence", "empathy", "spontaneity", "diligence", "assertiveness", "stability"];

    public static IReadOnlyList<string> Hormones { get; } = ["dopamine", "serotonin", "cortisol", "oxytocin", "adrenaline"];

    public static IReadOnlyList<string> Intimacy { get; } = ["warmth", "trust", "dependence", "security", "familiarity", "longing"];
}

/// <summary>Persona vector, endocrine levels and intimacy, each keyed by its dimension name, all in [0, 1].</summary>
public sealed record PersonaState(IReadOnlyDictionary<string, double> Vector, IReadOnlyDictionary<string, double> Endocrine, IReadOnlyDictionary<string, double> Intimacy, double UpdatedAt);

public sealed record InteractionSignal(double Valence, double Arousal, string? Event = null);

public sealed record PadState(double Pleasure, double Arousal, double Dominance);

public sealed record BigFive(double O, double C, double E, double A, double N);

public sealed record ThreeForce(double Natural, double Social, double Individual);

public sealed record MoodProfile(string Label, string Emoji, double VoiceRate, double VoicePitch, string Style);

public static class PersonaDynamics
{
    /// <summary>The default dynamics, in their recorded key order (which the fingerprint depends on).</summary>
    public static JsonObject Default => (JsonObject)JsonNode.Parse("""
        {"valenceNeutral":0.5,
         "endocrine":{"dopamine":{"valence":0.3},"serotonin":{"valence":0.15},"cortisol":{"valence":-0.25,"arousal":0.1},"oxytocin":{"valence":0.2},"adrenaline":{"arousal":0.3,"arousalNeutral":0.3}},
         "traits":{"warmth":{"valence":0.1},"empathy":{"valence":0.08},"curiosity":{"arousal":0.06},"playfulness":{"valence":0.08,"valenceNeutral":0.3,"arousal":0.04},
                   "patience":{"hormone":"cortisol","hormoneNeutral":0.5,"hormoneGain":-0.05},"caution":{"hormone":"cortisol","hormoneNeutral":0.3,"hormoneGain":0.08},
                   "confidence":{"valence":0.06},"assertiveness":{"valence":0.05,"valenceNeutral":0.4,"arousal":0.03},"stability":{"arousal":-0.04,"arousalNeutral":0.5}},
         "intimacy":{"warmth":{"valence":0.1},"trust":{"valence":0.08,"bias":0.01},"familiarity":{"bias":0.03},"security":{"valence":0.05,"arousal":0.02,"arousalNeutral":0.5},
                     "dependence":{"valence":0.04},"longing":{"bias":-0.02,"unfamiliarity":0.01}},
         "drift":{"relaxationMs":600000,
                  "endocrine":{"dopamine":{"baseline":0.5,"rate":0.3},"serotonin":{"baseline":0.5,"rate":0.2},"cortisol":{"baseline":0.2,"rate":0.4},"oxytocin":{"baseline":0.4,"rate":0.2},"adrenaline":{"baseline":0.2,"rate":0.5}},
                  "coupling":{"caution":{"hormone":"cortisol","hormoneNeutral":0.3,"hormoneGain":0.02},"patience":{"hormone":"cortisol","hormoneNeutral":0.3,"hormoneGain":-0.02},
                              "curiosity":{"hormone":"dopamine","hormoneNeutral":0.5,"hormoneGain":0.02},"playfulness":{"hormone":"dopamine","hormoneNeutral":0.5,"hormoneGain":0.02}},
                  "vectorBaseline":0.5,"vectorMeanRevertRate":0.05,"intimacyRelaxationMs":3600000,
                  "intimacy":{"longing":{"bias":0.02},"security":{"baseline":0.4,"rate":0.1},"dependence":{"baseline":0.2,"rate":0.05}},
                  "noiseSigma":0},
         "interactionGain":1}
        """)!;

    private static JsonNode? Merge(JsonNode? baseNode, JsonNode? patch)
    {
        if (patch is null)
            return baseNode?.DeepClone();
        if (patch is not JsonObject p || baseNode is not JsonObject b)
            return patch.DeepClone();
        var output = (JsonObject)b.DeepClone();
        foreach (var (key, value) in p)
            output[key] = Merge(output[key], value);
        return output;
    }

    /// <summary>The defaults deep-merged with an override (new keys append, existing keys keep their place).</summary>
    public static JsonObject Resolve(JsonObject? overrideConfig = null) => (JsonObject)Merge(Default, overrideConfig)!;

    private static JsonNode? RoundNumbers(JsonNode? n) => n switch
    {
        JsonObject o => new JsonObject(o.Select(kv => KeyValuePair.Create(kv.Key, RoundNumbers(kv.Value)))),
        JsonArray a => new JsonArray(a.Select(RoundNumbers).ToArray()),
        JsonValue v when v.GetValueKind() == System.Text.Json.JsonValueKind.Number => JsonValue.Create(Math.Floor((Num(v) * 1e6) + 0.5) / 1e6),
        _ => n?.DeepClone(),
    };

    /// <summary>JSON of the config with every number rounded to 6 decimals — identifies the dynamics used by a run.</summary>
    public static string Fingerprint(JsonObject config) => JsFormat.Stringify(RoundNumbers(config));

    internal static double Num(JsonNode? n) => double.Parse(n!.ToJsonString(), CultureInfo.InvariantCulture);

    internal static double? Opt(JsonObject? o, string key) => o?[key] is JsonValue v && v.GetValueKind() == System.Text.Json.JsonValueKind.Number ? Num(v) : null;

    internal static string? OptStr(JsonObject? o, string key) => o?[key] is JsonValue v && v.TryGetValue<string>(out var s) ? s : null;
}

public static class Persona
{
    private static double Clamp01(double n) => Math.Max(0, Math.Min(1, n));

    private static double Clamp(double n, double lo, double hi) => Math.Max(lo, Math.Min(hi, n));

    private static double MeanRevert(double current, double baseline, double rate) => current + ((baseline - current) * rate);

    /// <summary>Box–Muller with the injected RNG (seeded in experiments, so drift noise is reproducible).</summary>
    private static double Gaussian(Func<double> rng)
    {
        double u = 0, v = 0;
        while (u == 0)
            u = rng();
        while (v == 0)
            v = rng();
        return Math.Sqrt(-2 * Math.Log(u)) * Math.Cos(2 * Math.PI * v);
    }

    public static IReadOnlyDictionary<string, double> DefaultIntimacy() =>
        new Dictionary<string, double> { ["warmth"] = 0.3, ["trust"] = 0.3, ["dependence"] = 0.2, ["security"] = 0.4, ["familiarity"] = 0.5, ["longing"] = 0.2 };

    /// <summary>A fresh persona: every trait at the seed ± 0.05 (so agents are not identical), default endocrine and intimacy.</summary>
    public static PersonaState Create(double seed = 0.5, Func<double>? jitter = null, double? now = null)
    {
        var rnd = jitter ?? Random.Shared.NextDouble;
        return new PersonaState(PersonaDims.Traits.ToDictionary(t => t, _ => Clamp01(seed + ((rnd() - 0.5) * 0.1))),
            new Dictionary<string, double> { ["dopamine"] = 0.5, ["serotonin"] = 0.5, ["cortisol"] = 0.2, ["oxytocin"] = 0.4, ["adrenaline"] = 0.2 },
            DefaultIntimacy(), now ?? DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
    }

    /// <summary>One turn: hormones react to valence / arousal, then traits react to the signal and the just-updated hormones.</summary>
    public static PersonaState ApplyInteraction(PersonaState state, InteractionSignal signal, JsonObject? config = null, double? now = null)
    {
        var cfg = config ?? PersonaDynamics.Default;
        var v = new Dictionary<string, double>(state.Vector);
        var e = new Dictionary<string, double>(state.Endocrine);
        var i = ApplyIntimacy(state.Intimacy, signal, cfg);
        var val = Clamp01((signal.Valence + 1) / 2);
        var aro = Clamp01(signal.Arousal);
        var gain = PersonaDynamics.Num(cfg["interactionGain"]);
        var vN = PersonaDynamics.Num(cfg["valenceNeutral"]);
        foreach (var (name, node) in cfg["endocrine"]!.AsObject())
        {
            var r = node!.AsObject();
            var aN = PersonaDynamics.Opt(r, "arousalNeutral") ?? 0;
            e[name] = Clamp01(e[name] + (gain * (((PersonaDynamics.Opt(r, "valence") ?? 0) * (val - vN)) + ((PersonaDynamics.Opt(r, "arousal") ?? 0) * (aro - aN)))));
        }
        foreach (var (name, node) in cfg["traits"]!.AsObject())
        {
            if (node is not JsonObject r)
                continue;
            var d = 0.0;
            if (PersonaDynamics.Opt(r, "valence") is { } rv && rv != 0)
                d += rv * (val - (PersonaDynamics.Opt(r, "valenceNeutral") ?? vN));
            if (PersonaDynamics.Opt(r, "arousal") is { } ra && ra != 0)
                d += ra * (aro - (PersonaDynamics.Opt(r, "arousalNeutral") ?? 0));
            if (PersonaDynamics.OptStr(r, "hormone") is { Length: > 0 } h && PersonaDynamics.Opt(r, "hormoneGain") is { } hg && hg != 0)
                d += hg * (e[h] - (PersonaDynamics.Opt(r, "hormoneNeutral") ?? 0));
            v[name] = Clamp01(v.GetValueOrDefault(name, double.NaN) + (gain * d));
        }
        return new PersonaState(v, e, i, now ?? DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
    }

    /// <summary>Time relaxation: hormones toward baselines, the coupling term, optional noise, then slow trait mean reversion.</summary>
    public static PersonaState Drift(PersonaState state, double dtMs, JsonObject? config = null, Func<double>? rng = null, double? now = null)
    {
        var cfg = config ?? PersonaDynamics.Default;
        var d = cfg["drift"]!.AsObject();
        var v = new Dictionary<string, double>(state.Vector);
        var e = new Dictionary<string, double>(state.Endocrine);
        var i = DriftIntimacy(state.Intimacy, dtMs, cfg);
        var k = Math.Min(1, dtMs / PersonaDynamics.Num(d["relaxationMs"]));
        foreach (var (name, node) in d["endocrine"]!.AsObject())
            e[name] = MeanRevert(e[name], PersonaDynamics.Num(node!["baseline"]), k * PersonaDynamics.Num(node["rate"]));
        foreach (var (name, node) in d["coupling"]!.AsObject())
        {
            if (node is not JsonObject r || PersonaDynamics.OptStr(r, "hormone") is not { Length: > 0 } h || PersonaDynamics.Opt(r, "hormoneGain") is not { } hg || hg == 0)
                continue;
            v[name] = Clamp01(v.GetValueOrDefault(name, double.NaN) + (hg * (e[h] - (PersonaDynamics.Opt(r, "hormoneNeutral") ?? 0))));
        }
        var sigma = PersonaDynamics.Num(d["noiseSigma"]);
        if (sigma > 0)
        {
            var random = rng ?? Random.Shared.NextDouble;
            foreach (var dim in PersonaDims.Traits)
                v[dim] = Clamp01(v[dim] + (Gaussian(random) * sigma));
        }
        var baseline = PersonaDynamics.Num(d["vectorBaseline"]);
        var rate = PersonaDynamics.Num(d["vectorMeanRevertRate"]);
        foreach (var dim in PersonaDims.Traits)
            v[dim] = MeanRevert(v[dim], baseline, k * rate);
        return new PersonaState(v, e, i, now ?? DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
    }

    public static IReadOnlyDictionary<string, double> ApplyIntimacy(IReadOnlyDictionary<string, double> state, InteractionSignal signal, JsonObject? config = null)
    {
        var cfg = config ?? PersonaDynamics.Default;
        var i = new Dictionary<string, double>(state);
        var val = Clamp01((signal.Valence + 1) / 2);
        var aro = Clamp01(signal.Arousal);
        var vN = PersonaDynamics.Num(cfg["valenceNeutral"]);
        var gain = PersonaDynamics.Num(cfg["interactionGain"]);
        foreach (var (name, node) in cfg["intimacy"]!.AsObject())
        {
            if (node is not JsonObject r)
                continue;
            var d = 0.0;
            if (PersonaDynamics.Opt(r, "valence") is { } rv && rv != 0)
                d += rv * (val - vN);
            if (PersonaDynamics.Opt(r, "arousal") is { } ra && ra != 0)
                d += ra * (aro - (PersonaDynamics.Opt(r, "arousalNeutral") ?? 0));
            if (PersonaDynamics.Opt(r, "bias") is { } b && b != 0)
                d += b;
            if (PersonaDynamics.Opt(r, "unfamiliarity") is { } u && u != 0)
                d += u * (1 - i["familiarity"]);
            i[name] = Clamp01(i.GetValueOrDefault(name, double.NaN) + (gain * d));
        }
        return i;
    }

    public static IReadOnlyDictionary<string, double> DriftIntimacy(IReadOnlyDictionary<string, double> state, double dtMs, JsonObject? config = null)
    {
        var d = (config ?? PersonaDynamics.Default)["drift"]!.AsObject();
        var i = new Dictionary<string, double>(state);
        var k = Math.Min(1, dtMs / PersonaDynamics.Num(d["intimacyRelaxationMs"]));
        foreach (var (name, node) in d["intimacy"]!.AsObject())
        {
            if (node is not JsonObject r)
                continue;
            if (PersonaDynamics.Opt(r, "bias") is { } b && b != 0)
                i[name] = Clamp01(i[name] + (k * b));
            if (PersonaDynamics.Opt(r, "baseline") is { } baseline && PersonaDynamics.Opt(r, "rate") is { } rate)
                i[name] = MeanRevert(i[name], baseline, k * rate);
        }
        return i;
    }

    public static PadState ToPad(PersonaState s)
    {
        var e = s.Endocrine;
        var v = s.Vector;
        return new PadState(
            Clamp01(0.5 + (0.35 * (e["serotonin"] - e["cortisol"])) + (0.15 * (e["dopamine"] - 0.5)) + (0.1 * (v["warmth"] - 0.5))),
            Clamp01(0.5 + (0.3 * (e["adrenaline"] - 0.3)) + (0.25 * (e["dopamine"] - 0.5)) - (0.2 * (e["serotonin"] - 0.5)) + (0.1 * (v["curiosity"] - 0.5))),
            Clamp01(0.5 + (0.3 * (v["confidence"] - 0.5)) + (0.2 * (v["assertiveness"] - 0.5)) + (0.1 * (v["caution"] - 0.5))));
    }

    public static BigFive ToBigFive(IReadOnlyDictionary<string, double> v) => new(
        Clamp01((v["openness"] + v["curiosity"] + v["spontaneity"]) / 3),
        Clamp01((v["diligence"] + v["patience"] + v["stability"] + v["caution"]) / 4),
        Clamp01((v["warmth"] + v["playfulness"] + v["confidence"] + v["assertiveness"]) / 4),
        Clamp01((v["warmth"] + v["empathy"] + v["patience"]) / 3),
        Clamp01(((1 - v["stability"]) * 0.5) + ((1 - v["patience"]) * 0.3) + ((1 - v["confidence"]) * 0.2)));

    public static ThreeForce ToThreeForce(PersonaState s)
    {
        var v = s.Vector;
        var natural = 0.2 + ((v["stability"] + v["patience"]) / 2 * 0.3);
        var social = 0.2 + ((v["warmth"] + v["empathy"] + v["playfulness"]) / 3 * 0.4);
        var individual = 0.2 + ((v["assertiveness"] + v["curiosity"] + v["spontaneity"]) / 3 * 0.4);
        var sum = natural + social + individual;
        return new ThreeForce(natural / sum, social / sum, individual / sum);
    }

    private static readonly Dictionary<string, string> MoodEmoji = new()
    {
        ["content"] = "😊",
        ["motivated"] = "🤩",
        ["stressed"] = "😣",
        ["connected"] = "🥰",
        ["alert"] = "😮",
        ["calm"] = "😌",
    };

    /// <summary>The dominant hormone names the mood (stable sort: ties keep the listed order); voice rate / pitch track hormones.</summary>
    public static MoodProfile ToMoodProfile(PersonaState s)
    {
        var e = s.Endocrine;
        var v = s.Vector;
        var pad = ToPad(s);
        var label = new[] { ("content", e["serotonin"]), ("motivated", e["dopamine"]), ("stressed", e["cortisol"]), ("connected", e["oxytocin"]), ("alert", e["adrenaline"]) }
            .OrderByDescending(x => x.Item2).First().Item1;
        var rate = Clamp(1 + (0.2 * (e["dopamine"] - 0.5)) - (0.1 * (e["serotonin"] - 0.5)) + (0.15 * (e["adrenaline"] - 0.3)), 0.6, 1.6);
        var pitch = Clamp(1 + (0.1 * (e["dopamine"] - 0.5)) + (0.1 * (e["cortisol"] - 0.2)), 0.7, 1.4);
        var style = pad.Arousal > 0.6 ? "excited" : e["cortisol"] > 0.5 ? "tense" : v["warmth"] > 0.6 ? "warm" : v["playfulness"] > 0.6 ? "playful" : v["confidence"] > 0.6 ? "confident" : "calm";
        return new MoodProfile(label, MoodEmoji.GetValueOrDefault(label, "🙂"), rate, pitch, style);
    }

    private static string E2(double n) => JsFormat.ToFixed(n, 2);

    /// <summary>The persona summary injected into the prompt.</summary>
    public static string ToContext(PersonaState s)
    {
        var v = s.Vector;
        var traits = new List<string>();
        void Push(string name, double value, string high, string low) => traits.Add($"{name}:{(value > 0.6 ? high : value < 0.4 ? low : "balanced")}");
        Push("openness", v["openness"], "open", "focused");
        Push("warmth", v["warmth"], "warm", "reserved");
        Push("curiosity", v["curiosity"], "curious", "steady");
        Push("caution", v["caution"], "cautious", "bold");
        Push("playfulness", v["playfulness"], "playful", "serious");
        Push("formality", v["formality"], "formal", "casual");
        var pad = ToPad(s);
        var mood = ToMoodProfile(s);
        var b = ToBigFive(v);
        var f = ToThreeForce(s);
        var i = s.Intimacy;
        return string.Join(" ",
            $"Persona[{string.Join(", ", traits)}]",
            $"mood={mood.Label}{mood.Emoji} PAD(p:{E2(pad.Pleasure)},a:{E2(pad.Arousal)},d:{E2(pad.Dominance)})",
            $"big5(O:{E2(b.O)},C:{E2(b.C)},E:{E2(b.E)},A:{E2(b.A)},N:{E2(b.N)})",
            $"force(social:{E2(f.Social)})",
            $"intimacy(warmth:{E2(i["warmth"])},trust:{E2(i["trust"])},familiar:{E2(i["familiarity"])},longing:{E2(i["longing"])})");
    }
}
