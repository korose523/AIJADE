using Aijade.Core.Js;

namespace Aijade.Memory.Development;

// v8 §47 DIVE, the Developmental Intrinsic Value Engine. Interest emerges from novelty, knowledge gaps, challenge,
// identity / user relevance and future utility, and is suppressed by cost, risk and repetitive narrowing. Never a bare
// topic list: novelty alone degrades to random browsing, user relevance alone to sycophancy, utility alone to a tool.
// Pure and deterministic; runtime opt-in is decided by the store / config layer.

/// <summary>Candidate interest components, each in [0, 1]. Cost, risk and repetition are inhibitory.</summary>
public sealed record InterestComponents(
    double Novelty, double KnowledgeGap, double IdentityRelevance, double Challenge, double UserRelevance, double FutureUtility,
    double Cost, double Risk, double RepetitionPenalty);

public sealed record InterestWeights(
    double WNovelty = 1, double WGap = 1.2, double WIdentity = 1.2, double WChallenge = 0.8, double WUser = 1, double WUtility = 0.8,
    double WCost = 1, double WRisk = 1.5, double WRepetition = 1)
{
    public static InterestWeights Default { get; } = new();
}

public enum InterestSignal
{
    /// <summary>A new thread is created → latent.</summary>
    Seed,
    /// <summary>Curiosity probe → active.</summary>
    Probe,
    /// <summary>Sustained inquiry → stays active.</summary>
    Deepen,
    /// <summary>Park it to revisit later → incubating.</summary>
    Incubate,
    /// <summary>Back from incubation → active.</summary>
    Revisit,
    /// <summary>Questions answered → satisfied.</summary>
    Satisfy,
    /// <summary>Novelty frontier exhausted → satisfied.</summary>
    Saturate,
    /// <summary>Deliberately dropped → abandoned (reason recorded).</summary>
    Abandon,
}

/// <summary>The fields of an InterestThread that portfolio selection reads.</summary>
public sealed record PortfolioCandidate(string Id, string Subject, double IntrinsicValue, double IdentityRelevance, double UserRelevance);

/// <param name="Budget">Maximum threads selected (the daily exploration budget).</param>
/// <param name="DiversityWeight">λ, bonus for a subject not yet chosen.</param>
/// <param name="RedundancyWeight">ρ, penalty for a subject already chosen.</param>
/// <param name="IdentityReserve">Fraction of the budget reserved for identity-linked, non-user-utilitarian threads.</param>
/// <param name="ForbiddenSubjects">Subjects never auto-promoted to a sustained interest.</param>
public sealed record PortfolioOptions(
    int Budget, double DiversityWeight = 0.2, double RedundancyWeight = 0.3, double IdentityReserve = 0.2, IReadOnlyList<string>? ForbiddenSubjects = null);

public sealed record PortfolioSelection(IReadOnlyList<string> Selected, IReadOnlyList<string> IdentityReserved, IReadOnlyList<string> Forbidden);

public static class Dive
{
    private static double Clamp01(double x) => Math.Min(1, Math.Max(0, x));

    /// <summary>
    /// §47.1 V = w_n·N + w_g·G + w_i·I + w_c·C + w_r·R + w_u·U − w_k·K − w_s·S − w_p·P, clamped to [0, 1].
    /// Both attraction and inhibition are always applied.
    /// </summary>
    public static double IntrinsicValue(InterestComponents c, InterestWeights? weights = null)
    {
        var w = weights ?? InterestWeights.Default;
        var attraction = (w.WNovelty * Clamp01(c.Novelty)) + (w.WGap * Clamp01(c.KnowledgeGap)) + (w.WIdentity * Clamp01(c.IdentityRelevance))
            + (w.WChallenge * Clamp01(c.Challenge)) + (w.WUser * Clamp01(c.UserRelevance)) + (w.WUtility * Clamp01(c.FutureUtility));
        var inhibition = (w.WCost * Clamp01(c.Cost)) + (w.WRisk * Clamp01(c.Risk)) + (w.WRepetition * Clamp01(c.RepetitionPenalty));
        return Clamp01(attraction - inhibition);
    }

    private static bool Terminal(string status) => status is "satisfied" or "abandoned";

    /// <summary>§47.2 InterestThread lifecycle. Returns null for an illegal transition, so the caller can record it.</summary>
    public static string? NextStatus(string current, InterestSignal signal) => signal switch
    {
        InterestSignal.Seed => "latent",
        InterestSignal.Probe or InterestSignal.Deepen or InterestSignal.Revisit => Terminal(current) ? null : "active",
        InterestSignal.Incubate => current == "active" ? "incubating" : null,
        InterestSignal.Satisfy or InterestSignal.Saturate => current is "active" or "incubating" ? "satisfied" : null,
        InterestSignal.Abandon => Terminal(current) ? null : "abandoned",
        _ => null,
    };

    private static bool SameSubject(string a, string b) => JsText.Lower(JsText.Trim(a)) == JsText.Lower(JsText.Trim(b));

    /// <summary>
    /// §47.4 portfolio selection: reserve part of the budget for identity-linked threads (identity ≥ 0.6, user ≤ 0.4), hard-exclude
    /// forbidden subjects, then greedily add the candidate maximising value + λ (new subject) or − ρ (repeated subject).
    /// </summary>
    public static PortfolioSelection SelectPortfolio(IReadOnlyList<PortfolioCandidate> candidates, PortfolioOptions opts)
    {
        var forbiddenSubjects = opts.ForbiddenSubjects ?? [];
        bool IsForbidden(PortfolioCandidate c) => forbiddenSubjects.Any(f => SameSubject(f, c.Subject));
        var allowed = candidates.Where(c => !IsForbidden(c)).ToList();
        var forbidden = candidates.Where(IsForbidden).Select(c => c.Id).ToList();

        var reserveCount = Math.Max(0, (int)Math.Floor(opts.Budget * Clamp01(opts.IdentityReserve)));
        // Stable sort: equal values keep their input order.
        var identityPool = allowed.Where(c => c.IdentityRelevance >= 0.6 && c.UserRelevance <= 0.4).OrderByDescending(c => c.IntrinsicValue).ToList();
        var identityReserved = identityPool.Take(reserveCount).Select(c => c.Id).ToList();

        var chosen = new List<string>();
        var chosenSet = new HashSet<string>(StringComparer.Ordinal);
        foreach (var id in identityReserved)
        {
            if (chosenSet.Add(id))
                chosen.Add(id);
        }
        var chosenSubjects = identityPool.Take(reserveCount).Select(c => c.Subject).ToList();
        var pool = allowed.Where(c => !chosenSet.Contains(c.Id)).ToList();

        while (chosenSet.Count < opts.Budget && pool.Count > 0)
        {
            var bestIdx = -1;
            var bestScore = double.NegativeInfinity;
            for (var i = 0; i < pool.Count; i++)
            {
                var c = pool[i];
                var novel = !chosenSubjects.Any(s => SameSubject(s, c.Subject));
                var score = c.IntrinsicValue + (novel ? opts.DiversityWeight : -opts.RedundancyWeight);
                if (score > bestScore)
                {
                    bestScore = score;
                    bestIdx = i;
                }
            }
            var picked = pool[bestIdx];
            pool.RemoveAt(bestIdx);
            if (chosenSet.Add(picked.Id))
                chosen.Add(picked.Id);
            chosenSubjects.Add(picked.Subject);
        }
        return new PortfolioSelection(chosen, identityReserved, forbidden);
    }
}
