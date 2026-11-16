using System.Text.RegularExpressions;

using Aijade.Memory.Model;
using Aijade.Core.Js;

namespace Aijade.Memory.Retrieval;


/// <summary>One candidate's raw cue values, before weighting and before standardisation.</summary>
public readonly record struct RawScoreRow(double Similarity, double StrengthRaw, double Recency, double Context, double Affect);

public sealed record FusedScore(double Score, ScoreParts RawParts, ScoreZ Z);

public interface IDedupable
{
    CandidateKind Kind { get; }
    string Id { get; }
    string Content { get; }
    double CreatedAt { get; }
}

public static class Scoring
{
    /// <summary>The RRF damping constant (Cormack, Clarke &amp; Büttcher, SIGIR 2009), not tuned on any corpus.</summary>
    public const int RrfK = 60;

    private static readonly Regex Spaces = new(JsText.Space + "+", JsText.Options(false));

    public static double Jaccard(IReadOnlyList<string> a, IReadOnlyList<string> b)
    {
        if (a.Count == 0 && b.Count == 0)
            return 0;
        var sa = a.ToHashSet();
        var sb = b.ToHashSet();
        var inter = sa.Count(sb.Contains);
        var union = sa.Count + sb.Count - inter;
        return union == 0 ? 0 : (double)inter / union;
    }

    /// <summary>
    /// Collapse candidates whose whitespace-normalised content is identical. The survivor is chosen by provenance
    /// (episode before fact) and then age; losers stay in the store and are only excluded from ranking.
    /// </summary>
    public static (List<T> Kept, Dictionary<string, List<string>> Absorbed) CollapseDuplicateContent<T>(IEnumerable<T> items)
        where T : IDedupable
    {
        var buckets = new Dictionary<string, List<T>>();
        var order = new List<string>();
        foreach (var it in items)
        {
            var key = JsText.Lower(Spaces.Replace(JsText.Trim(it.Content), " "));
            if (buckets.TryGetValue(key, out var bucket))
            {
                bucket.Add(it);
            }
            else
            {
                buckets[key] = [it];
                order.Add(key);
            }
        }
        var kept = new List<T>();
        var absorbed = new Dictionary<string, List<string>>();
        foreach (var key in order)
        {
            var bucket = buckets[key];
            if (bucket.Count == 1)
            {
                kept.Add(bucket[0]);
                continue;
            }
            // Stable sort, as JavaScript's Array.prototype.sort: equal (kind, createdAt) keep input order.
            var sorted = bucket.OrderBy(x => (int)x.Kind).ThenBy(x => x.CreatedAt).ToList();
            kept.Add(sorted[0]);
            absorbed[sorted[0].Id] = sorted.Skip(1).Select(x => x.Id).ToList();
        }
        return (kept, absorbed);
    }

    /// <summary>Legacy "additive" score: raw weighted sum of individually squashed components.</summary>
    public static (double Score, ScoreParts Parts) ScoreAdditive(RawScoreRow r, RetrievalWeights w)
    {
        var sStrength = r.StrengthRaw / (1 + r.StrengthRaw);
        var sContext = Math.Max(0, Math.Min(1, r.Context));
        var sAffect = Math.Max(0, r.Affect);
        var score = (w.Similarity * r.Similarity) + (w.Strength * sStrength) + (w.Recency * r.Recency) + (w.Context * sContext) + (w.Affect * sAffect);
        return (score, new ScoreParts { Similarity = r.Similarity, Strength = sStrength, Recency = r.Recency, Context = sContext, Affect = sAffect });
    }

    private static (double[] Sim, double[] Str, double[] Rec, double[] Ctx, double[] Aff) Saturate(IReadOnlyList<RawScoreRow> rows)
    {
        var n = rows.Count;
        double[] sim = new double[n], str = new double[n], rec = new double[n], ctx = new double[n], aff = new double[n];
        for (var i = 0; i < n; i++)
        {
            var r = rows[i];
            sim[i] = r.Similarity;
            str[i] = r.StrengthRaw / (1 + r.StrengthRaw);
            rec[i] = r.Recency;
            ctx[i] = Math.Max(0, Math.Min(1, r.Context));
            aff[i] = Math.Max(0, r.Affect);
        }
        return (sim, str, rec, ctx, aff);
    }

    /// <summary>Each component z-scored across the pool, then weighted; shifted so the pool minimum is 0.</summary>
    public static List<FusedScore> ScoreStandardized(IReadOnlyList<RawScoreRow> rows, RetrievalWeights w)
    {
        var n = rows.Count;
        if (n == 0)
            return [];
        var (sim, str, rec, ctx, aff) = Saturate(rows);
        var zSim = ZScore(sim);
        var zStr = ZScore(str);
        var zRec = ZScore(rec);
        var zCtx = ZScore(ctx);
        var raw = new double[n];
        var min = double.PositiveInfinity;
        for (var i = 0; i < n; i++)
        {
            raw[i] = (w.Similarity * zSim[i]) + (w.Strength * zStr[i]) + (w.Recency * zRec[i]) + (w.Context * zCtx[i]) + (w.Affect * 0);
            if (raw[i] < min)
                min = raw[i];
        }
        var shift = min < 0 ? -min : 0;
        var output = new List<FusedScore>(n);
        for (var i = 0; i < n; i++)
        {
            output.Add(new FusedScore(raw[i] + shift,
                new ScoreParts { Similarity = sim[i], Strength = str[i], Recency = rec[i], Context = ctx[i], Affect = aff[i] },
                new ScoreZ(zSim[i], zStr[i], zRec[i], zCtx[i])));
        }
        return output;
    }

    /// <summary>Reciprocal Rank Fusion: score_i = Σ_c w_c / (k + rank_i(c)), ranks over the whole pool.</summary>
    public static List<FusedScore> ScoreRrf(IReadOnlyList<RawScoreRow> rows, RetrievalWeights w, int k = RrfK)
    {
        var n = rows.Count;
        if (n == 0)
            return [];
        var (sim, str, rec, ctx, aff) = Saturate(rows);
        var rSim = CompetitionRanksDescending(sim);
        var rStr = CompetitionRanksDescending(str);
        var rRec = CompetitionRanksDescending(rec);
        var rCtx = CompetitionRanksDescending(ctx);
        var output = new List<FusedScore>(n);
        for (var i = 0; i < n; i++)
        {
            var cSim = w.Similarity / (k + rSim[i]);
            var cStr = w.Strength / (k + rStr[i]);
            var cRec = w.Recency / (k + rRec[i]);
            var cCtx = w.Context / (k + rCtx[i]);
            var score = 0.0;
            score += cSim;
            score += cStr;
            score += cRec;
            score += cCtx;
            output.Add(new FusedScore(score,
                new ScoreParts { Similarity = sim[i], Strength = str[i], Recency = rec[i], Context = ctx[i], Affect = aff[i] },
                new ScoreZ(cSim, cStr, cRec, cCtx)));
        }
        return output;
    }

    /// <summary>1-based ranks, largest first; tied values share the mean of the ranks they span.</summary>
    public static double[] CompetitionRanksDescending(IReadOnlyList<double> xs)
    {
        var n = xs.Count;
        var output = new double[n];
        if (n == 0)
            return output;
        var order = Enumerable.Range(0, n).OrderByDescending(i => xs[i]).ToArray();
        var i0 = 0;
        while (i0 < n)
        {
            var j = i0;
            while (j + 1 < n && xs[order[j + 1]] == xs[order[i0]])
                j++;
            var r = (i0 + j + 2) / 2.0;
            for (var t = i0; t <= j; t++)
                output[order[t]] = r;
            i0 = j + 1;
        }
        return output;
    }

    /// <summary>Population z-scores; a zero-variance column maps to 0 rather than 0/0.</summary>
    public static double[] ZScore(IReadOnlyList<double> xs)
    {
        var n = xs.Count;
        if (n == 0)
            return [];
        var mean = 0.0;
        foreach (var x in xs)
            mean += x;
        mean /= n;
        var variance = 0.0;
        foreach (var x in xs)
        {
            var d = x - mean;
            variance += d * d;
        }
        variance /= n;
        var output = new double[n];
        if (!(variance > 0))
            return output;
        var sd = Math.Sqrt(variance);
        for (var i = 0; i < n; i++)
            output[i] = (xs[i] - mean) / sd;
        return output;
    }

    private static readonly Regex Negation = new(
        JsText.Boundary + "(?:not|never|no|don't|isn't|can't|won't|didn't|doesn't|wouldn't|couldn't|shouldn't|aren't)" + JsText.Boundary,
        JsText.Options(ignoreCase: true));

    private static readonly Regex EntitySplit = new("[^A-Za-z0-9]+", JsText.Options(false));
    private static readonly Regex Capitalised = new("^[A-Z][a-z]+$", JsText.Options(false));
    private static readonly Regex Digit = new("[0-9]", JsText.Options(false));

    /// <summary>Tokens that can act as a key entity: a capitalised word or any digit-bearing token.</summary>
    public static HashSet<string> EntityTokens(string text)
    {
        var set = new HashSet<string>();
        foreach (var raw in EntitySplit.Split(text))
        {
            if (raw.Length == 0)
                continue;
            if (Capitalised.IsMatch(raw) || Digit.IsMatch(raw))
                set.Add(JsText.Lower(raw));
        }
        return set;
    }

    public static bool HasNegation(string text) => Negation.IsMatch(text);

    /// <summary>Two candidates conflict when they share a key entity and only one of them is negated.</summary>
    public static bool DetectConflict(string a, string b) =>
        EntityTokens(a).Overlaps(EntityTokens(b)) && HasNegation(a) != HasNegation(b);
}
