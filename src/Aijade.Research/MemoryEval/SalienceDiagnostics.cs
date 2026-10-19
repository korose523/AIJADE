using Aijade.Core.Random;
using Aijade.Memory;
using Aijade.Memory.Locomo;
using Aijade.Memory.Model;
using Aijade.Memory.Salience;

namespace Aijade.Research.MemoryEval;

// P3 §5.4: which part of salience gating moves recall — pruning or the encode-time reweighting — and does it depend on
// the quality of the salience signal? Ported from the author's own diag-oracle-vs-predicted-salience / eval-metrics scripts.
// Three salience sources (oracle: gold evidence = 1; predicted: the deployed zero-label predictor; shuffled: the predicted
// values permuted across episodes, same marginal, AUC ≈ 0.5) × gating ON/OFF, plus ON without selective consolidation (the
// pruning dimension isolated). Recall@K is the per-conversation (macro) mean.

public sealed record SalienceCondition(string Key, string Source, bool Gating, bool? Selective);

public sealed record ConversationMetrics(IReadOnlyDictionary<int, double> Recall, double HitScoreMean, double EvidenceSurvival, int PrunedTotal, int PoolSize);

public sealed record SalienceDiagnosticsResult(
    int Conversations, IReadOnlyDictionary<string, double> Auc, IReadOnlyDictionary<string, ConversationMetrics> Conditions);

public static class SalienceDiagnostics
{
    public static readonly IReadOnlyList<int> Ks = [1, 2, 4, 8];

    private static readonly string[] Sources = ["oracle", "predicted", "shuffled"];

    public static readonly IReadOnlyList<SalienceCondition> Conditions =
    [
        new("predicted-ON", "predicted", true, null),
        new("predicted-OFF", "predicted", false, null),
        new("predicted-ON-noprune", "predicted", true, false),
        new("oracle-ON", "oracle", true, null),
        new("oracle-OFF", "oracle", false, null),
        new("oracle-ON-noprune", "oracle", true, false),
        new("shuffled-ON", "shuffled", true, null),
        new("shuffled-OFF", "shuffled", false, null),
    ];

    /// <summary>Gold evidence ids any question cites that resolve in the conversation.</summary>
    public static HashSet<string> GoldEvidence(LocomoConversation conv) =>
        [.. conv.Qa.SelectMany(q => q.Evidence).Where(conv.EvidenceIds.Contains)];

    /// <summary>One retrieval per question (the max-K ranking), hits read off by position; survival and pool from the store.</summary>
    public static ConversationMetrics Measure(BioticMemory memory, LocomoConversation conv, HashSet<string> gold)
    {
        var floor = memory.Config.RetrievalFloor;
        var maxK = Ks.Max();
        var covered = Ks.ToDictionary(k => k, _ => 0);
        var hitScores = new List<double>();
        foreach (var q in conv.Qa)
        {
            var candidates = new HashSet<string>(StringComparer.Ordinal);
            foreach (var e in q.Evidence.Where(conv.EvidenceIds.Contains))
            {
                candidates.Add(e);
                candidates.Add($"fact_{e}");
            }
            var ranking = memory.Retrieve(q.Question, maxK, bump: false);
            var hitAt = Ks.ToDictionary(k => k, _ => false);
            var best = double.NegativeInfinity;
            for (var i = 0; i < ranking.Count; i++)
            {
                var c = ranking[i];
                if (!candidates.Contains(c.Id))
                    continue;
                best = Math.Max(best, c.Score);
                if (c.Score > floor)
                {
                    foreach (var k in Ks.Where(k => i + 1 <= k))
                        hitAt[k] = true;
                }
            }
            foreach (var k in Ks.Where(k => hitAt[k]))
                covered[k]++;
            if (best > double.NegativeInfinity)
                hitScores.Add(best);
        }
        var forgottenGold = memory.Episodes.Count(e => e.Forgotten && gold.Contains(e.Id));
        return new ConversationMetrics(
            Ks.ToDictionary(k => k, k => conv.Qa.Count == 0 ? 0 : (double)covered[k] / conv.Qa.Count),
            hitScores.Count == 0 ? 0 : hitScores.Average(),
            gold.Count == 0 ? 1 : 1 - ((double)forgottenGold / gold.Count),
            memory.Episodes.Count(e => e.Forgotten),
            memory.Episodes.Count(e => !e.Forgotten) + memory.Facts.Count + memory.Procedural.Count + memory.Working.Count);
    }

    /// <summary>Fisher–Yates with the given generator; returns a new list.</summary>
    public static List<T> ShuffledCopy<T>(IReadOnlyList<T> source, Func<double> next)
    {
        var a = source.ToList();
        for (var i = a.Count - 1; i > 0; i--)
        {
            var j = (int)Math.Floor(next() * (i + 1));
            (a[i], a[j]) = (a[j], a[i]);
        }
        return a;
    }

    public static SalienceDiagnosticsResult Run(IReadOnlyList<LocomoConversation> conversations, RetrievalScoreMode mode = RetrievalScoreMode.Standardized,
        IReadOnlyCollection<string>? only = null, double? conflictPenalty = null)
    {
        // conditions are independent of each other, so a subset gives the same numbers for the conditions it keeps
        var conditions = only is null ? Conditions : [.. Conditions.Where(c => only.Contains(c.Key))];
        var perConversation = ParallelMap.Map(conversations, (conv, ci) =>
        {
            var gold = GoldEvidence(conv);
            // the context the store itself uses at encode time
            var predicted = conv.Episodes.Select(ep => 1 / (1 + Math.Exp(-SaliencePredictor.PredictV2(ep.Content, SalienceContext.Empty).Score))).ToList();
            var oracle = conv.Episodes.Select(ep => gold.Contains(ep.Id) ? 1.0 : 0.0).ToList();
            var shuffled = ShuffledCopy(predicted, new Mulberry32(unchecked((uint)(0xC0FFEE + ci))).AsFunc());
            var bySource = new Dictionary<string, List<double>> { ["oracle"] = oracle, ["predicted"] = predicted, ["shuffled"] = shuffled };
            var labels = conv.Episodes.Select(ep => gold.Contains(ep.Id) ? 1 : 0).ToList();
            var index = conv.Episodes.Select((ep, i) => (ep.Id, i)).ToDictionary(p => p.Id, p => p.i);
            var metrics = conditions.ToDictionary(c => c.Key, c =>
            {
                var values = bySource[c.Source];
                var config = MemoryConfig.Default with { Gating = c.Gating ? GatingCoefficients.Default : GatingCoefficients.None, RetrievalScoreMode = mode };
                if (conflictPenalty is { } penalty)
                    config = config with { ConflictPenalty = penalty };
                var memory = LocomoCorpus.BuildMemory(conv, config, ep => index.TryGetValue(ep.Id, out var i) ? values[i] : null, c.Selective);
                return Measure(memory, conv, gold);
            });
            return (BySource: bySource, Labels: labels, Metrics: metrics);
        });
        var acc = conditions.ToDictionary(c => c.Key, c => perConversation.Select(p => p.Metrics[c.Key]).ToList());
        var aucPool = Sources.ToDictionary(src => src, src =>
            (Scores: perConversation.SelectMany(p => p.BySource[src]).ToList(), Labels: perConversation.SelectMany(p => p.Labels).ToList()));
        static ConversationMetrics Mean(List<ConversationMetrics> xs) => new(
            Ks.ToDictionary(k => k, k => xs.Average(x => x.Recall[k])), xs.Average(x => x.HitScoreMean), xs.Average(x => x.EvidenceSurvival),
            (int)Math.Round(xs.Average(x => x.PrunedTotal)), (int)Math.Round(xs.Average(x => x.PoolSize)));
        return new SalienceDiagnosticsResult(conversations.Count,
            aucPool.ToDictionary(p => p.Key, p => SaliencePredictor.Auc(p.Value.Scores, p.Value.Labels)),
            acc.ToDictionary(p => p.Key, p => Mean(p.Value)));
    }
}
