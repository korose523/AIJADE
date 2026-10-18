using System.Text.Json;

using Aijade.Core.Random;
using Aijade.Research.Steering;

namespace Aijade.Tests;

/// <summary>The steering benchmark must equal the recorded golden data (null models, PRR table) and pass its self-test.</summary>
public class SteeringTests
{
    private static readonly JsonElement Golden =
        JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "steering-golden.json"))).RootElement;

    private static List<(string, string)> Edges(JsonElement a) => a.EnumerateArray().Select(e => (e[0].GetString()!, e[1].GetString()!)).ToList();

    [Fact]
    public void Null_models_and_recovery_table_match_the_original()
    {
        var g = new Graph(Enumerable.Range(0, 12).Select(i => $"n{i}").ToList(), Edges(Golden.GetProperty("edges")));
        Assert.Equal(Edges(Golden.GetProperty("undirected")[0]), SteeringBenchmark.DegreePreservingNull(g, 30, 42).Edges);
        Assert.Equal(Edges(Golden.GetProperty("undirected")[1]), SteeringBenchmark.DegreePreservingNull(g, 5, 7).Edges);
        Assert.Equal(Edges(Golden.GetProperty("directed")), SteeringBenchmark.DegreePreservingNull(g, 25, 9, directed: true).Edges);

        var reference = new BehaviorTrace("t", Enumerable.Range(0, 10).Select(i => new BehaviorStep(i, $"a{i}", i != 7)).ToList());
        static BehaviorTrace Half(BehaviorTrace p) => p with { Steps = p.Steps.Select((s, i) => s with { Ok = s.Ok || i % 2 == 0 }).ToList() };
        var res = SteeringBenchmark.Run(new SteeringConfig([("T1", reference), ("T2", reference with { Id = "u" })],
            [PerturbationKind.Latent, PerturbationKind.Transient, PerturbationKind.Permanent], Half, 3, 4));
        var e = Golden.GetProperty("res");
        Assert.Equal(e.GetProperty("cells").EnumerateArray().Select(c => (c.GetProperty("taskDim").GetString(), c.GetProperty("prr").GetDouble(), c.GetProperty("recoveryCost").GetInt32())),
            res.Cells.Select(c => ((string?)c.TaskDim, c.Prr, c.RecoveryCost)));
        Assert.Equal(e.GetProperty("meanPrr").GetDouble(), res.MeanPrr);
    }

    [Fact]
    public void Self_test_of_the_original_holds()
    {
        var g = new Graph(["a", "b", "c", "d", "e"], [("a", "b"), ("a", "c"), ("b", "c"), ("c", "d"), ("d", "e"), ("e", "a")]);
        static int Deg(Graph x, string n) => x.Edges.Count(e => e.From == n || e.To == n);
        var g2 = SteeringBenchmark.EdgeSwap(g, 20, new Mulberry32(42).AsFunc());
        Assert.All(g.Nodes, n => Assert.Equal(Deg(g, n), Deg(g2, n)));
        var dg = new Graph(["a", "b", "c", "d"], [("a", "b"), ("a", "c"), ("b", "c"), ("c", "d"), ("d", "a")]);
        var dg2 = SteeringBenchmark.EdgeSwap(dg, 10, new Mulberry32(7).AsFunc(), directed: true);
        Assert.All(dg.Nodes, n => Assert.Equal((dg.Edges.Count(e => e.From == n), dg.Edges.Count(e => e.To == n)), (dg2.Edges.Count(e => e.From == n), dg2.Edges.Count(e => e.To == n))));
        Assert.Equal(SteeringBenchmark.DegreePreservingNull(g, 20, 99).Edges, SteeringBenchmark.DegreePreservingNull(g, 20, 99).Edges);

        var reference = new BehaviorTrace("t1", Enumerable.Range(0, 8).Select(i => new BehaviorStep(i, $"a{i}", true)).ToList());
        var latent = SteeringBenchmark.ApplyPerturbation(reference, PerturbationKind.Latent, 2);
        Assert.True(!latent.Steps[2].Ok && latent.Steps[3].Ok);
        var permanent = SteeringBenchmark.ApplyPerturbation(reference, PerturbationKind.Permanent, 2);
        Assert.Equal(6, permanent.Steps.Count(s => !s.Ok));
        Assert.Equal(3, SteeringBenchmark.ApplyPerturbation(reference, PerturbationKind.Transient, 2, 3).Steps.Count(s => !s.Ok));
        static BehaviorTrace Perfect(BehaviorTrace p) => p with { Steps = p.Steps.Select(s => s with { Ok = true }).ToList() };
        Assert.Equal(1, SteeringBenchmark.Run(new SteeringConfig([("T1", reference)], [PerturbationKind.Latent, PerturbationKind.Transient, PerturbationKind.Permanent], Perfect)).MeanPrr, 9);
        Assert.Equal(0, SteeringBenchmark.Run(new SteeringConfig([("T1", reference)], [PerturbationKind.Permanent], p => p, 2)).MeanPrr);
        Assert.Equal(0, SteeringBenchmark.RecoveryCost(reference, permanent, Perfect(permanent)));
        Assert.Equal(6, SteeringBenchmark.RecoveryCost(reference, permanent, permanent));
    }
}
