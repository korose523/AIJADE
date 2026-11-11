using Aijade.Core.Js;
using Aijade.Memory.Contracts;
using Aijade.Memory.Development;

namespace Aijade.Research.Integration;

/// <summary>Evidence states for the staged research loop; an outcome memory is only a projection of this authority.</summary>
public enum SkillEvidenceState
{
    Unknown,
    Failed,
    Verified,
    Revoked,
}

/// <summary>Bindings qualified before a proposal can become a promotion job. A render receipt proves only its stated stage.</summary>
public sealed record SkillEvidence(
    string SkillId, string CodeSha256, string TaskId, string BenchSha256, string ExecutionId,
    string IntentId, string SessionId, string AssetVersion, string ReceiptIntentId, string ReceiptAssetVersion,
    string ReceiptStage, string ClaimedStage, bool? ExecutionOk, int Passed, int Total, string SelfVerdict)
{
    public const string AppliedStage = "behavior_overlay_pre_solve";

    public string Scope => $"bench:{TaskId}@{BenchSha256};render:{ReceiptStage}";

    /// <summary>First cross-record refusal. SelfVerdict is recorded but cannot supply missing or failed execution evidence.</summary>
    public string? Refusal()
    {
        if (string.IsNullOrWhiteSpace(SkillId) || string.IsNullOrWhiteSpace(TaskId) || string.IsNullOrWhiteSpace(IntentId) ||
            string.IsNullOrWhiteSpace(SessionId) || string.IsNullOrWhiteSpace(AssetVersion) ||
            CodeSha256.Length != 64 || !CodeSha256.All(Uri.IsHexDigit) || BenchSha256.Length != 64 || !BenchSha256.All(Uri.IsHexDigit) || string.IsNullOrWhiteSpace(ExecutionId))
            return "evidence_identity_missing";
        if (IntentId != ReceiptIntentId)
            return "execution_intent_mismatch";
        if (AssetVersion != ReceiptAssetVersion)
            return "asset_version_mismatch";
        if (ReceiptStage != AppliedStage || ClaimedStage != ReceiptStage)
            return "receipt_stage_insufficient";
        if (ExecutionOk is null)
            return "execution_unknown";
        if (ExecutionOk != true || Passed != Total || Total <= 0)
            return "execution_failed";
        return null;
    }

    public SkillEvidenceState State => ExecutionOk switch
    {
        null => SkillEvidenceState.Unknown,
        false => SkillEvidenceState.Failed,
        true => Refusal() is null ? SkillEvidenceState.Verified : SkillEvidenceState.Unknown,
    };

    public static string HashCode(string code) => JsFormat.Sha256Hex(code);
}

/// <summary>
/// An intentionally small, versioned research mapper. Only allow-listed acts become parameters; no candidate-produced
/// object keys or values are dispatched. This checks the representable command, not whether that command suits the user.
/// </summary>
public static class ResearchIntentMapper
{
    public const string Version = "ch7-allowlisted-acts-v1";

    public static IReadOnlyList<DialogueAct> Allowed { get; } = Array.AsReadOnly<DialogueAct>([DialogueAct.Inform, DialogueAct.Comfort, DialogueAct.Celebrate]);

    public static PerformanceIntent Map(DialogueAct act, string intentId, string personaSnapshotRef, bool? executionOk = true)
    {
        if (!Allowed.Contains(act))
            throw new ArgumentOutOfRangeException(nameof(act), "The research mapper does not allow this act");
        var selected = executionOk == true ? act : DialogueAct.Inform;
        return Pef.BuildPerformanceIntent(new PersonaInput(selected), new PerformanceIds(intentId, "aijade-ch7", "user:ch7", personaSnapshotRef), 0, 2);
    }
}
