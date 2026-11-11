using System.Text.Json.Nodes;

using Aijade.Memory.Development;
using Aijade.Research.Integration;

namespace Aijade.Tests;

public class ResearchPersistedActTests
{
    [Theory]
    [InlineData("inform", DialogueAct.Inform)]
    [InlineData("comfort", DialogueAct.Comfort)]
    [InlineData("celebrate", DialogueAct.Celebrate)]
    public void Read_actual_persisted_parameter(string text, DialogueAct expected)
    {
        var spec = new JsonObject { ["proposal"] = new JsonObject {
            ["candidateParams"] = new JsonObject { ["emotion.preset"] = text } } };
        Assert.Equal(expected, ResearchPersistedAct.Read(spec));
    }

    [Theory]
    [InlineData("{}")]
    [InlineData("""{"proposal":{"candidateParams":{}}}""")]
    [InlineData("""{"proposal":{"candidateParams":{"emotion.preset":"unknown"}}}""")]
    [InlineData("""{"proposal":{"candidateParams":{"emotion.preset":"comfort","other":1}}}""")]
    public void Missing_unknown_or_extra_configuration_cannot_supply_a_default(string text)
    {
        Assert.Throws<InvalidDataException>(() => ResearchPersistedAct.Read(JsonNode.Parse(text)!));
    }

    [Fact]
    public void Stored_wrong_act_is_delivered_without_request_based_correction()
    {
        var spec = JsonNode.Parse("""{"proposal":{"candidateParams":{"emotion.preset":"celebrate"}}}""")!;
        var actual = ResearchPersistedAct.Read(spec);
        var intent = ResearchIntentMapper.Map(actual, "round2-control", "persona:ch7", true);
        Assert.Equal(DialogueAct.Celebrate, actual);
        Assert.Equal("bright_smile", intent.Face);
    }
}
