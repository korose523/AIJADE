namespace Aijade.Growth.Metrics;

// §5.4 evaluation metrics as pure functions. Three are the paper's previously unformalised indicators — Future
// Utility@Budget, EffectiveProactivity and Growth Coherence; Evidence Precision / Recall, Contradiction Retention and
// False Consolidation Rate complete the memory + proactivity block. No global state, no clock, no randomness.

public sealed record TaskResult(double Weight, double Utility);

/// <param name="Net">The paper's EP = AcceptedUseful − Intrusive − Unjustified.</param>
/// <param name="Rate">EP_rate = net / N ∈ [−1, 1] (0 when N = 0).</param>
/// <param name="ActiveCount">N = AcceptedUseful + Intrusive + Unjustified.</param>
public sealed record ProactivityResult(double Net, double Rate, double ActiveCount);

public sealed record PrecisionRecall(double Precision, double Recall);

public static class Formulas
{
    /// <summary>
    /// FUB = Σ w_i·u_i / Σ w_i over future tasks, provided usable = min(storedCount, budget) &gt; 0; 0 when nothing usable or
    /// Σ w = 0. Callers truncate the stored set to the budget.
    /// </summary>
    public static double FutureUtilityAtBudget(double budget, double storedCount, IReadOnlyList<TaskResult> taskResults)
    {
        if (Math.Min(storedCount, budget) <= 0)
            return 0;
        var totalW = taskResults.Aggregate(0.0, (acc, r) => acc + r.Weight);
        if (totalW <= 0)
            return 0;
        return taskResults.Aggregate(0.0, (acc, r) => acc + (r.Weight * r.Utility)) / totalW;
    }

    /// <summary>EP net and rate; the active count is reported so "never proactive" cannot pass as low intrusion.</summary>
    public static ProactivityResult EffectiveProactivity(double acceptedUseful, double intrusive, double unjustified)
    {
        var net = acceptedUseful - intrusive - unjustified;
        var n = acceptedUseful + intrusive + unjustified;
        return new ProactivityResult(net, n <= 0 ? 0 : net / n, n);
    }

    /// <summary>GC = explained / total changes; 0 when there were no changes (no evidenced growth).</summary>
    public static double GrowthCoherence(double totalChanges, double explainedChanges) => totalChanges <= 0 ? 0 : explainedChanges / totalChanges;

    /// <summary>Precision = TP / retrieved (0 when nothing retrieved); Recall = TP / relevant (1 when nothing is relevant).</summary>
    public static PrecisionRecall EvidencePrecisionRecall(IReadOnlyList<bool> retrievedIsRelevant, double relevantTotal)
    {
        var tp = retrievedIsRelevant.Count(r => r);
        var fp = retrievedIsRelevant.Count - tp;
        return new PrecisionRecall(tp + fp == 0 ? 0 : (double)tp / (tp + fp), relevantTotal <= 0 ? 1 : tp / relevantTotal);
    }

    /// <summary>CR = retained / contradiction cases; 1 when there were none.</summary>
    public static double ContradictionRetention(double contradictionCases, double retainedCases) =>
        contradictionCases <= 0 ? 1 : retainedCases / contradictionCases;

    /// <summary>FCR = consolidated false / false facts; 0 when there were none. Lower is better (H2).</summary>
    public static double FalseConsolidationRate(double falseFacts, double consolidatedFalse) => falseFacts <= 0 ? 0 : consolidatedFalse / falseFacts;
}
