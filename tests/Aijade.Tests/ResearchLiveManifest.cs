using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace Aijade.Tests;

internal sealed record ResearchLiveOperations
{
    public required string Execution { get; init; }
    public required string? MapperActOverride { get; init; }
    public required string ReceiptCaseId { get; init; }
    public required string? AssetVersionOverride { get; init; }
    public required string ClaimedStage { get; init; }
    public required bool RepeatOutcome { get; init; }
    public required bool RevokeBeforeReuse { get; init; }
    public required bool FailStateWrite { get; init; }
}

internal sealed record ResearchLiveCase
{
    public required string CaseId { get; init; }
    public required List<string> Conditions { get; init; }
    public required string TaskId { get; init; }
    public required string CodeSha256 { get; init; }
    public required string RequestedAct { get; init; }
    public required ResearchLiveOperations Operations { get; init; }
}

/// <summary>Closed operational inputs only; classes, expected outcomes and scoring never enter this type.</summary>
internal sealed record ResearchLiveManifest
{
    public required string Schema { get; init; }
    public required string Purpose { get; init; }
    public required string OriginPacketManifestSha256 { get; init; }
    public required string SelectionSha256 { get; init; }
    public required string SourceAliasMapSha256 { get; init; }
    public required List<ResearchLiveCase> Cases { get; init; }

    private static readonly string[] Acts = ["inform", "comfort", "celebrate"];
    private static readonly string[] Arms = ["C1", "C2"];
    internal static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = false,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
    };

    public static ResearchLiveManifest Read(string text)
    {
        try
        {
            using var parsed = JsonDocument.Parse(text);
            CheckUniqueProperties(parsed.RootElement);
            var manifest = parsed.RootElement.Deserialize<ResearchLiveManifest>(Options)
                ?? throw new InvalidDataException("Missing live manifest");
            if (manifest.Schema != "aijade.ch7.live-case-manifest.v1" || manifest.Purpose != "known_development_qualification_only")
                throw new InvalidDataException("Unknown schema or held-out purpose is not enabled");
            if (!Hash(manifest.OriginPacketManifestSha256) || !Hash(manifest.SelectionSha256) || !Hash(manifest.SourceAliasMapSha256))
                throw new InvalidDataException("Manifest source hash");
            if (manifest.Cases is not { Count: >= 1 and <= 10 })
                throw new InvalidDataException("A renderer block holds one to ten pairs");
            var seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (var item in manifest.Cases)
            {
                if (item is null || item.CaseId is null || !Regex.IsMatch(item.CaseId, "^[A-Za-z0-9_-]{1,80}$") || !seen.Add(item.CaseId))
                    throw new InvalidDataException("Missing, duplicate or invalid case identity");
                if (item.Conditions is not { Count: 2 } || !item.Conditions.Order(StringComparer.Ordinal).SequenceEqual(Arms))
                    throw new InvalidDataException("Each pair needs C1 and C2 exactly once");
                if (string.IsNullOrWhiteSpace(item.TaskId) || !Hash(item.CodeSha256) || !Acts.Contains(item.RequestedAct, StringComparer.Ordinal))
                    throw new InvalidDataException("Programme or requested act");
                var op = item.Operations ?? throw new InvalidDataException("Missing operations");
                if (op.Execution is not ("run" or "omit") || op.ReceiptCaseId is null ||
                    op.ClaimedStage is not ("behavior_overlay_pre_solve" or "pixels_observed") ||
                    op.MapperActOverride is not null && !Acts.Contains(op.MapperActOverride, StringComparer.Ordinal) ||
                    op.AssetVersionOverride is not null && !Regex.IsMatch(op.AssetVersionOverride, "^[A-Za-z0-9_-]{1,128}$"))
                    throw new InvalidDataException("Invalid operation value");
            }
            if (manifest.Cases.Any(c => !seen.Contains(c.Operations.ReceiptCaseId)))
                throw new InvalidDataException("Dangling selected receipt case");
            if (Math.Abs(manifest.Cases.Count(c => c.Conditions[0] == "C1") - manifest.Cases.Count(c => c.Conditions[0] == "C2")) > 1)
                throw new InvalidDataException("Unbalanced first-arm order");
            return manifest;
        }
        catch (JsonException ex)
        {
            throw new InvalidDataException("Invalid or incomplete live manifest", ex);
        }
    }

    private static bool Hash(string? text) => text is not null && Regex.IsMatch(text, "^[0-9a-f]{64}$");

    private static void CheckUniqueProperties(JsonElement element)
    {
        if (element.ValueKind == JsonValueKind.Object)
        {
            var seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (var property in element.EnumerateObject())
            {
                if (!seen.Add(property.Name))
                    throw new InvalidDataException("Duplicate JSON property: " + property.Name);
                CheckUniqueProperties(property.Value);
            }
        }
        else if (element.ValueKind == JsonValueKind.Array)
        {
            foreach (var child in element.EnumerateArray()) CheckUniqueProperties(child);
        }
    }
}
