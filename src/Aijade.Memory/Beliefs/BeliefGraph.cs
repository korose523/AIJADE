using Aijade.Core.Js;

namespace Aijade.Memory.Beliefs;

// DGM belief graph (v7 §10.2, contract #5). Beliefs change only through evidence transactions
//   logit P(h|E) = logit P(h) + Σ r_k · ℓ_k   (counter-evidence subtracted),
// with r and ℓ clamped deterministically so an LLM-proposed likelihood can never exceed the validator's bound.

public enum BeliefStatus
{
    Hypothesis,
    Accepted,
    Contested,
    Retracted,
}

public enum BeliefOwner
{
    User,
    Agent,
    World,
}

public sealed record BeliefConfig(
    double AcceptThreshold = 0.65, double RetractThreshold = 0.2, double ContestedRatio = 0.5, double MaxAbsLikelihood = 2, double PriorConfidence = 0.5)
{
    public static BeliefConfig Default { get; } = new();
}

/// <summary>One evidence item; <see cref="Likelihood"/> may be model-proposed.</summary>
public sealed record EvidenceEntry(string Id, double Reliability, double Likelihood);

public sealed record Belief(
    string Id, string Proposition, string Scope, double Confidence, double Logit, IReadOnlyList<string> EvidenceIds,
    IReadOnlyList<string> CounterEvidenceIds, double ValidFrom, double? ValidTo, BeliefStatus Status, BeliefOwner Owner,
    double CreatedAt, double UpdatedAt, double SupportLogit, double CounterLogit);

/// <summary>Contract #5 — an auditable belief update.</summary>
public sealed record BeliefRevision(
    string Id, string BeliefId, double At, IReadOnlyList<string> EvidenceIds, IReadOnlyList<string> CounterEvidenceIds, double DeltaLogit,
    double LogitBefore, double LogitAfter, double ConfidenceBefore, double ConfidenceAfter, IReadOnlyList<double> SourceReliabilities,
    bool Clamped, string Rationale, string Actor);

/// <summary>A refused candidate, recorded so source traceability is measurable.</summary>
public sealed record BeliefRejection(string Proposition, string Reason, double At, string Actor);

public sealed record RevisionDelta(double Delta, double Support, double Counter, IReadOnlyList<double> Reliabilities, bool Clamped, string Rationale);

public static class BeliefMath
{
    public static double Clamp(double x, double min, double max) => Math.Min(max, Math.Max(min, x));

    /// <summary>Numerically stable logistic.</summary>
    public static double Sigmoid(double z)
    {
        if (z >= 0)
            return 1 / (1 + Math.Exp(-z));
        var e = Math.Exp(z);
        return e / (1 + e);
    }

    public static double Logit(double p)
    {
        var q = Clamp(p, 1e-9, 1 - 1e-9);
        return Math.Log(q / (1 - q));
    }

    /// <summary>Σ r·ℓ for support minus counter; support ℓ ∈ [−max, max], counter ℓ is a magnitude in [0, max].</summary>
    public static RevisionDelta Delta(IReadOnlyList<EvidenceEntry> evidence, IReadOnlyList<EvidenceEntry> counterEvidence, BeliefConfig cfg)
    {
        var reliabilities = new List<double>();
        var notes = new List<string>();
        var clamped = false;
        double support = 0, counter = 0;
        void Note(EvidenceEntry e, double r, double l) =>
            notes.Add($"clamped {e.Id}: r={JsFormat.Number(e.Reliability)}->{JsFormat.Number(r)}, l={JsFormat.Number(e.Likelihood)}->{JsFormat.Number(l)}");
        foreach (var e in evidence)
        {
            var r = Clamp(e.Reliability, 0, 1);
            var l = Clamp(e.Likelihood, -cfg.MaxAbsLikelihood, cfg.MaxAbsLikelihood);
            if (r != e.Reliability || l != e.Likelihood)
            {
                clamped = true;
                Note(e, r, l);
            }
            reliabilities.Add(r);
            support += r * l;
        }
        foreach (var e in counterEvidence)
        {
            var r = Clamp(e.Reliability, 0, 1);
            var l = Clamp(e.Likelihood, 0, cfg.MaxAbsLikelihood);
            if (r != e.Reliability || l != e.Likelihood)
            {
                clamped = true;
                Note(e, r, l);
            }
            reliabilities.Add(r);
            counter += r * l;
        }
        return new RevisionDelta(support - counter, support, counter, reliabilities, clamped, string.Join("; ", notes));
    }

    public static BeliefStatus NextStatus(double confidence, double supportLogit, double counterLogit, BeliefConfig cfg)
    {
        if (confidence <= cfg.RetractThreshold)
            return BeliefStatus.Retracted;
        var total = Math.Abs(supportLogit) + Math.Abs(counterLogit);
        var counterShare = total > 0 ? Math.Abs(counterLogit) / total : 0;
        if (counterShare >= cfg.ContestedRatio)
            return BeliefStatus.Contested;
        return confidence >= cfg.AcceptThreshold ? BeliefStatus.Accepted : BeliefStatus.Hypothesis;
    }

    /// <summary>Create a belief at the prior. Callers must already have checked that a source exists.</summary>
    public static Belief Create(
        string id, string proposition, IReadOnlyList<string> evidenceIds, double at, BeliefConfig cfg, string? scope = null,
        BeliefOwner owner = BeliefOwner.Agent, double? validFrom = null, double? validTo = null)
    {
        var prior = Clamp(cfg.PriorConfidence, 1e-9, 1 - 1e-9);
        return new Belief(id, proposition, scope ?? "global", prior, Logit(prior), [.. evidenceIds], [], validFrom ?? at, validTo,
            NextStatus(prior, 0, 0, cfg), owner, at, at, 0, 0);
    }

    /// <summary>Apply one evidence transaction. Pure.</summary>
    public static (Belief Belief, BeliefRevision Revision) Apply(
        Belief belief, string revisionId, double at, string actor, BeliefConfig cfg,
        IReadOnlyList<EvidenceEntry>? evidence = null, IReadOnlyList<EvidenceEntry>? counterEvidence = null, string? rationale = null)
    {
        evidence ??= [];
        counterEvidence ??= [];
        var d = Delta(evidence, counterEvidence, cfg);
        var logitAfter = belief.Logit + d.Delta;
        var confidenceAfter = Clamp(Sigmoid(logitAfter), 1e-9, 1 - 1e-9);
        var support = belief.SupportLogit + d.Support;
        var counter = belief.CounterLogit + d.Counter;
        var next = belief with
        {
            Logit = logitAfter,
            Confidence = confidenceAfter,
            SupportLogit = support,
            CounterLogit = counter,
            Status = NextStatus(confidenceAfter, support, counter, cfg),
            EvidenceIds = [.. belief.EvidenceIds, .. evidence.Select(e => e.Id)],
            CounterEvidenceIds = [.. belief.CounterEvidenceIds, .. counterEvidence.Select(e => e.Id)],
            UpdatedAt = at,
        };
        var revision = new BeliefRevision(revisionId, belief.Id, at, evidence.Select(e => e.Id).ToList(), counterEvidence.Select(e => e.Id).ToList(),
            d.Delta, belief.Logit, logitAfter, belief.Confidence, confidenceAfter, d.Reliabilities, d.Clamped,
            string.Join(" | ", new[] { rationale, d.Rationale }.Where(s => !string.IsNullOrEmpty(s))), actor);
        return (next, revision);
    }

    /// <summary>Explicit retraction — never a silent overwrite; the entry stays auditable.</summary>
    public static (Belief Belief, BeliefRevision Revision) Retract(Belief belief, string revisionId, double at, string actor, string reason)
    {
        var next = belief with { Status = BeliefStatus.Retracted, ValidTo = at, UpdatedAt = at };
        var revision = new BeliefRevision(revisionId, belief.Id, at, [], [], 0, belief.Logit, belief.Logit, belief.Confidence, belief.Confidence,
            [], false, $"retracted: {reason}", actor);
        return (next, revision);
    }
}
