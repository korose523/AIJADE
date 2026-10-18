using Aijade.Memory.Beliefs;
using Aijade.Memory.Kernel;

namespace Aijade.Tests;

/// <summary>Behaviour of the belief graph and the core state node.</summary>
public class BeliefTests
{
    private static readonly BeliefConfig Cfg = BeliefConfig.Default;

    private static Belief New() => BeliefMath.Create("b1", "user likes tea", ["src1"], 0, Cfg);

    [Fact]
    public void Starts_at_the_prior_as_a_hypothesis()
    {
        var b = New();
        Assert.Equal(0.5, b.Confidence, 6);
        Assert.Equal(0, b.Logit, 6);
        Assert.Equal(BeliefStatus.Hypothesis, b.Status);
        Assert.Equal(["src1"], b.EvidenceIds);
    }

    [Fact]
    public void Delta_adds_support_subtracts_counter_and_clamps()
    {
        var d = BeliefMath.Delta([new EvidenceEntry("e1", 1, 2)], [], Cfg);
        Assert.Equal(2, d.Delta, 6);
        Assert.False(d.Clamped);
        var c = BeliefMath.Delta([], [new EvidenceEntry("c1", 1, 2)], Cfg);
        Assert.Equal(-2, c.Delta, 6);
        var neg = BeliefMath.Delta([], [new EvidenceEntry("c1", 1, -3)], Cfg);
        Assert.True(neg.Clamped);
        Assert.Equal(0, neg.Delta, 6);
        var big = BeliefMath.Delta([new EvidenceEntry("e1", 1.5, 5)], [], Cfg);
        Assert.Equal(2, big.Delta, 6);
        Assert.Equal([1.0], big.Reliabilities);
        Assert.Contains("clamped e1: r=1.5->1, l=5->2", big.Rationale, StringComparison.Ordinal);
    }

    [Theory]
    [InlineData(0.1, 2, 4, BeliefStatus.Retracted)]
    [InlineData(0.5, 2, 2, BeliefStatus.Contested)]
    [InlineData(0.8, 3, 0, BeliefStatus.Accepted)]
    [InlineData(0.5, 1, 0, BeliefStatus.Hypothesis)]
    public void Status_follows_confidence_and_counter_share(double confidence, double support, double counter, BeliefStatus expected) =>
        Assert.Equal(expected, BeliefMath.NextStatus(confidence, support, counter, Cfg));

    [Fact]
    public void Evidence_transactions_move_hypothesis_to_accepted_contested_and_retracted()
    {
        var (accepted, r1) = BeliefMath.Apply(New(), "rev1", 1, "agent", Cfg, [new EvidenceEntry("e1", 1, 2)]);
        Assert.Equal(2, accepted.Logit, 6);
        Assert.Equal(0.8808, accepted.Confidence, 3);
        Assert.Equal(BeliefStatus.Accepted, accepted.Status);
        Assert.Equal(2, r1.DeltaLogit, 6);
        Assert.Equal("agent", r1.Actor);

        var (contested, r2) = BeliefMath.Apply(accepted, "rev2", 2, "agent", Cfg, counterEvidence: [new EvidenceEntry("c1", 1, 2)]);
        Assert.Equal(0.5, contested.Confidence, 6);
        Assert.Equal(BeliefStatus.Contested, contested.Status);
        Assert.Equal(-2, r2.DeltaLogit, 6);

        var (retracted, _) = BeliefMath.Apply(contested, "rev3", 3, "agent", Cfg, counterEvidence: [new EvidenceEntry("c2", 1, 2)]);
        Assert.Equal(-2, retracted.Logit, 6);
        Assert.Equal(0.1192, retracted.Confidence, 3);
        Assert.Equal(BeliefStatus.Retracted, retracted.Status);
        Assert.Equal(4, retracted.CounterLogit, 6);
    }

    [Fact]
    public void Explicit_retraction_keeps_the_entry_and_records_why()
    {
        var (b, rev) = BeliefMath.Retract(New(), "rev", 9, "user", "wrong person");
        Assert.Equal(BeliefStatus.Retracted, b.Status);
        Assert.Equal(9, b.ValidTo);
        Assert.Equal("retracted: wrong person", rev.Rationale);
        Assert.Equal(0, rev.DeltaLogit);
    }

    [Theory]
    [InlineData("aijade.video.frame_observed", false, CoreStateNode.S2)]
    [InlineData("aijade.learning.proposed.shadow_params", false, CoreStateNode.S3)]
    [InlineData("aijade.evidence.gate_evaluated", false, CoreStateNode.S4)]
    [InlineData("aijade.pgc.write_plan_ready", false, CoreStateNode.S5)]
    [InlineData("aijade.memory_tx.committed", false, CoreStateNode.S6)]
    [InlineData("aijade.evidence.weave_candidate_ready", false, CoreStateNode.S7)]
    [InlineData("aijade.memory_tx.committed", true, CoreStateNode.S8)]
    [InlineData("aijade.active_learning.started", false, CoreStateNode.S1)]
    [InlineData("aijade.persona.updated", false, CoreStateNode.S0)]
    public void Core_state_node_depends_on_topic_and_real_persistence(string topic, bool persisted, CoreStateNode expected) =>
        Assert.Equal(expected, CoreStateNodes.Derive(topic, persisted));
}
