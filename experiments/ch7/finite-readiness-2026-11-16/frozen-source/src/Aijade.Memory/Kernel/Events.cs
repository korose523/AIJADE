using System.Text.Json.Nodes;

using Aijade.Core.Schema;

using static Aijade.Core.Schema.WireSchema;

namespace Aijade.Memory.Kernel;

// v9 unified event envelope and topic payload schemas. All objects are strict: an unknown extra field is rejected, so the
// kernel can never accept an envelope the HTTP boundary would refuse. Payload field names stay snake_case on the wire.

/// <summary>Raised when an event fails validation or the v10 tick / causality requirement.</summary>
public sealed class EventValidationException(string message) : Exception(message);

public static class AijadeEvents
{
    public const string ActiveLearningRequested = "aijade.active_learning.requested";
    public const string ActiveLearningCompleted = "aijade.active_learning.completed";
    public const string EvidenceWeaveCandidateReady = "aijade.evidence.weave_candidate_ready";
    public const string PgcWritePlanReady = "aijade.pgc.write_plan_ready";
    public const string MemoryTxCommitted = "aijade.memory_tx.committed";
    public const string PersonaRenderRequested = "aijade.persona.render_requested";
    public const string LpmRenderReady = "aijade.lpm.render_ready";
    public const string WebpageTextObservation = "aijade.video.observation.webpage_text";
    public const string VideoTranscriptObservation = "aijade.video.observation.video_transcript";
    public const string LearningProposedShadowParams = "aijade.learning.proposed.shadow_params";
    public const string LearningProposedEvidence = "aijade.learning.proposed.evidence";
    public const string LearningConstraintOpinionEvaluation = "aijade.learning.constraint.opinion_evaluation";

    private static Dictionary<string, WireSchema> F(params (string Name, WireSchema Schema)[] fields) =>
        fields.ToDictionary(f => f.Name, f => f.Schema);

    /// <summary>The 13 envelope fields required by the HTTP boundary, plus the optional v10 tick / causality / core node.</summary>
    public static readonly IReadOnlyDictionary<string, WireSchema> EnvelopeFields = F(
        ("event_id", Str(1)),
        ("trace_id", Str(1)),
        ("correlation_id", Str(1)),
        ("timestamp", Whole(0)),
        ("producer", Str(1)),
        ("origin_device", Str(1)),
        ("privacy_level", Union(Literal(0), Literal(1), Literal(2), Literal(3))),
        ("evidence_refs", Arr(Str())),
        ("causal_context_refs", Arr(Str())),
        ("risk_score", Num(0, 1)),
        ("idempotency_key", Str(1)),
        ("replay_mode", Enum("live", "replay")),
        ("risk_level", Enum("low", "medium", "high")),
        // int32 column on the server: out-of-range ticks must be rejected at the boundary, not surface as a DB error.
        ("tick", Whole(0, 2_147_483_647).Optional()),
        ("causality", Obj(F(("inputHash", Str(1)))).Optional()),
        ("core_state_node", Enum(System.Enum.GetNames<CoreStateNode>()).Optional()));

    public static readonly ObjectSchema Envelope = Obj(EnvelopeFields);

    public static readonly ObjectSchema AnyEvent = Obj(EnvelopeFields).Extend(F(("topic", Str(1)), ("payload", Unknown())));

    public static readonly IReadOnlyDictionary<string, ObjectSchema> Payloads = new Dictionary<string, ObjectSchema>
    {
        [ActiveLearningRequested] = Obj(F(
            ("session_id", Str(1)),
            ("trace_id", Str(1)),
            ("requested_at", Whole(0)),
            ("target", Str().Optional()),
            ("quest_ref", Str(1)),
            ("resource_budget", Obj(F(("allocated", Num(0)), ("spent", Num(0)), ("unit", Enum("queries", "minutes", "usd", "tokens"))), strict: false)
                .Refine(b => NumberOf(b["spent"]) <= NumberOf(b["allocated"]), "resource_budget.spent must not exceed allocated (v8 §48.2)")),
            ("stop_conditions", Arr(Str(1), minItems: 1)))),
        [ActiveLearningCompleted] = Obj(F(
            ("session_id", Str(1)), ("trace_id", Str(1)), ("completed_at", Whole(0)), ("result_ref", Str().Optional()), ("quest_ref", Str(1)))),
        [EvidenceWeaveCandidateReady] = Obj(F(
            ("tx_id", Str(1)), ("weave_id", Str(1)), ("graph_hash", Str(1)), ("candidate_memory_write_ids", Arr(Str(1))))),
        [PgcWritePlanReady] = Obj(F(("pgc_state_id", Str(1)), ("write_plan_size", Whole(0)), ("policy_version", Str(1)))),
        [MemoryTxCommitted] = Obj(F(
            ("tx_id", Str(1)), ("trace_id", Str(1)), ("committed_count", Whole(0)), ("rejected_count", Whole(0)), ("throttled_count", Whole(0)))),
        [PersonaRenderRequested] = Obj(F(("session_id", Str(1)), ("persona_snapshot_ref", Str(1)), ("intent_ref", Str(1)))),
        [LpmRenderReady] = Obj(F(
            ("session_id", Str(1)), ("render_ref", Str(1)), ("applied_params_hash", Str(1)), ("asset_version_hash", Str(1).Optional()))),
        [WebpageTextObservation] = Obj(F(
            ("session_id", Str(1)), ("source_url", Str(1)), ("content_hash", Str(1)),
            ("spans", Arr(Obj(F(("start_offset", Whole(0)), ("end_offset", Whole(0)), ("label", Str(1).Optional()))), minItems: 1)),
            ("observation_text", Str(1)))),
        [VideoTranscriptObservation] = Obj(F(
            ("session_id", Str(1)), ("video_id", Str(1)), ("transcript_hash", Str(1)),
            ("time_spans", Arr(Obj(F(("start_ms", Whole(0)), ("end_ms", Whole(0)), ("text", Str(1)))), minItems: 1)),
            ("caption_text", Str(1)))),
        [LearningProposedShadowParams] = Obj(F(
            ("session_id", Str(1)), ("proposal_id", Str(1)), ("render_ref", Str(1)), ("applied_params_hash", Str(1)),
            ("asset_version_hash", Str(1)), ("input_hash", Str(1)), ("candidate_params", Record()), ("confidence", Num(0, 1)))),
        [LearningProposedEvidence] = Obj(F(
            ("session_id", Str(1)), ("proposal_id", Str(1)), ("render_ref", Str(1)), ("applied_params_hash", Str(1)),
            ("asset_version_hash", Str(1)), ("evidence_hash", Str(1)), ("claim_text", Str(1)), ("confidence", Num(0, 1)))),
        [LearningConstraintOpinionEvaluation] = Obj(F(
            ("evaluation_target", Str(1)),
            ("claims", Arr(Obj(F(("claim_text", Str(1)), ("confidence", Num(0, 1)))), minItems: 1)),
            ("uncertainty_notes", Str(1)))),
    };

    /// <summary>Supported topics, in registration order. A topic not listed here is rejected.</summary>
    public static IReadOnlyCollection<string> Topics => Payloads.Keys.ToList();

    private static readonly Dictionary<string, ObjectSchema> TopicEvents =
        Payloads.ToDictionary(kv => kv.Key, kv => Obj(EnvelopeFields).Extend(F(("topic", Literal(kv.Key)), ("payload", kv.Value))));

    /// <summary>Validate a full event (envelope + known topic + its payload). Empty list = valid.</summary>
    public static IReadOnlyList<string> Validate(JsonNode? input)
    {
        var topic = input is JsonObject o && o["topic"] is JsonValue t && t.TryGetValue<string>(out var s) ? s : null;
        if (topic is null || !TopicEvents.TryGetValue(topic, out var schema))
            return [$"$.topic: unsupported topic {(topic is null ? "(missing)" : $"\"{topic}\"")}"];
        return schema.Validate(input);
    }

    public static bool IsValid(JsonNode? input) => Validate(input).Count == 0;

    /// <summary>Video / learning events must carry an integer tick and a non-empty causality.inputHash.</summary>
    public static void AssertV10RequiredFields(JsonObject evt)
    {
        var topic = evt["topic"]?.GetValue<string>() ?? "";
        if (!topic.StartsWith("aijade.video.", StringComparison.Ordinal) && !topic.StartsWith("aijade.learning.", StringComparison.Ordinal))
            return;
        var inputHash = evt["causality"]?["inputHash"]?.GetValue<string>();
        if (evt["tick"] is null || evt["causality"] is null || string.IsNullOrEmpty(inputHash))
            throw new EventValidationException("v10 video/learning events require tick and causality.inputHash");
    }

    /// <summary>Assemble envelope + topic + payload, validate, and enforce the v10 requirement; returns the parsed event. Throws on failure.</summary>
    public static JsonObject Build(string topic, JsonObject envelope, JsonObject payload)
    {
        var evt = (JsonObject)envelope.DeepClone();
        evt["topic"] = topic;
        evt["payload"] = payload.DeepClone();
        var errors = Validate(evt);
        if (errors.Count > 0)
            throw new EventValidationException(string.Join("; ", errors));
        // The parsed form: keys in schema order.
        var parsed = (JsonObject)TopicEvents[topic].Shape(evt)!;
        AssertV10RequiredFields(parsed);
        return parsed;
    }
}
