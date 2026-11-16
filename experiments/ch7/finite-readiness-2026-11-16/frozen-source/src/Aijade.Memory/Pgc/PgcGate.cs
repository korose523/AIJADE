using System.Text.Json.Nodes;

using Aijade.Memory.Beliefs;
using Aijade.Memory.Dynamics;
using Aijade.Memory.Kernel;
using Aijade.Memory.Model;

namespace Aijade.Memory.Pgc;

// PGC gate (Physiological-Gated Consolidation), the first gate of the v9 write pipeline:
//     candidate_memory_writes → PGC → write_plan[commit | throttle | defer | reject] → MemoryTx → EvidenceWeave
// PGC is an evidence-based policy decision (decision + reason codes + contradiction report). It reuses the bounded
// plasticity gate only as a component of its state snapshot; the hormone gate itself stays neutral, since the A1
// experiment showed physiology contributes ≈ 0 to recall. Policies are versioned, so an ablation changes the policy, not
// the code. With a v6 four-dimensional state s_t in the read context, the v6 commitment-weight gate is used instead.

public enum MemoryKind
{
    LongTerm,
    Persona,
    Skill,
    Episodic,
    KnowledgeCard,
}

public enum PgcDecision
{
    Commit,
    Throttle,
    Defer,
    Reject,
}

public enum PgcReasonCode
{
    LowEvidence,
    SufficientEvidence,
    ContradictionDetected,
    PersonaShiftRisk,
    EvidenceUncertaintyHigh,
    ThrottledHighIntensity,
    DeferredPendingReview,
}

public enum ContradictionLevel
{
    Low,
    Medium,
    High,
}

/// <summary>Why a write could or could not commit, in diagnostic priority order.</summary>
public enum CommitReason
{
    /// <summary>The parameters make a commit impossible (constructive zero).</summary>
    WMaxBelowTheta,
    ContradictionHigh,
    EvidenceInsufficient,
    /// <summary>Deferred to offline consolidation — not a rejection.</summary>
    FatigueDeferred,
    /// <summary>This state was not good enough.</summary>
    WBelowTheta,
    Committed,
}

public enum TauDisplayLabel
{
    Episode,
    Emotion,
    Skill,
    Knowledge,
}

public sealed record PgcCandidateWrite(
    string MemoryWriteId, MemoryKind MemoryKind, JsonNode? CandidatePayload, IReadOnlyList<string> EvidenceIds, double ProposedIntensity,
    IReadOnlyList<string>? ClaimIds = null, ContentSalience? Salience = null);

public sealed record PgcEventLite(string Topic, JsonNode? Payload = null);

/// <summary>
/// What PGC reads. Evidence records and beliefs reuse the belief-graph types (no parallel entity model). The v6 state is
/// an overlay: without it the evidence-threshold policy applies unchanged.
/// </summary>
public sealed record PgcReadContext(
    double Now, IReadOnlyList<PgcEventLite> LastNEvents, IReadOnlyDictionary<string, double>? PhysiologySignals = null,
    IReadOnlyList<EvidenceEntry>? EvidenceRecords = null, IReadOnlyList<Belief>? Beliefs = null, PgcState4? V6State = null,
    IReadOnlyDictionary<StimulusFeature, double>? V6StimulusFeatures = null);

public sealed record PgcPolicy(
    string Version, int MinEvidenceCount, PgcDecision LowEvidenceAction, double SufficientEvidenceCount, double ContradictionSeverityHighThreshold,
    double PersonaShiftIntensityThreshold, double EvidenceUncertaintyThreshold, double IntensityMin, double IntensityMax, bool RequireEvidenceRecordsForSufficiency);

public sealed record PgcV6Params(IReadOnlyDictionary<Tau, double> Rho0ByTau, double Kappa, IReadOnlyDictionary<Tau, PgcState4> AlphaByTau);

public sealed record PgcV6DecisionPolicy(
    bool HighSeverityReject, PgcDecision LowAction, PgcDecision MediumAction, PgcDecision HighAction, double CommitMinW, double ThrottleMinW,
    double FatigueDeferIfGt, double FatigueDeferWThreshold, double SeverityMediumFrom, double SeverityHighFrom);

/// <summary>The v6 intermediate values written to the snapshot and audit (the replay minimums include computed w).</summary>
public sealed record PgcV6State(
    Tau Tau, PgcState4 S, double Rho0, double Kappa, double Dot, double WPrime, double W, double WMaxGlobal, double? WMaxAtF,
    bool CommitPossible, CommitReason CommitReason, bool FatigueDeferred, ContradictionLevel ContradictionLevel);

public sealed record PgcStateComponents(
    PlasticityGate Plasticity, double EvidenceStrength, double ContradictionSeverity, double EvidenceUncertainty, double PersonaShiftRisk);

public sealed record PgcStateSnapshot(string PgcStateId, PgcStateComponents Components, string? PgcPolicyVersion = null, PgcV6State? V6 = null);

public sealed record PgcWritePlanEntry(
    string MemoryWriteId, PgcDecision Decision, double FinalIntensity, IReadOnlyList<PgcReasonCode> ReasonCodes, IReadOnlyList<string> ExpectedTests,
    PgcStateSnapshot PgcStateSnapshot);

public sealed record ContradictionReport(string Severity, IReadOnlyList<string>? ConflictingEvidenceIds = null);

public sealed record PgcDecisionResult(string PgcStateId, IReadOnlyList<PgcWritePlanEntry> WritePlan, ContradictionReport ContradictionReport);

public sealed record PgcInput(string SessionId, string TraceId, IReadOnlyList<PgcCandidateWrite> CandidateMemoryWrites, PgcReadContext PgcReadContext, string PgcPolicyVersion);

public static class PgcGate
{
    /// <summary>Default policy v1; every threshold can be overridden by an ablation.</summary>
    public static PgcPolicy DefaultPolicyV1 { get; } = new("pgc_policy_v1", 1, PgcDecision.Reject, 3, 0.5, 2.0, 0.6, 0.2, 3.0, false);

    /// <summary>The control policy: every threshold at its loosest, i.e. no gating.</summary>
    public static PgcPolicy NeutralPolicy { get; } = new("pgc_policy_neutral", 0, PgcDecision.Throttle, 1, 1.0, double.PositiveInfinity, 1.0, 0.2, 3.0, false);

    public static IReadOnlyDictionary<string, PgcPolicy> PolicyRegistry { get; } = new Dictionary<string, PgcPolicy>
    {
        [DefaultPolicyV1.Version] = DefaultPolicyV1,
        [NeutralPolicy.Version] = NeutralPolicy,
    };

    public static PgcPolicy ResolvePolicy(string version) =>
        PolicyRegistry.TryGetValue(version, out var p) ? p : throw new ArgumentException($"[pgc] unknown pgc_policy_version: {version}", nameof(version));

    /// <summary>memory_kind (5) → τ (4); skill, missing from the author's table, maps to procedural.</summary>
    public static Tau TauOf(MemoryKind kind) => kind switch
    {
        MemoryKind.Episodic => Tau.Episodic,
        MemoryKind.Persona => Tau.Affective,
        MemoryKind.Skill => Tau.Procedural,
        _ => Tau.Semantic,
    };

    /// <summary>The paper's label for a τ: a renaming, derived from <see cref="TauOf"/>, never a second classification.</summary>
    public static TauDisplayLabel DisplayLabel(MemoryKind kind) => TauOf(kind) switch
    {
        Tau.Episodic => TauDisplayLabel.Episode,
        Tau.Affective => TauDisplayLabel.Emotion,
        Tau.Procedural => TauDisplayLabel.Skill,
        _ => TauDisplayLabel.Knowledge,
    };

    /// <summary>The production baseline, parameter case 4 (case 1 makes a commit constructively impossible).</summary>
    public static PgcV6Params ParamsCase4 { get; } = new(
        new Dictionary<Tau, double> { [Tau.Episodic] = 0.70, [Tau.Affective] = 0.75, [Tau.Procedural] = 0.65, [Tau.Semantic] = 0.60 },
        1.25,
        new Dictionary<Tau, PgcState4>
        {
            [Tau.Episodic] = new(0.90, 0.10, 0.00, -0.20),
            [Tau.Affective] = new(0.20, 0.80, 0.05, -0.15),
            [Tau.Procedural] = new(0.10, -0.10, 0.85, -0.25),
            [Tau.Semantic] = new(0.60, 0.05, 0.10, -0.10),
        });

    public const int V6TauCaseId = 4;

    public static PgcV6DecisionPolicy DefaultV6Policy { get; } = new(true, PgcDecision.Throttle, PgcDecision.Throttle, PgcDecision.Reject, 0.55, 0.30, 0.70, 0.45, 0.33, 0.66);

    private static double Clamp(double x, double min, double max) => Math.Min(max, Math.Max(min, x));

    /// <summary>
    /// Contradiction with the belief graph: a candidate claim among an accepted / contested belief's evidence, or a candidate
    /// evidence id among its counter-evidence. Severity = the belief's counter-logit share of its total logit mass. Candidate
    /// evidence records with negative likelihood also count (severity 0.5).
    /// </summary>
    public static (double Severity, IReadOnlyList<string> ConflictingEvidenceIds) DetectContradiction(
        PgcCandidateWrite cand, IReadOnlyList<Belief>? beliefs = null, IReadOnlyList<EvidenceEntry>? evidenceRecords = null)
    {
        var claimSet = (cand.ClaimIds ?? []).ToHashSet(StringComparer.Ordinal);
        var evidenceSet = cand.EvidenceIds.ToHashSet(StringComparer.Ordinal);
        var conflicting = new List<string>();
        var worst = 0.0;
        foreach (var b in beliefs ?? [])
        {
            if (b.Status is not (BeliefStatus.Accepted or BeliefStatus.Contested))
                continue;
            if (!b.EvidenceIds.Any(claimSet.Contains) && !b.CounterEvidenceIds.Any(evidenceSet.Contains))
                continue;
            var total = Math.Abs(b.SupportLogit) + Math.Abs(b.CounterLogit);
            worst = Math.Max(worst, total > 0 ? Math.Abs(b.CounterLogit) / total : 0.5);
            foreach (var id in b.EvidenceIds)
            {
                if (claimSet.Contains(id) && !conflicting.Contains(id))
                    conflicting.Add(id);
            }
            foreach (var id in b.CounterEvidenceIds)
            {
                if (evidenceSet.Contains(id) && !conflicting.Contains(id))
                    conflicting.Add(id);
            }
        }
        foreach (var e in evidenceRecords ?? [])
        {
            if (cand.EvidenceIds.Contains(e.Id) && e.Likelihood < 0 && !conflicting.Contains(e.Id))
            {
                conflicting.Add(e.Id);
                worst = Math.Max(worst, 0.5);
            }
        }
        return (worst, conflicting);
    }

    private static double EvidenceStrength(PgcCandidateWrite cand, PgcPolicy policy, List<EvidenceEntry> records)
    {
        if (policy.RequireEvidenceRecordsForSufficiency)
        {
            if (records.Count == 0)
                return 0;
            var sum = 0.0;
            foreach (var r in records)
                sum += Clamp(r.Reliability, 0, 1);
            return Clamp(sum / policy.SufficientEvidenceCount, 0, 1);
        }
        return Clamp(cand.EvidenceIds.Count / policy.SufficientEvidenceCount, 0, 1);
    }

    private static double EvidenceUncertainty(List<EvidenceEntry> records)
    {
        if (records.Count == 0)
            return 1;
        var sum = 0.0;
        foreach (var r in records)
            sum += Clamp(r.Reliability, 0, 1);
        return Clamp(1 - (sum / records.Count), 0, 1);
    }

    private static double PersonaShiftRisk(PgcCandidateWrite cand, PgcPolicy policy, double contradictionSeverity)
    {
        if (cand.MemoryKind != MemoryKind.Persona)
            return 0;
        var risk = 0.0;
        var t = policy.PersonaShiftIntensityThreshold;
        if (cand.ProposedIntensity > t)
            risk = Math.Max(risk, Clamp((cand.ProposedIntensity - t) / t, 0, 1));
        if (contradictionSeverity > 0)
            risk = Math.Max(risk, contradictionSeverity);
        return risk;
    }

    public static string WireName(PgcReasonCode c) => c switch
    {
        PgcReasonCode.LowEvidence => "low_evidence",
        PgcReasonCode.SufficientEvidence => "sufficient_evidence",
        PgcReasonCode.ContradictionDetected => "contradiction_detected",
        PgcReasonCode.PersonaShiftRisk => "persona_shift_risk",
        PgcReasonCode.EvidenceUncertaintyHigh => "evidence_uncertainty_high",
        PgcReasonCode.ThrottledHighIntensity => "throttled_high_intensity",
        _ => "deferred_pending_review",
    };

    private static List<string> ExpectedTests(PgcDecision decision, List<PgcReasonCode> reasons) => decision switch
    {
        PgcDecision.Reject => reasons.Select(c => $"recheck_after_{WireName(c)}").ToList(),
        PgcDecision.Commit => ["recall_probe", "contradiction_recheck"],
        _ => ["defer_until_more_evidence"],
    };

    /// <summary>v6 commitment weight: w = clip(ρ0 · (1 + α·s) · (1 − κ·f), 0, 1).</summary>
    public static (Tau Tau, double Rho0, double Kappa, double Dot, double WPrime, double W) ComputeV6CommitmentWeight(MemoryKind kind, PgcState4 s)
    {
        var tau = TauOf(kind);
        var rho0 = ParamsCase4.Rho0ByTau[tau];
        var alpha = ParamsCase4.AlphaByTau[tau];
        var kappa = ParamsCase4.Kappa;
        var dot = (alpha.A * s.A) + (alpha.C * s.C) + (alpha.D * s.D) + (alpha.F * s.F);
        var wPrime = rho0 * (1 + dot) * (1 - (kappa * s.F));
        return (tau, rho0, kappa, dot, wPrime, Math.Min(1, Math.Max(0, wPrime)));
    }

    public static ContradictionLevel LevelFromSeverity(double severity, PgcV6DecisionPolicy? policy = null)
    {
        var p = policy ?? DefaultV6Policy;
        return severity >= p.SeverityHighFrom ? ContradictionLevel.High : severity >= p.SeverityMediumFrom ? ContradictionLevel.Medium : ContradictionLevel.Low;
    }

    /// <summary>v6 decision order: high contradiction → reject; f &gt; 0.70 ∧ w ≥ 0.45 → defer; w ≥ 0.55 → commit; w ≥ 0.30 → throttle; else reject.</summary>
    public static (PgcDecision Decision, IReadOnlyList<PgcReasonCode> ReasonCodes, bool FatigueDeferred) ApplyV6Decision(
        double w, PgcState4 s, ContradictionLevel level, PgcV6DecisionPolicy? policy = null)
    {
        var p = policy ?? DefaultV6Policy;
        if (p.HighSeverityReject && level == ContradictionLevel.High)
            return (p.HighAction, [PgcReasonCode.ContradictionDetected], false);
        if (s.F > p.FatigueDeferIfGt && w >= p.FatigueDeferWThreshold)
            return (PgcDecision.Defer, [PgcReasonCode.DeferredPendingReview], true);
        if (w >= p.CommitMinW)
            return (PgcDecision.Commit, [PgcReasonCode.SufficientEvidence], false);
        if (w >= p.ThrottleMinW)
            return (PgcDecision.Throttle, [PgcReasonCode.ThrottledHighIntensity], false);
        return (PgcDecision.Reject, [PgcReasonCode.LowEvidence], false);
    }

    /// <summary>
    /// Closed-form upper bounds of w. The a/c/d terms are linear and independent, so the extremes sit at the all-positive
    /// (baseMax) or all-negative (baseMin) corner; with (1 − κf) &lt; 0 the minimum corner wins, so both are taken. Candidate f
    /// values are 0, 1 and each quadratic's vertex in (0, 1). w_max_at_f is null when f is not given (not computed ≠ global).
    /// </summary>
    public static (double WMaxGlobal, double? WMaxAtF) ComputeV6WMaxBounds(Tau tau, PgcV6Params? parameters = null, double? f = null)
    {
        var p = parameters ?? ParamsCase4;
        var rho0 = p.Rho0ByTau[tau];
        var alpha = p.AlphaByTau[tau];
        var kappa = p.Kappa;
        var af = alpha.F;
        var baseMax = 1 + Math.Max(alpha.A, 0) + Math.Max(alpha.C, 0) + Math.Max(alpha.D, 0);
        var baseMin = 1 + Math.Min(alpha.A, 0) + Math.Min(alpha.C, 0) + Math.Min(alpha.D, 0);
        double G(double fv)
        {
            var k = 1 - (kappa * fv);
            return Math.Max((baseMax + (af * fv)) * k, (baseMin + (af * fv)) * k);
        }
        var candidates = new List<double> { 0, 1 };
        if (af != 0)
        {
            var a = -af * kappa;
            foreach (var b in new[] { baseMax, baseMin })
            {
                var vertex = -(af - (b * kappa)) / (2 * a);
                if (vertex is > 0 and < 1)
                    candidates.Add(vertex);
            }
        }
        var gMax = double.NegativeInfinity;
        foreach (var fv in candidates)
            gMax = Math.Max(gMax, G(fv));
        return (Math.Min(1, Math.Max(0, rho0 * gMax)), f is { } fx ? Math.Min(1, Math.Max(0, rho0 * G(fx))) : null);
    }

    /// <summary>Commit diagnosis (not a gate): the first matching reason in priority order.</summary>
    public static (bool CommitPossible, CommitReason CommitReason) DeriveV6CommitVerdict(
        double wMaxGlobal, ContradictionLevel level, bool evidenceSufficient, PgcDecision decision, double w, double? theta = null)
    {
        var th = theta ?? DefaultV6Policy.CommitMinW;
        if (wMaxGlobal < th)
            return (false, CommitReason.WMaxBelowTheta);
        if (level == ContradictionLevel.High)
            return (false, CommitReason.ContradictionHigh);
        if (!evidenceSufficient)
            return (false, CommitReason.EvidenceInsufficient);
        if (decision == PgcDecision.Defer)
            return (false, CommitReason.FatigueDeferred);
        if (w < th)
            return (false, CommitReason.WBelowTheta);
        return (true, CommitReason.Committed);
    }

    /// <summary>The PGC decision for one candidate. Pure: the same input always gives the same output (replayable).</summary>
    public static PgcWritePlanEntry DecideCandidate(PgcCandidateWrite cand, PgcReadContext ctx, PgcPolicy policy)
    {
        var gate = cand.Salience is { } sal ? Plasticity.GateFromContent(sal).Clamped() : PlasticityGate.Neutral;
        var records = (ctx.EvidenceRecords ?? []).Where(r => cand.EvidenceIds.Contains(r.Id)).ToList();
        var strength = EvidenceStrength(cand, policy, records);
        var uncertainty = EvidenceUncertainty(records);
        var (severity, _) = DetectContradiction(cand, ctx.Beliefs, records);
        var personaRisk = PersonaShiftRisk(cand, policy, severity);
        var components = new PgcStateComponents(gate, strength, severity, uncertainty, personaRisk);
        var stateId = $"pgc_{cand.MemoryWriteId}_{policy.Version}";

        if (ctx.V6State is { } s)
        {
            var (tau, rho0, kappa, dot, wPrime, w) = ComputeV6CommitmentWeight(cand.MemoryKind, s);
            var (wMaxGlobal, wMaxAtF) = ComputeV6WMaxBounds(tau, ParamsCase4, s.F);
            var level = LevelFromSeverity(severity);
            var (decision, reasons, deferred) = ApplyV6Decision(w, s, level);
            var sufficient = cand.EvidenceIds.Count > 0 && strength >= 1;
            var (possible, why) = DeriveV6CommitVerdict(wMaxGlobal, level, sufficient, decision, w);
            var v6 = new PgcV6State(tau, s, rho0, kappa, dot, wPrime, w, wMaxGlobal, wMaxAtF, possible, why, deferred, level);
            return new PgcWritePlanEntry(cand.MemoryWriteId, decision, w, reasons, ExpectedTests(decision, [.. reasons]),
                new PgcStateSnapshot(stateId, components, policy.Version, v6));
        }

        var reasonCodes = new List<PgcReasonCode>();
        PgcDecision d;
        if (cand.EvidenceIds.Count == 0 || cand.EvidenceIds.Count < policy.MinEvidenceCount)
        {
            reasonCodes.Add(PgcReasonCode.LowEvidence);
            d = policy.LowEvidenceAction;
        }
        else if (severity > 0)
        {
            reasonCodes.Add(PgcReasonCode.ContradictionDetected);
            d = severity >= policy.ContradictionSeverityHighThreshold ? PgcDecision.Reject : PgcDecision.Throttle;
        }
        else if (personaRisk > 0 && cand.MemoryKind == MemoryKind.Persona)
        {
            // Persona memories are drift-sensitive: any risk is rejected outright rather than delayed.
            reasonCodes.Add(PgcReasonCode.PersonaShiftRisk);
            d = PgcDecision.Reject;
        }
        else if (uncertainty > policy.EvidenceUncertaintyThreshold && records.Count > 0)
        {
            reasonCodes.Add(PgcReasonCode.EvidenceUncertaintyHigh);
            d = PgcDecision.Throttle;
        }
        else if (strength >= 1)
        {
            reasonCodes.Add(PgcReasonCode.SufficientEvidence);
            d = PgcDecision.Commit;
        }
        else
        {
            reasonCodes.Add(PgcReasonCode.DeferredPendingReview);
            d = PgcDecision.Throttle;
        }
        var finalIntensity = Clamp(cand.ProposedIntensity * gate.ConsolidationGain, policy.IntensityMin, policy.IntensityMax);
        return new PgcWritePlanEntry(cand.MemoryWriteId, d, finalIntensity, reasonCodes, ExpectedTests(d, reasonCodes),
            new PgcStateSnapshot(stateId, components, policy.Version));
    }

    /// <summary>The write plan and contradiction report for a batch; any high-severity contradiction makes the report high.</summary>
    public static PgcDecisionResult Decide(PgcInput input)
    {
        var policy = ResolvePolicy(input.PgcPolicyVersion);
        var ctx = input.PgcReadContext;
        var plan = input.CandidateMemoryWrites.Select(c => DecideCandidate(c, ctx, policy)).ToList();
        var conflicting = new List<string>();
        var seen = new HashSet<string>(StringComparer.Ordinal);
        var maxSeverity = 0.0;
        foreach (var entry in plan)
        {
            var cand = input.CandidateMemoryWrites.First(c => c.MemoryWriteId == entry.MemoryWriteId);
            var (severity, ids) = DetectContradiction(cand, ctx.Beliefs, (ctx.EvidenceRecords ?? []).Where(r => cand.EvidenceIds.Contains(r.Id)).ToList());
            foreach (var id in ids)
            {
                if (seen.Add(id))
                    conflicting.Add(id);
            }
            maxSeverity = Math.Max(maxSeverity, severity);
        }
        return new PgcDecisionResult($"pgc_{input.SessionId}_{input.TraceId}_{policy.Version}", plan,
            new ContradictionReport(maxSeverity >= policy.ContradictionSeverityHighThreshold ? "high" : "low", conflicting.Count > 0 ? conflicting : null));
    }

    /// <summary>
    /// Wrap a PGC decision as aijade.pgc.write_plan_ready. The policy version is taken as the last
    /// "_"-separated segment of the state id — for "pgc_s_t_pgc_policy_v1" that is "v1", not the full version string.
    /// Reproduced as is so that events stay identical to those already logged.
    /// </summary>
    public static JsonObject BuildWritePlanReadyEvent(PgcDecisionResult decision, JsonObject envelope) =>
        AijadeEvents.Build(AijadeEvents.PgcWritePlanReady, envelope, new JsonObject
        {
            ["pgc_state_id"] = decision.PgcStateId,
            ["write_plan_size"] = decision.WritePlan.Count,
            ["policy_version"] = decision.PgcStateId.Split('_')[^1],
        });
}
