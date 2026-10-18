using Aijade.Memory;
using Aijade.Memory.Locomo;
using Aijade.Memory.Model;
using Aijade.Memory.Retrieval;

namespace Aijade.Research.MemoryEval;

// P4 / J5 retrieval experiments on LoCoMo:
//   1. gating interference — gating ON (DEFAULT) vs OFF (NONE): recall@K and the share of top-K slots that are not gold
//      evidence, under the default and the corrected (recency = 0) weights, for each retrieval score mode;
//   2. the score-combination ablation — the SAME 150-candidate pool per question re-ranked by additive weighted sums,
//      z-score standardisation and Reciprocal Rank Fusion; recall@K, MRR and NDCG@K. The admission criterion
//      (score > retrieval floor) uses the store's own score for every arm, so arms are compared on ranking, not on scale.

/// <summary>Delivered recall@8 (no gating) of one score mode with the conflict penalty on or off, and how much the penalty touches.</summary>
/// <param name="Mode">Score mode.</param>
/// <param name="ConflictPenalty">Multiplier applied to the losing side of a conflicting pair (1 = off).</param>
/// <param name="MacroRecall8">Mean over conversations of per-conversation recall@8.</param>
/// <param name="PenalizedShareOfTop8">Share of delivered top-8 slots whose item was penalised.</param>
/// <param name="GoldPenalizedShare">Share of questions with a gold item that was penalised anywhere in the scanned head.</param>
public sealed record DeliveryCheckRow(RetrievalScoreMode Mode, double ConflictPenalty, double MacroRecall8, double PenalizedShareOfTop8, double GoldPenalizedShare);

public sealed record GatingInterferenceResult(
    RetrievalScoreMode Mode, int Conversations,
    IReadOnlyDictionary<int, (double On, double Off)> Recall, IReadOnlyDictionary<int, (double On, double Off)> DistractorLoad,
    IReadOnlyDictionary<int, (double On, double Off)> RecallCorrected, IReadOnlyDictionary<int, (double On, double Off)> DistractorLoadCorrected);

public sealed record KDependenceResult(RetrievalScoreMode Mode, int Questions, IReadOnlyDictionary<int, double> OrderDiffers,
    IReadOnlyDictionary<int, double> RecallDirect, IReadOnlyDictionary<int, double> RecallFromTop8, IReadOnlyDictionary<int, double> RecallRankOnly,
    double FloorValue, double MaxScore, double MedianTop8Score);

/// <param name="Questions">Questions whose evidence is in the store.</param>
/// <param name="Gold">Mean components of the gold evidence items.</param>
/// <param name="AdditiveTop8">Mean components of the additive top 8 (default weights).</param>
/// <param name="Pool">Mean components of the whole candidate pool.</param>
/// <param name="PoolSd">Mean over questions of each component's standard deviation within the pool. The additive score weights
/// a component by w × SD in effect, the standardised score by w alone.</param>
public sealed record ComponentScalesResult(int Questions, IReadOnlyDictionary<string, double> Gold, IReadOnlyDictionary<string, double> AdditiveTop8,
    IReadOnlyDictionary<string, double> Pool, IReadOnlyDictionary<string, double>? PoolSd = null);

public sealed record ArmResult(string Key, string Combine, bool Primary, IReadOnlyDictionary<int, double> Recall, IReadOnlyDictionary<int, double> Ndcg, double Mrr);

public sealed record CombinationAblationResult(int Questions, IReadOnlyList<ArmResult> Arms);

public static class RetrievalAblation
{
    public static readonly IReadOnlyList<int> InterferenceKs = [1, 2, 3, 4, 6, 8];

    public static readonly IReadOnlyList<int> Ks = [1, 2, 4, 8];

    public const int RerankPool = 150;

    private static double Mean(IEnumerable<double> xs)
    {
        var list = xs.ToList();
        return list.Count == 0 ? 0 : list.Sum() / list.Count;
    }

    private static HashSet<string> Gold(LocomoConversation conv, LocomoQuestion q, bool onlyKnown)
    {
        var set = new HashSet<string>(StringComparer.Ordinal);
        foreach (var e in q.Evidence)
        {
            if (onlyKnown && !conv.EvidenceIds.Contains(e))
                continue;
            set.Add(e);
            set.Add($"fact_{e}");
        }
        return set;
    }

    /// <summary>
    /// Whether the store's ranking is the same for every K, so that the top-k of one top-K ranking equals a top-k retrieval.
    /// True for the standardised and RRF modes (the conflict rerank scans a constant head); false for additive, whose
    /// conflict penalty only scans the top-K, so a candidate's score — and the order — can change with K.
    /// </summary>
    public static bool RankingIndependentOfK(RetrievalScoreMode mode) => mode != RetrievalScoreMode.Additive;

    /// <summary>Evidence recall and distractor load at each K for one store and weight set.</summary>
    private static (Dictionary<int, double> Recall, Dictionary<int, double> Load) AtKs(BioticMemory memory, LocomoConversation conv, RetrievalWeights? weights)
    {
        var maxK = InterferenceKs.Max();
        var prefix = RankingIndependentOfK(memory.Config.RetrievalScoreMode);
        var covered = InterferenceKs.ToDictionary(k => k, _ => 0);
        var total = InterferenceKs.ToDictionary(k => k, _ => 0);
        var other = InterferenceKs.ToDictionary(k => k, _ => 0);
        foreach (var q in conv.Qa)
        {
            var known = Gold(conv, q, onlyKnown: true);
            var any = Gold(conv, q, onlyKnown: false);
            var ranking = prefix ? memory.Retrieve(q.Question, maxK, bump: false, weights) : null;
            foreach (var k in InterferenceKs)
            {
                var top = prefix ? ranking!.Take(k).ToList() : memory.Retrieve(q.Question, k, bump: false, weights);
                if (top.Any(c => known.Contains(c.Id) && c.Score > memory.Config.RetrievalFloor))
                    covered[k]++;
                total[k] += top.Count;
                other[k] += top.Count(c => !any.Contains(c.Id));
            }
        }
        return (InterferenceKs.ToDictionary(k => k, k => conv.Qa.Count == 0 ? 0 : (double)covered[k] / conv.Qa.Count),
            InterferenceKs.ToDictionary(k => k, k => total[k] == 0 ? 0 : (double)other[k] / total[k]));
    }

    /// <summary>
    /// Does recall@k depend on whether the top-k comes from a top-k call or from the first k of a top-8 call? Per mode: the
    /// share of questions whose top-k id lists differ, and recall@k (micro, no gating) under both readings. Zero difference
    /// is what allows a single top-8 retrieval to stand for every k; a difference is the K-dependent conflict penalty.
    /// Also recall@k of the direct call ignoring the retrieval floor (rank only), and the score range of the top-8 against
    /// the floor: an absolute floor that falls inside a fusion's score range truncates hits the ranking itself found.
    /// </summary>
    public static KDependenceResult KDependence(IReadOnlyList<LocomoConversation> conversations, RetrievalScoreMode mode)
    {
        var ks = InterferenceKs.Where(k => k < InterferenceKs.Max()).ToList();
        var perConversation = ParallelMap.Map(conversations, (conv, _) =>
        {
            var memory = LocomoCorpus.BuildMemory(conv, MemoryConfig.Default with { Gating = GatingCoefficients.None, RetrievalScoreMode = mode });
            var differs = ks.ToDictionary(k => k, _ => 0);
            var direct = ks.ToDictionary(k => k, _ => 0);
            var fromTop = ks.ToDictionary(k => k, _ => 0);
            var rankOnly = ks.ToDictionary(k => k, _ => 0);
            var scores = new List<double>();
            foreach (var q in conv.Qa)
            {
                var known = Gold(conv, q, onlyKnown: true);
                bool Hit(IEnumerable<ScoredCandidate> top) => top.Any(c => known.Contains(c.Id) && c.Score > memory.Config.RetrievalFloor);
                var top8 = memory.Retrieve(q.Question, InterferenceKs.Max(), bump: false);
                scores.AddRange(top8.Select(c => c.Score));
                foreach (var k in ks)
                {
                    var a = memory.Retrieve(q.Question, k, bump: false);
                    var b = top8.Take(k).ToList();
                    if (!a.Select(c => c.Id).SequenceEqual(b.Select(c => c.Id)))
                        differs[k]++;
                    if (Hit(a))
                        direct[k]++;
                    if (Hit(b))
                        fromTop[k]++;
                    if (a.Any(c => known.Contains(c.Id)))
                        rankOnly[k]++;
                }
            }
            return (Differs: differs, Direct: direct, FromTop: fromTop, RankOnly: rankOnly, Count: conv.Qa.Count, Scores: scores, Floor: memory.Config.RetrievalFloor);
        });
        var n = perConversation.Sum(p => p.Count);
        Dictionary<int, double> Share(Func<(Dictionary<int, int> Differs, Dictionary<int, int> Direct, Dictionary<int, int> FromTop, Dictionary<int, int> RankOnly, int Count, List<double> Scores, double Floor), Dictionary<int, int>> pick) =>
            ks.ToDictionary(k => k, k => n == 0 ? 0 : (double)perConversation.Sum(p => pick(p)[k]) / n);
        var all = perConversation.SelectMany(p => p.Scores).Order().ToList();
        return new KDependenceResult(mode, n, Share(p => p.Differs), Share(p => p.Direct), Share(p => p.FromTop), Share(p => p.RankOnly),
            perConversation.Length == 0 ? 0 : perConversation[0].Floor, all.Count == 0 ? 0 : all[^1], all.Count == 0 ? 0 : all[all.Count / 2]);
    }

    private static readonly string[] Components = ["similarity", "strength", "recency", "context"];

    /// <summary>
    /// The magnitudes the default additive score adds up: per question, the mean saturated component (similarity, strength
    /// s/(1+s), recency, context) of the gold evidence items, of the additive top 8 (default weights, no conflict penalty or
    /// noise) and of the whole candidate pool; averaged over the questions whose evidence is in the store. No gating.
    /// </summary>
    public static ComponentScalesResult ComponentScales(IReadOnlyList<LocomoConversation> conversations)
    {
        var w = RetrievalWeights.Default;
        static double Pick(ScoreParts p, string c) => c switch
        {
            "similarity" => p.Similarity,
            "strength" => p.Strength,
            "recency" => p.Recency,
            _ => p.Context,
        };
        var perConversation = ParallelMap.Map(conversations, (conv, _) =>
        {
            var memory = LocomoCorpus.BuildMemory(conv, MemoryConfig.Default with { Gating = GatingCoefficients.None, RetrievalScoreMode = RetrievalScoreMode.Standardized });
            var rows = new List<(Dictionary<string, double> Gold, Dictionary<string, double> Top, Dictionary<string, double> Pool, Dictionary<string, double> Sd)>();
            foreach (var q in conv.Qa)
            {
                var known = Gold(conv, q, onlyKnown: true);
                var all = memory.Retrieve(q.Question, int.MaxValue, bump: false);
                var gold = all.Where(c => known.Contains(c.Id)).ToList();
                if (gold.Count == 0)
                    continue;
                var top = all.OrderByDescending(c => (w.Similarity * c.Parts.Similarity) + (w.Strength * c.Parts.Strength) + (w.Recency * c.Parts.Recency) + (w.Context * c.Parts.Context))
                    .Take(8).ToList();
                rows.Add((Components.ToDictionary(c => c, c => gold.Average(x => Pick(x.Parts, c))),
                    Components.ToDictionary(c => c, c => top.Average(x => Pick(x.Parts, c))),
                    Components.ToDictionary(c => c, c => all.Average(x => Pick(x.Parts, c))),
                    Components.ToDictionary(c => c, c => Sd([.. all.Select(x => Pick(x.Parts, c))]))));
            }
            return rows;
        });
        var flat = perConversation.SelectMany(r => r).ToList();
        Dictionary<string, double> Avg(Func<(Dictionary<string, double> Gold, Dictionary<string, double> Top, Dictionary<string, double> Pool, Dictionary<string, double> Sd), Dictionary<string, double>> pick) =>
            Components.ToDictionary(c => c, c => Mean(flat.Select(r => pick(r)[c])));
        return new ComponentScalesResult(flat.Count, Avg(r => r.Gold), Avg(r => r.Top), Avg(r => r.Pool), Avg(r => r.Sd));
    }

    /// <summary>Population standard deviation (the z-scoring of the standardised mode divides by the pool's spread).</summary>
    private static double Sd(double[] xs)
    {
        if (xs.Length == 0)
            return 0;
        var m = xs.Average();
        return Math.Sqrt(xs.Sum(x => (x - m) * (x - m)) / xs.Length);
    }

    /// <summary>
    /// Delivery track without gating, per score mode, with the default conflict penalty and with the penalty switched off. In the
    /// additive mode the penalty scans the top K, in the standardised and RRF modes a constant head of 150 candidates, and the
    /// older side of a conflicting pair loses, so the penalty can act as a recency bias of its own.
    /// </summary>
    public static IReadOnlyList<DeliveryCheckRow> DeliveryCheck(IReadOnlyList<LocomoConversation> conversations)
    {
        var rows = new List<DeliveryCheckRow>();
        foreach (var mode in new[] { RetrievalScoreMode.Additive, RetrievalScoreMode.Standardized })
        {
            foreach (var penalty in new[] { MemoryConfig.Default.ConflictPenalty, 1.0 })
            {
                var perConversation = ParallelMap.Map(conversations, (conv, _) =>
                {
                    var memory = LocomoCorpus.BuildMemory(conv, MemoryConfig.Default with { Gating = GatingCoefficients.None, RetrievalScoreMode = mode, ConflictPenalty = penalty });
                    int hits = 0, slots = 0, penalizedSlots = 0, goldPenalized = 0;
                    foreach (var q in conv.Qa)
                    {
                        var known = Gold(conv, q, onlyKnown: true);
                        var head = memory.Retrieve(q.Question, mode == RetrievalScoreMode.Additive ? 8 : 150, bump: false);
                        var top = head.Take(8).ToList();
                        if (top.Any(c => known.Contains(c.Id) && c.Score > memory.Config.RetrievalFloor))
                            hits++;
                        slots += top.Count;
                        penalizedSlots += top.Count(c => c.Parts.Conflict);
                        if (head.Any(c => known.Contains(c.Id) && c.Parts.Conflict))
                            goldPenalized++;
                    }
                    var n = conv.Qa.Count;
                    return (Recall: n == 0 ? 0 : (double)hits / n, Slots: slots, Penalized: penalizedSlots, GoldPenalized: goldPenalized, Questions: n);
                });
                rows.Add(new DeliveryCheckRow(mode, penalty, Mean(perConversation.Select(c => c.Recall)),
                    perConversation.Sum(c => c.Slots) == 0 ? 0 : (double)perConversation.Sum(c => c.Penalized) / perConversation.Sum(c => c.Slots),
                    perConversation.Sum(c => c.Questions) == 0 ? 0 : (double)perConversation.Sum(c => c.GoldPenalized) / perConversation.Sum(c => c.Questions)));
            }
        }
        return rows;
    }

    public static GatingInterferenceResult GatingInterference(IReadOnlyList<LocomoConversation> conversations, RetrievalScoreMode mode)
    {
        var perConversation = ParallelMap.Map(conversations, (conv, _) =>
        {
            var on = LocomoCorpus.BuildMemory(conv, MemoryConfig.Default with { Gating = GatingCoefficients.Default, RetrievalScoreMode = mode });
            var off = LocomoCorpus.BuildMemory(conv, MemoryConfig.Default with { Gating = GatingCoefficients.None, RetrievalScoreMode = mode });
            return (On: AtKs(on, conv, null), Off: AtKs(off, conv, null), OnC: AtKs(on, conv, RetrievalWeights.Corrected), OffC: AtKs(off, conv, RetrievalWeights.Corrected));
        });
        IReadOnlyDictionary<int, (double, double)> Avg(Func<(Dictionary<int, double> Recall, Dictionary<int, double> Load), Dictionary<int, double>> pick, bool corrected) =>
            InterferenceKs.ToDictionary(k => k, k => (
                Mean(perConversation.Select(c => pick(corrected ? c.OnC : c.On)[k])),
                Mean(perConversation.Select(c => pick(corrected ? c.OffC : c.Off)[k]))));
        return new GatingInterferenceResult(mode, conversations.Count,
            Avg(r => r.Recall, false), Avg(r => r.Load, false), Avg(r => r.Recall, true), Avg(r => r.Load, true));
    }

    private sealed record PoolItem(string Id, double StoreScore, double Similarity, double Strength, double Recency, double Context);

    private sealed record Arm(string Key, string Combine, RetrievalWeights Weights, bool Primary);

    private static readonly RetrievalWeights Zero = new(0, 0, 0, 0, 0);

    private static readonly Arm[] Arms =
    [
        new("current", "additive", RetrievalWeights.Default, true),
        new("sim-only", "additive", Zero with { Similarity = 1 }, true),
        new("no-recency", "additive", RetrievalWeights.Corrected, true),
        new("rrf", "rrf", RetrievalWeights.Default, true),
        new("current-standardized", "standardized", RetrievalWeights.Default, false),
        new("no-recency-standardized", "standardized", RetrievalWeights.Corrected, false),
        new("rrf-no-recency", "rrf", RetrievalWeights.Corrected, false),
        new("store-default", "store-order", RetrievalWeights.Default, false),
        new("sim+ctx", "additive", Zero with { Similarity = 1, Context = 0.4 }, true),
        new("sim+str", "additive", Zero with { Similarity = 1, Strength = 0.6 }, true),
        new("sim-heavy", "additive", Zero with { Similarity = 3, Strength = 0.6, Recency = 0.3, Context = 0.4 }, true),
        new("str-only", "additive", Zero with { Strength = 1 }, true),
        new("rec-only", "additive", Zero with { Recency = 1 }, true),
    ];

    /// <summary>The store exposes saturated strength r/(1+r); the standardised and RRF rules take the raw value r.</summary>
    private static double Unsaturated(double s) => !(s > 0) ? 0 : s >= 1 ? 1e9 : s / (1 - s);

    private static double[] Scores(Arm arm, List<PoolItem> pool)
    {
        switch (arm.Combine)
        {
            case "store-order":
                return [.. pool.Select((_, i) => (double)(pool.Count - i))];
            case "additive":
            {
                var w = arm.Weights;
                return [.. pool.Select(c => (w.Similarity * c.Similarity) + (w.Strength * c.Strength) + (w.Recency * c.Recency) + (w.Context * c.Context))];
            }
            default:
            {
                var rows = pool.Select(c => new RawScoreRow(c.Similarity, Unsaturated(c.Strength), c.Recency, c.Context, 0)).ToList();
                var weights = arm.Weights with { Affect = 0 };
                var fused = arm.Combine == "rrf" ? Scoring.ScoreRrf(rows, weights) : Scoring.ScoreStandardized(rows, weights);
                return [.. fused.Select(f => f.Score)];
            }
        }
    }

    public static CombinationAblationResult CombinationAblation(IReadOnlyList<LocomoConversation> conversations)
    {
        var recall = Arms.ToDictionary(a => a.Key, _ => Ks.ToDictionary(k => k, _ => new List<double>()));
        var ndcg = Arms.ToDictionary(a => a.Key, _ => Ks.ToDictionary(k => k, _ => new List<double>()));
        var rr = Arms.ToDictionary(a => a.Key, _ => new List<double>());
        var questions = 0;
        foreach (var conv in conversations)
        {
            // pure retriever behaviour: no pruning, no reweighting
            var memory = LocomoCorpus.BuildMemory(conv, MemoryConfig.Default with { Gating = GatingCoefficients.None });
            var floor = memory.Config.RetrievalFloor;
            foreach (var q in conv.Qa)
            {
                questions++;
                var pool = memory.Retrieve(q.Question, RerankPool, bump: false)
                    .Select(c => new PoolItem(c.Id, c.Score, c.Parts.Similarity, c.Parts.Strength, c.Parts.Recency, c.Parts.Context)).ToList();
                var gold = Gold(conv, q, onlyKnown: true);
                var goldInPool = pool.Count(c => gold.Contains(c.Id) && c.StoreScore > floor);
                foreach (var arm in Arms)
                {
                    var scores = Scores(arm, pool);
                    // descending; ties broken by the input position (stable, reproducible)
                    var order = Enumerable.Range(0, pool.Count).OrderByDescending(i => scores[i]).ThenBy(i => i).ToList();
                    bool Relevant(int pos) => gold.Contains(pool[order[pos]].Id) && pool[order[pos]].StoreScore > floor;
                    var first = Enumerable.Range(0, order.Count).FirstOrDefault(Relevant, -1);
                    rr[arm.Key].Add(first >= 0 ? 1.0 / (first + 1) : 0);
                    foreach (var k in Ks)
                    {
                        double dcg = 0, idcg = 0;
                        for (var pos = 0; pos < k && pos < order.Count; pos++)
                        {
                            if (Relevant(pos))
                                dcg += 1 / Math.Log2(pos + 2);
                        }
                        for (var pos = 0; pos < Math.Min(k, goldInPool); pos++)
                            idcg += 1 / Math.Log2(pos + 2);
                        ndcg[arm.Key][k].Add(idcg > 0 ? dcg / idcg : 0);
                        recall[arm.Key][k].Add(dcg > 0 ? 1 : 0);
                    }
                }
            }
        }
        return new CombinationAblationResult(questions, [.. Arms.Select(a => new ArmResult(a.Key, a.Combine, a.Primary,
            Ks.ToDictionary(k => k, k => Mean(recall[a.Key][k])), Ks.ToDictionary(k => k, k => Mean(ndcg[a.Key][k])), Mean(rr[a.Key])))]);
    }
}
