using System.Text.Json.Nodes;

using Aijade.Memory.Locomo;
using Aijade.Memory.Model;
using Aijade.Memory.Salience;
using Aijade.Research.Statistics;

namespace Aijade.Research.MemoryEval;

// P3-A and P3-B of experiments/plans/2026-10-22-followup-analyses.md (committed before this code was written): the headline
// contrasts of P3 re-estimated on the answerable questions (LoCoMo category ≠ 5), recall counted per evidence turn, and the
// gating × scorer interaction estimated directly. A store does not depend on which questions are scored and retrieval does
// not change it (bump: false), so each store is built once, exactly as in the published runs, and every question set is
// scored on it; the all-question values reproduce the archived files.

/// <summary>One scored question: hit-any at K; its distinct evidence turns that resolve in the conversation, and how many were hit.</summary>
public sealed record ScoredQuestion(bool Answerable, bool Hit, int Evidence, int EvidenceHit)
{
    public double EvidenceShare => Evidence == 0 ? double.NaN : EvidenceHit / (double)Evidence;
}

/// <summary>A delivery-track scorer: score mode and conflict-penalty override (null keeps the default).</summary>
public sealed record DeliveryScorer(string Key, RetrievalScoreMode Mode, double? ConflictPenalty);

/// <summary>Every question of one conversation scored under each delivery store (scorer × gating) and each diagnostic arm.</summary>
public sealed record ConversationScores(
    IReadOnlyDictionary<(string Scorer, bool Gating), IReadOnlyList<ScoredQuestion>> Delivery,
    IReadOnlyDictionary<string, IReadOnlyList<ScoredQuestion>> Diagnostic);

public static class AnswerableReanalysis
{
    public const int K = MemoryUncertainty.K;

    public const int Iterations = 10000;

    public const uint Seed = 0x5EED_2026;

    /// <summary>LoCoMo category 5 holds the adversarial questions, unanswerable from the conversation by the corpus's definition.</summary>
    public static bool Answerable(LocomoQuestion q) => q.Category != 5;

    public static readonly IReadOnlyList<DeliveryScorer> Scorers =
    [
        new("additive", RetrievalScoreMode.Additive, null),
        new("additive, penalty off", RetrievalScoreMode.Additive, 1.0),
        new("standardized", RetrievalScoreMode.Standardized, null),
        new("standardized, penalty off", RetrievalScoreMode.Standardized, 1.0),
    ];

    public static readonly IReadOnlyList<string> DiagnosticArms = ["current", "sim-only"];

    private static readonly (string Key, Func<ScoredQuestion, bool> Keep)[] Subsets = [("all", _ => true), ("answerable", q => q.Answerable)];

    public static IReadOnlyList<ConversationScores> Score(IReadOnlyList<LocomoConversation> conversations) =>
        ParallelMap.Map(conversations, (conv, _) => ScoreConversation(conv));

    private static ConversationScores ScoreConversation(LocomoConversation conv)
    {
        // the deployed salience, as SalienceDiagnostics computes the "predicted" source
        var predicted = conv.Episodes.ToDictionary(ep => ep.Id, ep => 1 / (1 + Math.Exp(-SaliencePredictor.PredictV2(ep.Content, SalienceContext.Empty).Score)));
        var delivery = new Dictionary<(string, bool), IReadOnlyList<ScoredQuestion>>();
        foreach (var scorer in Scorers)
        {
            foreach (var gating in new[] { true, false })
            {
                var config = MemoryConfig.Default with { Gating = gating ? GatingCoefficients.Default : GatingCoefficients.None, RetrievalScoreMode = scorer.Mode };
                if (scorer.ConflictPenalty is { } penalty)
                    config = config with { ConflictPenalty = penalty };
                var memory = LocomoCorpus.BuildMemory(conv, config, ep => predicted.TryGetValue(ep.Id, out var v) ? v : null);
                delivery[(scorer.Key, gating)] = [.. conv.Qa.Select(q =>
                    Judge(conv, q, memory.Retrieve(q.Question, K, bump: false).Select(c => (c.Id, c.Score)), memory.Config.RetrievalFloor))];
            }
        }

        // the diagnostic track: the store's own top 150 (no gating) re-ranked by each arm's weights, floor applied (WeightAblation)
        var store = LocomoCorpus.BuildMemory(conv, MemoryConfig.Default with { Gating = GatingCoefficients.None });
        var diagnostic = DiagnosticArms.ToDictionary(a => a, _ => new List<ScoredQuestion>());
        foreach (var q in conv.Qa)
        {
            var pool = store.Retrieve(q.Question, WeightAblation.RerankPool, bump: false);
            foreach (var arm in DiagnosticArms)
            {
                var w = WeightAblation.Configurations.First(c => c.Key == arm);
                var ranked = pool
                    .Select(c => (c, V: (w.Similarity * c.Parts.Similarity) + (w.Strength * c.Parts.Strength) + (w.Recency * c.Parts.Recency) + (w.Context * c.Parts.Context)))
                    .OrderByDescending(x => x.V).Select(x => (x.c.Id, x.c.Score));
                diagnostic[arm].Add(Judge(conv, q, ranked, store.Config.RetrievalFloor));
            }
        }
        return new ConversationScores(delivery, diagnostic.ToDictionary(p => p.Key, p => (IReadOnlyList<ScoredQuestion>)p.Value));
    }

    /// <summary>
    /// Hit-any as in the papers (an evidence turn or its fact copy in the top K above the retrieval floor) and the evidence
    /// turns hit. An evidence turn counts when its id resolves to a turn of the conversation: every such turn is encoded into
    /// each store, and one that gating pruned counts as a miss, so the denominator is the same under every configuration.
    /// </summary>
    private static ScoredQuestion Judge(LocomoConversation conv, LocomoQuestion q, IEnumerable<(string Id, double Score)> ranking, double floor)
    {
        var turns = q.Evidence.Where(conv.EvidenceIds.Contains).Distinct().ToList();
        var hitIds = ranking.Take(K).Where(c => c.Score > floor).Select(c => c.Id).ToHashSet(StringComparer.Ordinal);
        var hit = turns.Count(e => hitIds.Contains(e) || hitIds.Contains($"fact_{e}"));
        return new ScoredQuestion(Answerable(q), hit > 0, turns.Count, hit);
    }

    public static JsonObject Report(IReadOnlyList<LocomoConversation> corpus)
    {
        var scores = Score(corpus);
        var report = new JsonObject
        {
            ["experiment"] = "P3-A / P3-B (experiments/plans/2026-10-22-followup-analyses.md): the headline contrasts on the answerable questions (LoCoMo category ≠ 5) beside all questions, per-evidence recall, and the gating × scorer interaction; conversation bootstrap (10,000, percentile 95%) and exact sign-flip test, K = 8",
            ["questions"] = new JsonObject
            {
                ["all"] = corpus.Sum(c => c.Qa.Count), ["answerable"] = corpus.Sum(c => c.Qa.Count(Answerable)),
                ["adversarial"] = corpus.Sum(c => c.Qa.Count(q => !Answerable(q))),
            },
            ["clarifications"] = new JsonArray(
                "per-evidence recall: the plan's \"evidence turn present in the store\" is read as a cited turn id that resolves to a turn of the conversation; every such turn is encoded into each store, and one pruned by gating counts as a miss, so the denominator does not change with the configuration"),
        };
        var subsets = new JsonObject();
        foreach (var (key, keep) in Subsets)
            subsets[key] = SubsetReport(corpus, scores, key == "all" ? null : Answerable, keep);
        report["subsets"] = subsets;
        report["interaction"] = InteractionReport(scores);
        return report;
    }

    private static JsonObject SubsetReport(IReadOnlyList<LocomoConversation> corpus, IReadOnlyList<ConversationScores> scores,
        Func<LocomoQuestion, bool>? filter, Func<ScoredQuestion, bool> keep)
    {
        var o = new JsonObject();
        var convs = filter is null ? corpus : [.. corpus.Select(c => c with { Qa = [.. c.Qa.Where(filter)] })];

        // items 1-3: recency and the diagnostic track, by the published code (WeightAblation) on the subset
        var perConv = WeightAblation.RunVariantsPerConversation(convs, null, [(WeightAblation.RerankPool, true), (int.MaxValue, false)]);
        var pooled = WeightAblation.Combine([.. perConv.Select(p => p[0])]);
        var whole = WeightAblation.Combine([.. perConv.Select(p => p[1])]);
        var questions = perConv.Select(p => (double)p[0].Questions).ToArray();
        double[] Hits(int v, string arm) => [.. perConv.Select(p => p[v].RecallByWeights[arm][K] * p[v].Questions)];
        o["questions"] = (int)questions.Sum();
        o["recencyBias"] = new JsonObject
        {
            ["meanNewerInTopK"] = pooled.RecencyBias.MeanNewerInTopK, ["baselineIfUnbiased"] = pooled.RecencyBias.BaselineIfUnbiased,
            ["scanned"] = pooled.RecencyBias.Scanned, ["evidenceMissing"] = pooled.RecencyBias.EvidenceMissing,
        };
        o["diagnostic"] = new JsonObject
        {
            ["pool150Floor"] = new JsonObject { ["current"] = pooled.RecallByWeights["current"][K], ["simOnly"] = pooled.RecallByWeights["sim-only"][K] },
            ["wholeStoreRankOnly"] = new JsonObject { ["current"] = whole.RecallByWeights["current"][K], ["simOnly"] = whole.RecallByWeights["sim-only"][K] },
            ["contrasts"] = new JsonArray(
                ToJson(MemoryUncertainty.Micro("weights (150-candidate pool, floor): sim-only vs current", Hits(0, "sim-only"), Hits(0, "current"), questions, Iterations, Seed)),
                ToJson(MemoryUncertainty.Micro("weights (whole store, rank alone): sim-only vs current", Hits(1, "sim-only"), Hits(1, "current"), questions, Iterations, Seed))),
        };
        // the same hits from this class's own re-ranking: a check that both code paths score the diagnostic arms alike
        var own = DiagnosticArms.ToDictionary(a => a, a => scores.Select(s => (double)s.Diagnostic[a].Where(keep).Count(q => q.Hit)).ToArray());
        o["diagnosticSelfCheck"] = DiagnosticArms.All(a => own[a].Zip(Hits(0, a), (x, y) => Math.Abs(x - y) < 1e-9).All(b => b));

        // items 4-5: delivery recall@8 (macro) per scorer and gating, the penalty contrast and the gating contrasts
        double[] Recall(string scorer, bool gating) => [.. scores.Select(s => HitRate(s.Delivery[(scorer, gating)].Where(keep)))];
        var delivery = new JsonObject();
        foreach (var scorer in Scorers)
            delivery[scorer.Key] = new JsonObject { ["gatingOff"] = Recall(scorer.Key, false).Average(), ["gatingOn"] = Recall(scorer.Key, true).Average() };
        o["delivery"] = delivery;
        o["penaltyContrast"] = ToJson(MemoryUncertainty.Macro("delivery (standardized, no gating): penalty off vs on",
            Recall("standardized, penalty off", false), Recall("standardized", false), Iterations, Seed));
        o["gatingContrasts"] = new JsonArray([.. Scorers.Select(s =>
            (JsonNode)ToJson(MemoryUncertainty.Macro($"gating (predicted, {s.Key}): ON vs OFF", Recall(s.Key, true), Recall(s.Key, false), Iterations, Seed)))]);

        // auxiliary: per-evidence recall@8 on questions with at least one (and at least two) evidence turns in the store
        var perEvidence = new JsonObject();
        foreach (var (label, min) in new[] { ("withEvidence", 1), ("multiEvidence", 2) })
        {
            bool Keep(ScoredQuestion q) => keep(q) && q.Evidence >= min;
            var p = new JsonObject { ["questions"] = scores.Sum(s => s.Diagnostic["current"].Count(Keep)) };
            var n = scores.Select(s => (double)s.Diagnostic["current"].Count(Keep)).ToArray();
            double[] Shares(string arm) => [.. scores.Select(s => s.Diagnostic[arm].Where(Keep).Sum(q => q.EvidenceShare))];
            p["diagnostic"] = new JsonObject
            {
                ["current"] = Shares("current").Sum() / n.Sum(), ["simOnly"] = Shares("sim-only").Sum() / n.Sum(),
                ["contrast"] = ToJson(MicroOver(n, "per-evidence, weights (150-candidate pool, floor): sim-only vs current", Shares("sim-only"), Shares("current"))),
            };
            double[] Mean(string scorer, bool gating) => [.. scores.Select(s => s.Delivery[(scorer, gating)].Where(Keep).Select(q => q.EvidenceShare).DefaultIfEmpty(double.NaN).Average())];
            var d = new JsonObject();
            foreach (var scorer in Scorers)
            {
                d[scorer.Key] = new JsonObject
                {
                    ["gatingOff"] = Finite(Mean(scorer.Key, false)).Average(), ["gatingOn"] = Finite(Mean(scorer.Key, true)).Average(),
                    ["gatingContrast"] = ToJson(MacroOver($"per-evidence, gating (predicted, {scorer.Key}): ON vs OFF", Mean(scorer.Key, true), Mean(scorer.Key, false))),
                };
            }
            p["delivery"] = d;
            p["penaltyContrast"] = ToJson(MacroOver("per-evidence, delivery (standardized, no gating): penalty off vs on",
                Mean("standardized, penalty off", false), Mean("standardized", false)));
            perEvidence[label] = p;
        }
        o["perEvidenceRecall"] = perEvidence;
        return o;
    }

    /// <summary>P3-B: per conversation, the gating effect under one scorer minus that under the standardised scorer with its default penalty.</summary>
    private static JsonObject InteractionReport(IReadOnlyList<ConversationScores> scores)
    {
        var o = new JsonObject();
        foreach (var (key, keep) in Subsets)
        {
            double[] G(string scorer) => [.. scores.Select(s => HitRate(s.Delivery[(scorer, true)].Where(keep)) - HitRate(s.Delivery[(scorer, false)].Where(keep)))];
            var contrasts = new[]
            {
                MemoryUncertainty.Macro("Δ1: gating effect, additive minus standardized", G("additive"), G("standardized"), Iterations, Seed),
                MemoryUncertainty.Macro("Δ2: gating effect, standardized with the penalty off minus standardized", G("standardized, penalty off"), G("standardized"), Iterations, Seed),
            };
            var arr = new JsonArray([.. contrasts.Select(c => (JsonNode)ToJson(c))]);
            var sub = new JsonObject { ["contrasts"] = arr };
            if (key == "answerable")
            {
                sub["holm"] = new JsonArray([.. Stats.HolmBonferroni([.. contrasts.Select(c => c.SignFlipP)], 0.05, [.. contrasts.Select(c => c.Key)])
                    .Select(h => (JsonNode)new JsonObject { ["key"] = h.Label, ["p"] = h.P, ["adjustedP"] = h.AdjustedP, ["reject"] = h.Reject })]);
            }
            o[key] = sub;
        }
        return o;
    }

    private static double HitRate(IEnumerable<ScoredQuestion> qs)
    {
        var list = qs.ToList();
        return list.Count == 0 ? double.NaN : list.Count(q => q.Hit) / (double)list.Count;
    }

    private static IEnumerable<double> Finite(IEnumerable<double> xs) => xs.Where(double.IsFinite);

    /// <summary>Macro contrast over the conversations that have at least one question of the kind (both arms then defined).</summary>
    private static PairedContrast MacroOver(string key, double[] a, double[] b)
    {
        var keep = Enumerable.Range(0, a.Length).Where(i => double.IsFinite(a[i]) && double.IsFinite(b[i])).ToArray();
        return MemoryUncertainty.Macro(key, [.. keep.Select(i => a[i])], [.. keep.Select(i => b[i])], Iterations, Seed);
    }

    /// <summary>Micro contrast over the conversations that have at least one question of the kind.</summary>
    private static PairedContrast MicroOver(double[] n, string key, double[] a, double[] b)
    {
        var keep = Enumerable.Range(0, n.Length).Where(i => n[i] > 0).ToArray();
        return MemoryUncertainty.Micro(key, [.. keep.Select(i => a[i])], [.. keep.Select(i => b[i])], [.. keep.Select(i => n[i])], Iterations, Seed);
    }

    public static JsonObject ToJson(PairedContrast c) => new()
    {
        ["key"] = c.Key, ["caliber"] = c.Caliber, ["a"] = c.A, ["b"] = c.B, ["difference"] = c.Difference,
        ["bootstrap95"] = new JsonArray(c.BootstrapLo, c.BootstrapHi), ["signFlipP"] = c.SignFlipP,
        ["unitsPositive"] = c.ConversationsPositive, ["unitsNegative"] = c.ConversationsNegative, ["units"] = c.Conversations,
    };
}
