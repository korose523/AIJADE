using Aijade.Growth.Benchmark;
using Aijade.Growth.Metrics;
using Aijade.Memory.Development;

namespace Aijade.Growth.Pilot;

// §5.3 / §5.4 mechanism-level simulator: each configuration installs a real PolicyStorage, every benchmark session runs
// through the genuine GrowthLoop on in-memory ports, and every metric is computed from the committed memory set — never
// from a configuration flag. Still a deterministic simulation: no real LLM, database or human subjects.

/// <summary>The §5.4 memory / proactivity metrics plus the identity block, per dataset.</summary>
public sealed record DatasetMetrics(
    double Fub, double EpNet, double EpRate, double Gc, double Precision, double Recall, double Cr, double Fcr, double StoredCount, double CoreStability,
    double IdentityDrift, double SkillRetention)
{
    /// <summary>Metric keys in their recorded order.</summary>
    public static IReadOnlyList<string> Keys { get; } =
        ["fub", "epNet", "epRate", "gc", "precision", "recall", "cr", "fcr", "storedCount", "coreStability", "identityDrift", "skillRetention"];

    public double this[string key] => key switch
    {
        "fub" => Fub,
        "epNet" => EpNet,
        "epRate" => EpRate,
        "gc" => Gc,
        "precision" => Precision,
        "recall" => Recall,
        "cr" => Cr,
        "fcr" => Fcr,
        "storedCount" => StoredCount,
        "coreStability" => CoreStability,
        "identityDrift" => IdentityDrift,
        "skillRetention" => SkillRetention,
        _ => throw new ArgumentOutOfRangeException(nameof(key), key, "unknown metric"),
    };
}

public sealed record ConfigResult(MechanismConfig Config, IReadOnlyDictionary<string, IReadOnlyList<double>> PerDataset, DatasetMetrics Metrics);

public static class Simulator
{
    /// <summary>Per-role predicted future value (HAC gate) and importance (threshold baselines).</summary>
    private static readonly Dictionary<string, (double Fv, double Imp)> RoleProps = new(StringComparer.Ordinal)
    {
        ["preference_early"] = (0.40, 0.50),
        ["preference_late"] = (0.85, 0.80),
        ["conflict_early"] = (0.60, 0.70),
        ["conflict_late"] = (0.65, 0.75),
        ["lowfreq_highvalue"] = (1.00, 0.95),
        ["highfreq_lowvalue"] = (0.05, 0.10),
        // The one role CDI exists to block: attractive to the non-CDI gates (high salience) with little future utility, so
        // the CDI ablation is identifiable.
        ["emotion_high_lowfact"] = (0.10, 0.85),
        ["delayed_useful"] = (0.95, 0.45),
        ["poison"] = (0.00, 0.30),
        ["relationship_boundary"] = (0.70, 0.70),
        ["neutral_fact"] = (0.30, 0.50),
    };

    private static readonly InterestComponents Components = new(0.6, 0.5, 0.7, 0.5, 0.6, 0.5, 0.2, 0.1, 0.1);

    private sealed class SessionSearch : ISearchPort
    {
        public IReadOnlyList<RawHit> Current { get; set; } = [];

        public Task<IReadOnlyList<RawHit>> SearchAsync(string query, IReadOnlyList<string> sourceTypes, CancellationToken cancellationToken = default) =>
            Task.FromResult(Current);
    }

    private static List<IReadOnlyList<RawHit>> BuildSessionHits(LongitudinalDataset dataset)
    {
        var bySession = new Dictionary<int, List<RawHit>>();
        foreach (var stmt in dataset.Statements)
        {
            var (fv, imp) = RoleProps[stmt.Role];
            var meta = new MemoryMeta(stmt.Id, stmt.SessionIndex, stmt.IsTrue, stmt.Role, stmt.IsDistractor, stmt.IsContradictionLate, stmt.Contradicts,
                stmt.IsContradictionLate && stmt.Contradicts is not null ? stmt.Contradicts : stmt.Id, fv, imp);
            if (!bySession.TryGetValue(stmt.SessionIndex, out var list))
                bySession[stmt.SessionIndex] = list = [];
            list.Add(new RawHit(MemoryPolicies.EncodeLocator(meta), stmt.Role, stmt.Text, 0));
        }
        var max = bySession.Keys.Max();
        return Enumerable.Range(0, max + 1).Select(s => (IReadOnlyList<RawHit>)(bySession.GetValueOrDefault(s) ?? [])).ToList();
    }

    private static async Task<DatasetMetrics> SimulateDatasetAsync(MechanismConfig config, LongitudinalDataset dataset, int budget, CancellationToken cancellationToken)
    {
        var llm = new StubLlm();
        var policy = new PolicyStorage(new InMemoryStorage(), MemoryPolicies.ParamsFrom(config, budget, MemoryPolicies.MakeReflection(llm)));
        var search = new SessionSearch();
        var scheduler = new InMemoryScheduler();
        scheduler.MarkUnlimited("growth_loop");
        var loop = new GrowthLoop(new GrowthPorts(policy, scheduler, search, new InMemorySigning(), llm, new GrowthIds(), TimeZoneInfo.Utc),
            "agent-pilot", $"scope-{dataset.Id}");
        var sessionHits = BuildSessionHits(dataset);
        for (var s = 0; s < sessionHits.Count; s++)
        {
            search.Current = sessionHits[s];
            await loop.RunOnceAsync(new RunOnceInput($"session-{s}", [$"e{s}"], Components, 0.7, 0.6, 0.5, $"learn session {s}", "consolidate statement", 0.5,
                QuestionType.Everyday, $"session-{s}"), cancellationToken).ConfigureAwait(false);
        }
        return ComputeDatasetMetrics(policy.Committed, dataset, budget);
    }

    /// <summary>Every metric from the genuinely committed memory set and the dataset ground truth.</summary>
    public static DatasetMetrics ComputeDatasetMetrics(IReadOnlyList<MemoryMeta> committed, LongitudinalDataset dataset, int budget)
    {
        var committedIds = committed.Select(m => m.StmtId).ToHashSet(StringComparer.Ordinal);

        // Effective proactivity over the committed substrate: valuable true memories are worth sharing (accepted useful),
        // true low-value clutter is over-sharing (intrusive), admitted false facts are sharing without evidence (unjustified).
        int acceptedUseful = 0, intrusive = 0, unjustified = 0, distractorsCommitted = 0;
        foreach (var m in committed)
        {
            if (!m.IsTrue)
            {
                unjustified++;
                continue;
            }
            if (m.IsDistractor || m.Role == "neutral_fact")
            {
                intrusive++;
                if (m.IsDistractor)
                    distractorsCommitted++;
                continue;
            }
            if (m.Role is { } role && SyntheticLongitudinal.ValuableRoles.Contains(role))
                acceptedUseful++;
        }
        var ep = Formulas.EffectiveProactivity(acceptedUseful, intrusive, unjustified);

        var golden = new HashSet<string>(StringComparer.Ordinal);
        foreach (var q in dataset.TaskQueries)
            golden.UnionWith(q.RelevantTrueIds);
        var tp = golden.Count(committedIds.Contains);
        var pr = Formulas.EvidencePrecisionRecall([.. Enumerable.Repeat(true, tp), .. Enumerable.Repeat(false, distractorsCommitted)], golden.Count);
        var taskResults = dataset.TaskQueries.Select(q => new TaskResult(q.Weight, q.RelevantTrueIds.Any(committedIds.Contains) ? 1 : 0)).ToList();
        var fub = Formulas.FutureUtilityAtBudget(budget, committedIds.Count, taskResults);

        var pairs = dataset.Statements.Where(s => s.IsContradictionLate && s.Contradicts is not null).Select(s => (Early: s.Contradicts!, Late: s.Id)).ToList();
        var cr = Formulas.ContradictionRetention(pairs.Count, pairs.Count(p => committedIds.Contains(p.Early) && committedIds.Contains(p.Late)));

        var poisonIds = dataset.Statements.Where(s => s.Role == "poison").Select(s => s.Id).ToList();
        var fcr = Formulas.FalseConsolidationRate(poisonIds.Count, poisonIds.Count(committedIds.Contains));

        // GC: the fraction of developmental learning events whose evidence stays consolidated at the end of the run.
        var gc = Formulas.GrowthCoherence(dataset.Statements.Count, committedIds.Count);

        var counts = IdentityMetrics.Count(committed) with { TotalSkills = dataset.Statements.Count(s => s.Role == "lowfreq_highvalue") };
        return new DatasetMetrics(fub, ep.Net, ep.Rate, gc, pr.Precision, pr.Recall, cr, fcr, committedIds.Count, IdentityMetrics.CoreStability(counts),
            IdentityMetrics.IdentityDrift(counts), IdentityMetrics.SkillRetention(counts));
    }

    /// <summary>Every configuration over the whole benchmark. Deterministic; datasets run concurrently (they share no state).</summary>
    public static async Task<IReadOnlyList<ConfigResult>> SimulateAllAsync(
        SyntheticLongitudinalBenchmark benchmark, IReadOnlyList<MechanismConfig> configs, CancellationToken cancellationToken = default)
    {
        var results = new List<ConfigResult>();
        foreach (var config in configs)
        {
            var per = await Task.WhenAll(benchmark.Datasets.Select(d =>
                Task.Run(() => SimulateDatasetAsync(config, d, benchmark.Scale.BudgetPerDataset, cancellationToken), cancellationToken))).ConfigureAwait(false);
            var perDataset = DatasetMetrics.Keys.ToDictionary(k => k, k => (IReadOnlyList<double>)per.Select(m => m[k]).ToList(), StringComparer.Ordinal);
            double M(string k) => Stats.Mean(perDataset[k]);
            var metrics = new DatasetMetrics(M("fub"), M("epNet"), M("epRate"), M("gc"), M("precision"), M("recall"), M("cr"), M("fcr"),
                Math.Floor(M("storedCount") + 0.5), M("coreStability"), M("identityDrift"), M("skillRetention"));
            results.Add(new ConfigResult(config, perDataset, metrics));
        }
        return results;
    }
}
