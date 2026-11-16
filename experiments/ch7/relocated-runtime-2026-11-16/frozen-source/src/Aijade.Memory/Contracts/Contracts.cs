using System.Text.RegularExpressions;

using Aijade.Core.Js;

namespace Aijade.Memory.Contracts;

// v7 §24/§25 wire contracts. Each validator is pure and returns a result instead of throwing, so a refusal can be
// recorded and source traceability measured. Enumerated fields stay strings because they arrive over the wire and
// the validators exist precisely to reject unknown values.

/// <summary>Outcome of a contract validator.</summary>
public readonly record struct Validation(bool Ok, string? Reason = null)
{
    public static Validation Pass => new(true);

    public static Validation Fail(string reason) => new(false, reason);
}

public sealed record SourceRef(string Ref, bool Trusted, string? ConsentPolicy = null);

/// <summary>v7 §24 — every percept / action / state transition is wrapped in this envelope.</summary>
public sealed record EventEnvelope(
    string EventId, string Schema, string AgentId, string UserScope, string DeviceId, string SessionId, string Timestamp,
    IReadOnlyList<string> Modality, string PayloadRef, EventProvenance Provenance, string Privacy, string TraceId);

public sealed record EventProvenance(string Source, bool Trusted, string ConsentPolicy);

/// <summary>v7 §25 #4 — a memory proposed for admission; it must name its source (§6).</summary>
public sealed record MemoryCandidate(
    string Id, string Content, string Kind, IReadOnlyList<SourceRef> Sources, double ProposedAt, double? Salience = null, string? TraceId = null)
{
    public const string SchemaId = "aijade.memory_candidate@1";
}

public sealed record ExperimentCondition(string Name, string Description, IReadOnlyDictionary<string, object?>? Params = null);

/// <summary>v7 §25 #15 — a reproducible experiment: fixed seed, conditions, committed metrics.</summary>
public sealed record ExperimentManifest(
    string Id, string Name, string Version, double Seed, IReadOnlyList<ExperimentCondition> Conditions, IReadOnlyList<string> Metrics,
    double CreatedAt, string? Notes = null)
{
    public const string SchemaId = "aijade.experiment_manifest@1";
}

public sealed record AppraisalDimensions(double Valence, double Arousal, double GoalRelevance, double Novelty, double Control, double Urgency);

/// <summary>v7 §25 #2 — stimulus appraisal with a bounded confidence.</summary>
public sealed record Appraisal(
    string Id, string EventRef, string AgentId, string UserScope, AppraisalDimensions Dimensions, double Confidence,
    string AppraisedBy, double AppraisedAt, string? TraceId = null)
{
    public const string SchemaId = "aijade.appraisal@1";
}

/// <summary>HAC endogenous state z_t = [a, v, d, n, s, c, b], all in [0, 1].</summary>
public sealed record EndogenousStateVector(double Arousal, double Vigilance, double Drive, double Novelty, double Safety, double CognitiveLoad, double Boredom);

/// <summary>v7 §25 #3 — immutable, content-addressed snapshot of the endogenous state.</summary>
public sealed record StateSnapshot(
    string Id, string AgentId, string UserScope, double TakenAt, EndogenousStateVector State, string Source, bool Frozen,
    string Fingerprint, string? TraceId = null)
{
    public const string SchemaId = "aijade.state_snapshot@1";
}

/// <summary>v7 §25 #14 — explicit or implicit feedback bound to a target.</summary>
public sealed record FeedbackEvent(
    string Id, string AgentId, string UserScope, string SessionId, string TargetRef, string Type, string Signal, double Timestamp,
    double? Value = null, IReadOnlyDictionary<string, double>? Evidence = null, double? Valence = null, string? TraceId = null)
{
    public const string SchemaId = "aijade.feedback_event@1";
}

public sealed record GoalBudget(double Allocated, double Spent, string Unit);

/// <summary>v7 §25 #7 — a goal with provenance, lifecycle status and budget.</summary>
public sealed record GoalRecord(
    string Id, string AgentId, string UserScope, string Goal, SourceRef? Source, string Status, GoalBudget Budget, double CreatedAt,
    string? PlanRef = null, string? TraceId = null)
{
    public const string SchemaId = "aijade.goal_record@1";
}

public sealed record PlanNode(string Id, string Kind, string Label, IReadOnlyList<string> DependsOn, IReadOnlyList<string>? Compensates = null, string? Status = null);

public sealed record PlanEdge(string From, string To, string Type);

/// <summary>v7 §25 #8 — a plan as a DAG with saga-style compensation.</summary>
public sealed record PlanGraph(
    string Id, string AgentId, string UserScope, IReadOnlyList<PlanNode> Nodes, double CreatedAt, IReadOnlyList<PlanEdge>? Edges = null,
    string? GoalRef = null, string? TraceId = null)
{
    public const string SchemaId = "aijade.plan_graph@1";
}

public sealed record Grantee(string? AgentId = null, string? UserScope = null);

/// <summary>v7 §25 #9 — a capability granted with scope, consent and provenance.</summary>
public sealed record CapabilityGrant(
    string Id, Grantee Grantee, string Capability, string Scope, string GrantedBy, double IssuedAt, string ConsentPolicy,
    IReadOnlyList<SourceRef> Source, double? ExpiresAt = null, string? TraceId = null)
{
    public const string SchemaId = "aijade.capability_grant@1";
}

/// <summary>v7 §25 #10 — an action the agent executed, bound to its episode.</summary>
public sealed record ActionRecord(
    string Id, string AgentId, string UserScope, string Action, IReadOnlyDictionary<string, object?> Args, string Outcome,
    string EpisodeRef, double Timestamp, string? PlanRef = null, string? TraceId = null)
{
    public const string SchemaId = "aijade.action_record@1";
}

/// <summary>v7 §25 #11 — a non-trivial semantic change between two states.</summary>
public sealed record SemanticMotion(
    string Id, string AgentId, string UserScope, string FromRef, string ToRef, object? Delta, double Magnitude, string Basis,
    double Timestamp, IReadOnlyList<SourceRef> Source, string? TraceId = null)
{
    public const string SchemaId = "aijade.semantic_motion@1";
}

public sealed record SkillManifest(IReadOnlyDictionary<string, object?>? Inputs, IReadOnlyDictionary<string, object?>? Outputs, string Signature);

/// <summary>v7 §25 #12 — a versioned, packaged, executable skill.</summary>
public sealed record SkillPackage(
    string Id, string Name, string Version, string CapabilityRef, SkillManifest? Manifest, string ArtifactRef, string Author,
    IReadOnlyList<SourceRef> Source, string? ValidatedBy = null, IReadOnlyDictionary<string, double>? Metrics = null, string? TraceId = null)
{
    public const string SchemaId = "aijade.skill_package@1";
}

public static partial class ContractValidation
{
    private static bool Blank(string? s) => string.IsNullOrWhiteSpace(s);

    public static Validation Validate(MemoryCandidate c) =>
        c.Sources.Count == 0 ? Validation.Fail("MemoryCandidate must carry ≥1 source (v7 §6 traceability)") : Validation.Pass;

    public static Validation Validate(ExperimentManifest m)
    {
        if (!double.IsFinite(m.Seed))
            return Validation.Fail("ExperimentManifest requires a fixed seed (reproducibility)");
        if (m.Conditions.Count == 0)
            return Validation.Fail("ExperimentManifest requires ≥1 condition");
        if (m.Metrics.Count == 0)
            return Validation.Fail("ExperimentManifest requires ≥1 reported metric (falsifiable)");
        return Validation.Pass;
    }

    public static Validation Validate(Appraisal a)
    {
        if (string.IsNullOrEmpty(a.EventRef))
            return Validation.Fail("Appraisal must bind to an event (eventRef, v7 §25 #2)");
        if (a.Confidence < 0 || a.Confidence > 1)
            return Validation.Fail("Appraisal.confidence must be ∈ [0,1]");
        var d = a.Dimensions;
        if (!new[] { d.Valence, d.Arousal, d.GoalRelevance, d.Novelty, d.Control, d.Urgency }.All(double.IsFinite))
            return Validation.Fail("Appraisal dimensions must all be finite numbers");
        if (d.Valence is < -1 or > 1)
            return Validation.Fail("Appraisal.valence must be ∈ [−1,1]");
        if (d.Arousal is < 0 or > 1)
            return Validation.Fail("Appraisal.arousal must be ∈ [0,1]");
        if (d.GoalRelevance is < 0 or > 1)
            return Validation.Fail("Appraisal.goalRelevance must be ∈ [0,1]");
        if (d.Novelty is < 0 or > 1)
            return Validation.Fail("Appraisal.novelty must be ∈ [0,1]");
        if (d.Control is < -1 or > 1)
            return Validation.Fail("Appraisal.control must be ∈ [−1,1]");
        if (d.Urgency is < 0 or > 1)
            return Validation.Fail("Appraisal.urgency must be ∈ [0,1]");
        if (!double.IsFinite(a.AppraisedAt))
            return Validation.Fail("Appraisal.appraisedAt must be a finite timestamp");
        return Validation.Pass;
    }

    public static Validation Validate(StateSnapshot s)
    {
        if (!s.Frozen)
            return Validation.Fail("StateSnapshot must be frozen (immutable, v7 §25 #3)");
        if (string.IsNullOrEmpty(s.Fingerprint))
            return Validation.Fail("StateSnapshot requires a content fingerprint");
        if (!double.IsFinite(s.TakenAt))
            return Validation.Fail("StateSnapshot.takenAt must be a finite timestamp");
        var st = s.State;
        double[] dims = [st.Arousal, st.Vigilance, st.Drive, st.Novelty, st.Safety, st.CognitiveLoad, st.Boredom];
        if (!dims.All(double.IsFinite))
            return Validation.Fail("StateSnapshot.state values must all be finite");
        if (dims.Any(x => x is < 0 or > 1))
            return Validation.Fail("StateSnapshot.state values must be ∈ [0,1]");
        return Validation.Pass;
    }

    public static Validation Validate(FeedbackEvent f)
    {
        if (string.IsNullOrEmpty(f.TargetRef))
            return Validation.Fail("FeedbackEvent must bind to a target (targetRef, v7 §25 #14)");
        if (f.Type is not ("explicit" or "implicit"))
            return Validation.Fail("FeedbackEvent.type must be explicit|implicit");
        if (string.IsNullOrEmpty(f.Signal))
            return Validation.Fail("FeedbackEvent.signal must be a non-empty string");
        if (!double.IsFinite(f.Timestamp))
            return Validation.Fail("FeedbackEvent.timestamp must be a finite number");
        if (f.Value is { } v && !double.IsFinite(v))
            return Validation.Fail("FeedbackEvent.value must be a number when present");
        if (f.Valence is < -1 or > 1)
            return Validation.Fail("FeedbackEvent.valence must be ∈ [−1,1]");
        return Validation.Pass;
    }

    private static readonly string[] GoalStatuses = ["active", "paused", "achieved", "abandoned", "failed"];

    public static Validation Validate(GoalRecord g)
    {
        if (Blank(g.Goal))
            return Validation.Fail("GoalRecord.goal must be a non-empty string");
        if (string.IsNullOrEmpty(g.Source?.Ref))
            return Validation.Fail("GoalRecord must carry a source ref (v7 §6)");
        if (!GoalStatuses.Contains(g.Status))
            return Validation.Fail($"GoalRecord.status must be one of {string.Join('|', GoalStatuses)}");
        if (!double.IsFinite(g.Budget.Allocated) || g.Budget.Allocated < 0)
            return Validation.Fail("GoalRecord.budget.allocated must be a finite number ≥ 0");
        if (!double.IsFinite(g.Budget.Spent) || g.Budget.Spent < 0)
            return Validation.Fail("GoalRecord.budget.spent must be a finite number ≥ 0");
        if (g.Budget.Spent > g.Budget.Allocated)
            return Validation.Fail("GoalRecord.budget.spent must not exceed allocated");
        return Validation.Pass;
    }

    private static readonly string[] PlanKinds = ["action", "check", "parallel", "goal"];

    public static Validation Validate(PlanGraph p)
    {
        if (p.Nodes.Count == 0)
            return Validation.Fail("PlanGraph must contain ≥1 node");
        var ids = new List<string>();
        foreach (var n in p.Nodes)
        {
            if (string.IsNullOrEmpty(n.Id))
                return Validation.Fail("PlanGraph node must have an id");
            if (ids.Contains(n.Id))
                return Validation.Fail($"PlanGraph duplicate node id: {n.Id}");
            ids.Add(n.Id);
        }
        var known = ids.ToHashSet();
        foreach (var n in p.Nodes)
        {
            if (!PlanKinds.Contains(n.Kind))
                return Validation.Fail($"PlanGraph node.kind must be one of {string.Join('|', PlanKinds)}");
            foreach (var dep in n.DependsOn)
            {
                if (!known.Contains(dep))
                    return Validation.Fail($"PlanGraph node {n.Id} depends on unknown node {dep}");
            }
            foreach (var comp in n.Compensates ?? [])
            {
                if (!known.Contains(comp))
                    return Validation.Fail($"PlanGraph node {n.Id} compensates unknown node {comp}");
            }
        }
        foreach (var e in p.Edges ?? [])
        {
            if (!known.Contains(e.From) || !known.Contains(e.To))
                return Validation.Fail($"PlanGraph edge references unknown node ({e.From}→{e.To})");
        }

        // Acyclic dependency check: DFS with white / gray / black colouring.
        var color = ids.ToDictionary(id => id, _ => 0);
        var byId = p.Nodes.ToDictionary(n => n.Id);
        bool HasCycle(string u)
        {
            color[u] = 1;
            foreach (var v in byId[u].DependsOn)
            {
                if (color[v] == 1)
                    return true;
                if (color[v] == 0 && HasCycle(v))
                    return true;
            }
            color[u] = 2;
            return false;
        }
        foreach (var id in ids)
        {
            if (color[id] == 0 && HasCycle(id))
                return Validation.Fail("PlanGraph dependency graph contains a cycle");
        }
        return Validation.Pass;
    }

    public static Validation Validate(CapabilityGrant g)
    {
        if (Blank(g.Capability))
            return Validation.Fail("CapabilityGrant.capability must be a non-empty string");
        if (string.IsNullOrEmpty(g.Grantee.AgentId) && string.IsNullOrEmpty(g.Grantee.UserScope))
            return Validation.Fail("CapabilityGrant.grantee must identify an agent or user scope");
        if (Blank(g.GrantedBy))
            return Validation.Fail("CapabilityGrant.grantedBy must be a non-empty string");
        if (!double.IsFinite(g.IssuedAt))
            return Validation.Fail("CapabilityGrant.issuedAt must be a finite timestamp");
        if (g.ExpiresAt is { } exp)
        {
            if (!double.IsFinite(exp))
                return Validation.Fail("CapabilityGrant.expiresAt must be a finite timestamp");
            if (exp <= g.IssuedAt)
                return Validation.Fail("CapabilityGrant.expiresAt must be > issuedAt");
        }
        if (Blank(g.ConsentPolicy))
            return Validation.Fail("CapabilityGrant.consentPolicy must be a non-empty string");
        if (g.Source.Count == 0 || !g.Source.All(s => !string.IsNullOrEmpty(s.Ref)))
            return Validation.Fail("CapabilityGrant must carry ≥1 source with a ref (v7 §6)");
        return Validation.Pass;
    }

    public static Validation Validate(ActionRecord r)
    {
        if (Blank(r.Action))
            return Validation.Fail("ActionRecord.action must be a non-empty string");
        if (Blank(r.EpisodeRef))
            return Validation.Fail("ActionRecord.episodeRef must be a non-empty string (v7 §10.1)");
        if (string.IsNullOrEmpty(r.AgentId) && string.IsNullOrEmpty(r.UserScope))
            return Validation.Fail("ActionRecord must identify an agent or user scope");
        if (!double.IsFinite(r.Timestamp))
            return Validation.Fail("ActionRecord.timestamp must be a finite number");
        return Validation.Pass;
    }

    public static Validation Validate(SemanticMotion m)
    {
        if (Blank(m.FromRef))
            return Validation.Fail("SemanticMotion.fromRef must be a non-empty string");
        if (Blank(m.ToRef))
            return Validation.Fail("SemanticMotion.toRef must be a non-empty string");
        if (m.FromRef == m.ToRef)
            return Validation.Fail("SemanticMotion.fromRef and toRef must differ (non-trivial motion)");
        if (!double.IsFinite(m.Magnitude) || m.Magnitude < 0)
            return Validation.Fail("SemanticMotion.magnitude must be a finite number ≥ 0");
        if (Blank(m.Basis))
            return Validation.Fail("SemanticMotion.basis must be a non-empty string");
        if (m.Source.Count == 0 || !m.Source.All(s => !string.IsNullOrEmpty(s.Ref)))
            return Validation.Fail("SemanticMotion must carry ≥1 source with a ref (v7 §6)");
        return Validation.Pass;
    }

    [GeneratedRegex(@"^[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Z.-]+)?(?:\+[0-9A-Z.-]+)?$", RegexOptions.IgnoreCase | RegexOptions.CultureInvariant)]
    private static partial Regex SemVer();

    public static Validation Validate(SkillPackage s)
    {
        if (Blank(s.Name))
            return Validation.Fail("SkillPackage.name must be a non-empty string");
        if (!SemVer().IsMatch(s.Version))
            return Validation.Fail("SkillPackage.version must be a valid semver (e.g. 1.2.3)");
        if (Blank(s.CapabilityRef))
            return Validation.Fail("SkillPackage.capabilityRef must be a non-empty string");
        if (s.Manifest?.Inputs is null || s.Manifest.Outputs is null)
            return Validation.Fail("SkillPackage.manifest must declare inputs and outputs");
        if (s.Source.Count == 0 || !s.Source.All(src => !string.IsNullOrEmpty(src.Ref)))
            return Validation.Fail("SkillPackage must carry ≥1 source with a ref (v7 §6)");
        return Validation.Pass;
    }

    /// <summary>Deterministic, order-independent fingerprint: FNV-1a over "source|takenAt|a|v|d|n|s|c|b".</summary>
    public static string StateSnapshotFingerprint(EndogenousStateVector state, string source, double takenAt) =>
        JsFormat.Fnv1a(string.Join('|', new[]
        {
            source, JsFormat.Number(takenAt), JsFormat.Number(state.Arousal), JsFormat.Number(state.Vigilance), JsFormat.Number(state.Drive),
            JsFormat.Number(state.Novelty), JsFormat.Number(state.Safety), JsFormat.Number(state.CognitiveLoad), JsFormat.Number(state.Boredom),
        }));
}
