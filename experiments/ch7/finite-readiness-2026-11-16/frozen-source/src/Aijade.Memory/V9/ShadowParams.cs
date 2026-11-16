using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Memory.Kernel;
using Aijade.Memory.Model;
using Aijade.Memory.Pgc;

namespace Aijade.Memory.V9;

// Learning shadow params: two v10 learning events (proposed shadow params, proposed evidence) are reduced to one candidate
// write that the existing PGC gate decides on. This is NOT the CDI identity shadow evaluation: it asks whether a learned
// parameter change deserves to be kept, not how the agent's identity evolves. Pure and deterministic.

/// <summary>Which fields re-compute the input hash: candidate_params, or the evidence body {evidence_hash, claim_text}.</summary>
public enum ShadowParamsAnchorKind
{
    ShadowParams,
    Evidence,
}

/// <summary>
/// A reduced learning proposal. <see cref="AnchorVerified"/> tells whether the input hash was checked against a declared
/// value (shadow_params) or derived because the contract has none to compare with (evidence); either way it can be
/// recomputed by whoever acts on the proposal.
/// </summary>
public sealed record ShadowParamsProposal(
    string ProposalId, string SessionId, string InputHash, ShadowParamsAnchorKind AnchorKind, bool AnchorVerified, JsonObject CandidateParams,
    double Confidence, string? RenderRef = null, string? AppliedParamsHash = null, string? AssetVersionHash = null, string? EvidenceHash = null,
    string? ClaimText = null)
{
    /// <summary>The proposal as spread into payloads ({...proposal}); absent optional fields are omitted.</summary>
    public JsonObject ToJson()
    {
        var o = new JsonObject
        {
            ["proposalId"] = ProposalId,
            ["sessionId"] = SessionId,
            ["inputHash"] = InputHash,
            ["anchorKind"] = WireName.Of(AnchorKind),
            ["anchorVerified"] = AnchorVerified,
            ["candidateParams"] = CandidateParams.DeepClone(),
            ["confidence"] = Confidence,
        };
        if (RenderRef is not null)
            o["renderRef"] = RenderRef;
        if (AppliedParamsHash is not null)
            o["appliedParamsHash"] = AppliedParamsHash;
        if (AssetVersionHash is not null)
            o["assetVersionHash"] = AssetVersionHash;
        if (EvidenceHash is not null)
            o["evidenceHash"] = EvidenceHash;
        if (ClaimText is not null)
            o["claimText"] = ClaimText;
        return o;
    }

    /// <summary>The inverse of <see cref="ToJson"/> (a proposal read back from a job queue); the anchor is not trusted, re-verify it.</summary>
    public static ShadowParamsProposal FromJson(JsonObject o)
    {
        static string? Opt(JsonNode? n) => n?.GetValue<string>();
        return new ShadowParamsProposal(o["proposalId"]!.GetValue<string>(), o["sessionId"]!.GetValue<string>(), o["inputHash"]!.GetValue<string>(),
            WireName.Parse<ShadowParamsAnchorKind>(o["anchorKind"]!.GetValue<string>()), o["anchorVerified"]!.GetValue<bool>(),
            (JsonObject)(o["candidateParams"]?.DeepClone() ?? new JsonObject()), o["confidence"]!.GetValue<double>(), Opt(o["renderRef"]),
            Opt(o["appliedParamsHash"]), Opt(o["assetVersionHash"]), Opt(o["evidenceHash"]), Opt(o["claimText"]));
    }
}

/// <summary>The gate's rejection: an input hash that does not match, or an unsupported event.</summary>
public sealed class ShadowParamsIntegrityException(string message) : Exception($"[shadow-params] {message}");

public static class ShadowParams
{
    /// <summary>input_hash = contentHash({ session_id, proposal_id, body }); the proposal id keeps equal bodies apart across proposals.</summary>
    public static string ComputeLearningInputHash(string sessionId, string proposalId, JsonNode? body) =>
        V9Hash.ContentHash(new JsonObject { ["session_id"] = sessionId, ["proposal_id"] = proposalId, ["body"] = body?.DeepClone() });

    private static JsonObject EvidenceBody(string evidenceHash, string claimText) => new() { ["evidence_hash"] = evidenceHash, ["claim_text"] = claimText };

    /// <summary>
    /// Recompute the anchor from the proposal's own fields. Proposals travel serialized between processes, so this must be
    /// replayable by anyone holding one; an evidence proposal missing its body is rejected (not computable ≠ consistent).
    /// </summary>
    public static Contracts.Validation VerifyAnchor(ShadowParamsProposal p)
    {
        if (p.AnchorKind == ShadowParamsAnchorKind.ShadowParams)
        {
            var expected = ComputeLearningInputHash(p.SessionId, p.ProposalId, p.CandidateParams);
            return expected == p.InputHash ? Contracts.Validation.Pass
                : Contracts.Validation.Fail($"shadow_params input_hash mismatch: declared={p.InputHash} recomputed={expected}");
        }
        if (p.EvidenceHash is null || p.ClaimText is null)
            return Contracts.Validation.Fail("evidence proposal is missing evidence_hash / claim_text, so its anchor cannot be recomputed");
        var e = ComputeLearningInputHash(p.SessionId, p.ProposalId, EvidenceBody(p.EvidenceHash, p.ClaimText));
        return e == p.InputHash ? Contracts.Validation.Pass : Contracts.Validation.Fail($"evidence input_hash mismatch: declared={p.InputHash} recomputed={e}");
    }

    private static string S(JsonNode? n) => n?.GetValue<string>() ?? "";

    private static double D(JsonNode? n) => Core.Schema.WireSchema.NumberOf(n);

    /// <summary>
    /// Reduce a learning event to a proposal. shadow_params: the declared input_hash must match the recomputed one or
    /// this throws. evidence: the contract has no input_hash, so the anchor is derived from the evidence body.
    /// </summary>
    public static ShadowParamsProposal FromEvent(JsonObject evt)
    {
        var topic = S(evt["topic"]);
        var p = evt["payload"] as JsonObject ?? throw new ShadowParamsIntegrityException("event has no payload");
        if (topic == AijadeEvents.LearningProposedShadowParams)
        {
            var candidateParams = (JsonObject)p["candidate_params"]!;
            var recomputed = ComputeLearningInputHash(S(p["session_id"]), S(p["proposal_id"]), candidateParams);
            if (recomputed != S(p["input_hash"]))
                throw new ShadowParamsIntegrityException($"shadow_params input_hash mismatch: declared={S(p["input_hash"])} recomputed={recomputed}");
            return new ShadowParamsProposal(S(p["proposal_id"]), S(p["session_id"]), S(p["input_hash"]), ShadowParamsAnchorKind.ShadowParams, true,
                (JsonObject)candidateParams.DeepClone(), D(p["confidence"]), S(p["render_ref"]), S(p["applied_params_hash"]), S(p["asset_version_hash"]));
        }
        if (topic == AijadeEvents.LearningProposedEvidence)
        {
            var computed = ComputeLearningInputHash(S(p["session_id"]), S(p["proposal_id"]), EvidenceBody(S(p["evidence_hash"]), S(p["claim_text"])));
            return new ShadowParamsProposal(S(p["proposal_id"]), S(p["session_id"]), computed, ShadowParamsAnchorKind.Evidence, false, [],
                D(p["confidence"]), S(p["render_ref"]), S(p["applied_params_hash"]), S(p["asset_version_hash"]), S(p["evidence_hash"]), S(p["claim_text"]));
        }
        throw new ShadowParamsIntegrityException($"unsupported event topic for shadow-params reduction: {topic}");
    }

    /// <summary>
    /// The proposal as a PGC candidate: salience = confidence, social 0, novelty = 1 − confidence, intensity = confidence;
    /// the evidence is the proposal itself (shadow_{id}); default kind knowledge_card (τ = semantic).
    /// </summary>
    public static PgcCandidateWrite AsPgcCandidate(ShadowParamsProposal p, MemoryKind memoryKind = MemoryKind.KnowledgeCard, IReadOnlyList<string>? evidenceIds = null, string? memoryWriteId = null)
    {
        var c = Math.Max(0, Math.Min(1, p.Confidence));
        return new PgcCandidateWrite(memoryWriteId ?? $"sp_{p.ProposalId}", memoryKind, p.ToJson(), evidenceIds ?? [$"shadow_{p.ProposalId}"], c, null, new ContentSalience(c, 0, 1 - c));
    }

    /// <summary>Stimulus features of the learning path, centred on confidence (independent of the perception path).</summary>
    public static Dictionary<StimulusFeature, double> LearningStimulus(ShadowParamsProposal p)
    {
        var c = Math.Max(0, Math.Min(1, p.Confidence));
        return new() { [StimulusFeature.UncertaintyLoadScore] = 1 - c, [StimulusFeature.StimArousalScore] = c, [StimulusFeature.StimDriveScore] = c, [StimulusFeature.StimFatigueScore] = 0 };
    }
}

public enum VideoObservationKind
{
    WebpageText,
    VideoTranscript,
}

public sealed record EvidenceCandidate(VideoObservationKind SourceKind, string SourceRef, string ClaimText, string EvidenceHash, double Confidence);

/// <summary>
/// Video observations (webpage text, subtitles) → evidence candidates → aijade.learning.proposed.evidence. Render ref,
/// applied-params hash and asset version must come from the app layer: synthesized defaults are forbidden (v10 §14.4).
/// </summary>
public static class VideoObservation
{
    private static double Clamp01(double v) => double.IsFinite(v) ? Math.Max(0, Math.Min(1, v)) : 0;

    /// <summary>contentHash({ source_kind, source_ref, claim_text }); written verbatim as evidence_hash, never re-normalized.</summary>
    public static string EvidenceHashFor(VideoObservationKind kind, string sourceRef, string claimText) =>
        V9Hash.ContentHash(new JsonObject { ["source_kind"] = WireName.Of(kind), ["source_ref"] = sourceRef, ["claim_text"] = claimText });

    private static string S(JsonNode? n) => n is JsonValue v && v.TryGetValue<string>(out var s) ? s : "";

    private static EvidenceCandidate From(JsonObject payload, VideoObservationKind kind, string textField, string hashField, string spansField, string what, string spanWhat)
    {
        var text = S(payload[textField]);
        var hash = S(payload[hashField]);
        if (JsText.Trim(text).Length == 0)
            throw new ArgumentException($"[video-observation] {what} observation requires non-empty {textField}", nameof(payload));
        if (JsText.Trim(hash).Length == 0)
            throw new ArgumentException($"[video-observation] {what} observation requires non-empty {hashField}", nameof(payload));
        if (payload[spansField] is not JsonArray { Count: > 0 } spans)
            throw new ArgumentException($"[video-observation] {what} observation requires at least one {spanWhat}", nameof(payload));
        // More spans, firmer evidence (capped at 1.0).
        return new EvidenceCandidate(kind, hash, text, EvidenceHashFor(kind, hash, text), Clamp01(0.5 + (0.1 * Math.Min(spans.Count, 5))));
    }

    public static EvidenceCandidate FromWebpage(JsonObject payload) =>
        From(payload, VideoObservationKind.WebpageText, "observation_text", "content_hash", "spans", "webpage", "span");

    public static EvidenceCandidate FromSubtitles(JsonObject payload) =>
        From(payload, VideoObservationKind.VideoTranscript, "caption_text", "transcript_hash", "time_spans", "subtitle", "time_span");

    public static JsonObject ToEventPayload(EvidenceCandidate c, string sessionId, string proposalId, string? renderRef, string? appliedParamsHash, string? assetVersionHash, double? confidence = null)
    {
        if (renderRef is null || appliedParamsHash is null || assetVersionHash is null)
        {
            throw new ArgumentException("[video-observation] learning.proposed.evidence requires explicit renderRef, "
                + "appliedParamsHash, and assetVersionHash; synthesized defaults are forbidden (v10 §14.4 / report P0-2)");
        }
        return new JsonObject
        {
            ["session_id"] = sessionId,
            ["proposal_id"] = proposalId,
            ["render_ref"] = renderRef,
            ["applied_params_hash"] = appliedParamsHash,
            ["asset_version_hash"] = assetVersionHash,
            ["evidence_hash"] = c.EvidenceHash,
            ["claim_text"] = c.ClaimText,
            ["confidence"] = Clamp01(confidence ?? c.Confidence),
        };
    }

    public static string ProposalInputHash(string sessionId, string proposalId, EvidenceCandidate c) =>
        ShadowParams.ComputeLearningInputHash(sessionId, proposalId, new JsonObject { ["evidence_hash"] = c.EvidenceHash, ["claim_text"] = c.ClaimText });
}
