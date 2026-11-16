using System.Text.RegularExpressions;

namespace Aijade.Memory.Contracts;

// v8 §53.2 autonomous-growth contracts #16–#28: DIVE interest threads, AEL quests and evidence, transfer and
// association, life journal and selective sharing, VSE self-evolution and PEF persona expression.

public sealed record Budget(double Allocated, double Spent, string Unit);

/// <summary>#16 — a developmental interest thread with history, value, relevance and a bounded attention budget.</summary>
public sealed record InterestThread(
    string Id, string AgentId, string UserScope, string Subject, IReadOnlyList<string> OriginEventIds, IReadOnlyList<string> MotivatingQuestions,
    double IntrinsicValue, double IdentityRelevance, double UserRelevance, double NoveltyFrontier, IReadOnlyList<string> KnowledgeGaps,
    IReadOnlyList<string> CurrentHypotheses, double Progress, Budget AttentionBudget, string Status, double LastReflectedAt,
    string? AbandonedReason = null, string? TraceId = null);

public sealed record SourcePlan(string QuestionType, IReadOnlyList<string> SourceTypes, int MaxSources);

/// <summary>#17 — a learning quest, bounded before it starts by stop conditions and a resource budget.</summary>
public sealed record LearningQuest(
    string Id, string AgentId, string UserScope, string InterestThreadRef, string ResearchQuestion, string OperationalDefinition,
    IReadOnlyList<string> PriorBeliefs, double ExpectedInformationGain, SourcePlan SourcePlan, Budget ResourceBudget, string PrivacyClass,
    IReadOnlyList<string> StopConditions, IReadOnlyList<string> SuccessCriteria, IReadOnlyList<string> Deliverables,
    string ExperimentManifestRef, string Status, double CreatedAt, string? TraceId = null);

public sealed record SourceQuality(double Reliability, double Independence, double Directness, double Recency, double Reproducibility);

/// <summary>#18 — a source with lineage (to detect reposts posing as independent sources) and quality.</summary>
public sealed record SourceRecord(
    string Id, string Locator, string SourceType, SourceQuality Quality, IReadOnlyList<string> UpstreamRefs, string ContentHash,
    double FetchedAt, string? License = null, string? TraceId = null);

public sealed record Claim(string Proposition, string EpistemicStatus, IReadOnlyList<string> SupportSourceRefs, IReadOnlyList<string> CounterSourceRefs, double Confidence);

/// <summary>#19 — propositions with support and retained counter-evidence.</summary>
public sealed record ClaimMap(string Id, string AgentId, string UserScope, string QuestRef, IReadOnlyList<Claim> Claims, double CreatedAt, string? TraceId = null);

/// <summary>#20 — a synthesised knowledge artefact; the evidence graph, not the summary, is the source.</summary>
public sealed record KnowledgeArtifact(
    string Id, string AgentId, string UserScope, string Kind, string QuestRef, object? Payload, string EvidenceGraphRef,
    IReadOnlyList<SourceRef> Sources, double CreatedAt, string? TraceId = null);

/// <summary>#21 — an association that keeps the reasoning path that produced it.</summary>
public sealed record AssociationPath(
    string Id, string AgentId, string UserScope, string FromConcept, string ToConcept, string Kind, IReadOnlyList<string> Path,
    double Score, IReadOnlyList<string> EvidenceRefs, double CreatedAt, string? TraceId = null);

/// <summary>#22 — knowledge / skill transfer; failed transfers are kept as counter-examples.</summary>
public sealed record TransferRecord(
    string Id, string AgentId, string UserScope, string SourceDomain, string TargetDomain, IReadOnlyList<string> InvariantsPreserved,
    IReadOnlyList<string> BrokenConditions, string PredictedOutcome, string MeasuredOutcome, double NegativeTransferSignal, string Tier,
    bool Validated, double CreatedAt, string? TraceId = null);

/// <summary>#23 — a privacy-filtered autobiographical journal entry.</summary>
public sealed record LifeJournalEntry(
    string Id, string AgentId, string UserScope, string Date, IReadOnlyList<string> ExperiencedEvents, IReadOnlyList<string> ActiveInterests,
    IReadOnlyList<string> LearnedClaims, IReadOnlyList<string> ChangedBeliefs, IReadOnlyList<string> PracticedSkills,
    IReadOnlyList<string> UnresolvedQuestions, IReadOnlyList<string> IdentityReflections, string SharePolicy, IReadOnlyList<string> EvidenceRefs,
    double CreatedAt, string? TraceId = null);

public sealed record ShareUtility(
    double Relevance, double Novelty, double RelationalValue, double Timeliness, double Uncertainty, double Interruption, double PrivacyRisk, double Repetition);

/// <summary>#24 — a candidate share with its utility and one of four channels.</summary>
public sealed record ShareCandidate(
    string Id, string AgentId, string UserScope, string ContentRef, ShareUtility Utility, double Score, string Channel, double DecidedAt, string? TraceId = null);

public sealed record ProposalTest(string Kind, bool Passed, string? EvidenceRef = null);

/// <summary>#25 — the immutable evidence pack for a candidate change; rollback plan is mandatory.</summary>
public sealed record EvolutionProposal(
    string Id, string AgentId, IReadOnlyList<string> TriggerEvidence, IReadOnlyList<string> AffectedComponents, string Grade,
    string BaselineVersion, string ChangeSpec, string SourceDiff, string GeneratedBy, IReadOnlyList<ProposalTest> Tests, string RollbackPlan,
    string ApprovalPolicy, string Signature, double CreatedAt, string? DependencyDiff = null, string? MigrationPlan = null,
    IReadOnlyDictionary<string, double>? BenchmarkResults = null, IReadOnlyDictionary<string, object>? SafetyResults = null,
    string? BehaviorDiff = null, string? IdentityDiff = null, string? TraceId = null);

public sealed record GateResult(bool Passed, int? Findings = null);

public sealed record CoreTestGate(bool Passed, int Total, int Failed);

/// <summary>#26 — per-stage evaluation results; no passing core test gate, no promotion.</summary>
public sealed record EvaluationEvidencePack(
    string Id, string ProposalRef, CoreTestGate UnitContractPropertyTests, double CreatedAt, GateResult? StaticAnalysis = null,
    (bool Passed, IReadOnlyList<string>? Violations)? DependencyLicenseScan = null, GateResult? SecuritySandbox = null,
    GateResult? HistoricalReplay = null, GateResult? AdversarialEval = null, (bool Improved, IReadOnlyDictionary<string, double>? Delta)? BenchmarkComparison = null,
    string? BehaviorDiff = null, string? IdentityDiff = null, string? TraceId = null);

/// <summary>#27 — a signed release with canary ratio and a rollback path that must exist.</summary>
public sealed record SignedRelease(
    string Id, string Version, string ProposalRef, string EvidencePackRef, string ApprovedBy, double SignedAt, string Signature,
    double CanaryRatio, bool RollbackAvailable, string? TraceId = null);

public sealed record ExpressionVector(
    double Valence, double Arousal, double Dominance, double Intimacy, double Certainty, double Curiosity, double Playfulness, double Reflection, double Urgency);

public sealed record VoiceProsody(double? Rate = null, double? Pitch = null, double? Energy = null);

/// <summary>#28 — an incremental, time-marked persona-expression intent tied to a persona snapshot.</summary>
public sealed record PerformanceIntent(
    string Id, string AgentId, string UserScope, string PersonaSnapshotRef, double TimeMarked, ExpressionVector Expression, double Duration,
    string? TextStyle = null, VoiceProsody? VoiceProsody = null, string? Face = null, string? Gaze = null, string? Gesture = null,
    string? Posture = null, string? TurnTaking = null, string? CameraBehavior = null, string? SceneContext = null, string? TraceId = null);

public static partial class ContractValidationV8
{
    private static bool In01(double n) => double.IsFinite(n) && n is >= 0 and <= 1;

    private static bool Blank(string? s) => string.IsNullOrWhiteSpace(s);

    private static bool HasSources(IReadOnlyList<SourceRef>? sources) =>
        sources is { Count: > 0 } && sources.All(s => !string.IsNullOrEmpty(s.Ref));

    private static Validation BudgetCheck(Budget b, string name)
    {
        if (!double.IsFinite(b.Allocated) || b.Allocated < 0)
            return Validation.Fail($"{name}.allocated must be a finite number ≥ 0");
        if (!double.IsFinite(b.Spent) || b.Spent < 0)
            return Validation.Fail($"{name}.spent must be a finite number ≥ 0");
        if (b.Spent > b.Allocated)
            return Validation.Fail($"{name}.spent must not exceed allocated");
        return Validation.Pass;
    }

    private static readonly string[] InterestStatuses = ["latent", "active", "incubating", "satisfied", "abandoned"];

    public static Validation Validate(InterestThread t)
    {
        if (Blank(t.Subject))
            return Validation.Fail("InterestThread.subject must be a non-empty string");
        if (t.OriginEventIds.Count == 0)
            return Validation.Fail("InterestThread must have ≥1 origin event (v8 §47.1 history)");
        if (!new[] { t.IntrinsicValue, t.IdentityRelevance, t.UserRelevance, t.NoveltyFrontier, t.Progress }.All(In01))
            return Validation.Fail("InterestThread value fields must be ∈ [0,1]");
        if (BudgetCheck(t.AttentionBudget, "InterestThread.attentionBudget") is { Ok: false } b)
            return b;
        if (!InterestStatuses.Contains(t.Status))
            return Validation.Fail($"InterestThread.status must be one of {string.Join('|', InterestStatuses)}");
        if (t.Status == "abandoned" && string.IsNullOrEmpty(t.AbandonedReason))
            return Validation.Fail("InterestThread abandoned threads must record abandonedReason (v8 §47.2)");
        if (!double.IsFinite(t.LastReflectedAt))
            return Validation.Fail("InterestThread.lastReflectedAt must be a finite timestamp");
        return Validation.Pass;
    }

    public static Validation Validate(LearningQuest q)
    {
        if (Blank(q.InterestThreadRef))
            return Validation.Fail("LearningQuest must bind to an interest thread (interestThreadRef)");
        if (Blank(q.ResearchQuestion))
            return Validation.Fail("LearningQuest.researchQuestion must be a non-empty string");
        if (Blank(q.OperationalDefinition))
            return Validation.Fail("LearningQuest.operationalDefinition must be a non-empty string");
        if (!In01(q.ExpectedInformationGain))
            return Validation.Fail("LearningQuest.expectedInformationGain must be ∈ [0,1]");
        if (q.StopConditions.Count == 0)
            return Validation.Fail("LearningQuest must declare ≥1 stop condition (v8 §48.2 no endless browsing)");
        if (BudgetCheck(q.ResourceBudget, "LearningQuest.resourceBudget") is { Ok: false } b)
            return b;
        if (Blank(q.ExperimentManifestRef))
            return Validation.Fail("LearningQuest must reference an ExperimentManifest (experimentManifestRef)");
        return Validation.Pass;
    }

    public static Validation Validate(SourceRecord s)
    {
        if (Blank(s.Locator))
            return Validation.Fail("SourceRecord.locator must be a non-empty string");
        if (Blank(s.SourceType))
            return Validation.Fail("SourceRecord.sourceType must be a non-empty string");
        var q = s.Quality;
        if (!new[] { q.Reliability, q.Independence, q.Directness, q.Recency, q.Reproducibility }.All(In01))
            return Validation.Fail("SourceRecord.quality dimensions must all be ∈ [0,1]");
        if (Blank(s.ContentHash))
            return Validation.Fail("SourceRecord.contentHash must be a non-empty string (dedup reposts)");
        if (!double.IsFinite(s.FetchedAt))
            return Validation.Fail("SourceRecord.fetchedAt must be a finite timestamp");
        return Validation.Pass;
    }

    private static readonly string[] EpistemicStatuses = ["observed", "source_statement", "inference", "hypothesis", "value_judgment", "unknown"];

    public static Validation Validate(ClaimMap m)
    {
        if (Blank(m.QuestRef))
            return Validation.Fail("ClaimMap must bind to a quest (questRef)");
        foreach (var c in m.Claims)
        {
            if (Blank(c.Proposition))
                return Validation.Fail("ClaimMap claim must have a non-empty proposition");
            if (!EpistemicStatuses.Contains(c.EpistemicStatus))
                return Validation.Fail($"ClaimMap claim.epistemicStatus must be one of {string.Join('|', EpistemicStatuses)}");
            if (c.SupportSourceRefs.Count == 0)
                return Validation.Fail("ClaimMap claim must have ≥1 support source (v7 §6)");
            if (!In01(c.Confidence))
                return Validation.Fail("ClaimMap claim.confidence must be ∈ [0,1]");
        }
        return Validation.Pass;
    }

    private static readonly string[] ArtifactKinds =
        ["claim_map", "concept_map", "causal_model", "procedure", "comparison_matrix", "open_question_set", "learning_note", "shareable_story"];

    public static Validation Validate(KnowledgeArtifact a)
    {
        if (!ArtifactKinds.Contains(a.Kind))
            return Validation.Fail($"KnowledgeArtifact.kind must be one of {string.Join('|', ArtifactKinds)}");
        if (Blank(a.QuestRef))
            return Validation.Fail("KnowledgeArtifact must bind to a quest (questRef)");
        if (Blank(a.EvidenceGraphRef))
            return Validation.Fail("KnowledgeArtifact must reference the evidence graph (summary ≠ source)");
        if (!HasSources(a.Sources))
            return Validation.Fail("KnowledgeArtifact must carry ≥1 source (v7 §6)");
        return Validation.Pass;
    }

    private static readonly string[] AssociationKinds = ["semantic", "causal", "temporal", "structural", "autobiographical", "embodied"];

    public static Validation Validate(AssociationPath p)
    {
        if (!AssociationKinds.Contains(p.Kind))
            return Validation.Fail($"AssociationPath.kind must be one of {string.Join('|', AssociationKinds)}");
        if (Blank(p.FromConcept))
            return Validation.Fail("AssociationPath.fromConcept must be a non-empty string");
        if (Blank(p.ToConcept))
            return Validation.Fail("AssociationPath.toConcept must be a non-empty string");
        if (p.Path.Count == 0)
            return Validation.Fail("AssociationPath must keep ≥1 reasoning step (v8 §49.2 no pathless association)");
        if (!double.IsFinite(p.Score))
            return Validation.Fail("AssociationPath.score must be a finite number");
        return Validation.Pass;
    }

    private static readonly string[] Tiers = ["T0", "T1", "T2", "T3", "T4"];

    public static Validation Validate(TransferRecord r)
    {
        if (!Tiers.Contains(r.Tier))
            return Validation.Fail($"TransferRecord.tier must be one of {string.Join('|', Tiers)}");
        if (Blank(r.SourceDomain))
            return Validation.Fail("TransferRecord.sourceDomain must be a non-empty string");
        if (Blank(r.TargetDomain))
            return Validation.Fail("TransferRecord.targetDomain must be a non-empty string");
        if (!In01(r.NegativeTransferSignal))
            return Validation.Fail("TransferRecord.negativeTransferSignal must be ∈ [0,1]");
        if (r.Tier is "T2" or "T3" or "T4" && !r.Validated)
            return Validation.Fail("TransferRecord tier T2+ must be validated (v8 §49.3)");
        return Validation.Pass;
    }

    [GeneratedRegex("^[0-9]{4}-[0-9]{2}-[0-9]{2}$")]
    private static partial Regex IsoDate();

    private static readonly string[] SharePolicies = ["private", "diary_only", "shareable"];

    public static Validation Validate(LifeJournalEntry e)
    {
        if (!IsoDate().IsMatch(e.Date))
            return Validation.Fail("LifeJournalEntry.date must be ISO YYYY-MM-DD");
        if (!SharePolicies.Contains(e.SharePolicy))
            return Validation.Fail($"LifeJournalEntry.sharePolicy must be one of {string.Join('|', SharePolicies)}");
        if (!double.IsFinite(e.CreatedAt))
            return Validation.Fail("LifeJournalEntry.createdAt must be a finite timestamp");
        return Validation.Pass;
    }

    private static readonly string[] Channels = ["diary", "next_chat", "light_hint", "full_share"];

    public static Validation Validate(ShareCandidate c)
    {
        if (Blank(c.ContentRef))
            return Validation.Fail("ShareCandidate.contentRef must be a non-empty string");
        var u = c.Utility;
        if (!new[] { u.Relevance, u.Novelty, u.RelationalValue, u.Timeliness, u.Uncertainty, u.Interruption, u.PrivacyRisk, u.Repetition }.All(In01))
            return Validation.Fail("ShareCandidate.utility components must all be ∈ [0,1]");
        if (!double.IsFinite(c.Score))
            return Validation.Fail("ShareCandidate.score must be a finite number");
        if (!Channels.Contains(c.Channel))
            return Validation.Fail($"ShareCandidate.channel must be one of {string.Join('|', Channels)}");
        if (!double.IsFinite(c.DecidedAt))
            return Validation.Fail("ShareCandidate.decidedAt must be a finite timestamp");
        return Validation.Pass;
    }

    private static readonly string[] Grades = ["E0", "E1", "E2", "E3", "E4", "E5"];

    public static Validation Validate(EvolutionProposal p)
    {
        if (!Grades.Contains(p.Grade))
            return Validation.Fail($"EvolutionProposal.grade must be one of {string.Join('|', Grades)}");
        if (Blank(p.BaselineVersion))
            return Validation.Fail("EvolutionProposal.baselineVersion must be a non-empty string");
        if (Blank(p.ChangeSpec))
            return Validation.Fail("EvolutionProposal.changeSpec must be a non-empty string");
        if (Blank(p.SourceDiff))
            return Validation.Fail("EvolutionProposal.sourceDiff must be a non-empty string");
        if (Blank(p.RollbackPlan))
            return Validation.Fail("EvolutionProposal must carry a rollback plan (v8 §51.3 recoverability)");
        if (p.Tests.Count == 0)
            return Validation.Fail("EvolutionProposal must include ≥1 test (v8 §51.3)");
        if (Blank(p.Signature))
            return Validation.Fail("EvolutionProposal.signature must be a non-empty string");
        if (Blank(p.GeneratedBy))
            return Validation.Fail("EvolutionProposal.generatedBy must be a non-empty string");
        return Validation.Pass;
    }

    public static Validation Validate(EvaluationEvidencePack p)
    {
        if (Blank(p.ProposalRef))
            return Validation.Fail("EvaluationEvidencePack must bind to a proposal (proposalRef)");
        var t = p.UnitContractPropertyTests;
        if (t.Total < 0)
            return Validation.Fail("EvaluationEvidencePack.unitContractPropertyTests.total must be ≥ 0");
        if (t.Failed < 0)
            return Validation.Fail("EvaluationEvidencePack.unitContractPropertyTests.failed must be ≥ 0");
        if (t.Failed > t.Total)
            return Validation.Fail("EvaluationEvidencePack failed tests must not exceed total");
        if (t.Failed > 0 && t.Passed)
            return Validation.Fail("EvaluationEvidencePack cannot pass core gate with failing tests");
        return Validation.Pass;
    }

    public static Validation Validate(SignedRelease r)
    {
        if (Blank(r.Version))
            return Validation.Fail("SignedRelease.version must be a non-empty string");
        if (Blank(r.ProposalRef))
            return Validation.Fail("SignedRelease must bind to a proposal (proposalRef)");
        if (Blank(r.EvidencePackRef))
            return Validation.Fail("SignedRelease must bind to an evidence pack (evidencePackRef)");
        if (Blank(r.ApprovedBy))
            return Validation.Fail("SignedRelease.approvedBy must be a non-empty string");
        if (Blank(r.Signature))
            return Validation.Fail("SignedRelease.signature must be a non-empty string");
        if (!In01(r.CanaryRatio))
            return Validation.Fail("SignedRelease.canaryRatio must be ∈ [0,1]");
        if (!r.RollbackAvailable)
            return Validation.Fail("SignedRelease must keep rollback available (v8 §51.3 keep-or-rollback)");
        if (!double.IsFinite(r.SignedAt))
            return Validation.Fail("SignedRelease.signedAt must be a finite timestamp");
        return Validation.Pass;
    }

    public static Validation Validate(PerformanceIntent i)
    {
        if (Blank(i.PersonaSnapshotRef))
            return Validation.Fail("PerformanceIntent must reference a persona snapshot (personaSnapshotRef, v8 §52.5)");
        var e = i.Expression;
        if (!double.IsFinite(e.Valence) || e.Valence < -1 || e.Valence > 1)
            return Validation.Fail("PerformanceIntent.expression.valence must be ∈ [−1,1]");
        if (!new[] { e.Arousal, e.Dominance, e.Intimacy, e.Certainty, e.Curiosity, e.Playfulness, e.Reflection, e.Urgency }.All(In01))
            return Validation.Fail("PerformanceIntent.expression components (besides valence) must be ∈ [0,1]");
        if (!double.IsFinite(i.TimeMarked))
            return Validation.Fail("PerformanceIntent.timeMarked must be a finite timestamp");
        if (!double.IsFinite(i.Duration) || i.Duration < 0)
            return Validation.Fail("PerformanceIntent.duration must be a finite number ≥ 0");
        return Validation.Pass;
    }
}
