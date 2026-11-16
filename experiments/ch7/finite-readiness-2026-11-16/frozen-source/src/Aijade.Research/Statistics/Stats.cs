using Aijade.Core.Random;

namespace Aijade.Research.Statistics;

// Every function is pure: randomness enters only through an explicit seed (Mulberry32), so results are
// reproducible bit for bit across runs. Numeric behaviour is pinned by golden tests in
// Aijade.Tests, so published RQ-C numbers can be recomputed exactly.

/// <summary>Point estimate with a (default 95 %) interval.</summary>
public readonly record struct ConfidenceInterval(double Mean, double Lo, double Hi)
{
    public static ConfidenceInterval Undefined => new(double.NaN, double.NaN, double.NaN);
}

/// <summary>A skill collapsed to its success / call counts — the resampling unit.</summary>
public readonly record struct SkillCount(int Succ, int Calls);

public readonly record struct CellMeans(double A, double B, double C, double D);

public sealed record DidResult(double Estimate, ConfidenceInterval Ci, CellMeans CellMeans);

public sealed record ChiSquareResult(double Statistic, double P, int[,] Table, int Df);

public sealed record LogOddsInteractionResult(double Estimate, double Se, double Z, double P);

public sealed record McNemarResult(
    int A, int B, int C, int D, int NPairs, double ChiSquare, double PChiSquare, double? PExact, double P, bool UsedExact);

public sealed record HolmStep(string Label, double P, double AdjustedP, bool Reject);

public readonly record struct RiskDifferenceCi(double Estimate, double Lo, double Hi);

public static class Stats
{
    /// <summary>JavaScript's <c>Number.EPSILON</c> (2⁻⁵²) — not <see cref="double.Epsilon"/>, which is the smallest subnormal.</summary>
    private const double MachineEpsilon = 2.220446049250313e-16;

    public const uint DefaultBootstrapSeed = 0x9E3779B9;
    public const uint DefaultDidSeed = 0x1234567;

    /// <summary>Linear-interpolated percentile of an already-sorted array.</summary>
    private static double Percentile(List<double> sorted, double p)
    {
        if (sorted.Count == 0)
            return double.NaN;
        var idx = (sorted.Count - 1) * p;
        var lo = (int)Math.Floor(idx);
        var hi = (int)Math.Ceiling(idx);
        return lo == hi ? sorted[lo] : sorted[lo] + ((sorted[hi] - sorted[lo]) * (idx - lo));
    }

    /// <summary>95 % percentile interval of a bootstrap distribution; non-finite draws carry no information and are dropped.</summary>
    private static ConfidenceInterval CiFromDistribution(IEnumerable<double> dist, double mean)
    {
        var finite = dist.Where(double.IsFinite).ToList();
        if (finite.Count == 0)
            return new ConfidenceInterval(mean, double.NaN, double.NaN);
        finite.Sort();
        return new ConfidenceInterval(mean, Percentile(finite, 0.025), Percentile(finite, 0.975));
    }

    private static int Draw(Mulberry32 rng, int n) => (int)Math.Floor(rng.Next() * n);

    private static double Mean(IReadOnlyList<double> xs)
    {
        if (xs.Count == 0)
            return double.NaN;
        var s = 0.0;
        foreach (var x in xs)
            s += x;
        return s / xs.Count;
    }

    /// <summary>Percentile bootstrap CI for the mean (see <see cref="BcaBootstrapCi"/> for a coverage-corrected interval).</summary>
    public static ConfidenceInterval BootstrapCi(IReadOnlyList<double> values, int iterations = 10000, uint seed = DefaultBootstrapSeed)
    {
        var n = values.Count;
        if (n == 0)
            return ConfidenceInterval.Undefined;
        var rng = new Mulberry32(seed);
        var means = new double[iterations];
        for (var i = 0; i < iterations; i++)
        {
            var s = 0.0;
            for (var j = 0; j < n; j++)
                s += values[Draw(rng, n)];
            means[i] = s / n;
        }
        return CiFromDistribution(means, Mean(values));
    }

    /// <summary>DiD = mean(D) − mean(C) − mean(B) + mean(A) over per-unit values, with a bootstrap CI (descriptive only).</summary>
    public static DidResult DifferenceInDifferences(
        IReadOnlyList<double> a, IReadOnlyList<double> b, IReadOnlyList<double> c, IReadOnlyList<double> d,
        int iterations = 10000, uint seed = DefaultDidSeed)
    {
        var rng = new Mulberry32(seed);
        var point = Mean(d) - Mean(c) - Mean(b) + Mean(a);
        var dist = new double[iterations];
        for (var i = 0; i < iterations; i++)
        {
            var dA = Resample(a, rng);
            var dB = Resample(b, rng);
            var dC = Resample(c, rng);
            var dD = Resample(d, rng);
            dist[i] = Mean(dD) - Mean(dC) - Mean(dB) + Mean(dA);
        }
        return new DidResult(point, CiFromDistribution(dist, point), new CellMeans(Mean(a), Mean(b), Mean(c), Mean(d)));
    }

    private static double[] Resample(IReadOnlyList<double> xs, Mulberry32 rng)
    {
        var n = xs.Count;
        var output = new double[n];
        for (var i = 0; i < n; i++)
            output[i] = xs[Draw(rng, n)];
        return output;
    }

    /// <summary>Horner evaluation ((c0·x + c1)·x + c2)… — a fixed operation order.</summary>
    private static double Horner(ReadOnlySpan<double> coefficients, double x)
    {
        var r = coefficients[0];
        for (var i = 1; i < coefficients.Length; i++)
            r = (r * x) + coefficients[i];
        return r;
    }

    /// <summary>Abramowitz &amp; Stegun 7.1.26 error-function approximation (max error ≈ 1.5e-7).</summary>
    public static double Erf(double x)
    {
        var sign = x < 0 ? -1 : 1;
        var ax = Math.Abs(x);
        var t = 1 / (1 + (0.3275911 * ax));
        var y = 1 - (Horner([1.061405429, -1.453152027, 1.421413741, -0.284496736, 0.254829592], t) * t * Math.Exp(-ax * ax));
        return sign * y;
    }

    public static double NormalCdf(double x) => 0.5 * (1 + Erf(x / Math.Sqrt(2)));

    /// <summary>Standard normal survival function P(Z &gt; x), accurate deep into the tail (≈1e-15 relative).</summary>
    public static double NormalSf(double x)
    {
        if (double.IsNaN(x))
            return double.NaN;
        if (double.IsPositiveInfinity(x))
            return 0;
        if (double.IsNegativeInfinity(x))
            return 1;
        if (x >= 2)
            return NormalSfTailCf(x);
        if (x <= -2)
            return 1 - NormalSfTailCf(-x);
        return 0.5 * (1 - ErfSeries(x / Math.Sqrt(2)));
    }

    /// <summary>Laplace continued fraction, depth 128 (converged to the last bit for x ≥ 2).</summary>
    private static double NormalSfTailCf(double x)
    {
        var f = 0.0;
        for (var k = 128; k >= 1; k--)
            f = k / (x + f);
        return Math.Exp(-x * x / 2) / Math.Sqrt(2 * Math.PI) / (x + f);
    }

    private static double ErfSeries(double x)
    {
        var x2 = x * x;
        var term = x;
        var sum = x;
        for (var n = 1; n < 200; n++)
        {
            term *= -x2 / n;
            var add = term / ((2 * n) + 1);
            sum += add;
            if (Math.Abs(add) <= MachineEpsilon * Math.Abs(sum))
                break;
        }
        return 2 / Math.Sqrt(Math.PI) * sum;
    }

    public static double TwoSidedNormalP(double z) => 2 * NormalSf(Math.Abs(z));

    /// <summary>Inverse standard normal CDF — Acklam's rational approximation (relative error ≈ 1.15e-9).</summary>
    public static double NormalQuantile(double p)
    {
        if (p <= 0)
            return double.NegativeInfinity;
        if (p >= 1)
            return double.PositiveInfinity;
        ReadOnlySpan<double> a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00];
        ReadOnlySpan<double> b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01];
        ReadOnlySpan<double> c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00];
        ReadOnlySpan<double> d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00];
        const double plow = 0.02425;
        const double phigh = 1 - plow;
        if (p < plow)
        {
            var q = Math.Sqrt(-2 * Math.Log(p));
            return Horner(c, q) / ((Horner(d, q) * q) + 1);
        }
        if (p <= phigh)
        {
            var q = p - 0.5;
            var r = q * q;
            return Horner(a, r) * q / ((Horner(b, r) * r) + 1);
        }
        var qq = Math.Sqrt(-2 * Math.Log(1 - p));
        return -Horner(c, qq) / ((Horner(d, qq) * qq) + 1);
    }

    /// <summary>Pearson chi-square for [[a, b], [c, d]] (Yates-corrected by default). A zero margin yields p = 1, not NaN.</summary>
    public static ChiSquareResult ChiSquare2x2(int a, int b, int c, int d, bool useYates = true)
    {
        var table = new[,] { { a, b }, { c, d } };
        double n = a + b + c + d;
        if (n == 0)
            return new ChiSquareResult(0, 1, table, 1);
        var cross = ((double)a * d) - ((double)b * c);
        var denom = (double)(a + b) * (c + d) * (a + c) * (b + d);
        if (denom == 0)
            return new ChiSquareResult(0, 1, table, 1);
        var stat = n * cross * cross / denom;
        if (useYates)
        {
            var adj = Math.Max(0, Math.Abs(cross) - (n / 2));
            stat = n * adj * adj / denom;
        }
        var p = stat <= 0 ? 1 : TwoSidedNormalP(Math.Sqrt(stat));
        return new ChiSquareResult(stat, p, table, 1);
    }

    /// <summary>Pooled precision = Σsucc / Σcalls.</summary>
    public static double PooledPrecision(IReadOnlyList<SkillCount> skills)
    {
        long calls = 0, succ = 0;
        foreach (var s in skills)
        {
            calls += s.Calls;
            succ += s.Succ;
        }
        return calls == 0 ? double.NaN : (double)succ / calls;
    }

    /// <summary>Percentile bootstrap CI for pooled precision, resampling skills with replacement.</summary>
    public static ConfidenceInterval BootstrapPooledPrecision(IReadOnlyList<SkillCount> skills, int iterations = 10000, uint seed = DefaultBootstrapSeed)
    {
        var n = skills.Count;
        if (n == 0)
            return ConfidenceInterval.Undefined;
        var rng = new Mulberry32(seed);
        var means = new double[iterations];
        for (var i = 0; i < iterations; i++)
            means[i] = ResamplePooled(skills, rng);
        return CiFromDistribution(means, PooledPrecision(skills));
    }

    private static double ResamplePooled(IReadOnlyList<SkillCount> skills, Mulberry32 rng)
    {
        var n = skills.Count;
        if (n == 0)
            return double.NaN;
        long succ = 0, calls = 0;
        for (var j = 0; j < n; j++)
        {
            var s = skills[Draw(rng, n)];
            succ += s.Succ;
            calls += s.Calls;
        }
        return calls == 0 ? double.NaN : (double)succ / calls;
    }

    /// <summary>DiD on pooled precision, consistent with the headline four-cell table.</summary>
    public static DidResult PooledDifferenceInDifferences(
        IReadOnlyList<SkillCount> a, IReadOnlyList<SkillCount> b, IReadOnlyList<SkillCount> c, IReadOnlyList<SkillCount> d,
        int iterations = 10000, uint seed = DefaultDidSeed)
    {
        var rng = new Mulberry32(seed);
        var point = PooledPrecision(d) - PooledPrecision(c) - PooledPrecision(b) + PooledPrecision(a);
        var dist = new double[iterations];
        for (var i = 0; i < iterations; i++)
        {
            // Fixed draw order: D, C, B, A.
            var rd = ResamplePooled(d, rng);
            var rc = ResamplePooled(c, rng);
            var rb = ResamplePooled(b, rng);
            var ra = ResamplePooled(a, rng);
            dist[i] = rd - rc - rb + ra;
        }
        return new DidResult(point, CiFromDistribution(dist, point),
            new CellMeans(PooledPrecision(a), PooledPrecision(b), PooledPrecision(c), PooledPrecision(d)));
    }

    private static (double A, double B, double C, double D) Haldane(double a, double b, double c, double d) =>
        a == 0 || b == 0 || c == 0 || d == 0 ? (a + 0.5, b + 0.5, c + 0.5, d + 0.5) : (a, b, c, d);

    public static double OddsRatio(double a, double b, double c, double d)
    {
        var (A, B, C, D) = Haldane(a, b, c, d);
        return A * D / (B * C);
    }

    public static double RiskDifference(double a, double b, double c, double d)
    {
        var (A, B, C, D) = Haldane(a, b, c, d);
        return (A / (A + B)) - (C / (C + D));
    }

    public static double CramersV(double chiSquareStat, double n) => n <= 0 ? double.NaN : Math.Sqrt(Math.Max(0, chiSquareStat) / n);

    public static double CohensH(double p1, double p2)
    {
        static double AsinSqrt(double p) => Math.Asin(Math.Sqrt(Math.Min(1, Math.Max(0, p))));
        return (2 * AsinSqrt(p1)) - (2 * AsinSqrt(p2));
    }

    /// <summary>Log product-ratio of a 2×2 factorial table with Woolf SE and a two-sided normal p.</summary>
    public static LogOddsInteractionResult LogOddsInteraction(double a, double b, double c, double d)
    {
        var (A, B, C, D) = Haldane(a, b, c, d);
        var estimate = Math.Log(A * D / (B * C));
        var se = Math.Sqrt((1 / A) + (1 / B) + (1 / C) + (1 / D));
        var z = se == 0 ? 0 : estimate / se;
        var p = se == 0 ? (estimate == 0 ? 1 : 0) : TwoSidedNormalP(z);
        return new LogOddsInteractionResult(estimate, se, z, p);
    }

    /// <summary>McNemar's paired test; the exact binomial test is used when fewer than 25 pairs are discordant.</summary>
    public static McNemarResult McNemarExactOrChi(int a, int b, int c, int d)
    {
        var nPairs = a + b + c + d;
        var discordant = b + c;
        var stat = discordant == 0 ? 0 : Math.Pow(Math.Abs(b - c) - 1, 2) / discordant;
        var pChi = stat <= 0 ? 1 : TwoSidedNormalP(Math.Sqrt(stat));
        double? pExact = null;
        var usedExact = false;
        if (discordant is > 0 and < 25)
        {
            pExact = ExactBinomialTwoSided(b, discordant);
            usedExact = true;
        }
        var p = usedExact && pExact is { } exact ? exact : pChi;
        return new McNemarResult(a, b, c, d, nPairs, stat, pChi, pExact, p, usedExact);
    }

    private static double ExactBinomialTwoSided(int x, int n)
    {
        double Pmf(int k) => Math.Exp(LnChoose(n, k) - (n * Math.Log(2)));
        var lo = Math.Min(x, n - x);
        var hi = Math.Max(x, n - x);
        var p = 0.0;
        for (var k = 0; k <= lo; k++)
            p += Pmf(k);
        for (var k = hi; k <= n; k++)
            p += Pmf(k);
        return Math.Min(1, p);
    }

    private static double LnChoose(int n, int k)
    {
        if (k < 0 || k > n)
            return double.NegativeInfinity;
        k = Math.Min(k, n - k);
        var s = 0.0;
        for (var i = 1; i <= k; i++)
            s += Math.Log((double)(n - k + i) / i);
        return s;
    }

    /// <summary>Holm step-down. Non-finite p-values are not testable: they get AdjustedP = NaN and do not count towards m.</summary>
    public static IReadOnlyList<HolmStep> HolmBonferroni(IReadOnlyList<double> pValues, double alpha = 0.05, IReadOnlyList<string>? labels = null)
    {
        var testable = pValues.Select((p, i) => (P: p, I: i)).Where(e => double.IsFinite(e.P)).OrderBy(e => e.P).ToList();
        var adjusted = new Dictionary<int, double>();
        var prev = 0.0;
        for (var k = 0; k < testable.Count; k++)
        {
            var monotone = Math.Max(Math.Min(1, testable[k].P * (testable.Count - k)), prev);
            adjusted[testable[k].I] = monotone;
            prev = monotone;
        }
        return pValues.Select((p, i) =>
        {
            var has = adjusted.TryGetValue(i, out var adj);
            var label = labels is not null && i < labels.Count ? labels[i] : i.ToString(System.Globalization.CultureInfo.InvariantCulture);
            return new HolmStep(label, p, has ? adj : double.NaN, has && adj <= alpha);
        }).ToList();
    }

    /// <summary>BCa (bias-corrected accelerated) bootstrap CI for the mean.</summary>
    public static ConfidenceInterval BcaBootstrapCi(IReadOnlyList<double> values, int iterations = 10000, uint seed = DefaultBootstrapSeed, double confidence = 0.95)
    {
        var n = values.Count;
        if (n < 2)
            return ConfidenceInterval.Undefined;
        var rng = new Mulberry32(seed);
        var orig = Mean(values);
        var means = new double[iterations];
        for (var i = 0; i < iterations; i++)
        {
            var s = 0.0;
            for (var j = 0; j < n; j++)
                s += values[Draw(rng, n)];
            means[i] = s / n;
        }
        var finite = means.Where(double.IsFinite).ToList();
        if (finite.Count == 0)
            return new ConfidenceInterval(orig, double.NaN, double.NaN);
        finite.Sort();

        var below = finite.Count(m => m <= orig);
        var frac = Math.Min(1 - (1.0 / (finite.Count + 1)), Math.Max(1.0 / (finite.Count + 1), (double)below / finite.Count));
        var z0 = NormalQuantile(frac);

        var total = 0.0;
        foreach (var v in values)
            total += v;
        double sumCubed = 0, sumSq = 0;
        foreach (var v in values)
        {
            var dev = orig - ((total - v) / (n - 1));
            sumCubed += dev * dev * dev;
            sumSq += dev * dev;
        }
        var acc = sumSq == 0 ? 0 : sumCubed / (6 * Math.Pow(sumSq, 1.5));

        var alphaLo = (1 - confidence) / 2;
        var zLo = NormalQuantile(alphaLo);
        var zHi = NormalQuantile(1 - alphaLo);
        var pLo = NormalCdf(z0 + ((z0 + zLo) / (1 - (acc * (z0 + zLo)))));
        var pHi = NormalCdf(z0 + ((z0 + zHi) / (1 - (acc * (z0 + zHi)))));
        return new ConfidenceInterval(orig,
            Percentile(finite, Math.Min(1, Math.Max(0, pLo))),
            Percentile(finite, Math.Min(1, Math.Max(0, pHi))));
    }

    private static (double Lo, double Hi) WilsonInterval(double succ, double n, double z)
    {
        if (n == 0)
            return (double.NaN, double.NaN);
        var p = succ / n;
        var z2 = z * z;
        var denom = 1 + (z2 / n);
        var centre = (p + (z2 / (2 * n))) / denom;
        var half = z * Math.Sqrt((p * (1 - p) / n) + (z2 / (4 * n * n))) / denom;
        return (centre - half, centre + half);
    }

    /// <summary>Newcombe hybrid-score interval for p1 − p2 with p1 = a/(a+b), p2 = c/(c+d), clamped to [−1, 1].</summary>
    public static RiskDifferenceCi RiskDifferenceInterval(double a, double b, double c, double d, double confidence = 0.95)
    {
        var n1 = a + b;
        var n2 = c + d;
        if (n1 == 0 || n2 == 0)
            return new RiskDifferenceCi(double.NaN, double.NaN, double.NaN);
        var z = NormalQuantile(1 - ((1 - confidence) / 2));
        var p1 = a / n1;
        var p2 = c / n2;
        var estimate = p1 - p2;
        var (l1, u1) = WilsonInterval(a, n1, z);
        var (l2, u2) = WilsonInterval(c, n2, z);
        var lo = estimate - Math.Sqrt(Math.Pow(p1 - l1, 2) + Math.Pow(u2 - p2, 2));
        var hi = estimate + Math.Sqrt(Math.Pow(u1 - p1, 2) + Math.Pow(p2 - l2, 2));
        return new RiskDifferenceCi(estimate, Math.Max(-1, lo), Math.Min(1, hi));
    }

    /// <summary>Minimum detectable effect (proportion scale) of a two-proportion z-test at n per cell.</summary>
    public static double MinDetectableEffectProportion(double nPerCell, double p0 = 0.5, double alpha = 0.05, double power = 0.8)
    {
        var zA = NormalQuantile(1 - (alpha / 2));
        var zB = NormalQuantile(power);
        double F(double delta)
        {
            var p1 = p0 - (delta / 2);
            var p2 = p0 + (delta / 2);
            var v = (p1 * (1 - p1)) + (p2 * (1 - p2));
            return (Math.Pow(zA + zB, 2) * v / (delta * delta)) - nPerCell;
        }
        if (nPerCell <= 0)
            return double.NaN;
        if (F(1) > 0)
            return 1;
        double lo = 1e-6, hi = 1;
        for (var i = 0; i < 100; i++)
        {
            var mid = (lo + hi) / 2;
            if (F(mid) > 0)
                lo = mid;
            else
                hi = mid;
        }
        return (lo + hi) / 2;
    }

    /// <summary>Achieved power of the two-proportion z-test for effect δ at n per cell.</summary>
    public static double PowerForEffectProportion(double delta, double nPerCell, double p0 = 0.5, double alpha = 0.05)
    {
        if (nPerCell <= 0)
            return double.NaN;
        var p1 = p0 + delta;
        if (p1 <= 0 || p1 >= 1)
            return double.NaN;
        var se = Math.Sqrt((p0 * (1 - p0) / nPerCell) + (p1 * (1 - p1) / nPerCell));
        if (se <= 0)
            return double.NaN;
        return NormalCdf(((p1 - p0) / se) - NormalQuantile(1 - (alpha / 2)));
    }
}
