using System.Text.RegularExpressions;

using Aijade.Memory.Lexical;
using Aijade.Core.Js;

namespace Aijade.Memory.Salience;

// Predictive salience without gold labels: 13 unsupervised text features weighted by a theory prior.
// The weights were chosen after seeing single-feature AUCs on the full corpus, so in-sample AUC is an optimistic
// upper bound; leave-one-conversation-out estimates are reported separately (see the papers).

/// <summary>Causal context for one utterance: earlier turns of the same conversation and corpus IDF.</summary>
public sealed record SalienceContext(IReadOnlyList<string> Priors, IReadOnlyDictionary<string, double> Idf, int NDocs)
{
    /// <summary>The context the store uses at encode time: no priors, no corpus statistics.</summary>
    public static SalienceContext Empty { get; } = new([], new Dictionary<string, double>(), 1);
}

public sealed record SaliencePrediction(double Score, IReadOnlyList<double> Features);

/// <summary>v1 breakdown (kept for comparison experiments).</summary>
public sealed record SalienceBreakdown(double Novelty, double Entity, double Commitment, double Length, double Question, double Total);

public static class SaliencePredictor
{
    private const string B = JsText.Boundary;
    private const string S = JsText.Space;

    private static Regex I(string pattern, bool ignoreCase = true) => new(pattern, JsText.Options(ignoreCase));

    /// <summary>Commitments, preferences and self-statements — what long-term memory should keep.</summary>
    private static readonly Regex Commitment = I(
        $@"{B}i{S}+(?:will|'ll|am{S}+going{S}+to|plan{S}+to|need{S}+to|want{S}+to|have{S}+to|decided{S}+to|promise|hope{S}+to){B}"
        + $@"|{B}my{S}+(?:favorite|favourite|birthday|name|wife|husband|mom|dad|dog|cat|son|daughter|brother|sister){B}"
        + $@"|{B}i{S}+(?:like|love|hate|prefer|enjoy|always|never){B}");

    private static readonly Regex Capitalised = I("^[A-Z][a-z]+$", ignoreCase: false);
    private static readonly Regex Digit = I("[0-9]", ignoreCase: false);
    private static readonly Regex NonWordish = I("[^a-z0-9'-]");

    private static readonly Regex Backchannel = I(
        $@"^(?:oh|ah|hmm|haha+|hehe+|lol|yeah+|yes+|yep|yup|nope|no+|(?:ok(?:ay)?)+|sure|right|true|wow|oops|hey|hi+|hello+|bye+|thanks?|thank you|really\?*|what\?*|huh\?*|m{{2,}}|uh+|um+|alright|got it|i see|of course|exactly|definitely|absolutely|me too|same here){B}");

    private static readonly Regex PastVerb = I(
        $"{B}(?:was|were|went|did|had|saw|got|took|made|came|said|told|bought|visited|met|started|finished|moved|found|lost|gave|ate|drank|played|watched|read|wrote|traveled|travelled|won|joined|graduated|adopted|married){B}");

    private static readonly Regex BeVerb = I($"{B}(?:is|am|are|was|were|be|been|being){B}");

    private static readonly Regex TimeWord = I(
        $"{B}(?:today|yesterday|tomorrow|last|next|ago|week|weekend|month|year|monday|tuesday|wednesday|thursday|friday|saturday|sunday|january|february|march|april|may|june|july|august|september|october|november|december|morning|afternoon|evening|night|birthday|anniversary){B}");

    private static readonly Regex FirstPerson = I($"{B}(?:i|my|me|mine|myself){B}");
    private static readonly Regex Possessive = I($"{B}(?:my|his|her|their|our|its){B}");
    private static readonly Regex SecondPerson = I($"{B}(?:you|your|yours|yourself){B}");

    private static readonly HashSet<string> SalienceStop =
    [
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "am", "to", "of", "and", "or", "but", "in", "on", "at", "it",
        "this", "that", "i", "you", "he", "she", "we", "they", "my", "your", "his", "her", "our", "their", "for", "with", "as",
        "so", "if", "then", "than", "do", "does", "did", "have", "has", "had", "not", "no", "yes",
    ];

    public static readonly IReadOnlyDictionary<string, double> V1Weights = new Dictionary<string, double>
    {
        ["novelty"] = 0.35, ["entity"] = 0.25, ["commitment"] = 0.25, ["length"] = 0.10, ["question"] = 0.05,
    };

    /// <summary>Theory-prior weights of the v2 predictor (direction and relative magnitude only).</summary>
    public static readonly IReadOnlyDictionary<string, double> PriorWeights = new Dictionary<string, double>
    {
        ["length"] = 1.00, ["contentDensity"] = 0.35, ["noveltyIdf"] = 0.20, ["meanIdf"] = 0.30, ["selfDisclosure"] = 0.55,
        ["possessive"] = 0.30, ["pastVerb"] = 0.35, ["temporal"] = 0.35, ["entity"] = 0.30, ["commitment"] = 0.45,
        ["isQuestion"] = -0.40, ["isBackchannel"] = -0.60, ["secondPerson"] = -0.30,
    };

    private static double Clamp01(double x) => Math.Min(1, Math.Max(0, x));

    private static double Log1P(double x) => Math.Log(1 + x);

    private static string[] Words(string text) => JsText.SplitOnSpace(JsText.Lower(text)).Where(w => w.Length > 0).ToArray();

    private static int Count(Regex re, string text) => re.Count(text);

    private static double EntityDensity(string text)
    {
        var raw = JsText.SplitOnSpace(text);
        var hits = 0;
        for (var i = 0; i < raw.Length; i++)
        {
            var w = NonWordish.Replace(raw[i], "");
            if (w.Length == 0)
                continue;
            if (i > 0 && Capitalised.IsMatch(w))
                hits++;
            else if (Digit.IsMatch(w))
                hits++;
        }
        return Math.Min(1, hits / 3.0);
    }

    /// <summary>The 13 v2 features, in index order.</summary>
    public static readonly IReadOnlyList<(string Name, Func<string, SalienceContext, double> Fn)> Features =
    [
        ("length", (t, _) => Math.Min(1, Log1P(Words(t).Length) / Log1P(60))),
        ("contentDensity", (t, _) =>
        {
            var w = Words(t);
            return w.Length > 0 ? (double)w.Count(x => !SalienceStop.Contains(x)) / w.Length : 0;
        }),
        ("noveltyIdf", (t, ctx) =>
        {
            var w = Words(t);
            if (w.Length == 0 || ctx.Priors.Count == 0)
                return 0.5;
            var seen = new HashSet<string>();
            foreach (var p in ctx.Priors.Skip(Math.Max(0, ctx.Priors.Count - 10)))
            {
                foreach (var x in Words(p))
                    seen.Add(x);
            }
            double newMass = 0, total = 0;
            foreach (var x in w)
            {
                var idf = ctx.Idf.TryGetValue(x, out var v) ? v : Log1P(ctx.NDocs);
                total += idf;
                if (!seen.Contains(x))
                    newMass += idf;
            }
            return total != 0 ? newMass / total : 0;
        }),
        ("meanIdf", (t, ctx) =>
        {
            var w = Words(t);
            if (w.Length == 0)
                return 0;
            var max = Log1P(ctx.NDocs);
            var sum = 0.0;
            foreach (var x in w)
                sum += ctx.Idf.TryGetValue(x, out var v) ? v : max;
            return sum / w.Length / max;
        }),
        ("selfDisclosure", (t, _) => Math.Min(1, (Count(FirstPerson, t) + (Count(BeVerb, t) * 0.5) + (Count(PastVerb, t) * 0.5)) / 5)),
        ("possessive", (t, _) => Math.Min(1, Count(Possessive, t) / 3.0)),
        ("pastVerb", (t, _) => Math.Min(1, Count(PastVerb, t) / 3.0)),
        ("temporal", (t, _) => Math.Min(1, Count(TimeWord, t) / 2.0)),
        ("entity", (t, _) => EntityDensity(t)),
        ("commitment", (t, _) => Commitment.IsMatch(t) ? 1 : 0),
        ("isQuestion", (t, _) => t.Contains('?', StringComparison.Ordinal) ? 1 : 0),
        ("isBackchannel", (t, _) => Backchannel.IsMatch(JsText.Trim(t)) ? 1 : 0),
        ("secondPerson", (t, _) => Math.Min(1, Count(SecondPerson, t) / 3.0)),
    ];

    public static int FeatureIndex(string name)
    {
        for (var i = 0; i < Features.Count; i++)
        {
            if (Features[i].Name == name)
                return i;
        }
        return -1;
    }

    public static double[] FeatureVector(string content, SalienceContext ctx) => Features.Select(f => f.Fn(content, ctx)).ToArray();

    /// <summary>v2 zero-label prediction with the prior weights (or supplied weights / standardisation).</summary>
    public static SaliencePrediction PredictV2(
        string content, SalienceContext ctx, IReadOnlyList<double>? mean = null, IReadOnlyList<double>? sd = null,
        IReadOnlyDictionary<string, double>? weights = null)
    {
        var raw = FeatureVector(content, ctx);
        var w = weights ?? PriorWeights;
        var features = raw.Select((v, j) => mean is not null && sd is not null ? (v - mean[j]) / (sd[j] == 0 ? 1 : sd[j]) : v).ToArray();
        var score = 0.0;
        for (var j = 0; j < features.Length; j++)
            score += features[j] * w.GetValueOrDefault(Features[j].Name);
        return new SaliencePrediction(score, features);
    }

    /// <summary>v1 predictor (novelty / entity / commitment / length / question).</summary>
    public static SalienceBreakdown PredictV1(string content, IReadOnlyList<string>? priors = null)
    {
        priors ??= [];
        var tokens = Tokenizer.Tokenize(content);
        var cur = Bow(content);
        var window = priors.Skip(Math.Max(0, priors.Count - 8)).ToList();
        var maxSim = 0.0;
        foreach (var p in window)
        {
            var s = BowCosine(cur, Bow(p));
            if (s > maxSim)
                maxSim = s;
        }
        var novelty = window.Count > 0 ? Clamp01(1 - maxSim) : 0.5;
        var entityHits = 0;
        var raw = JsText.SplitOnSpace(content).Where(x => x.Length > 0).ToArray();
        for (var i = 0; i < raw.Length; i++)
        {
            var w = NonWordish.Replace(raw[i], "");
            if (w.Length == 0)
                continue;
            if (i != 0 && Capitalised.IsMatch(w))
                entityHits++;
            else if (Digit.IsMatch(w))
                entityHits++;
        }
        var entity = Clamp01(entityHits / 3.0);
        var commitment = Commitment.IsMatch(content) ? 1 : 0;
        var length = Clamp01(tokens.Count / 30.0);
        var question = content.Contains('?', StringComparison.Ordinal) ? 1 : 0;
        var total = Clamp01((V1Weights["novelty"] * novelty) + (V1Weights["entity"] * entity) + (V1Weights["commitment"] * commitment)
            + (V1Weights["length"] * length) + (V1Weights["question"] * question));
        return new SalienceBreakdown(novelty, entity, commitment, length, question, total);
    }

    private static List<(string Token, int Count)> Bow(string text)
    {
        var order = new List<string>();
        var counts = new Dictionary<string, int>();
        foreach (var t in Tokenizer.Tokenize(text))
        {
            if (counts.TryGetValue(t, out var c))
            {
                counts[t] = c + 1;
            }
            else
            {
                counts[t] = 1;
                order.Add(t);
            }
        }
        return order.Select(t => (t, counts[t])).ToList();
    }

    private static double BowCosine(List<(string Token, int Count)> a, List<(string Token, int Count)> b)
    {
        if (a.Count == 0 || b.Count == 0)
            return 0;
        var lookup = b.ToDictionary(x => x.Token, x => x.Count);
        double dot = 0, na = 0, nb = 0;
        foreach (var (k, v) in a)
        {
            na += (double)v * v;
            if (lookup.TryGetValue(k, out var o) && o != 0)
                dot += (double)v * o;
        }
        foreach (var (_, v) in b)
            nb += (double)v * v;
        return na == 0 || nb == 0 ? 0 : dot / Math.Sqrt(na * nb);
    }

    /// <summary>Corpus-level IDF, unsupervised: idf = log1p(N / df).</summary>
    public static (Dictionary<string, double> Idf, int NDocs) BuildCorpusIdf(IEnumerable<string> texts)
    {
        var df = new Dictionary<string, int>();
        var order = new List<string>();
        var n = 0;
        foreach (var t in texts)
        {
            n++;
            foreach (var tok in Tokenizer.Tokenize(t).Distinct())
            {
                if (df.TryGetValue(tok, out var c))
                {
                    df[tok] = c + 1;
                }
                else
                {
                    df[tok] = 1;
                    order.Add(tok);
                }
            }
        }
        var idf = new Dictionary<string, double>();
        foreach (var tok in order)
            idf[tok] = Log1P((double)n / df[tok]);
        return (idf, n);
    }

    /// <summary>AUC with ties counted half: 0.5 = chance, 1.0 = perfect.</summary>
    public static double Auc(IReadOnlyList<double> scores, IReadOnlyList<int> labels)
    {
        var pos = new List<double>();
        var neg = new List<double>();
        for (var i = 0; i < labels.Count; i++)
            (labels[i] == 1 ? pos : neg).Add(scores[i]);
        if (pos.Count == 0 || neg.Count == 0)
            return 0.5;
        double wins = 0, ties = 0;
        foreach (var p in pos)
        {
            foreach (var q in neg)
            {
                if (p > q)
                    wins++;
                else if (p == q)
                    ties++;
            }
        }
        return (wins + (0.5 * ties)) / ((double)pos.Count * neg.Count);
    }
}
