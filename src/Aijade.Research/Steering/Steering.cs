using Aijade.Core.Random;

namespace Aijade.Research.Steering;

// An agent steering /
// perturbation-recovery harness. Task dimensions × perturbation kinds (latent / transient / permanent), scored by the
// perturbation recovery rate and recovery cost; plus the degree-preserving (double-edge swap) null model as a topology
// signal. The methodology follows MOSAIC's taxonomy and ToolMaze's PRR as citations only; the algorithms are the author's own.
// Every random draw is seeded (mulberry32), so a fixed seed gives a bit-exact null model.

public enum PerturbationKind
{
    Latent,
    Transient,
    Permanent,
}

public sealed record BehaviorStep(double T, string Action, bool Ok);

public sealed record BehaviorTrace(string Id, IReadOnlyList<BehaviorStep> Steps);

public sealed record Graph(IReadOnlyList<string> Nodes, IReadOnlyList<(string From, string To)> Edges);

public sealed record CellResult(string TaskDim, PerturbationKind Kind, double Prr, int RecoveryCost);

public sealed record SteeringResult(IReadOnlyList<CellResult> Cells, double MeanPrr);

public sealed record SteeringConfig(
    IReadOnlyList<(string TaskDim, BehaviorTrace Reference)> ReferenceTraces, IReadOnlyList<PerturbationKind> PerturbationKinds,
    Func<BehaviorTrace, BehaviorTrace> Recover, int AtIndex = 1, int TransientWindow = 3, Graph? Topology = null, int? NumSwaps = null, uint Seed = 1);

public static class SteeringBenchmark
{
    /// <summary>Latent fails one step at the index; transient fails a window; permanent fails everything from the index on.</summary>
    public static BehaviorTrace ApplyPerturbation(BehaviorTrace trace, PerturbationKind kind, int atIndex = 1, int transientWindow = 3)
    {
        var steps = trace.Steps.Select((s, idx) => idx < atIndex ? s : kind switch
        {
            PerturbationKind.Latent => idx == atIndex ? s with { Ok = false } : s,
            PerturbationKind.Transient => idx < atIndex + transientWindow ? s with { Ok = false } : s,
            _ => s with { Ok = false },
        }).ToList();
        return new BehaviorTrace($"{trace.Id}:{Core.Js.WireName.Of(kind)}@{atIndex}", steps);
    }

    /// <summary>Of the steps the perturbation broke, the fraction the agent restored (1 when nothing was broken).</summary>
    public static double PerturbationRecoveryRate(BehaviorTrace reference, BehaviorTrace perturbed, BehaviorTrace recovered)
    {
        var affected = Enumerable.Range(0, reference.Steps.Count).Where(i => reference.Steps[i].Ok && !perturbed.Steps[i].Ok).ToList();
        return affected.Count == 0 ? 1 : (double)affected.Count(i => recovered.Steps[i].Ok) / affected.Count;
    }

    /// <summary>The number of broken steps left unrecovered.</summary>
    public static int RecoveryCost(BehaviorTrace reference, BehaviorTrace perturbed, BehaviorTrace recovered) =>
        Enumerable.Range(0, reference.Steps.Count).Count(i => reference.Steps[i].Ok && !perturbed.Steps[i].Ok && !recovered.Steps[i].Ok);

    public static SteeringResult Run(SteeringConfig cfg)
    {
        ArgumentNullException.ThrowIfNull(cfg);
        var cells = new List<CellResult>();
        foreach (var (taskDim, reference) in cfg.ReferenceTraces)
        {
            foreach (var kind in cfg.PerturbationKinds)
            {
                var perturbed = ApplyPerturbation(reference, kind, cfg.AtIndex, cfg.TransientWindow);
                var recovered = cfg.Recover(perturbed);
                cells.Add(new CellResult(taskDim, kind, PerturbationRecoveryRate(reference, perturbed, recovered), RecoveryCost(reference, perturbed, recovered)));
            }
        }
        var sum = 0.0;
        foreach (var c in cells)
            sum += c.Prr;
        return new SteeringResult(cells, cells.Count > 0 ? sum / cells.Count : 0);
    }

    public static Graph? NullModelTopology(SteeringConfig cfg) =>
        cfg.Topology is { } t ? DegreePreservingNull(t, cfg.NumSwaps ?? t.Edges.Count, cfg.Seed) : null;

    private static string UndirectedKey((string A, string B) e) => string.CompareOrdinal(e.A, e.B) <= 0 ? $"{e.A}\0{e.B}" : $"{e.B}\0{e.A}";

    private static string DirectedKey((string A, string B) e) => $"{e.A}\0{e.B}";

    /// <summary>
    /// MCMC double-edge swap (a–b, c–d → a–d, c–b), rejecting self-loops and duplicate edges, until the requested number of
    /// swaps is accepted or max(50·n, n + 100) attempts are spent. Every node keeps its degree (in- and out-degree when directed).
    /// </summary>
    public static Graph EdgeSwap(Graph input, int numSwaps, Func<double> rng, bool directed = false)
    {
        var edges = input.Edges.ToArray();
        Func<(string, string), string> key = directed ? DirectedKey : UndirectedKey;
        var seen = edges.Select(key).ToHashSet(StringComparer.Ordinal);
        int accepted = 0, attempts = 0;
        var maxAttempts = Math.Max(numSwaps * 50, numSwaps + 100);
        while (accepted < numSwaps && attempts < maxAttempts)
        {
            attempts++;
            var i = (int)Math.Floor(rng() * edges.Length);
            var j = (int)Math.Floor(rng() * edges.Length);
            if (i == j)
                continue;
            var (a, b) = edges[i];
            var (c, d) = edges[j];
            if (directed ? a == d || c == b : a == c || a == d || b == c || b == d)
                continue;
            var e1 = (a, d);
            var e2 = (c, b);
            var k1 = key(e1);
            var k2 = key(e2);
            if (seen.Contains(k1) || seen.Contains(k2))
                continue;
            seen.Remove(key(edges[i]));
            seen.Remove(key(edges[j]));
            edges[i] = e1;
            edges[j] = e2;
            seen.Add(k1);
            seen.Add(k2);
            accepted++;
        }
        return new Graph([.. input.Nodes], edges);
    }

    public static Graph DegreePreservingNull(Graph input, int numSwaps, uint seed, bool directed = false) =>
        EdgeSwap(input, numSwaps, new Mulberry32(seed).AsFunc(), directed);
}
