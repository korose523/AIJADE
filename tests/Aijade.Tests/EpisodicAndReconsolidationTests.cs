using Aijade.Memory.Dynamics;
using Aijade.Memory.Episodic;
using Aijade.Memory.Model;

namespace Aijade.Tests;

/// <summary>Behaviour of the episodic graph and reconsolidation.</summary>
public class EpisodicAndReconsolidationTests
{
    private static readonly EpisodicSource S1 = new("src-1", true, "d1");

    private static EpisodicGraph Graph(params string[] ids)
    {
        var g = new EpisodicGraph();
        foreach (var (id, i) in ids.Select((id, i) => (id, i)))
            Assert.True(g.AddEvent(new EpisodicEvent(id, $"ref:{id}", i), [S1 with { Id = $"src-{id}" }]).Ok);
        return g;
    }

    [Fact]
    public void Sourceless_events_are_refused_and_counted()
    {
        var g = new EpisodicGraph();
        Assert.False(g.AddEvent(new EpisodicEvent("e1", "r", 0), []).Ok);
        Assert.Equal(1, g.Refusals);
        Assert.Equal(0, g.Size);
        Assert.True(g.AddEvent(new EpisodicEvent("e1", "r", 0), [S1]).Ok);
        Assert.False(g.AddEvent(new EpisodicEvent("e1", "r", 0), [S1]).Ok);
        Assert.Equal(1, g.TraceabilityRate());
        Assert.False(g.AddSource("nope", S1).Ok);
    }

    [Fact]
    public void Conflicting_sources_coexist_and_are_reported()
    {
        var g = Graph("e1");
        g.AddSource("e1", new EpisodicSource("src-x", true, "d1"));
        Assert.Empty(g.Contradictions());
        g.AddSource("e1", new EpisodicSource("src-y", false, "d2"));
        var c = Assert.Single(g.Contradictions());
        Assert.Equal(3, c.Sources.Count);
        g.AddSource("e1", new EpisodicSource("src-z", true));
        Assert.Single(g.Contradictions());
    }

    [Fact]
    public void Temporal_edges_stay_acyclic_and_after_is_the_inverse_of_before()
    {
        var g = Graph("e1", "e2", "e3");
        Assert.True(g.AddEdge(new EpisodicEdge(EpisodicEdgeKind.Before, "e1", "e2", 0)).Ok);
        Assert.False(g.AddEdge(new EpisodicEdge(EpisodicEdgeKind.Before, "e2", "e1", 0)).Ok);
        Assert.True(g.AddEdge(new EpisodicEdge(EpisodicEdgeKind.Before, "e2", "e3", 0)).Ok);
        Assert.False(g.AddEdge(new EpisodicEdge(EpisodicEdgeKind.Before, "e3", "e1", 0)).Ok);
        Assert.False(g.AddEdge(new EpisodicEdge(EpisodicEdgeKind.After, "e1", "e3", 0)).Ok);
        Assert.False(g.AddEdge(new EpisodicEdge(EpisodicEdgeKind.Before, "e1", "e1", 0)).Ok);
        Assert.False(g.AddEdge(new EpisodicEdge(EpisodicEdgeKind.Before, "zz", "e1", 0)).Ok);
        Assert.Equal(["e1", "e2", "e3"], g.TemporalOrder());
    }

    [Fact]
    public void Causal_candidates_entities_and_expressions_are_recorded_not_adjudicated()
    {
        var g = Graph("e1");
        g.AddEdge(new EpisodicEdge(EpisodicEdgeKind.CausedCandidate, "e1", "outcome-a", 0));
        g.AddEdge(new EpisodicEdge(EpisodicEdgeKind.CausedCandidate, "e1", "outcome-b", 0));
        g.AddEdge(new EpisodicEdge(EpisodicEdgeKind.Involves, "e1", "Caroline", 0));
        g.AddEdge(new EpisodicEdge(EpisodicEdgeKind.ExpressedAs, "e1", "motion:wave", 0));
        Assert.Equal(["outcome-a", "outcome-b"], g.CausalCandidates("e1"));
        Assert.Equal(["Caroline"], g.EntitiesOf("e1"));
        Assert.Equal(["motion:wave"], g.ExpressionsOf("e1"));
        Assert.Equal(2, g.EdgesFrom("e1", EpisodicEdgeKind.CausedCandidate).Count);
    }

    private sealed class FixedDetector(ReconsolidationVerdict verdict) : IContradictionDetector
    {
        public ReconsolidationVerdict Evaluate(SemanticFact existing, string candidate) => verdict;
    }

    private static SemanticFact Fact() => new() { Id = "fact_1", Content = "lives in Hangzhou", DerivedFrom = ["e1"], CreatedAt = 0, ContextTags = [], Confidence = 0.9 };

    private static readonly ReconsolidationVerdict Moved = new(ReconsolidationKind.Contradiction, 0.8, "lives in Seoul", 0.7);

    [Fact]
    public void Disabled_engine_and_noop_detector_never_mutate()
    {
        var off = new ReconsolidationEngine(detector: new FixedDetector(Moved));
        off.MarkLabile("fact_1", 0);
        Assert.Null(off.Reconsolidate(Fact(), "x", 1).Updated);
        var noop = new ReconsolidationEngine(ReconsolidationConfig.Default with { Enabled = true });
        noop.MarkLabile("fact_1", 0);
        Assert.Null(noop.Reconsolidate(Fact(), "x", 1).Updated);
    }

    [Fact]
    public void Labile_window_cooldown_and_version_cap_bound_updates()
    {
        var cfg = ReconsolidationConfig.Default with { Enabled = true, MaxVersions = 2 };
        var e = new ReconsolidationEngine(cfg, new FixedDetector(Moved));
        Assert.Null(e.Reconsolidate(Fact(), "x", 0).Updated);
        e.MarkLabile("fact_1", 0);
        Assert.True(e.IsLabile("fact_1", cfg.LabileWindowMs));
        Assert.False(e.IsLabile("fact_1", cfg.LabileWindowMs + 1));

        e.MarkLabile("fact_1", 0);
        var (u1, ev1) = e.Reconsolidate(Fact(), "moved", 10);
        Assert.Equal("lives in Seoul", u1!.Fact.Content);
        Assert.Equal(1, u1.Version);
        Assert.Equal("contradiction applied (conf 0.9→0.7)", ev1!.Summary);
        Assert.Null(e.Reconsolidate(Fact(), "again", 20).Updated);
        Assert.NotNull(e.Reconsolidate(Fact(), "again", 10 + cfg.CooldownMs).Updated);
        Assert.Null(e.Reconsolidate(Fact(), "third", 10 + (3 * cfg.CooldownMs)).Updated);
        Assert.Equal(2, e.AuditTrail.Count);
    }
}
