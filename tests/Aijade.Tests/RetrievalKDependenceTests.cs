using Aijade.Memory;
using Aijade.Memory.Locomo;
using Aijade.Memory.Model;
using Aijade.Research.MemoryEval;

namespace Aijade.Tests;

/// <summary>
/// The P4 experiments read recall@k for every k from one top-8 ranking. That is only valid when the ranking does not depend
/// on K: in the standardised and RRF modes the conflict rerank scans a constant head, so the first k of a top-8 call must
/// equal a top-k call; in the additive mode the penalty only scans the top-K, so the two may differ.
/// </summary>
public class RetrievalKDependenceTests
{
    private static BioticMemory Store(RetrievalScoreMode mode)
    {
        var m = new BioticMemory(MemoryConfig.Default with { RetrievalScoreMode = mode }, 0);
        string[] texts =
        [
            "Alice moved to Berlin last spring for a new job.",
            "Alice did not move to Berlin; she stayed in Paris.",
            "Bob adopted a dog named Rex in March.",
            "Bob never adopted a dog, he is allergic.",
            "Carol started learning the violin this year.",
            "Carol is not learning the violin anymore.",
            "Dave went hiking in the Alps with Alice.",
            "Dave did not go hiking, it rained all week.",
            "Erin bakes sourdough bread every weekend.",
            "Erin isn't baking bread these days.",
            "Frank works at a hospital in Berlin.",
            "Alice and Bob met at a concert in Paris.",
        ];
        for (var i = 0; i < texts.Length; i++)
            m.Encode(new EncodeInput($"e{i}", texts[i], i * 1000, new EpisodeContext(null, null, null, [])));
        return m;
    }

    [Theory]
    [InlineData(RetrievalScoreMode.Standardized)]
    [InlineData(RetrievalScoreMode.Rrf)]
    public void The_first_k_of_a_top_8_ranking_equal_a_top_k_ranking(RetrievalScoreMode mode)
    {
        var m = Store(mode);
        foreach (var q in new[] { "Where did Alice move?", "Did Bob adopt a dog?", "Who went hiking in the Alps?", "Is Erin baking bread?" })
        {
            var top8 = m.Retrieve(q, 8, bump: false).Select(c => c.Id).ToList();
            foreach (var k in new[] { 1, 2, 3, 4, 6 })
                Assert.Equal(top8.Take(k), m.Retrieve(q, k, bump: false).Select(c => c.Id));
        }
    }
    [Fact]
    public void Paired_contrasts_resample_conversations_and_the_sign_flip_test_is_exact()
    {
        // ten conversations, all positive: only the two all-same-sign assignments reach the observed mean
        double[] a = [0.5, 0.6, 0.4, 0.7, 0.5, 0.6, 0.5, 0.4, 0.6, 0.5], b = [.. a.Select(x => x - 0.1)];
        var c = MemoryUncertainty.Macro("t", a, b, iterations: 2000, seed: 7);
        Assert.Equal(0.1, c.Difference, 12);
        Assert.Equal(2.0 / 1024, c.SignFlipP, 12);
        Assert.Equal((10, 0), (c.ConversationsPositive, c.ConversationsNegative));
        Assert.Equal(0.1, c.BootstrapLo, 9);                 // every resample of constant differences is 0.1
        // symmetric differences: no evidence of an effect
        Assert.Equal(1.0, MemoryUncertainty.SignFlip([0.1, -0.1, 0.2, -0.2], x => x.Average()), 12);
        // micro caliber pools hits over questions
        var m = MemoryUncertainty.Micro("m", [3, 1], [1, 1], [4, 2], iterations: 500, seed: 1);
        Assert.Equal((4.0 / 6) - (2.0 / 6), m.Difference, 12);
    }
    [Fact]
    public void LongMemEval_questions_become_one_question_conversations_and_large_samples_use_monte_carlo_sign_flips()
    {
        const string json = """
            [{"question_id":"q1","question_type":"single-session-user","question":"What degree did I get?","answer":"BA",
              "question_date":"2023/05/30 (Tue) 23:40","haystack_dates":["2023/05/20 (Sat) 02:21","2023/05/21 (Sun) 10:00"],
              "haystack_session_ids":["s_a","s_b"],
              "haystack_sessions":[[{"role":"user","content":"hi"},{"role":"assistant","content":"hello"}],
                                   [{"role":"user","content":"I graduated with a BA","has_answer":true},{"role":"assistant","content":"congrats","has_answer":false}]]},
             {"question_id":"q2_abs","question_type":"temporal-reasoning","question":"?","answer":"n/a","question_date":"2023/05/30 (Tue) 23:40",
              "haystack_dates":["2023/05/20 (Sat) 02:21"],"haystack_session_ids":["s_c"],"haystack_sessions":[[{"role":"user","content":"x"}]]}]
            """;
        using var doc = System.Text.Json.JsonDocument.Parse(json);
        var parsed = doc.RootElement.EnumerateArray().Select(LongMemEvalCorpus.ParseQuestion).ToList();
        Assert.Null(parsed[1]);                                   // no marked evidence: left out
        var conv = parsed[0]!;
        Assert.Equal(4, conv.Episodes.Count);
        Assert.Equal(["1:s_b#0"], conv.Qa.Single().Evidence);
        Assert.Equal(LongMemEvalCorpus.ParseDate("2023/05/21 (Sun) 10:00")!.Value + 60_000, conv.Episodes[3].CreatedAt);
        Assert.Equal(LongMemEvalCorpus.ParseDate("2023/05/30 (Tue) 23:40"), conv.EndTs);
        // more than 20 units: Monte Carlo sign flips, never below 1 / (draws + 1)
        var d = Enumerable.Repeat(0.1, 50).ToArray();
        Assert.Equal(1.0 / 10_001, MemoryUncertainty.SignFlip(d, x => x.Average()), 12);
    }
}
