using System.Text.Json.Nodes;

using Aijade.Growth.Metrics;

namespace Aijade.Growth.Benchmark;

// §39.1 / §5.2 deterministic synthetic longitudinal benchmark: multi-day timelines containing preference drift, conflicting
// facts, low-frequency high-value events, high-frequency noise, high-emotion low-fact events, delayed-usefulness
// information, memory poisoning and relationship-boundary shifts. Only a seeded mulberry32 is used, so a seed yields a
// byte-identical benchmark (same JSON, hence the same SHA-256).

/// <param name="Id">st_{globalIndex}.</param>
/// <param name="DatasetId">Scenario index.</param>
/// <param name="SessionIndex">Session within the scenario.</param>
/// <param name="GlobalIndex">Index across all scenarios.</param>
/// <param name="WindowIndex">Time window.</param>
/// <param name="Text">{role}@d{d}s{session}#{local}.</param>
/// <param name="IsTrue">Ground truth: false for poison.</param>
/// <param name="Role">Statement role.</param>
/// <param name="IsDistractor">High-frequency low-value or high-emotion low-fact.</param>
/// <param name="IsContradictionLate">The late member of a contradiction pair.</param>
/// <param name="Contradicts">The earlier conflict_early statement, for a late member.</param>
public sealed record Statement(
    string Id, int DatasetId, int SessionIndex, int GlobalIndex, int WindowIndex, string Text, bool IsTrue, string Role, bool IsDistractor,
    bool IsContradictionLate, string? Contradicts = null);

/// <summary>A held-out task query; <see cref="RelevantTrueIds"/> is the golden set retrieval should hit.</summary>
public sealed record TaskQuery(string Id, int DatasetId, int WindowIndex, double Weight, IReadOnlyList<string> RelevantTrueIds);

public sealed record LongitudinalDataset(int Id, IReadOnlyList<Statement> Statements, IReadOnlyList<TaskQuery> TaskQueries);

public sealed record BenchmarkScale(
    int Datasets, int SessionsPerDataset, int StatementsPerSession, int Windows, double SessionsPerWindow, double ContradictionRate,
    double DistractorRate, int BudgetPerDataset, int TotalStatements)
{
    /// <summary>12 datasets × 20 sessions × 8 statements = 1920; 6 windows; 15% contradictions; 10% distractors; budget 200.</summary>
    public static BenchmarkScale Default { get; } = new(12, 20, 8, 6, 12 * 20 / 6.0, 0.15, 0.10, 200, 12 * 20 * 8);
}

public sealed record ContradictionPair(string EarlyId, string LateId);

public sealed record SyntheticLongitudinalBenchmark(
    double Seed, BenchmarkScale Scale, IReadOnlyList<LongitudinalDataset> Datasets, IReadOnlyList<ContradictionPair> Contradictions,
    IReadOnlyList<string> Distractors)
{
    /// <summary>The benchmark JSON in its recorded layout (member order included).</summary>
    public JsonObject ToJson() => new()
    {
        ["seed"] = Seed,
        ["scale"] = new JsonObject
        {
            ["datasets"] = Scale.Datasets,
            ["sessionsPerDataset"] = Scale.SessionsPerDataset,
            ["statementsPerSession"] = Scale.StatementsPerSession,
            ["windows"] = Scale.Windows,
            ["sessionsPerWindow"] = Scale.SessionsPerWindow,
            ["contradictionRate"] = Scale.ContradictionRate,
            ["distractorRate"] = Scale.DistractorRate,
            ["budgetPerDataset"] = Scale.BudgetPerDataset,
            ["totalStatements"] = Scale.TotalStatements,
        },
        ["datasets"] = new JsonArray([.. Datasets.Select(d => (JsonNode)new JsonObject
        {
            ["id"] = d.Id,
            ["statements"] = new JsonArray([.. d.Statements.Select(StatementJson)]),
            ["taskQueries"] = new JsonArray([.. d.TaskQueries.Select(q => (JsonNode)new JsonObject
            {
                ["id"] = q.Id,
                ["datasetId"] = q.DatasetId,
                ["windowIndex"] = q.WindowIndex,
                ["weight"] = q.Weight,
                ["relevantTrueIds"] = new JsonArray([.. q.RelevantTrueIds.Select(id => (JsonNode)id)]),
            })]),
        })]),
        ["contradictions"] = new JsonArray([.. Contradictions.Select(c => (JsonNode)new JsonObject { ["earlyId"] = c.EarlyId, ["lateId"] = c.LateId })]),
        ["distractors"] = new JsonArray([.. Distractors.Select(id => (JsonNode)id)]),
    };

    private static JsonNode StatementJson(Statement s)
    {
        var o = new JsonObject
        {
            ["id"] = s.Id,
            ["datasetId"] = s.DatasetId,
            ["sessionIndex"] = s.SessionIndex,
            ["globalIndex"] = s.GlobalIndex,
            ["windowIndex"] = s.WindowIndex,
            ["text"] = s.Text,
            ["isTrue"] = s.IsTrue,
            ["role"] = s.Role,
            ["isDistractor"] = s.IsDistractor,
            ["isContradictionLate"] = s.IsContradictionLate,
        };
        if (s.Contradicts is not null)
            o["contradicts"] = s.Contradicts;
        return o;
    }
}

public static class SyntheticLongitudinal
{
    private static readonly (string Role, int Count)[] RoleTemplate =
    [
        ("lowfreq_highvalue", 12), ("delayed_useful", 12), ("preference_early", 12), ("preference_late", 12),
        ("relationship_boundary", 10), ("highfreq_lowvalue", 10), ("emotion_high_lowfact", 6), ("neutral_fact", 30),
    ];

    /// <summary>Roles that count as valuable for the golden task-retrieval set.</summary>
    public static IReadOnlySet<string> ValuableRoles { get; } = new HashSet<string>(StringComparer.Ordinal)
    {
        "lowfreq_highvalue", "delayed_useful", "preference_late", "conflict_early", "conflict_late", "relationship_boundary",
    };

    private static bool IsDistractorRole(string role) => role is "highfreq_lowvalue" or "emotion_high_lowfact";

    /// <summary>JavaScript Math.round for non-negative values (half rounds up).</summary>
    private static int JsRound(double x) => (int)Math.Floor(x + 0.5);

    private static List<string> Shuffle(List<string> xs, Func<double> rng)
    {
        var a = xs.ToList();
        for (var i = a.Count - 1; i > 0; i--)
        {
            var j = (int)Math.Floor(rng() * (i + 1));
            (a[i], a[j]) = (a[j], a[i]);
        }
        return a;
    }

    public static SyntheticLongitudinalBenchmark Generate(double seed = 1, BenchmarkScale? scale = null)
    {
        var sc = scale ?? BenchmarkScale.Default;
        var rng = Stats.Mulberry32(seed);
        var datasets = new List<LongitudinalDataset>();
        var allContradictions = new List<ContradictionPair>();
        var allDistractors = new List<string>();

        for (var d = 0; d < sc.Datasets; d++)
        {
            var statements = new List<Statement>();
            var contradictions = new List<ContradictionPair>();
            // Deterministic per-dataset count jitter: global averages stay at the spec rates, CIs stay non-degenerate.
            var nCl = 20 + (int)Math.Floor(rng() * 9);
            var nPoison = 6 + (int)Math.Floor(rng() * 5);
            var other = 160 - (2 * nCl) - nPoison;
            var tTotal = RoleTemplate.Sum(t => t.Count);
            var otherRoles = new List<string>();
            foreach (var (role, count) in RoleTemplate)
            {
                var c = Math.Max(0, JsRound((double)count / tTotal * other));
                for (var i = 0; i < c; i++)
                    otherRoles.Add(role);
            }
            // Fix rounding drift on neutral_fact (the largest share) to hit `other` exactly.
            var drift = other - otherRoles.Count;
            if (drift > 0)
            {
                for (var i = 0; i < drift; i++)
                    otherRoles.Add("neutral_fact");
            }
            else if (drift < 0)
            {
                var remove = -drift;
                for (var i = otherRoles.Count - 1; i >= 0 && remove > 0; i--)
                {
                    if (otherRoles[i] == "neutral_fact")
                    {
                        otherRoles.RemoveAt(i);
                        remove--;
                    }
                }
                for (var i = 0; i < remove; i++)
                    otherRoles.Add("neutral_fact");
            }

            var firstN = other / 2;
            var poisonFirst = Enumerable.Repeat("poison", nPoison / 2);
            var poisonSecond = Enumerable.Repeat("poison", nPoison - (nPoison / 2));
            var firstHalf = Shuffle([.. otherRoles.Take(firstN), .. poisonFirst, .. Enumerable.Repeat("conflict_early", nCl)], rng);
            var secondHalf = Shuffle([.. otherRoles.Skip(firstN), .. poisonSecond, .. Enumerable.Repeat("conflict_late", nCl)], rng);

            var earlyPool = new List<string>();
            var localIndex = 0;
            var half = firstHalf.Count + secondHalf.Count;
            void Emit(string role)
            {
                var sessionIndex = localIndex / sc.StatementsPerSession;
                var globalIndex = (d * half) + localIndex;
                var sessionGlobal = (d * sc.SessionsPerDataset) + sessionIndex;
                var windowIndex = (int)Math.Floor(sessionGlobal / sc.SessionsPerWindow);
                var id = $"st_{globalIndex}";
                var isDistractor = IsDistractorRole(role);
                var isLate = role == "conflict_late";
                string? contradicts = null;
                if (isLate)
                {
                    // An empty pool cannot occur: all early members come first.
                    contradicts = earlyPool.Count > 0 ? earlyPool[^1] : null;
                    contradictions.Add(new ContradictionPair(contradicts!, id));
                }
                if (role == "conflict_early")
                    earlyPool.Add(id);
                if (isDistractor)
                    allDistractors.Add(id);
                statements.Add(new Statement(id, d, sessionIndex, globalIndex, windowIndex, $"{role}@d{d}s{sessionIndex}#{localIndex}", role != "poison", role,
                    isDistractor, isLate, contradicts));
                localIndex++;
            }
            foreach (var r in firstHalf)
                Emit(r);
            foreach (var r in secondHalf)
                Emit(r);

            // One task query per virtual window; golden = valuable statements from strictly earlier sessions (delayed use).
            var taskQueries = new List<TaskQuery>();
            var sessionsPerVWin = (int)Math.Ceiling((double)sc.SessionsPerDataset / sc.Windows);
            for (var q = 0; q < sc.Windows; q++)
            {
                var startSession = q * sessionsPerVWin;
                var golden = statements.Where(s => ValuableRoles.Contains(s.Role) && s.SessionIndex < startSession).Select(s => s.Id).ToList();
                if (golden.Count == 0)
                    golden = statements.Where(s => ValuableRoles.Contains(s.Role) && s.SessionIndex <= startSession).Select(s => s.Id).ToList();
                taskQueries.Add(new TaskQuery($"q_{d}_{q}", d, q, 1, golden));
            }
            datasets.Add(new LongitudinalDataset(d, statements, taskQueries));
            allContradictions.AddRange(contradictions);
        }
        return new SyntheticLongitudinalBenchmark(seed, sc, datasets, allContradictions, allDistractors);
    }
}
