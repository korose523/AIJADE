using System.IO.Compression;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Integrations.Renderer;
using Aijade.Research.Integration;
using Aijade.Research.SkillBench;
using Aijade.Server.Product;

using Microsoft.Extensions.DependencyInjection;

namespace Aijade.Tests;

public partial class ResearchLoopQualificationTests
{
    private static string FiniteRoot()
    {
        var p = new DirectoryInfo(AppContext.BaseDirectory);
        while (p is not null && !(File.Exists(Path.Combine(p.FullName, "global.json")) && Directory.Exists(Path.Combine(p.FullName, "src")))) p = p.Parent;
        return p?.FullName ?? throw new InvalidOperationException("Repository root missing");
    }

    private static string LogicalText(string path)
    {
        if (File.Exists(path)) return File.ReadAllText(path);
        using var stream = new GZipStream(File.OpenRead(path + ".gz"), CompressionMode.Decompress);
        using var reader = new StreamReader(stream);
        return reader.ReadToEnd();
    }

    private static ResearchFiniteManifest FiniteKnown()
    {
        var known = ResearchLiveManifest.Read(File.ReadAllText(Path.Combine(FiniteRoot(), "experiments/ch7/live-manifest-known-input-v1.json")));
        return new ResearchFiniteManifest
        {
            Schema = "aijade.ch7.live-case-manifest.v2", Purpose = "qualification_only", BlockIndex = 0,
            ProtocolPlanSha256 = new string('a', 64), ConstructionFreezeCommit = new string('b', 40),
            SelectionSha256 = known.SelectionSha256,
            Cases = known.Cases.Select(c => new ResearchFiniteCase { Input = c,
                ReplayAt = c.Operations.RepeatOutcome ? "before_delivery" : "none",
                RevokeAt = c.Operations.RevokeBeforeReuse ? "after_delivery" : "none",
                FailurePoint = c.Operations.FailStateWrite ? "authority_before" : "none" }).ToList(),
        };
    }

    [Fact]
    public void Finite_parser_roundtrips_known_inputs_and_enforces_closed_source_bound_blocks()
    {
        var m = FiniteKnown();
        var text = JsonSerializer.Serialize(m, ResearchFiniteManifest.Options);
        Assert.Equal(text, JsonSerializer.Serialize(ResearchFiniteManifest.Read(text), ResearchFiniteManifest.Options));
        Action<JsonObject>[] changes =
        [
            r => r["purpose"] = "assume_confirmed",
            r => r["blockIndex"] = 4,
            r => r["constructionFreezeCommit"] = "not-a-commit",
            r => r["protocolPlanSha256"] = null,
            r => r["selectionSha256"] = new string('Z',64),
            r => r["cases"]![0]!["expectedC2"] = true,
            r => r["cases"]![0]!["input"]!["caseClass"] = "normal",
            r => r["cases"]![0]!["input"]!["operations"]!["repeatOutcome"] = true,
            r => r["cases"]![0]!["replayAt"] = "after_delivery",
            r => r["cases"]![0]!["input"]!["operations"]!["receiptCaseId"] = "unbound",
            r => r["cases"]![0]!["input"]!["codeSha256"] = "missing",
            r => r["cases"]![0]!["input"]!["conditions"] = new JsonArray("C1","C1"),
            r => r["cases"]![0]!["revokeAt"] = 1,
            r => r["cases"]![0]!.AsObject().Remove("failurePoint"),
            r => { r["purpose"] = "confirmed_finite_heldout"; r["cases"]!.AsArray().RemoveAt(0); },
        ];
        foreach (var change in changes)
        {
            var r = JsonNode.Parse(text)!.AsObject(); change(r);
            Assert.Throws<InvalidDataException>(() => ResearchFiniteManifest.Read(r.ToJsonString()));
        }
        Assert.Throws<InvalidDataException>(() => ResearchFiniteManifest.Read("{\"purpose\":\"qualification_only\"," + text[1..]));
        var aliases = m.Cases.Select((c,i) => (c.Input.CaseId, Alias: "control_alias_"+i)).ToDictionary(p => p.CaseId,p => p.Alias);
        var renamed = m with { Cases = m.Cases.Select(c => c with { Input = c.Input with {
            CaseId = aliases[c.Input.CaseId], Operations = c.Input.Operations with { ReceiptCaseId = aliases[c.Input.Operations.ReceiptCaseId] } } }).Reverse().ToList() };
        Assert.Equal(10, ResearchFiniteManifest.Read(JsonSerializer.Serialize(renamed, ResearchFiniteManifest.Options)).Cases.Count);
    }

    [Fact]
    public async Task Frozen_candidate_bank_execution_matches_original_labels_without_replacement()
    {
        var path = Path.Combine(FiniteRoot(), "experiments/ch7/finite-heldout/candidate-bank.json");
        var bank = JsonNode.Parse(File.ReadAllText(path))!;
        var results = new JsonArray();
        foreach (var p in bank["programs"]!.AsArray())
        {
            var code = p!["code"]!.GetValue<string>(); var taskId = p["taskId"]!.GetValue<string>();
            Assert.Equal(p["codeSha256"]!.GetValue<string>(), SkillEvidence.HashCode(code));
            var execution = new Sandbox { IsolateArguments = true }.RunTask(code, Bench.Tasks.Single(t => t.Id == taskId));
            results.Add(new JsonObject { ["taskId"] = taskId, ["codeSha256"] = p["codeSha256"]!.DeepClone(),
                ["archivedExecutionOk"] = p["trial"]!["execOk"]!.DeepClone(), ["actualExecution"] = JsonSerializer.SerializeToNode(execution,Json) });
        }
        if (Env("AIJADE_CH7_FINITE_BANK_CONTROL") is { } output) await File.WriteAllTextAsync(output, results.ToJsonString(Json), TestContext.Current.CancellationToken);
        Assert.Equal(8, results.Count);
        Assert.All(results, r => Assert.Equal(r!["archivedExecutionOk"]!.GetValue<bool>(), r["actualExecution"]!["ok"]!.GetValue<bool>()));
    }

    [Theory]
    [InlineData("replay", "before_delivery")]
    [InlineData("replay", "after_delivery")]
    [InlineData("replay", "after_first_reuse")]
    [InlineData("replay", "after_duplicate_reuse")]
    [InlineData("revoke", "before_delivery")]
    [InlineData("revoke", "after_delivery")]
    [InlineData("revoke", "after_memory_probe")]
    [InlineData("revoke", "after_authority_probe")]
    [InlineData("failure", "authority_before")]
    [InlineData("failure", "authority_after")]
    [InlineData("failure", "outcome_before")]
    [InlineData("failure", "outbox_before")]
    public async Task Finite_operation_placements_use_actual_known_evidence_and_preserve_full_observations(string operation, string placement)
    {
        var root = Path.Combine(FiniteRoot(), "experiments/ch7/live-manifest-2026-11-12/attempts/development-02");
        var known = FiniteKnown();
        var chosen = known.Cases.Single(c => operation == "replay" ? c.Input.Operations.RepeatOutcome :
            operation == "revoke" ? c.Input.Operations.RevokeBeforeReuse : c.Input.Operations.FailStateWrite);
        var finite = chosen with { ReplayAt = operation == "replay" ? placement : "none",
            RevokeAt = operation == "revoke" ? placement : "none", FailurePoint = operation == "failure" ? placement : "none" };
        var oldRows = JsonNode.Parse(LogicalText(Path.Combine(root,"cases.json")))!.AsArray();
        var old = oldRows.First(r => r!["caseId"]!.GetValue<string>() == finite.Input.CaseId)!;
        var temporary = Path.Combine(Path.GetTempPath(),"aijade-finite-control-"+Guid.NewGuid().ToString("N")); Directory.CreateDirectory(temporary);
        try
        {
            var registryPath = Path.Combine(temporary,"registry.jsonl");
            var statePath = Path.Combine(temporary,"state.jsonl");
            await File.WriteAllTextAsync(registryPath, LogicalText(Path.Combine(root,"registry.jsonl")), TestContext.Current.CancellationToken);
            await File.WriteAllTextAsync(statePath, LogicalText(Path.Combine(root,"client/aijade-render-state.jsonl")), TestContext.Current.CancellationToken);
            var registry = IntentRegistry.Read(registryPath);
            var import = RenderReceiptImporter.Plan(RenderSessionManifest.Seal(registry,statePath),registry,RenderStateFile.Read(statePath));
            Assert.Empty(import.FileReasons); Assert.Empty(import.Unknown);
            var results = new JsonArray();
            foreach (var condition in Enum.GetValues<ResearchConstraintCondition>())
            {
                using var gateway = new NoGateway();
                await using var host = await ServerTestHost.StartAsync(worker:false,services: services =>
                    services.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => gateway));
                await ResearchLoopAdapter.InitializeAsync(host); await InitializeFlowIdentityAsync(host);
                var phases = new List<string>();
                var result = await RunFiniteSuffixAsync(finite,old["prepared"]!.DeepClone().AsObject(),
                    old["selectedReceipt"]!["intentId"]!.GetValue<string>(),import,registry,host,gateway,
                    old["initialWrite"]!.AsObject(),old["initialRead"]!.AsObject(),condition,"qualification_only",phases.Add,TestContext.Current.CancellationToken);
                result["controlPhases"] = new JsonArray(phases.Select(p => (JsonNode)JsonValue.Create(p)!).ToArray()); results.Add(result);
                Assert.Equal(0,result["gatewayAttempts"]!.GetValue<int>());
                var trace = result["operationTrace"]!.AsArray();
                if (operation == "replay")
                {
                    Assert.True(result["duplicateCommit"]!["duplicate"]!.GetValue<bool>());
                    Assert.False(result["duplicateReuse"]!["executed"]!.GetValue<bool>());
                    Assert.Equal(placement,Assert.Single(trace)!["at"]!.GetValue<string>());
                    var begin = phases.IndexOf("replay.begin");
                    Assert.True(placement switch { "before_delivery" => begin < phases.IndexOf("delivery.begin"),
                        "after_delivery" => begin > phases.IndexOf("delivery.end") && begin < phases.IndexOf("round2.begin"),
                        "after_first_reuse" => begin > phases.IndexOf("round2.first.end") && begin < phases.IndexOf("round2.duplicate.end"),
                        _ => begin > phases.IndexOf("round2.duplicate.end") });
                }
                else if (operation == "revoke")
                {
                    Assert.Equal("authority_revoked",result["round2"]!["reason"]!.GetValue<string>());
                    Assert.True(phases.IndexOf("revoke.end") < phases.IndexOf("round2.begin"));
                    Assert.Contains(trace,r => r!["operation"]!.GetValue<string>() == "revoke" && r["at"]!.GetValue<string>() == placement);
                }
                else
                {
                    Assert.Equal("P0001",result["databaseErrorCode"]!.GetValue<string>());
                    Assert.Equal(placement,result["databaseErrorWitness"]!["point"]!.GetValue<string>());
                    Assert.Equal(1,result["databaseErrorWitness"]!["specs"]!.GetValue<int>());
                    Assert.Equal(placement == "authority_before" ? 0 : 1,result["databaseErrorWitness"]!["authority"]!.GetValue<int>());
                    Assert.Equal(0L,result["final"]!["outboxCount"]!.GetValue<long>());
                }
            }
            if (Env("AIJADE_CH7_FINITE_PLACEMENT_CONTROL") is { } output)
                await File.WriteAllTextAsync(Path.Combine(output,operation+"-"+placement+".json"),results.ToJsonString(Json), TestContext.Current.CancellationToken);
        }
        finally { Directory.Delete(temporary,true); }
    }
}
