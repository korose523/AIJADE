using System.Diagnostics;
using System.IO.Compression;
using System.Net;
using System.Security.Cryptography;
using System.Text;
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

/// <summary>
/// P3-E (experiments/plans/2026-11-05-p3-e-product-delivery-path.md): how much of a question's evidence reaches the prompt on
/// the product's own path. Each LoCoMo conversation goes into a fresh product store through the perception endpoint; each
/// question goes through <see cref="ChatOrchestrator.SendAsync(string, Aijade.Client.Api.Character?, IReadOnlyList{StoredMessage}, string, string, CancellationToken)"/>
/// with the product's memory provider; the prompt is captured where the model would be called. Run with AIJADE_EXPERIMENT_DIR,
/// AIJADE_P3E_CORPUS and AIJADE_P3E_CONDITION (text, or embedding with Ollama on 127.0.0.1:11434); skipped otherwise.
/// New runs must also select AIJADE_P3E_ENTRY (legacy-direct or shared-memory-only). Version 2 observes full text in the
/// actual request and writes a distinct schema/file; it must not be fed silently into the archived version 1 aggregator.
/// </summary>
public class ProductDeliveryExperimentTests
{
    private const string EmbeddingModel = "nomic-embed-text";
    private const int ServerLimit = 6;
    private const int PromptItems = 5;

    /// <summary>Reads the client's calls at the transport, and stands in for the model.</summary>
    private sealed class Tap(HttpMessageHandler server) : DelegatingHandler(server)
    {
        public List<(string Query, List<string> Ids)> Searches { get; } = [];
        public List<JsonObject> Responses { get; } = [];

        public string? SystemMessage { get; private set; }

        public int Calls { get; private set; }

        public void Reset()
        {
            Searches.Clear();
            Responses.Clear();
            SystemMessage = null;
            Calls = 0;
        }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Calls++;
            var path = request.RequestUri!.AbsolutePath;
            if (path.EndsWith("/openai/v1/chat/completions", StringComparison.Ordinal))
            {
                var body = JsonNode.Parse(await request.Content!.ReadAsStringAsync(cancellationToken).ConfigureAwait(false))!;
                SystemMessage = body["messages"]!.AsArray().First(m => m!["role"]!.GetValue<string>() == "system")!["content"]!.GetValue<string>();
                return new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent("data: {\"choices\":[{\"delta\":{\"content\":\"ok\"}}]}\n\ndata: [DONE]\n\n", Encoding.UTF8, "text/event-stream"),
                };
            }
            var response = await base.SendAsync(request, cancellationToken).ConfigureAwait(false);
            if (path.EndsWith("/api/v1/memory/items", StringComparison.Ordinal) || path.EndsWith("/api/v1/memory/items/", StringComparison.Ordinal))
            {
                var text = await response.Content.ReadAsStringAsync(cancellationToken).ConfigureAwait(false);
                var query = global::System.Web.HttpUtility.ParseQueryString(request.RequestUri.Query)["q"] ?? "";
                Responses.Add(new JsonObject { ["query"] = query, ["status"] = (int)response.StatusCode, ["rawBody"] = text });
                Searches.Add((query, response.IsSuccessStatusCode ? [.. JsonNode.Parse(text)!["items"]!.AsArray().Select(i => i!["id"]!.GetValue<string>())] : []));
                response.Content = new StringContent(text, Encoding.UTF8, "application/json");
            }
            return response;
        }
    }

    private sealed record Stored(string Id, string Content, DateTime CreatedAt, float[]? Vector);

    [Fact]
    public async Task Evidence_is_followed_from_the_store_to_the_prompt()
    {
        var ct = TestContext.Current.CancellationToken;
        if (Environment.GetEnvironmentVariable("AIJADE_EXPERIMENT_DIR") is not { Length: > 0 } dir
            || Environment.GetEnvironmentVariable("AIJADE_P3E_CORPUS") is not { Length: > 0 } corpusPath
            || Environment.GetEnvironmentVariable("AIJADE_P3E_CONDITION") is not { Length: > 0 } condition)
        {
            Assert.Skip("set AIJADE_EXPERIMENT_DIR, AIJADE_P3E_CORPUS and AIJADE_P3E_CONDITION to run P3-E");
            return;
        }
        Assert.True(condition is "text" or "embedding");
        var entry = Environment.GetEnvironmentVariable("AIJADE_P3E_ENTRY");
        Assert.True(entry is "legacy-direct" or "shared-memory-only", "select AIJADE_P3E_ENTRY explicitly; shared-memory-only is not the full Web/QQ host");
        var budget = entry == "legacy-direct" ? null : new PromptBudget();
        var planCommit = Environment.GetEnvironmentVariable("AIJADE_P3E_PLAN_COMMIT");
        Assert.True(planCommit?.Length == 40, "record the separately pushed current-version plan commit");
        Assert.Equal(LocomoCorpus.Sha256, LocomoCorpus.FileSha256(corpusPath));
        Directory.CreateDirectory(dir);
        var journal = Path.Combine(dir, $"rows-{entry}-{condition}.jsonl");
        var embeddingJournal = Path.Combine(dir, $"embeddings-{entry}-{condition}.jsonl");
        foreach (var path in new[] { journal, embeddingJournal })
            using (new FileStream(path, FileMode.CreateNew)) { }
        await using (var metadata = new FileStream(Path.Combine(dir, $"run-{entry}-{condition}.json"), FileMode.CreateNew))
            await global::System.Text.Json.JsonSerializer.SerializeAsync(metadata, new
            {
                entry, condition, planCommit, declaredCodeCommit = Environment.GetEnvironmentVariable("AIJADE_GIT_COMMIT"),
                productBase = "d9dcf6bdc928f822e7a2fc3bf4e2cb00a36ebade", startedAt = DateTimeOffset.UtcNow,
                testAssemblySha256 = Hash(typeof(ProductDeliveryExperimentTests).Assembly.Location),
                clientAssemblySha256 = Hash(typeof(CompanionRuntime).Assembly.Location),
                serverAssemblySha256 = Hash(typeof(EmbeddingService).Assembly.Location),
                corpusSha256 = LocomoCorpus.Sha256,
            }, cancellationToken: ct);
        var embedding = condition == "embedding";
        var corpus = LocomoCorpus.Load(corpusPath);
        var rows = new JsonArray();
        int responseMismatches = 0, promptMismatches = 0, failedTurns = 0, skippedTurns = 0, notStored = 0, plannedBlockDifferences = 0, ambiguousPrompts = 0, embeddingMisses = 0;
        var clock = Stopwatch.StartNew();
        for (var c = 0; c < corpus.Count; c++)
        {
            var conv = corpus[c];
            using var embeddingTap = new ProductEmbeddingObservation(new HttpClientHandler(), embeddingJournal);
            await using var host = await ServerTestHost.StartAsync(worker: false,
                services: s => s.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => embeddingTap));
            if (embedding)
            {
                var routes = new JsonObject { ["embeddings"] = new JsonObject { ["upstream"] = "http://127.0.0.1:11434/v1", ["model"] = EmbeddingModel, ["keys"] = new JsonArray("ollama") } };
                Assert.Equal(200, (await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", routes, ServerTestHost.AdminToken)).Status);
            }
            var written = 0;
            foreach (var turn in conv.Episodes)
            {
                if (string.IsNullOrWhiteSpace(turn.Content))
                {
                    skippedTurns++;
                    continue;
                }
                var id = EventId(c, turn.Id);
                var (status, _) = await host.SendAsync(HttpMethod.Post, "/api/v1/v9/perception", new JsonObject
                {
                    ["event_id"] = id, ["session_id"] = $"locomo-{c}", ["trace_id"] = $"t-{id}", ["correlation_id"] = $"t-{id}", ["timestamp"] = turn.CreatedAt,
                    ["origin_device"] = "p3-e", ["privacy_level"] = 1, ["risk_score"] = 0.1, ["source"] = "chat", ["content"] = turn.Content,
                });
                if (status is < 200 or >= 300)
                    notStored++;
                else
                    written++;
            }

            using var tap = new Tap(host.App.GetTestServer().CreateHandler());
            // The first search on the embedding path embeds the whole store first, which outlasts the default 100 seconds on a CPU.
            using var http = new HttpClient(tap) { BaseAddress = host.Client.BaseAddress, Timeout = TimeSpan.FromHours(1) };
            var tokens = new MemoryTokenStore();
            await tokens.SetAsync(ServerTestHost.Token);
            var api = new AijadeApi(http, tokens);
            var memory = new MemoryRecallProvider(api, () => true);
            var orchestrator = entry == "legacy-direct"
                ? new ChatOrchestrator(api, [memory], new OrchestratorOptions())
                : CompanionRuntime.Create(api, [new("memory", memory)], new OrchestratorOptions { PromptBudget = budget });
            var chat = await api.CreateChatAsync(null, $"p3-e {c}", ct);
            List<Stored>? store = null;
            for (var q = 0; q < conv.Qa.Count; q++)
            {
                var question = conv.Qa[q];
                tap.Reset();
                embeddingTap.Vectors.Clear();
                var started = clock.Elapsed;
                var completed = false;
                await foreach (var e in orchestrator.SendAsync(chat.Id, null, [], question.Question, "p3-e", ct))
                {
                    if (e is TurnCompleted)
                        completed = true;
                }
                if (!completed)
                    failedTurns++;
                var ms = (clock.Elapsed - started).TotalMilliseconds;
                // On the embedding path the first search has just embedded the store, so read it after that search.
                if (store is null)
                {
                    store = await ReadStoreAsync(host.Db, ct);
                    await using var output = new FileStream(Path.Combine(dir, $"store-{entry}-{condition}-{c}.json.gz"), FileMode.CreateNew);
                    await using var compressed = new GZipStream(output, CompressionLevel.SmallestSize);
                    await global::System.Text.Json.JsonSerializer.SerializeAsync(compressed, store, cancellationToken: ct);
                }
                var byId = store.ToDictionary(s => s.Id, StringComparer.Ordinal);

                // Step 2 and 3: the pool and what passes the threshold, recomputed with the server's predicate and formula.
                var pool = new HashSet<string>(StringComparer.Ordinal);
                var above = new HashSet<string>(StringComparer.Ordinal);
                var mismatch = false;
                foreach (var (query, returned) in tap.Searches)
                {
                    List<string> expected;
                    if (embedding)
                    {
                        if (!embeddingTap.Vectors.TryGetValue(query.Trim(), out var v))
                        {
                            embeddingMisses++;
                            mismatch = true;
                            continue;
                        }
                        var scored = store.Take(2000)
                            .Select(s => (s.Id, Score: EmbeddingService.Cosine(s.Vector!, v) + (s.Content.Contains(query.Trim(), StringComparison.OrdinalIgnoreCase) ? 0.15 : 0)))
                            .ToList();
                        pool.UnionWith(scored.Select(s => s.Id));
                        var passing = scored.Where(s => s.Score >= MemoryLibrary.MinSimilarity).OrderByDescending(s => s.Score).ToList();
                        above.UnionWith(passing.Select(s => s.Id));
                        expected = [.. passing.Take(ServerLimit).Select(s => s.Id)];
                    }
                    else
                    {
                        var matched = await MatchAsync(host.Db, query.Trim(), ct);
                        pool.UnionWith(matched);
                        above.UnionWith(matched);
                        expected = [.. matched.Take(ServerLimit)];
                    }
                    if (!expected.SequenceEqual(returned))
                        mismatch = true;
                }
                if (mismatch)
                    responseMismatches++;

                // Steps 4 and 5: the client's own rule, on what the server returned.
                var received = new List<string>();
                foreach (var (_, returned) in tap.Searches)
                {
                    foreach (var id in returned)
                    {
                        if (!received.Contains(id, StringComparer.Ordinal))
                            received.Add(id);
                    }
                }
                var kept = received.Where(id => !string.Equals(byId[id].Content.Trim(), question.Question.Trim(), StringComparison.OrdinalIgnoreCase)).ToList();
                var planned = kept.OrderByDescending(id => byId[id].CreatedAt).Take(PromptItems).ToList();
                var byServer = kept.Take(PromptItems).ToList();
                var observation = ProductPromptObservation.Observe(tap.SystemMessage, [.. planned.Select(id => new PromptMemory(id, byId[id].Content))]);
                var inPrompt = observation.FullItemIds;
                if (!observation.Identifiable && observation.State != "ambiguous-source")
                    promptMismatches++;
                if (observation.State == "ambiguous-source")
                    ambiguousPrompts++;
                if (!observation.Identifiable || !planned.SequenceEqual(inPrompt))
                    plannedBlockDifferences++;

                var located = question.Evidence.Where(d => conv.Episodes.Any(t => t.Id == d)).Distinct(StringComparer.Ordinal).ToList();
                var ids = located.Select(d => $"ep_{EventId(c, d)}").ToList();
                int Count(IEnumerable<string> set)
                {
                    var s = set.ToHashSet(StringComparer.Ordinal);
                    return ids.Count(s.Contains);
                }
                var newestEvidence = ids.Where(byId.ContainsKey).Select(i => byId[i].CreatedAt).DefaultIfEmpty(DateTime.MinValue).Max();
                var row = new JsonObject
                {
                    ["c"] = c, ["q"] = q, ["category"] = question.Category, ["answerable"] = AnswerableReanalysis.Answerable(question),
                    ["evidence"] = question.Evidence.Distinct(StringComparer.Ordinal).Count(), ["located"] = located.Count,
                    ["stored"] = Count(byId.Keys), ["pool"] = Count(pool), ["above"] = Count(above), ["response"] = Count(received), ["kept"] = Count(kept),
                    ["plannedPrompt"] = Count(planned), ["plannedPromptItems"] = planned.Count,
                    ["prompt"] = observation.Identifiable ? Count(inPrompt) : null,
                    ["serverTop5"] = Count(byServer),
                    ["promptItems"] = observation.Identifiable ? inPrompt.Count : null, ["serverTop5Items"] = byServer.Count,
                    ["newerInPrompt"] = !observation.Identifiable || newestEvidence == DateTime.MinValue ? null : inPrompt.Count(i => byId[i].CreatedAt > newestEvidence),
                    ["newerInServerTop5"] = newestEvidence == DateTime.MinValue ? null : byServer.Count(i => byId[i].CreatedAt > newestEvidence),
                    ["repeatsInPrompt"] = observation.Identifiable ? inPrompt.Count - inPrompt.Select(i => byId[i].Content).Distinct(StringComparer.Ordinal).Count() : null,
                    ["promptState"] = observation.State, ["promptIdentifiable"] = observation.Identifiable, ["promptTruncated"] = observation.Truncated,
                    ["plannedPromptIds"] = new JsonArray([.. planned.Select(i => JsonValue.Create(i))]),
                    ["observedFullItemIds"] = observation.Identifiable ? new JsonArray([.. inPrompt.Select(i => JsonValue.Create(i))]) : null,
                    ["systemSha256"] = observation.SystemSha256, ["rawSystem"] = tap.SystemMessage,
                    ["completed"] = completed, ["providerConsulted"] = tap.Searches.Count > 0,
                    ["searchTrace"] = new JsonArray([.. tap.Responses.Select(r => r.DeepClone())]),
                    ["embeddingRequestsSoFar"] = embeddingTap.Requests, ["embeddingFailuresSoFar"] = embeddingTap.Failures,
                    ["searches"] = tap.Searches.Count, ["termSearch"] = tap.Searches.Count > 1, ["firstEmpty"] = tap.Searches.Count == 0 || tap.Searches[0].Ids.Count == 0,
                    ["echoDropped"] = received.Count - kept.Count, ["fewerThanFive"] = kept.Count < PromptItems, ["mismatch"] = mismatch,
                    ["ms"] = Math.Round(ms, 1), ["calls"] = tap.Calls,
                };
                rows.Add(row);
                await ProductEmbeddingObservation.AppendAsync(journal, row, ct);
                await File.WriteAllTextAsync(Path.Combine(dir, $"progress-{entry}-{condition}.json"), new JsonObject
                {
                    ["condition"] = condition, ["conversation"] = c, ["question"] = q, ["rows"] = rows.Count,
                    ["minutes"] = Math.Round(clock.Elapsed.TotalMinutes, 2), ["failedTurns"] = failedTurns,
                    ["responseMismatches"] = responseMismatches, ["promptMismatches"] = promptMismatches,
                }.ToJsonString(), ct);
            }
            TestContext.Current.SendDiagnosticMessage($"conversation {c}: {written} turns, {conv.Qa.Count} questions, {clock.Elapsed.TotalMinutes:F1} min");
        }

        var report = new JsonObject
        {
            ["schema"] = "aijade.product-path.observed-prompt.v2",
            ["instrumentationRevision"] = "durable-upstream-capture-20261110",
            ["plan"] = "experiments/plans/2026-11-10-p3-e-shared-runtime.md", ["planCommit"] = planCommit,
            ["experiment"] = "P3-E: evidence along the product's delivery path",
            ["historicalReferencePlan"] = "experiments/plans/2026-11-05-p3-e-product-delivery-path.md",
            ["executionGate"] = "Author explicitly requested this Mac full-corpus run; no supervisor receipt or external registration is inferred. See current plan decision.",
            ["declaredCodeCommit"] = Environment.GetEnvironmentVariable("AIJADE_GIT_COMMIT"),
            ["testAssemblySha256"] = Convert.ToHexStringLower(SHA256.HashData(await File.ReadAllBytesAsync(typeof(ProductDeliveryExperimentTests).Assembly.Location, ct))),
            ["clientAssemblySha256"] = Convert.ToHexStringLower(SHA256.HashData(await File.ReadAllBytesAsync(typeof(CompanionRuntime).Assembly.Location, ct))),
            ["entry"] = entry,
            ["scope"] = "memory-only; empty history; no question recording; local model-response stand-in; not full Web/QQ, multi-turn or proactive delivery",
            ["promptBudget"] = budget is null ? null : global::System.Text.Json.JsonSerializer.SerializeToNode(budget),
            ["budgetUnit"] = "UTF-16 code units, not tokens",
            ["condition"] = condition,
            ["embeddingModel"] = embedding ? EmbeddingModel : null,
            ["corpusSha256"] = LocomoCorpus.Sha256,
            ["skippedEmptyTurns"] = skippedTurns,
            ["turnsNotStored"] = notStored,
            ["failedTurns"] = failedTurns,
            ["responseMismatches"] = responseMismatches,
            ["promptMismatches"] = promptMismatches,
            ["plannedBlockDifferences"] = plannedBlockDifferences,
            ["ambiguousPrompts"] = ambiguousPrompts, ["embeddingObservationMisses"] = embeddingMisses,
            ["minutes"] = Math.Round(clock.Elapsed.TotalMinutes, 1),
            ["generatedAt"] = DateTimeOffset.UtcNow.ToString("O"),
            ["rows"] = rows,
        };
        Directory.CreateDirectory(dir);
        await using (var output = new FileStream(Path.Combine(dir, $"product-path-v2-{entry}-{condition}.json"), FileMode.CreateNew))
            await global::System.Text.Json.JsonSerializer.SerializeAsync(output, report, cancellationToken: ct);
        Assert.Equal(0, failedTurns);
        Assert.Equal(0, notStored);
        Assert.Equal(0, responseMismatches);
        Assert.Equal(0, promptMismatches);
        Assert.Equal(0, embeddingMisses);
    }

    private static string Hash(string path) => Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(path)));

    private static string EventId(int conversation, string dia) => $"locomo-{conversation}-{dia.Replace(':', '-')}";

    private static async Task<List<Stored>> ReadStoreAsync(NpgsqlDataSource db, CancellationToken ct)
    {
        var rows = new List<Stored>();
        await using var conn = await db.OpenConnectionAsync(ct);
        await using var cmd = new NpgsqlCommand("SELECT p.id, c.content, p.created_at, c.embedding FROM evidence_packs p JOIN evidence_chunks c ON c.pack_id = p.id ORDER BY p.created_at DESC", conn);
        await using var r = await cmd.ExecuteReaderAsync(ct);
        while (await r.ReadAsync(ct))
            rows.Add(new Stored(r.GetString(0), r.GetString(1), r.GetDateTime(2), r.IsDBNull(3) ? null : (float[])r.GetValue(3)));
        return rows;
    }

    /// <summary>The text search's predicate and order, with no limit.</summary>
    private static async Task<List<string>> MatchAsync(NpgsqlDataSource db, string query, CancellationToken ct)
    {
        var ids = new List<string>();
        await using var conn = await db.OpenConnectionAsync(ct);
        await using var cmd = new NpgsqlCommand("SELECT p.id FROM evidence_packs p JOIN evidence_chunks c ON c.pack_id = p.id WHERE c.content ILIKE '%' || $1 || '%' ORDER BY p.created_at DESC", conn);
        cmd.Parameters.AddWithValue(query);
        await using var r = await cmd.ExecuteReaderAsync(ct);
        while (await r.ReadAsync(ct))
            ids.Add(r.GetString(0));
        return ids;
    }
}
