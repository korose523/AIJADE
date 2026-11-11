using System.Text.Json;

using Aijade.Memory.Locomo;

namespace Aijade.Tests;

public sealed class LongMemEvalEligibilityTests
{
    private static readonly string[] Dates = ["2023/05/20 (Sat) 02:21", "unparseable"];
    private static readonly string[] SessionIds = ["repeated", "repeated"];
    private static readonly string[] ExpectedIds = ["0:repeated#0", "1:repeated#0"];
    private static JsonDocument Question(string id, bool marked) => JsonDocument.Parse(JsonSerializer.Serialize(new
    {
        question_id = id, question = "Where?", answer = "there", question_date = "unparseable",
        haystack_dates = Dates,
        haystack_session_ids = SessionIds,
        haystack_sessions = new[]
        {
            new[] { new { role = "user", content = "there", has_answer = marked } },
            new[] { new { role = "assistant", content = "there too", has_answer = false } },
        },
    }));

    [Theory]
    [InlineData("q_abs", true)]
    [InlineData("q_abs", false)]
    [InlineData("q_abs_middle", true)]
    public void Official_abstention_predicate_overrides_marked_turns_without_erasing_annotations(string id, bool marked)
    {
        using var doc = Question(id, marked);
        Assert.Null(LongMemEvalCorpus.ParseQuestion(doc.RootElement));
        var all = LongMemEvalCorpus.ParseQuestion(doc.RootElement, LongMemEvalFrame.AllQuestionsV1)!;
        Assert.Equal(5, all.Qa.Single().Category);
        Assert.Equal(marked ? 1 : 0, all.EvidenceIds.Count);
        var legacy = LongMemEvalCorpus.ParseQuestion(doc.RootElement, LongMemEvalFrame.LegacyMarkedV1);
        if (!marked)
            Assert.Null(legacy);
        else
        {
            Assert.Equal(0, legacy!.Qa.Single().Category);
            Assert.Equal(JsonSerializer.Serialize(all.Episodes), JsonSerializer.Serialize(legacy.Episodes));
            Assert.Equal(all.EndTs, legacy.EndTs);
            Assert.Equal(all.EvidenceIds, legacy.EvidenceIds);
        }
    }

    [Theory]
    [InlineData(LongMemEvalFrame.AnswerableV2)]
    [InlineData(LongMemEvalFrame.AllQuestionsV1)]
    public void Missing_non_abstention_evidence_is_an_input_error(LongMemEvalFrame frame)
    {
        using var doc = Question("normal", false);
        Assert.Throws<InvalidDataException>(() => LongMemEvalCorpus.ParseQuestion(doc.RootElement, frame));
        Assert.Null(LongMemEvalCorpus.ParseQuestion(doc.RootElement, LongMemEvalFrame.LegacyMarkedV1));
    }

    [Fact]
    public void Normal_legacy_shape_dates_and_source_position_ids_are_preserved()
    {
        using var doc = Question("normal", true);
        var primary = LongMemEvalCorpus.ParseQuestion(doc.RootElement)!;
        var legacy = LongMemEvalCorpus.ParseQuestion(doc.RootElement, LongMemEvalFrame.LegacyMarkedV1)!;
        Assert.Equal(JsonSerializer.Serialize(legacy), JsonSerializer.Serialize(primary));
        Assert.Equal(ExpectedIds, primary.Episodes.Select(e => e.Id));
        Assert.Equal(LongMemEvalCorpus.ParseDate("2023/05/20 (Sat) 02:21"), primary.Episodes[0].CreatedAt);
        Assert.Equal(LocomoCorpus.DateUtc(2023, 0, 1) + LocomoCorpus.Day, primary.Episodes[1].CreatedAt);
        Assert.Equal(primary.Episodes.Max(e => e.CreatedAt), primary.EndTs);
        Assert.Equal("answerable-v2", LongMemEvalCorpus.FrameName(LongMemEvalFrame.AnswerableV2));
        Assert.Equal("legacy-marked-v1", LongMemEvalCorpus.FrameName(LongMemEvalFrame.LegacyMarkedV1));
        Assert.Equal("all-questions-v1", LongMemEvalCorpus.FrameName(LongMemEvalFrame.AllQuestionsV1));
        Assert.Throws<ArgumentOutOfRangeException>(() => LongMemEvalCorpus.FrameName((LongMemEvalFrame)99));
    }
}
