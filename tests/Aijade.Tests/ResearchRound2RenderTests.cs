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

    [Fact]
    public async Task Run_known_development_persisted_act_second_render()
    {
        if (Env("AIJADE_CH7_ROUND2_RENDER_OUTPUT") is not { } directory)
        {
            Assert.Skip("Second-round persisted-act development measurement is opt-in; no held-out execution");
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
            await RunPersistedActRenderAsync(live, results, directory, session, ct);
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


    private static async Task RunPersistedActRenderAsync(List<ManifestPair> live, JsonArray baseRows,
        string directory, string session, CancellationToken ct)
    {
        var second = Path.Combine(directory, "round2");
        Directory.CreateDirectory(second);
        var journal = new FlowJournal(Path.Combine(second, "journal.jsonl"));
        var observations = new JsonArray();
        journal.Add("batch", "round2.begin");
        foreach (var pair in live)
        {
            var key = PairKey(pair.Context.Id, pair.Condition);
            var row = baseRows.Single(n => n!["caseId"]!.GetValue<string>() == pair.Context.Id &&
                n["condition"]!.GetValue<string>() == pair.Condition)!;
            journal.Add(key, "selection.begin");
            var database = await DatabaseIdentityAsync(pair.Context.Host);
            Assert.True(JsonNode.DeepEquals(database, pair.Context.Database));
            var authorityText = await pair.Context.Host.ScalarAsync(
                "SELECT body::text FROM research_skill_authority WHERE skill_id=$1", "skill-" + pair.Context.Id);
            var authority = authorityText is null ? null : JsonNode.Parse(authorityText);
            var observation = new JsonObject
            {
                ["caseId"] = pair.Context.Id, ["condition"] = pair.Condition,
                ["baseRound2"] = row["round2"]!.DeepClone(),
                ["databaseBefore"] = database.DeepClone(),
                ["authorityAfterReuse"] = authority?.DeepClone(),
                ["requestedActReference"] = pair.Definition.RequestedAct,
                ["dispatched"] = false, ["receipt"] = null, ["importPosts"] = new JsonArray(),
            };
            if (row["round2"]!["executed"]!.GetValue<bool>() != true)
            {
                observation["disposition"] = "reuse_refused";
                observation["reason"] = row["round2"]!["reason"]!.DeepClone();
            }
            else if (!JsonNode.DeepEquals(authority, row["round2"]!["authority"]))
            {
                observation["disposition"] = "configuration_unavailable";
                observation["reason"] = "authority_changed_after_reuse";
            }
            else
            {
                var specId = authority?["specId"]?.GetValue<string>();
                var text = specId is null ? null : await pair.Context.Host.ScalarAsync(
                    "SELECT spec::text FROM evolution_specs WHERE id=$1", specId);
                observation["specId"] = specId;
                observation["specText"] = text;
                observation["specTextSha256"] = text is null ? null : SkillEvidence.HashCode(text);
                var spec = text is null ? null : JsonNode.Parse(text);
                observation["specification"] = spec?.DeepClone();
                try
                {
                    if (spec is null) throw new InvalidDataException("persisted_spec_absent");
                    var act = ResearchPersistedAct.Read(spec);
                    var verdict = row["round2"]!["execution"]!.Deserialize<ExecutionVerdict>(Json)!;
                    var intent = ResearchIntentMapper.Map(act, "round2_" + session + "_" + pair.Context.Id + "_" + pair.Condition,
                        "persona:ch7", verdict.Ok);
                    observation["persistedAct"] = WireName.Of(act);
                    observation["mappedAct"] = WireName.Of(verdict.Ok ? act : DialogueAct.Inform);
                    observation["mappedIntent"] = JsonSerializer.SerializeToNode(intent, Json);
                    observation["disposition"] = "prepared";
                }
                catch (InvalidDataException ex)
                {
                    observation["disposition"] = "configuration_unavailable";
                    observation["reason"] = ex.Message;
                }
            }
            observations.Add(observation);
            journal.Add(key, "selection.end", observation);
        }
        var preparedPath = Path.Combine(second, "actions-prepared.json");
        await WriteFlowAsync(preparedPath, observations, ct);
        await WriteFlowAsync(Path.Combine(second, "renderer-request.tmp"), new JsonObject
        {
            ["session"] = session + "-round2",
            ["preparedSha256"] = SkillEvidence.HashCode(await File.ReadAllTextAsync(preparedPath, ct)),
        }, ct);
        journal.Add("batch", "selections.complete");
        File.Move(Path.Combine(second, "renderer-request.tmp"), Path.Combine(second, "renderer-request.json"));
        var ready = await WaitFlowAsync(Path.Combine(second, "renderer-ready.json"), ct);
        journal.Add("batch", "renderer.ready", ready);
        var registryPath = Path.Combine(second, "registry.jsonl");
        IntentRegistry.Create(registryPath, session + "-round2", ready["context"]!.GetValue<string>());
        using (var link = new MosaicRendererLink(ready["port"]!.GetValue<int>(), session + "-round2"))
        {
            foreach (var item in observations.OfType<JsonObject>().Where(o => o["disposition"]!.GetValue<string>() == "prepared"))
            {
                var key = PairKey(item["caseId"]!.GetValue<string>(), item["condition"]!.GetValue<string>());
                var intent = item["mappedIntent"]!.Deserialize<Aijade.Memory.Contracts.PerformanceIntent>(Json)!;
                var registered = new RegisteredIntent(intent.Id, intent.PersonaSnapshotRef, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
                IntentRegistry.Append(registryPath, registered);
                journal.Add(key, "intent.registered", JsonSerializer.SerializeToNode(registered, Json));
                var packets = await link.SendAsync(intent, ct: ct);
                item["registered"] = JsonSerializer.SerializeToNode(registered, Json);
                item["packets"] = new JsonArray(packets.Select(p => (JsonNode)p.DeepClone()).ToArray());
                item["dispatched"] = true;
                journal.Add(key, "intent.sent", item);
                await Task.Delay(1000, ct);
            }
        }
        await WriteFlowAsync(Path.Combine(second, "actions-dispatched.json"), observations, ct);
        var closed = await WaitFlowAsync(Path.Combine(second, "renderer-closed.json"), ct);
        journal.Add("batch", "renderer.closed", closed);
        Assert.Equal(0, closed["exitCode"]!.GetValue<int>());
        var statePath = Path.Combine(second, "client", "aijade-render-state.jsonl");
        Assert.Equal(closed["stateSha256"]!.GetValue<string>(),
            Convert.ToHexStringLower(SHA256.HashData(await File.ReadAllBytesAsync(statePath, ct))));
        var registry = IntentRegistry.Read(registryPath);
        var manifest = RenderSessionManifest.Seal(registry, statePath);
        await File.WriteAllTextAsync(Path.Combine(second, "manifest.json"), manifest.ToJson() + "\n", ct);
        var import = RenderReceiptImporter.Plan(manifest, registry, RenderStateFile.Read(statePath));
        await WriteFlowAsync(Path.Combine(second, "receipt-dispositions.json"), new JsonObject
        {
            ["fileReasons"] = JsonSerializer.SerializeToNode(import.FileReasons, Json),
            ["refusedRows"] = new JsonArray(import.RefusedRows.Select(p => (JsonNode)new JsonObject {
                ["sequence"] = p.Seq, ["reason"] = p.Reason }).ToArray()),
            ["unknown"] = new JsonArray(import.Unknown.Select(p => (JsonNode)new JsonObject {
                ["intentId"] = p.IntentId, ["reason"] = p.Reason }).ToArray()),
        }, ct);
        foreach (var item in observations.OfType<JsonObject>())
        {
            var key = PairKey(item["caseId"]!.GetValue<string>(), item["condition"]!.GetValue<string>());
            var context = live.Single(p => PairKey(p.Context.Id, p.Condition) == key).Context;
            if (item["dispatched"]!.GetValue<bool>())
            {
                var intentId = item["mappedIntent"]!["id"]!.GetValue<string>();
                var receipt = import.Receipts.SingleOrDefault(r => r.IntentId == intentId);
                item["receipt"] = JsonSerializer.SerializeToNode(receipt, Json);
                item["disposition"] = receipt is null ? "render_unknown" : "applied_known";
                if (receipt is not null)
                {
                    var posts = item["importPosts"]!.AsArray();
                    foreach (var envelope in new[] { receipt.Request, receipt.Receipt })
                    {
                        var (status, response) = await context.Host.PostAsync("/api/v1/v9/events", envelope);
                        posts.Add(new JsonObject { ["request"] = envelope.DeepClone(), ["status"] = status, ["response"] = response });
                    }
                }
            }
            var after = await DatabaseIdentityAsync(context.Host);
            Assert.True(JsonNode.DeepEquals(context.Database, after));
            item["databaseAfter"] = after;
            item["snapshotAfterRender"] = await new ResearchLoopAdapter(context.Host).SnapshotAsync();
            journal.Add(key, "case.complete", item);
        }
        await WriteFlowAsync(Path.Combine(second, "actions.json"), observations, ct);
        journal.Add("batch", "round2.observations_complete");
    }
}
