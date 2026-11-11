using System.Text.Json;

using Aijade.Memory.Locomo;
using Aijade.Memory.Model;
using Aijade.Research.MemoryEval;

namespace Aijade.Tests;

public sealed class LongMemEvalReanalysisTests
{
    private static readonly string[] Dates = ["2023/05/20 (Sat) 02:21"];
    private static readonly string[] SessionIds = ["s"];
    private static LocomoConversation Case(int index, int turns)
    {
        using var doc = JsonDocument.Parse(JsonSerializer.Serialize(new
        {
            question_id = $"case-{index}", question = "Where did Alice move?", answer = "Berlin",
            question_date = "2023/06/30 (Fri) 12:00", haystack_dates = Dates, haystack_session_ids = SessionIds,
            haystack_sessions = new[] { Enumerable.Range(0, turns).Select(i => new
            {
                role = "user", content = i == index ? "Alice moved to Berlin." : i % 7 == 0 ? "Alice did not move to Berlin; she stayed in Paris."
                    : $"Travel note {i} includes a distant city.", has_answer = i == index,
            }).ToArray() },
        }));
        return LongMemEvalCorpus.ParseQuestion(doc.RootElement)!;
    }

    [Fact]
    public void Sufficient_records_reconstruct_full_kernel_statistics_with_unequal_pool_and_slot_counts()
    {
        // Small and >150-candidate histories expose wrong slot weighting, pool caps and pooled/within-pool SD confusion.
        LocomoConversation[] corpus = [Case(1, 4), Case(2, 160)];
        var rows = corpus.Select((c, i) => LongMemEvalReanalysis.Measure(c, i)).ToArray();
        var parts = WeightAblation.RunVariantsPerConversation(corpus, null, [(150, true), (150, false), (int.MaxValue, false)]);
        for (var i = 0; i < 3; i++)
            EqualNumbers(WeightAblation.Combine(parts.Select(p => p[i]).ToArray()), WeightAblation.Combine(rows.Select(r => r.Weights[i]).ToArray()));
        EqualNumbers(RetrievalAblation.ComponentScales(corpus), LongMemEvalReanalysis.ComponentSummary(rows));
        EqualNumbers(RetrievalAblation.DeliveryCheck(corpus), LongMemEvalReanalysis.DeliverySummary(rows));
        EqualNumbers(MemoryUncertainty.Run(corpus), LongMemEvalReanalysis.Contrasts(rows, penaltyOff: false, includeWeights: true));
        EqualNumbers(MemoryUncertainty.Run(corpus, conflictPenalty: 1.0, includeWeights: false), LongMemEvalReanalysis.Contrasts(rows, penaltyOff: true, includeWeights: false));
        var report = LongMemEvalReanalysis.Reports(rows);
        Assert.Equal(6, report.Count);
        var family = report["diagnostics.json"]["predictedGatingHolmFamily"]!.AsArray();
        Assert.Equal(4, family.Count);
        Assert.All(family, n => Assert.InRange(n!["holmP"]!.GetValue<double>(), n["signFlipP"]!.GetValue<double>(), 1));
    }

    private static void EqualNumbers<T>(T expected, T actual)
    {
        using var a = JsonDocument.Parse(JsonSerializer.Serialize(expected));
        using var b = JsonDocument.Parse(JsonSerializer.Serialize(actual));
        Compare(a.RootElement, b.RootElement);
    }

    private static void Compare(JsonElement a, JsonElement b)
    {
        Assert.Equal(a.ValueKind, b.ValueKind);
        switch (a.ValueKind)
        {
            case JsonValueKind.Object:
                Assert.Equal(a.EnumerateObject().Select(p => p.Name), b.EnumerateObject().Select(p => p.Name));
                foreach (var p in a.EnumerateObject()) Compare(p.Value, b.GetProperty(p.Name));
                break;
            case JsonValueKind.Array:
                Assert.Equal(a.GetArrayLength(), b.GetArrayLength());
                for (var i = 0; i < a.GetArrayLength(); i++) Compare(a[i], b[i]);
                break;
            case JsonValueKind.Number: Assert.Equal(a.GetDouble(), b.GetDouble(), 10); break;
            default: Assert.Equal(a.GetRawText(), b.GetRawText()); break;
        }
    }
}
