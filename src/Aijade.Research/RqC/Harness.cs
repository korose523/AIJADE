using System.Text.Json.Nodes;

using Aijade.Learning.Skills;
using Aijade.Research.SkillBench;
using Aijade.Research.Statistics;

namespace Aijade.Research.RqC;

// The RQ-C 2×2 experiment: self-verification × environment feedback, inside the executable (oracle) domain. Each
// (condition, trial) runs its own skill registry over the same block-sampled tasks for several rounds; a skill is reused
// while active and regenerated once it has failed its way out, and the accumulated evidence is fed back only through the
// channels the condition owns. The analysis unit is the skill, never the execution (re-used skills are correlated).

/// <summary>
/// The protocol of the RQ-C runs, fixed in this code before the runs and not registered on an external platform. The class
/// and the summary field <c>preregistrationDeviation</c> keep their original names so that archived summaries stay
/// comparable. Not tuning knobs; any deviation is reported loudly.
/// </summary>
public static class Preregistration
{
    public const int Trials = 30;
    public const int Rounds = 5;
    public const int NTasks = 12;
    public const double PruneThreshold = 0.5;
    public const int PruneMinCalls = 3;
    public const uint Seed = 42;
}

public sealed record Condition(bool SelfVerification, bool EnvFeedback)
{
    public string Id => RqcAnalysis.ConditionId(SelfVerification, EnvFeedback);

    /// <summary>Canonical order, matching the learning-loop table cells.</summary>
    public static IReadOnlyList<Condition> All { get; } = [new(false, false), new(false, true), new(true, false), new(true, true)];
}

public sealed record HarnessStep(
    string Condition, int Trial, int Round, string TaskId, string SkillId, bool Reused, int Attempt, bool HadEnvFeedback, bool HadSelfCritique,
    bool RegeneratedFromFailure, bool? SelfVerdictPass, bool ExecOk, double DurationMs)
{
    /// <summary>The executed code (extracted from the generation, or the reused skill's body). Not part of trials.jsonl.</summary>
    public string? Code { get; init; }

    /// <summary>The model's raw generation when this step generated one. Not part of trials.jsonl.</summary>
    public string? Generation { get; init; }

    /// <summary>The self-verification rationale when this step ran one. Not part of trials.jsonl.</summary>
    public string? SelfRationale { get; init; }

    /// <summary>The verifier's whole reply when it is longer than the rationale (audit only). Not part of trials.jsonl.</summary>
    public string? SelfReply { get; init; }
}

public sealed record RunOptions(
    ILlmBackend Backend, int Trials, int Rounds, uint Seed, int NTasks, Sandbox Sandbox, double? PruneThreshold = null, int? PruneMinCalls = null,
    Func<double>? Now = null, Action<HarnessStep>? OnStep = null);

/// <summary>
/// Regenerations of a failed task, how many carried a signal, how many recovered, and how many recovered with code that differs
/// from the task's previous code (the causal channel: an unchanged candidate that passes was only rejected by the self-verifier).
/// </summary>
public sealed record LoopDiagnostics(int Regenerations, int RegenerationsWithSignal, int Recoveries, double RecoveredRate, int RecoveriesWithChangedCode = 0);

public sealed record ConditionResult(Condition Condition, IReadOnlyList<SkillRecord> Records, LoopDiagnostics Loop);

/// <summary>The constructive-null guard: identical cells or an inert loop mean the run says nothing about the 2×2.</summary>
public sealed record DegeneracyCheck(bool AllCellsIdenticalPrecision, int TotalRegenerations, int TotalRecoveries, double RecoveredRate, bool ManipulationReachable, string Note,
    int? TotalRecoveriesWithChangedCode = null);

public sealed record CellPrecision(bool Sv, bool Ef, IReadOnlyList<SkillCount> Skills);

public sealed record EffectSizes(double OddsRatio, double RiskDifference, double CramersV, double CohensH, LogOddsInteractionResult InteractionLogOdds);

public sealed record PowerDeclaration(double MinDetectableEffectAt80, int NSkillsPerCell, double PowerAtDelta10pp, double PowerAtDelta5pp);

public sealed record ExperimentResult(
    IReadOnlyList<ConditionResult> Conditions, IReadOnlyList<LearningLoopCell> Table, SelfVerificationDiagnostic Diagnostics,
    IReadOnlyList<(bool Sv, bool Ef, ConfidenceInterval Ci)> PerCellCi, int NSkills, int NExecutions, EffectSizes EffectSizes,
    IReadOnlyList<HolmStep> Multiplicity, LogOddsInteractionResult FactorialInteraction, ChiSquareResult ChiSquare, ChiSquareResult ChiSquareSelfVerification,
    ChiSquareResult ChiSquareExecutionLevel, McNemarResult McNemarEnvFeedback, PowerDeclaration Power, IReadOnlyList<string> PreregistrationDeviation,
    DegeneracyCheck Degeneracy, DidResult DiffInDiff, IReadOnlyList<CellPrecision> Cells)
{
    public const string AnalysisUnit = "skill";
}

public static class Harness
{
    /// <summary>Mixed into the trial sampling seed so task selection depends on the trial only (block design).</summary>
    private const int BlockLabel = 0xC0FFEE;

    private static string N(double x) => Aijade.Core.Js.JsFormat.Number(x);

    public static IReadOnlyList<string> ValidatePreregistration(RunOptions o)
    {
        var d = new List<string>();
        void Check(string key, double actual, double expected)
        {
            if (actual != expected)
                d.Add($"{key}: run={N(actual)} preregistered={N(expected)}");
        }
        Check("trials", o.Trials, Preregistration.Trials);
        Check("rounds", o.Rounds, Preregistration.Rounds);
        Check("nTasks", o.NTasks, Preregistration.NTasks);
        Check("pruneThreshold", o.PruneThreshold ?? Preregistration.PruneThreshold, Preregistration.PruneThreshold);
        Check("pruneMinCalls", o.PruneMinCalls ?? Preregistration.PruneMinCalls, Preregistration.PruneMinCalls);
        Check("seed", o.Seed, Preregistration.Seed);
        return d;
    }

    /// <summary>A skill's binary outcome: success iff successes / calls ≥ 0.5.</summary>
    private static bool SkillSuccess(SkillRecord r) => r.CallCount > 0 && (double)r.SuccessCount / r.CallCount >= 0.5;

    private static bool Sv(SkillRecord r) => r.SelfVerification?.Enabled ?? false;

    private static bool Ef(SkillRecord r) => r.EnvFeedback?.Enabled ?? false;

    /// <summary>JavaScript Math.round (half toward +∞).</summary>
    private static double JsRound(double x) => Math.Floor(x + 0.5);

    public static async Task<ExperimentResult> RunAsync(RunOptions o, CancellationToken cancellationToken = default)
    {
        var pruneThreshold = o.PruneThreshold ?? Preregistration.PruneThreshold;
        var pruneMinCalls = o.PruneMinCalls ?? Preregistration.PruneMinCalls;
        var now = o.Now ?? (() => 0);
        var deviation = ValidatePreregistration(o);

        var trialTasks = Enumerable.Range(0, o.Trials).Select(t => Bench.SampleTasks(o.NTasks, RqcAnalysis.DeriveSeed(o.Seed, BlockLabel, t))).ToList();
        var conditions = new List<ConditionResult>();
        foreach (var cond in Condition.All)
            conditions.Add(await RunConditionAsync(cond, o, pruneThreshold, pruneMinCalls, now, trialTasks, cancellationToken).ConfigureAwait(false));
        var all = conditions.SelectMany(c => c.Records).ToList();

        var table = SkillMetrics.LearningLoopTable(all, SkillDomain.Executable);
        var diagnostics = SkillMetrics.SelfVerificationDiagnostics(all);
        var cells = new List<CellPrecision>();
        foreach (var sv in new[] { false, true })
        {
            foreach (var ef in new[] { false, true })
                cells.Add(new CellPrecision(sv, ef, all.Where(r => Sv(r) == sv && Ef(r) == ef && r.CallCount > 0).Select(r => new SkillCount(r.SuccessCount, r.CallCount)).ToList()));
        }
        IReadOnlyList<SkillCount> Cell(bool sv, bool ef) => cells.First(c => c.Sv == sv && c.Ef == ef).Skills;
        var perCellCi = cells.Select(c => (c.Sv, c.Ef, Stats.BootstrapPooledPrecision(c.Skills, seed: RqcAnalysis.DeriveSeed(o.Seed, c.Sv ? 3 : 1, c.Ef ? 2 : 0)))).ToList();
        var did = Stats.PooledDifferenceInDifferences(Cell(false, false), Cell(false, true), Cell(true, false), Cell(true, true), seed: o.Seed ^ 0x5BD1E995u);

        int onSucc = 0, onFail = 0, offSucc = 0, offFail = 0, svOnSucc = 0, svOnFail = 0, svOffSucc = 0, svOffFail = 0, nSkills = 0, nExecutions = 0;
        var condSuccFail = new Dictionary<string, (int Succ, int Fail)>(StringComparer.Ordinal);
        foreach (var r in all)
        {
            nExecutions += r.CallCount;
            if (r.CallCount == 0)
                continue;
            nSkills++;
            var ok = SkillSuccess(r);
            if (Ef(r))
            {
                if (ok) onSucc++; else onFail++;
            }
            else if (ok)
            {
                offSucc++;
            }
            else
            {
                offFail++;
            }
            if (Sv(r))
            {
                if (ok) svOnSucc++; else svOnFail++;
            }
            else if (ok)
            {
                svOffSucc++;
            }
            else
            {
                svOffFail++;
            }
            var id = RqcAnalysis.ConditionId(Sv(r), Ef(r));
            var e = condSuccFail.GetValueOrDefault(id);
            condSuccFail[id] = ok ? (e.Succ + 1, e.Fail) : (e.Succ, e.Fail + 1);
        }
        var chi = Stats.ChiSquare2x2(onSucc, onFail, offSucc, offFail);
        var chiSv = Stats.ChiSquare2x2(svOnSucc, svOnFail, svOffSucc, svOffFail);
        var degeneracy = DetectDegeneracy(table, conditions.Select(c => c.Loop).ToList());

        static int Succ(IEnumerable<SkillRecord> xs) => xs.Sum(r => r.SuccessCount);
        static int Fail(IEnumerable<SkillRecord> xs) => xs.Sum(r => r.CallCount - r.SuccessCount);
        var envOn = all.Where(Ef).ToList();
        var envOff = all.Where(r => !Ef(r)).ToList();
        var chiExec = Stats.ChiSquare2x2(Succ(envOn), Fail(envOn), Succ(envOff), Fail(envOff));

        var onRate = onSucc + onFail == 0 ? double.NaN : (double)onSucc / (onSucc + onFail);
        var offRate = offSucc + offFail == 0 ? double.NaN : (double)offSucc / (offSucc + offFail);
        var effects = new EffectSizes(Stats.OddsRatio(onSucc, onFail, offSucc, offFail), Stats.RiskDifference(onSucc, onFail, offSucc, offFail),
            Stats.CramersV(chi.Statistic, nSkills), Stats.CohensH(onRate, offRate),
            Stats.LogOddsInteraction(Cell(false, false).Sum(s => s.Succ), Cell(false, true).Sum(s => s.Succ), Cell(true, false).Sum(s => s.Succ), Cell(true, true).Sum(s => s.Succ)));
        var (a, b, c, d) = McNemarTable(all);
        var mcnemar = Stats.McNemarExactOrChi(a, b, c, d);

        var family = new List<(string Label, double P)>
        {
            ("omnibus.envFeedbackAxis", chi.P),
            ("omnibus.selfVerificationAxis", chiSv.P),
            ("svXef.factorialInteraction", effects.InteractionLogOdds.P),
            ("envFeedback.mcnemar", mcnemar.P),
        };
        for (var i = 0; i < Condition.All.Count; i++)
        {
            for (var j = i + 1; j < Condition.All.Count; j++)
            {
                var ci = condSuccFail.GetValueOrDefault(Condition.All[i].Id);
                var cj = condSuccFail.GetValueOrDefault(Condition.All[j].Id);
                family.Add(($"pairwise.{Condition.All[i].Id}.vs.{Condition.All[j].Id}", Stats.ChiSquare2x2(ci.Succ, ci.Fail, cj.Succ, cj.Fail).P));
            }
        }
        var holm = Stats.HolmBonferroni(family.Select(f => f.P).ToList(), 0.05, family.Select(f => f.Label).ToList());

        var perCell = nSkills > 0 ? (int)JsRound(nSkills / 4.0) : 0;
        var power = new PowerDeclaration(
            perCell > 0 ? Stats.MinDetectableEffectProportion(perCell) * 100 : double.NaN, perCell,
            perCell > 0 ? Stats.PowerForEffectProportion(0.10, perCell) : double.NaN,
            perCell > 0 ? Stats.PowerForEffectProportion(0.05, perCell) : double.NaN);

        return new ExperimentResult(conditions, table, diagnostics, perCellCi, nSkills, nExecutions, effects, holm, effects.InteractionLogOdds,
            chi, chiSv, chiExec, mcnemar, power, deviation, degeneracy, did, cells);
    }

    private static DegeneracyCheck DetectDegeneracy(IReadOnlyList<LearningLoopCell> table, IReadOnlyList<LoopDiagnostics> loops)
    {
        var precisions = table.Select(c => c.Precision).Where(double.IsFinite).ToList();
        var identical = precisions.Count == 4 && precisions.Select(p => Aijade.Core.Js.JsFormat.ToFixed(p, 12)).Distinct().Count() == 1;
        var regen = loops.Sum(l => l.Regenerations);
        var rec = loops.Sum(l => l.Recoveries);
        var changed = loops.Sum(l => l.RecoveriesWithChangedCode);
        var rate = regen > 0 ? (double)rec / regen : double.NaN;
        var (reachable, note) = RqcAnalysis.Guard(identical, regen, rec, changed);
        return new DegeneracyCheck(identical, regen, rec, rate, reachable, note, changed);
    }

    /// <summary>McNemar pairs: environment feedback OFF vs ON for the same (self-verification, trial, task).</summary>
    private static (int A, int B, int C, int D) McNemarTable(List<SkillRecord> records)
    {
        var pairs = new OrderedDictionary<string, (SkillRecord? Off, SkillRecord? On)>(StringComparer.Ordinal);
        foreach (var r in records)
        {
            if (r.Metadata?["taskId"]?.GetValue<string>() is not { } taskId || r.Metadata?["trial"] is not JsonValue trialNode)
                continue;
            var key = $"{(Sv(r) ? "true" : "false")}|{trialNode.GetValue<int>()}|{taskId}";
            var e = pairs.GetValueOrDefault(key);
            pairs[key] = Ef(r) ? (e.Off, r) : (r, e.On);
        }
        int a = 0, b = 0, c = 0, d = 0;
        foreach (var (off, on) in pairs.Values)
        {
            if (off is null || on is null)
                continue;
            var offOk = SkillSuccess(off);
            var onOk = SkillSuccess(on);
            if (!offOk && !onOk) a++;
            else if (!offOk && onOk) b++;
            else if (offOk && !onOk) c++;
            else d++;
        }
        return (a, b, c, d);
    }

    private sealed class RetryState
    {
        public int Attempts { get; set; }
        public EnvironmentFeedbackSignal? EnvFeedback { get; set; }
        public string? SelfCritique { get; set; }
        public string? LastCode { get; set; }
    }

    private static async Task<ConditionResult> RunConditionAsync(Condition cond, RunOptions o, double pruneThreshold, int pruneMinCalls, Func<double> now,
        List<IReadOnlyList<BenchTask>> trialTasks, CancellationToken ct)
    {
        var records = new List<SkillRecord>();
        int regenerations = 0, withSignal = 0, recoveries = 0, changedRecoveries = 0;
        for (var t = 0; t < o.Trials; t++)
        {
            var registry = new SkillRegistry(new MemorySkillStore(), now);
            var skillByTask = new Dictionary<string, string>(StringComparer.Ordinal);
            var retry = new Dictionary<string, RetryState>(StringComparer.Ordinal);
            for (var round = 0; round < o.Rounds; round++)
            {
                foreach (var task in trialTasks[t])
                {
                    var skillId = skillByTask.GetValueOrDefault(task.Id);
                    var reused = false;
                    SkillRecord? existing = null;
                    var replacedAfterFailure = false;
                    if (skillId is not null)
                    {
                        existing = await registry.GetAsync(skillId, ct).ConfigureAwait(false);
                        if (existing is { Status: SkillLifecycle.Active })
                        {
                            reused = true;
                        }
                        else
                        {
                            replacedAfterFailure = existing is not null;
                            skillId = null;
                            existing = null;
                        }
                    }

                    string code;
                    string? generation = null, selfRationale = null, selfReply = null;
                    bool? selfVerdict = null;
                    var st = retry.GetValueOrDefault(task.Id) ?? new RetryState();
                    bool hadEnv = false, hadCritique = false;
                    var attempt = st.Attempts;
                    var previousCode = st.LastCode;
                    if (skillId is null)
                    {
                        // Evidence is injected only through the channels this condition owns.
                        var env = cond.EnvFeedback ? st.EnvFeedback : null;
                        var critique = cond.SelfVerification ? st.SelfCritique : null;
                        hadEnv = env is not null;
                        hadCritique = critique is not null;
                        var ctx = new GenerateContext(attempt, env, critique, env is not null || critique is not null ? st.LastCode : null);
                        var candidate = await o.Backend.GenerateAsync(task, ctx, ct).ConfigureAwait(false);
                        code = Bench.ExtractCodeBlock(candidate) ?? candidate;
                        generation = candidate;
                        skillId = $"{cond.Id}-t{t}-r{round}-{task.Id}";
                        await registry.CreateAsync(new CreateSkillOptions($"skill-{task.Id}", SkillDomain.Executable, candidate, EnvFeedback: new EnvFeedback(cond.EnvFeedback),
                            Metadata: new JsonObject { ["taskId"] = task.Id, ["trial"] = t, ["round"] = round, ["condition"] = cond.Id }, SkillId: skillId), ct).ConfigureAwait(false);
                        if (cond.SelfVerification)
                        {
                            var v = await o.Backend.VerifyAsync(task, candidate, ct).ConfigureAwait(false);
                            await registry.SetSelfVerificationAsync(skillId, v.Pass ? SkillVerdict.Pass : SkillVerdict.Fail, v.Score, v.Rationale, o.Backend.Name, ct).ConfigureAwait(false);
                            selfVerdict = v.Pass;
                            st.SelfCritique = v.Rationale;
                            selfRationale = v.Rationale;
                            selfReply = v.FullReply;
                        }
                        skillByTask[task.Id] = skillId;
                        st.Attempts = attempt + 1;
                        st.LastCode = code;
                        retry[task.Id] = st;
                    }
                    else
                    {
                        code = existing!.Body is { } body ? Bench.ExtractCodeBlock(body) ?? body : "";
                        selfVerdict = existing.SelfVerification is { } sv ? sv.Verdict == SkillVerdict.Pass : null;
                    }

                    var verdict = o.Sandbox.RunTask(code, task);
                    await registry.RecordExecutionAsync(skillId, new ExecutionOutcome(verdict.Ok, verdict.Error, JsRound(verdict.DurationMs)), ct).ConfigureAwait(false);
                    st.EnvFeedback = new EnvironmentFeedbackSignal(verdict.Failures.Select(f => f.Index).ToList(), verdict.Passed, verdict.Total,
                        (verdict.Error is { } err ? [err] : Array.Empty<string>()).Concat(verdict.Failures.Where(f => f.Error is not null).Select(f => f.Error!)).Take(4).ToList());
                    retry[task.Id] = st;
                    if (cond.EnvFeedback)
                        await registry.PruneLowPrecisionAsync(pruneThreshold, pruneMinCalls, ct).ConfigureAwait(false);
                    if (!reused && replacedAfterFailure)
                    {
                        regenerations++;
                        if (hadEnv || hadCritique)
                            withSignal++;
                        if (verdict.Ok)
                        {
                            recoveries++;
                            if (code != previousCode)
                                changedRecoveries++;
                        }
                    }
                    o.OnStep?.Invoke(new HarnessStep(cond.Id, t, round, task.Id, skillId, reused, attempt, hadEnv, hadCritique, !reused && replacedAfterFailure,
                        selfVerdict, verdict.Ok, JsRound(verdict.DurationMs)) { Code = code, Generation = generation, SelfRationale = selfRationale, SelfReply = selfReply });
                }
            }
            records.AddRange(await registry.AllAsync(ct).ConfigureAwait(false));
        }
        return new ConditionResult(cond, records, new LoopDiagnostics(regenerations, withSignal, recoveries, regenerations > 0 ? (double)recoveries / regenerations : double.NaN, changedRecoveries));
    }
}
