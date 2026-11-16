using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Integrations.Renderer;
using Aijade.Memory.Development;
using Aijade.Memory.V9;
using Aijade.Research.Integration;
using Aijade.Research.SkillBench;
using Aijade.Server.Product;
using Aijade.Server.V9;

using Microsoft.Extensions.DependencyInjection;

using Npgsql;

namespace Aijade.Tests;

public partial class ResearchLoopQualificationTests
{
    private sealed record ManifestPair(string Condition, ResearchLiveCase Definition, LiveCase Context);

    [Fact]
    public async Task Run_live_manifest_known_development_dataflow()
    {
        if (Env("AIJADE_CH7_LIVE_MANIFEST_OUTPUT") is not { } directory)
        {
            Assert.Skip("Live known-development manifest measurement is opt-in; held-out execution is disabled");
            return;
        }
        var ct = TestContext.Current.CancellationToken;
        var manifestText = await File.ReadAllTextAsync(Required("AIJADE_CH7_LIVE_CASES"), ct);
        var manifest = ResearchLiveManifest.Read(manifestText);
        var selection = Selection();
        Assert.Equal(manifest.SelectionSha256, SkillEvidence.HashCode(await File.ReadAllTextAsync(Required("AIJADE_CH7_INPUT"), ct)));
        var catalogue = Catalogue(selection);
        var session = Required("AIJADE_CH7_SESSION");
        var journal = new FlowJournal(Path.Combine(directory, "journal.jsonl"));
        var live = new List<ManifestPair>();
        var prepared = new JsonArray();
        var results = new JsonArray();
        journal.Add("batch", "batch.begin", JsonSerializer.SerializeToNode(manifest, ResearchLiveManifest.Options));
        try
        {
            foreach (var definition in manifest.Cases)
            {
                foreach (var condition in definition.Conditions)
                {
                    var id = definition.CaseId; var key = PairKey(id, condition);
                    var gateway = new NoGateway();
                    var host = await ServerTestHost.StartAsync(worker: false, services: services =>
                        services.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => gateway));
                    var database = new JsonObject { ["database"] = await host.ScalarAsync("SELECT current_database()"), ["caseId"] = id, ["condition"] = condition };
                    File.AppendAllText(Path.Combine(directory, "database-leases.jsonl"), database.ToJsonString(Json) + "\n");
                    var context = new LiveCase(id, host, gateway, new JsonObject(), new JsonObject(), new JsonObject(), database);
                    live.Add(new ManifestPair(condition, definition, context));
                    await ResearchLoopAdapter.InitializeAsync(host);
                    await InitializeFlowIdentityAsync(host);
                    database = await DatabaseIdentityAsync(host);
                    journal.Add(key, "database.open", database);
                    var candidate = catalogue.Single(c => c.TaskId == definition.TaskId && c.CodeSha256 == definition.CodeSha256);
                    var (write, read, route) = await RetrieveManifestRouteAsync(host, definition, candidate, catalogue, session, journal, key);
                    var task = Bench.Tasks.Single(t => t.Id == route.Program.TaskId);
                    journal.Add(key, "execution.begin");
                    var execution = definition.Operations.Execution == "omit" ? null : new Sandbox { IsolateArguments = true }.RunTask(route.Program.Code, task);
                    journal.Add(key, "execution.end", JsonSerializer.SerializeToNode(execution, Json));
                    var act = definition.Operations.MapperActOverride is { } overridden
                        ? Enum.Parse<DialogueAct>(overridden, true) : route.RequestedAct;
                    var intentId = "pi_" + session + "_" + id;
                    var intent = ResearchIntentMapper.Map(act, intentId, "persona:ch7", execution?.Ok);
                    var archived = CatalogueKeys.Select(k => selection[k]!).Single(p => p["taskId"]!.GetValue<string>() == route.Program.TaskId && p["codeSha256"]!.GetValue<string>() == route.Program.CodeSha256);
                    var source = new JsonObject
                    {
                        ["caseId"] = id, ["condition"] = condition, ["runtimeCase"] = JsonSerializer.SerializeToNode(definition, ResearchLiveManifest.Options),
                        ["taskId"] = task.Id, ["code"] = route.Program.Code, ["codeSha256"] = route.Program.CodeSha256,
                        ["route"] = JsonSerializer.SerializeToNode(route, Json), ["routeVersion"] = ResearchRetrievedRoute.Version,
                        ["benchSha256"] = Bench.ManifestSha256, ["archivedSelfVerdict"] = archived["trial"]!["selfVerdict"]!.GetValue<string>(),
                        ["executionId"] = "execution-" + session + "-" + id, ["execution"] = JsonSerializer.SerializeToNode(execution, Json),
                        ["intentId"] = intentId, ["mappedIntent"] = JsonSerializer.SerializeToNode(intent, Json), ["mapperVersion"] = ResearchIntentMapper.Version,
                        ["requestedAct"] = WireName.Of(route.RequestedAct), ["mapperInputAct"] = WireName.Of(act),
                        ["dispatchedAct"] = WireName.Of(execution?.Ok == true ? act : DialogueAct.Inform), ["databaseBefore"] = database.DeepClone(),
                    };
                    journal.Add(key, "intent.mapped", source);
                    live[^1] = new ManifestPair(condition, definition, new LiveCase(id, host, gateway, source, write, read, database));
                    prepared.Add(source.DeepClone());
                    await WriteFlowAsync(Path.Combine(directory, "prepared.json"), prepared, ct);
                }
                var a = live[^2].Context; var b = live[^1].Context;
                Assert.True(JsonNode.DeepEquals(a.InitialWrite["request"], b.InitialWrite["request"]));
                Assert.True(JsonNode.DeepEquals(a.InitialRead, b.InitialRead));
                Assert.True(JsonNode.DeepEquals(a.Source["route"], b.Source["route"]));
                Assert.True(JsonNode.DeepEquals(a.Source["mappedIntent"], b.Source["mappedIntent"]));
                Assert.True(JsonNode.DeepEquals(WithoutExecutionDuration(a.Source["execution"]), WithoutExecutionDuration(b.Source["execution"])));
                journal.Add(definition.CaseId, "pair.inputs_equal");
            }
            journal.Add("batch", "prefixes.complete");
            await WriteFlowAsync(Path.Combine(directory, "renderer-request.tmp"), new JsonObject
            {
                ["session"] = session, ["preparedSha256"] = SkillEvidence.HashCode(await File.ReadAllTextAsync(Path.Combine(directory, "prepared.json"), ct)),
            }, ct);
            File.Move(Path.Combine(directory, "renderer-request.tmp"), Path.Combine(directory, "renderer-request.json"));
            var ready = await WaitFlowAsync(Path.Combine(directory, "renderer-ready.json"), ct);
            journal.Add("batch", "renderer.ready", ready);
            var registryPath = Path.Combine(directory, "registry.jsonl");
            IntentRegistry.Create(registryPath, session, ready["context"]!.GetValue<string>());
            using (var link = new MosaicRendererLink(ready["port"]!.GetValue<int>(), session))
            {
                foreach (var definition in manifest.Cases)
                {
                    var contexts = live.Where(c => c.Definition.CaseId == definition.CaseId).ToArray();
                    var source = contexts[0].Context.Source;
                    var intent = ResearchIntentMapper.Map(Enum.Parse<DialogueAct>(source["mapperInputAct"]!.GetValue<string>(), true),
                        source["intentId"]!.GetValue<string>(), "persona:ch7", source["execution"]?["ok"]?.GetValue<bool>());
                    var registered = new RegisteredIntent(intent.Id, intent.PersonaSnapshotRef, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
                    IntentRegistry.Append(registryPath, registered);
                    journal.Add(definition.CaseId, "intent.registered", JsonSerializer.SerializeToNode(registered, Json));
                    var packets = await link.SendAsync(intent, ct: ct);
                    foreach (var context in contexts)
                    {
                        context.Context.Source["registered"] = JsonSerializer.SerializeToNode(registered, Json);
                        context.Context.Source["packets"] = new JsonArray(packets.Select(p => (JsonNode)p.DeepClone()).ToArray());
                        journal.Add(PairKey(definition.CaseId, context.Condition), "shared_intent.sent", context.Context.Source);
                    }
                    await Task.Delay(1000, ct);
                }
                Assert.Equal(manifest.Cases.Count * 2, link.Sent);
            }
            await WriteFlowAsync(Path.Combine(directory, "prepared-dispatched.json"), new JsonArray(live.Select(c => (JsonNode)c.Context.Source.DeepClone()).ToArray()), ct);
            var closed = await WaitFlowAsync(Path.Combine(directory, "renderer-closed.json"), ct);
            journal.Add("batch", "renderer.closed", closed);
            Assert.Equal(0, closed["exitCode"]!.GetValue<int>());
            var statePath = Path.Combine(directory, "client", "aijade-render-state.jsonl");
            Assert.Equal(closed["stateSha256"]!.GetValue<string>(), Convert.ToHexStringLower(SHA256.HashData(await File.ReadAllBytesAsync(statePath, ct))));
            var registry = IntentRegistry.Read(registryPath);
            var renderManifest = RenderSessionManifest.Seal(registry, statePath);
            await File.WriteAllTextAsync(Path.Combine(directory, "manifest.json"), renderManifest.ToJson() + "\n", ct);
            var import = RenderReceiptImporter.Plan(renderManifest, registry, RenderStateFile.Read(statePath));
            Assert.Empty(import.FileReasons); Assert.Empty(import.Unknown); Assert.Equal(manifest.Cases.Count, import.Receipts.Count);
            foreach (var pair in live)
            {
                var context = pair.Context; var key = PairKey(context.Id, pair.Condition);
                var before = await DatabaseIdentityAsync(context.Host);
                journal.Add(key, "database.resumed", before);
                Assert.True(JsonNode.DeepEquals(context.Database, before));
                var condition = pair.Condition == "C1" ? ResearchConstraintCondition.ModuleLocal : ResearchConstraintCondition.CrossModule;
                var selectedIntent = live.First(c => c.Definition.CaseId == pair.Definition.Operations.ReceiptCaseId).Context.Source["intentId"]!.GetValue<string>();
                var result = await RunManifestSuffixAsync(pair.Definition, context.Source, selectedIntent, import, registry,
                    context.Host, context.Gateway, context.InitialWrite, context.InitialRead, condition, phase => journal.Add(key, phase), ct);
                var after = await DatabaseIdentityAsync(context.Host);
                journal.Add(key, "database.completed", after);
                Assert.True(JsonNode.DeepEquals(context.Database, after));
                result["databaseBefore"] = context.Database.DeepClone(); result["databaseAfter"] = after.DeepClone();
                results.Add(result); journal.Add(key, "case.complete", result);
                await WriteFlowAsync(Path.Combine(directory, "cases.json"), results, ct);
            }
            Assert.Equal(manifest.Cases.Count * 2, results.Count);
            Assert.Equal(0, live.Sum(c => c.Context.Gateway.Attempts));
            journal.Add("batch", "batch.observations_complete");
        }
        finally
        {
            foreach (var item in live)
            {
                await item.Context.Host.DisposeAsync(); item.Context.Gateway.Dispose();
                journal.Add(PairKey(item.Context.Id, item.Condition), "database.disposed", item.Context.Database);
            }
        }
    }

    private static async Task<(JsonObject Write, JsonObject Read, ResearchRetrievedRoute Route)> RetrieveManifestRouteAsync(
        ServerTestHost host, ResearchLiveCase definition, ResearchProgram candidate, ResearchProgram[] catalogue,
        string session, FlowJournal journal, string key)
    {
        var request = ResearchLoopAdapter.Perception("route-" + definition.CaseId, session, Cue(definition.CaseId, candidate, definition.RequestedAct));
        journal.Add(key, "memory.write.begin");
        var (status, response) = await host.PostAsync("/api/v1/v9/perception", request);
        var write = new JsonObject { ["request"] = request, ["status"] = status, ["response"] = response };
        journal.Add(key, "memory.write.end", write);
        Assert.Equal(201, status);
        var path = "/api/v1/memory/items/?q=" + Uri.EscapeDataString(ResearchRetrievedRoute.Prefix(definition.CaseId).TrimEnd()) + "&limit=6";
        journal.Add(key, "memory.read.begin");
        var (readStatus, body) = await host.SendAsync(HttpMethod.Get, path);
        var read = new JsonObject { ["path"] = path, ["status"] = readStatus, ["response"] = body };
        journal.Add(key, "memory.read.end", read);
        Assert.Equal(200, readStatus);
        var item = Assert.Single(body!["items"]!.AsArray())!;
        var route = ResearchRetrievedRoute.Select(item["content"]!.GetValue<string>(), definition.CaseId, catalogue);
        journal.Add(key, "route.selected", JsonSerializer.SerializeToNode(route, Json));
        return (write, read, route);
    }

    private static async Task<JsonObject> RunManifestSuffixAsync(ResearchLiveCase definition, JsonObject source, string selectedIntent,
        ReceiptImportPlan import, IntentRegistry registry, ServerTestHost host, NoGateway gateway,
        JsonObject initialWrite, JsonObject initialRead, ResearchConstraintCondition condition, Action<string> phase, CancellationToken ct)
    {
        var id = definition.CaseId; var op = definition.Operations;
        var adapter = new ResearchLoopAdapter(host, condition);
        phase("import.begin");
        var posts = new JsonArray();
        await RenderReceiptImporter.ImportAsync(import, async envelope =>
        {
            var (status, response) = await host.PostAsync("/api/v1/v9/events", envelope);
            posts.Add(new JsonObject { ["request"] = envelope.DeepClone(), ["status"] = status, ["response"] = response });
            return status;
        });
        phase("import.end");
        var receipt = import.Receipts.Single(r => r.IntentId == selectedIntent);
        var code = source["code"]!.GetValue<string>();
        var task = Bench.Tasks.Single(t => t.Id == source["taskId"]!.GetValue<string>());
        var execution = source["execution"]?.Deserialize<ExecutionVerdict>(Json);
        var evidence = new SkillEvidence("skill-" + id, SkillEvidence.HashCode(code), task.Id, Bench.ManifestSha256,
            source["executionId"]!.GetValue<string>(), source["intentId"]!.GetValue<string>(), registry.SessionId,
            op.AssetVersionOverride ?? receipt.AssetVersionHash, receipt.IntentId, receipt.AssetVersionHash,
            SkillEvidence.AppliedStage, op.ClaimedStage, execution?.Ok, execution?.Passed ?? 0,
            execution?.Total ?? task.Tests.Count, source["archivedSelfVerdict"]!.GetValue<string>());
        var proposalId = "proposal-" + id;
        var parameters = new JsonObject { ["emotion.preset"] = source["dispatchedAct"]!.GetValue<string>() };
        var proposal = new ShadowParamsProposal(proposalId, registry.SessionId,
            ShadowParams.ComputeLearningInputHash(registry.SessionId, proposalId, parameters), ShadowParamsAnchorKind.ShadowParams, true,
            parameters, 0.9, receipt.RenderRef, receipt.AppliedParamsHash, evidence.AssetVersion);
        var payload = new JsonObject
        {
            ["session_id"] = registry.SessionId, ["render_ref"] = receipt.RenderRef,
            ["applied_params_hash"] = receipt.AppliedParamsHash, ["asset_version_hash"] = evidence.AssetVersion,
            ["proposal_id"] = proposalId, ["input_hash"] = proposal.InputHash, ["candidate_params"] = parameters.DeepClone(), ["confidence"] = 0.9,
        };
        var envelope = Envelope("evt-" + proposalId, registry.SessionId, payload);
        phase("admission.begin");
        var (admissionStatus, admissionBody) = await host.PostAsync("/api/v1/v9/events", envelope);
        string? diagnosticReason = null; long? diagnosticCount = null;
        if (admissionStatus == 400)
        {
            try { await host.App.Services.GetRequiredService<V9EventService>().AppendEventAsync(V9EventInput.FromEnvelope(envelope, payload), ct); }
            catch (RenderTraceContractException ex) { diagnosticReason = WireName.Of(ex.Reason); }
            diagnosticCount = await host.CountAsync("SELECT count(*) FROM events WHERE event_id=$1", "evt-" + proposalId);
        }
        phase("admission.end");
        if (op.FailStateWrite)
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
        ResearchLoopAdapter.CommitResult? commit = null; ResearchLoopAdapter.CommitResult? duplicate = null;
        string? databaseError = null;
        phase("commit.begin");
        try
        {
            commit = await adapter.CommitAsync(outcomeId, evidence, proposal, "evt-" + proposalId, ct);
            if (op.RepeatOutcome) duplicate = await adapter.CommitAsync(outcomeId, evidence, proposal, "evt-" + proposalId, ct);
        }
        catch (PostgresException ex) when (op.FailStateWrite && ex.SqlState == "P0001") { databaseError = ex.SqlState; }
        phase("commit.end");
        var beforeDelivery = await adapter.SnapshotAsync();
        phase("delivery.begin");
        var delivery = await adapter.DeliverAsync(outcomeId);
        var duplicateDelivery = op.RepeatOutcome ? await adapter.DeliverAsync(outcomeId) : null;
        phase("delivery.end");
        if (op.RevokeBeforeReuse)
        {
            phase("revoke.begin"); await adapter.RevokeAsync(evidence.SkillId, ct); phase("revoke.end");
        }
        phase("round2.begin");
        var round2 = await adapter.Round2Async(outcomeId, evidence.SkillId, code, task, ct);
        var duplicateReuse = op.RepeatOutcome ? await adapter.Round2Async(outcomeId, evidence.SkillId, code, task, ct) : null;
        phase("round2.end");
        var final = await adapter.SnapshotAsync();
        return new JsonObject
        {
            ["caseId"] = id, ["condition"] = condition == ResearchConstraintCondition.ModuleLocal ? "C1" : "C2",
            ["policyVersion"] = condition == ResearchConstraintCondition.ModuleLocal ? "strong-local-v1" : "cross-module-v1",
            ["batch"] = "live_manifest_known_development", ["dataOrigin"] = "fresh_known_scenario_execution",
            ["runtimeInput"] = JsonSerializer.SerializeToNode(definition, ResearchLiveManifest.Options), ["sharedRenderedIntent"] = true,
            ["gatewayAttempts"] = gateway.Attempts, ["initialWrite"] = initialWrite.DeepClone(), ["initialRead"] = initialRead.DeepClone(),
            ["prepared"] = source.DeepClone(), ["importPosts"] = posts, ["selectedReceipt"] = JsonSerializer.SerializeToNode(receipt, Json),
            ["evidence"] = JsonSerializer.SerializeToNode(evidence, Json), ["proposal"] = proposal.ToJson(),
            ["admission"] = new JsonObject { ["request"] = envelope, ["status"] = admissionStatus, ["response"] = admissionBody,
                ["diagnosticDirectAppendAttempts"] = admissionStatus == 400 ? 1 : 0, ["diagnosticCoreReason"] = diagnosticReason, ["diagnosticEventCount"] = diagnosticCount },
            ["commit"] = JsonSerializer.SerializeToNode(commit, Json), ["duplicateCommit"] = JsonSerializer.SerializeToNode(duplicate, Json),
            ["promotionAttempts"] = new JsonArray(adapter.PromotionAttempts.Select(p => (JsonNode)p.DeepClone()).ToArray()),
            ["databaseErrorCode"] = databaseError, ["beforeDelivery"] = beforeDelivery, ["delivery"] = delivery, ["duplicateDelivery"] = duplicateDelivery,
            ["round2"] = round2, ["duplicateReuse"] = duplicateReuse, ["final"] = final,
        };
    }
}
