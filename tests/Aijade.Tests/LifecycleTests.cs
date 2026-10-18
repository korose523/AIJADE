using System.Text.Json;

using Aijade.Core.Js;
using Aijade.Memory.Dynamics;
using Aijade.Memory.Lifecycle;
using Aijade.Memory.Model;

namespace Aijade.Tests;

/// <summary>Two-stage forgetting, the legacy state gate and toFixed must equal the recorded golden data.</summary>
public class LifecycleTests
{
    private static readonly JsonElement Golden =
        JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "lifecycle-golden.json"))).RootElement;

    private static double? D(JsonElement o, string name) => o.TryGetProperty(name, out var v) ? v.GetDouble() : null;

    private static PhysiologicalState State(JsonElement s) => new(s.GetProperty("dopamine").GetDouble(), s.GetProperty("serotonin").GetDouble(),
        s.GetProperty("cortisol").GetDouble(), s.GetProperty("oxytocin").GetDouble(), s.GetProperty("adrenaline").GetDouble(), D(s, "intimacy"));

    private static HormoneLevels Levels(PhysiologicalState s) => new(s.Dopamine, s.Serotonin, s.Cortisol, s.Oxytocin, s.Adrenaline);

    [Fact]
    public void Sweeps_match_the_original()
    {
        var states = Golden.GetProperty("states").EnumerateArray().Select(State).ToArray();
        var now = Golden.GetProperty("now").GetDouble();
        var items = Golden.GetProperty("items").EnumerateArray().ToArray();
        var sweeps = Golden.GetProperty("sweeps").EnumerateArray().ToArray();
        for (var i = 0; i < items.Length; i++)
        {
            var it = items[i];
            var input = new SweepInput(it.GetProperty("id").GetString()!, it.GetProperty("createdAt").GetDouble(), it.GetProperty("lastAccessedAt").GetDouble(),
                it.GetProperty("accessCount").GetInt32(), it.GetProperty("baseStrength").GetDouble(), it.GetProperty("durability").GetDouble(),
                it.TryGetProperty("tier", out var t) ? System.Enum.Parse<MemoryTier>(t.GetString()!, true) : null);
            var r = ForgettingSweep.SweepWithGate(input, now, new ForgettingConfig(), i % 5 == 0 ? GatingCoefficients.None : GatingCoefficients.Default, states[i % states.Length]);
            var e = sweeps[i];
            // pow / exp may differ from V8 in the last ulp; everything derived from them is compared with that tolerance.
            Assert.Equal(e.GetProperty("strength").GetDouble(), r.Strength, 1e-12);
            Assert.Equal(System.Enum.Parse<MemoryTier>(e.GetProperty("tier").GetString()!, true), r.Tier);
            Assert.Equal(e.GetProperty("demoted").GetBoolean(), r.Demoted);
            Assert.Equal(e.GetProperty("deletionCandidate").GetBoolean(), r.DeletionCandidate);
            Assert.Equal(e.TryGetProperty("reason", out var reason) ? reason.GetString() : null, r.Reason);
        }
    }

    [Fact]
    public void State_gate_and_presentation_match_the_original()
    {
        var states = Golden.GetProperty("states").EnumerateArray().Select(State).ToArray();
        foreach (var (s, g) in states.Zip(Golden.GetProperty("gates").EnumerateArray()))
        {
            Assert.Equal(new PlasticityGate(g.GetProperty("consolidationGain").GetDouble(), g.GetProperty("decayMultiplier").GetDouble(),
                g.GetProperty("retrievalNoise").GetDouble(), g.GetProperty("moodCongruenceWeight").GetDouble(), g.GetProperty("socialBonus").GetDouble(),
                g.GetProperty("explorationTemperature").GetDouble()), Plasticity.GateFromState(s));
        }
        var pres = Golden.GetProperty("pres").EnumerateArray().ToArray();
        for (var i = 0; i < states.Length; i++)
        {
            var v3 = new PhysiologicalStateV3(Levels(states[i]), Levels(states[(i + 1) % 6]), Levels(states[(i + 2) % 6]), Affect.Neutral);
            var p = pres[i];
            Assert.Equal(new PresentationModulation(p.GetProperty("warmth").GetDouble(), p.GetProperty("verbosity").GetDouble(),
                p.GetProperty("hesitation").GetDouble(), p.GetProperty("energy").GetDouble()), Plasticity.DerivePresentation(v3, true));
        }
        Assert.Equal(PresentationModulation.Neutral, Plasticity.DerivePresentation(new PhysiologicalStateV3(Levels(states[0]), Levels(states[1]), Levels(states[2]), Affect.Neutral), false));
        Assert.True(Plasticity.IsNeutral(Plasticity.GateFromCoefficients(GatingCoefficients.None, states[0])));
    }

    [Fact]
    public void ToFixed_matches_javascript()
    {
        foreach (var pair in Golden.GetProperty("fixed").EnumerateArray())
            Assert.Equal(pair[1].GetString(), JsFormat.ToFixed(pair[0].GetDouble(), 1));
        Assert.Equal("0.0", JsFormat.ToFixed(-0.0, 1));
    }

    [Fact]
    public void Tiers_only_go_down_and_candidates_need_cold_unaccessed_dwell()
    {
        Assert.Equal(MemoryTier.Hot, ForgettingSweep.TierOf(0.6));
        Assert.Equal(MemoryTier.Warm, ForgettingSweep.TierOf(0.25));
        Assert.Equal(MemoryTier.Cold, ForgettingSweep.TierOf(0.2));
        const double Day = 86_400_000;
        var strong = new SweepInput("a", 0, 0, 3, 1, 1, MemoryTier.Cold);
        Assert.Equal(MemoryTier.Cold, ForgettingSweep.Sweep(strong, 0, new ForgettingConfig(), 1).Tier);
        var weak = new SweepInput("b", 0, 0, 0, 0.1, 1, MemoryTier.Hot);
        var r = ForgettingSweep.Sweep(weak, 40 * Day, new ForgettingConfig(), 1);
        Assert.True(r.Demoted && r.DeletionCandidate);
        Assert.Equal("cold tier, accessCount=0, dwell=40.0d >= 30d", r.Reason);
        Assert.False(ForgettingSweep.Sweep(weak with { AccessCount = 1 }, 40 * Day, new ForgettingConfig(), 1).DeletionCandidate);
    }

    [Fact]
    public void Ledger_never_deletes_silently()
    {
        var ledger = new DeletionLedger();
        var gate = new GateSnapshot(1, 0);
        ledger.Enqueue("a", "cold", 1, gate);
        ledger.Enqueue("a", "cold again", 2, gate);
        ledger.Enqueue("b", "cold", 3, gate);
        Assert.Equal(2, ledger.Pending().Count);
        Assert.True(ledger.Retain("a", 4));
        Assert.False(ledger.Commit("a", 5));
        Assert.True(ledger.Commit("b", 6));
        Assert.Empty(ledger.Pending());
        Assert.Equal([DeletionResolution.Retained, DeletionResolution.Deleted], ledger.All().Select(e => e.Resolution!.Value));
        ledger.Enqueue("a", "cold later", 7, gate);
        Assert.Single(ledger.Pending());
        Assert.Equal(3, ledger.All().Count);
    }
}
