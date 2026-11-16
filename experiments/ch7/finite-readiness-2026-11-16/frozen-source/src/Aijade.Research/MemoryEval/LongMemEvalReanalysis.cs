using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Memory;
using Aijade.Memory.Locomo;
using Aijade.Memory.Model;

namespace Aijade.Research.MemoryEval;

public sealed record LongMemComponent(string Id, bool Gold, double Score, double Similarity, double Strength, double Recency, double Context);
public sealed record LongMemDelivered(string Id, bool Gold, double Score, bool Conflict);
public sealed record LongMemDelivery(RetrievalScoreMode Mode, double Penalty, double Floor, IReadOnlyList<LongMemDelivered> Head);
public sealed record LongMemGating(RetrievalScoreMode Mode, bool PenaltyOff, IReadOnlyDictionary<string, ConversationMetrics> Conditions);
public sealed record LongMemCase(int RawIndex, string QuestionId, bool Answerable, int Episodes,
    IReadOnlyList<WeightAblationResult> Weights, IReadOnlyList<LongMemComponent> Components,
    IReadOnlyList<LongMemDelivery> Delivery, IReadOnlyList<LongMemGating> Gating);

/// <summary>
/// Fresh per-question sufficient records for the separately frozen eligibility correction. No score, predictor,
/// production policy, label or history is changed. Legacy reconstruction is a prerequisite for corrected claims.
/// </summary>
public static class LongMemEvalReanalysis
{
    private static readonly string[] ComponentNames = ["similarity", "strength", "recency", "context"];
    private static readonly string[] GatingConditions = ["predicted-ON", "predicted-OFF", "oracle-ON", "oracle-OFF"];
    private const uint Seed = 0x5EED_2026;
    private const int Iterations = 10_000;

    public static LongMemCase Measure(LocomoConversation conv, int rawIndex)
    {
        if (conv.Qa.Count != 1 || conv.EvidenceIds.Count == 0)
            throw new ArgumentException("The kernel journal requires exactly one evidence-marked question per history.", nameof(conv));
        var q = conv.Qa[0];
        var gold = q.Evidence.Where(conv.EvidenceIds.Contains).SelectMany(e => new[] { e, $"fact_{e}" }).ToHashSet(StringComparer.Ordinal);
        var weights = WeightAblation.RunVariants([conv], null, [(150, true), (150, false), (int.MaxValue, false)]);
        var memory = LocomoCorpus.BuildMemory(conv, MemoryConfig.Default with { Gating = GatingCoefficients.None, RetrievalScoreMode = RetrievalScoreMode.Standardized });
        var components = memory.Retrieve(q.Question, int.MaxValue, bump: false)
            .Select(c => new LongMemComponent(c.Id, gold.Contains(c.Id), c.Score, c.Parts.Similarity, c.Parts.Strength, c.Parts.Recency, c.Parts.Context)).ToArray();
        var delivery = new List<LongMemDelivery>();
        var gating = new List<LongMemGating>();
        foreach (var mode in new[] { RetrievalScoreMode.Additive, RetrievalScoreMode.Standardized })
        {
            foreach (var off in new[] { false, true })
            {
                var penalty = off ? 1.0 : MemoryConfig.Default.ConflictPenalty;
                var store = LocomoCorpus.BuildMemory(conv, MemoryConfig.Default with { Gating = GatingCoefficients.None, RetrievalScoreMode = mode, ConflictPenalty = penalty });
                var head = store.Retrieve(q.Question, mode == RetrievalScoreMode.Additive ? 8 : 150, bump: false)
                    .Select(c => new LongMemDelivered(c.Id, gold.Contains(c.Id), c.Score, c.Parts.Conflict)).ToArray();
                delivery.Add(new(mode, penalty, store.Config.RetrievalFloor, head));
                gating.Add(new(mode, off, SalienceDiagnostics.Run([conv], mode, GatingConditions, off ? 1.0 : null).Conditions));
            }
        }
        return new(rawIndex, conv.SampleId, !LongMemEvalCorpus.IsAbstention(conv.SampleId), conv.Episodes.Count, weights, components, delivery, gating);
    }

    private static double Component(LongMemComponent r, string name) => name switch
    {
        "similarity" => r.Similarity, "strength" => r.Strength, "recency" => r.Recency, _ => r.Context,
    };

    public static ComponentScalesResult ComponentSummary(IReadOnlyList<LongMemCase> cases)
    {
        // Historical PoolSd is explicitly the mean of within-question population SDs. It is not a pooled SD.
        var eligible = cases.Where(c => c.Components.Any(r => r.Gold)).ToArray();
        var w = RetrievalWeights.Default;
        double Avg(Func<LongMemCase, IEnumerable<LongMemComponent>> select, string name) => eligible.Length == 0 ? 0
            : eligible.Average(c => select(c).Average(r => Component(r, name)));
        IEnumerable<LongMemComponent> Top(LongMemCase c) => c.Components.OrderByDescending(r =>
            (w.Similarity * r.Similarity) + (w.Strength * r.Strength) + (w.Recency * r.Recency) + (w.Context * r.Context)).Take(8);
        double Sd(LongMemCase c, string name)
        {
            var mean = c.Components.Average(r => Component(r, name));
            return Math.Sqrt(c.Components.Average(r => Math.Pow(Component(r, name) - mean, 2)));
        }
        return new(eligible.Length,
            ComponentNames.ToDictionary(n => n, n => Avg(c => c.Components.Where(r => r.Gold), n)),
            ComponentNames.ToDictionary(n => n, n => Avg(Top, n)),
            ComponentNames.ToDictionary(n => n, n => Avg(c => c.Components, n)),
            ComponentNames.ToDictionary(n => n, n => eligible.Length == 0 ? 0 : eligible.Average(c => Sd(c, n))));
    }

    public static IReadOnlyList<DeliveryCheckRow> DeliverySummary(IReadOnlyList<LongMemCase> cases)
    {
        return cases[0].Delivery.Select(template =>
        {
            var cells = cases.Select(c => c.Delivery.Single(d => d.Mode == template.Mode && d.Penalty == template.Penalty)).ToArray();
            var slots = cells.Sum(c => c.Head.Take(8).Count());
            return new DeliveryCheckRow(template.Mode, template.Penalty,
                cells.Average(c => c.Head.Take(8).Any(r => r.Gold && r.Score > c.Floor) ? 1.0 : 0.0),
                slots == 0 ? 0 : (double)cells.Sum(c => c.Head.Take(8).Count(r => r.Conflict)) / slots,
                cells.Average(c => c.Head.Any(r => r.Gold && r.Conflict) ? 1.0 : 0.0));
        }).ToArray();
    }

    public static IReadOnlyList<PairedContrast> Contrasts(IReadOnlyList<LongMemCase> cases, bool penaltyOff, bool includeWeights)
    {
        var result = new List<PairedContrast>();
        if (includeWeights)
            result.Add(WeightContrast(cases, 0, "weights: sim-only vs current"));
        foreach (var mode in new[] { RetrievalScoreMode.Additive, RetrievalScoreMode.Standardized })
            foreach (var source in new[] { "predicted", "oracle" })
            {
                double[] Values(string suffix) => cases.Select(c => c.Gating.Single(g => g.Mode == mode && g.PenaltyOff == penaltyOff)
                    .Conditions[$"{source}-{suffix}"].Recall[8]).ToArray();
                result.Add(MemoryUncertainty.Macro($"gating ({source}, {mode.ToString().ToLowerInvariant()}): ON vs OFF", Values("ON"), Values("OFF"), Iterations, Seed));
            }
        return result;
    }

    private static PairedContrast WeightContrast(IReadOnlyList<LongMemCase> cases, int variant, string key) =>
        MemoryUncertainty.Micro(key, cases.Select(c => c.Weights[variant].RecallByWeights["sim-only"][8] * c.Weights[variant].Questions).ToArray(),
            cases.Select(c => c.Weights[variant].RecallByWeights["current"][8] * c.Weights[variant].Questions).ToArray(),
            cases.Select(c => (double)c.Weights[variant].Questions).ToArray(), Iterations, Seed);

    private static JsonObject Map(IReadOnlyDictionary<string, double> d) => new(d.Select(p => KeyValuePair.Create(p.Key, (JsonNode?)JsonValue.Create(p.Value))));
    private static JsonObject Ks(IReadOnlyDictionary<int, double> d) => Map(d.ToDictionary(p => p.Key.ToString(System.Globalization.CultureInfo.InvariantCulture), p => p.Value));
    private static JsonObject Bias(RecencyBias b) => new()
    {
        ["meanNewerInTopK"] = b.MeanNewerInTopK, ["baselineIfUnbiased"] = b.BaselineIfUnbiased, ["meanSlotAgePercentile"] = b.MeanSlotAgePercentile,
    };
    private static JsonObject Contrast(PairedContrast c) => new()
    {
        ["key"] = c.Key, ["caliber"] = c.Caliber, ["a"] = c.A, ["b"] = c.B, ["difference"] = c.Difference,
        ["bootstrap95"] = new JsonArray(c.BootstrapLo, c.BootstrapHi), ["signFlipP"] = c.SignFlipP,
        ["unitsPositive"] = c.ConversationsPositive, ["unitsNegative"] = c.ConversationsNegative, ["units"] = c.Conversations,
    };
    private static JsonObject Variant(string name, WeightAblationResult r) => new()
    {
        ["what"] = name, ["questions"] = r.Questions, ["poolCoverage"] = r.PoolCoverage,
        ["recencyBias"] = Bias(r.RecencyBias), ["recallByWeights"] = new JsonObject(r.RecallByWeights.Select(p => KeyValuePair.Create(p.Key, (JsonNode?)Ks(p.Value)))),
    };

    public static IReadOnlyDictionary<string, JsonObject> Reports(IReadOnlyList<LongMemCase> cases)
    {
        if (cases.Count == 0 || cases.Select(c => c.RawIndex).Distinct().Count() != cases.Count)
            throw new ArgumentException("A nonempty unique case frame is required.", nameof(cases));
        var variants = Enumerable.Range(0, 3).Select(i => WeightAblation.Combine(cases.Select(c => c.Weights[i]).ToArray())).ToArray();
        var r = variants[0];
        var bias = Bias(r.RecencyBias);
        bias["scanned"] = r.RecencyBias.Scanned;
        var on = Contrasts(cases, penaltyOff: false, includeWeights: true);
        var off = Contrasts(cases, penaltyOff: true, includeWeights: false);
        var scales = ComponentSummary(cases);
        var allComponents = cases.SelectMany(c => c.Components).ToArray();
        // A separately labelled pooled SD can be reconstructed from the raw component records; never substitute it for PoolSd.
        var pooledSd = ComponentNames.ToDictionary(n => n, n =>
        {
            var m = allComponents.Average(v => Component(v, n));
            return Math.Sqrt(allComponents.Average(v => Math.Pow(Component(v, n) - m, 2)));
        });
        var predicted = new[] { (Rows: on, Off: false), (Rows: off, Off: true) }.SelectMany(p => p.Rows.Where(c => c.Key.Contains("predicted", StringComparison.Ordinal))
            .Select(c => (Contrast: c, p.Off))).OrderBy(p => p.Contrast.SignFlipP).ToArray();
        var holm = new JsonArray();
        double cumulative = 0;
        for (var i = 0; i < predicted.Length; i++)
        {
            var c = predicted[i];
            cumulative = Math.Max(cumulative, Math.Min(1, (predicted.Length - i) * c.Contrast.SignFlipP));
            var row = Contrast(c.Contrast);
            row["penaltyOff"] = c.Off; row["holmP"] = cumulative; row["familySize"] = 4;
            holm.Add(row);
        }
        return new Dictionary<string, JsonObject>(StringComparer.Ordinal)
        {
            ["replication.json"] = new()
            {
                ["provenance"] = new JsonObject { ["questions"] = cases.Count, ["episodes"] = cases.Sum(c => c.Episodes), ["corpusSha256"] = LongMemEvalCorpus.Sha256 },
                ["recencyBias"] = bias,
                ["recallByWeights"] = new JsonObject(r.RecallByWeights.Select(p => KeyValuePair.Create(p.Key, (JsonNode?)Ks(p.Value)))),
                ["contrasts"] = new JsonArray(on.Select(c => (JsonNode)Contrast(c)).ToArray()),
            },
            ["pool-check.json"] = new()
            {
                ["published"] = Variant("top 150, floor applied", variants[0]), ["pool150RankOnly"] = Variant("top 150, rank alone", variants[1]),
                ["wholeStore"] = Variant("every candidate, rank alone", variants[2]),
                ["contrasts"] = new JsonArray(Contrast(WeightContrast(cases, 0, "weights (150-candidate pool, floor): sim-only vs current")),
                    Contrast(WeightContrast(cases, 2, "weights (whole store, rank alone): sim-only vs current"))),
            },
            ["component-scales.json"] = new()
            {
                ["questions"] = scales.Questions, ["gold"] = Map(scales.Gold), ["additiveTop8"] = Map(scales.AdditiveTop8),
                ["pool"] = Map(scales.Pool), ["poolSd"] = Map(scales.PoolSd!),
            },
            ["delivery-check.json"] = new()
            {
                ["rows"] = new JsonArray(DeliverySummary(cases).Select(c => (JsonNode)new JsonObject
                {
                    ["mode"] = WireName.Of(c.Mode), ["conflictPenalty"] = c.ConflictPenalty, ["recall8Macro"] = c.MacroRecall8,
                    ["penalizedShareOfTop8"] = c.PenalizedShareOfTop8, ["goldPenalizedShare"] = c.GoldPenalizedShare,
                }).ToArray()),
            },
            ["gating-penalty-off.json"] = new()
            {
                ["conflictPenalty"] = 1.0, ["contrasts"] = new JsonArray(off.Select(c => (JsonNode)Contrast(c)).ToArray()),
            },
            ["diagnostics.json"] = new()
            {
                ["predictedGatingHolmFamily"] = holm, ["pooledComponentSd"] = Map(pooledSd),
                ["historicalPoolSdEstimand"] = "Mean over questions of within-question population SD; distinct from pooledComponentSd.",
                ["resamplingUnit"] = "question case conditional on compiled history; shared sessions do not establish independent users",
            },
        };
    }
}
