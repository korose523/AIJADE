using Aijade.Memory.Locomo;
using Aijade.Memory.Model;

namespace Aijade.Research.MemoryEval;

/// <summary>One paired contrast with its uncertainty, the conversation being the unit of resampling.</summary>
public sealed record PairedContrast(
    string Key, string Caliber, int K, double A, double B, double Difference, double BootstrapLo, double BootstrapHi,
    double SignFlipP, int ConversationsPositive, int ConversationsNegative, int Conversations);

/// <summary>
/// Uncertainty of the headline contrasts of P3 §5 with the conversation as the unit of dependence: questions of one dialogue
/// share its memory store, so they are not independent. Each contrast is computed per conversation by running the existing
/// ablations on that conversation alone, then summarised by a conversation bootstrap (percentile interval) and an exact
/// sign-flip randomisation test over the paired per-conversation differences (2^n assignments, n = 10 for LoCoMo).
/// </summary>
public static class MemoryUncertainty
{
    public const int K = 8;

    private static readonly string[] GatingConditions = ["predicted-ON", "predicted-OFF", "oracle-ON", "oracle-OFF"];

    /// <param name="conversations">The units of dependence (LoCoMo dialogues; LongMemEval questions).</param>
    /// <param name="iterations">Bootstrap resamples (and Monte Carlo sign flips above 20 units).</param>
    /// <param name="seed">Seed of the resampling.</param>
    /// <param name="conflictPenalty">Overrides the store's conflict penalty in the delivery-track contrasts (1 = off); null keeps the default.</param>
    /// <param name="includeWeights">Also compute the diagnostic-track contrast (it does not depend on the conflict penalty override).</param>
    public static IReadOnlyList<PairedContrast> Run(IReadOnlyList<LocomoConversation> conversations, int iterations = 10000, uint seed = 0x5EED_2026,
        double? conflictPenalty = null, bool includeWeights = true)
    {
        var contrasts = new List<PairedContrast>();

        // Diagnostic track (fixed pool, micro): similarity alone against the default weights.
        if (includeWeights)
        {
            var weights = ParallelMap.Map(conversations, (conv, _) => WeightAblation.Run([conv]));
            var questions = weights.Select(w => (double)w.Questions).ToArray();
            double[] Hits(string key) => [.. weights.Select(w => w.RecallByWeights[key][K] * w.Questions)];
            contrasts.Add(Micro("weights: sim-only vs current", Hits("sim-only"), Hits("current"), questions, iterations, seed));
        }

        // Delivery track (macro): gating ON - OFF under each score mode and salience source.
        foreach (var mode in new[] { RetrievalScoreMode.Additive, RetrievalScoreMode.Standardized })
        {
            var perConv = ParallelMap.Map(conversations, (conv, _) => SalienceDiagnostics.Run([conv], mode, GatingConditions, conflictPenalty).Conditions);
            foreach (var source in new[] { "predicted", "oracle" })
            {
                double[] R(string condition) => [.. perConv.Select(c => c[condition].Recall[K])];
                contrasts.Add(Macro($"gating ({source}, {mode.ToString().ToLowerInvariant()}): ON vs OFF", R($"{source}-ON"), R($"{source}-OFF"), iterations, seed));
            }
        }
        return contrasts;
    }

    /// <summary>Macro caliber: the mean over conversations of per-conversation recall; the contrast is the mean paired difference.</summary>
    public static PairedContrast Macro(string key, double[] a, double[] b, int iterations, uint seed)
    {
        var d = a.Zip(b, (x, y) => x - y).ToArray();
        var (lo, hi) = Bootstrap(d.Length, idx => idx.Average(i => d[i]), iterations, seed);
        return new PairedContrast(key, "macro", K, a.Average(), b.Average(), d.Average(), lo, hi, SignFlip(d, x => x.Average()),
            d.Count(x => x > 0), d.Count(x => x < 0), d.Length);
    }

    /// <summary>Micro caliber: pooled hits over pooled questions; resampling draws whole conversations.</summary>
    public static PairedContrast Micro(string key, double[] hitsA, double[] hitsB, double[] questions, int iterations, uint seed)
    {
        double Rate(double[] hits, IEnumerable<int> idx)
        {
            double h = 0, n = 0;
            foreach (var i in idx)
            {
                h += hits[i];
                n += questions[i];
            }
            return n > 0 ? h / n : double.NaN;
        }
        var all = Enumerable.Range(0, questions.Length).ToArray();
        var (lo, hi) = Bootstrap(questions.Length, idx => Rate(hitsA, idx) - Rate(hitsB, idx), iterations, seed);
        // the sign-flip test permutes which arm each conversation's hits belong to, keeping the pooled caliber
        var d = hitsA.Zip(hitsB, (x, y) => x - y).ToArray();
        var total = questions.Sum();
        var perConv = all.Select(i => (hitsA[i] / questions[i]) - (hitsB[i] / questions[i])).ToArray();
        return new PairedContrast(key, "micro", K, Rate(hitsA, all), Rate(hitsB, all), Rate(hitsA, all) - Rate(hitsB, all), lo, hi,
            SignFlip(d, x => x.Sum() / total), perConv.Count(x => x > 0), perConv.Count(x => x < 0), questions.Length);
    }

    /// <summary>Percentile interval of a statistic over resampled conversations (with replacement).</summary>
    private static (double Lo, double Hi) Bootstrap(int n, Func<IEnumerable<int>, double> statistic, int iterations, uint seed)
    {
        var rng = new Random(unchecked((int)seed));
        var values = new double[iterations];
        var idx = new int[n];
        for (var it = 0; it < iterations; it++)
        {
            for (var j = 0; j < n; j++)
                idx[j] = rng.Next(n);
            values[it] = statistic(idx);
        }
        Array.Sort(values);
        return (values[(int)(0.025 * (iterations - 1))], values[(int)Math.Ceiling(0.975 * (iterations - 1))]);
    }

    /// <summary>
    /// Two-sided sign-flip p-value: exact over the 2^n sign assignments for up to 20 units, otherwise a Monte Carlo estimate
    /// from 10,000 random assignments ((extreme + 1) / (draws + 1)).
    /// </summary>
    public static double SignFlip(double[] d, Func<IEnumerable<double>, double> statistic, uint seed = 0x51F7)
    {
        var n = d.Length;
        if (n > 20)
        {
            const int draws = 10_000;
            var rng = new Random(unchecked((int)seed));
            var obs = Math.Abs(statistic(d));
            var flips = new double[n];
            var count = 0;
            for (var it = 0; it < draws; it++)
            {
                for (var i = 0; i < n; i++)
                    flips[i] = rng.Next(2) == 0 ? -d[i] : d[i];
                if (Math.Abs(statistic(flips)) >= obs - 1e-12)
                    count++;
            }
            return (count + 1) / (double)(draws + 1);
        }
        var observed = Math.Abs(statistic(d));
        var extreme = 0;
        var flipped = new double[n];
        for (var mask = 0; mask < 1 << n; mask++)
        {
            for (var i = 0; i < n; i++)
                flipped[i] = (mask & (1 << i)) != 0 ? -d[i] : d[i];
            if (Math.Abs(statistic(flipped)) >= observed - 1e-12)
                extreme++;
        }
        return extreme / (double)(1 << n);
    }
}
