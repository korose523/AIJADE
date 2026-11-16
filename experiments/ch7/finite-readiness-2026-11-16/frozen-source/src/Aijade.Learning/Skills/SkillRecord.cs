using System.Text.Json.Nodes;

namespace Aijade.Learning.Skills;

// A skill library that can actually be measured. Each record carries the three RQ-C events — the LLM's self-verification,
// the environment's execution verdict, and whether the environment's feedback drives the lifecycle — plus the call
// counters that make precision computable and the lifecycle that lets skills leave (without which every question about
// the library getting better has no denominator).

public enum SkillDomain
{
    Executable,
    Game,
    Conversation,
    Synthetic,
}

public enum SkillLifecycle
{
    Active,
    Retired,
    Rejected,
}

public enum SkillVerdict
{
    Pass,
    Fail,
}

public enum RetirementReason
{
    LowPrecision,
    Superseded,
    SelfRejected,
    Manual,
}

public sealed record SkillTrigger(string? Rationale = null, double? Confidence = null, string? SessionId = null, int? TurnIndex = null);

public sealed record SelfVerification(SkillVerdict Verdict, bool Enabled, double? Score = null, string? Rationale = null, string? Model = null);

public sealed record ExecutionOutcome(bool Ok, string? Detail = null, double? DurationMs = null);

public sealed record SkillExecution(bool Ok, double ExecutedAt, int Attempt, string? Detail = null, double? DurationMs = null);

public sealed record EnvFeedback(bool Enabled, double? AppliedAt = null);

public sealed record SkillRecord(string SkillId, string Name, double CreatedAt, SkillDomain Domain)
{
    public SkillTrigger? Trigger { get; init; }
    public SelfVerification? SelfVerification { get; init; }
    public SkillExecution? Execution { get; init; }
    public EnvFeedback? EnvFeedback { get; init; }
    public int CallCount { get; init; }
    public int SuccessCount { get; init; }
    public int FailureCount { get; init; }
    public double? LastUsedAt { get; init; }
    public SkillLifecycle Status { get; init; } = SkillLifecycle.Active;
    public double? RetiredAt { get; init; }
    public RetirementReason? RetirementReason { get; init; }
    public string? Body { get; init; }
    public JsonObject? Metadata { get; init; }
}

/// <summary>
/// Library-level counts and rates. The self-verification rates condition on the verdict, as a library dashboard needs them:
/// <c>SelfVerificationHallucinationRate</c> = P(execution fails | self-pass), the share of admitted skills that are broken, and
/// <c>SelfVerificationMissRate</c> = P(execution succeeds | self-fail). They are the predictive values, not the RQ-C estimands
/// of the same names, which condition on the execution outcome (see <c>Aijade.Research.RqC.RqcModels.Diagnostics</c>).
/// </summary>
public sealed record SkillLibraryMetrics(
    int Total, int Active, int Retired, int Rejected, int SelfPass, int SelfFail, int SelfVerificationDisabled, int Executed, int ExecSuccess,
    int ExecFail, double Precision, double MeanCallsPerSkill, double SelfVerificationHallucinationRate, double SelfVerificationMissRate,
    double SelfEnvironmentAgreement, IReadOnlyDictionary<SkillDomain, int> ByDomain);

/// <summary>Deprecated domain × self-verification table: the conversation cells can never have a hallucination rate.</summary>
public sealed record TwoByTwoCell(SkillDomain Domain, bool SelfVerificationEnabled, int Count, double HallucinationRate, double Precision);

/// <summary>One cell of the RQ-C design (self-verification × environment feedback), both varied inside the oracle domains.</summary>
public sealed record LearningLoopCell(bool SelfVerificationEnabled, bool EnvFeedbackEnabled, int Count, double Precision, double RetiredRate, double MeanCallsPerSkill);

public sealed record SelfVerificationDiagnostic(int N, double HallucinationRate, double MissRate, double Agreement);

public static class SkillMetrics
{
    /// <summary>Only executable and game skills have an environment that can say whether they worked.</summary>
    public static bool HasEnvironmentalOracle(SkillDomain d) => d is SkillDomain.Executable or SkillDomain.Game;

    /// <summary>NaN, not 0, when the denominator is empty: a study that executed nothing must not report "0% precision".</summary>
    private static double Ratio(double n, double d) => d == 0 ? double.NaN : n / d;

    public static SkillLibraryMetrics Compute(IReadOnlyList<SkillRecord> records)
    {
        var byDomain = Enum.GetValues<SkillDomain>().ToDictionary(d => d, _ => 0);
        int active = 0, retired = 0, rejected = 0, selfPass = 0, selfFail = 0, svDisabled = 0, executed = 0, execSuccess = 0, execFail = 0;
        int passExecFail = 0, failExecSuccess = 0, passExecuted = 0, failExecuted = 0, agreeNum = 0, agreeDen = 0;
        double totalCalls = 0, successes = 0;
        foreach (var r in records)
        {
            byDomain[r.Domain]++;
            switch (r.Status)
            {
                case SkillLifecycle.Active: active++; break;
                case SkillLifecycle.Retired: retired++; break;
                default: rejected++; break;
            }
            var sv = r.SelfVerification;
            if (sv is not { Enabled: true })
                svDisabled++;
            else if (sv.Verdict == SkillVerdict.Pass)
                selfPass++;
            else
                selfFail++;
            totalCalls += r.CallCount;
            successes += r.SuccessCount;
            if (r.Execution is not { } ex)
                continue;
            executed++;
            if (ex.Ok)
                execSuccess++;
            else
                execFail++;
            if (sv is not { Enabled: true })
                continue;
            // Rates are over skills that were actually executed, not over everything the model judged.
            agreeDen++;
            if ((sv.Verdict == SkillVerdict.Pass) == ex.Ok)
                agreeNum++;
            if (sv.Verdict == SkillVerdict.Pass)
            {
                passExecuted++;
                if (!ex.Ok)
                    passExecFail++;
            }
            else
            {
                failExecuted++;
                if (ex.Ok)
                    failExecSuccess++;
            }
        }
        return new SkillLibraryMetrics(records.Count, active, retired, rejected, selfPass, selfFail, svDisabled, executed, execSuccess, execFail,
            Ratio(successes, totalCalls), Ratio(totalCalls, records.Count), Ratio(passExecFail, passExecuted), Ratio(failExecSuccess, failExecuted),
            Ratio(agreeNum, agreeDen), byDomain);
    }

    [Obsolete("Domain cannot serve as a 2×2 axis: the conversation cells have no oracle. Use LearningLoopTable.")]
    public static IReadOnlyList<TwoByTwoCell> TwoByTwo(IReadOnlyList<SkillRecord> records)
    {
        var cells = new List<TwoByTwoCell>();
        foreach (var domain in new[] { SkillDomain.Game, SkillDomain.Conversation })
        {
            foreach (var enabled in new[] { true, false })
            {
                var subset = records.Where(r => r.Domain == domain && (r.SelfVerification?.Enabled ?? false) == enabled).ToList();
                var m = Compute(subset);
                cells.Add(new TwoByTwoCell(domain, enabled, subset.Count, m.SelfVerificationHallucinationRate, m.Precision));
            }
        }
        return cells;
    }

    /// <summary>The 2×2 over the oracle domains (executable + game pooled by default), cells ordered (sv, ef) = 00, 01, 10, 11.</summary>
    public static IReadOnlyList<LearningLoopCell> LearningLoopTable(IReadOnlyList<SkillRecord> records, SkillDomain? domain = null)
    {
        var target = domain is { } d ? [d] : new[] { SkillDomain.Executable, SkillDomain.Game };
        var filtered = records.Where(r => target.Contains(r.Domain)).ToList();
        var cells = new List<LearningLoopCell>();
        foreach (var sv in new[] { false, true })
        {
            foreach (var ef in new[] { false, true })
            {
                var subset = filtered.Where(r => (r.SelfVerification?.Enabled ?? false) == sv && (r.EnvFeedback?.Enabled ?? false) == ef).ToList();
                var m = Compute(subset);
                cells.Add(new LearningLoopCell(sv, ef, subset.Count, m.Precision, Ratio(m.Retired, subset.Count), m.MeanCallsPerSkill));
            }
        }
        return cells;
    }

    /// <summary>Hallucination / miss / agreement over records that have both a self-verdict and an execution.</summary>
    public static SelfVerificationDiagnostic SelfVerificationDiagnostics(IReadOnlyList<SkillRecord> records)
    {
        var subset = records.Where(r => r.SelfVerification is { Enabled: true } && r.Execution is not null).ToList();
        var m = Compute(subset);
        return new SelfVerificationDiagnostic(subset.Count, m.SelfVerificationHallucinationRate, m.SelfVerificationMissRate, m.SelfEnvironmentAgreement);
    }
}
