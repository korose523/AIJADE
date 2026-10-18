using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Memory.Beliefs;
using Aijade.Memory.Kernel;
using Aijade.Memory.Model;
using Aijade.Memory.Pgc;

namespace Aijade.Memory.V9;

// The single executable path of the causal core: perception evidence → PGC state transition → write plan → MemoryTx →
// EvidenceWeave. Storage is a port, so the kernel stays independent of any database or deployment. Observation context
// (device, privacy, risk) and the v10 tick / input hash come from the input and are propagated, never invented.

public sealed record V9PerceptionInput(
    string EventId, string SessionId, string TraceId, string CorrelationId, double Timestamp, string OriginDevice, int PrivacyLevel, double RiskScore,
    string Source, string Content, IReadOnlyDictionary<StimulusFeature, double>? StimulusFeatures = null, string? RiskLevel = null, string? CapabilityToken = null);

public sealed record V9LearningInput(
    string EventId, string SessionId, string TraceId, string CorrelationId, double Timestamp, string OriginDevice, int PrivacyLevel, double RiskScore,
    int Tick, string InputHash, JsonObject Event, string? CapabilityToken = null);

public sealed record V9VideoObservationInput(
    string EventId, string SessionId, string TraceId, string CorrelationId, double Timestamp, string OriginDevice, int PrivacyLevel, double RiskScore,
    int Tick, string InputHash, string ProposalId, JsonObject Event, string? RenderRef = null, string? AppliedParamsHash = null, string? AssetVersionHash = null,
    string? CapabilityToken = null);

/// <summary>Every row of one run, exposed together so an adapter can commit them atomically.</summary>
public sealed record V9RuntimeArtifact(
    EvidencePackRow EvidencePack, EvidenceChunkRow EvidenceChunk, PgcStateRow PgcState, PgcWritePlanRow PgcWritePlan, MemoryTxRow MemoryTx,
    IReadOnlyList<MemoryVersionRow> MemoryVersions, EvidenceWeaveRow EvidenceWeave, IReadOnlyList<JsonObject> Events);

public sealed record V9RuntimeResult(V9RuntimeArtifact Artifact, TxResult Tx, ShadowParamsProposal? Proposal = null);

/// <summary>The minimal repository that makes the runtime durable.</summary>
public interface IV9RuntimeStore
{
    Task<PgcStateRow?> ReadLatestPgcStateAsync(string sessionId, CancellationToken cancellationToken = default);

    Task PersistAsync(V9RuntimeArtifact artifact, CancellationToken cancellationToken = default);
}

/// <summary>
/// The stateful PGC runtime; one instance serves many sessions, reading the previous state from the port before each
/// event. With a capability gate, every entry point authorizes the token before anything is committed.
/// </summary>
public sealed class V9CausalRuntime(IV9RuntimeStore store, MemoryWriteGate? gate = null, string writeCapability = "memory:write", string writeScope = "global", TimeProvider? time = null)
{
    private const string Policy = "pgc_policy_v1";

    private static string Id(string prefix, string eventId) => $"{prefix}_{eventId}";

    private static double ClampRisk(double v) => double.IsFinite(v) ? Math.Max(0, Math.Min(1, v)) : 1;

    private static string RiskBand(double r) => r >= 0.7 ? "high" : r >= 0.35 ? "medium" : "low";

    private static JsonArray Strings(params string[] s) => new(s.Select(x => (JsonNode?)x).ToArray());

    private async Task AuthorizeAsync(string? token, CancellationToken ct)
    {
        if (gate is not null)
            await gate.AuthorizeAsync(token ?? "", writeCapability, writeScope, cancellationToken: ct).ConfigureAwait(false);
    }

    /// <summary>Perception stimulus from the content length and risk; caller-supplied features override (they are persisted as evidence).</summary>
    private static Dictionary<StimulusFeature, double> PerceptionStimulus(V9PerceptionInput input)
    {
        var length = Math.Min(1, input.Content.Length / 800.0);
        var risk = ClampRisk(input.RiskScore);
        var f = new Dictionary<StimulusFeature, double>
        {
            [StimulusFeature.StimArousalScore] = length,
            [StimulusFeature.UncertaintyLoadScore] = risk,
            [StimulusFeature.StimDriveScore] = Math.Max(0.15, length * 0.5),
            [StimulusFeature.StimFatigueScore] = risk * 0.2,
        };
        foreach (var (k, v) in input.StimulusFeatures ?? new Dictionary<StimulusFeature, double>())
            f[k] = v;
        return f;
    }

    private static PgcWritePlanRow PlanRow(string eventId, string sessionId, string traceId, double timestamp, PgcDecisionResult decision, string stateId) => new(
        Id("pwp", eventId), stateId, sessionId, traceId, Policy,
        decision.WritePlan.Select(e => new PgcWritePlanEntryRow(e.MemoryWriteId, e.Decision, e.FinalIntensity, e.ReasonCodes, e.ExpectedTests,
            e.PgcStateSnapshot.PgcStateId, e.PgcStateSnapshot)).ToList(),
        decision.ContradictionReport, timestamp);

    private static JsonObject Envelope(string eventId, string traceId, string correlationId, double timestamp, string originDevice, int privacy, double risk,
        JsonArray evidenceRefs, string riskLevel, int? tick = null, string? inputHash = null)
    {
        var e = new JsonObject
        {
            ["event_id"] = Id("evt", eventId),
            ["trace_id"] = traceId,
            ["correlation_id"] = correlationId,
            ["timestamp"] = timestamp,
            ["producer"] = "v9-causal-runtime",
            ["origin_device"] = originDevice,
            ["privacy_level"] = privacy,
            ["evidence_refs"] = evidenceRefs,
            ["causal_context_refs"] = Strings(traceId),
            ["risk_score"] = ClampRisk(risk),
            ["idempotency_key"] = Id("runtime", eventId),
            ["replay_mode"] = "live",
            ["risk_level"] = riskLevel,
        };
        if (tick is { } t)
            e["tick"] = t;
        if (inputHash is not null)
            e["causality"] = new JsonObject { ["inputHash"] = inputHash };
        return e;
    }

    private static JsonObject WithKey(JsonObject envelope, string suffix)
    {
        var e = (JsonObject)envelope.DeepClone();
        e["idempotency_key"] = $"{envelope["idempotency_key"]!.GetValue<string>()}:{suffix}";
        return e;
    }

    /// <summary>Tag every event with its core state node (v10 §4.2), from the topic and whether a version was really stored.</summary>
    private static List<JsonObject> Tag(List<JsonObject> events, bool hasMemoryVersion)
    {
        foreach (var e in events)
            e["core_state_node"] = CoreStateNodes.Derive(e["topic"]!.GetValue<string>(), hasMemoryVersion).ToString();
        return events;
    }

    public async Task<V9RuntimeResult> ProcessPerceptionAsync(V9PerceptionInput input, CancellationToken cancellationToken = default)
    {
        if (JsText.Trim(input.Content).Length == 0)
            throw new ArgumentException("v9 perception requires non-empty content", nameof(input));
        var previous = await store.ReadLatestPgcStateAsync(input.SessionId, cancellationToken).ConfigureAwait(false);
        var stimulus = PerceptionStimulus(input);
        var state = new PgcStateIntegrator(previous?.V6State).Step(PgcStateMath.EvaluateStimulus(stimulus));

        var packId = Id("ep", input.EventId);
        var chunkId = Id("ec", input.EventId);
        var writeId = Id("mw", input.EventId);
        var pack = new EvidencePackRow(packId, input.SessionId, input.Source, input.Timestamp,
            $"origin_device={input.OriginDevice};privacy={input.PrivacyLevel};risk={JsFormat.Number(ClampRisk(input.RiskScore))}");
        var chunk = new EvidenceChunkRow(chunkId, packId, 0, input.Content, input.Timestamp);
        var salience = new ContentSalience(0.5, 0.2, 0.5);
        var decision = PgcGate.Decide(new PgcInput(input.SessionId, input.TraceId,
            [new PgcCandidateWrite(writeId, MemoryKind.Episodic, new JsonObject { ["content"] = input.Content, ["source"] = input.Source }, [chunkId], 1, null, salience)],
            new PgcReadContext(input.Timestamp, [new PgcEventLite("perception_event")], EvidenceRecords: [new EvidenceEntry(chunkId, 1, 1)], V6State: state, V6StimulusFeatures: stimulus),
            Policy));

        var riskLevel = input.RiskLevel ?? RiskBand(input.RiskScore);
        var payload = new MemoryPayload(writeId,
            new NormalizedPayload(MemoryKind.Episodic, new JsonObject { ["content"] = input.Content, ["source"] = input.Source },
                new MemoryPayloadAttributes(["perception", input.Source], [], riskLevel, salience), input.Content),
            packId, [chunkId], new Provenance(input.Source, input.OriginDevice));
        var envelope = Envelope(input.EventId, input.TraceId, input.CorrelationId, input.Timestamp, input.OriginDevice, input.PrivacyLevel, input.RiskScore,
            Strings(packId, chunkId), riskLevel);
        return await CommitAsync(input.EventId, input.SessionId, input.TraceId, input.Timestamp, input.CapabilityToken, state, decision, pack, chunk, payload,
            new MemoryTxEnvelopeContext(input.OriginDevice, input.PrivacyLevel, ClampRisk(input.RiskScore), EvidenceRefs: [packId, chunkId]),
            envelope, null, null, cancellationToken).ConfigureAwait(false);
    }

    /// <summary>
    /// A v10 learning event through the same gate chain. The event is reduced first (the input_hash gate); the produced
    /// learning event and every derived event carry the input's tick and input hash, so one replay unit covers them all.
    /// </summary>
    public async Task<V9RuntimeResult> ProcessLearningAsync(V9LearningInput input, CancellationToken cancellationToken = default)
    {
        var proposal = ShadowParams.FromEvent(input.Event);
        var previous = await store.ReadLatestPgcStateAsync(input.SessionId, cancellationToken).ConfigureAwait(false);
        var stimulus = ShadowParams.LearningStimulus(proposal);
        var state = new PgcStateIntegrator(previous?.V6State).Step(PgcStateMath.EvaluateStimulus(stimulus));

        var packId = Id("ep", input.EventId);
        var chunkId = Id("ec", input.EventId);
        var writeId = Id("mw", input.EventId);
        var pack = new EvidencePackRow(packId, input.SessionId, "learning:shadow_params", input.Timestamp,
            $"origin_device={input.OriginDevice};privacy={input.PrivacyLevel};risk={JsFormat.Number(ClampRisk(input.RiskScore))}");
        var chunk = new EvidenceChunkRow(chunkId, packId, 0,
            JsFormat.Stringify(new JsonObject { ["proposalId"] = proposal.ProposalId, ["inputHash"] = proposal.InputHash, ["confidence"] = proposal.Confidence }), input.Timestamp);
        var candidate = ShadowParams.AsPgcCandidate(proposal);
        var decision = PgcGate.Decide(new PgcInput(input.SessionId, input.TraceId, [candidate],
            new PgcReadContext(input.Timestamp, [new PgcEventLite(input.Event["topic"]!.GetValue<string>())], EvidenceRecords: [], V6State: state, V6StimulusFeatures: stimulus),
            Policy));

        var riskLevel = RiskBand(input.RiskScore);
        var payload = new MemoryPayload(writeId,
            new NormalizedPayload(candidate.MemoryKind, proposal.ToJson(), new MemoryPayloadAttributes(["learning", "shadow_params"], [], riskLevel, candidate.Salience),
                JsFormat.Stringify(new JsonObject { ["proposalId"] = proposal.ProposalId, ["inputHash"] = proposal.InputHash })),
            packId, [chunkId], new Provenance("learning:shadow_params", input.OriginDevice));
        var envelope = Envelope(input.EventId, input.TraceId, input.CorrelationId, input.Timestamp, input.OriginDevice, input.PrivacyLevel, input.RiskScore,
            Strings(packId, chunkId), riskLevel, input.Tick, input.InputHash);

        var shadow = input.Event["topic"]!.GetValue<string>() == AijadeEvents.LearningProposedShadowParams;
        var learningPayload = new JsonObject
        {
            ["session_id"] = proposal.SessionId,
            ["proposal_id"] = proposal.ProposalId,
            ["render_ref"] = proposal.RenderRef ?? $"render_{proposal.ProposalId}",
            ["applied_params_hash"] = proposal.AppliedParamsHash ?? proposal.InputHash,
            ["asset_version_hash"] = proposal.AssetVersionHash ?? proposal.InputHash,
        };
        if (shadow)
        {
            learningPayload["input_hash"] = proposal.InputHash;
            learningPayload["candidate_params"] = proposal.CandidateParams.DeepClone();
        }
        else
        {
            learningPayload["evidence_hash"] = proposal.EvidenceHash ?? proposal.InputHash;
            learningPayload["claim_text"] = proposal.ClaimText ?? $"shadow-params proposal {proposal.ProposalId}";
        }
        learningPayload["confidence"] = proposal.Confidence;
        var learningEvent = AijadeEvents.Build(shadow ? AijadeEvents.LearningProposedShadowParams : AijadeEvents.LearningProposedEvidence, envelope, learningPayload);

        return await CommitAsync(input.EventId, input.SessionId, input.TraceId, input.Timestamp, input.CapabilityToken, state, decision, pack, chunk, payload,
            new MemoryTxEnvelopeContext(input.OriginDevice, input.PrivacyLevel, ClampRisk(input.RiskScore), EvidenceRefs: [packId, chunkId], Tick: input.Tick, CausalityInputHash: input.InputHash),
            envelope, learningEvent, proposal, cancellationToken).ConfigureAwait(false);
    }

    /// <summary>
    /// Route A (video only): a stored webpage-text or subtitle observation → evidence candidate → learning.proposed.evidence
    /// → the same chain as <see cref="ProcessLearningAsync"/>.
    /// </summary>
    public Task<V9RuntimeResult> ProcessVideoObservationAsync(V9VideoObservationInput input, CancellationToken cancellationToken = default)
    {
        var topic = input.Event["topic"]?.GetValue<string>();
        var payload = (JsonObject)input.Event["payload"]!;
        var candidate = topic == AijadeEvents.WebpageTextObservation ? VideoObservation.FromWebpage(payload)
            : topic == AijadeEvents.VideoTranscriptObservation ? VideoObservation.FromSubtitles(payload)
            : throw new ArgumentException($"[v9-runtime] unsupported video observation topic: {topic}", nameof(input));
        var evidenceEvent = AijadeEvents.Build(AijadeEvents.LearningProposedEvidence,
            Envelope(input.EventId, input.TraceId, input.CorrelationId, input.Timestamp, input.OriginDevice, input.PrivacyLevel, input.RiskScore,
                [], RiskBand(input.RiskScore), input.Tick, input.InputHash),
            VideoObservation.ToEventPayload(candidate, input.SessionId, input.ProposalId, input.RenderRef, input.AppliedParamsHash, input.AssetVersionHash));
        return ProcessLearningAsync(new V9LearningInput(input.EventId, input.SessionId, input.TraceId, input.CorrelationId, input.Timestamp, input.OriginDevice,
            input.PrivacyLevel, input.RiskScore, input.Tick, input.InputHash, evidenceEvent, input.CapabilityToken), cancellationToken);
    }

    private async Task<V9RuntimeResult> CommitAsync(
        string eventId, string sessionId, string traceId, double timestamp, string? token, PgcState4 state, PgcDecisionResult decision,
        EvidencePackRow pack, EvidenceChunkRow chunk, MemoryPayload payload, MemoryTxEnvelopeContext txContext, JsonObject baseEnvelope,
        JsonObject? learningEvent, ShadowParamsProposal? proposal, CancellationToken ct)
    {
        var snapshot = decision.WritePlan[0].PgcStateSnapshot;
        var pgcState = new PgcStateRow(snapshot.PgcStateId, sessionId, traceId, Policy, snapshot.Components, state, timestamp);
        var planRow = PlanRow(eventId, sessionId, traceId, timestamp, decision, snapshot.PgcStateId);
        var txInput = new MemoryTxInput(sessionId, traceId, decision.WritePlan, [payload], new TxPolicy(TxAtomicity.PerWrite, 1), Id("tx", eventId), token, txContext);
        await AuthorizeAsync(token, ct).ConfigureAwait(false);
        var engine = new MemoryTxEngine(gate: gate, time: time);
        var tx = engine.Commit(txInput);
        var weave = EvidenceWeave.Build(engine, tx.TxId, new WeaveSpec(true, true));
        var versions = engine.GetVersionsForTx(tx.TxId);
        var events = new List<JsonObject>();
        if (learningEvent is not null)
            events.Add(learningEvent);
        events.Add(PgcGate.BuildWritePlanReadyEvent(decision, WithKey(baseEnvelope, "pgc")));
        events.AddRange(tx.Events.Select(e => (JsonObject)e.DeepClone()));
        events.Add(EvidenceWeave.BuildCandidateReadyEvent(weave, WithKey(baseEnvelope, "weave")));
        var artifact = new V9RuntimeArtifact(pack, chunk, pgcState, planRow, engine.ToMemoryTxRow(txInput, tx), versions, EvidenceWeave.ToRow(weave, timestamp),
            Tag(events, versions.Count > 0));
        await store.PersistAsync(artifact, ct).ConfigureAwait(false);
        return new V9RuntimeResult(artifact, tx, proposal);
    }
}

/// <summary>An in-memory runtime store (tests, single-process use): the latest PGC state per session and every artifact.</summary>
public sealed class InMemoryV9RuntimeStore : IV9RuntimeStore
{
    private readonly Dictionary<string, PgcStateRow> _latest = new(StringComparer.Ordinal);

    public List<V9RuntimeArtifact> Artifacts { get; } = [];

    public Task<PgcStateRow?> ReadLatestPgcStateAsync(string sessionId, CancellationToken cancellationToken = default) =>
        Task.FromResult(_latest.GetValueOrDefault(sessionId));

    public Task PersistAsync(V9RuntimeArtifact artifact, CancellationToken cancellationToken = default)
    {
        Artifacts.Add(artifact);
        _latest[artifact.PgcState.SessionId] = artifact.PgcState;
        return Task.CompletedTask;
    }
}
