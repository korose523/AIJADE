using System.Diagnostics;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Chat;
using Aijade.Memory.Locomo;
using Aijade.Server.Product;

using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;

using Npgsql;

namespace Aijade.Tests;

/// <summary>Frozen second-corpus text-policy design. Completion bodies are captured locally, never answered by a model.</summary>
public sealed class LongMemEvalProductPolicyTests
{
    private const string Plan = "a7961cf8cde1de659c2272a664d4c936a50484c4";
    private static readonly (int Limit, bool Newest, string Name)[] Policies =
        [(6, true, "6-newest"), (6, false, "6-server"), (60, true, "60-newest"), (60, false, "60-server")];
    private static readonly JsonSerializerOptions Pretty = new() { WriteIndented = true };
    private static readonly string[] FixtureDates = ["2023/05/20 (Sat) 02:21", "2023/05/20 (Sat) 02:21"];
    private static readonly string[] FixtureSessions = ["same", "same"];
    private sealed record Stored(string Id, string Content, DateTime CreatedAt, bool HasVector, string Owner);
    private sealed record CaseResult(int Writes, int Captures, int Unknown, bool Truncated);

    private sealed class ForbiddenGateway : HttpMessageHandler
    {
        public int Attempts { get; private set; }
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Attempts++;
            throw new InvalidOperationException("No gateway, embedding or model request is permitted in this text-only study.");
        }
    }

    [Fact]
    public async Task Complete_second_corpus_text_policy_measurement()
    {
        var ct = TestContext.Current.CancellationToken;
        if (Environment.GetEnvironmentVariable("AIJADE_P3_LME_PRODUCT_OUT") is not { Length: > 0 } output)
        {
            Assert.Skip("set AIJADE_P3_LME_PRODUCT_OUT for the complete 500-question second-corpus execution");
            return;
        }
        var data = Environment.GetEnvironmentVariable("AIJADE_LONGMEMEVAL")!;
        Assert.Equal(LongMemEvalCorpus.Sha256, LocomoCorpus.FileSha256(data));
        var corpus = LongMemEvalCorpus.Load(data, LongMemEvalFrame.AllQuestionsV1);
        Assert.Equal(500, corpus.Count);
        Assert.Equal(470, corpus.Count(c => !LongMemEvalCorpus.IsAbstention(c.SampleId)));
        Directory.CreateDirectory(output);
        var clock = Stopwatch.StartNew();
        int writes = 0, captures = 0, unknown = 0, truncatedCases = 0;
        for (var i = 0; i < corpus.Count; i++)
        {
            var result = await RunCaseAsync(corpus[i], i, output, ct);
            writes += result.Writes; captures += result.Captures; unknown += result.Unknown; truncatedCases += result.Truncated ? 1 : 0;
            await File.WriteAllTextAsync(Path.Combine(output, "progress.json"), JsonSerializer.Serialize(new
            {
                phase = "product-text", completedQuestions = i + 1, questions = 500, writes, captures, unknown, truncatedCases,
                elapsedSeconds = clock.Elapsed.TotalSeconds, planCommit = Plan,
            }), ct);
            TestContext.Current.SendDiagnosticMessage($"LongMemEval text {i + 1}/500, {writes} writes, {captures} captures");
        }
        Assert.Equal(246738, writes); Assert.Equal(2000, captures);
        Assert.Equal(LongMemEvalCorpus.Sha256, LocomoCorpus.FileSha256(data));
        await File.WriteAllTextAsync(Path.Combine(output, "product-receipt.json"), JsonSerializer.Serialize(new
        {
            schema = "aijade.p3.longmemeval.product.text.v2", planCommit = Plan, codeCommit = Environment.GetEnvironmentVariable("AIJADE_GIT_COMMIT"),
            questions = corpus.Count, primaryQuestions = 470, legacyMarkedQuestions = 479, abstentionQuestions = 30, writes, captures, unknown,
            truncatedCases, corpusSha256 = LongMemEvalCorpus.Sha256, policies = Policies.Select(p => p.Name), budget = new PromptBudget(),
            elapsedSeconds = clock.Elapsed.TotalSeconds, newModelCalls = 0, gatewayAttempts = 0,
            binaries = new[] { typeof(LongMemEvalProductPolicyTests).Assembly, typeof(CompanionRuntime).Assembly, typeof(LongMemEvalCorpus).Assembly }.Select(a => new
            {
                name = a.GetName().Name, sha256 = Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(a.Location))),
                informationalVersion = a.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion,
            }),
            scope = "Complete configured text-policy path on frozen cleaned LongMemEval_s. Local stand-in completion only; no dense/external policy, generated answer, Web/QQ or user evaluation.",
        }, Pretty), ct);
    }

    [Theory]
    [InlineData("quartz", false)]
    [InlineData("quartz unrelatedword?", true)]
    public async Task Synthetic_long_unicode_duplicate_and_fallback_writes_reach_the_actual_boundary(string query, bool duplicate)
    {
        // Both source positions share a session ID, with >4,000 UTF-16 units and duplicated content. Never infer a known zero from ambiguous attribution.
        var unicode = "quartz " + string.Concat(Enumerable.Repeat("鱼🐟", 1600));
        using var doc = JsonDocument.Parse(JsonSerializer.Serialize(new
        {
            question_id = "synthetic", question = query, answer = "fixture",
            question_date = "2023/05/30 (Tue) 23:40", haystack_dates = FixtureDates,
            haystack_session_ids = FixtureSessions,
            haystack_sessions = new[]
            {
                Enumerable.Range(0, 35).Select(i => new { role = "user", content = i == 34 ? unicode : $"quartz short-{i}", has_answer = i == 0 }).ToArray(),
                Enumerable.Range(0, 35).Select(i => new { role = "assistant", content = i >= 33 ? duplicate ? unicode : unicode + i : $"quartz other-{i}", has_answer = false }).ToArray(),
            },
        }));
        var conv = LongMemEvalCorpus.ParseQuestion(doc.RootElement, LongMemEvalFrame.AllQuestionsV1)!;
        var output = Path.Combine(Path.GetTempPath(), "aijade-lme-policy-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(output);
        var result = await RunCaseAsync(conv, 0, output, TestContext.Current.CancellationToken);
        Assert.Equal(70, result.Writes); Assert.Equal(4, result.Captures); Assert.True(result.Truncated);
        if (duplicate) Assert.True(result.Unknown > 0); else Assert.Equal(0, result.Unknown);
        var qualification = Environment.GetEnvironmentVariable("AIJADE_P3_LME_QUALIFICATION_OUT");
        if (qualification is { Length: > 0 })
        {
            qualification = Path.Combine(qualification, query == "quartz" ? "ordinary" : "fallback");
            Directory.CreateDirectory(qualification);
            foreach (var file in Directory.EnumerateFiles(output))
                File.Copy(file, Path.Combine(qualification, Path.GetFileName(file)), overwrite: false);
        }
    }

    private static async Task<CaseResult> RunCaseAsync(LocomoConversation conv, int index, string output, CancellationToken ct)
    {
        using var forbidden = new ForbiddenGateway();
        await using var host = await ServerTestHost.StartAsync(worker: false, services: services =>
            services.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => forbidden));
        var prefix = $"question-{index:D3}";
        var source = conv.Episodes.Where(t => !string.IsNullOrWhiteSpace(t.Content)).ToDictionary(t => "ep_" + EventId(index, t.Id), StringComparer.Ordinal);
        await using (var writeFile = new FileStream(Path.Combine(output, prefix + "-writes.jsonl.gz"), FileMode.CreateNew))
        await using (var zipped = new GZipStream(writeFile, CompressionLevel.SmallestSize))
        await using (var writes = new StreamWriter(zipped))
        {
            foreach (var (packId, turn) in source)
            {
                var id = EventId(index, turn.Id);
                var body = new JsonObject
                {
                    ["event_id"] = id, ["session_id"] = $"longmemeval-{index}", ["trace_id"] = "t-" + id, ["correlation_id"] = "t-" + id,
                    ["timestamp"] = turn.CreatedAt, ["origin_device"] = "p3-longmemeval-text", ["privacy_level"] = 1, ["risk_score"] = 0.1,
                    ["source"] = "chat", ["content"] = turn.Content,
                };
                var (status, response) = await host.PostAsync("/api/v1/v9/perception", body);
                await writes.WriteLineAsync(new JsonObject
                {
                    ["sourceId"] = turn.Id, ["packId"] = packId, ["request"] = body, ["status"] = status, ["response"] = response,
                }.ToJsonString().AsMemory(), ct);
                Assert.InRange(status, 200, 299);
            }
        }
        var store = await ReadStoreAsync(host.Db, ct);
        Assert.Equal(source.Count, store.Count);
        var byId = store.ToDictionary(s => s.Id, StringComparer.Ordinal);
        foreach (var item in store)
        {
            Assert.True(source.TryGetValue(item.Id, out var turn));
            Assert.Equal(turn!.Content, item.Content);
            Assert.Equal(turn.CreatedAt, new DateTimeOffset(DateTime.SpecifyKind(item.CreatedAt, DateTimeKind.Utc)).ToUnixTimeMilliseconds());
            Assert.False(item.HasVector); Assert.Equal(ServerTestHost.UserId, item.Owner);
        }
        await WriteGzipAsync(Path.Combine(output, prefix + "-store.json.gz"), store, ct);
        var storeHash = StoreHash(store);
        using var tap = new PolicyTap(host.App.GetTestServer().CreateHandler());
        using var http = new HttpClient(tap) { BaseAddress = host.Client.BaseAddress, Timeout = TimeSpan.FromMinutes(5) };
        var tokens = new MemoryTokenStore(); await tokens.SetAsync(ServerTestHost.Token);
        var api = new AijadeApi(http, tokens);
        var runtimes = Policies.ToDictionary(p => p.Name, p => CompanionRuntime.Create(api,
            [new("memory", p.Name == "6-newest" ? new MemoryRecallProvider(api, () => true) : new PolicyMemoryContext(api, p.Limit, p.Newest))],
            new OrchestratorOptions { PromptBudget = new PromptBudget() }), StringComparer.Ordinal);
        var chat = await api.CreateChatAsync(null, $"longmemeval text {index}", ct);
        var question = conv.Qa.Single();
        var gold = question.Evidence.Select(id => "ep_" + EventId(index, id)).ToHashSet(StringComparer.Ordinal);
        Assert.All(gold, id => Assert.True(byId.ContainsKey(id)));
        var rows = new List<JsonObject>();
        int unknown = 0; bool truncated = false;
        await using var boundaryFile = new FileStream(Path.Combine(output, prefix + "-raw-boundaries.jsonl.gz"), FileMode.CreateNew);
        await using var boundaryZip = new GZipStream(boundaryFile, CompressionLevel.SmallestSize);
        await using var boundaries = new StreamWriter(boundaryZip);
        for (var position = 0; position < Policies.Length; position++)
        {
            var policy = Policies[(index + position) % Policies.Length];
            tap.Reset(); bool completed = false;
            await foreach (var item in runtimes[policy.Name].SendAsync(chat.Id, null, [], question.Question, "p3-longmemeval-text", ct))
                completed |= item is TurnCompleted;
            // Persist even an incomplete/unattributable request before any scientific qualification assertion can fail.
            await boundaries.WriteLineAsync(JsonSerializer.Serialize(new
            {
                rawIndex = index, questionId = conv.SampleId, policy = policy.Name, position, completed,
                tap.CompletionCaptures, tap.CompletionBody, tap.SystemMessage, searches = tap.Searches,
            }).AsMemory(), ct);
            await boundaries.FlushAsync(ct);
            Assert.True(completed); Assert.Equal(1, tap.CompletionCaptures); Assert.NotNull(tap.CompletionBody); Assert.NotEmpty(tap.Searches);
            var pool = new HashSet<string>(StringComparer.Ordinal);
            var returned = new List<string>();
            var matches = new JsonArray();
            foreach (var search in tap.Searches)
            {
                Assert.Equal(200, search.Status); Assert.Equal(policy.Limit, search.Limit);
                var ranked = await MatchAsync(host.Db, search.Query.Trim(), ct);
                QualifyNativeLimit(ranked, search.Ids, policy.Limit, byId);
                pool.UnionWith(ranked);
                matches.Add(new JsonObject { ["query"] = search.Query, ["nativePoolIds"] = Ids(ranked) });
                foreach (var id in search.Ids)
                    if (!returned.Contains(id, StringComparer.Ordinal)) returned.Add(id);
            }
            var kept = returned.Where(id => !string.Equals(byId[id].Content.Trim(), question.Question.Trim(), StringComparison.OrdinalIgnoreCase)).ToArray();
            var planned = (policy.Newest ? kept.OrderByDescending(id => byId[id].CreatedAt).Take(5) : kept.Take(5)).ToArray();
            var observation = ProductPromptObservation.Observe(tap.SystemMessage, planned.Select(id => new PromptMemory(id, byId[id].Content)).ToArray());
            if (!observation.Identifiable) { Assert.Equal("ambiguous-source", observation.State); unknown++; }
            var marker = tap.SystemMessage!.Contains(ProductPromptObservation.Marker, StringComparison.Ordinal);
            truncated |= marker;
            int Count(IEnumerable<string> ids) => ids.Distinct(StringComparer.Ordinal).Count(gold.Contains);
            rows.Add(new JsonObject
            {
                ["rawIndex"] = index, ["questionId"] = conv.SampleId, ["policy"] = policy.Name, ["position"] = position,
                ["answerable"] = !LongMemEvalCorpus.IsAbstention(conv.SampleId), ["legacyMarked"] = gold.Count > 0,
                ["evidence"] = gold.Count, ["stored"] = Count(byId.Keys), ["pool"] = Count(pool), ["response"] = Count(returned),
                ["kept"] = Count(kept), ["planned"] = Count(planned), ["prompt"] = observation.Identifiable ? Count(observation.FullItemIds) : null,
                ["promptLower"] = observation.Identifiable ? Count(observation.FullItemIds) : 0,
                ["promptUpper"] = observation.Identifiable ? Count(observation.FullItemIds) : Count(planned),
                ["poolIds"] = Ids(pool), ["responseIds"] = Ids(returned), ["keptIds"] = Ids(kept), ["plannedIds"] = Ids(planned),
                ["observedIds"] = observation.Identifiable ? Ids(observation.FullItemIds) : null, ["goldIds"] = Ids(gold),
                ["state"] = observation.State, ["attributable"] = observation.Identifiable, ["truncated"] = observation.Truncated, ["rawTruncationMarker"] = marker,
                ["rawSystem"] = tap.SystemMessage, ["systemSha256"] = observation.SystemSha256,
                ["completionBody"] = tap.CompletionBody, ["completionBodySha256"] = Hash(tap.CompletionBody!),
                ["searches"] = new JsonArray(tap.Searches.Select(s => JsonSerializer.SerializeToNode(s)).ToArray()), ["poolQueries"] = matches,
                ["storeSha256"] = storeHash, ["completed"] = completed, ["completionCaptures"] = tap.CompletionCaptures,
            });
        }
        Assert.Equal(storeHash, StoreHash(await ReadStoreAsync(host.Db, ct)));
        Assert.Equal(0, forbidden.Attempts);
        await WriteGzipAsync(Path.Combine(output, prefix + "-captures.json.gz"), rows, ct);
        return new(source.Count, rows.Count, unknown, truncated);
    }

    private static void QualifyNativeLimit(List<string> ranked, IReadOnlyList<string> returned, int limit, IReadOnlyDictionary<string, Stored> store)
    {
        Assert.Equal(Math.Min(limit, ranked.Count), returned.Count); Assert.Equal(returned.Count, returned.Distinct(StringComparer.Ordinal).Count());
        var set = ranked.ToHashSet(StringComparer.Ordinal);
        Assert.All(returned, id => Assert.Contains(id, set));
        Assert.Equal(returned.Select(id => store[id].CreatedAt).OrderDescending(), returned.Select(id => store[id].CreatedAt));
        if (returned.Count == 0) return;
        var boundary = store[ranked[Math.Min(limit, ranked.Count) - 1]].CreatedAt;
        Assert.All(ranked.Where(id => store[id].CreatedAt > boundary), id => Assert.Contains(id, returned));
        Assert.All(returned, id => Assert.True(store[id].CreatedAt >= boundary));
    }

    private static async Task<List<Stored>> ReadStoreAsync(NpgsqlDataSource db, CancellationToken ct)
    {
        var rows = new List<Stored>();
        await using var conn = await db.OpenConnectionAsync(ct);
        await using var cmd = new NpgsqlCommand("SELECT p.id,c.content,p.created_at,c.embedding IS NOT NULL,o.user_id FROM evidence_packs p JOIN evidence_chunks c ON c.pack_id=p.id JOIN memory_session_owners o ON o.session_id=p.session_id ORDER BY p.created_at DESC", conn);
        await using var reader = await cmd.ExecuteReaderAsync(ct);
        while (await reader.ReadAsync(ct)) rows.Add(new(reader.GetString(0), reader.GetString(1), reader.GetDateTime(2), reader.GetBoolean(3), reader.GetString(4)));
        return rows;
    }

    private static async Task<List<string>> MatchAsync(NpgsqlDataSource db, string query, CancellationToken ct)
    {
        var ids = new List<string>();
        await using var conn = await db.OpenConnectionAsync(ct);
        await using var cmd = new NpgsqlCommand("SELECT p.id FROM evidence_packs p JOIN evidence_chunks c ON c.pack_id=p.id WHERE c.content ILIKE '%' || $1 || '%' ORDER BY p.created_at DESC", conn);
        cmd.Parameters.AddWithValue(query);
        await using var reader = await cmd.ExecuteReaderAsync(ct);
        while (await reader.ReadAsync(ct)) ids.Add(reader.GetString(0));
        return ids;
    }

    private static string EventId(int index, string sourceId) => $"longmem-{index}-{Hash(sourceId)}";
    private static string Hash(string text) => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(text)));
    private static string StoreHash(IEnumerable<Stored> store) => Hash(JsonSerializer.Serialize(store.OrderBy(s => s.Id, StringComparer.Ordinal)));
    private static JsonArray Ids(IEnumerable<string> ids) => new(ids.Select(id => (JsonNode?)JsonValue.Create(id)).ToArray());
    private static async Task WriteGzipAsync<T>(string path, T value, CancellationToken ct)
    {
        await using var file = new FileStream(path, FileMode.CreateNew);
        await using var zip = new GZipStream(file, CompressionLevel.SmallestSize);
        await JsonSerializer.SerializeAsync(zip, value, cancellationToken: ct);
    }
}
