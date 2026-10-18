using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Memory.Contracts;
using Aijade.Memory.Experiments;
using Aijade.Memory.Kernel;

namespace Aijade.Tests;

/// <summary>Capability tokens and the experiment registry, plus a byte-exact round trip of the committed registry.</summary>
public class CapabilityAndExperimentTests
{
    private static readonly CapabilityGrant Grant = new("g1", new Grantee(UserScope: "u1"), "memory.write", "session:s1", "user", 10, "explicit",
        [new SourceRef("consent:1", true)], ExpiresAt: 100);

    private sealed class FixedSigner(CapabilityClaims claims) : ICapabilityTokenSigner
    {
        public Task<string> SignAsync(CapabilityClaims c, CancellationToken cancellationToken = default) => Task.FromResult("unused");

        public Task<CapabilityClaims> VerifyAsync(string token, CancellationToken cancellationToken = default) => Task.FromResult(claims);
    }

    private static MemoryWriteGate Gate(CapabilityClaims claims) => new(new FixedSigner(claims), [Grant]);

    private static readonly CapabilityClaims Valid = new("g1", "memory.write", "session:s1", new Grantee(UserScope: "u1"), 10, 100);

    [Fact]
    public async Task Accepts_a_signed_token_backed_by_an_active_grant()
    {
        var token = await Gate(Valid).AuthorizeAsync("token", "memory.write", "session:s1", now: 50, cancellationToken: TestContext.Current.CancellationToken);
        Assert.Equal("g1", token.Claims.GrantId);
        Assert.Equal("token", token.Token);
    }

    [Theory]
    [InlineData("memory.write", "session:s2", 50, "scope mismatch")]
    [InlineData("memory.delete", "session:s1", 50, "capability mismatch")]
    [InlineData("memory.write", "session:s1", 100, "token expired or not yet valid")]
    [InlineData("memory.write", "session:s1", 5, "token expired or not yet valid")]
    public async Task Rejects_tokens_outside_their_grant(string capability, string scope, double now, string reason)
    {
        var e = await Assert.ThrowsAsync<MemoryWriteDeniedException>(() => Gate(Valid).AuthorizeAsync("token", capability, scope, now, TestContext.Current.CancellationToken));
        Assert.Contains(reason, e.Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task Rejects_a_token_whose_grant_is_unknown_or_has_lapsed()
    {
        var e = await Assert.ThrowsAsync<MemoryWriteDeniedException>(() => Gate(Valid with { GrantId = "g2" }).AuthorizeAsync("t", "memory.write", "session:s1", 50, TestContext.Current.CancellationToken));
        Assert.Contains("no active capability grant", e.Message, StringComparison.Ordinal);
        // Token valid until 200, but the grant itself ended at 100.
        e = await Assert.ThrowsAsync<MemoryWriteDeniedException>(() => Gate(Valid with { ExpiresAt = 200 }).AuthorizeAsync("t", "memory.write", "session:s1", 150, TestContext.Current.CancellationToken));
        Assert.Contains("no active capability grant", e.Message, StringComparison.Ordinal);
    }

    private static readonly ManifestSpec Base = new("test-exp", "Test experiment",
        [new ExperimentCondition("on", "gating on"), new ExperimentCondition("off", "gating off")], ["recall", "f1"], Seed: 0);

    [Fact]
    public void Builds_a_valid_manifest_with_defaults()
    {
        var m = ExperimentManifests.Build(Base with { Seed = null });
        Assert.Equal(0, m.Seed);
        Assert.Matches(@"^\d+\.\d+\.\d+$", m.Version);
        Assert.True(m.CreatedAt > 0);
        Assert.Equal("diagnostic only", ExperimentManifests.Build(Base with { Notes = "diagnostic only" }).Notes);
    }

    [Fact]
    public void Rejects_manifests_that_cannot_be_falsified_or_reproduced()
    {
        Assert.Contains("condition", Assert.Throws<ExperimentManifestException>(() => ExperimentManifests.Build(Base with { Conditions = [] })).Message, StringComparison.Ordinal);
        Assert.Contains("metric", Assert.Throws<ExperimentManifestException>(() => ExperimentManifests.Build(Base with { Metrics = [] })).Message, StringComparison.Ordinal);
        Assert.Contains("seed", Assert.Throws<ExperimentManifestException>(() => ExperimentManifests.Build(Base with { Seed = double.NaN })).Message, StringComparison.Ordinal);
    }

    [Fact]
    public void Reregistration_overwrites_but_keeps_the_first_createdAt()
    {
        var path = Path.Combine(Path.GetTempPath(), $"aijade-registry-{Guid.NewGuid():N}.json");
        try
        {
            var registry = new ExperimentRegistry(path);
            registry.Register(ExperimentManifests.Build(Base) with { CreatedAt = 1 });
            var reg = registry.Register(ExperimentManifests.Build(Base with { Name = "Test experiment (updated)" }) with { CreatedAt = 2 });
            Assert.Equal(1, reg["count"]!.GetValue<int>());
            var entry = registry.Read()["experiments"]!["test-exp"]!;
            Assert.Equal("Test experiment (updated)", entry["name"]!.GetValue<string>());
            Assert.Equal(1, WireNumber(entry["createdAt"]));
        }
        finally
        {
            File.Delete(path);
        }
    }

    [Fact]
    public void Corrupt_or_foreign_registry_reads_as_empty()
    {
        var path = Path.Combine(Path.GetTempPath(), $"aijade-registry-{Guid.NewGuid():N}.json");
        try
        {
            File.WriteAllText(path, "{not json");
            Assert.Equal(0, new ExperimentRegistry(path).Read()["count"]!.GetValue<int>());
            File.WriteAllText(path, """{"schema":"other","experiments":{}}""");
            Assert.Equal(0, new ExperimentRegistry(path).Read()["count"]!.GetValue<int>());
        }
        finally
        {
            File.Delete(path);
        }
    }

    [Fact]
    public void A_written_registry_round_trips_byte_for_byte()
    {
        var path = Path.Combine(Path.GetTempPath(), $"aijade-registry-{Guid.NewGuid():N}.json");
        try
        {
            var registry = new ExperimentRegistry(path);
            foreach (var (id, notes) in new[] { ("weight-ablation", "LoCoMo, no gating"), ("leakage-audit", (string?)null) })
                registry.Register(ExperimentManifests.Build(new ManifestSpec(id, id, [new ExperimentCondition("baseline", "default weights")],
                    ["recall@8", "mrr"], Seed: 42, Notes: notes)));
            var text = File.ReadAllText(path);
            var reg = new ExperimentRegistry(path).Read();
            Assert.Equal(2, reg["count"]!.GetValue<int>());
            Assert.Equal(text, JsFormat.Stringify(reg, 2) + "\n");
        }
        finally
        {
            File.Delete(path);
        }
    }

    private static double WireNumber(JsonNode? n) => Aijade.Core.Schema.WireSchema.NumberOf(n);
}
