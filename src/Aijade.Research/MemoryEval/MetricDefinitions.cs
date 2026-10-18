using Aijade.Memory;
using Aijade.Memory.Locomo;
using Aijade.Memory.Model;
using Aijade.Memory.Salience;

namespace Aijade.Research.MemoryEval;

// P4 / J5 §5.6, two definition defects of recall@K on this store:
//   1. aggregation caliber — the per-conversation (macro) mean and the question-level (micro) mean differ whenever the
//      conversations have unequal question counts; neither is wrong, but figures in the two calibers cannot be compared;
//   2. duplicate copies — the lexical distiller writes a fact with the same content as its episode and recall counts either
//      id as a hit, so a kept memory occupies two slots of the top-K; and the pool size alone moves recall@K. Arms switch the
//      distiller (lexical vs none) and retrieval-time content dedupe (on vs off) over a grid of kept fractions q for oracle and
//      predicted salience, gating on. EffectiveTop8 is the mean number of distinct contents among the top 8 results.

public sealed record CaliberRow(RetrievalScoreMode Mode, IReadOnlyDictionary<int, double> Macro, IReadOnlyDictionary<int, double> Micro);

public sealed record DuplicationArm(string Salience, double Q, bool Facts, bool Dedupe, IReadOnlyDictionary<int, double> Recall, double EvidenceSurvival,
    double Distinct, double PoolSize, double EffectiveTop8);

public static class MetricDefinitions
{
    public static readonly IReadOnlyList<double> Qs = [1, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3];

    private static readonly string[] SalienceKinds = ["oracle", "predicted"];

    private sealed class NullDistiller : IDistiller
    {
        public IReadOnlyList<SemanticFact> Distill(IReadOnlyList<Episode> episodes) => [];
    }

    public static IReadOnlyList<CaliberRow> AggregationCaliber(IReadOnlyList<LocomoConversation> conversations)
    {
        var rows = new List<CaliberRow>();
        foreach (var mode in new[] { RetrievalScoreMode.Additive, RetrievalScoreMode.Standardized, RetrievalScoreMode.Rrf })
        {
            var measured = ParallelMap.Map(conversations, (conv, _) =>
            {
                var memory = LocomoCorpus.BuildMemory(conv, MemoryConfig.Default with { Gating = GatingCoefficients.None, RetrievalScoreMode = mode });
                return SalienceDiagnostics.Measure(memory, conv, SalienceDiagnostics.GoldEvidence(conv));
            });
            var perConversation = SalienceDiagnostics.Ks.ToDictionary(k => k, k => measured.Select(m => m.Recall[k]).ToList());
            var hits = SalienceDiagnostics.Ks.ToDictionary(k => k, k => measured.Select((m, i) => (int)Math.Round(m.Recall[k] * conversations[i].Qa.Count)).Sum());
            var questions = conversations.Sum(c => c.Qa.Count);
            rows.Add(new CaliberRow(mode, perConversation.ToDictionary(p => p.Key, p => p.Value.Average()),
                hits.ToDictionary(p => p.Key, p => questions == 0 ? 0 : (double)p.Value / questions)));
        }
        return rows;
    }

    public static IReadOnlyList<DuplicationArm> DuplicationConfusion(IReadOnlyList<LocomoConversation> conversations)
    {
        var arms = SalienceKinds.SelectMany(s => Qs.SelectMany(q => new[] { (s, q, Facts: true, Dedupe: true), (s, q, Facts: false, Dedupe: true), (s, q, Facts: true, Dedupe: false), (s, q, Facts: false, Dedupe: false) })).ToList();
        var perConversation = ParallelMap.Map(conversations, (conv, _) =>
        {
            var gold = SalienceDiagnostics.GoldEvidence(conv);
            var predicted = conv.Episodes.Select(ep => 1 / (1 + Math.Exp(-SaliencePredictor.PredictV2(ep.Content, SalienceContext.Empty).Score))).ToList();
            var oracle = conv.Episodes.Select(ep => gold.Contains(ep.Id) ? 1.0 : 0.0).ToList();
            var index = conv.Episodes.Select((ep, i) => (ep.Id, i)).ToDictionary(p => p.Id, p => p.i);
            return arms.ToDictionary(arm => arm, arm =>
            {
                var values = arm.s == "oracle" ? oracle : predicted;
                var memory = LocomoCorpus.BuildMemory(conv, MemoryConfig.Default with { Gating = GatingCoefficients.Default, DedupeByContent = arm.Dedupe },
                    ep => index.TryGetValue(ep.Id, out var i) ? values[i] : null, keepFraction: arm.q, distiller: arm.Facts ? null : new NullDistiller());
                var effective = conv.Qa.Count == 0 ? 0 : conv.Qa.Average(q => memory.Retrieve(q.Question, 8, bump: false).Select(c => c.Content).Distinct(StringComparer.Ordinal).Count());
                return (M: SalienceDiagnostics.Measure(memory, conv, gold), Distinct: memory.Episodes.Count(e => !e.Forgotten), Effective: effective);
            });
        });
        var acc = arms.ToDictionary(a => a, a => perConversation.Select(p => p[a]).ToList());
        return [.. arms.Select(a => new DuplicationArm(a.s, a.q, a.Facts, a.Dedupe,
            SalienceDiagnostics.Ks.ToDictionary(k => k, k => acc[a].Average(x => x.M.Recall[k])),
            acc[a].Average(x => x.M.EvidenceSurvival), acc[a].Average(x => x.Distinct), acc[a].Average(x => x.M.PoolSize), acc[a].Average(x => x.Effective)))];
    }
}
