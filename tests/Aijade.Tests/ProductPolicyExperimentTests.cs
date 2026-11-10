using System.Diagnostics;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Chat;
using Aijade.Memory.Locomo;
using Aijade.Research.MemoryEval;
using Aijade.Server.Memory;
using Aijade.Server.Product;

using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;

using Npgsql;

namespace Aijade.Tests;

/// <summary>Opt-in complete configured policy design; never changes production defaults.</summary>
public sealed class ProductPolicyExperimentTests
{
    private static readonly JsonSerializerOptions ReceiptOptions = new() { WriteIndented = true };
    private static readonly (int Limit, bool Newest, string Name)[] Policies =
        [(6, true, "6-newest"), (6, false, "6-server"), (60, true, "60-newest"), (60, false, "60-server")];
    private sealed record Stored(string Id, string Content, DateTime CreatedAt, float[]? Vector);

    [Fact]
    public async Task All_configured_policies_deliver_captured_prompts()
    {
        var ct = TestContext.Current.CancellationToken;
        if (Environment.GetEnvironmentVariable("AIJADE_P3_POLICY_OUT") is not { Length: > 0 } folder
            || Environment.GetEnvironmentVariable("AIJADE_P3_POLICY_MODE") is not { Length: > 0 } mode)
        {
            Assert.Skip("set AIJADE_P3_POLICY_OUT and AIJADE_P3_POLICY_MODE for full configured policy execution");
            return;
        }
        Assert.True(mode is "text" or "embedding");
        var corpusPath = Environment.GetEnvironmentVariable("AIJADE_P3E_CORPUS")!;
        var prior = Environment.GetEnvironmentVariable("AIJADE_P3_POLICY_PRIOR")!;
        var plan = Environment.GetEnvironmentVariable("AIJADE_P3_POLICY_PLAN")!;
        Assert.Equal(40, plan.Length);
        Assert.Equal(LocomoCorpus.Sha256, LocomoCorpus.FileSha256(corpusPath));
        Directory.CreateDirectory(folder);
        var embeddingFolder = Path.Combine(prior, "embedding");
        var replay = await PolicyVectorReplay.LoadAsync(Path.Combine(embeddingFolder, "embeddings-shared-memory-only-embedding.jsonl.gz"), ct);
        await using var oldFile = File.OpenRead(Path.Combine(prior, mode, $"product-path-v2-shared-memory-only-{mode}.json.gz"));
        await using var oldZip = new GZipStream(oldFile, CompressionMode.Decompress);
        var old = (await JsonNode.ParseAsync(oldZip, cancellationToken: ct))!["rows"]!.AsArray()
            .ToDictionary(r => (r!["c"]!.GetValue<int>(), r["q"]!.GetValue<int>()), r => r!);
        var corpus = LocomoCorpus.Load(corpusPath);
        var budget = new PromptBudget();
        var clock = Stopwatch.StartNew();
        var rows = 0;
        var baselines = 0;
        var writes = 0;
        var unknown = 0;
        await using var output = new FileStream(Path.Combine(folder, $"product-{mode}.jsonl.gz"), FileMode.CreateNew);
        await using var compressed = new GZipStream(output, CompressionLevel.SmallestSize);
        await using var journal = new StreamWriter(compressed);
        for (var c = 0; c < corpus.Count; c++)
        {
            var conv = corpus[c];
            await using var host = await ServerTestHost.StartAsync(worker: false, services: services =>
                services.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(replay.NewHandler));
            if (mode == "embedding")
            {
                var route = new JsonObject { ["embeddings"] = new JsonObject { ["upstream"] = "http://127.0.0.1:1/v1", ["model"] = "nomic-embed-text", ["keys"] = new JsonArray("local-replay") } };
                Assert.Equal(200, (await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", route, ServerTestHost.AdminToken)).Status);
            }
            foreach (var turn in conv.Episodes.Where(t => !string.IsNullOrWhiteSpace(t.Content)))
            {
                var id = EventId(c, turn.Id);
                var (status, _) = await host.PostAsync("/api/v1/v9/perception", new JsonObject
                {
                    ["event_id"] = id, ["session_id"] = $"locomo-{c}", ["trace_id"] = $"t-{id}", ["correlation_id"] = $"t-{id}", ["timestamp"] = turn.CreatedAt,
                    ["origin_device"] = "p3-policy", ["privacy_level"] = 1, ["risk_score"] = 0.1, ["source"] = "chat", ["content"] = turn.Content,
                });
                Assert.InRange(status, 200, 299);
                writes++;
            }
            using var tap = new PolicyTap(host.App.GetTestServer().CreateHandler());
            using var http = new HttpClient(tap) { BaseAddress = host.Client.BaseAddress, Timeout = TimeSpan.FromHours(1) };
            var tokens = new MemoryTokenStore();
            await tokens.SetAsync(ServerTestHost.Token);
            var api = new AijadeApi(http, tokens);
            var runtimes = Policies.ToDictionary(p => p.Name, p => CompanionRuntime.Create(api,
                [new("memory", p.Name == "6-newest" ? new MemoryRecallProvider(api, () => true) : new PolicyMemoryContext(api, p.Limit, p.Newest))],
                new OrchestratorOptions { PromptBudget = budget }), StringComparer.Ordinal);
            var chat = await api.CreateChatAsync(null, $"p3-policy {mode} {c}", ct);
            List<Stored>? store = null;
            var rankedCache = new Dictionary<string, (List<string> Pool, List<string> Above)>(StringComparer.Ordinal);
            for (var q = 0; q < conv.Qa.Count; q++)
            {
                var question = conv.Qa[q];
                for (var position = 0; position < Policies.Length; position++)
                {
                    var policy = Policies[(c + q + position) % Policies.Length];
                    tap.Reset();
                    var completed = false;
                    await foreach (var item in runtimes[policy.Name].SendAsync(chat.Id, null, [], question.Question, "p3-policy", ct))
                        completed |= item is TurnCompleted;
                    Assert.True(completed);
                    Assert.NotEmpty(tap.Searches);
                    if (store is null)
                    {
                        store = await ReadStoreAsync(host.Db, ct);
                        await using var snapshot = new FileStream(Path.Combine(folder, $"store-{mode}-{c}.json.gz"), FileMode.CreateNew);
                        await using var zipped = new GZipStream(snapshot, CompressionLevel.SmallestSize);
                        await JsonSerializer.SerializeAsync(zipped, store, cancellationToken: ct);
                    }
                    var byId = store.ToDictionary(s => s.Id, StringComparer.Ordinal);
                    var pool = new HashSet<string>(StringComparer.Ordinal);
                    var above = new HashSet<string>(StringComparer.Ordinal);
                    var returned = new List<string>();
                    foreach (var search in tap.Searches)
                    {
                        Assert.Equal(200, search.Status);
                        Assert.Equal(policy.Limit, search.Limit);
                        if (!rankedCache.TryGetValue(search.Query, out var ranked))
                        {
                            if (mode == "embedding")
                            {
                                var vector = replay.Get(search.Query.Trim());
                                var scored = store.Take(2000).Select(s => (s.Id, Score: EmbeddingService.Cosine(s.Vector!, vector)
                                    + (s.Content.Contains(search.Query.Trim(), StringComparison.OrdinalIgnoreCase) ? 0.15 : 0))).ToList();
                                ranked = ([.. scored.Select(s => s.Id)], [.. scored.Where(s => s.Score >= MemoryLibrary.MinSimilarity).OrderByDescending(s => s.Score).Select(s => s.Id)]);
                            }
                            else
                            {
                                var matches = await MatchAsync(host.Db, search.Query.Trim(), ct);
                                ranked = (matches, matches);
                            }
                            rankedCache.Add(search.Query, ranked);
                        }
                        Assert.Equal(ranked.Above.Take(policy.Limit), search.Ids);
                        pool.UnionWith(ranked.Pool);
                        above.UnionWith(ranked.Above);
                        foreach (var id in search.Ids)
                            if (!returned.Contains(id, StringComparer.Ordinal))
                                returned.Add(id);
                    }
                    var kept = returned.Where(id => !string.Equals(byId[id].Content.Trim(), question.Question.Trim(), StringComparison.OrdinalIgnoreCase)).ToList();
                    var planned = (policy.Newest ? kept.OrderByDescending(id => byId[id].CreatedAt).Take(5) : kept.Take(5)).ToList();
                    var observation = ProductPromptObservation.Observe(tap.SystemMessage, [.. planned.Select(id => new PromptMemory(id, byId[id].Content))]);
                    if (!observation.Identifiable)
                    {
                        Assert.Equal("ambiguous-source", observation.State);
                        unknown++;
                    }
                    var gold = question.Evidence.Distinct(StringComparer.Ordinal).Select(id => "ep_" + EventId(c, id)).ToHashSet(StringComparer.Ordinal);
                    int Count(IEnumerable<string> ids) => ids.ToHashSet(StringComparer.Ordinal).Count(gold.Contains);
                    if (policy.Name == "6-newest")
                    {
                        Assert.Equal(old[(c, q)]["observedFullItemIds"]!.AsArray().Select(i => i!.GetValue<string>()), observation.FullItemIds);
                        Assert.Equal(old[(c, q)]["prompt"]!.GetValue<int>(), Count(observation.FullItemIds));
                        baselines++;
                    }
                    var row = new JsonObject
                    {
                        ["c"] = c, ["q"] = q, ["policy"] = policy.Name, ["position"] = position, ["mode"] = mode,
                        ["answerable"] = AnswerableReanalysis.Answerable(question), ["evidence"] = gold.Count, ["located"] = gold.Count(byId.ContainsKey),
                        ["stored"] = Count(byId.Keys), ["pool"] = Count(pool), ["above"] = Count(above), ["response"] = Count(returned), ["kept"] = Count(kept),
                        ["planned"] = Count(planned), ["prompt"] = observation.Identifiable ? Count(observation.FullItemIds) : null,
                        ["poolIds"] = Ids(pool), ["aboveIds"] = Ids(above), ["responseIds"] = Ids(returned), ["keptIds"] = Ids(kept),
                        ["plannedIds"] = Ids(planned), ["observedIds"] = observation.Identifiable ? Ids(observation.FullItemIds) : null, ["goldIds"] = Ids(gold),
                        ["rawSystem"] = tap.SystemMessage, ["systemSha256"] = observation.SystemSha256,
                        ["state"] = observation.State, ["truncated"] = observation.Truncated, ["completed"] = completed,
                        ["searches"] = new JsonArray([.. tap.Searches.Select(s => JsonSerializer.SerializeToNode(s))]),
                    };
                    await journal.WriteLineAsync(row.ToJsonString().AsMemory(), ct);
                    await journal.FlushAsync(ct);
                    rows++;
                }
                await File.WriteAllTextAsync(Path.Combine(folder, "progress.json"), JsonSerializer.Serialize(new { mode, c, q, rows, baselines, minutes = clock.Elapsed.TotalMinutes }), ct);
            }
            TestContext.Current.SendDiagnosticMessage($"{mode} conversation {c}: {conv.Qa.Count * 4} captured policy turns");
        }
        Assert.Equal(7944, rows);
        Assert.Equal(1986, baselines);
        Assert.Equal(0, replay.Misses);
        await File.WriteAllTextAsync(Path.Combine(folder, $"product-{mode}-receipt.json"), JsonSerializer.Serialize(new
        {
            schema = "aijade.p3.policy.product.v1", planCommit = plan, codeCommit = Environment.GetEnvironmentVariable("AIJADE_GIT_COMMIT"),
            mode, rows, baselines, writes, unknown, corpusSha256 = LocomoCorpus.Sha256, budget, replayCalls = replay.Calls, replayInputs = replay.Inputs,
            replayMisses = replay.Misses, newModelCalls = 0, elapsedMinutes = clock.Elapsed.TotalMinutes,
            source = "experiments/p3-e/2026-11-10-shared-runtime/attempt-02", policies = Policies.Select(p => p.Name),
            binaries = new[] { typeof(ProductPolicyExperimentTests).Assembly, typeof(CompanionRuntime).Assembly, typeof(EmbeddingService).Assembly }.Select(a => new
            {
                name = a.GetName().Name, sha256 = Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(a.Location))),
                informationalVersion = a.GetCustomAttribute<AssemblyInformationalVersionAttribute>()!.InformationalVersion,
            }),
            scope = "Complete configured 2x2 policy design; vector replay; single-turn shared memory runtime; no Web/QQ, evolving history or answer evaluation.",
        }, ReceiptOptions), ct);
    }

    private static JsonArray Ids(IEnumerable<string> ids) => new([.. ids.Select(id => JsonValue.Create(id))]);
    private static string EventId(int conversation, string dia) => $"locomo-{conversation}-{dia.Replace(':', '-')}";

    private static async Task<List<Stored>> ReadStoreAsync(NpgsqlDataSource db, CancellationToken ct)
    {
        var rows = new List<Stored>();
        await using var conn = await db.OpenConnectionAsync(ct);
        await using var cmd = new NpgsqlCommand("SELECT p.id, c.content, p.created_at, c.embedding FROM evidence_packs p JOIN evidence_chunks c ON c.pack_id = p.id ORDER BY p.created_at DESC", conn);
        await using var reader = await cmd.ExecuteReaderAsync(ct);
        while (await reader.ReadAsync(ct))
            rows.Add(new(reader.GetString(0), reader.GetString(1), reader.GetDateTime(2), reader.IsDBNull(3) ? null : (float[])reader.GetValue(3)));
        return rows;
    }

    private static async Task<List<string>> MatchAsync(NpgsqlDataSource db, string query, CancellationToken ct)
    {
        var ids = new List<string>();
        await using var conn = await db.OpenConnectionAsync(ct);
        await using var cmd = new NpgsqlCommand("SELECT p.id FROM evidence_packs p JOIN evidence_chunks c ON c.pack_id = p.id WHERE c.content ILIKE '%' || $1 || '%' ORDER BY p.created_at DESC", conn);
        cmd.Parameters.AddWithValue(query);
        await using var reader = await cmd.ExecuteReaderAsync(ct);
        while (await reader.ReadAsync(ct))
            ids.Add(reader.GetString(0));
        return ids;
    }
}
