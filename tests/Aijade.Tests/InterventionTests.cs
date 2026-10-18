using System.Text.Json;

using Aijade.Memory.Experiments;
using Aijade.Memory.Interventions;

namespace Aijade.Tests;

/// <summary>Fingerprints and RNG must equal the recorded golden data.</summary>
public class InterventionTests
{
    private static readonly JsonElement Golden =
        JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "intervention-golden.json"))).RootElement;

    private static InterventionPlan Plan(string id = "test-abl", Dictionary<string, bool>? switches = null, Dictionary<string, string>? bypass = null) =>
        new(id, "Test ablation", "no replay", switches ?? new Dictionary<string, bool> { ["hac_active_replay"] = false }, bypass);

    [Fact]
    public void Shipped_plan_fingerprints_match_the_original()
    {
        var expected = Golden.GetProperty("plans").EnumerateArray().ToArray();
        Assert.Equal(expected.Select(e => e.GetProperty("id").GetString()), Interventions.AllAblationPlans.Select(p => p.Id));
        foreach (var (plan, e) in Interventions.AllAblationPlans.Zip(expected))
        {
            Assert.Equal(e.GetProperty("fp0").GetString(), Interventions.Resolve(plan).Fingerprint);
            Assert.Equal(e.GetProperty("fp42").GetString(), Interventions.Resolve(plan, 42).Fingerprint);
            Assert.Equal(e.GetProperty("fpFrac").GetString(), Interventions.Resolve(plan, 0.5).Fingerprint);
        }
        var c = Golden.GetProperty("custom");
        var custom = Interventions.Resolve(new InterventionPlan("x", "x", "x",
            new Dictionary<string, bool> { ["cdi_shadow_eval"] = false, ["hac_state"] = false },
            new Dictionary<string, string> { ["memory_window"] = "w(3)", ["long_term_memory"] = "window(8)" }), 1e21);
        Assert.Equal(c.GetProperty("fingerprint").GetString(), custom.Fingerprint);
    }

    [Fact]
    public void Rng_matches_the_original()
    {
        var rng = Interventions.Rng(7);
        foreach (var x in Golden.GetProperty("rng").EnumerateArray())
            Assert.Equal(x.GetDouble(), rng());
    }

    [Fact]
    public void Points_cover_every_group_with_full_mechanism_defaults()
    {
        Assert.Equal(Interventions.Points.Count, Interventions.Points.Select(p => p.Id).Distinct().Count());
        Assert.True(Interventions.Points.Count >= 20);
        foreach (var g in System.Enum.GetValues<InterventionGroup>())
            Assert.Contains(Interventions.Points, p => p.Group == g);
        var d = Interventions.DefaultSwitches;
        Assert.True(d["dgm_dual_graph"] && d["dgm_counter_evidence"] && d["cdi_shadow_eval"]);
        Assert.False(d["dgm_llm_commit"] || d["hac_fix_transition"] || d["hac_random_write"]);
    }

    [Fact]
    public void Validation_rejects_empty_unknown_and_anonymous_plans()
    {
        Assert.True(Interventions.Validate(Plan()).Ok);
        Assert.Contains("≥1 switch", Interventions.Validate(Plan(switches: [])).Reason, StringComparison.Ordinal);
        Assert.Contains("Unknown intervention point", Interventions.Validate(Plan(switches: new() { ["hac_sate"] = false })).Reason, StringComparison.Ordinal);
        Assert.Contains("Unknown bypass point", Interventions.Validate(Plan(bypass: new() { ["nope"] = "x" })).Reason, StringComparison.Ordinal);
        Assert.False(Interventions.Validate(Plan(id: "")).Ok);
        Assert.Contains("invalid", Assert.Throws<InterventionException>(() => Interventions.Resolve(Plan(switches: []))).Message, StringComparison.Ordinal);
        Assert.Contains("finite seed", Assert.Throws<InterventionException>(() => Interventions.Resolve(Plan(), double.NaN)).Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Resolution_merges_defaults_and_is_order_independent()
    {
        var r = Interventions.Resolve(Plan(), 7);
        Assert.False(r.IsEnabled("hac_active_replay"));
        Assert.True(r.IsEnabled("hac_state"));
        Assert.False(r.IsEnabled("nope"));
        Assert.Equal(Interventions.Points.Count, r.Switches.Count);
        Assert.Equal(r.Fingerprint, Interventions.Resolve(Plan(), 7).Fingerprint);
        Assert.NotEqual(r.Fingerprint, Interventions.Resolve(Plan(), 8).Fingerprint);
        Assert.NotEqual(r.Fingerprint, Interventions.Resolve(Plan(id: "other"), 7).Fingerprint);
        var a = Interventions.Resolve(Plan(switches: new() { ["hac_state"] = false, ["cdi_identity"] = false }));
        var b = Interventions.Resolve(Plan(switches: new() { ["cdi_identity"] = false, ["hac_state"] = false }));
        Assert.Equal(a.Fingerprint, b.Fingerprint);
        var b1 = Interventions.Resolve(Interventions.BaselinePlans[1]);
        Assert.Equal("window(8)", b1.BypassOf("long_term_memory"));
        Assert.Null(b1.BypassOf("hac_state"));
        Assert.False(Interventions.Resolve(Interventions.BaselinePlans[0]).IsEnabled("long_term_memory"));
    }

    [Fact]
    public void Registration_writes_a_manifest_condition()
    {
        var path = Path.Combine(Path.GetTempPath(), $"aijade-registry-{Guid.NewGuid():N}.json");
        try
        {
            var (manifest, resolved) = Interventions.Register(Plan(), new ExperimentRegistry(path), seed: 3);
            Assert.Equal("intervention:test-abl", manifest.Id);
            Assert.Equal(3, manifest.Seed);
            Assert.Equal("test-abl", manifest.Conditions[0].Name);
            var stored = new ExperimentRegistry(path).Read()["experiments"]!["intervention:test-abl"]!["conditions"]![0]!["params"]!;
            Assert.Equal(resolved.Fingerprint, stored["fingerprint"]!.GetValue<string>());
            Assert.False(stored["switches"]!["hac_active_replay"]!.GetValue<bool>());
            Assert.Equal("long_term_memory", ((System.Text.Json.Nodes.JsonObject)stored["switches"]!).First().Key);
        }
        finally
        {
            File.Delete(path);
        }
    }
}
