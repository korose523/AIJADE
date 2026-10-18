using System.Text.Json;

using Aijade.Memory.Pgc;

namespace Aijade.Tests;

/// <summary>The PGC state dynamics must follow the recorded trajectory (golden data).</summary>
public class PgcStateTests
{
    private static readonly JsonElement Golden =
        JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "pgc-state-golden.json"))).RootElement;

    private static PgcState4 Read(JsonElement e) =>
        new(e.GetProperty("a").GetDouble(), e.GetProperty("c").GetDouble(), e.GetProperty("d").GetDouble(), e.GetProperty("f").GetDouble());

    private static void Close(PgcState4 expected, PgcState4 actual)
    {
        foreach (var (x, y) in expected.ToArray().Zip(actual.ToArray()))
            Assert.True(Math.Abs(x - y) <= 1e-12, $"expected {expected}, got {actual}");
    }

    [Fact]
    public void Stimulus_evaluation_and_trajectory_match_the_original()
    {
        Dictionary<StimulusFeature, double>[] features =
        [
            new() { [StimulusFeature.StimArousalScore] = 0.9, [StimulusFeature.StimDriveScore] = 0.6 },
            new() { [StimulusFeature.StimStrainScore] = 0.8, [StimulusFeature.UncertaintyLoadScore] = 0.5 },
            new() { [StimulusFeature.StimFatigueScore] = 0.95, [StimulusFeature.IdleAndOverloadScore] = 1 },
            new(),
            new() { [StimulusFeature.PersonaEnergyScore] = 1, [StimulusFeature.SkillNeedScore] = 0.7, [StimulusFeature.StimArousalScore] = 0.2 },
        ];
        var stimuli = features.Select(f => PgcStateMath.EvaluateStimulus(f)).ToArray();
        var expectedStimuli = Golden.GetProperty("stimuli").EnumerateArray().Select(Read).ToArray();
        for (var i = 0; i < stimuli.Length; i++)
            Close(expectedStimuli[i], stimuli[i]);

        var integrator = new PgcStateIntegrator();
        var expected = Golden.GetProperty("traj").EnumerateArray().Select(Read).ToArray();
        for (var t = 0; t < 40; t++)
            Close(expected[t], integrator.Step(stimuli[t % stimuli.Length], t % 7 == 0 ? 0.5 : null));

        Assert.Equal(Golden.GetProperty("trig").GetBoolean(), integrator.MaybeTriggerOfflineConsolidation(400));
        Close(Read(Golden.GetProperty("after")), integrator.State);
    }

    [Fact]
    public void Offline_consolidation_needs_both_fatigue_and_idleness()
    {
        var it = new PgcStateIntegrator(new PgcState4(0.5, 0.5, 0.5, 0.9));
        Assert.False(it.MaybeTriggerOfflineConsolidation(10));
        Assert.True(it.MaybeTriggerOfflineConsolidation(301));
        Assert.Equal(PgcStateSpec.Default.SStar, it.State);
    }
}
