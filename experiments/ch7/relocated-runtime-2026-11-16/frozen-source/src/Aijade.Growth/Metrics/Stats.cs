namespace Aijade.Growth.Metrics;

// §5.5 deterministic statistics: bootstrap 95% CIs, Cohen's d and Bonferroni, all resampling driven by a seeded
// mulberry32, so the pilot is byte-for-byte reproducible.

public static class Stats
{
    /// <summary>mulberry32: a small seedable PRNG with floats in [0, 1), bit-identical across runs and platforms.</summary>
    public static Func<double> Mulberry32(double seed) => new Aijade.Core.Random.Mulberry32(Aijade.Core.Js.JsFormat.ToUint32(seed)).AsFunc();

    public static double Mean(IReadOnlyList<double> xs) => xs.Count == 0 ? 0 : xs.Aggregate(0.0, (a, b) => a + b) / xs.Count;

    /// <summary>Sample variance around <paramref name="m"/>; 0 below two elements.</summary>
    public static double Variance(IReadOnlyList<double> xs, double m) =>
        xs.Count < 2 ? 0 : xs.Aggregate(0.0, (a, b) => a + ((b - m) * (b - m))) / (xs.Count - 1);

    /// <summary>Percentile bootstrap 95% CI of the mean: [means[⌊0.025(k−1)⌋], means[⌈0.975(k−1)⌉]] over k seeded resamples.</summary>
    public static (double Lo, double Hi) BootstrapCI(IReadOnlyList<double> values, double seed, int iterations = 2000)
    {
        var n = values.Count;
        if (n == 0)
            return (0, 0);
        var rng = Mulberry32(seed);
        var means = new double[iterations];
        for (var i = 0; i < iterations; i++)
        {
            double s = 0;
            for (var j = 0; j < n; j++)
                s += values[(int)Math.Floor(rng() * n) % n];
            means[i] = s / n;
        }
        Array.Sort(means);
        return (means[(int)Math.Floor(0.025 * (means.Length - 1))], means[(int)Math.Ceiling(0.975 * (means.Length - 1))]);
    }

    /// <summary>Cohen's d with the pooled standard deviation; 0 when a sample has fewer than two elements or the pooled SD is 0.</summary>
    public static double CohensD(IReadOnlyList<double> a, IReadOnlyList<double> b)
    {
        int na = a.Count, nb = b.Count;
        if (na < 2 || nb < 2)
            return 0;
        double ma = Mean(a), mb = Mean(b);
        var pooled = Math.Sqrt((((na - 1) * Variance(a, ma)) + ((nb - 1) * Variance(b, mb))) / (na + nb - 2));
        return pooled == 0 ? 0 : (ma - mb) / pooled;
    }

    /// <summary>Bonferroni (the paper specifies it, not Holm / BH): α/m and whether each p rejects.</summary>
    public static (double CorrectedAlpha, IReadOnlyList<bool> Rejected) Bonferroni(IReadOnlyList<double> pValues, double alpha = 0.05)
    {
        var corrected = alpha / pValues.Count;
        return (corrected, pValues.Select(p => p <= corrected).ToList());
    }
}
