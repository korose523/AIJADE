using System.Text.Json.Nodes;

using Aijade.Memory.Development;

namespace Aijade.Tests;

// Delivery bridge only: it neither grants reuse nor checks suitability for the request.
internal static class ResearchPersistedAct
{
    internal static DialogueAct Read(JsonNode specification)
    {
        if (specification is not JsonObject root || root["proposal"] is not JsonObject proposal ||
            proposal["candidateParams"] is not JsonObject parameters ||
            parameters.Count != 1 || parameters["emotion.preset"] is not JsonValue value ||
            !value.TryGetValue<string>(out var act))
            throw new InvalidDataException("persisted_act_configuration_missing");
        return act switch
        {
            "inform" => DialogueAct.Inform,
            "comfort" => DialogueAct.Comfort,
            "celebrate" => DialogueAct.Celebrate,
            _ => throw new InvalidDataException("persisted_act_not_allowlisted"),
        };
    }
}
