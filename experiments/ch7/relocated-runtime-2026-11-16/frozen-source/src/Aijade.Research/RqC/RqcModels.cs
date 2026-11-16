using System.Text.Json.Nodes;

using Aijade.Research.Statistics;

namespace Aijade.Research.RqC;

// Model-based analysis of the RQ-C skills, written for the audit of P2's statistical plan (2026-10-12). The plan in P2 §5 names a mixed-effects logistic regression with
// skill/task random effects as the primary model and a log-odds interaction; the harness instead reports a "log-odds
// interaction" computed from each cell's count of successful *executions* only (four numbers, no failures), which is a
// log ratio of execution counts, not a log-odds interaction, and counts a reused skill once per call. This class computes
// what the plan describes, on the unit P2 declares (the skill, outcome Y_s = skill usable), so the two can be compared:
//   1. the skill-level log-odds interaction from the 2×2×2 table (Wald test; Haldane correction only when a cell is empty);
//   2. a logistic regression Y_s ~ sv + ef + sv:ef by IRLS, with model-based and cluster-robust (sandwich) standard errors,
//      clustered by block (trial × task: the four conditions share it) and by task;
//   3. the mixed-effects logistic regression of the plan with a random intercept per task (one observation per skill makes a
//      per-skill random effect unidentifiable), fitted by maximum likelihood with Gauss–Hermite quadrature.
public static class RqcModels
{
    private sealed record Obs(double[] X, int Y, string Task, string Block);

    private static double Logistic(double x) => 1 / (1 + Math.Exp(-x));

    private static List<Obs> Data(IReadOnlyList<SkillState> skills) =>
        [.. skills.Where(s => s.CallCount > 0).Select(s =>
        {
            double sv = s.SelfVerificationCondition ? 1 : 0, ef = s.EnvFeedback ? 1 : 0;
            return new Obs([1, sv, ef, sv * ef], s.Success ? 1 : 0, s.TaskId, $"{s.Trial}|{s.TaskId}");
        })];

    /// <summary>
    /// The same models on the design's own unit: one observation per slot (trial × task × condition), the last skill
    /// generated for it, so every cell holds exactly one observation per block and regeneration cannot change the task mix
    /// of a cell. The McNemar test of the harness pairs on this unit; the conditional fit here is stratified by block.
    /// </summary>
    public static JsonObject AnalyzeSlots(IReadOnlyList<SkillState> skills)
    {
        var last = skills.Where(s => s.CallCount > 0)
            .GroupBy(s => (s.SelfVerificationCondition, s.EnvFeedback, s.Trial, s.TaskId))
            .Select(g => g.Last()).ToList();
        var result = Analyze(last, "slot (trial × task × condition; the last skill generated for it)");
        if (result["logisticRegression"]?["note"] is null)
            result["conditionalLogisticByBlock"] = FitConditional(Data(last), o => o.Block, "block (trial × task)");
        return result;
    }

    public static JsonObject Analyze(IReadOnlyList<SkillState> skills) => Analyze(skills, "skill");

    /// <summary>
    /// The harness's McNemar test (environment feedback OFF vs ON per self-verification × trial × task slot, last skill per
    /// slot) treats the pairs as independent, but a task recurs in many trials and its outcome is nearly fixed by the task.
    /// Durkalski et al.'s (2003) clustered McNemar statistic X² = (Σ_k (b_k − c_k))² / Σ_k (b_k − c_k)², clustering by task,
    /// is reported beside the naive one together with how many tasks the discordant pairs come from.
    /// </summary>
    public static JsonObject ClusteredMcNemar(IReadOnlyList<SkillState> skills)
    {
        var pairs = new Dictionary<(bool, int, string), (SkillState? Off, SkillState? On)>();
        foreach (var s in skills)
        {
            var key = (s.SelfVerificationCondition, s.Trial, s.TaskId);
            var e = pairs.GetValueOrDefault(key);
            pairs[key] = s.EnvFeedback ? (e.Off, s) : (s, e.On);
        }
        var perTask = new Dictionary<string, (int B, int C)>();
        int nPairs = 0, b = 0, c = 0;
        foreach (var ((_, _, task), (off, on)) in pairs)
        {
            if (off is null || on is null)
                continue;
            nPairs++;
            var e = perTask.GetValueOrDefault(task);
            if (!off.Success && on.Success)
            {
                b++;
                perTask[task] = (e.B + 1, e.C);
            }
            else if (off.Success && !on.Success)
            {
                c++;
                perTask[task] = (e.B, e.C + 1);
            }
        }
        var num = perTask.Values.Sum(v => v.B - v.C);
        var den = perTask.Values.Sum(v => (double)(v.B - v.C) * (v.B - v.C));
        var x2 = den > 0 ? num * (double)num / den : double.NaN;
        return new JsonObject
        {
            ["pairs"] = nPairs,
            ["b"] = b,
            ["c"] = c,
            ["tasksWithDiscordantPairs"] = perTask.Count,
            ["largestTaskShareOfDiscordant"] = F(b + c > 0 ? perTask.Values.Max(v => v.B + v.C) / (double)(b + c) : double.NaN),
            ["clusteredChiSquare"] = F(x2),
            ["clusteredP"] = double.IsFinite(x2) ? F(Stats.TwoSidedNormalP(Math.Sqrt(x2))) : null,
            ["method"] = "Durkalski et al. (2003) clustered McNemar, clusters = tasks",
        };
    }

    /// <summary>
    /// The self-assessment estimands of P2 §3.2, conditioned on the oracle's verdict — hallucinationRate = P(self-pass | unusable)
    /// = FP/(FP+TN), missRate = P(self-fail | usable) = FN/(FN+TP), agreement — and the two predictive values conditioned on the
    /// self-verdict (falseDiscoveryRate = P(unusable | self-pass), falseOmissionRate = P(usable | self-fail)), each with its own
    /// numerator and denominator, Wilson intervals and task-cluster bootstrap intervals (percentile and BCa).
    /// </summary>
    public static JsonObject Diagnostics(IReadOnlyList<SkillState> skills, int iterations = 10000, uint seed = 0x2545F491)
    {
        var verified = skills.Where(s => s.SelfVerdict is not null && s.LastExecutionOk is not null).ToList();
        // confusion counts: positive = self-pass, truth = usable (execution ok)
        static Confusion Count(IEnumerable<SkillState> v)
        {
            int tp = 0, fp = 0, fn = 0, tn = 0;
            foreach (var s in v)
            {
                var pass = s.SelfVerdict == "pass";
                var ok = s.LastExecutionOk == true;
                if (pass && ok)
                    tp++;
                else if (pass)
                    fp++;
                else if (ok)
                    fn++;
                else
                    tn++;
            }
            return new Confusion(tp, fp, fn, tn);
        }
        // (name, numerator, denominator) of every ratio statistic
        (string Name, Func<Confusion, int> Num, Func<Confusion, int> Den)[] stats =
        [
            ("hallucinationRate", c => c.Fp, c => c.Fp + c.Tn),
            ("missRate", c => c.Fn, c => c.Fn + c.Tp),
            ("agreement", c => c.Tp + c.Tn, c => c.N),
            ("falseDiscoveryRate", c => c.Fp, c => c.Fp + c.Tp),
            ("falseOmissionRate", c => c.Fn, c => c.Fn + c.Tn),
        ];
        static double? Ratio(int num, int den) => den > 0 ? num / (double)den : null;
        double? Difference(Confusion c) =>
            Ratio(stats[1].Num(c), stats[1].Den(c)) is { } miss && Ratio(stats[0].Num(c), stats[0].Den(c)) is { } hal ? miss - hal : null;

        var all = Count(verified);
        var byTask = verified.GroupBy(s => s.TaskId).Select(g => Count(g)).ToList();
        var boot = Enumerable.Range(0, stats.Length + 1).Select(_ => new List<double>()).ToArray();
        var rng = new Random((int)seed);
        for (var it = 0; it < iterations; it++)
        {
            var sum = new Confusion(0, 0, 0, 0);
            for (var k = 0; k < byTask.Count; k++)
                sum += byTask[rng.Next(byTask.Count)];
            for (var i = 0; i < stats.Length; i++)
            {
                if (Ratio(stats[i].Num(sum), stats[i].Den(sum)) is { } r)
                    boot[i].Add(r);
            }
            if (Difference(sum) is { } d)
                boot[stats.Length].Add(d);
        }
        // Leave-one-task-out values of each statistic, for the BCa acceleration (P2 §5 names BCa intervals).
        var jack = Enumerable.Range(0, stats.Length + 1).Select(_ => new List<double>()).ToArray();
        foreach (var t in byTask)
        {
            var rest = all - t;
            for (var i = 0; i < stats.Length; i++)
            {
                if (Ratio(stats[i].Num(rest), stats[i].Den(rest)) is { } r)
                    jack[i].Add(r);
            }
            if (Difference(rest) is { } d)
                jack[stats.Length].Add(d);
        }
        JsonObject Rate(int num, int den, List<double> b, List<double> j)
        {
            b.Sort();
            var o = new JsonObject { ["numerator"] = num, ["denominator"] = den, ["estimate"] = F(den > 0 ? num / (double)den : double.NaN) };
            if (den > 0)
            {
                var (lo, hi) = Wilson(num, den);
                o["wilson95"] = new JsonArray(F(lo), F(hi));
            }
            if (b.Count > 0)
                o["taskBootstrap95"] = new JsonArray(F(b[(int)(0.025 * (b.Count - 1))]), F(b[(int)Math.Ceiling(0.975 * (b.Count - 1))]));
            if (den > 0 && Bca(b, num / (double)den, j) is { } bca)
                o["taskBootstrapBca95"] = new JsonArray(F(bca.Lo), F(bca.Hi));
            return o;
        }
        JsonObject DifferenceNode()
        {
            var b = boot[stats.Length];
            b.Sort();
            if (Difference(all) is not { } est || b.Count == 0)
                return new JsonObject { ["note"] = "undefined: one of the two rates has no denominator" };
            var o = new JsonObject
            {
                ["estimate"] = F(est),
                ["taskBootstrap95"] = new JsonArray(F(b[(int)(0.025 * (b.Count - 1))]), F(b[(int)Math.Ceiling(0.975 * (b.Count - 1))])),
                ["shareOfResamplesAboveZero"] = F(b.Count(x => x > 0) / (double)b.Count),
            };
            if (Bca(b, est, jack[stats.Length]) is { } bca)
                o["taskBootstrapBca95"] = new JsonArray(F(bca.Lo), F(bca.Hi));
            return o;
        }
        var result = new JsonObject
        {
            ["n"] = all.N,
            ["tasks"] = byTask.Count,
            ["confusion"] = new JsonObject { ["tp"] = all.Tp, ["fp"] = all.Fp, ["fn"] = all.Fn, ["tn"] = all.Tn },
            ["usableShare"] = F(all.N > 0 ? (all.Tp + all.Fn) / (double)all.N : double.NaN),
        };
        for (var i = 0; i < stats.Length; i++)
            result[stats[i].Name] = Rate(stats[i].Num(all), stats[i].Den(all), boot[i], jack[i]);
        result["missMinusHallucination"] = DifferenceNode();
        result["definitions"] = "positive = self-pass, truth = oracle-usable; hallucinationRate = FP/(FP+TN), missRate = FN/(FN+TP), "
            + "falseDiscoveryRate = FP/(FP+TP), falseOmissionRate = FN/(FN+TN)";
        result["bootstrap"] = $"{iterations} resamples of the {byTask.Count} tasks; percentile and BCa (acceleration from the leave-one-task-out jackknife)";
        return result;
    }

    /// <summary>
    /// Regenerations after a failure and the recoveries among them, split by whether the regenerated code differs from the
    /// task's previous code in the same condition and trial. A recovery with unchanged code is not evidence that feedback
    /// reached the generator: a candidate the self-verifier rejected although it worked "recovers" when it is regenerated
    /// unchanged. <paramref name="codes"/> holds the extracted code of every step (candidates.jsonl), indexed like the steps.
    /// </summary>
    public static JsonObject ChangedCodeRecoveries(IReadOnlyList<StepRecord> steps, IReadOnlyList<string?> codes)
    {
        if (codes.Count != steps.Count)
            throw new ArgumentException($"{codes.Count} codes for {steps.Count} steps", nameof(codes));
        var last = new Dictionary<(string, int, string), string?>();
        int regenerations = 0, changed = 0, recoveries = 0, changedRecoveries = 0;
        for (var i = 0; i < steps.Count; i++)
        {
            var s = steps[i];
            var key = (s.Condition, s.Trial, s.TaskId);
            if (s.RegeneratedFromFailure)
            {
                var differs = !last.TryGetValue(key, out var previous) || previous != codes[i];
                regenerations++;
                if (differs)
                    changed++;
                if (s.ExecOk)
                {
                    recoveries++;
                    if (differs)
                        changedRecoveries++;
                }
            }
            if (!s.Reused)
                last[key] = codes[i];
        }
        return new JsonObject
        {
            ["regenerations"] = regenerations,
            ["regenerationsWithChangedCode"] = changed,
            ["recoveries"] = recoveries,
            ["recoveriesWithChangedCode"] = changedRecoveries,
        };
    }

    private readonly record struct Confusion(int Tp, int Fp, int Fn, int Tn)
    {
        public int N => Tp + Fp + Fn + Tn;

        public static Confusion operator +(Confusion a, Confusion b) => new(a.Tp + b.Tp, a.Fp + b.Fp, a.Fn + b.Fn, a.Tn + b.Tn);

        public static Confusion operator -(Confusion a, Confusion b) => new(a.Tp - b.Tp, a.Fp - b.Fp, a.Fn - b.Fn, a.Tn - b.Tn);
    }

    /// <summary>
    /// Bias-corrected and accelerated interval (Efron 1987) from sorted bootstrap replicates, the point estimate and the
    /// jackknife values; null when it cannot be formed (too few clusters or replicates).
    /// </summary>
    private static (double Lo, double Hi)? Bca(List<double> sorted, double estimate, List<double> jack, double level = 0.95)
    {
        if (sorted.Count < 100 || jack.Count < 3 || !double.IsFinite(estimate))
            return null;
        var b = sorted.Count;
        var below = (sorted.Count(x => x < estimate) + (0.5 * sorted.Count(x => x == estimate))) / b;
        var z0 = Stats.NormalQuantile(Math.Clamp(below, 0.5 / b, 1 - (0.5 / b)));
        var mean = jack.Average();
        double num = 0, den = 0;
        foreach (var j in jack)
        {
            var d = mean - j;
            num += d * d * d;
            den += d * d;
        }
        var a = den > 0 ? num / (6 * Math.Pow(den, 1.5)) : 0;
        double At(double alpha)
        {
            var z = Stats.NormalQuantile(alpha);
            var q = Stats.NormalCdf(z0 + ((z0 + z) / (1 - (a * (z0 + z)))));
            var pos = Math.Clamp(q, 0, 1) * (b - 1);
            var lo = (int)Math.Floor(pos);
            var hi = Math.Min(b - 1, lo + 1);
            return sorted[lo] + ((sorted[hi] - sorted[lo]) * (pos - lo));
        }
        return (At((1 - level) / 2), At((1 + level) / 2));
    }

    private static (double Lo, double Hi) Wilson(int k, int n, double z = 1.959963984540054)
    {
        var p = k / (double)n;
        var denom = 1 + (z * z / n);
        var centre = (p + (z * z / (2 * n))) / denom;
        var half = z * Math.Sqrt((p * (1 - p) / n) + (z * z / (4.0 * n * n))) / denom;
        return (centre - half, centre + half);
    }

    private static JsonObject Analyze(IReadOnlyList<SkillState> skills, string unit)
    {
        var data = Data(skills);
        var cells = new JsonObject();
        var n = new double[2, 2, 2]; // [sv, ef, success]
        foreach (var o in data)
            n[(int)o.X[1], (int)o.X[2], o.Y]++;
        foreach (var sv in new[] { 0, 1 })
        {
            foreach (var ef in new[] { 0, 1 })
                cells[$"sv{sv}-ef{ef}"] = new JsonObject { ["success"] = (int)n[sv, ef, 1], ["failure"] = (int)n[sv, ef, 0] };
        }

        // 1. Skill-level log-odds interaction: logit(p11) − logit(p10) − logit(p01) + logit(p00).
        var any0 = false;
        foreach (var v in n)
            any0 |= v == 0;
        double C(int sv, int ef, int y) => n[sv, ef, y] + (any0 ? 0.5 : 0);
        double Logit(int sv, int ef) => Math.Log(C(sv, ef, 1) / C(sv, ef, 0));
        var est = Logit(1, 1) - Logit(1, 0) - Logit(0, 1) + Logit(0, 0);
        double inv = 0;
        foreach (var sv in new[] { 0, 1 })
        {
            foreach (var ef in new[] { 0, 1 })
            {
                foreach (var y in new[] { 0, 1 })
                    inv += 1 / C(sv, ef, y);
            }
        }
        var se = Math.Sqrt(inv);

        var result = new JsonObject
        {
            ["unit"] = unit,
            ["outcome"] = "Y_s (skill usable: success/calls ≥ 0.5)",
            ["nSkills"] = data.Count,
            ["nTasks"] = data.Select(o => o.Task).Distinct().Count(),
            ["nBlocks"] = data.Select(o => o.Block).Distinct().Count(),
            ["cells"] = cells,
            ["skillLevelInteraction"] = Wald(est, se, any0 ? "Haldane +0.5 (a cell is empty)" : "none"),
        };
        if (any0)
        {
            // A cell with no successes or no failures separates the data: the maximum-likelihood estimates do not exist.
            const string why = "not estimable: a cell has no successes or no failures (complete separation)";
            result["logisticRegression"] = new JsonObject { ["note"] = why };
            result["mixedLogistic"] = new JsonObject { ["note"] = why };
            return result;
        }
        var glm = FitLogit(data);
        result["logisticRegression"] = glm.Json;
        result["mixedLogistic"] = FitMixed(data, glm.Beta);
        result["conditionalLogistic"] = FitConditional(data, o => o.Task, "task");
        return result;
    }

    /// <summary>A finite number, or null (a degenerate fit is reported as missing, not as a number).</summary>
    private static JsonValue? F(double v) => double.IsFinite(v) ? JsonValue.Create(v) : null;

    private static JsonObject Wald(double est, double se, string? correction = null)
    {
        var z = est / se;
        var o = new JsonObject { ["estimate"] = F(est), ["se"] = F(se), ["z"] = F(z), ["p"] = double.IsFinite(z) ? F(Stats.TwoSidedNormalP(z)) : null };
        if (correction is not null)
            o["correction"] = correction;
        return o;
    }

    private static readonly string[] Terms = ["intercept", "selfVerification", "envFeedback", "interaction"];

    private sealed record Glm(double[] Beta, JsonObject Json);

    // ---- logistic regression (IRLS) with model-based and cluster-robust standard errors -------------------------------

    private static Glm FitLogit(List<Obs> data)
    {
        const int K = 4;
        var beta = new double[K];
        double[,] info = new double[K, K];
        for (var iter = 0; iter < 100; iter++)
        {
            info = new double[K, K];
            var score = new double[K];
            foreach (var o in data)
            {
                var p = Logistic(Dot(o.X, beta));
                var w = p * (1 - p);
                for (var i = 0; i < K; i++)
                {
                    score[i] += o.X[i] * (o.Y - p);
                    for (var j = 0; j < K; j++)
                        info[i, j] += w * o.X[i] * o.X[j];
                }
            }
            var step = Solve(info, score);
            for (var i = 0; i < K; i++)
                beta[i] += step[i];
            if (step.Max(Math.Abs) < 1e-10)
                break;
        }
        var cov = Invert(info);
        var json = new JsonObject { ["method"] = "maximum likelihood (IRLS)" };
        var model = new JsonObject();
        for (var i = 0; i < K; i++)
            model[Terms[i]] = Wald(beta[i], Math.Sqrt(cov[i, i]));
        json["modelBased"] = model;
        foreach (var (name, key) in new (string, Func<Obs, string>)[] { ("clusterRobustByBlock", o => o.Block), ("clusterRobustByTask", o => o.Task) })
        {
            var robust = Sandwich(data, beta, cov, key);
            var terms = new JsonObject();
            for (var i = 0; i < K; i++)
                terms[Terms[i]] = Wald(beta[i], Math.Sqrt(robust[i, i]));
            terms["clusters"] = data.Select(key).Distinct().Count();
            json[name] = terms;
        }
        return new Glm(beta, json);
    }

    /// <summary>Cluster-robust covariance (CR1): bread · Σ_g U_g U_gᵀ · bread · G/(G−1).</summary>
    private static double[,] Sandwich(List<Obs> data, double[] beta, double[,] bread, Func<Obs, string> cluster)
    {
        const int K = 4;
        var meat = new double[K, K];
        var groups = data.GroupBy(cluster).ToList();
        foreach (var g in groups)
        {
            var u = new double[K];
            foreach (var o in g)
            {
                var r = o.Y - Logistic(Dot(o.X, beta));
                for (var i = 0; i < K; i++)
                    u[i] += o.X[i] * r;
            }
            for (var i = 0; i < K; i++)
            {
                for (var j = 0; j < K; j++)
                    meat[i, j] += u[i] * u[j];
            }
        }
        var gcount = groups.Count;
        var v = Mul(Mul(bread, meat), bread);
        for (var i = 0; i < K; i++)
        {
            for (var j = 0; j < K; j++)
                v[i, j] *= gcount / (gcount - 1.0);
        }
        return v;
    }

    // ---- mixed-effects logistic regression: random intercept per task, Gauss–Hermite quadrature -----------------------

    /// <summary>Nodes and weights of m-point Gauss–Hermite quadrature (weight exp(−x²)).</summary>

    public static (double[] Nodes, double[] Weights) Hermite(int m)
    {
        // Golub–Welsch: eigenvalues of the Jacobi matrix of the physicists' Hermite polynomials (by Newton on the
        // three-term recurrence, which is accurate enough for m ≤ 60).
        var nodes = new double[m];
        var weights = new double[m];
        for (var i = 0; i < m; i++)
        {
            var z = i == 0 ? Math.Sqrt(2.0 * m + 1) - (1.85575 * Math.Pow(2.0 * m + 1, -1.0 / 6))
                : i == 1 ? nodes[0] - (1.14 * Math.Pow(m, 0.426) / nodes[0])
                : i == 2 ? (1.86 * nodes[1]) - (0.86 * nodes[0])
                : i == 3 ? (1.91 * nodes[2]) - (0.91 * nodes[1])
                : (2.0 * nodes[i - 1]) - nodes[i - 2];
            double pp = 0;
            for (var iter = 0; iter < 100; iter++)
            {
                double p1 = Math.Pow(Math.PI, -0.25), p2 = 0;
                for (var j = 1; j <= m; j++)
                {
                    var p3 = p2;
                    p2 = p1;
                    p1 = (z * Math.Sqrt(2.0 / j) * p2) - (Math.Sqrt((j - 1.0) / j) * p3);
                }
                pp = Math.Sqrt(2.0 * m) * p2;
                var dz = p1 / pp;
                z -= dz;
                if (Math.Abs(dz) < 1e-14)
                    break;
            }
            nodes[i] = z;
            weights[i] = 2 / (pp * pp);
        }
        return (nodes, weights);
    }

    private static JsonObject FitMixed(List<Obs> data, double[] start)
    {
        var (gh, gw) = Hermite(20);
        var groups = data.GroupBy(o => o.Task).Select(g => g.ToList()).ToList();

        // θ = (β0..β3, log σ). Marginal log-likelihood per task g: log ∫ exp(ℓ_g(u)) φ(u; 0, σ²) du, by *adaptive*
        // Gauss–Hermite quadrature (centred at the mode of the integrand, scaled by its curvature), which stays accurate
        // when σ is large — tasks whose skills almost always succeed or always fail push σ up.
        double ClusterLog(List<Obs> g, double[] th, double sigma)
        {
            var etas = g.Select(o => Dot(o.X, th)).ToArray();
            double F(double u)
            {
                double ll = 0;
                for (var i = 0; i < etas.Length; i++)
                    ll += g[i].Y == 1 ? -Softplus(-(etas[i] + u)) : -Softplus(etas[i] + u);
                return ll - (u * u / (2 * sigma * sigma));
            }
            double D1(double u) => g.Select((o, i) => o.Y - Logistic(etas[i] + u)).Sum() - (u / (sigma * sigma));
            double D2(double u) => -g.Select((_, i) => { var p = Logistic(etas[i] + u); return p * (1 - p); }).Sum() - (1 / (sigma * sigma));
            double mode = 0;
            for (var it = 0; it < 50; it++)
            {
                var step = D1(mode) / D2(mode);
                mode -= Math.Clamp(step, -5, 5);
                if (Math.Abs(step) < 1e-10)
                    break;
            }
            var scale = 1 / Math.Sqrt(-D2(mode));
            var terms = new double[gh.Length];
            for (var k = 0; k < gh.Length; k++)
            {
                var u = mode + (Math.Sqrt(2) * scale * gh[k]);
                terms[k] = Math.Log(gw[k]) + (gh[k] * gh[k]) + F(u);
            }
            var mx = terms.Max();
            return mx + Math.Log(terms.Sum(t => Math.Exp(t - mx))) + Math.Log(Math.Sqrt(2) * scale) - Math.Log(Math.Sqrt(2 * Math.PI) * sigma);
        }

        double NegLogLik(double[] th)
        {
            var sigma = Math.Exp(th[4]);
            return -groups.Sum(g => ClusterLog(g, th, sigma));
        }

        var theta = new double[] { start[0], start[1], start[2], start[3], Math.Log(0.5) };
        // σ is bounded to [0.01, 20] (log scale −4.6…3.0): a likelihood still rising at the upper bound means tasks behave
        // almost deterministically, and the fit is flagged rather than run off to infinity.
        double Bounded(double[] th) => NegLogLik([th[0], th[1], th[2], th[3], Math.Clamp(th[4], Math.Log(0.01), Math.Log(20))]);
        var opt = Bfgs(Bounded, theta);
        opt[4] = Math.Clamp(opt[4], Math.Log(0.01), Math.Log(20));
        var atBound = opt[4] >= Math.Log(20) - 1e-6;
        var hess = NumericHessian(NegLogLik, opt);
        var json = new JsonObject
        {
            ["method"] = "maximum likelihood, random intercept per task, 20-point adaptive Gauss–Hermite quadrature",
            ["logLik"] = F(-NegLogLik(opt)),
            ["sigmaTask"] = F(Math.Exp(opt[4])),
        };
        if (atBound)
            json["warning"] = "task standard deviation at its upper bound (20): outcomes are nearly determined by the task, so the random-intercept model is at the edge of estimability";
        double[,] cov;
        try
        {
            cov = Invert(hess);
        }
        catch (InvalidOperationException)
        {
            json["note"] = "Hessian singular: standard errors unavailable";
            return json;
        }
        var terms = new JsonObject();
        for (var i = 0; i < 4; i++)
            terms[Terms[i]] = Wald(opt[i], Math.Sqrt(cov[i, i]));
        json["fixedEffects"] = terms;
        // σ near zero sits on the boundary; its Wald SE (on the log scale) is reported but not used for testing.
        json["logSigmaSe"] = F(Math.Sqrt(Math.Max(cov[4, 4], 0)));
        return json;
    }

    // ---- conditional logistic regression, stratified by task ------------------------------------------------------------

    /// <summary>
    /// Conditional likelihood given the number of usable skills per task: task intercepts drop out entirely, and tasks
    /// whose skills all succeed (or all fail) carry no information. The denominator Σ_{|S|=m} exp(Σ_{i∈S} x_iβ) is computed
    /// by the usual recursion over the stratum (in log space).
    /// </summary>
    private static JsonObject FitConditional(List<Obs> data, Func<Obs, string> stratum, string by)
    {
        var strata = data.GroupBy(stratum).Select(g => g.ToList())
            .Where(g => g.Any(o => o.Y == 1) && g.Any(o => o.Y == 0)).ToList();
        if (strata.Count == 0)
        {
            return new JsonObject
            {
                ["method"] = $"conditional maximum likelihood, stratified by {by}",
                ["informativeStrata"] = 0,
                ["informativeSkills"] = 0,
                ["note"] = "not estimable: every task's skills all succeed or all fail",
            };
        }
        double NegLogLik(double[] b)
        {
            double total = 0;
            foreach (var g in strata)
            {
                var m = g.Count(o => o.Y == 1);
                var eta = g.Select(o => (o.X[1] * b[0]) + (o.X[2] * b[1]) + (o.X[3] * b[2])).ToArray();
                // logB[j] = log Σ over size-j subsets of the first i items
                var logB = new double[m + 1];
                Array.Fill(logB, double.NegativeInfinity);
                logB[0] = 0;
                for (var i = 0; i < g.Count; i++)
                {
                    for (var j = Math.Min(i + 1, m); j >= 1; j--)
                        logB[j] = LogAdd(logB[j], logB[j - 1] + eta[i]);
                }
                total += g.Select((o, i) => o.Y == 1 ? eta[i] : 0).Sum() - logB[m];
            }
            return -total;
        }
        var opt = Bfgs(NegLogLik, new double[3]);
        var json = new JsonObject
        {
            ["method"] = $"conditional maximum likelihood, stratified by {by}",
            ["informativeStrata"] = strata.Count,
            ["informativeSkills"] = strata.Sum(g => g.Count),
        };
        double[,] cov;
        try
        {
            cov = Invert(NumericHessian(NegLogLik, opt));
        }
        catch (InvalidOperationException)
        {
            json["note"] = "Hessian singular: a contrast is not identified within tasks";
            return json;
        }
        var terms = new JsonObject();
        for (var i = 0; i < 3; i++)
            terms[Terms[i + 1]] = Wald(opt[i], Math.Sqrt(cov[i, i]));
        if (Enumerable.Range(0, 3).Any(i => !(Math.Sqrt(cov[i, i]) < 50)))
        {
            // The likelihood keeps rising along some direction (e.g. one cell succeeds in every informative stratum):
            // the estimates run off to infinity and their standard errors are meaningless.
            json["note"] = "not estimable: quasi-separation within strata (the estimates diverge)";
            return json;
        }
        json["effects"] = terms;
        return json;
    }

    private static double LogAdd(double a, double b) =>
        double.IsNegativeInfinity(a) ? b : double.IsNegativeInfinity(b) ? a : Math.Max(a, b) + Math.Log(1 + Math.Exp(-Math.Abs(a - b)));

    private static double Softplus(double x) => x > 30 ? x : x < -30 ? Math.Exp(x) : Math.Log(1 + Math.Exp(x));

    private static double[] Bfgs(Func<double[], double> f, double[] x0)
    {
        var k = x0.Length;
        var x = (double[])x0.Clone();
        var h = Identity(k);
        var g = Gradient(f, x);
        var fx = f(x);
        for (var iter = 0; iter < 500; iter++)
        {
            var d = new double[k];
            for (var i = 0; i < k; i++)
            {
                for (var j = 0; j < k; j++)
                    d[i] -= h[i, j] * g[j];
            }
            double t = 1, fnew;
            double[] xnew;
            while (true)
            {
                xnew = [.. x.Select((v, i) => v + (t * d[i]))];
                fnew = f(xnew);
                if (fnew <= fx + (1e-4 * t * Dot(g, d)) || t < 1e-12)
                    break;
                t /= 2;
            }
            var gnew = Gradient(f, xnew);
            var s = xnew.Select((v, i) => v - x[i]).ToArray();
            var y = gnew.Select((v, i) => v - g[i]).ToArray();
            var sy = Dot(s, y);
            if (sy > 1e-12)
            {
                var hy = new double[k];
                for (var i = 0; i < k; i++)
                {
                    for (var j = 0; j < k; j++)
                        hy[i] += h[i, j] * y[j];
                }
                var yhy = Dot(y, hy);
                for (var i = 0; i < k; i++)
                {
                    for (var j = 0; j < k; j++)
                        h[i, j] += (((sy + yhy) * s[i] * s[j]) / (sy * sy)) - (((hy[i] * s[j]) + (s[i] * hy[j])) / sy);
                }
            }
            var done = Math.Abs(fx - fnew) < 1e-12 && gnew.Max(Math.Abs) < 1e-6;
            x = xnew;
            g = gnew;
            fx = fnew;
            if (done)
                break;
        }
        return x;
    }

    private static double[] Gradient(Func<double[], double> f, double[] x)
    {
        var g = new double[x.Length];
        for (var i = 0; i < x.Length; i++)
        {
            var e = 1e-5 * Math.Max(1, Math.Abs(x[i]));
            var a = (double[])x.Clone();
            var b = (double[])x.Clone();
            a[i] += e;
            b[i] -= e;
            g[i] = (f(a) - f(b)) / (2 * e);
        }
        return g;
    }

    private static double[,] NumericHessian(Func<double[], double> f, double[] x)
    {
        var k = x.Length;
        var h = new double[k, k];
        for (var i = 0; i < k; i++)
        {
            var e = 1e-4 * Math.Max(1, Math.Abs(x[i]));
            var a = (double[])x.Clone();
            var b = (double[])x.Clone();
            a[i] += e;
            b[i] -= e;
            var ga = Gradient(f, a);
            var gb = Gradient(f, b);
            for (var j = 0; j < k; j++)
                h[i, j] = (ga[j] - gb[j]) / (2 * e);
        }
        for (var i = 0; i < k; i++)
        {
            for (var j = i + 1; j < k; j++)
                h[i, j] = h[j, i] = (h[i, j] + h[j, i]) / 2;
        }
        return h;
    }

    // ---- small dense linear algebra ----------------------------------------------------------------------------------

    internal static double Dot(double[] a, double[] b)
    {
        double s = 0;
        for (var i = 0; i < Math.Min(a.Length, b.Length); i++)
            s += a[i] * b[i];
        return s;
    }

    private static double[,] Identity(int k)
    {
        var m = new double[k, k];
        for (var i = 0; i < k; i++)
            m[i, i] = 1;
        return m;
    }

    internal static double[,] Mul(double[,] a, double[,] b)
    {
        int n = a.GetLength(0), m = b.GetLength(1), k = a.GetLength(1);
        var c = new double[n, m];
        for (var i = 0; i < n; i++)
        {
            for (var j = 0; j < m; j++)
            {
                for (var t = 0; t < k; t++)
                    c[i, j] += a[i, t] * b[t, j];
            }
        }
        return c;
    }

    internal static double[] Solve(double[,] a, double[] b)
    {
        var inv = Invert(a);
        var k = b.Length;
        var x = new double[k];
        for (var i = 0; i < k; i++)
        {
            for (var j = 0; j < k; j++)
                x[i] += inv[i, j] * b[j];
        }
        return x;
    }

    internal static double[,] Invert(double[,] a)
    {
        var k = a.GetLength(0);
        var m = new double[k, 2 * k];
        for (var i = 0; i < k; i++)
        {
            for (var j = 0; j < k; j++)
                m[i, j] = a[i, j];
            m[i, k + i] = 1;
        }
        for (var c = 0; c < k; c++)
        {
            var piv = c;
            for (var r = c + 1; r < k; r++)
            {
                if (Math.Abs(m[r, c]) > Math.Abs(m[piv, c]))
                    piv = r;
            }
            if (Math.Abs(m[piv, c]) < 1e-14)
                throw new InvalidOperationException("singular matrix");
            if (piv != c)
            {
                for (var j = 0; j < 2 * k; j++)
                    (m[c, j], m[piv, j]) = (m[piv, j], m[c, j]);
            }
            var d = m[c, c];
            for (var j = 0; j < 2 * k; j++)
                m[c, j] /= d;
            for (var r = 0; r < k; r++)
            {
                if (r == c)
                    continue;
                var f = m[r, c];
                for (var j = 0; j < 2 * k; j++)
                    m[r, j] -= f * m[c, j];
            }
        }
        var inv = new double[k, k];
        for (var i = 0; i < k; i++)
        {
            for (var j = 0; j < k; j++)
                inv[i, j] = m[i, k + j];
        }
        return inv;
    }
}
