using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Providers.Substrate;

namespace Aijade.Tests;

/// <summary>The model substrate's fingerprints and determinism audit must equal the recorded golden data (fake substrates).</summary>
public class SubstrateTests
{
    private static readonly JsonElement Golden =
        JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Golden", "substrate-golden.json"))).RootElement;

    private static readonly ModelIdentity Id = new("qwythos", "sha256:abc123");

    private static readonly ChatMessage[] M = [new(ChatRole.User, "hi")];

    /// <summary>A substrate whose output is a function of the sampling it receives (or an exception).</summary>
    private sealed class Fake(Func<SamplingConfig, int, string?> gen) : ISubstrate
    {
        private int _i;

        public Task<ModelIdentity> IdentityAsync(CancellationToken cancellationToken = default) => Task.FromResult(Id);

        public Task<RunFingerprint> FingerprintAsync(SamplingConfig? sampling = null, CancellationToken cancellationToken = default) =>
            Task.FromResult(SubstrateFingerprint.Build(SubstrateMode.Research, Id, sampling ?? SamplingConfig.Research, "0.34.0"));

        public Task<GenerateResult> GenerateAsync(GenerateOptions options, CancellationToken cancellationToken = default)
        {
            var text = gen(options.Sampling!, _i++) ?? throw new InvalidOperationException("HTTP 400 Bad Request");
            return Task.FromResult(new GenerateResult(text, SubstrateFingerprint.Build(SubstrateMode.Research, Id, options.Sampling!, "0.34.0"), "qwythos", "x"));
        }
    }

    private static string S(double seed) => JsFormat.Number(seed);

    private static readonly Dictionary<string, Func<Fake>> Scenarios = new()
    {
        ["pass"] = () => new Fake((s, _) => s.Temperature == 0 ? "same" : $"t{S(s.Seed)}"),
        ["falsePositive"] = () => new Fake((_, _) => "same"),
        ["inconclusive"] = () => new Fake((s, _) => s.Temperature == 0 ? "same" : null),
        ["nondet"] = () => new Fake((s, i) => s.Temperature == 0 ? $"x{i % 2}" : $"t{S(s.Seed)}"),
        ["emptyControl"] = () => new Fake((s, _) => s.Temperature == 0 ? "same" : ""),
    };

    [Fact]
    public async Task Fingerprints_and_audits_match_the_original()
    {
        var ct = TestContext.Current.CancellationToken;
        Assert.Equal(Golden.GetProperty("hashResearch").GetString(), SubstrateFingerprint.HashSampling(SamplingConfig.Research));
        Assert.Equal(Golden.GetProperty("hashQwythos").GetString(), SubstrateFingerprint.HashSampling(SamplingConfig.QwythosInteractive));
        Assert.Equal(Golden.GetProperty("fps").EnumerateArray().Select(x => x.GetString()), new[]
        {
            SubstrateFingerprint.Build(SubstrateMode.Research, Id, SamplingConfig.Research, "0.33.3").Fingerprint,
            SubstrateFingerprint.Build(SubstrateMode.Interactive, new ModelIdentity("q"), SamplingConfig.QwythosInteractive).Fingerprint,
            SubstrateFingerprint.Build(SubstrateMode.Research, new ModelIdentity("q", "sha256:bbb"), SamplingConfig.Research with { NumCtx = 0.5 }).Fingerprint,
        });
        Assert.Equal(Golden.GetProperty("text").EnumerateArray().Select(x => x.GetString()), new[] { Determinism.HashText(""), Determinism.HashText("水循环 water cycle 😀") });

        foreach (var audit in Golden.GetProperty("audits").EnumerateObject())
        {
            var e = audit.Value;
            var a = await Determinism.AuditAsync(Scenarios[audit.Name](), M, 3, audit.Name == "pass" ? SeedStrategy.Varied : SeedStrategy.Fixed, ct: ct);
            Assert.Equal(e.GetProperty("verdict").GetString(), Determinism.Kebab(a.Verdict));
            Assert.Equal((e.GetProperty("discriminative").GetBoolean(), e.GetProperty("falsePositiveRisk").GetBoolean()), (a.Discriminative, a.FalsePositiveRisk));
            Assert.Equal(e.GetProperty("reason").GetString(), a.Reason);
            Assert.Equal(e.GetProperty("controlVerdict").GetString(), WireName.Of(a.Control.Verdict));
            Assert.Equal(e.GetProperty("samplingJson").GetString(), JsFormat.Stringify(a.Control.Sampling.ToJson()));
            Assert.Equal(e.GetProperty("samplingHash").GetString(), a.Control.SamplingHash);
            Assert.Equal(e.GetProperty("checkHashes").EnumerateArray().Select(x => (x[0].GetDouble(), x[1].GetString())), a.Check.PerRun.Select(r => (r.Seed, (string?)r.Hash)));
            Assert.Equal(e.GetProperty("controlHashes").EnumerateArray().Select(x => (x[0].GetDouble(), x[1].GetString())), a.Control.PerRun.Select(r => (r.Seed, (string?)r.Hash)));
        }
        var custom = await Determinism.AuditAsync(Scenarios["falsePositive"](), M, 2, controlSampling: new JsonObject { ["top_k"] = 100, ["temperature"] = 1.5 }, ct: ct);
        Assert.Equal(Golden.GetProperty("customReason").GetString(), custom.Reason);
        Assert.Equal(Golden.GetProperty("customSampling").GetString(), JsFormat.Stringify(custom.Control.Sampling.ToJson()));
        Assert.Equal(Golden.GetProperty("measure").EnumerateArray().Select(x => x.GetDouble()), (await Determinism.MeasureAsync(Scenarios["pass"](), M, ct: ct)).PerRun.Select(r => r.Seed));
    }

    [Fact]
    public async Task Guards_refuse_unreproducible_configurations()
    {
        var ct = TestContext.Current.CancellationToken;
        Assert.Throws<SamplingException>(() => SubstrateFingerprint.AssertComplete(SamplingConfig.Research with { Temperature = double.NaN }));
        Assert.Contains("temperature=0", Assert.Throws<SamplingException>(() => SubstrateFingerprint.AssertResearchMode(SamplingConfig.Research with { Temperature = 0.6 })).Message, StringComparison.Ordinal);
        using var http = new HttpClient();
        Assert.Throws<SamplingException>(() => new OllamaSubstrate(http, " "));
        Assert.Throws<SamplingException>(() => new OllamaSubstrate(http, "q", SubstrateMode.Research, SamplingConfig.QwythosInteractive));
        Assert.Equal("http://h:1", new OllamaSubstrate(http, "q", baseUrl: "http://h:1///").BaseUrl);
        Assert.NotEqual(SubstrateFingerprint.Build(SubstrateMode.Research, Id, SamplingConfig.Research).Fingerprint,
            SubstrateFingerprint.Build(SubstrateMode.Interactive, Id, SamplingConfig.Research).Fingerprint);
        await Assert.ThrowsAsync<NonDeterministicSubstrateException>(() => Determinism.AssertAsync(Scenarios["nondet"](), M, 3, ct: ct));
        Assert.Contains("false-positive-risk", (await Assert.ThrowsAsync<NonDeterministicSubstrateException>(() => Determinism.AssertAuditAsync(Scenarios["falsePositive"](), M, 3, ct: ct))).Message, StringComparison.Ordinal);
        Assert.Contains("control hashes", (await Assert.ThrowsAsync<NonDeterministicSubstrateException>(() => Determinism.AssertAuditAsync(Scenarios["inconclusive"](), M, 3, ct: ct))).Message, StringComparison.Ordinal);
        Assert.Equal(DeterminismAuditVerdict.Pass, (await Determinism.AssertAuditAsync(Scenarios["pass"](), M, 3, ct: ct)).Verdict);
        Assert.Equal(2, (await Determinism.MeasureAsync(Scenarios["pass"](), M, 1, ct: ct)).Runs);
    }
}
