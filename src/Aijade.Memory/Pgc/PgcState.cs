namespace Aijade.Memory.Pgc;

// Four-dimensional endogenous state s = [a, c, d, f] (arousal, strain, drive, fatigue), Euler-integrated:
//   s_{t+1} = clip( s_t + Δt · [ −Λ(s_t − s*) + W·u_t + B·σ(s_t) ] )
// with the "fourth specification" parameters (the earlier one provably could never reach the commit threshold).

/// <summary>State vector, each dimension in [0, 1].</summary>
public readonly record struct PgcState4(double A, double C, double D, double F)
{
    public double[] ToArray() => [A, C, D, F];

    public static PgcState4 FromClipped(double[] v) => new(Clip(v[0]), Clip(v[1]), Clip(v[2]), Clip(v[3]));

    private static double Clip(double x) => x < 0 ? 0 : x > 1 ? 1 : x;
}

/// <summary>The four physiological memory types τ.</summary>
public enum Tau
{
    Episodic,
    Affective,
    Procedural,
    Semantic,
}

public sealed record PgcStateSpec(
    PgcState4 SStar, PgcState4 Lambda, double[][] W, double[][] B, double SigmaK, double SigmaX0, double Dt,
    double FatigueThreshold, double IdleSeconds)
{
    public static PgcStateSpec Default { get; } = new(
        new PgcState4(0.12, 0.10, 0.08, 0.05),
        new PgcState4(0.22, 0.18, 0.20, 0.26),
        [[0.90, 0.05, 0.00, 0.00], [0.10, 0.85, 0.05, 0.00], [0.00, 0.10, 0.80, 0.05], [0.00, 0.00, 0.10, 0.75]],
        [[0.00, 0.00, 0.10, -0.35], [-0.15, 0.00, -0.28, 0.10], [0.08, -0.25, 0.00, -0.40], [0.00, 0.12, 0.05, 0.00]],
        10.0, 0.5, 1.0, 0.72, 300);
}

public enum StimulusFeature
{
    StimArousalScore,
    PersonaEnergyScore,
    StimStrainScore,
    UncertaintyLoadScore,
    StimDriveScore,
    SkillNeedScore,
    StimFatigueScore,
    IdleAndOverloadScore,
}

public static class PgcStateMath
{
    public static double Logistic(double x, double k, double x0) => 1 / (1 + Math.Exp(-k * (x - x0)));

    /// <summary>Feature → per-dimension weights, in declaration order (the summation order).</summary>
    public static readonly IReadOnlyList<(StimulusFeature Feature, PgcState4 Weights)> StimulusWeights =
    [
        (StimulusFeature.StimArousalScore, new(0.70, 0.05, 0.00, 0.00)),
        (StimulusFeature.PersonaEnergyScore, new(0.20, 0.00, 0.00, 0.00)),
        (StimulusFeature.StimStrainScore, new(0.00, 0.75, 0.00, 0.05)),
        (StimulusFeature.UncertaintyLoadScore, new(0.00, 0.15, 0.00, 0.00)),
        (StimulusFeature.StimDriveScore, new(0.00, 0.05, 0.72, 0.00)),
        (StimulusFeature.SkillNeedScore, new(0.00, 0.00, 0.20, 0.00)),
        (StimulusFeature.StimFatigueScore, new(0.00, 0.08, 0.00, 0.78)),
        (StimulusFeature.IdleAndOverloadScore, new(0.00, 0.00, 0.00, 0.18)),
    ];

    /// <summary>Features → stimulus u ∈ [0,1]^4: weighted sum per dimension, logistic (k = 9, x0 = 0.5), clip. Missing = 0.</summary>
    public static PgcState4 EvaluateStimulus(IReadOnlyDictionary<StimulusFeature, double> features, double k = 9.0, double x0 = 0.5)
    {
        double a = 0, c = 0, d = 0, f = 0;
        foreach (var (feat, w) in StimulusWeights)
        {
            if (!features.TryGetValue(feat, out var v) || double.IsNaN(v))
                continue;
            a += w.A * v;
            c += w.C * v;
            d += w.D * v;
            f += w.F * v;
        }
        return PgcState4.FromClipped([Logistic(a, k, x0), Logistic(c, k, x0), Logistic(d, k, x0), Logistic(f, k, x0)]);
    }
}

/// <summary>Deterministic integrator: same initial state and stimulus sequence ⇒ same trajectory.</summary>
public sealed class PgcStateIntegrator(PgcState4? initial = null, PgcStateSpec? spec = null)
{
    private readonly PgcStateSpec _spec = spec ?? PgcStateSpec.Default;

    public PgcState4 State { get; private set; } = initial ?? (spec ?? PgcStateSpec.Default).SStar;

    public PgcState4 Step(PgcState4 stimulus, double? dt = null)
    {
        var h = dt ?? _spec.Dt;
        var s = State.ToArray();
        var sStar = _spec.SStar.ToArray();
        var lam = _spec.Lambda.ToArray();
        var u = stimulus.ToArray();
        var sig = s.Select(x => PgcStateMath.Logistic(x, _spec.SigmaK, _spec.SigmaX0)).ToArray();
        var drive = MatVec(_spec.W, u);
        var interaction = MatVec(_spec.B, sig);
        var next = new double[4];
        for (var i = 0; i < 4; i++)
        {
            var recovery = -lam[i] * (s[i] - sStar[i]);
            var delta = recovery + drive[i] + interaction[i];
            next[i] = s[i] + (h * delta);
        }
        State = PgcState4.FromClipped(next);
        return State;
    }

    public PgcState4 Reset() => State = _spec.SStar;

    /// <summary>Fatigue above threshold and idle long enough → reset to baseline (offline consolidation).</summary>
    public bool MaybeTriggerOfflineConsolidation(double idleSeconds)
    {
        if (State.F > _spec.FatigueThreshold && idleSeconds > _spec.IdleSeconds)
        {
            Reset();
            return true;
        }
        return false;
    }

    private static double[] MatVec(double[][] m, double[] u)
    {
        var output = new double[4];
        for (var i = 0; i < 4; i++)
        {
            var acc = 0.0;
            for (var j = 0; j < 4; j++)
                acc += m[i][j] * u[j];
            output[i] = acc;
        }
        return output;
    }
}
