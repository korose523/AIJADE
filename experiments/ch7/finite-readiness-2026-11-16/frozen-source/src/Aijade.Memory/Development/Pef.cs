using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Memory.Contracts;
using Aijade.Memory.Kernel;

namespace Aijade.Memory.Development;

// v8 §52 PEF, the Persona–Expression Field: the persona stack (constitutional, character, developmental, relationship,
// expressive state, dialogue act, scene) maps onto a continuous expression vector e_t and backend-agnostic channels, so the
// cognitive layer never depends on a renderer (generative video or a VRM / Live2D / MMD avatar). Performance is
// incremental and full duplex; generated output is checked for identity consistency and degrades to a controllable
// avatar or pure voice on failure. Pure and deterministic; renderer wiring lives in the runtime layer.

public enum DialogueAct
{
    Inform,
    Question,
    Answer,
    Comfort,
    Celebrate,
    Apologise,
    Refuse,
    Backchannel,
    Greet,
    Farewell,
    ThinkAloud,
}

/// <summary>A partial expression vector; absent components contribute nothing.</summary>
public sealed record PartialExpression(
    double? Valence = null, double? Arousal = null, double? Dominance = null, double? Intimacy = null, double? Certainty = null,
    double? Curiosity = null, double? Playfulness = null, double? Reflection = null, double? Urgency = null)
{
    internal double?[] ToArray() => [Valence, Arousal, Dominance, Intimacy, Certainty, Curiosity, Playfulness, Reflection, Urgency];
}

public sealed record ConstitutionalSelf(IReadOnlyList<string>? ValueBoundaries = null, string? IdentityNarrative = null);

/// <summary>Growth evidence (interests, milestones, aesthetics, themes) — never unverified consciousness claims.</summary>
public sealed record DevelopmentalSelf(
    IReadOnlyList<string>? Interests = null, IReadOnlyList<string>? Milestones = null, IReadOnlyList<string>? Aesthetics = null,
    IReadOnlyList<string>? AutobiographicalThemes = null);

/// <summary>Dyadic context: intimacy (closeness) and formality (0 casual … 1 formal), both in [0, 1].</summary>
public sealed record RelationshipModel(double? Intimacy = null, double? Formality = null, IReadOnlyList<string>? BoundaryTags = null);

/// <summary>The seven §52.2 persona-stack inputs; only the dialogue act is required.</summary>
public sealed record PersonaInput(
    DialogueAct DialogueAct, ConstitutionalSelf? Constitutional = null, PartialExpression? Character = null, DevelopmentalSelf? Developmental = null,
    RelationshipModel? Relationship = null, PartialExpression? ExpressiveState = null, string? SceneContext = null);

public sealed record PerformanceChannels(
    string TextStyle, VoiceProsody VoiceProsody, string Face, string Gaze, string Gesture, string Posture, string TurnTaking, string CameraBehavior);

public sealed record PerformanceIds(string Id, string AgentId, string UserScope, string PersonaSnapshotRef);

public enum DuplexEvent
{
    /// <summary>The user is speaking; a backchannel opportunity.</summary>
    ListenSignal,
    /// <summary>No committed clause yet; anticipate.</summary>
    PartialSemantics,
    /// <summary>A clause is ready to perform.</summary>
    CommittedClause,
    /// <summary>The user barged in.</summary>
    UserInterruption,
}

public sealed record DuplexDecision(string TurnTaking, string Motion, bool AbortSpeech, bool BlendOutMotion);

/// <summary>Renderer-side observations of one generated segment; drift / conflict scores in [0, 1] (0 = perfect).</summary>
public sealed record ConsistencyObservation(
    double? FaceIdentityDrift = null, double? ClothingDrift = null, double? VoiceprintDrift = null, double? ProsodyDrift = null,
    IReadOnlyList<string>? ForbiddenActions = null, double? EmotionSemanticConflict = null, double? LipSyncDeviationMs = null,
    bool? SceneContinuityBreak = null, IReadOnlyList<string>? BoundaryViolations = null);

public sealed record ConsistencyThresholds(
    double FaceIdentityDrift = 0.2, double ClothingDrift = 0.3, double VoiceprintDrift = 0.25, double ProsodyDrift = 0.4,
    double EmotionSemanticConflict = 0.5, double LipSyncDeviationMs = 120)
{
    public static ConsistencyThresholds Default { get; } = new();
}

public enum ConsistencyFailureKind
{
    FaceIdentityDrift,
    ClothingDrift,
    VoiceprintDrift,
    ProsodyDrift,
    ForbiddenAction,
    EmotionSemanticConflict,
    LipSyncDeviation,
    SceneContinuity,
    BoundaryViolation,
}

public sealed record ConsistencyFailure(ConsistencyFailureKind Kind, string Detail);

/// <summary>Avatar = controllable parametric avatar (identity guaranteed); Voice = pure voice, the strongest fallback.</summary>
public enum DegradeMode
{
    None,
    Avatar,
    Voice,
}

public sealed record ConsistencyVerdict(bool Ok, DegradeMode Degrade, IReadOnlyList<ConsistencyFailure> Failures);

/// <summary>The input of an lpm.render_ready receipt: the canonical applied-parameter text is computed by the side holding the map.</summary>
public sealed record LpmRenderReceipt(string SessionId, string RenderRef, string AppliedParamsHash, string? AssetVersionHash = null);

public static class Pef
{
    /// <summary>A calm, attentive, mid-everything agent.</summary>
    public static ExpressionVector Neutral { get; } = new(0, 0.4, 0.5, 0.4, 0.6, 0.5, 0.3, 0.4, 0.2);

    /// <summary>Weight of the transient expressive state against the stable baseline.</summary>
    public const double ExpressiveStateWeight = 0.6;

    private static double Clamp01(double n) => double.IsFinite(n) ? Math.Min(1, Math.Max(0, n)) : 0;

    private static double ClampValence(double n) => double.IsFinite(n) ? Math.Min(1, Math.Max(-1, n)) : 0;

    private static double[] ToArray(ExpressionVector e) => [e.Valence, e.Arousal, e.Dominance, e.Intimacy, e.Certainty, e.Curiosity, e.Playfulness, e.Reflection, e.Urgency];

    private static ExpressionVector FromArray(double[] a) => new(a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], a[8]);

    /// <summary>Valence into [−1, 1], every other component into [0, 1]; non-finite becomes 0.</summary>
    public static ExpressionVector Clamp(ExpressionVector e) => new(
        ClampValence(e.Valence), Clamp01(e.Arousal), Clamp01(e.Dominance), Clamp01(e.Intimacy), Clamp01(e.Certainty),
        Clamp01(e.Curiosity), Clamp01(e.Playfulness), Clamp01(e.Reflection), Clamp01(e.Urgency));

    /// <summary>Additive per-act nudges, applied before clamping.</summary>
    private static PartialExpression ActDelta(DialogueAct act) => act switch
    {
        DialogueAct.Inform => new(Certainty: 0.1, Reflection: 0.05),
        DialogueAct.Question => new(Curiosity: 0.3, Arousal: 0.1),
        DialogueAct.Answer => new(Certainty: 0.15, Curiosity: 0.05),
        DialogueAct.Comfort => new(Intimacy: 0.3, Arousal: -0.15, Valence: 0.1, Urgency: -0.1),
        DialogueAct.Celebrate => new(Valence: 0.4, Arousal: 0.25, Playfulness: 0.2),
        DialogueAct.Apologise => new(Valence: -0.2, Dominance: -0.2, Intimacy: 0.1, Reflection: 0.15),
        DialogueAct.Refuse => new(Certainty: 0.25, Dominance: 0.2, Playfulness: -0.2),
        DialogueAct.Backchannel => new(Arousal: -0.1, Urgency: -0.15, Intimacy: 0.05),
        DialogueAct.Greet => new(Valence: 0.2, Arousal: 0.1, Intimacy: 0.1),
        DialogueAct.Farewell => new(Valence: 0.1, Arousal: -0.1, Reflection: 0.1),
        DialogueAct.ThinkAloud => new(Reflection: 0.3, Curiosity: 0.15, Certainty: -0.15, Urgency: -0.1),
        _ => new(),
    };

    private const int Intimacy = 3, Curiosity = 5, Playfulness = 6, Reflection = 7;

    /// <summary>
    /// §52.2 character baseline over neutral → blend with the expressive state → dialogue-act deltas → relationship
    /// (intimacy pulls intimacy, formality suppresses playfulness) → developmental (interests / milestones raise
    /// curiosity / reflection) → clamp.
    /// </summary>
    public static ExpressionVector MapPersonaToExpression(PersonaInput input)
    {
        var baseline = ToArray(Neutral);
        if (input.Character?.ToArray() is { } ch)
        {
            for (var k = 0; k < 9; k++)
                baseline[k] = ch[k] ?? baseline[k];
        }
        var blended = (double[])baseline.Clone();
        if (input.ExpressiveState?.ToArray() is { } st)
        {
            const double w = ExpressiveStateWeight;
            for (var k = 0; k < 9; k++)
            {
                if (st[k] is { } transient)
                    blended[k] = (baseline[k] * (1 - w)) + (transient * w);
            }
        }
        var deltas = ActDelta(input.DialogueAct).ToArray();
        for (var k = 0; k < 9; k++)
        {
            if (deltas[k] is { } d)
                blended[k] += d;
        }
        if (input.Relationship is { } rel)
        {
            if (rel.Intimacy is { } intimacy)
                blended[Intimacy] = (blended[Intimacy] * 0.5) + (Clamp01(intimacy) * 0.5);
            if (rel.Formality is { } formality)
                blended[Playfulness] -= Clamp01(formality) * 0.3;
        }
        if (input.Developmental is { } dev)
        {
            if (dev.Interests is { Count: > 0 } interests)
                blended[Curiosity] += Math.Min(0.15, interests.Count * 0.02);
            if (dev.Milestones is { Count: > 0 } milestones)
                blended[Reflection] += Math.Min(0.1, milestones.Count * 0.02);
        }
        return Clamp(FromArray(blended));
    }

    /// <summary>Expression vector + dialogue act → output channels. Fixed thresholds: deterministic and testable.</summary>
    public static PerformanceChannels DeriveChannels(ExpressionVector e, DialogueAct act)
    {
        var v = Clamp(e);
        var prosody = new VoiceProsody(
            Clamp01(0.5 + (v.Urgency * 0.35) + ((v.Arousal - 0.5) * 0.3)),
            Clamp01(0.5 + ((v.Arousal - 0.5) * 0.4) + (v.Valence * 0.15)),
            Clamp01(0.3 + (v.Arousal * 0.5) + ((v.Dominance - 0.5) * 0.2)));
        var textStyle = v.Reflection > 0.65 ? "reflective" : v.Playfulness > 0.6 ? "playful" : v.Certainty > 0.75 ? "declarative" : v.Intimacy > 0.65 ? "warm" : "neutral";
        var face = v.Valence > 0.3 ? (v.Arousal > 0.6 ? "bright_smile" : "soft_smile")
            : v.Valence < -0.3 ? (v.Arousal > 0.6 ? "concerned" : "subdued")
            : v.Curiosity > 0.65 ? "attentive_curious" : "neutral_attentive";
        var gaze = v.Intimacy > 0.6 ? "sustained_soft" : v.Reflection > 0.65 ? "briefly_averted_thinking" : v.Dominance > 0.7 ? "steady_direct" : "natural_conversational";
        var gesture = v.Arousal > 0.7 && v.Playfulness > 0.5 ? "animated_open" : v.Reflection > 0.65 ? "minimal_contained" : v.Intimacy > 0.6 ? "gentle_open_palm" : "rest_neutral";
        var posture = v.Dominance > 0.7 ? "upright_forward" : v.Arousal < 0.3 ? "relaxed_settled" : v.Curiosity > 0.65 ? "leaning_in" : "neutral_engaged";
        var turnTaking = act == DialogueAct.Backchannel ? "backchannel" : act == DialogueAct.Question ? "yield" : "hold";
        var camera = v.Intimacy > 0.7 ? "close_up_slow_push" : v.Arousal > 0.7 ? "medium_dynamic" : v.Reflection > 0.65 ? "static_contemplative" : "medium_static";
        return new PerformanceChannels(textStyle, prosody, face, gaze, gesture, posture, turnTaking, camera);
    }

    /// <summary>§52.4 a complete, time-marked incremental PerformanceIntent (contract #28), valid by construction.</summary>
    public static PerformanceIntent BuildPerformanceIntent(PersonaInput input, PerformanceIds ids, double timeMarked, double duration)
    {
        var expression = MapPersonaToExpression(input);
        var c = DeriveChannels(expression, input.DialogueAct);
        return new PerformanceIntent(ids.Id, ids.AgentId, ids.UserScope, ids.PersonaSnapshotRef, timeMarked, expression, duration,
            c.TextStyle, c.VoiceProsody, c.Face, c.Gaze, c.Gesture, c.Posture, c.TurnTaking, c.CameraBehavior, input.SceneContext);
    }

    /// <summary>
    /// Wrap an intent as aijade.persona.render_requested. Taking the intent (not a bare string) makes a dangling reference
    /// unrepresentable: an intent always carries its persona snapshot ref (§52.5 identity continuity).
    /// </summary>
    public static JsonObject BuildPersonaRenderRequestedEvent(PerformanceIntent intent, string sessionId, JsonObject envelope) =>
        AijadeEvents.Build(AijadeEvents.PersonaRenderRequested, envelope, new JsonObject
        {
            ["session_id"] = sessionId,
            ["persona_snapshot_ref"] = intent.PersonaSnapshotRef,
            ["intent_ref"] = intent.Id,
        });

    /// <summary>
    /// Wrap a render receipt as aijade.lpm.render_ready. An empty applied-params text means nothing was written, i.e. no
    /// render happened: better no event than one that lies, so it throws. An empty asset hash is omitted, not passed on.
    /// </summary>
    public static JsonObject BuildLpmRenderReadyEvent(LpmRenderReceipt input, JsonObject envelope)
    {
        if (input.AppliedParamsHash.Length == 0)
        {
            throw new ArgumentException(
                "lpm.render_ready 拒绝发出：appliedParamsHash 为空串 ⇒ 本轮没有任何通道被写入，"
                + "即没有渲染发生。契约中 applied_params_hash 为 .min(1)，\"什么都没写\"不可表达；"
                + "此时应当不发事件，而不是发一条空回执（见 Kernel/Events.cs 中该 schema 的说明）。", nameof(input));
        }
        var payload = new JsonObject
        {
            ["session_id"] = input.SessionId,
            ["render_ref"] = input.RenderRef,
            ["applied_params_hash"] = input.AppliedParamsHash,
        };
        if (!string.IsNullOrEmpty(input.AssetVersionHash))
            payload["asset_version_hash"] = input.AssetVersionHash;
        return AijadeEvents.Build(AijadeEvents.LpmRenderReady, envelope, payload);
    }

    /// <summary>§52.4 full-duplex scheduling.</summary>
    public static DuplexDecision ScheduleDuplex(DuplexEvent e) => e switch
    {
        DuplexEvent.ListenSignal => new("backchannel", "micro_expression_nod_short_ack", false, false),
        DuplexEvent.PartialSemantics => new("hold", "anticipatory_gaze_posture_preparation", false, false),
        DuplexEvent.CommittedClause => new("hold", "prosody_gesture_phrase_lip_timeline", false, false),
        DuplexEvent.UserInterruption => new("yield", "listen_pose", true, true),
        _ => throw new ArgumentOutOfRangeException(nameof(e)),
    };

    private static string N(double x) => JsFormat.Number(x);

    /// <summary>
    /// §52.5 identity-consistency check; never throws. Identity-level failures (face drift, forbidden actions, boundary
    /// violations, scene break) degrade to pure voice; expression-level failures only degrade to a controllable avatar.
    /// </summary>
    public static ConsistencyVerdict IdentityConsistencyCheck(ConsistencyObservation obs, ConsistencyThresholds? thresholds = null)
    {
        var t = thresholds ?? ConsistencyThresholds.Default;
        var failures = new List<ConsistencyFailure>();
        if (obs.FaceIdentityDrift is { } face && face > t.FaceIdentityDrift)
            failures.Add(new(ConsistencyFailureKind.FaceIdentityDrift, $"face identity drift {N(face)} > {N(t.FaceIdentityDrift)}"));
        if (obs.ClothingDrift is { } clothing && clothing > t.ClothingDrift)
            failures.Add(new(ConsistencyFailureKind.ClothingDrift, $"clothing drift {N(clothing)} > {N(t.ClothingDrift)}"));
        if (obs.VoiceprintDrift is { } voice && voice > t.VoiceprintDrift)
            failures.Add(new(ConsistencyFailureKind.VoiceprintDrift, $"voiceprint drift {N(voice)} > {N(t.VoiceprintDrift)}"));
        if (obs.ProsodyDrift is { } prosody && prosody > t.ProsodyDrift)
            failures.Add(new(ConsistencyFailureKind.ProsodyDrift, $"prosody drift {N(prosody)} > {N(t.ProsodyDrift)}"));
        if (obs.ForbiddenActions is { Count: > 0 } forbidden)
            failures.Add(new(ConsistencyFailureKind.ForbiddenAction, $"role-forbidden actions observed: {string.Join(", ", forbidden)}"));
        if (obs.EmotionSemanticConflict is { } conflict && conflict > t.EmotionSemanticConflict)
            failures.Add(new(ConsistencyFailureKind.EmotionSemanticConflict, $"emotion-semantic conflict {N(conflict)} > {N(t.EmotionSemanticConflict)}"));
        if (obs.LipSyncDeviationMs is { } lip && lip > t.LipSyncDeviationMs)
            failures.Add(new(ConsistencyFailureKind.LipSyncDeviation, $"lip-sync deviation {N(lip)}ms > {N(t.LipSyncDeviationMs)}ms"));
        if (obs.SceneContinuityBreak == true)
            failures.Add(new(ConsistencyFailureKind.SceneContinuity, "scene continuity break detected"));
        if (obs.BoundaryViolations is { Count: > 0 } boundary)
            failures.Add(new(ConsistencyFailureKind.BoundaryViolation, $"cultural/relationship boundary violations: {string.Join(", ", boundary)}"));
        if (failures.Count == 0)
            return new ConsistencyVerdict(true, DegradeMode.None, []);
        var identityLevel = failures.Any(f => f.Kind is ConsistencyFailureKind.FaceIdentityDrift or ConsistencyFailureKind.ForbiddenAction
            or ConsistencyFailureKind.BoundaryViolation or ConsistencyFailureKind.SceneContinuity);
        return new ConsistencyVerdict(false, identityLevel ? DegradeMode.Voice : DegradeMode.Avatar, failures);
    }
}
