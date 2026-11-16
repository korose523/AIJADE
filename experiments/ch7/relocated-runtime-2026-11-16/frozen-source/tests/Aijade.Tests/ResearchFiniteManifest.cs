using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;

namespace Aijade.Tests;

internal sealed record ResearchFiniteCase
{
    public required ResearchLiveCase Input { get; init; }
    public required string ReplayAt { get; init; }
    public required string RevokeAt { get; init; }
    public required string FailurePoint { get; init; }
}

/// <summary>Operational inputs only. No family, scoring window or expected arm outcome.</summary>
internal sealed record ResearchFiniteManifest
{
    public required string Schema { get; init; }
    public required string Purpose { get; init; }
    public required string ProtocolPlanSha256 { get; init; }
    public required string ConstructionFreezeCommit { get; init; }
    public required string SelectionSha256 { get; init; }
    public required int BlockIndex { get; init; }
    public required List<ResearchFiniteCase> Cases { get; init; }

    internal static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web)
    {
        PropertyNameCaseInsensitive = false,
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
    };

    public static ResearchFiniteManifest Read(string text)
    {
        try
        {
            using var parsed = JsonDocument.Parse(text);
            Unique(parsed.RootElement);
            var m = parsed.RootElement.Deserialize<ResearchFiniteManifest>(Options)
                ?? throw new InvalidDataException("Missing finite manifest");
            if (m.Schema != "aijade.ch7.live-case-manifest.v2" ||
                m.Purpose is not ("qualification_only" or "confirmed_finite_heldout"))
                throw new InvalidDataException("Finite manifest scope");
            if (!Hash(m.ProtocolPlanSha256, 64) || !Hash(m.SelectionSha256, 64) || !Hash(m.ConstructionFreezeCommit, 40))
                throw new InvalidDataException("Finite manifest source identity");
            if (m.BlockIndex is < 0 or > 3 || m.Cases is not { Count: >= 1 and <= 10 } ||
                m.Purpose == "confirmed_finite_heldout" && m.Cases.Count != 10)
                throw new InvalidDataException("Finite block population");
            var seen = new HashSet<string>(StringComparer.Ordinal);
            foreach (var c in m.Cases)
            {
                var d = c?.Input ?? throw new InvalidDataException("Missing operational input");
                if (d.CaseId is null || !Regex.IsMatch(d.CaseId, "^[A-Za-z0-9_-]{1,80}$") || !seen.Add(d.CaseId) ||
                    d.Conditions is not { Count: 2 } || !d.Conditions.Order(StringComparer.Ordinal).SequenceEqual(["C1", "C2"]) ||
                    string.IsNullOrWhiteSpace(d.TaskId) || !Hash(d.CodeSha256, 64) || !Act(d.RequestedAct))
                    throw new InvalidDataException("Finite case identity/programme/arms");
                var op = d.Operations ?? throw new InvalidDataException("Missing operations");
                if (op.Execution is not ("run" or "omit") || string.IsNullOrWhiteSpace(op.ReceiptCaseId) ||
                    op.ClaimedStage is not ("behavior_overlay_pre_solve" or "pixels_observed") ||
                    op.MapperActOverride is not null && !Act(op.MapperActOverride) ||
                    op.AssetVersionOverride is not null && !Regex.IsMatch(op.AssetVersionOverride, "^[A-Za-z0-9_-]{1,128}$"))
                    throw new InvalidDataException("Invalid finite operation");
                if (c.ReplayAt is not ("none" or "before_delivery" or "after_delivery" or "after_first_reuse" or "after_duplicate_reuse") ||
                    c.RevokeAt is not ("none" or "before_delivery" or "after_delivery" or "after_memory_probe" or "after_authority_probe") ||
                    c.FailurePoint is not ("none" or "authority_before" or "authority_after" or "outcome_before" or "outbox_before") ||
                    op.RepeatOutcome != (c.ReplayAt != "none") || op.RevokeBeforeReuse != (c.RevokeAt != "none") ||
                    op.FailStateWrite != (c.FailurePoint != "none"))
                    throw new InvalidDataException("Missing/inconsistent operation placement");
                // The confirmed design has one intervention per case. Neither arm sees a class label.
                if (new[] { op.RepeatOutcome, op.RevokeBeforeReuse, op.FailStateWrite }.Count(v => v) > 1)
                    throw new InvalidDataException("Combined operation placements are not in the frozen design");
            }
            if (m.Cases.Any(c => !seen.Contains(c.Input.Operations.ReceiptCaseId)) ||
                Math.Abs(m.Cases.Count(c => c.Input.Conditions[0] == "C1") - m.Cases.Count(c => c.Input.Conditions[0] == "C2")) > 1)
                throw new InvalidDataException("Dangling receipt or unbalanced first-arm order");
            return m;
        }
        catch (JsonException ex) { throw new InvalidDataException("Invalid or incomplete finite manifest", ex); }
    }

    private static bool Hash(string? text, int length) => text is not null && Regex.IsMatch(text, "^[0-9a-f]{" + length + "}$");
    private static bool Act(string? text) => text is "inform" or "comfort" or "celebrate";

    private static void Unique(JsonElement e)
    {
        if (e.ValueKind == JsonValueKind.Object)
        {
            var names = new HashSet<string>(StringComparer.Ordinal);
            foreach (var p in e.EnumerateObject())
            {
                if (!names.Add(p.Name)) throw new InvalidDataException("Duplicate JSON property");
                Unique(p.Value);
            }
        }
        else if (e.ValueKind == JsonValueKind.Array) foreach (var item in e.EnumerateArray()) Unique(item);
    }
}
