using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Integrations.Renderer;
using Aijade.Memory.Contracts;
using Aijade.Memory.Development;
using Aijade.Memory.V9;
using Aijade.Research.Integration;
using Aijade.Research.SkillBench;
using Aijade.Server.Product;

using Microsoft.Extensions.DependencyInjection;

using Npgsql;

namespace Aijade.Tests;

/// <summary>Chapter 7 development qualification. Opt-in renderer/database measurement; never a held-out comparison.</summary>
public class ResearchLoopQualificationTests
{
    private static readonly string[] CaseIds = ["H", "I1", "I2", "I3", "I4", "I5", "I6", "I7", "I8", "S1"];
    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);

    private sealed class NoGateway : HttpMessageHandler
    {
        public int Attempts { get; private set; }

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Attempts++;
            throw new InvalidOperationException("A provider request is forbidden during Chapter 7 development qualification");
        }
    }

    private static string? Env(string name) => Environment.GetEnvironmentVariable(name) is { Length: > 0 } value ? value : null;

    private static string Required(string name) => Env(name) ?? throw new InvalidOperationException(name + " missing");

    private static DialogueAct Act(string id) => id == "S1" ? DialogueAct.Celebrate : DialogueAct.Comfort;

    private static JsonObject Envelope(string id, string session, JsonObject payload) => new()
    {
        ["event_id"] = id, ["trace_id"] = "trace-" + id, ["correlation_id"] = "corr-" + id, ["timestamp"] = 1_794_412_800_000L,
        ["producer"] = "ch7-research-adapter", ["origin_device"] = "research-host", ["privacy_level"] = 1,
        ["evidence_refs"] = new JsonArray(), ["causal_context_refs"] = new JsonArray(), ["risk_score"] = 0.1,
        ["idempotency_key"] = "idem-" + id, ["replay_mode"] = "live", ["risk_level"] = "low",
        ["tick"] = 1, ["causality"] = new JsonObject { ["inputHash"] = payload["input_hash"]!.GetValue<string>() },
        ["topic"] = "aijade.learning.proposed.shadow_params", ["payload"] = payload,
    };

    /// <summary>Input qualification: the exact selected historical code, source hash and unchanged executable verdict.</summary>
    [Fact]
    public async Task Prepare_archived_executions_and_register_before_render_dispatch()
    {
        if (Env("AIJADE_CH7_PREPARE") is not { } output)
        {
            Assert.Skip("AIJADE_CH7_PREPARE is not set (development renderer dispatch is opt-in)");
            return;
        }
        var ct = TestContext.Current.CancellationToken;
        var selection = JsonNode.Parse(await File.ReadAllTextAsync(Required("AIJADE_CH7_INPUT"), ct))!.AsObject();
        Directory.CreateDirectory(output);
        var session = Required("AIJADE_CH7_SESSION");
        var context = Required("AIJADE_CH7_CONTEXT");
        var registryPath = Path.Combine(output, "registry.jsonl");
        Assert.False(File.Exists(registryPath));
        IntentRegistry.Create(registryPath, session, context);
        var records = new JsonArray();
        using var link = new MosaicRendererLink(int.Parse(Required("AIJADE_CH7_PORT"), CultureInfo.InvariantCulture), session);
        foreach (var id in CaseIds)
        {
            var selected = selection[id == "I5" ? "unusable" : "usable"]!.AsObject();
            var code = selected["code"]!.GetValue<string>();
            Assert.Equal(selected["codeSha256"]!.GetValue<string>(), SkillEvidence.HashCode(code));
            var task = Bench.Tasks.Single(t => t.Id == selected["taskId"]!.GetValue<string>());
            var execution = id == "I4" ? null : new Sandbox { IsolateArguments = true }.RunTask(code, task);
            if (execution is not null)
                Assert.Equal(id != "I5", execution.Ok);
            var intentId = "pi_" + session + "_" + id;
            var intent = ResearchIntentMapper.Map(Act(id), intentId, "persona:ch7", execution?.Ok);
            var registered = new RegisteredIntent(intentId, intent.PersonaSnapshotRef, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
            IntentRegistry.Append(registryPath, registered);
            var packets = await link.SendAsync(intent, ct: ct);
            records.Add(new JsonObject
            {
                ["caseId"] = id, ["taskId"] = task.Id, ["code"] = code, ["codeSha256"] = SkillEvidence.HashCode(code),
                ["benchSha256"] = Bench.ManifestSha256, ["historicalSelection"] = selected.DeepClone(),
                ["executionId"] = "execution-" + session + "-" + id, ["execution"] = JsonSerializer.SerializeToNode(execution, Json),
                ["intentId"] = intentId, ["registered"] = JsonSerializer.SerializeToNode(registered, Json),
                ["mapperVersion"] = ResearchIntentMapper.Version, ["requestedAct"] = "comfort", ["mapperInputAct"] = WireName.Of(Act(id)),
                ["dispatchedAct"] = WireName.Of(execution?.Ok == true ? Act(id) : DialogueAct.Inform),
                ["packets"] = new JsonArray(packets.Select(p => (JsonNode)p.DeepClone()).ToArray()),
            });
            await File.WriteAllTextAsync(Path.Combine(output, "prepared.json"), records.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + "\n", ct);
            await Task.Delay(1000, ct);
        }
        Assert.Equal(20, link.Sent);
    }

    /// <summary>The declared ten cases on a newly closed/sealed client file and real PostgreSQL/event/memory paths.</summary>
    [Fact]
    public async Task Qualify_ten_declared_cases_on_the_staged_C2_path()
    {
        if (Env("AIJADE_CH7_RUN") is not { } directory)
        {
            Assert.Skip("AIJADE_CH7_RUN is not set (no development or held-out measurement enabled)");
            return;
        }
        var ct = TestContext.Current.CancellationToken;
        var registry = IntentRegistry.Read(Path.Combine(directory, "registry.jsonl"));
        var file = RenderStateFile.Read(Path.Combine(directory, "client", "aijade-render-state.jsonl"));
        var manifest = RenderSessionManifest.Seal(registry, Path.Combine(directory, "client", "aijade-render-state.jsonl"));
        await File.WriteAllTextAsync(Path.Combine(directory, "manifest.json"), manifest.ToJson() + "\n", ct);
        var import = RenderReceiptImporter.Plan(manifest, registry, file);
        Assert.Empty(import.FileReasons);
        Assert.Empty(import.Unknown);
        Assert.Equal(CaseIds.Length, import.Receipts.Count);
        var prepared = JsonNode.Parse(await File.ReadAllTextAsync(Path.Combine(directory, "prepared.json"), ct))!.AsArray();
        var rows = new JsonArray();
        foreach (var id in CaseIds)
        {
            var source = prepared.Single(p => p!["caseId"]!.GetValue<string>() == id)!.AsObject();
            var result = await RunCaseAsync(id, source, import, registry, ct);
            rows.Add(result);
            await File.WriteAllTextAsync(Path.Combine(directory, "cases.json"), rows.ToJsonString(new JsonSerializerOptions { WriteIndented = true }) + "\n", ct);
        }
        Assert.All(rows, r => Assert.True(r!["qualified"]!.GetValue<bool>(), r.ToJsonString()));
    }

    private static async Task<JsonObject> RunCaseAsync(string id, JsonObject source, ReceiptImportPlan import, IntentRegistry registry, CancellationToken ct)
    {
        using var gateway = new NoGateway();
        await using var host = await ServerTestHost.StartAsync(worker: false, services: services =>
            services.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => gateway));
        await ResearchLoopAdapter.InitializeAsync(host);
        var adapter = new ResearchLoopAdapter(host);
        var initial = ResearchLoopAdapter.Perception("initial-" + id, registry.SessionId, "ch7_initial " + id + " requested_act comfort");
        var (initialStatus, initialResponse) = await host.PostAsync("/api/v1/v9/perception", initial);
        Assert.Equal(201, initialStatus);
        var initialPath = "/api/v1/memory/items/?q=" + Uri.EscapeDataString("ch7_initial " + id) + "&limit=6";
        var (initialReadStatus, initialRead) = await host.SendAsync(HttpMethod.Get, initialPath);
        Assert.Equal(200, initialReadStatus);
        Assert.Single(initialRead!["items"]!.AsArray());
        var importPosts = new JsonArray();
        await RenderReceiptImporter.ImportAsync(import, async e =>
        {
            var (status, response) = await host.PostAsync("/api/v1/v9/events", e);
            importPosts.Add(new JsonObject { ["request"] = e.DeepClone(), ["status"] = status, ["response"] = response });
            return status;
        });
        var ownIntent = source["intentId"]!.GetValue<string>();
        var receipt = import.Receipts.Single(r => r.IntentId == ownIntent);
        if (id == "I1")
            receipt = import.Receipts.Single(r => r.IntentId == preparedOtherIntent(registry));
        var code = source["code"]!.GetValue<string>();
        var task = Bench.Tasks.Single(t => t.Id == source["taskId"]!.GetValue<string>());
        var execution = source["execution"] is null ? null : source["execution"]!.Deserialize<ExecutionVerdict>(Json);
        var evidence = new SkillEvidence("skill-" + id, SkillEvidence.HashCode(code), task.Id, Bench.ManifestSha256,
            source["executionId"]!.GetValue<string>(), ownIntent, registry.SessionId, id == "I2" ? "different-asset" : receipt.AssetVersionHash,
            receipt.IntentId, receipt.AssetVersionHash, SkillEvidence.AppliedStage, id == "I6" ? "pixels_observed" : SkillEvidence.AppliedStage,
            execution?.Ok, execution?.Passed ?? 0, execution?.Total ?? task.Tests.Count, "pass");
        var proposalId = "proposal-" + id;
        var parameters = new JsonObject { ["emotion.preset"] = source["dispatchedAct"]!.GetValue<string>() };
        var proposal = new ShadowParamsProposal(proposalId, registry.SessionId,
            ShadowParams.ComputeLearningInputHash(registry.SessionId, proposalId, parameters), ShadowParamsAnchorKind.ShadowParams, true,
            parameters, 0.9, receipt.RenderRef, receipt.AppliedParamsHash, evidence.AssetVersion);
        var payload = new JsonObject
        {
            ["session_id"] = registry.SessionId, ["render_ref"] = receipt.RenderRef,
            ["applied_params_hash"] = receipt.AppliedParamsHash, ["asset_version_hash"] = evidence.AssetVersion,
            ["proposal_id"] = proposalId, ["input_hash"] = proposal.InputHash,
            ["candidate_params"] = parameters.DeepClone(), ["confidence"] = 0.9,
        };
        var envelope = Envelope("evt-" + proposalId, registry.SessionId, payload);
        var (admissionStatus, admissionBody) = await host.PostAsync("/api/v1/v9/events", envelope);
        if (id == "I8")
            await host.ExecAsync("""
                CREATE FUNCTION reject_authority() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN
                    IF (SELECT count(*) FROM evolution_specs) <> 1 OR (SELECT count(*) FROM eval_reports) <> 1 THEN
                        RAISE EXCEPTION 'promotion rows not visible before injected failure' USING ERRCODE='P0002';
                    END IF;
                    RAISE EXCEPTION 'ch7 injected authority-write failure' USING ERRCODE='P0001'; END $$;
                CREATE TRIGGER reject_authority_write BEFORE INSERT OR UPDATE ON research_skill_authority
                FOR EACH ROW EXECUTE FUNCTION reject_authority();
                """);
        var outcomeId = "outcome-" + id;
        ResearchLoopAdapter.CommitResult? commit = null;
        ResearchLoopAdapter.CommitResult? duplicate = null;
        string? databaseError = null;
        try
        {
            commit = await adapter.CommitAsync(outcomeId, evidence, proposal, "evt-" + proposalId, ct);
            if (id == "I3")
                duplicate = await adapter.CommitAsync(outcomeId, evidence, proposal, "evt-" + proposalId, ct);
        }
        catch (PostgresException ex) when (id == "I8" && ex.SqlState == "P0001")
        {
            databaseError = ex.SqlState;
        }
        var beforeDelivery = await adapter.SnapshotAsync();
        var delivery = await adapter.DeliverAsync(outcomeId);
        JsonObject? duplicateDelivery = null;
        if (id == "I3")
            duplicateDelivery = await adapter.DeliverAsync(outcomeId);
        if (id == "I7")
            await adapter.RevokeAsync(evidence.SkillId, ct);
        var round2 = await adapter.Round2Async(outcomeId, evidence.SkillId, code, task, ct);
        JsonObject? duplicateReuse = null;
        if (id == "I3")
            duplicateReuse = await adapter.Round2Async(outcomeId, evidence.SkillId, code, task, ct);
        var final = await adapter.SnapshotAsync();
        var expectedPromoted = id is "H" or "I3" or "I7" or "S1";
        var expectedReuse = id is "H" or "I3" or "S1";
        var promoted = final["specs"]!.GetValue<long>();
        var reports = final["reports"]!.GetValue<long>();
        var authority = final["authority"]!.AsArray();
        var state = authority.Count == 0 ? "absent" : authority[0]!["state"]!.GetValue<string>();
        var expectedState = id == "I8" ? "absent" : id == "I7" ? "revoked" : expectedPromoted ? "verified" : id == "I5" ? "failed" : "unknown";
        var qualified = gateway.Attempts == 0 && promoted == (expectedPromoted ? 1 : 0) && reports == promoted && state == expectedState &&
            round2["executed"]!.GetValue<bool>() == expectedReuse && final["reuseCount"]!.GetValue<long>() == (expectedReuse ? 1 : 0) &&
            final["outcomeMemoryCount"]!.GetValue<long>() == (id == "I8" ? 0 : 1) &&
            (id != "I1" || commit?.Outcome.Reason == "execution_intent_mismatch") &&
            (id != "I2" || admissionStatus == 400 && admissionBody!.ToJsonString().Contains("asset_version_hash_mismatch", StringComparison.Ordinal)) &&
            (id != "I4" || commit?.Outcome.Reason == "execution_unknown") &&
            (id != "I5" || commit?.Outcome.Reason == "execution_failed") &&
            (id != "I6" || commit?.Outcome.Reason == "receipt_stage_insufficient") &&
            (id != "I7" || round2["retrieved"]!.GetValue<bool>() && round2["memoryOutcome"]!["state"]!.GetValue<string>() == "verified") &&
            (id != "I3" || duplicate?.Duplicate == true && duplicateDelivery?["duplicate"]?.GetValue<bool>() == true && duplicateReuse?["executed"]?.GetValue<bool>() == false) &&
            (id != "I8" || databaseError == "P0001" && final["outboxCount"]!.GetValue<long>() == 0 && authority.Count == 0);
        return new JsonObject
        {
            ["caseId"] = id, ["batch"] = "development_qualification_only", ["condition"] = "C2", ["qualified"] = qualified,
            ["gatewayAttempts"] = gateway.Attempts,
            ["expected"] = new JsonObject { ["promotions"] = expectedPromoted ? 1 : 0, ["state"] = expectedState, ["round2Execution"] = expectedReuse },
            ["initialWrite"] = new JsonObject { ["request"] = initial, ["status"] = initialStatus, ["response"] = initialResponse },
            ["initialRead"] = new JsonObject { ["path"] = initialPath, ["status"] = initialReadStatus, ["response"] = initialRead },
            ["prepared"] = source.DeepClone(), ["importPosts"] = importPosts, ["selectedReceipt"] = JsonSerializer.SerializeToNode(receipt, Json),
            ["evidence"] = JsonSerializer.SerializeToNode(evidence, Json), ["proposal"] = proposal.ToJson(),
            ["admission"] = new JsonObject { ["request"] = envelope, ["status"] = admissionStatus, ["response"] = admissionBody },
            ["commit"] = JsonSerializer.SerializeToNode(commit, Json), ["duplicateCommit"] = JsonSerializer.SerializeToNode(duplicate, Json),
            ["databaseErrorCode"] = databaseError, ["beforeDelivery"] = beforeDelivery, ["delivery"] = delivery,
            ["duplicateDelivery"] = duplicateDelivery, ["round2"] = round2, ["duplicateReuse"] = duplicateReuse,
            ["final"] = final, ["semanticMismatchConstructed"] = id == "S1",
        };

        static string preparedOtherIntent(IntentRegistry registered) => registered.Intents.Single(i => i.IntentId.EndsWith("_S1", StringComparison.Ordinal)).IntentId;
    }
}
