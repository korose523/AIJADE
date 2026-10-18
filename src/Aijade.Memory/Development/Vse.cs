using System.Text;

using Aijade.Memory.Contracts;
using Aijade.Core.Js;

namespace Aijade.Memory.Development;

// v8 §51 VSE, Verified Self-Evolution: strategies, workflows, skills and non-critical code may improve, but only through
// proposal → sandbox → evaluation → signed release → rollback, never by rewriting the trusted core directly. The E0–E5
// grading is the hard boundary: E1–E3 may be optimised, E4 needs human review, E5 (safety constitution, keys, audit,
// release root) is never touched. Pure and deterministic; the release controller lives in the runtime layer.

public enum EvolutionGrade
{
    E0,
    E1,
    E2,
    E3,
    E4,
    E5,
}

public enum AutomationLevel
{
    /// <summary>E0: automatic, short-lived.</summary>
    Auto,
    /// <summary>E1: auto-propose, enable after offline evaluation.</summary>
    AutoProposeOfflineEval,
    /// <summary>E2: sandbox test, sign, canary.</summary>
    SandboxSignGray,
    /// <summary>E3: full test plus review / pre-authorisation, then release.</summary>
    FullTestReview,
    /// <summary>E4: no autonomous modification; human review.</summary>
    HumanReviewRequired,
    /// <summary>E5: never modifiable by the agent.</summary>
    Forbidden,
}

/// <summary>The §51.3 pipeline stages followed by the two terminal outcomes.</summary>
public enum EvolutionStage
{
    CapabilityGap,
    ReproducibleIssue,
    RootCauseHypotheses,
    ChangeSpecification,
    CandidatePatch,
    StaticAnalysis,
    DependencyLicenseScan,
    UnitContractPropertyTests,
    SecuritySandbox,
    HistoricalReplay,
    AdversarialEvaluation,
    BenchmarkComparison,
    ShadowMode,
    CanaryRelease,
    SignedPromotion,
    RuntimeMonitoring,
    Kept,
    RolledBack,
}

public enum EvolutionEvent
{
    Advance,
    Keep,
    Rollback,
}

public sealed record CandidateVersion(
    string Id, double DeltaQuality, double DeltaLatency, double DeltaCost, double Risk, double Complexity, double Drift,
    double Safety, double BaselineSafety, bool CoreInvariantsHold, bool RollbackAvailable);

public sealed record VseRoutingIdentity(string? UserId = null, string? SessionId = null);

public enum RoutingIdentityKind
{
    User,
    Session,
}

/// <summary>A routing decision at a service entry point; <see cref="Bucket"/> ∈ [0, 1) is compared with the canary ratio.</summary>
public sealed record VseRouteDecision(string TraceId, double Bucket, double CanaryRatio, bool Eligible, RoutingIdentityKind IdentityKind, string? ReleaseId = null, string? Version = null);

public sealed record EvolutionWeights(double AlphaLatency = 1, double BetaCost = 1, double GammaRisk = 2, double EtaComplexity = 0.5, double KappaDrift = 1.5)
{
    public static EvolutionWeights Default { get; } = new();
}

public static class Vse
{
    /// <summary>§51.1 the automation ceiling of each grade.</summary>
    public static AutomationLevel AutomationAllowed(EvolutionGrade grade) => (AutomationLevel)(int)grade;

    /// <summary>§51.1 whether the agent may autonomously change an object of this grade (not E4, never E5).</summary>
    public static Validation AssertEvolvable(EvolutionGrade grade) => grade switch
    {
        EvolutionGrade.E5 => Validation.Fail("E5 (safety constitution / keys / audit / release root) can never be modified by the agent (v8 §51.1)"),
        EvolutionGrade.E4 => Validation.Fail("E4 (core orchestration / memory transactions / identity constraints / permissions) requires human review; no autonomous direct modification (v8 §51.1)"),
        _ => Validation.Pass,
    };

    /// <summary>§51.3 pipeline: advance moves forward; from RuntimeMonitoring keep commits, rollback is allowed anywhere. Illegal → null.</summary>
    public static EvolutionStage? NextStage(EvolutionStage current, EvolutionEvent e)
    {
        if (current is EvolutionStage.Kept or EvolutionStage.RolledBack)
            return null;
        return e switch
        {
            EvolutionEvent.Rollback => EvolutionStage.RolledBack,
            EvolutionEvent.Keep => current == EvolutionStage.RuntimeMonitoring ? EvolutionStage.Kept : null,
            _ => current == EvolutionStage.RuntimeMonitoring ? null : current + 1,
        };
    }

    /// <summary>§51.3 promotion gate: the core test gate is mandatory; every optional gate present must also pass.</summary>
    public static Validation CanPromote(EvaluationEvidencePack pack)
    {
        if (!pack.UnitContractPropertyTests.Passed)
            return Validation.Fail("core unit/contract/property tests did not pass");
        if (pack.StaticAnalysis is { Passed: false })
            return Validation.Fail("static analysis failed");
        if (pack.DependencyLicenseScan is { Passed: false })
            return Validation.Fail("dependency/license scan failed");
        if (pack.SecuritySandbox is { Passed: false })
            return Validation.Fail("security sandbox reported escapes");
        if (pack.HistoricalReplay is { Passed: false })
            return Validation.Fail("historical replay showed regressions");
        if (pack.AdversarialEval is { Passed: false })
            return Validation.Fail("adversarial evaluation found issues");
        return Validation.Pass;
    }

    /// <summary>Stable FNV-1a bucket over the UTF-8 bytes of "namespace:user:id" (or session); no randomness, so retries keep their lane.</summary>
    public static double StableBucket(VseRoutingIdentity identity, string ns = "aijade-vse")
    {
        var user = identity.UserId is null ? "" : JsText.Trim(identity.UserId);
        var session = identity.SessionId is null ? "" : JsText.Trim(identity.SessionId);
        var value = user.Length > 0 ? $"user:{user}" : session.Length > 0 ? $"session:{session}" : "";
        if (value.Length == 0)
            throw new ArgumentException("VSE routing requires a userId or sessionId", nameof(identity));
        var hash = 2166136261u;
        foreach (var b in Encoding.UTF8.GetBytes($"{ns}:{value}"))
        {
            hash ^= b;
            hash = unchecked(hash * 16777619u);
        }
        return hash / 4294967296.0;
    }

    /// <summary>§51.4 ΔQuality − αΔLatency − βΔCost − γRisk − ηComplexity − κDrift.</summary>
    public static double Objective(CandidateVersion c, EvolutionWeights? weights = null)
    {
        var w = weights ?? EvolutionWeights.Default;
        return c.DeltaQuality - (w.AlphaLatency * c.DeltaLatency) - (w.BetaCost * c.DeltaCost) - (w.GammaRisk * c.Risk)
            - (w.EtaComplexity * c.Complexity) - (w.KappaDrift * c.Drift);
    }

    /// <summary>§51.4 hard constraints: Safety(v') ≥ Safety(v) ∧ core invariants hold ∧ rollback available.</summary>
    public static bool SatisfiesConstraints(CandidateVersion c) => c.Safety >= c.BaselineSafety && c.CoreInvariantsHold && c.RollbackAvailable;

    /// <summary>The highest-objective feasible candidate, or null (keep the baseline rather than force a bad change).</summary>
    public static CandidateVersion? SelectCandidate(IEnumerable<CandidateVersion> candidates, EvolutionWeights? weights = null)
    {
        CandidateVersion? best = null;
        var bestScore = double.NegativeInfinity;
        foreach (var c in candidates)
        {
            if (!SatisfiesConstraints(c))
                continue;
            var score = Objective(c, weights);
            if (score > bestScore)
            {
                bestScore = score;
                best = c;
            }
        }
        return best;
    }
}
