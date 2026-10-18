using Aijade.Core.Js;
using Aijade.Core.Random;
using Aijade.Memory.Beliefs;
using Aijade.Memory.Contracts;
using Aijade.Memory.Experiments;
using Aijade.Memory.Hac;
using Aijade.Memory.Identity;
using Aijade.Memory.Interventions;
using Aijade.Memory.Model;
using Aijade.Memory.Replay;
using Aijade.Memory.Storage;

namespace Aijade.Memory;

// The opt-in subsystems of the store: the v7 §10.2 belief graph, the §9 HAC + §11 CDI closed loop,
// the §38 intervention API, the §12 CBR replay log and §26 storage. None of them touches durability or salience.

public sealed record BeliefProposal(
    string Proposition, IReadOnlyList<string> EvidenceIds, string? Id = null, string? Scope = null, BeliefOwner Owner = BeliefOwner.Agent,
    double? ValidFrom = null, double? ValidTo = null, string Actor = "agent");

/// <summary>Feedback mapped onto one identity parameter (§11.3).</summary>
public sealed record IdentityFeedbackOptions(
    string EpisodeId, IdentityLayer Layer, string ParamKey, double DeltaValue, IdentitySource? ProposedBy = null, bool ExplicitUpgrade = false,
    string? Justification = null, bool Traceable = true);

public sealed partial class BioticMemory
{
    private HacController? _hac;
    private int _hacCall;
    private IdentityController? _identity;
    private StateSnapshot? _lastHacSnapshot;
    private ResolvedIntervention? _intervention;
    private readonly ReplayLog? _replayLog;
    private readonly IStorageAdapter? _storage;

    public List<Belief> Beliefs { get; } = [];
    public List<BeliefRevision> BeliefRevisions { get; } = [];

    /// <summary>Rejected belief candidates, kept so source traceability stays measurable (§6).</summary>
    public List<BeliefRejection> BeliefRejections { get; } = [];

    /// <param name="config">The store configuration; opt-in subsystems are constructed only when enabled.</param>
    /// <param name="now">The store clock in Unix milliseconds.</param>
    public BioticMemory(MemoryConfig? config = null, double? now = null)
    {
        Config = config ?? MemoryConfig.Default;
        Now = now ?? DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        if (Config.Hac is { Enabled: true } hac)
        {
            _hac = new HacController(hac);
            // CDI belongs to the same closed loop: it exists only when the loop is enabled.
            _identity = new IdentityController(Config.Cdi ?? CdiConfig.Default);
        }
        if (Config.Intervention is { Enabled: true, Plan: { } plan } iv)
            _intervention = Interventions.Interventions.Resolve(plan, iv.Seed);
        _replayLog = Config.Cbr is { Enabled: true } ? new ReplayLog() : null;
        // §26: with an adapter configured, a fresh instance resumes exactly where a previous one left off.
        _storage = Config.Storage;
        if (_storage?.Load() is { } restored)
            Hydrate(restored);
    }

    /// <summary>A seeded RNG per HAC call, (now + call) mod 2^32, so the degradation noise is reproducible.</summary>
    private Func<double> HacRng() => new Mulberry32(JsFormat.ToUint32(Now + _hacCall++)).AsFunc();

    // ---------- v7 §10.2 belief graph ----------

    /// <summary>A candidate with no source never enters the belief graph (v7 §6); the rejection is recorded, not thrown.</summary>
    public (bool Ok, Belief? Belief, string? Reason) ProposeBelief(BeliefProposal input)
    {
        if (input.EvidenceIds.Count == 0)
        {
            BeliefRejections.Add(new BeliefRejection(input.Proposition, "no source: v7 §6 forbids sourceless entries in the belief graph", Now, input.Actor));
            Flush();
            return (false, null, "no source: a belief requires at least one evidence id");
        }
        var belief = BeliefMath.Create(input.Id ?? $"belief_{Beliefs.Count}_{JsFormat.Number(Now)}", input.Proposition, input.EvidenceIds, Now, Config.Belief,
            input.Scope, input.Owner, input.ValidFrom, input.ValidTo);
        Beliefs.Add(belief);
        Flush();
        return (true, belief, null);
    }

    /// <summary>Apply an evidence transaction; counter-evidence is subtracted.</summary>
    public (bool Ok, Belief? Belief, BeliefRevision? Revision, string? Reason) ReviseBelief(
        string beliefId, IReadOnlyList<EvidenceEntry>? evidence = null, IReadOnlyList<EvidenceEntry>? counterEvidence = null, string actor = "agent", string? rationale = null)
    {
        var idx = Beliefs.FindIndex(b => b.Id == beliefId);
        if (idx < 0)
            return (false, null, null, $"belief not found: {beliefId}");
        var (belief, revision) = BeliefMath.Apply(Beliefs[idx], $"rev_{BeliefRevisions.Count}_{beliefId}", Now, actor, Config.Belief, evidence, counterEvidence, rationale);
        Beliefs[idx] = belief;
        BeliefRevisions.Add(revision);
        Flush();
        return (true, belief, revision, null);
    }

    /// <summary>Explicit retraction — never a silent overwrite (v7 §10.4).</summary>
    public (bool Ok, Belief? Belief, BeliefRevision? Revision, string? Reason) RetractBelief(string beliefId, string reason, string actor = "user")
    {
        var idx = Beliefs.FindIndex(b => b.Id == beliefId);
        if (idx < 0)
            return (false, null, null, $"belief not found: {beliefId}");
        var (belief, revision) = BeliefMath.Retract(Beliefs[idx], $"rev_{BeliefRevisions.Count}_{beliefId}", Now, actor, reason);
        Beliefs[idx] = belief;
        BeliefRevisions.Add(revision);
        Flush();
        return (true, belief, revision, null);
    }

    /// <summary>Beliefs usable now: not retracted and inside their validity window.</summary>
    public IReadOnlyList<Belief> ActiveBeliefs(BeliefOwner? owner = null) =>
        Beliefs.Where(b => b.Status != BeliefStatus.Retracted && (owner is null || b.Owner == owner) && (b.ValidTo is not { } to || Now <= to)).ToList();

    // ---------- v7 §9 HAC (opt-in) ----------

    /// <summary>Advance z_t from a stimulus and an action; a no-op when HAC is disabled.</summary>
    public void StepHac(HacState stimulus, HacState action)
    {
        if (_hac is null)
            return;
        _hac.Step(stimulus, action, HacRng());
        Flush();
    }

    /// <summary>The current endogenous state, or null when HAC is disabled.</summary>
    public HacState? HacState => _hac?.State;

    /// <summary>The §9.3 write decision for a candidate; null when HAC is disabled (callers use the content-salience path).</summary>
    public WriteDecision? HacWriteDecision(UtilityFeatures f, WriteConstraints constraints) => _hac?.Decide(f, constraints);

    /// <summary>
    /// Advance z_t from an appraisal (§9.1) through the stimulus channel only, and keep a frozen snapshot so the HAC → CDI
    /// bridge can use it as evidence.
    /// </summary>
    public void StepHacAppraisal(Appraisal appraisal)
    {
        if (_hac is null)
            return;
        _hac.StepAppraisal(appraisal, HacRng());
        _lastHacSnapshot = _hac.Snapshot("hac", Now, appraisal.AgentId, appraisal.UserScope);
        Flush();
    }

    /// <summary>A frozen, content-addressed snapshot of z_t (§25 #3); null when HAC is disabled.</summary>
    public StateSnapshot? HacSnapshot(double? takenAt = null, string agentId = "", string userScope = "") =>
        _hac?.Snapshot("hac", takenAt ?? Now, agentId, userScope);

    // ---------- v7 §11 CDI (part of the closed loop) ----------

    /// <summary>A candidate from feedback, not committed, for shadow evaluation; null when the loop is disabled.</summary>
    public IdentityCandidate? CdiProposalFromFeedback(FeedbackEvent feedback, IdentityFeedbackOptions o) =>
        _identity is null ? null : Cdi.CandidateFromFeedback(feedback, o.EpisodeId, o.Layer, o.ParamKey, o.DeltaValue, o.ProposedBy ?? IdentitySource.World, o.ExplicitUpgrade, o.Justification, o.Traceable);

    /// <summary>Validate, solve and (if admissible) commit a feedback-derived identity change; null when the loop is disabled.</summary>
    public (IdentityVersion? Version, SolveResult Result)? CdiFromFeedback(FeedbackEvent feedback, IdentityFeedbackOptions o)
    {
        if (_identity is null)
            return null;
        var candidate = CdiProposalFromFeedback(feedback, o)!;
        var result = _identity.Apply(candidate, o.ProposedBy ?? candidate.ProposedBy);
        Flush();
        return result;
    }

    public IdentityState? CdiState => _identity?.State;

    public IReadOnlyList<IdentityVersion>? CdiVersions => _identity?.History;

    /// <summary>Roll back to a prior signed version (§11.3); null when the loop is disabled.</summary>
    public IdentityVersion? CdiRollback(string signature)
    {
        if (_identity is null)
            return null;
        var v = _identity.RollbackTo(signature);
        Flush();
        return v;
    }

    /// <summary>The latest HAC snapshot as world-observation evidence for CDI (never a write); null without loop or snapshot.</summary>
    public IdentityEvidence? CdiObserveHac(string episodeId, bool traceable = true) =>
        _identity is null || _lastHacSnapshot is null ? null : Cdi.EvidenceFromSnapshot(_lastHacSnapshot, episodeId, traceable);

    // ---------- v7 §38 intervention API (opt-in) ----------

    /// <summary>
    /// Resolve a plan as this instance's current configuration; with a registry, also register it as a §38 manifest.
    /// Null when the intervention API is not enabled. Describes the configuration only — never changes memory dynamics.
    /// </summary>
    public (ResolvedIntervention Resolved, RegisteredIntervention? Registered)? ApplyIntervention(
        InterventionPlan plan, double? seed = null, ExperimentRegistry? registry = null, IReadOnlyList<string>? metrics = null)
    {
        if (Config.Intervention is not { Enabled: true } iv)
            return null;
        var s = seed ?? iv.Seed;
        _intervention = Interventions.Interventions.Resolve(plan, s);
        Flush();
        return (_intervention, registry is null ? null : Interventions.Interventions.Register(plan, registry, s, metrics));
    }

    public ResolvedIntervention? InterventionResolved => _intervention;

    /// <summary>Whether a point is on; without a resolved plan the defaults apply, and unknown points are off.</summary>
    public bool InterventionEnabled(string pointId) =>
        _intervention?.IsEnabled(pointId) ?? Interventions.Interventions.DefaultSwitches.GetValueOrDefault(pointId);

    public string? InterventionBypass(string pointId) => _intervention?.BypassOf(pointId);

    public string? InterventionFingerprint => _intervention?.Fingerprint;

    // ---------- v7 §12 CBR replay (opt-in) ----------

    /// <summary>Log a replay bundle (append-only); null when CBR is not enabled.</summary>
    public Validation? CbrLogBundle(ReplayBundle b)
    {
        if (_replayLog is null)
            return null;
        var r = _replayLog.Add(b);
        if (r.Ok)
            Flush();
        return r;
    }

    public ReplayBundle? CbrGetBundle(string bundleId) => _replayLog?.Get(bundleId);

    public IReadOnlyList<ReplayBundle> CbrBundles => _replayLog?.All() ?? [];

    /// <summary>
    /// Paired ITE over logged bundles. The outcomes come from the caller (who ran each bundle through a policy); ids not in
    /// the log are ignored. Null when CBR is not enabled.
    /// </summary>
    public IteEstimate? CbrEstimateIte(IReadOnlyDictionary<string, double> treatedOutcomes, IReadOnlyDictionary<string, double> controlOutcomes)
    {
        if (_replayLog is null)
            return null;
        List<ReplayRun> Runs(IReadOnlyDictionary<string, double> map) =>
            map.Where(kv => _replayLog.Get(kv.Key) is not null).Select(kv => new ReplayRun(_replayLog.Get(kv.Key)!, kv.Value)).ToList();
        return Cbr.EstimateIte(Cbr.Pair(Runs(treatedOutcomes), Runs(controlOutcomes)).Pairs);
    }

    // ---------- v7 §26 storage (opt-in) ----------

    /// <summary>A snapshot of all state; HAC / CDI / intervention / CBR parts only when those subsystems exist.</summary>
    public StoreSnapshot ToSnapshot() => new(
        StoreSnapshot.SchemaId,
        Config with { Storage = null },
        new StoreCollections([.. Episodes], [.. Facts], [.. Procedural], [.. Working], [.. Beliefs], [.. BeliefRevisions], [.. BeliefRejections]),
        _hac is null ? null : new HacSnapshotState(_hac.State, _hacCall),
        _identity is null ? null : new CdiSnapshotState(_identity.State, _identity.History),
        _intervention,
        _replayLog?.All());

    /// <summary>Persist through the configured adapter (no-op without one).</summary>
    public void Save() => _storage?.Persist(ToSnapshot());

    private void Flush() => _storage?.Persist(ToSnapshot());

    /// <summary>Restore every collection and the subsystem state from a snapshot; never decides retention, only carries it.</summary>
    private void Hydrate(StoreSnapshot s)
    {
        Episodes.Clear();
        Episodes.AddRange(s.Collections.Episodes);
        Facts.Clear();
        Facts.AddRange(s.Collections.Facts);
        Procedural.Clear();
        Procedural.AddRange(s.Collections.Procedural);
        Working.Clear();
        Working.AddRange(s.Collections.Working);
        Beliefs.Clear();
        Beliefs.AddRange(s.Collections.Beliefs);
        BeliefRevisions.Clear();
        BeliefRevisions.AddRange(s.Collections.BeliefRevisions);
        BeliefRejections.Clear();
        BeliefRejections.AddRange(s.Collections.BeliefRejections);
        if (s.Hac is { } h && Config.Hac is { Enabled: true } hac)
            _hac = new HacController(hac, h.Z);
        _hacCall = s.Hac?.Call ?? 0;
        if (s.Cdi is { } c && Config.Hac is { Enabled: true })
            _identity = new IdentityController(Config.Cdi ?? CdiConfig.Default, c.State, history: c.Versions);
        if (s.Intervention is { } iv && Config.Intervention is { Enabled: true })
            _intervention = iv;
        if (s.CbrBundles is { } bundles && _replayLog is not null)
        {
            foreach (var b in bundles)
                _replayLog.Add(b);
        }
        _index = null;
    }
}
