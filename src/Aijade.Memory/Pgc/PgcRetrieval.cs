using Aijade.Core.Random;

namespace Aijade.Memory.Pgc;

// PGC retrieval gating, the opposite direction of the write gate:  r̂(m, q, s_t) = r(m, q) · (1 + β_τ · s_t) + ε,
// ε ~ N(0, (σ0 + σ1·c_t)²). The paper predicts that rising strain c_t lowers declarative retrieval accuracy; testing that
// requires reproducible noise, so it is drawn from a seeded mulberry32 and the seed is recorded with every result.

public sealed record RetrievalGatingInput(string MemoryId, string QueryId, Tau Tau, double BaseScore, PgcState4 State, uint Seed);

/// <summary>A gated score with its amplification, noise, σ and the seed that reproduces the noise on replay.</summary>
public sealed record RetrievalGatingResult(
    string MemoryId, string QueryId, Tau Tau, double BaseScore, double GatedScore, double AmplificationFactor, double Noise, double Sigma, uint Seed)
{
    /// <summary>Always true: the seed is part of every result (the random_seed_recorded flag).</summary>
    public bool RandomSeedRecorded { get; } = true;
}

/// <summary>A reproducible N(0, σ²) sampler with σ = σ0 + σ1·c.</summary>
public sealed class RetrievalNoiseSampler(uint seed)
{
    /// <summary>JavaScript's Number.EPSILON (2^−52), not .NET's double.Epsilon (the smallest subnormal).</summary>
    private const double JsNumberEpsilon = 2.220446049250313e-16;

    private readonly Func<double> _rng = new Mulberry32(seed).AsFunc();

    public uint Seed { get; } = seed;

    public double Next(PgcState4 state)
    {
        var sigma = PgcRetrieval.Sigma0 + (PgcRetrieval.Sigma1 * state.C);
        // Box–Muller; the first uniform is floored at machine epsilon to avoid log(0).
        var u1 = Math.Max(_rng(), JsNumberEpsilon);
        var u2 = _rng();
        return Math.Sqrt(-2 * Math.Log(u1)) * Math.Cos(2 * Math.PI * u2) * sigma;
    }
}

public static class PgcRetrieval
{
    public const double Sigma0 = 0.02;
    public const double Sigma1 = 0.10;

    public static PgcState4 Beta(Tau tau) => tau switch
    {
        Tau.Episodic => new(0.10, 0.05, 0.00, 0.00),
        Tau.Affective => new(-0.05, 0.20, 0.00, 0.00),
        Tau.Procedural => new(0.00, -0.10, 0.15, 0.00),
        _ => new(0.05, 0.10, 0.05, 0.00),
    };

    /// <summary>Gate one memory's relevance: amplify or damp by the state, then add the reproducible noise.</summary>
    public static RetrievalGatingResult Gate(RetrievalGatingInput input)
    {
        var beta = Beta(input.Tau);
        var s = input.State;
        var dot = (beta.A * s.A) + (beta.C * s.C) + (beta.D * s.D) + (beta.F * s.F);
        var amplification = 1 + dot;
        var sigma = Sigma0 + (Sigma1 * s.C);
        var noise = new RetrievalNoiseSampler(input.Seed).Next(s);
        return new RetrievalGatingResult(input.MemoryId, input.QueryId, input.Tau, input.BaseScore, (input.BaseScore * amplification) + noise, amplification, noise, sigma, input.Seed);
    }

    /// <summary>The same τ, state and seed for every candidate (so each result replays from the recorded seed).</summary>
    public static IReadOnlyList<RetrievalGatingResult> GateBatch(string queryId, Tau tau, PgcState4 state, uint seed, IEnumerable<(string MemoryId, double BaseScore)> candidates) =>
        candidates.Select(c => Gate(new RetrievalGatingInput(c.MemoryId, queryId, tau, c.BaseScore, state, seed))).ToList();
}
