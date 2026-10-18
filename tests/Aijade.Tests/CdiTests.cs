using System.Text.Json;

using Aijade.Memory.Identity;

namespace Aijade.Tests;

/// <summary>CDI must sign, reject and roll back exactly as recorded (golden data).</summary>
public class CdiTests
{
    private static readonly JsonElement Golden =
        JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "cdi-golden.json"))).RootElement;

    private static IdentityEvidence Ev(string episode, EvidenceTrigger trigger = EvidenceTrigger.Deliberate) =>
        new(episode, IdentitySource.User, true, "preference", trigger);

    private static Dictionary<IdentityLayer, OrderedDictionary<string, double>> D(params (IdentityLayer Layer, string Key, double Value)[] entries)
    {
        var d = new Dictionary<IdentityLayer, OrderedDictionary<string, double>>();
        foreach (var (layer, key, value) in entries)
        {
            if (!d.TryGetValue(layer, out var inner))
                d[layer] = inner = [];
            inner[key] = value;
        }
        return d;
    }

    [Fact]
    public void Signatures_rejections_and_rollback_match_the_golden_data()
    {
        Assert.Equal(Golden.GetProperty("defaultHash").GetString(), Cdi.Hash(IdentityState.Default));
        double t = 1000;
        var ctl = new IdentityController(CdiConfig.ConsentAlsoSafetyBound, clock: () => t++);
        IdentityCandidate[] candidates =
        [
            new("c1", IdentitySource.User, [Ev("e1"), Ev("e2")], D((IdentityLayer.Character, "verbosity", 0.1), (IdentityLayer.Character, "curiosity", 0.05))),
            new("c2", IdentitySource.Agent, [Ev("e1"), Ev("e3")], D((IdentityLayer.Expressive, "warmth", 0.2), (IdentityLayer.Character, "formality", -0.1))),
            new("c3", IdentitySource.User, [Ev("e1"), Ev("e2")], D((IdentityLayer.Character, "verbosity", 0.45), (IdentityLayer.Character, "formality", 0.3))),
            new("c4", IdentitySource.Agent, [Ev("e1"), Ev("e2")], D((IdentityLayer.Constitutional, "userConsent", 0.1))),
            new("c5", IdentitySource.User, [Ev("e4"), Ev("e5")], D((IdentityLayer.Constitutional, "harmThreshold", 0.4)), ExplicitUpgrade: true),
            new("c6", IdentitySource.User, [Ev("e4"), Ev("e5")], D((IdentityLayer.Constitutional, "harmThreshold", 0.2), (IdentityLayer.Expressive, "energy", 0.1)), ExplicitUpgrade: true),
            new("c7", IdentitySource.User, [Ev("e6", EvidenceTrigger.Emotion), Ev("e7", EvidenceTrigger.Emotion)], D((IdentityLayer.Expressive, "energy", 0.1))),
            new("c8", IdentitySource.User, [Ev("e6")], D((IdentityLayer.Expressive, "energy", 0.1))),
        ];
        var expected = Golden.GetProperty("results").EnumerateArray().ToArray();
        for (var i = 0; i < candidates.Length; i++)
        {
            var (version, result) = ctl.Apply(candidates[i]);
            Assert.Equal(expected[i].GetProperty("ok").GetBoolean(), result.Ok);
            if (result.Ok)
            {
                Assert.Equal(expected[i].GetProperty("sig").GetString(), version!.Signature);
                Assert.Equal(expected[i].GetProperty("parents").EnumerateArray().Select(p => p.GetString()), version.Parents);
                Assert.Equal(expected[i].GetProperty("createdAt").GetDouble(), version.CreatedAt);
            }
            else
            {
                Assert.Equal(expected[i].GetProperty("reason").GetString(), result.Reason);
            }
        }

        var rollback = ctl.RollbackTo(ctl.History[0].Signature);
        Assert.Equal(Golden.GetProperty("rollback").GetProperty("sig").GetString(), rollback.Signature);
        Assert.Equal(4, rollback.Version);
        Assert.True(rollback.RolledBack);
        Assert.Equal(Golden.GetProperty("stability").GetDouble(), Cdi.CoreStability(ctl.State, IdentityState.Default), 12);
        Assert.Equal(Golden.GetProperty("recovery").GetDouble(), Cdi.RollbackRecoveryRate(ctl.State, IdentityState.Default), 12);
    }

    [Fact]
    public void Shadow_evaluation_never_commits()
    {
        var ctl = new IdentityController(CdiConfig.Default);
        var before = Cdi.Hash(ctl.State);
        var shadow = ctl.Shadow(new IdentityCandidate("c", IdentitySource.User, [Ev("e1"), Ev("e2")], D((IdentityLayer.Character, "verbosity", 0.1))));
        Assert.True(shadow.Ok);
        Assert.Equal(before, Cdi.Hash(ctl.State));
        Assert.Empty(ctl.History);
    }

    [Fact]
    public void Untraceable_or_evidence_free_candidates_are_rejected()
    {
        Assert.False(Cdi.Validate(new IdentityCandidate("c", IdentitySource.User, [], D()), CdiConfig.Default).Ok);
        var untraceable = new IdentityEvidence("e1", IdentitySource.User, false, "preference", EvidenceTrigger.Deliberate);
        Assert.Contains("untraceable", Cdi.Validate(new IdentityCandidate("c", IdentitySource.User, [untraceable, Ev("e2")], D()), CdiConfig.Default).Reason, StringComparison.Ordinal);
    }

    [Fact]
    public void Constitutional_change_needs_a_non_agent_proposer_and_an_explicit_upgrade()
    {
        var delta = D((IdentityLayer.Constitutional, "harmThreshold", 0.1));
        Assert.Contains("explicitUpgrade", Cdi.Validate(new IdentityCandidate("c", IdentitySource.User, [Ev("e1"), Ev("e2")], delta), CdiConfig.Default).Reason, StringComparison.Ordinal);
        Assert.True(Cdi.Validate(new IdentityCandidate("c", IdentitySource.User, [Ev("e1"), Ev("e2")], delta, ExplicitUpgrade: true), CdiConfig.Default).Ok);
    }

    /// <summary>P1 Appendix A.7: four out-of-bounds proposals, each built so that only the targeted check can fail.</summary>
    private static IReadOnlyList<(string Case, string Expected, SolveResult Result)> A7(CdiConfig cfg)
    {
        static IdentityState Near(string key, double v)
        {
            var s = IdentityState.Default;
            s.Constitutional[key] = v;
            return s;
        }
        IdentityEvidence[] two = [Ev("e1"), Ev("e2")];
        return
        [
            ("①", "Constraint", Cdi.Solve(IdentityState.Default, new("c", IdentitySource.User, two, D((IdentityLayer.Character, "verbosity", 0.6))), cfg)),
            ("②", "Constraint", Cdi.Solve(IdentityState.Default, new("c", IdentitySource.User, [Ev("e1"), Ev("e1")], D((IdentityLayer.Character, "verbosity", 0.1))), cfg)),
            ("③", "Safety", Cdi.Solve(Near("harmThreshold", 0.9), new("c", IdentitySource.User, two, D((IdentityLayer.Constitutional, "harmThreshold", 0.2)), ExplicitUpgrade: true), cfg)),
            ("④", "Consent", Cdi.Solve(Near("userConsent", 0.9), new("c", IdentitySource.User, two, D((IdentityLayer.Constitutional, "userConsent", 0.2)), ExplicitUpgrade: true), cfg)),
            ("legit", "ok", Cdi.Solve(IdentityState.Default, new("c", IdentitySource.User, two, D((IdentityLayer.Character, "verbosity", 0.1))), cfg)),
        ];
    }

    [Fact]
    public void The_consent_stage_is_reachable_by_default_but_not_when_consent_is_also_a_safety_bound()
    {
        static string Got(SolveResult r) => r.Ok ? "ok" : r.Stage!.Value.ToString();
        var shadowed = A7(CdiConfig.ConsentAlsoSafetyBound);
        Assert.Equal(["Constraint", "Validation", "Safety", "Safety", "ok"], shadowed.Select(x => Got(x.Result)));
        var fixedDefault = A7(CdiConfig.Default);
        Assert.Equal(["Constraint", "Validation", "Safety", "Consent", "ok"], fixedDefault.Select(x => Got(x.Result)));
    }
}
