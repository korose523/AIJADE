using Aijade.Memory.Contracts;

namespace Aijade.Memory.Hac;

// v7 §9 Homeostatic Active Consolidation. The 7-dimensional endogenous state z_t is a computational homeostatic variable,
// NOT the hormone vector shown (H2c) to contribute ≈0 to recall, so it never feeds durability or salience. It drives only
// the write gate (§9.3) and retrieval degradation noise (§9.5) — a cost growing with cognitive load, which keeps HAC
// falsifiable. All randomness is seeded.

/// <summary>Endogenous state z = [a, v, d, n, s, c, b]: arousal, vigilance, drive, novelty, safety, cognitive load, boredom.</summary>
public readonly record struct HacState(double A, double V, double D, double N, double S, double C, double B)
{
    public double[] ToArray() => [A, V, D, N, S, C, B];

    public static HacState From(IReadOnlyList<double> x) => new(x[0], x[1], x[2], x[3], x[4], x[5], x[6]);

    public static HacState Uniform(double x) => new(x, x, x, x, x, x, x);
}

/// <summary>Predicted future-utility features of a candidate memory (§9.2).</summary>
public readonly record struct UtilityFeatures(double I, double N, double R, double G, double P, double C, double Q);

public sealed record HacWeights(double Alpha = 1, double Beta = 1, double Gamma = 1, double Delta = 1, double Eta = 1, double Lambda = 1, double Mu = 1);

public enum HacDynamics
{
    Fixed,
    Learned,
    Ablated,
}

public sealed record HacConfig
{
    public HacDynamics Dynamics { get; init; } = HacDynamics.Fixed;
    public double ZMin { get; init; }
    public double ZMax { get; init; } = 1;
    public double[][] A { get; init; } = Diag7(0.9);
    public double[][] B { get; init; } = Diag7(0.1);
    public double[][] C { get; init; } = Diag7(0.1);
    public HacState Setpoint { get; init; } = HacState.Uniform(0.5);
    public HacState Wz { get; init; } = HacState.Uniform(1);
    public HacWeights UtilityWeights { get; init; } = new();
    public double[] GateW { get; init; } = Enumerable.Repeat(0.1, 21).ToArray();
    public double GateB { get; init; }
    public double Sigma0 { get; init; } = 0.05;
    public double Sigma1 { get; init; } = 0.15;

    /// <summary>Opt-in; when false the content-salience gating ablation is untouched.</summary>
    public bool Enabled { get; init; }

    public static HacConfig Default { get; } = new();

    public static double[][] Diag7(double x) => Enumerable.Range(0, 7).Select(i => Enumerable.Range(0, 7).Select(j => i == j ? x : 0).ToArray()).ToArray();
}

/// <summary>The seven hard preconditions of any write (§9.3).</summary>
public sealed record WriteConstraints(bool HasSource, bool UserPolicyAllows, bool NotPromptInjection, bool NotDuplicate, bool TypeValid, bool ConflictFlagged, double BudgetRemaining);

public sealed record WriteDecision(double P, bool HardOk, IReadOnlyList<double> Phi, string? Reason = null);

public sealed record ReplayCandidate(string Id, double U, double D, IReadOnlyDictionary<string, double> Sim);

public static class HacMath
{
    private static double[] MatVec(double[][] m, double[] v)
    {
        var output = new double[7];
        for (var i = 0; i < 7; i++)
        {
            var s = 0.0;
            for (var j = 0; j < 7; j++)
                s += m[i][j] * v[j];
            output[i] = s;
        }
        return output;
    }

    private static double Clamp01(double x) => Math.Min(1, Math.Max(0, x));

    /// <summary>z_{t+1} = clip(A·z + B·g(x) + C·u + ε). Process noise ε ∈ [−0.02, 0.02] is drawn first, one value per dimension.</summary>
    public static HacState Step(HacState z, HacState stimulus, HacState action, HacConfig cfg, Func<double> rng)
    {
        if (cfg.Dynamics == HacDynamics.Ablated)
            return z;
        var eps = new double[7];
        for (var d = 0; d < 7; d++)
            eps[d] = (rng() - 0.5) * 0.04;
        var az = MatVec(cfg.A, z.ToArray());
        var bs = MatVec(cfg.B, stimulus.ToArray());
        var cu = MatVec(cfg.C, action.ToArray());
        var next = new double[7];
        for (var d = 0; d < 7; d++)
        {
            var s = 0.0;
            s += az[d];
            s += bs[d];
            s += cu[d];
            s += eps[d];
            next[d] = Math.Min(cfg.ZMax, Math.Max(cfg.ZMin, s));
        }
        return HacState.From(next);
    }

    /// <summary>e = W_z ⊙ (z − z*).</summary>
    public static HacState HomeostaticError(HacState z, HacConfig cfg)
    {
        var zz = z.ToArray();
        var w = cfg.Wz.ToArray();
        var sp = cfg.Setpoint.ToArray();
        return HacState.From(Enumerable.Range(0, 7).Select(i => w[i] * (zz[i] - sp[i])).ToArray());
    }

    /// <summary>U = αI + βN + γR + δG + ηP − λC − μQ.</summary>
    public static double PredictUtility(UtilityFeatures f, HacWeights w) =>
        (w.Alpha * f.I) + (w.Beta * f.N) + (w.Gamma * f.R) + (w.Delta * f.G) + (w.Eta * f.P) - (w.Lambda * f.C) - (w.Mu * f.Q);

    public static Validation CanWriteHard(WriteConstraints c)
    {
        if (!c.HasSource)
            return Validation.Fail("no source (v7 §6)");
        if (!c.UserPolicyAllows)
            return Validation.Fail("user policy forbids");
        if (!c.NotPromptInjection)
            return Validation.Fail("possible prompt injection");
        if (!c.NotDuplicate)
            return Validation.Fail("duplicate");
        if (!c.TypeValid)
            return Validation.Fail("type validation failed");
        if (!c.ConflictFlagged)
            return Validation.Fail("conflict not flagged");
        if (c.BudgetRemaining <= 0)
            return Validation.Fail("write budget exceeded");
        return Validation.Pass;
    }

    /// <summary>φ = [utility7 | state7 | error7].</summary>
    public static double[] GateFeatures(UtilityFeatures f, HacState z, HacState e) =>
        [f.I, f.N, f.R, f.G, f.P, f.C, f.Q, .. z.ToArray(), .. e.ToArray()];

    /// <summary>p = σ(wᵀφ + b); any failing hard constraint forces p = 0 — the hard rules dominate the learned gate.</summary>
    public static WriteDecision Decide(UtilityFeatures f, HacState z, HacState e, WriteConstraints constraints, HacConfig cfg)
    {
        var hard = CanWriteHard(constraints);
        var phi = GateFeatures(f, z, e);
        if (!hard.Ok)
            return new WriteDecision(0, false, phi, hard.Reason);
        var dot = cfg.GateB;
        for (var i = 0; i < phi.Length; i++)
            dot += cfg.GateW[i] * phi[i];
        return new WriteDecision(1 / (1 + Math.Exp(-dot)), true, phi);
    }

    /// <summary>Greedy S* = argmax Σ(U+D) − ρ·Σ sim(i, j): add the best marginal gain until none is positive.</summary>
    public static IReadOnlyList<string> SelectReplay(IReadOnlyList<ReplayCandidate> candidates, double rho, int? budget = null)
    {
        var limit = budget ?? candidates.Count;
        var chosen = new List<string>();
        var remaining = candidates.ToList();
        while (chosen.Count < limit && remaining.Count > 0)
        {
            var bestIdx = -1;
            var bestGain = double.NegativeInfinity;
            for (var i = 0; i < remaining.Count; i++)
            {
                var redundancy = 0.0;
                foreach (var id in chosen)
                    redundancy += remaining[i].Sim.GetValueOrDefault(id);
                var gain = remaining[i].U + remaining[i].D - (rho * redundancy);
                if (gain > bestGain)
                {
                    bestGain = gain;
                    bestIdx = i;
                }
            }
            if (bestGain <= 0)
                break;
            chosen.Add(remaining[bestIdx].Id);
            remaining.RemoveAt(bestIdx);
        }
        return chosen;
    }

    /// <summary>Box–Muller standard normal from two non-zero uniforms.</summary>
    private static double StandardNormal(Func<double> rng)
    {
        double u = 0, v = 0;
        while (u == 0)
            u = rng();
        while (v == 0)
            v = rng();
        return Math.Sqrt(-2 * Math.Log(u)) * Math.Cos(2 * Math.PI * v);
    }

    /// <summary>ξ ~ N(0, σ0² + σ1·c): variance grows with cognitive load, so load measurably degrades retrieval.</summary>
    public static double RetrievalDegradation(double load, HacConfig cfg, Func<double> rng) =>
        Math.Sqrt(Math.Pow(cfg.Sigma0, 2) + (cfg.Sigma1 * Math.Max(0, load))) * StandardNormal(rng);

    /// <summary>Appraisal → stimulus g(x), every dimension bounded into [0, 1]. Feeds z only, never durability / salience.</summary>
    public static HacState AppraisalToStimulus(Appraisal appraisal)
    {
        var d = appraisal.Dimensions;
        return new HacState(Clamp01(d.Arousal), Clamp01(d.GoalRelevance), Clamp01((d.Valence + 1) / 2), Clamp01(d.Novelty),
            Clamp01((d.Control + 1) / 2), Clamp01(d.Urgency), Clamp01(1 - d.Arousal));
    }

    /// <summary>Feedback → action u: positive explicit feedback raises safety and lowers load; implicit is sign-neutral.</summary>
    public static HacState FeedbackToAction(FeedbackEvent feedback)
    {
        double sign = feedback.Valence is { } v ? Math.Sign(v) : feedback.Type == "explicit" ? 1 : 0;
        var mag = feedback.Value is { } value ? Clamp01(Math.Abs(value) / 5) : 0.2;
        var delta = sign * mag;
        var mid = (HacConfig.Default.ZMin + HacConfig.Default.ZMax) / 2;
        return new HacState(mid, mid, mid, mid, Clamp01(mid + delta), Clamp01(mid - delta), mid);
    }

    public static EndogenousStateVector ToSnapshotState(HacState z) => new(z.A, z.V, z.D, z.N, z.S, z.C, z.B);
}

/// <summary>Holds the mutable z_t of a running agent.</summary>
public sealed class HacController(HacConfig config, HacState? initial = null)
{
    public HacConfig Config { get; } = config;

    public HacState State { get; private set; } = initial ?? HacState.Uniform((config.ZMin + config.ZMax) / 2);

    public HacState Step(HacState stimulus, HacState action, Func<double> rng) => State = HacMath.Step(State, stimulus, action, Config, rng);

    public HacState Error() => HacMath.HomeostaticError(State, Config);

    public WriteDecision Decide(UtilityFeatures f, WriteConstraints constraints) => HacMath.Decide(f, State, Error(), constraints, Config);

    public double Degradation(Func<double> rng, double? load = null) => HacMath.RetrievalDegradation(load ?? State.C, Config, rng);

    /// <summary>Drive z through the stimulus channel only (neutral action).</summary>
    public HacState StepAppraisal(Appraisal appraisal, Func<double> rng)
    {
        var mid = (Config.ZMin + Config.ZMax) / 2;
        return State = HacMath.Step(State, HacMath.AppraisalToStimulus(appraisal), HacState.Uniform(mid), Config, rng);
    }

    /// <summary>Immutable, content-addressed snapshot of the current state.</summary>
    public StateSnapshot Snapshot(string source, double takenAt, string agentId = "", string userScope = "")
    {
        var state = HacMath.ToSnapshotState(State);
        var fingerprint = ContractValidation.StateSnapshotFingerprint(state, source, takenAt);
        return new StateSnapshot($"snap_{source}_{Aijade.Core.Js.JsFormat.Number(takenAt)}_{fingerprint}", agentId, userScope, takenAt, state, source, true, fingerprint);
    }
}
