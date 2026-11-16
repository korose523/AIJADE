using System.Text.Json.Nodes;

using Aijade.Research.Statistics;

namespace Aijade.Research.RqC;

// P2-C of experiments/plans/2026-10-22-followup-analyses.md (committed before this code was written): does environment
// feedback change the verifier's error rates, and do the rates hold over the five rounds? Only the two self-verification-on
// cells carry verdicts. The verifier prompt holds the task and the candidate code alone, so feedback can move the rates only
// through which candidates are produced; the target is the error rate on the candidates produced under each condition.
// Unit, truth and rates follow RqcModels.Diagnostics: the skill; the outcome of its last execution; hallucinationRate =
// FP/(FP+TN), missRate = FN/(FN+TP) with positive = self-pass. Intervals come from a task-cluster bootstrap.
public static class VerifierFeedback
{
    public const int Rounds = 5;

    /// <summary>Below this many tasks with unusable skills in a cell, the hallucinationRate comparison is descriptive only.</summary>
    public const int MinTasksWithUnusable = 5;

    private static readonly bool[] EfLevels = [false, true];

    private sealed record Judged(string TaskId, bool Ef, int Round, bool Pass, bool Usable, string? Code)
    {
        public bool Wrong => Pass != Usable;
    }

    private readonly record struct Counts(int Tp, int Fp, int Fn, int Tn)
    {
        public static Counts operator +(Counts a, Counts b) => new(a.Tp + b.Tp, a.Fp + b.Fp, a.Fn + b.Fn, a.Tn + b.Tn);

        public double Hallucination => Fp + Tn > 0 ? Fp / (double)(Fp + Tn) : double.NaN;

        public double Miss => Fn + Tp > 0 ? Fn / (double)(Fn + Tp) : double.NaN;

        public static Counts Of(IEnumerable<Judged> xs)
        {
            int tp = 0, fp = 0, fn = 0, tn = 0;
            foreach (var x in xs)
            {
                if (x.Pass && x.Usable)
                    tp++;
                else if (x.Pass)
                    fp++;
                else if (x.Usable)
                    fn++;
                else
                    tn++;
            }
            return new Counts(tp, fp, fn, tn);
        }
    }

    /// <param name="steps">The run's step log.</param>
    /// <param name="codes">The extracted code of every step, indexed like <paramref name="steps"/>; null skips the per-candidate analyses.</param>
    /// <param name="config">The run's registry configuration (seed and pruning rule), for replaying the skills.</param>
    /// <param name="iterations">Bootstrap resamples.</param>
    /// <param name="seed">Seed of the resampling (the one RqcModels.Diagnostics uses).</param>
    public static JsonObject Analyze(IReadOnlyList<StepRecord> steps, IReadOnlyList<string?>? codes, RqcConfig config, int iterations = 10000, uint seed = 0x2545F491)
    {
        // a skill's round and code are those of its first step (its code: the first step that has one)
        var round = new Dictionary<string, int>(StringComparer.Ordinal);
        var code = new Dictionary<string, string>(StringComparer.Ordinal);
        for (var i = 0; i < steps.Count; i++)
        {
            round.TryAdd(steps[i].SkillId, steps[i].Round);
            if (codes?[i] is { } c)
                code.TryAdd(steps[i].SkillId, c);
        }
        var judged = RqcAnalysis.ReplaySkills(steps, config)
            .Where(s => s.SelfVerificationCondition && s.SelfVerdict is not null && s.LastExecutionOk is not null)
            .Select(s => new Judged(s.TaskId, s.EnvFeedback, round[s.Id], s.SelfVerdict == "pass", s.LastExecutionOk == true, code.GetValueOrDefault(s.Id)))
            .ToList();
        var tasks = judged.Select(j => j.TaskId).Distinct().Order(StringComparer.Ordinal).ToList();

        var result = new JsonObject
        {
            ["skillsJudged"] = judged.Count,
            ["tasks"] = tasks.Count,
            ["definitions"] = "skill unit; truth = last execution; positive = self-pass; hallucinationRate = FP/(FP+TN), missRate = FN/(FN+TP); "
                + $"task-cluster bootstrap ({iterations} resamples of the {tasks.Count} tasks, percentile 95%, one draw for both cells)",
        };

        // Question 1: feedback
        var feedback = new JsonObject();
        foreach (var ef in EfLevels)
        {
            var cell = judged.Where(j => j.Ef == ef).ToList();
            var o = CellJson(cell, tasks, iterations, seed);
            o["tasksWithUnusable"] = cell.Where(j => !j.Usable).Select(j => j.TaskId).Distinct().Count();
            feedback[ef ? "ef1" : "ef0"] = o;
        }
        feedback["difference"] = DifferenceJson(judged, tasks, j => j.Ef, iterations, seed);
        var fewTasks = EfLevels.Any(ef => judged.Where(j => j.Ef == ef && !j.Usable).Select(j => j.TaskId).Distinct().Count() < MinTasksWithUnusable);
        feedback["hallucinationComparisonDescriptiveOnly"] = fewTasks;
        feedback["logistic"] = new JsonObject
        {
            ["unusable"] = EfLogit(judged.Where(j => !j.Usable).ToList(), "verdict wrong = self-pass"),
            ["usable"] = EfLogit(judged.Where(j => j.Usable).ToList(), "verdict wrong = self-fail"),
        };
        if (codes is not null)
        {
            feedback["distinctCandidates"] = DistinctJson(judged, tasks, iterations, seed);
            feedback["consistency"] = ConsistencyJson(judged);
        }
        result["feedback"] = feedback;

        // Question 2: rounds
        var perRound = new JsonArray();
        for (var r = 0; r < Rounds; r++)
        {
            var cell = judged.Where(j => j.Round == r).ToList();
            var o = CellJson(cell, tasks, iterations, seed);
            o["round"] = r;
            o["tasksUnusable"] = cell.Where(j => !j.Usable).Select(j => j.TaskId).Distinct().Count();
            o["tasksUsable"] = cell.Where(j => j.Usable).Select(j => j.TaskId).Distinct().Count();
            perRound.Add(o);
        }
        result["rounds"] = new JsonObject
        {
            ["perRound"] = perRound,
            ["trend"] = new JsonObject
            {
                ["unusable"] = Logit([.. judged.Where(j => !j.Usable).Select(j => Row(j, [1, j.Round, j.Ef ? 1 : 0]))], ["intercept", "round", "envFeedback"], "verdict wrong = self-pass"),
                ["usable"] = Logit([.. judged.Where(j => j.Usable).Select(j => Row(j, [1, j.Round, j.Ef ? 1 : 0]))], ["intercept", "round", "envFeedback"], "verdict wrong = self-fail"),
            },
            ["withinTaskExploratory"] = WithinTask(judged),
        };
        return result;
    }

    /// <summary>
    /// Exploratory, added after the planned trend test was run: skills first generated after round 0 are regenerations, and
    /// a self-fail rejects a skill, so the later rounds hold the few tasks whose skills the verifier kept rejecting and the
    /// trend test compares different tasks across rounds. Within a task the question is answered directly: the tasks with
    /// judged skills both in round 0 and later, and their error counts in each period.
    /// </summary>
    private static JsonObject WithinTask(IReadOnlyList<Judged> judged)
    {
        JsonArray Tasks(bool usable) => new([.. judged.Where(j => j.Usable == usable).GroupBy(j => j.TaskId)
            .Where(g => g.Any(j => j.Round == 0) && g.Any(j => j.Round > 0)).OrderBy(g => g.Key, StringComparer.Ordinal)
            .Select(g => (JsonNode)new JsonObject
            {
                ["task"] = g.Key,
                ["round0"] = new JsonObject { ["wrong"] = g.Count(j => j.Round == 0 && j.Wrong), ["n"] = g.Count(j => j.Round == 0) },
                ["later"] = new JsonObject { ["wrong"] = g.Count(j => j.Round > 0 && j.Wrong), ["n"] = g.Count(j => j.Round > 0) },
            })]);
        return new JsonObject
        {
            ["what"] = "exploratory (not in the plan): tasks with judged skills in round 0 and in a later round, error counts per period; unusable: wrong = self-pass, usable: wrong = self-fail",
            ["unusable"] = Tasks(false),
            ["usable"] = Tasks(true),
        };
    }

    private static (double[] X, int Y, string Cluster) Row(Judged j, double[] x) => (x, j.Wrong ? 1 : 0, j.TaskId);

    /// <summary>Counts and both rates of one set of judged skills, with task-cluster bootstrap intervals.</summary>
    private static JsonObject CellJson(IReadOnlyList<Judged> cell, IReadOnlyList<string> tasks, int iterations, uint seed)
    {
        var byTask = PerTask(cell, tasks);
        var all = Counts.Of(cell);
        JsonObject Rate(int num, int den, Func<Counts, double> rate)
        {
            var o = new JsonObject { ["numerator"] = num, ["denominator"] = den, ["estimate"] = F(rate(all)) };
            var (lo, hi) = Bootstrap(tasks.Count, idx => rate(Sum(byTask, idx)), iterations, seed);
            o["taskBootstrap95"] = new JsonArray(F(lo), F(hi));
            return o;
        }
        return new JsonObject
        {
            ["n"] = cell.Count,
            ["confusion"] = new JsonObject { ["tp"] = all.Tp, ["fp"] = all.Fp, ["fn"] = all.Fn, ["tn"] = all.Tn },
            ["hallucinationRate"] = Rate(all.Fp, all.Fp + all.Tn, c => c.Hallucination),
            ["missRate"] = Rate(all.Fn, all.Fn + all.Tp, c => c.Miss),
        };
    }

    /// <summary>Each rate in the group where <paramref name="second"/> holds minus the other group, from one task draw for both.</summary>
    private static JsonObject DifferenceJson(IReadOnlyList<Judged> judged, IReadOnlyList<string> tasks, Func<Judged, bool> second, int iterations, uint seed)
    {
        var a = PerTask([.. judged.Where(second)], tasks);
        var b = PerTask([.. judged.Where(j => !second(j))], tasks);
        JsonObject One(Func<Counts, double> rate)
        {
            var est = rate(Sum(a, null)) - rate(Sum(b, null));
            var (lo, hi) = Bootstrap(tasks.Count, idx => rate(Sum(a, idx)) - rate(Sum(b, idx)), iterations, seed);
            return new JsonObject
            {
                ["estimate"] = F(est), ["taskBootstrap95"] = new JsonArray(F(lo), F(hi)),
                ["detected"] = double.IsFinite(lo) && double.IsFinite(hi) && (lo > 0 || hi < 0),
            };
        }
        return new JsonObject { ["what"] = "ef1 − ef0", ["hallucinationRate"] = One(c => c.Hallucination), ["missRate"] = One(c => c.Miss) };
    }

    /// <summary>The rates on distinct candidates (task, code) within each condition: the first judged skill of each stands for it (P2 Table 2b).</summary>
    private static JsonObject DistinctJson(IReadOnlyList<Judged> judged, IReadOnlyList<string> tasks, int iterations, uint seed)
    {
        var withCode = judged.Where(j => j.Code is not null).ToList();
        var distinct = withCode.GroupBy(j => (j.Ef, j.TaskId, j.Code)).Select(g => g.First()).ToList();
        var o = new JsonObject { ["skillsWithoutCode"] = judged.Count - withCode.Count };
        foreach (var ef in EfLevels)
            o[ef ? "ef1" : "ef0"] = CellJson([.. distinct.Where(j => j.Ef == ef)], tasks, iterations, seed);
        o["difference"] = DifferenceJson(distinct, tasks, j => j.Ef, iterations, seed);
        return o;
    }

    /// <summary>Decoding non-determinism baseline: candidates (task, code) judged in both conditions, and those that received different verdicts.</summary>
    private static JsonObject ConsistencyJson(IReadOnlyList<Judged> judged)
    {
        var groups = judged.Where(j => j.Code is not null).GroupBy(j => (j.TaskId, j.Code)).ToList();
        var inBoth = groups.Where(g => g.Any(j => j.Ef) && g.Any(j => !j.Ef)).ToList();
        return new JsonObject
        {
            ["candidates"] = groups.Count,
            ["judgedInBothConditions"] = inBoth.Count,
            ["differentVerdictsInBoth"] = inBoth.Count(g => g.Select(j => j.Pass).Distinct().Count() > 1),
            ["differentVerdictsAny"] = groups.Count(g => g.Select(j => j.Pass).Distinct().Count() > 1),
        };
    }

    /// <summary>
    /// "Verdict wrong" on environment feedback in one usability group. With no wrong verdicts, or only wrong verdicts, in one
    /// condition the maximum-likelihood estimate does not exist and the fit is reported as not estimable.
    /// </summary>
    private static JsonObject EfLogit(IReadOnlyList<Judged> group, string outcome)
    {
        foreach (var ef in EfLevels)
        {
            var cell = group.Where(j => j.Ef == ef).ToList();
            if (cell.Count == 0 || cell.All(j => j.Wrong) || cell.All(j => !j.Wrong))
                return new JsonObject { ["outcome"] = outcome, ["n"] = group.Count, ["note"] = $"not estimable: ef{(ef ? 1 : 0)} has {cell.Count(j => j.Wrong)} wrong of {cell.Count}" };
        }
        return Logit([.. group.Select(j => Row(j, [1, j.Ef ? 1 : 0]))], ["intercept", "envFeedback"], outcome);
    }

    /// <summary>Logistic regression by IRLS with cluster-robust (CR1) standard errors; a fit that does not converge is reported as not estimable.</summary>
    private static JsonObject Logit(IReadOnlyList<(double[] X, int Y, string Cluster)> data, string[] terms, string outcome)
    {
        var k = terms.Length;
        var o = new JsonObject { ["outcome"] = outcome, ["n"] = data.Count, ["wrong"] = data.Count(d => d.Y == 1) };
        if (data.Count == 0 || data.All(d => d.Y == 1) || data.All(d => d.Y == 0))
        {
            o["note"] = "not estimable: no wrong verdicts or only wrong verdicts";
            return o;
        }
        var beta = new double[k];
        var info = new double[k, k];
        var converged = false;
        for (var iter = 0; iter < 100 && !converged; iter++)
        {
            info = new double[k, k];
            var score = new double[k];
            foreach (var (x, y, _) in data)
            {
                var p = Logistic(RqcModels.Dot(x, beta));
                for (var i = 0; i < k; i++)
                {
                    score[i] += x[i] * (y - p);
                    for (var j = 0; j < k; j++)
                        info[i, j] += p * (1 - p) * x[i] * x[j];
                }
            }
            double[] step;
            try
            {
                step = RqcModels.Solve(info, score);
            }
            catch (InvalidOperationException)
            {
                // the information matrix degenerates when fitted probabilities run to 0 or 1
                break;
            }
            for (var i = 0; i < k; i++)
                beta[i] += step[i];
            converged = step.Max(Math.Abs) < 1e-10;
        }
        if (!converged || beta.Any(b => !double.IsFinite(b) || Math.Abs(b) > 20))
        {
            o["note"] = "not estimable: the fit did not converge (separation)";
            return o;
        }
        var bread = RqcModels.Invert(info);
        var meat = new double[k, k];
        var groups = data.GroupBy(d => d.Cluster).ToList();
        foreach (var g in groups)
        {
            var u = new double[k];
            foreach (var (x, y, _) in g)
            {
                var r = y - Logistic(RqcModels.Dot(x, beta));
                for (var i = 0; i < k; i++)
                    u[i] += x[i] * r;
            }
            for (var i = 0; i < k; i++)
            {
                for (var j = 0; j < k; j++)
                    meat[i, j] += u[i] * u[j];
            }
        }
        var v = RqcModels.Mul(RqcModels.Mul(bread, meat), bread);
        var coefficients = new JsonObject();
        for (var i = 0; i < k; i++)
        {
            var se = Math.Sqrt(v[i, i] * groups.Count / (groups.Count - 1.0));
            var z = beta[i] / se;
            coefficients[terms[i]] = new JsonObject
            {
                ["estimate"] = F(beta[i]), ["se"] = F(se), ["z"] = F(z), ["p"] = double.IsFinite(z) ? F(Stats.TwoSidedNormalP(z)) : null,
                ["wald95"] = new JsonArray(F(beta[i] - (1.959963984540054 * se)), F(beta[i] + (1.959963984540054 * se))),
            };
        }
        o["clusters"] = groups.Count;
        o["coefficients"] = coefficients;
        o["standardErrors"] = "cluster-robust (CR1) by task";
        return o;
    }

    private static Counts[] PerTask(IReadOnlyList<Judged> cell, IReadOnlyList<string> tasks)
    {
        var index = tasks.Select((t, i) => (t, i)).ToDictionary(p => p.t, p => p.i, StringComparer.Ordinal);
        var counts = new Counts[tasks.Count];
        foreach (var g in cell.GroupBy(j => j.TaskId))
            counts[index[g.Key]] = Counts.Of(g);
        return counts;
    }

    /// <summary>Counts summed over a resample of task indices (null: every task once).</summary>
    private static Counts Sum(Counts[] byTask, int[]? idx)
    {
        var sum = new Counts(0, 0, 0, 0);
        if (idx is null)
        {
            foreach (var c in byTask)
                sum += c;
            return sum;
        }
        foreach (var i in idx)
            sum += byTask[i];
        return sum;
    }

    /// <summary>Percentile 95% interval of a statistic over task resamples; resamples on which it is undefined are skipped.</summary>
    private static (double Lo, double Hi) Bootstrap(int tasks, Func<int[], double> statistic, int iterations, uint seed)
    {
        var rng = new Random(unchecked((int)seed));
        var values = new List<double>(iterations);
        var idx = new int[tasks];
        for (var it = 0; it < iterations; it++)
        {
            for (var j = 0; j < tasks; j++)
                idx[j] = rng.Next(tasks);
            if (statistic(idx) is var v && double.IsFinite(v))
                values.Add(v);
        }
        if (values.Count == 0)
            return (double.NaN, double.NaN);
        values.Sort();
        return (values[(int)(0.025 * (values.Count - 1))], values[(int)Math.Ceiling(0.975 * (values.Count - 1))]);
    }

    private static double Logistic(double x) => 1 / (1 + Math.Exp(-x));

    private static JsonValue? F(double v) => double.IsFinite(v) ? JsonValue.Create(v) : null;
}
