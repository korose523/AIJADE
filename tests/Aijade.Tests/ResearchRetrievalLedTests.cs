using System.Diagnostics;
using System.Globalization;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Integrations.Renderer;
using Aijade.Memory.Contracts;
using Aijade.Memory.Development;
using Aijade.Research.Integration;
using Aijade.Research.SkillBench;
using Aijade.Server.Product;

using Microsoft.Extensions.DependencyInjection;

namespace Aijade.Tests;

public partial class ResearchLoopQualificationTests
{
    private static readonly string[] CatalogueKeys = ["usable", "unusable"];
    private sealed class FlowJournal(string path)
    {
        private int sequence;

        public void Add(string caseId, string phase, JsonNode? detail = null)
        {
            var row = new JsonObject
            {
                ["sequence"] = ++sequence, ["caseId"] = caseId, ["phase"] = phase,
                ["utc"] = DateTimeOffset.UtcNow.ToString("O", CultureInfo.InvariantCulture),
                ["monotonicTicks"] = Stopwatch.GetTimestamp(), ["frequency"] = Stopwatch.Frequency,
                ["detail"] = detail?.DeepClone(),
            };
            File.AppendAllText(path, row.ToJsonString(Json) + "\n");
        }
    }

    private sealed record LiveCase(string Id, ServerTestHost Host, NoGateway Gateway, JsonObject Source,
        JsonObject InitialWrite, JsonObject InitialRead, JsonObject Database);

    private static JsonObject Selection()
    {
        if (Env("AIJADE_CH7_INPUT") is { } path)
            return JsonNode.Parse(File.ReadAllText(path))!.AsObject();
        var root = new DirectoryInfo(AppContext.BaseDirectory);
        while (root is not null && !File.Exists(Path.Combine(root.FullName, "AIJADE.sln")) && !Directory.Exists(Path.Combine(root.FullName, ".git")) && !File.Exists(Path.Combine(root.FullName, ".git")))
            root = root.Parent;
        return JsonNode.Parse(File.ReadAllText(Path.Combine(root?.FullName ?? throw new InvalidOperationException("Repository not found"),
            "experiments/ch7/2026-11-12/selection.json")))!.AsObject();
    }

    private static ResearchProgram[] Catalogue(JsonObject selection) => CatalogueKeys.Select(key => new ResearchProgram(
        selection[key]!["taskId"]!.GetValue<string>(), selection[key]!["codeSha256"]!.GetValue<string>(), selection[key]!["code"]!.GetValue<string>())).ToArray();

    private static string Cue(string id, ResearchProgram program, string act) => ResearchRetrievedRoute.Prefix(id) + new JsonObject
    {
        ["caseId"] = id, ["taskId"] = program.TaskId, ["codeSha256"] = program.CodeSha256, ["requestedAct"] = act,
    }.ToJsonString(Json);

    private static async Task<(JsonObject Write, JsonObject Read, ResearchRetrievedRoute Route)> RetrieveRouteAsync(
        ServerTestHost host, string id, string eventId, string session, string content, ResearchProgram[] catalogue,
        FlowJournal? journal = null)
    {
        journal?.Add(id, "memory.write.begin");
        var request = ResearchLoopAdapter.Perception(eventId, session, content);
        var (status, response) = await host.PostAsync("/api/v1/v9/perception", request);
        var write = new JsonObject { ["request"] = request, ["status"] = status, ["response"] = response };
        journal?.Add(id, "memory.write.end", write);
        Assert.Equal(201, status);
        var path = "/api/v1/memory/items/?q=" + Uri.EscapeDataString(ResearchRetrievedRoute.Prefix(id).TrimEnd()) + "&limit=6";
        journal?.Add(id, "memory.read.begin");
        var (readStatus, body) = await host.SendAsync(HttpMethod.Get, path);
        var read = new JsonObject { ["path"] = path, ["status"] = readStatus, ["response"] = body };
        journal?.Add(id, "memory.read.end", read);
        Assert.Equal(200, readStatus);
        var item = Assert.Single(body!["items"]!.AsArray())!;
        var route = ResearchRetrievedRoute.Select(item["content"]!.GetValue<string>(), id, catalogue);
        journal?.Add(id, "route.selected", JsonSerializer.SerializeToNode(route, Json));
        return (write, read, route);
    }

    [Fact]
    public async Task Retrieved_content_changes_selected_program_and_act_on_the_actual_memory_API()
    {
        var catalogue = Catalogue(Selection());
        using var gateway = new NoGateway();
        await using var host = await ServerTestHost.StartAsync(worker: false, services: services =>
            services.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => gateway));
        var rows = new JsonArray();
        string? oldId = null;
        var conditions = new[] { (catalogue[0], "comfort"), (catalogue[0], "celebrate"), (catalogue[1], "comfort") };
        for (var i = 0; i < conditions.Length; i++)
        {
            JsonObject? deletion = null;
            if (oldId is not null)
            {
                var path = "/api/v1/memory/items/" + Uri.EscapeDataString(oldId);
                var (status, response) = await host.SendAsync(HttpMethod.Delete, path);
                deletion = new JsonObject { ["path"] = path, ["status"] = status, ["response"] = response };
                Assert.Equal(200, status);
            }
            var (write, read, route) = await RetrieveRouteAsync(host, "control", "route-control-" + i, "ch7-route-control",
                Cue("control", conditions[i].Item1, conditions[i].Item2), catalogue);
            oldId = read["response"]!["items"]![0]!["id"]!.GetValue<string>();
            var execution = new Sandbox { IsolateArguments = true }.RunTask(route.Program.Code, Bench.Tasks.Single(t => t.Id == route.Program.TaskId));
            var intent = ResearchIntentMapper.Map(route.RequestedAct, "pi_control_" + i, "persona:ch7", execution.Ok);
            Assert.Equal(i != 2, execution.Ok);
            Assert.Equal(conditions[i].Item1, route.Program);
            Assert.Equal(conditions[i].Item2, WireName.Of(route.RequestedAct));
            rows.Add(new JsonObject
            {
                ["condition"] = i, ["deletePrevious"] = deletion, ["write"] = write, ["read"] = read,
                ["route"] = JsonSerializer.SerializeToNode(route, Json), ["execution"] = JsonSerializer.SerializeToNode(execution, Json),
                ["intent"] = JsonSerializer.SerializeToNode(intent, Json),
                ["mappedAct"] = WireName.Of(execution.Ok ? route.RequestedAct : DialogueAct.Inform), ["gatewayAttempts"] = gateway.Attempts,
            });
        }
        Assert.Equal(0, gateway.Attempts);
        if (Env("AIJADE_CH7_ROUTE_CONTROL") is { } output)
            await File.WriteAllTextAsync(output, rows.ToJsonString(new JsonSerializerOptions(Json) { WriteIndented = true }) + "\n", TestContext.Current.CancellationToken);
    }

    [Fact]
    public void Retrieved_route_refuses_malformed_or_unbound_content()
    {
        var catalogue = Catalogue(Selection());
        var valid = Cue("control", catalogue[0], "comfort");
        foreach (var content in new[]
        {
            "ch7_route_control {", "ch7_route_control []", Cue("other", catalogue[0], "comfort"),
            "ch7_route_control {}", "ch7_route_control {\"caseId\":5}",
            valid.Replace("\"caseId\":\"control\"", "\"caseId\":\"other\"", StringComparison.Ordinal),
            Cue("control", catalogue[0], "unsupported"), Cue("control", catalogue[0] with { CodeSha256 = new string('0', 64) }, "comfort"),
        })
            Assert.Throws<InvalidDataException>(() => ResearchRetrievedRoute.Select(content, "control", catalogue));
        Assert.Throws<InvalidDataException>(() => ResearchRetrievedRoute.Select(valid, "control", [catalogue[0] with { Code = "different" }]));
    }

    private static async Task<JsonObject> DatabaseIdentityAsync(ServerTestHost host) => new()
    {
        ["database"] = await host.ScalarAsync("SELECT current_database()"),
        ["token"] = await host.ScalarAsync("SELECT token FROM research_flow_identity"),
    };

    private static Task WriteFlowAsync(string path, JsonNode body, CancellationToken ct) =>
        File.WriteAllTextAsync(path, body.ToJsonString(new JsonSerializerOptions(Json) { WriteIndented = true }) + "\n", ct);

    private static async Task<JsonObject> WaitFlowAsync(string path, CancellationToken ct)
    {
        while (!File.Exists(path))
            await Task.Delay(200, ct);
        return JsonNode.Parse(await File.ReadAllTextAsync(path, ct))!.AsObject();
    }

    [Fact]
    public async Task Qualify_retrieval_led_execution_rendering_and_same_database_writeback()
    {
        if (Env("AIJADE_CH7_FLOW") is not { } directory)
        {
            Assert.Skip("AIJADE_CH7_FLOW is not set (live retrieval-led development measurement is opt-in)");
            return;
        }
        var ct = TestContext.Current.CancellationToken;
        var selection = Selection();
        var catalogue = Catalogue(selection);
        var session = Required("AIJADE_CH7_SESSION");
        var journal = new FlowJournal(Path.Combine(directory, "journal.jsonl"));
        var live = new List<LiveCase>();
        var prepared = new JsonArray();
        var results = new JsonArray();
        journal.Add("batch", "batch.begin");
        try
        {
            foreach (var id in CaseIds)
            {
                var gateway = new NoGateway();
                var host = await ServerTestHost.StartAsync(worker: false, services: services =>
                    services.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => gateway));
                var database = new JsonObject { ["database"] = await host.ScalarAsync("SELECT current_database()") };
                File.AppendAllText(Path.Combine(directory, "database-leases.jsonl"), database.ToJsonString(Json) + "\n");
                // Register ownership immediately, before further operations that may throw.
                var context = new LiveCase(id, host, gateway, new JsonObject(), new JsonObject(), new JsonObject(), database);
                live.Add(context);
                await ResearchLoopAdapter.InitializeAsync(host);
                await host.ExecAsync("CREATE TABLE research_flow_identity(token text PRIMARY KEY); INSERT INTO research_flow_identity VALUES($1)", Guid.NewGuid().ToString("N"));
                database = await DatabaseIdentityAsync(host);
                journal.Add(id, "database.open", database);
                var chosen = id == "I5" ? catalogue[1] : catalogue[0];
                var (write, read, route) = await RetrieveRouteAsync(host, id, "route-" + id, session, Cue(id, chosen, "comfort"), catalogue, journal);
                var task = Bench.Tasks.Single(t => t.Id == route.Program.TaskId);
                journal.Add(id, "execution.begin");
                var execution = id == "I4" ? null : new Sandbox { IsolateArguments = true }.RunTask(route.Program.Code, task);
                journal.Add(id, "execution.end", JsonSerializer.SerializeToNode(execution, Json));
                var act = id == "S1" ? DialogueAct.Celebrate : route.RequestedAct;
                var intentId = "pi_" + session + "_" + id;
                var intent = ResearchIntentMapper.Map(act, intentId, "persona:ch7", execution?.Ok);
                var source = new JsonObject
                {
                    ["caseId"] = id, ["taskId"] = task.Id, ["code"] = route.Program.Code, ["codeSha256"] = route.Program.CodeSha256,
                    ["route"] = JsonSerializer.SerializeToNode(route, Json), ["routeVersion"] = ResearchRetrievedRoute.Version,
                    ["benchSha256"] = Bench.ManifestSha256, ["executionId"] = "execution-" + session + "-" + id,
                    ["execution"] = JsonSerializer.SerializeToNode(execution, Json), ["intentId"] = intentId,
                    ["mappedIntent"] = JsonSerializer.SerializeToNode(intent, Json), ["mapperVersion"] = ResearchIntentMapper.Version,
                    ["requestedAct"] = WireName.Of(route.RequestedAct), ["mapperInputAct"] = WireName.Of(act),
                    ["dispatchedAct"] = WireName.Of(execution?.Ok == true ? act : DialogueAct.Inform), ["databaseBefore"] = database.DeepClone(),
                };
                journal.Add(id, "intent.mapped", source);
                live[^1] = new LiveCase(id, host, gateway, source, write, read, database);
                prepared.Add(source.DeepClone());
                await WriteFlowAsync(Path.Combine(directory, "prepared.json"), prepared, ct);
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
                foreach (var item in live)
                {
                    var intent = ResearchIntentMapper.Map(Enum.Parse<DialogueAct>(item.Source["mapperInputAct"]!.GetValue<string>(), true),
                        item.Source["intentId"]!.GetValue<string>(), "persona:ch7", item.Source["execution"]?["ok"]?.GetValue<bool>());
                    var registered = new RegisteredIntent(intent.Id, intent.PersonaSnapshotRef, DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
                    IntentRegistry.Append(registryPath, registered);
                    journal.Add(item.Id, "intent.registered", JsonSerializer.SerializeToNode(registered, Json));
                    var packets = await link.SendAsync(intent, ct: ct);
                    item.Source["registered"] = JsonSerializer.SerializeToNode(registered, Json);
                    item.Source["packets"] = new JsonArray(packets.Select(p => (JsonNode)p.DeepClone()).ToArray());
                    journal.Add(item.Id, "intent.sent", item.Source);
                    await Task.Delay(1000, ct);
                }
                Assert.Equal(20, link.Sent);
            }
            await WriteFlowAsync(Path.Combine(directory, "prepared-dispatched.json"), new JsonArray(live.Select(x => (JsonNode)x.Source.DeepClone()).ToArray()), ct);
            var closed = await WaitFlowAsync(Path.Combine(directory, "renderer-closed.json"), ct);
            journal.Add("batch", "renderer.closed", closed);
            Assert.Equal(0, closed["exitCode"]!.GetValue<int>());
            var statePath = Path.Combine(directory, "client", "aijade-render-state.jsonl");
            Assert.Equal(closed["stateSha256"]!.GetValue<string>(), Convert.ToHexStringLower(SHA256.HashData(await File.ReadAllBytesAsync(statePath, ct))));
            var registry = IntentRegistry.Read(registryPath);
            var manifest = RenderSessionManifest.Seal(registry, statePath);
            await File.WriteAllTextAsync(Path.Combine(directory, "manifest.json"), manifest.ToJson() + "\n", ct);
            var import = RenderReceiptImporter.Plan(manifest, registry, RenderStateFile.Read(statePath));
            Assert.Empty(import.FileReasons);
            Assert.Empty(import.Unknown);
            Assert.Equal(CaseIds.Length, import.Receipts.Count);
            foreach (var item in live)
            {
                var database = await DatabaseIdentityAsync(item.Host);
                journal.Add(item.Id, "database.resumed", database);
                Assert.Equal(item.Database.ToJsonString(), database.ToJsonString());
                var result = await RunCaseOnHostAsync(item.Id, item.Source, import, registry, item.Host, item.Gateway,
                    item.InitialWrite, item.InitialRead, ct, phase => journal.Add(item.Id, phase));
                result["databaseBefore"] = item.Database.DeepClone();
                result["databaseAfter"] = database.DeepClone();
                results.Add(result);
                journal.Add(item.Id, "case.complete", result);
                await WriteFlowAsync(Path.Combine(directory, "cases.json"), results, ct);
            }
            Assert.All(results, r => Assert.True(r!["qualified"]!.GetValue<bool>(), r.ToJsonString()));
            journal.Add("batch", "batch.qualified");
        }
        finally
        {
            foreach (var item in live)
            {
                await item.Host.DisposeAsync();
                item.Gateway.Dispose();
                journal.Add(item.Id, "database.disposed", item.Database);
            }
        }
    }
}
