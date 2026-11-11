using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Memory.Development;

namespace Aijade.Research.Integration;

/// <summary>A closed development catalogue. Retrieved text can select a verified hash, never supply new code.</summary>
public sealed record ResearchProgram(string TaskId, string CodeSha256, string Code);

/// <summary>A research-only route derived from returned memory content, before execution or intent mapping.</summary>
public sealed record ResearchRetrievedRoute(string CaseId, string MemoryContentSha256, ResearchProgram Program, DialogueAct RequestedAct)
{
    public const string Version = "ch7-retrieved-catalogue-v1";

    public static string Prefix(string caseId) => "ch7_route_" + caseId + " ";

    public static ResearchRetrievedRoute Select(string content, string expectedCase, IReadOnlyList<ResearchProgram> catalogue)
    {
        if (!content.StartsWith(Prefix(expectedCase), StringComparison.Ordinal))
            throw new InvalidDataException("route_case_mismatch");
        JsonObject cue;
        try
        {
            cue = JsonNode.Parse(content[Prefix(expectedCase).Length..]) as JsonObject ?? throw new InvalidDataException("route_not_object");
        }
        catch (JsonException ex)
        {
            throw new InvalidDataException("route_invalid_json", ex);
        }
        if (Read(cue, "caseId") != expectedCase)
            throw new InvalidDataException("route_case_mismatch");
        var taskId = Read(cue, "taskId");
        var hash = Read(cue, "codeSha256");
        var matches = catalogue.Where(p => p.TaskId == taskId && p.CodeSha256 == hash && SkillEvidence.HashCode(p.Code) == hash).ToArray();
        if (matches.Length != 1)
            throw new InvalidDataException("route_program_not_in_catalogue");
        var act = Read(cue, "requestedAct") switch
        {
            "comfort" => DialogueAct.Comfort,
            "celebrate" => DialogueAct.Celebrate,
            "inform" => DialogueAct.Inform,
            _ => throw new InvalidDataException("route_act_not_allowlisted"),
        };
        return new ResearchRetrievedRoute(expectedCase, SkillEvidence.HashCode(content), matches[0], act);
    }

    private static string Read(JsonObject cue, string key) =>
        cue[key] is JsonValue value && value.TryGetValue<string>(out var text) ? text : throw new InvalidDataException("route_string_required_" + key);
}
