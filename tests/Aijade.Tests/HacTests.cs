using System.Text.Json;

using Aijade.Core.Random;
using Aijade.Memory.Contracts;
using Aijade.Memory.Hac;

namespace Aijade.Tests;

/// <summary>The HAC closed loop must reproduce the recorded golden data step for step.</summary>
public class HacTests
{
    private static readonly JsonElement Golden =
        JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "hac-golden.json"))).RootElement;

    private static HacState Read(JsonElement e) => new(
        e.GetProperty("a").GetDouble(), e.GetProperty("v").GetDouble(), e.GetProperty("d").GetDouble(), e.GetProperty("n").GetDouble(),
        e.GetProperty("s").GetDouble(), e.GetProperty("c").GetDouble(), e.GetProperty("b").GetDouble());

    private static void Close(double expected, double actual, string what) =>
        Assert.True(Math.Abs(expected - actual) <= 1e-12, $"{what}: expected {expected:R}, got {actual:R}");

    [Fact]
    public void Closed_loop_trajectory_decisions_noise_and_snapshot_match()
    {
        var cfg = HacConfig.Default with
        {
            Enabled = true,
            GateW = Golden.GetProperty("gateW").EnumerateArray().Select(x => x.GetDouble()).ToArray(),
            GateB = -0.2,
        };
        var hac = new HacController(cfg);
        var rng = new Mulberry32(1234).AsFunc();
        var expected = Golden.GetProperty("traj").EnumerateArray().Select(Read).ToArray();
        for (var t = 0; t < 30; t++)
        {
            if (t % 3 == 0)
            {
                var appraisal = new Appraisal("a", "e", "x", "u",
                    new AppraisalDimensions(Math.Sin(t), t % 5 / 5.0, 0.7, t % 7 / 7.0, Math.Cos(t), t % 4 / 4.0), 0.9, "model", t);
                hac.StepAppraisal(appraisal, rng);
            }
            else
            {
                var feedback = new FeedbackEvent("f", "x", "u", "s", "r", t % 2 == 1 ? "explicit" : "implicit", "rating", t,
                    Value: t % 6, Valence: t % 4 == 0 ? null : (t % 3) - 1);
                hac.Step(new HacState(0.9, 0.2, 0.6, t % 5 / 5.0, 0.3, 0.8, 0.1), HacMath.FeedbackToAction(feedback), rng);
            }
            foreach (var (x, y) in expected[t].ToArray().Zip(hac.State.ToArray()))
                Close(x, y, $"z[{t}]");
        }

        var features = new UtilityFeatures(0.7, 0.4, 0.5, 0.6, 0.2, 0.3, 0.1);
        var ok = new WriteConstraints(true, true, true, true, true, true, 3);
        Close(Golden.GetProperty("decision").GetProperty("p").GetDouble(), hac.Decide(features, ok).P, "p_write");
        var blocked = hac.Decide(features, ok with { NotDuplicate = false });
        Assert.Equal(0, blocked.P);
        Assert.Equal("duplicate", blocked.Reason);

        var degradation = Golden.GetProperty("deg").EnumerateArray().Select(x => x.GetDouble()).ToArray();
        for (var i = 0; i < degradation.Length; i++)
            Close(degradation[i], hac.Degradation(rng, i / 7.0), $"ξ[{i}]");

        var snap = hac.Snapshot("hac", 1791428571829, "agent", "user");
        Assert.Equal(Golden.GetProperty("snap").GetProperty("id").GetString(), snap.Id);
        Assert.True(ContractValidation.Validate(snap).Ok);
        Close(Golden.GetProperty("utility").GetDouble(), HacMath.PredictUtility(features, cfg.UtilityWeights), "U");
    }

    [Fact]
    public void Replay_selection_trades_utility_against_redundancy()
    {
        var replay = HacMath.SelectReplay(
        [
            new ReplayCandidate("m1", 0.6, 0.1, new Dictionary<string, double> { ["m2"] = 0.9, ["m3"] = 0.1 }),
            new ReplayCandidate("m2", 0.65, 0.0, new Dictionary<string, double> { ["m1"] = 0.9, ["m3"] = 0.2 }),
            new ReplayCandidate("m3", 0.3, 0.2, new Dictionary<string, double> { ["m1"] = 0.1, ["m2"] = 0.2 }),
            new ReplayCandidate("m4", -0.2, 0.1, new Dictionary<string, double>()),
        ], 0.5);
        Assert.Equal(Golden.GetProperty("replay").EnumerateArray().Select(x => x.GetString()), replay);
    }

    [Fact]
    public void Ablated_dynamics_freeze_the_state()
    {
        var z = HacState.Uniform(0.3);
        Assert.Equal(z, HacMath.Step(z, HacState.Uniform(1), HacState.Uniform(1), HacConfig.Default with { Dynamics = HacDynamics.Ablated }, () => 0.9));
    }
}
