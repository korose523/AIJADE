using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Research.Statistics;

namespace Aijade.Research.RqC;

// The analysis is recomputed purely from the persisted per-execution log
// (trials.jsonl): skill lifecycles are replayed with the registry's rules, then every statistic of the
// published summary.json is derived deterministically.

/// <summary>One line of trials.jsonl.</summary>
public sealed record StepRecord(
    string Condition, int Trial, int Round, string TaskId, string SkillId, bool Reused, int Attempt,
    bool HadEnvFeedback, bool HadSelfCritique, bool RegeneratedFromFailure, string? SelfVerdict, bool ExecOk, string? CodeHash = null)
{
    public bool SelfVerification => Condition.StartsWith("sv1", StringComparison.Ordinal);

    public bool EnvFeedback => Condition.EndsWith("ef1", StringComparison.Ordinal);

    /// <summary>Parses one log line. Logs written by older harness versions lack the loop-accounting fields; they default to false / 0.</summary>
    public static StepRecord Parse(string line)
    {
        using var doc = JsonDocument.Parse(line);
        var e = doc.RootElement;
        bool Flag(string name) => e.TryGetProperty(name, out var v) && v.GetBoolean();
        var verdict = e.TryGetProperty("selfVerdict", out var sv) && sv.ValueKind == JsonValueKind.String ? sv.GetString() : null;
        return new StepRecord(
            e.GetProperty("condition").GetString()!, e.GetProperty("trial").GetInt32(), e.GetProperty("round").GetInt32(),
            e.GetProperty("taskId").GetString()!, e.GetProperty("skillId").GetString()!, Flag("reused"),
            e.TryGetProperty("attempt", out var at) ? at.GetInt32() : 0, Flag("hadEnvFeedback"), Flag("hadSelfCritique"),
            Flag("regeneratedFromFailure"), verdict, e.GetProperty("execOk").GetBoolean(),
            e.TryGetProperty("codeHash", out var ch) && ch.ValueKind == JsonValueKind.String ? ch.GetString() : null);
    }

    public static IReadOnlyList<StepRecord> ReadJsonl(string path) =>
        File.ReadLines(path).Where(l => l.Length > 0).Select(Parse).ToList();
}

public enum SkillStatus
{
    Active,
    Retired,
    Rejected,
}

/// <summary>A skill as the registry held it at the end of the run.</summary>
public sealed class SkillState(string id, bool selfVerification, bool envFeedback, int trial, string taskId)
{
    public string Id { get; } = id;
    public bool SelfVerificationCondition { get; } = selfVerification;
    public bool EnvFeedback { get; } = envFeedback;
    public int Trial { get; } = trial;
    public string TaskId { get; } = taskId;
    public int CallCount { get; set; }
    public int SuccessCount { get; set; }
    public SkillStatus Status { get; set; } = SkillStatus.Active;

    /// <summary>"pass" / "fail" when the skill was self-verified, otherwise null.</summary>
    public string? SelfVerdict { get; set; }

    /// <summary>Outcome of the most recent execution (the registry keeps only the latest verdict).</summary>
    public bool? LastExecutionOk { get; set; }

    /// <summary>Binary skill outcome: success iff success / calls ≥ 0.5.</summary>
    public bool Success => CallCount > 0 && (double)SuccessCount / CallCount >= 0.5;
}

public sealed record RqcConfig(uint Seed = 42, double PruneThreshold = 0.5, int PruneMinCalls = 3);

public static class RqcAnalysis
{
    private static readonly int[] PowerReferenceSizes = [240, 360];

    public static readonly IReadOnlyList<(bool Sv, bool Ef)> Conditions = [(false, false), (false, true), (true, false), (true, true)];

    public static string ConditionId(bool sv, bool ef) => $"sv{(sv ? 1 : 0)}-ef{(ef ? 1 : 0)}";

    /// <summary>Deterministic seed derivation, (32-bit wrapping multiplication, Math.imul semantics).</summary>
    public static uint DeriveSeed(uint baseSeed, int i, int t = 0)
    {
        unchecked
        {
            return ((baseSeed ^ 0x85EBCA6B) * 0x9E3779B9) ^ ((uint)(i + 1) * 0xC2B2AE35) ^ ((uint)(t + 1) * 0x27D4EB2F);
        }
    }

    /// <summary>
    /// Replays the skill registry from the step log, in log order, applying the registry's lifecycle rules:
    /// a self-verification "fail" rejects the new skill; ≥3 calls with no success retire it when environmental
    /// feedback is on; and after every environmental-feedback step all active skills of that (condition, trial)
    /// registry with ≥ minCalls calls and precision below the threshold are pruned.
    /// </summary>
    /// <summary>
    /// The constructive-null guard. With code fingerprints in the log (<paramref name="changedRecoveries"/> not null), only a
    /// recovery whose code differs from the task's previous code shows that feedback reached the generator: a candidate the
    /// self-verifier rejected although it worked passes when regenerated unchanged. Logs without fingerprints keep the
    /// original rule, which counts every recovery.
    /// </summary>
    public static (bool Reachable, string Note) Guard(bool identicalPrecision, int regenerations, int recoveries, int? changedRecoveries)
    {
        if (identicalPrecision)
            return (false, "NULL BY CONSTRUCTION: all four cells share an identical precision — neither factor has a causal path to the outcome. Do NOT report as \"no effect\".");
        if (changedRecoveries is not { } changed)
        {
            return regenerations == 0 || recoveries > 0
                ? (true, $"reachable: cells differ and {recoveries}/{regenerations} regenerations recovered")
                : (false, $"INERT LOOP: {regenerations} regenerations produced 0 recoveries — feedback never changed a candidate. Check that generate() folds GenerateContext into the prompt.");
        }
        return regenerations == 0 || changed > 0
            ? (true, $"reachable: cells differ and {changed}/{regenerations} regenerations recovered with changed code ({recoveries} recovered in all)")
            : (false, $"INERT LOOP: {regenerations} regenerations, {recoveries} recovered, none with changed code — feedback never changed a candidate. Check that generate() folds GenerateContext into the prompt.");
    }

    /// <summary>Recoveries whose code fingerprint differs from the task's previous one (same condition and trial); null when the log has no fingerprints.</summary>
    public static int? ChangedCodeRecoveries(IReadOnlyList<StepRecord> steps)
    {
        if (steps.Count == 0 || steps.Any(s => s.CodeHash is null))
            return null;
        var last = new Dictionary<(string, int, string), string?>();
        var changed = 0;
        foreach (var s in steps)
        {
            var key = (s.Condition, s.Trial, s.TaskId);
            if (s.RegeneratedFromFailure && s.ExecOk && (!last.TryGetValue(key, out var previous) || previous != s.CodeHash))
                changed++;
            if (!s.Reused)
                last[key] = s.CodeHash;
        }
        return changed;
    }

    public static IReadOnlyList<SkillState> ReplaySkills(IEnumerable<StepRecord> steps, RqcConfig config)
    {
        var all = new List<SkillState>();
        var registries = new Dictionary<(string, int), List<SkillState>>();
        var byId = new Dictionary<string, SkillState>();
        foreach (var s in steps)
        {
            if (!registries.TryGetValue((s.Condition, s.Trial), out var registry))
                registries[(s.Condition, s.Trial)] = registry = [];

            if (!byId.TryGetValue(s.SkillId, out var skill))
            {
                skill = new SkillState(s.SkillId, s.SelfVerification, s.EnvFeedback, s.Trial, s.TaskId);
                byId[s.SkillId] = skill;
                registry.Add(skill);
                all.Add(skill);
                if (s.SelfVerdict is not null)
                {
                    skill.SelfVerdict = s.SelfVerdict;
                    if (s.SelfVerdict == "fail" && skill.Status == SkillStatus.Active)
                        skill.Status = SkillStatus.Rejected;
                }
            }

            skill.CallCount++;
            if (s.ExecOk)
                skill.SuccessCount++;
            skill.LastExecutionOk = s.ExecOk;
            if (skill.CallCount >= 3 && skill.SuccessCount == 0 && skill.Status == SkillStatus.Active && skill.EnvFeedback)
                skill.Status = SkillStatus.Retired;

            if (s.EnvFeedback)
            {
                foreach (var r in registry)
                {
                    if (r.Status == SkillStatus.Active && r.CallCount >= config.PruneMinCalls
                        && (double)r.SuccessCount / r.CallCount < config.PruneThreshold)
                    {
                        r.Status = SkillStatus.Retired;
                    }
                }
            }
        }
        return all;
    }

    private static double Ratio(double n, double d) => d == 0 ? double.NaN : n / d;

    /// <summary>Recomputes the analysis part of summary.json (everything except run metadata).</summary>
    public static JsonObject Analyze(IReadOnlyList<StepRecord> steps, RqcConfig config)
    {
        var skills = ReplaySkills(steps, config);
        var result = new JsonObject
        {
            ["analysisUnit"] = "skill",
            ["nSkills"] = skills.Count(s => s.CallCount > 0),
            ["nExecutions"] = skills.Sum(s => s.CallCount),
            ["conditions"] = new JsonArray(Conditions.Select(c => (JsonNode)ConditionId(c.Sv, c.Ef)).ToArray()),
        };

        // Learning-loop table, one cell per condition.
        var table = new JsonArray();
        var precisions = new List<double>();
        foreach (var (sv, ef) in Conditions)
        {
            var subset = skills.Where(s => s.SelfVerificationCondition == sv && s.EnvFeedback == ef).ToList();
            var calls = subset.Sum(s => s.CallCount);
            var precision = Ratio(subset.Sum(s => s.SuccessCount), calls);
            precisions.Add(precision);
            table.Add(new JsonObject
            {
                ["selfVerificationEnabled"] = sv,
                ["envFeedbackEnabled"] = ef,
                ["count"] = subset.Count,
                ["precision"] = Num(precision),
                ["retiredRate"] = Num(Ratio(subset.Count(s => s.Status == SkillStatus.Retired), subset.Count)),
                ["meanCallsPerSkill"] = Num(Ratio(calls, subset.Count)),
            });
        }
        result["table"] = table;

        // Self-verification diagnostic on the overlap of self-verdict and execution. The estimands condition on the oracle's
        // verdict (P2 §3.2: hallucinationRate = P(self-pass | unusable), missRate = P(self-fail | usable)); the predictive values
        // condition on the self-verdict. Before 2026-10-15 the predictive values were written under the estimand names.
        var verified = skills.Where(s => s.SelfVerdict is not null && s.LastExecutionOk is not null).ToList();
        var selfPass = verified.Where(s => s.SelfVerdict == "pass").ToList();
        var selfFail = verified.Where(s => s.SelfVerdict != "pass").ToList();
        var unusable = verified.Where(s => s.LastExecutionOk == false).ToList();
        var usable = verified.Where(s => s.LastExecutionOk == true).ToList();
        result["diagnostics"] = new JsonObject
        {
            ["n"] = verified.Count,
            ["hallucinationRate"] = Num(Ratio(unusable.Count(s => s.SelfVerdict == "pass"), unusable.Count)),
            ["missRate"] = Num(Ratio(usable.Count(s => s.SelfVerdict != "pass"), usable.Count)),
            ["agreement"] = Num(Ratio(verified.Count(s => (s.SelfVerdict == "pass") == s.LastExecutionOk), verified.Count)),
            ["falseDiscoveryRate"] = Num(Ratio(selfPass.Count(s => s.LastExecutionOk == false), selfPass.Count)),
            ["falseOmissionRate"] = Num(Ratio(selfFail.Count(s => s.LastExecutionOk == true), selfFail.Count)),
        };

        // Per-cell skill aggregates (skills with at least one call).
        List<SkillCount> Cell(bool sv, bool ef) => skills
            .Where(s => s.SelfVerificationCondition == sv && s.EnvFeedback == ef && s.CallCount > 0)
            .Select(s => new SkillCount(s.SuccessCount, s.CallCount)).ToList();
        var a = Cell(false, false);
        var b = Cell(false, true);
        var c = Cell(true, false);
        var d = Cell(true, true);

        var perCell = new JsonArray();
        foreach (var (sv, ef) in Conditions)
        {
            var ci = Stats.BootstrapPooledPrecision(Cell(sv, ef), seed: DeriveSeed(config.Seed, sv ? 3 : 1, ef ? 2 : 0));
            perCell.Add(new JsonObject { ["sv"] = sv, ["ef"] = ef, ["ci"] = Ci(ci) });
        }
        result["perCellCI"] = perCell;

        var did = Stats.PooledDifferenceInDifferences(a, b, c, d, seed: config.Seed ^ 0x5BD1E995);
        result["diffInDiff"] = new JsonObject
        {
            ["estimate"] = Num(did.Estimate),
            ["ci"] = Ci(did.Ci),
            ["cellMeans"] = new JsonObject { ["a"] = Num(did.CellMeans.A), ["b"] = Num(did.CellMeans.B), ["c"] = Num(did.CellMeans.C), ["d"] = Num(did.CellMeans.D) },
        };

        // Skill-level 2×2 contrasts.
        int onSucc = 0, onFail = 0, offSucc = 0, offFail = 0, svOnSucc = 0, svOnFail = 0, svOffSucc = 0, svOffFail = 0;
        var condSuccFail = new Dictionary<string, (int Succ, int Fail)>();
        foreach (var s in skills.Where(s => s.CallCount > 0))
        {
            var ok = s.Success;
            if (s.EnvFeedback) { if (ok) onSucc++; else onFail++; }
            else if (ok) offSucc++;
            else offFail++;
            if (s.SelfVerificationCondition) { if (ok) svOnSucc++; else svOnFail++; }
            else if (ok) svOffSucc++;
            else svOffFail++;
            var id = ConditionId(s.SelfVerificationCondition, s.EnvFeedback);
            var e = condSuccFail.GetValueOrDefault(id);
            condSuccFail[id] = ok ? (e.Succ + 1, e.Fail) : (e.Succ, e.Fail + 1);
        }
        var nSkills = skills.Count(s => s.CallCount > 0);
        var chi = Stats.ChiSquare2x2(onSucc, onFail, offSucc, offFail);
        var chiSv = Stats.ChiSquare2x2(svOnSucc, svOnFail, svOffSucc, svOffFail);
        var envOn = skills.Where(s => s.EnvFeedback).ToList();
        var envOff = skills.Where(s => !s.EnvFeedback).ToList();
        var chiExec = Stats.ChiSquare2x2(
            envOn.Sum(s => s.SuccessCount), envOn.Sum(s => s.CallCount - s.SuccessCount),
            envOff.Sum(s => s.SuccessCount), envOff.Sum(s => s.CallCount - s.SuccessCount));

        double onRate = Ratio(onSucc, onSucc + onFail), offRate = Ratio(offSucc, offSucc + offFail);
        var interaction = Stats.LogOddsInteraction(a.Sum(x => x.Succ), b.Sum(x => x.Succ), c.Sum(x => x.Succ), d.Sum(x => x.Succ));
        result["effectSizes"] = new JsonObject
        {
            ["oddsRatio"] = Num(Stats.OddsRatio(onSucc, onFail, offSucc, offFail)),
            ["riskDifference"] = Num(Stats.RiskDifference(onSucc, onFail, offSucc, offFail)),
            ["cramersV"] = Num(Stats.CramersV(chi.Statistic, nSkills)),
            ["cohensH"] = Num(Stats.CohensH(onRate, offRate)),
            ["interactionLogOdds"] = LogOdds(interaction),
        };

        var mcnemar = McNemar(skills);
        var family = new List<(string Label, double P)>
        {
            ("omnibus.envFeedbackAxis", chi.P),
            ("omnibus.selfVerificationAxis", chiSv.P),
            ("svXef.factorialInteraction", interaction.P),
            ("envFeedback.mcnemar", mcnemar.P),
        };
        for (var i = 0; i < Conditions.Count; i++)
        {
            for (var j = i + 1; j < Conditions.Count; j++)
            {
                var ci = condSuccFail.GetValueOrDefault(ConditionId(Conditions[i].Sv, Conditions[i].Ef));
                var cj = condSuccFail.GetValueOrDefault(ConditionId(Conditions[j].Sv, Conditions[j].Ef));
                family.Add(($"pairwise.{ConditionId(Conditions[i].Sv, Conditions[i].Ef)}.vs.{ConditionId(Conditions[j].Sv, Conditions[j].Ef)}",
                    Stats.ChiSquare2x2(ci.Succ, ci.Fail, cj.Succ, cj.Fail).P));
            }
        }
        var holm = Stats.HolmBonferroni(family.Select(f => f.P).ToList(), 0.05, family.Select(f => f.Label).ToList());
        result["multiplicity"] = new JsonObject
        {
            ["method"] = "holm",
            ["alpha"] = 0.05,
            ["adjusted"] = new JsonArray(holm.Select(h => (JsonNode)new JsonObject
            {
                ["label"] = h.Label, ["p"] = Num(h.P), ["adjustedP"] = Num(h.AdjustedP), ["reject"] = h.Reject,
            }).ToArray()),
        };
        result["factorialInteraction"] = LogOdds(interaction);
        result["chiSquare"] = Chi(chi);
        result["chiSquareSelfVerification"] = Chi(chiSv);
        result["chiSquareExecutionLevel"] = Chi(chiExec);
        result["mcnemarEnvFeedback"] = new JsonObject
        {
            ["a"] = mcnemar.A, ["b"] = mcnemar.B, ["c"] = mcnemar.C, ["d"] = mcnemar.D, ["nPairs"] = mcnemar.NPairs,
            ["chiSquare"] = Num(mcnemar.ChiSquare), ["pChiSquare"] = Num(mcnemar.PChiSquare),
            ["pExact"] = mcnemar.PExact is { } pe ? Num(pe) : null, ["p"] = Num(mcnemar.P), ["usedExact"] = mcnemar.UsedExact,
        };

        var perCellN = nSkills > 0 ? (int)Math.Round(nSkills / 4.0, MidpointRounding.AwayFromZero) : 0;
        result["power"] = new JsonObject
        {
            ["minDetectableEffectAt80"] = Num(perCellN > 0 ? Stats.MinDetectableEffectProportion(perCellN) * 100 : double.NaN),
            ["nSkillsPerCell"] = perCellN,
            ["powerAtDelta10pp"] = Num(perCellN > 0 ? Stats.PowerForEffectProportion(0.10, perCellN) : double.NaN),
            ["powerAtDelta5pp"] = Num(perCellN > 0 ? Stats.PowerForEffectProportion(0.05, perCellN) : double.NaN),
        };
        result["powerReference"] = new JsonArray(PowerReferenceSizes.Select(n => (JsonNode)new JsonObject
        {
            ["nPerCell"] = n,
            ["minDetectableEffectAt80pp"] = Math.Round(Stats.MinDetectableEffectProportion(n) * 100, 2, MidpointRounding.AwayFromZero),
            ["powerAtDelta10pp"] = Math.Round(Stats.PowerForEffectProportion(0.10, n), 4, MidpointRounding.AwayFromZero),
            ["powerAtDelta5pp"] = Math.Round(Stats.PowerForEffectProportion(0.05, n), 4, MidpointRounding.AwayFromZero),
        }).ToArray());

        // Loop liveness and the constructive-null guard.
        var loops = Conditions.Select(cond =>
        {
            var id = ConditionId(cond.Sv, cond.Ef);
            var regen = steps.Where(s => s.Condition == id && s.RegeneratedFromFailure).ToList();
            var recoveries = regen.Count(s => s.ExecOk);
            return (Id: id, Regenerations: regen.Count, WithSignal: regen.Count(s => s.HadEnvFeedback || s.HadSelfCritique), Recoveries: recoveries);
        }).ToList();
        var identical = precisions.All(double.IsFinite) && precisions.Count == 4
            && precisions.Select(p => p.ToString("F12", CultureInfo.InvariantCulture)).Distinct().Count() == 1;
        var totalRegen = loops.Sum(l => l.Regenerations);
        var totalRec = loops.Sum(l => l.Recoveries);
        var changedRec = ChangedCodeRecoveries(steps);
        var (reachable, note) = Guard(identical, totalRegen, totalRec, changedRec);
        result["degeneracy"] = new JsonObject
        {
            ["allCellsIdenticalPrecision"] = identical,
            ["totalRegenerations"] = totalRegen,
            ["totalRecoveries"] = totalRec,
            ["recoveredRate"] = Num(Ratio(totalRec, totalRegen)),
            ["manipulationReachable"] = reachable,
            ["note"] = note,
        };
        if (changedRec is { } cr)
            result["degeneracy"]!["totalRecoveriesWithChangedCode"] = cr;
        result["loopDiagnostics"] = new JsonArray(loops.Select(l => (JsonNode)new JsonObject
        {
            ["condition"] = l.Id,
            ["loop"] = new JsonObject
            {
                ["regenerations"] = l.Regenerations,
                ["regenerationsWithSignal"] = l.WithSignal,
                ["recoveries"] = l.Recoveries,
                ["recoveredRate"] = Num(Ratio(l.Recoveries, l.Regenerations)),
            },
        }).ToArray());
        return result;
    }

    /// <summary>McNemar table pairing the envFeedback OFF/ON skill per (selfVerification, trial, task); the last skill per slot wins.</summary>
    private static McNemarResult McNemar(IReadOnlyList<SkillState> skills)
    {
        var pairs = new Dictionary<(bool, int, string), (SkillState? Off, SkillState? On)>();
        foreach (var s in skills)
        {
            var key = (s.SelfVerificationCondition, s.Trial, s.TaskId);
            var e = pairs.GetValueOrDefault(key);
            pairs[key] = s.EnvFeedback ? (e.Off, s) : (s, e.On);
        }
        int a = 0, b = 0, c = 0, d = 0;
        foreach (var (off, on) in pairs.Values)
        {
            if (off is null || on is null)
                continue;
            switch (off.Success, on.Success)
            {
                case (false, false): a++; break;
                case (false, true): b++; break;
                case (true, false): c++; break;
                default: d++; break;
            }
        }
        return Stats.McNemarExactOrChi(a, b, c, d);
    }

    // JSON.stringify writes NaN and ±Infinity as null; mirror that so the output is directly comparable.
    private static JsonValue? Num(double x) => double.IsFinite(x) ? JsonValue.Create(x) : null;

    private static JsonObject Ci(ConfidenceInterval ci) => new() { ["mean"] = Num(ci.Mean), ["lo"] = Num(ci.Lo), ["hi"] = Num(ci.Hi) };

    private static JsonObject LogOdds(LogOddsInteractionResult r) => new() { ["estimate"] = Num(r.Estimate), ["se"] = Num(r.Se), ["z"] = Num(r.Z), ["p"] = Num(r.P) };

    private static JsonObject Chi(ChiSquareResult r) => new()
    {
        ["statistic"] = Num(r.Statistic),
        ["p"] = Num(r.P),
        ["table"] = new JsonArray(new JsonArray(r.Table[0, 0], r.Table[0, 1]), new JsonArray(r.Table[1, 0], r.Table[1, 1])),
        ["df"] = r.Df,
    };
}
