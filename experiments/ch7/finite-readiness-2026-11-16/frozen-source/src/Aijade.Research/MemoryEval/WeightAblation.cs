using Aijade.Memory;
using Aijade.Memory.Locomo;
using Aijade.Memory.Model;

namespace Aijade.Research.MemoryEval;

// The
// P3 experiment: re-rank the SAME candidate pool under different component weights, and count how many of the
// top-8 are newer than the gold evidence.

public sealed record AblationWeights(string Key, double Similarity, double Strength, double Recency, double Context);

public sealed record RecencyBias(int Scanned, int EvidenceMissing, double MeanNewerInTopK, double BaselineIfUnbiased, double MeanSlotAgePercentile);

/// <param name="Questions">Questions scored.</param>
/// <param name="RecallByWeights">Micro recall@K of each weighting arm.</param>
/// <param name="RecencyBias">Recency statistics of the default additive ranking within the pool.</param>
/// <param name="PoolCoverage">Share of questions with at least one gold item anywhere in the re-ranked pool: the ceiling of
/// every arm's recall, since no re-ranking can find evidence the pool does not hold.</param>
public sealed record WeightAblationResult(
    int Questions, IReadOnlyDictionary<string, IReadOnlyDictionary<int, double>> RecallByWeights, RecencyBias RecencyBias,
    double PoolCoverage = double.NaN);

public static class WeightAblation
{
    /// <summary>Pool re-ranked per question: the top-N under the store's own scoring (bounded because conflict detection is O(N²)).</summary>
    public const int RerankPool = 150;

    public static readonly IReadOnlyList<int> Ks = [1, 2, 4, 8];

    public static readonly IReadOnlyList<AblationWeights> Configurations =
    [
        new("current", 1, 0.6, 0.3, 0.4),
        new("sim-only", 1, 0, 0, 0),
        new("sim+ctx", 1, 0, 0, 0.4),
        new("sim+str", 1, 0.6, 0, 0),
        new("no-recency", 1, 0.6, 0, 0.4),
        new("sim-heavy", 3, 0.6, 0.3, 0.4),
        new("str-only", 0, 1, 0, 0),
        new("rec-only", 0, 0, 1, 0),
    ];

    private static double Average(List<double> xs) => xs.Count == 0 ? 0 : xs.Sum() / xs.Count;

    private sealed record Candidate(string Id, double Score, double Similarity, double Strength, double Recency, double Context);

    /// <summary>
    /// Runs the ablation under NO_GATING with the store's default retrieval configuration. The pool is the top
    /// <paramref name="pool"/> candidates under the store's own score mode (standardised by default), so it is chosen by a
    /// scorer that itself weights recency; <c>int.MaxValue</c> re-ranks every candidate instead. With
    /// <paramref name="applyFloor"/> a hit also needs a store score above the retrieval floor (the published diagnostic
    /// track); without it the arms are judged on rank alone, which a whole-store pool needs because the floor is set for
    /// top-ranked scores.
    /// </summary>
    public static WeightAblationResult Run(IReadOnlyList<LocomoConversation> conversations, MemoryConfig? baseConfig = null, int pool = RerankPool, bool applyFloor = true) =>
        RunVariants(conversations, baseConfig, [(pool, applyFloor)])[0];

    /// <summary>
    /// Several pools from one retrieval per question: the store's whole ranking is fetched once and each variant takes its
    /// head. In the standardised and RRF modes the conflict penalty scans a constant head of candidates, so the head of the
    /// whole ranking equals a top-N call.
    /// </summary>
    public static IReadOnlyList<WeightAblationResult> RunVariants(IReadOnlyList<LocomoConversation> conversations, MemoryConfig? baseConfig,
        IReadOnlyList<(int Pool, bool ApplyFloor)> variants)
    {
        var config = (baseConfig ?? MemoryConfig.Default) with { Gating = GatingCoefficients.None };
        var fetch = variants.Max(v => v.Pool);
        var acc = variants.Select(_ => new Accumulator()).ToList();

        foreach (var conv in conversations)
        {
            var memory = LocomoCorpus.BuildMemory(conv, config);
            var createdById = new Dictionary<string, double>();
            foreach (var e in conv.Episodes)
                createdById[e.Id] = e.CreatedAt;
            var allCreated = conv.Episodes.Select(e => e.CreatedAt).Order().ToArray();
            double AgePercentile(double t)
            {
                int lo = 0, hi = allCreated.Length;
                while (lo < hi)
                {
                    var mid = (lo + hi) >> 1;
                    if (allCreated[mid] < t)
                        lo = mid + 1;
                    else
                        hi = mid;
                }
                return allCreated.Length > 0 ? (double)lo / allCreated.Length : 0;
            }
            double? CreatedAt(string id) =>
                createdById.TryGetValue(id, out var t) ? t
                : id.StartsWith("fact_", StringComparison.Ordinal) && createdById.TryGetValue(id[5..], out var u) ? u : null;

            foreach (var q in conv.Qa)
            {
                var all = memory.Retrieve(q.Question, fetch, bump: false)
                    .Select(c => new Candidate(c.Id, c.Score, c.Parts.Similarity, c.Parts.Strength, c.Parts.Recency, c.Parts.Context))
                    .ToList();
                var ev = new HashSet<string>();
                foreach (var e in q.Evidence)
                {
                    if (!conv.EvidenceIds.Contains(e))
                        continue;
                    ev.Add(e);
                    ev.Add($"fact_{e}");
                }
                double? evTs = null;
                foreach (var e in q.Evidence)
                {
                    if (createdById.TryGetValue(e, out var t) && (evTs is null || t > evTs))
                        evTs = t;
                }
                for (var v = 0; v < variants.Count; v++)
                {
                    var floor = variants[v].ApplyFloor ? memory.Config.RetrievalFloor : double.NegativeInfinity;
                    acc[v].Add(all.Count > variants[v].Pool ? all.GetRange(0, variants[v].Pool) : all, ev, evTs, floor, CreatedAt, AgePercentile);
                }
            }
        }
        return [.. acc.Select(a => a.Result())];
    }

    /// <summary>The variants on each conversation alone, in parallel (for per-conversation contrasts; see <see cref="Combine"/>).</summary>
    public static IReadOnlyList<IReadOnlyList<WeightAblationResult>> RunVariantsPerConversation(IReadOnlyList<LocomoConversation> conversations,
        MemoryConfig? baseConfig, IReadOnlyList<(int Pool, bool ApplyFloor)> variants) =>
        ParallelMap.Map(conversations, (conv, _) => RunVariants([conv], baseConfig, variants));

    /// <summary>
    /// Combines results computed on disjoint sets of conversations into the result over their union: every field is a mean
    /// over questions (recall, coverage) or over questions with dated evidence (recency), so the parts are weighted by those
    /// counts.
    /// </summary>
    public static WeightAblationResult Combine(IReadOnlyList<WeightAblationResult> parts)
    {
        var questions = parts.Sum(p => p.Questions);
        double ByQuestions(Func<WeightAblationResult, double> x) => questions == 0 ? double.NaN : parts.Sum(p => x(p) * p.Questions) / questions;
        var dated = parts.Sum(p => p.RecencyBias.Scanned - p.RecencyBias.EvidenceMissing);
        double ByDated(Func<RecencyBias, double> x) => dated == 0 ? 0 : parts.Sum(p => x(p.RecencyBias) * (p.RecencyBias.Scanned - p.RecencyBias.EvidenceMissing)) / dated;
        var recall = Configurations.ToDictionary(c => c.Key,
            c => (IReadOnlyDictionary<int, double>)Ks.ToDictionary(k => k, k => ByQuestions(p => p.RecallByWeights[c.Key][k])));
        return new WeightAblationResult(questions, recall,
            new RecencyBias(parts.Sum(p => p.RecencyBias.Scanned), parts.Sum(p => p.RecencyBias.EvidenceMissing),
                ByDated(b => b.MeanNewerInTopK), ByDated(b => b.BaselineIfUnbiased), ByDated(b => b.MeanSlotAgePercentile)),
            ByQuestions(p => p.PoolCoverage));
    }

    private sealed class Accumulator
    {
        private readonly Dictionary<string, Dictionary<int, List<double>>> recall =
            Configurations.ToDictionary(c => c.Key, _ => Ks.ToDictionary(k => k, _ => new List<double>()));
        private readonly List<double> newerCounts = [], poolNewerShare = [], slotAge = [];
        private int scanned, evidenceMissing, questions, covered;

        private static List<Candidate> Rank(List<Candidate> cands, AblationWeights w) =>
            // stable descending sort
            [.. cands.Select(c => (c, V: (w.Similarity * c.Similarity) + (w.Strength * c.Strength) + (w.Recency * c.Recency) + (w.Context * c.Context)))
                .OrderByDescending(x => x.V).Select(x => x.c)];

        public void Add(List<Candidate> cands, HashSet<string> ev, double? evTs, double floor, Func<string, double?> createdAt, Func<double, double> agePercentile)
        {
            questions++;
            if (cands.Any(c => ev.Contains(c.Id)))
                covered++;
            foreach (var w in Configurations)
            {
                var ranked = Rank(cands, w);
                foreach (var k in Ks)
                    recall[w.Key][k].Add(ranked.Take(k).Any(c => ev.Contains(c.Id) && c.Score > floor) ? 1 : 0);
            }
            scanned++;
            if (evTs is not { } evidenceTs)
            {
                evidenceMissing++;
                return;
            }
            var top = Rank(cands, Configurations[0]).Take(Ks.Max()).ToList();
            newerCounts.Add(top.Count(c => createdAt(c.Id) is { } t && t > evidenceTs));
            slotAge.Add(Average(top.Select(c => agePercentile(createdAt(c.Id) ?? 0)).ToList()));
            poolNewerShare.Add(1 - agePercentile(evidenceTs));
        }

        public WeightAblationResult Result() => new(questions,
            recall.ToDictionary(kv => kv.Key, kv => (IReadOnlyDictionary<int, double>)kv.Value.ToDictionary(x => x.Key, x => Average(x.Value))),
            new RecencyBias(scanned, evidenceMissing, Average(newerCounts), Average(poolNewerShare) * Ks.Max(), Average(slotAge)),
            questions == 0 ? double.NaN : (double)covered / questions);
    }
}
