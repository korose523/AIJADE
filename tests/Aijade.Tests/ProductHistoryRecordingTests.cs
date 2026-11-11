using System.Diagnostics;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Chat;
using Aijade.Memory.Locomo;
using Aijade.Server.Product;

using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;

namespace Aijade.Tests;

/// <summary>Complete controlled public-question trajectories; never generates an answer with a model.</summary>
public sealed class ProductHistoryRecordingTests
{
    private sealed class GatewayState { internal int Attempts; }
    private sealed class ForbiddenGateway(GatewayState state) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            Interlocked.Increment(ref state.Attempts);
            throw new InvalidOperationException("Live gateway request forbidden in the history-recording study");
        }
    }
    private sealed record Counts(int BaseWrites, int QuestionWrites, int Rows, int Captures, int Unknown, int GatewayAttempts);
    private static readonly JsonSerializerOptions Pretty = new(JsonSerializerDefaults.Web) { WriteIndented = true };
    private static readonly string[] FixtureQuestions = ["quartz impossiblephase", "quartz", "quartz"];
    private static readonly string[] FixtureEvidence = ["D1:1"];
    private static string Hash(string text) => HistoryRecordingSupport.Hash(text);

    [Fact]
    public async Task Complete_controlled_history_and_recording_trajectories()
    {
        if (Environment.GetEnvironmentVariable("AIJADE_P3_HISTORY_OUT") is not { Length: > 0 } output)
        {
            Assert.Skip("Complete scripted history/recording study is opt-in; no model inference");
            return;
        }
        var ct = TestContext.Current.CancellationToken;
        var corpusPath = Environment.GetEnvironmentVariable("AIJADE_P3E_CORPUS")!;
        Assert.Equal(LocomoCorpus.Sha256, LocomoCorpus.FileSha256(corpusPath));
        var corpus = LocomoCorpus.Load(corpusPath);
        Assert.Equal(10, corpus.Count); Assert.Equal(1986, corpus.Sum(c => c.Qa.Count));
        Directory.CreateDirectory(output);
        var clock = Stopwatch.StartNew(); var counts = new List<Counts>();
        var journal = new HistoryJournal(Path.Combine(output, "batch-journal.jsonl"));
        await File.WriteAllTextAsync(Path.Combine(output, "prompt-constants.json"), new JsonObject
        {
            ["persona"] = ChatOrchestrator.DefaultPersona,
            ["expressionInstruction"] = Expressions.Instruction,
            ["replyInstruction"] = CompanionRuntime.VisibleReplyInstruction,
            ["memoryHeader"] = ProductPromptObservation.Header,
            ["truncationMarker"] = ProductPromptObservation.Marker,
            ["promptBudget"] = JsonSerializer.SerializeToNode(new PromptBudget(), HistoryRecordingSupport.Json),
            ["historyWindow"] = new OrchestratorOptions().HistoryWindow,
        }.ToJsonString(Pretty), ct);
        for (var c = 0; c < corpus.Count; c++)
        {
            for (var position = 0; position < HistoryRecordingSupport.Arms.Length; position++)
            {
                var arm = HistoryRecordingSupport.Arms[(c + position) % HistoryRecordingSupport.Arms.Length];
                var folder = Path.Combine(output, $"c{c:D2}-{arm}");
                journal.Add($"c{c:D2}/{arm}", "trajectory.begin");
                var result = await RunTrajectoryAsync(corpus[c], c, arm, position, folder,
                    Path.Combine(output, "database-leases.jsonl"), ct);
                counts.Add(result);
                journal.Add($"c{c:D2}/{arm}", "trajectory.complete", JsonSerializer.SerializeToNode(result, HistoryRecordingSupport.Json));
                await File.WriteAllTextAsync(Path.Combine(output, "batch-progress.json"), JsonSerializer.Serialize(new
                {
                    completedTrajectories = counts.Count, rows = counts.Sum(x => x.Rows), lastConversation = c, lastArm = arm,
                }, Pretty), ct);
            }
        }
        await File.WriteAllTextAsync(Path.Combine(output, "execution.json"), JsonSerializer.Serialize(new
        {
            schema = "aijade.p3.history-recording-execution.v1", status = "SCHEDULED_TRAJECTORIES_COMPLETE",
            codeCommit = Environment.GetEnvironmentVariable("AIJADE_GIT_COMMIT"), planCommit = Environment.GetEnvironmentVariable("AIJADE_P3_HISTORY_PLAN"),
            corpusSha256 = LocomoCorpus.Sha256, conversations = corpus.Count, questions = corpus.Sum(c => c.Qa.Count),
            trajectories = counts.Count, rows = counts.Sum(x => x.Rows), captures = counts.Sum(x => x.Captures),
            baseWrites = counts.Sum(x => x.BaseWrites), questionWrites = counts.Sum(x => x.QuestionWrites),
            unknownObservations = counts.Sum(x => x.Unknown), gatewayAttempts = counts.Sum(x => x.GatewayAttempts),
            elapsedSeconds = clock.Elapsed.TotalSeconds, newModelCalls = 0, formalHardwareQualification = false,
            binaries = new[] { typeof(ProductHistoryRecordingTests).Assembly, typeof(CompanionRuntime).Assembly, typeof(LocomoCorpus).Assembly }.Select(a => new
            {
                name = a.GetName().Name, sha256 = Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(a.Location))),
                informationalVersion = a.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion,
            }),
            scope = "Five specified public-question/history/recording trajectories. Default text memory path, fixed reply stand-in; not natural dialogue, answer quality, contradiction labels, full Web/QQ or default external fact maintenance.",
        }, Pretty), ct);
        Assert.Equal(0, counts.Sum(x => x.GatewayAttempts));
    }

    [Theory]
    [InlineData("static")]
    [InlineData("history")]
    [InlineData("record-after")]
    [InlineData("record-before")]
    [InlineData("record-between")]
    public async Task Synthetic_schedules_keep_actual_history_and_one_record_at_the_declared_boundary(string arm)
    {
        var longText = "quartz " + string.Concat(Enumerable.Repeat("quartz 🐟 ", 800));
        var turns = Enumerable.Range(0, 8).Select(i => new
        {
            dia_id = "D1:" + i, speaker = "synthetic", text = i == 0 ? "quartz" : i == 7 ? longText : "quartz source-" + i,
        }).ToArray();
        var questions = FixtureQuestions
            .Select(q => new { question = q, answer = "not sent to the runtime", evidence = FixtureEvidence, category = 1 }).ToArray();
        using var document = JsonDocument.Parse(JsonSerializer.Serialize(new
        {
            sample_id = "synthetic-history",
            conversation = new { session_1_date_time = "12:00 pm on 1 January, 2023", session_1 = turns }, qa = questions,
        }));
        var conversation = LocomoCorpus.ParseConversation(document.RootElement);
        var configured = Environment.GetEnvironmentVariable("AIJADE_P3_HISTORY_QUAL_OUT");
        var root = configured ?? Path.Combine(Path.GetTempPath(), "aijade-history-qualification-" + Guid.NewGuid().ToString("N"));
        var folder = Path.Combine(root, arm);
        var result = await RunTrajectoryAsync(conversation, 0, arm, 0, folder, null, TestContext.Current.CancellationToken);
        Assert.Equal(3, result.Rows); Assert.Equal(3, result.Captures); Assert.Equal(0, result.GatewayAttempts);
        Assert.Equal(HistoryRecordingSupport.Records(arm) ? 3 : 0, result.QuestionWrites);
        var records = await ReadRowsAsync(Path.Combine(folder, "records.jsonl.gz"), TestContext.Current.CancellationToken);
        foreach (var row in records)
        {
            var q = row["q"]!.GetValue<int>(); var expectedHistory = arm == "static" ? 0 : 2 * q;
            Assert.Equal(expectedHistory, row["historySupplied"]!.AsArray().Count);
            Assert.True(row["completed"]!.GetValue<bool>()); Assert.Equal(1, row["completionCaptures"]!.GetValue<int>());
            Assert.Empty(row["moduleFailures"]!.AsArray());
            Assert.Equal(8 + (HistoryRecordingSupport.Records(arm) ? q : 0), row["storeBefore"]!["count"]!.GetValue<int>());
            Assert.Equal(8 + (HistoryRecordingSupport.Records(arm) ? q + 1 : 0), row["storeAfter"]!["count"]!.GetValue<int>());
            var searches = row["searches"]!.AsArray();
            Assert.NotEmpty(searches);
            var extraAtFirst = arm == "record-before" ? 1 : 0;
            Assert.Equal(8 + (HistoryRecordingSupport.Records(arm) ? q : 0) + extraAtFirst,
                searches[0]!["storeCountAtResponse"]!.GetValue<int>());
            if (arm == "record-between")
            {
                Assert.Single(row["questionWrites"]!.AsArray());
                var second = searches.Skip(1).ToArray();
                if (q == 0) Assert.NotEmpty(second);
                Assert.All(second, s => Assert.Equal(8 + q + 1, s!["storeCountAtResponse"]!.GetValue<int>()));
            }
        }
    }

    private static async Task<Counts> RunTrajectoryAsync(LocomoConversation conversation, int c, string arm, int position,
        string folder, string? leases, CancellationToken ct)
    {
        Directory.CreateDirectory(folder);
        var gateway = new GatewayState();
        await using var host = await ServerTestHost.StartAsync(worker: false, services: services =>
            services.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => new ForbiddenGateway(gateway)));
        var database = await host.ScalarAsync("SELECT current_database()");
        if (leases is not null) File.AppendAllText(leases, new JsonObject { ["database"] = database, ["c"] = c, ["arm"] = arm }.ToJsonString() + "\n");
        var journal = new HistoryJournal(Path.Combine(folder, "journal.jsonl"));
        var session = $"p3-history-{c}";
        var source = conversation.Episodes.Where(e => !string.IsNullOrWhiteSpace(e.Content))
            .ToDictionary(e => "ep_" + HistoryRecordingSupport.EventId(c, e.Id), StringComparer.Ordinal);
        var logical = source.ToDictionary(p => p.Key, p => "source:" + p.Value.Id, StringComparer.Ordinal);
        using (var file = new FileStream(Path.Combine(folder, "base-writes.jsonl.gz"), FileMode.CreateNew))
        using (var zip = new GZipStream(file, CompressionLevel.SmallestSize))
        using (var writes = new StreamWriter(zip))
        {
            foreach (var (packId, episode) in source)
            {
                var id = HistoryRecordingSupport.EventId(c, episode.Id);
                var body = new JsonObject
                {
                    ["event_id"] = id, ["session_id"] = session, ["trace_id"] = "trace-" + id, ["correlation_id"] = "trace-" + id,
                    ["timestamp"] = episode.CreatedAt, ["origin_device"] = "p3-history", ["privacy_level"] = 1,
                    ["risk_score"] = .1, ["source"] = "chat", ["content"] = episode.Content,
                };
                var (status, response) = await host.PostAsync("/api/v1/v9/perception", body);
                await writes.WriteLineAsync(new JsonObject { ["sourceId"] = episode.Id, ["packId"] = packId,
                    ["request"] = body, ["status"] = status, ["response"] = response }.ToJsonString().AsMemory(), ct);
                await writes.FlushAsync(ct);
                Assert.InRange(status, 200, 299);
            }
        }
        var original = await HistoryRecordingSupport.StoreAsync(host, ct);
        Assert.Equal(source.Count, original.Count);
        Assert.All(original, item =>
        {
            Assert.Equal(source[item.Id].Content, item.Content);
            Assert.Equal((long)source[item.Id].CreatedAt, item.CreatedAt);
            Assert.Equal(ServerTestHost.UserId, item.Owner); Assert.False(item.HasVector);
        });
        await WriteGzipAsync(Path.Combine(folder, "base-store.json.gz"), original, ct);
        journal.Add("trajectory", "base.complete", HistoryRecordingSupport.State(original, logical));
        await File.WriteAllTextAsync(Path.Combine(folder, "input.json"), new JsonObject
        {
            ["c"] = c, ["sampleId"] = conversation.SampleId, ["arm"] = arm, ["position"] = position, ["database"] = database,
            ["questions"] = conversation.Qa.Count, ["baseItems"] = original.Count,
            ["promptBudget"] = JsonSerializer.SerializeToNode(new PromptBudget(), HistoryRecordingSupport.Json),
            ["historyWindow"] = new OrchestratorOptions().HistoryWindow,
            ["baseCanonicalSha256"] = HistoryRecordingSupport.State(original, logical)["canonicalSha256"]!.DeepClone(),
        }.ToJsonString(Pretty), ct);
        using var tap = new HistoryRecordingTap(host.App.GetTestServer().CreateHandler(), host, journal);
        using var http = new HttpClient(tap) { BaseAddress = host.Client.BaseAddress, Timeout = TimeSpan.FromMinutes(5) };
        var tokens = new MemoryTokenStore(); await tokens.SetAsync(ServerTestHost.Token);
        var api = new AijadeApi(http, tokens);
        var failures = new List<string>();
        var runtime = CompanionRuntime.Create(api, [new("memory", new MemoryRecallProvider(api, () => true))],
            new OrchestratorOptions { PromptBudget = new PromptBudget() }, audio: false,
            moduleFailed: (id, ex) => failures.Add(id + ":" + ex.GetType().Name));
        var chat = await api.CreateChatAsync(null, "controlled p3 history " + arm, ct);
        var time = new HistoryRecordingClock();
        var recorder = new ConversationRecorder(api, session, "p3-history", time);
        var totalWrites = 0; var captured = 0; var unknown = 0; var rows = 0;
        await using var stream = new FileStream(Path.Combine(folder, "records.jsonl.gz"), FileMode.CreateNew);
        await using var compressed = new GZipStream(stream, CompressionLevel.SmallestSize);
        await using var output = new StreamWriter(compressed);
        for (var q = 0; q < conversation.Qa.Count; q++)
        {
            var question = conversation.Qa[q]; var key = $"c{c:D2}/{arm}/q{q:D4}";
            tap.Begin(key); failures.Clear(); time.Now = new DateTimeOffset(2026, 11, 12, 0, 0, 0, TimeSpan.Zero).AddMinutes(q);
            journal.Add(key, "question.begin");
            var before = await HistoryRecordingSupport.StoreAsync(host, ct);
            var beforeState = HistoryRecordingSupport.State(before, logical);
            IReadOnlyList<StoredMessage> history = arm == "static" ? [] : await api.MessagesAsync(chat.Id, ct: ct);
            var questionWrites = new JsonArray();
            async Task RecordAsync()
            {
                journal.Add(key, "question.record.begin");
                var prior = tap.Calls.Count(x => x["path"]!.GetValue<string>() == "/api/v1/v9/perception");
                var accepted = await recorder.RecordAsync(question.Question, ct);
                var call = tap.Calls.Where(x => x["path"]!.GetValue<string>() == "/api/v1/v9/perception").Skip(prior).Single();
                var body = JsonNode.Parse(call["requestBody"]!.GetValue<string>())!;
                var packId = "ep_" + body["event_id"]!.GetValue<string>();
                logical.Add(packId, "question:" + q.ToString("D4", System.Globalization.CultureInfo.InvariantCulture));
                var store = await HistoryRecordingSupport.StoreAsync(host, ct);
                var stored = store.Single(s => s.Id == packId);
                var item = new JsonObject
                {
                    ["q"] = q, ["packId"] = packId, ["logicalId"] = logical[packId], ["call"] = call["call"]!.DeepClone(),
                    ["accepted"] = accepted, ["stored"] = JsonSerializer.SerializeToNode(stored, HistoryRecordingSupport.Json),
                };
                questionWrites.Add(item); totalWrites++;
                journal.Add(key, "question.record.end", item);
            }
            if (arm == "record-before") await RecordAsync();
            if (arm == "record-between") tap.AfterFirstMemoryResponse = RecordAsync;
            journal.Add(key, "turn.begin");
            var completed = false; var events = new JsonArray();
            await foreach (var item in runtime.SendAsync(chat.Id, null, history, question.Question, "p3-history", ct))
            {
                if (item is TurnCompleted) completed = true;
                if (item is TurnCompleted or TurnFailed) events.Add(JsonSerializer.SerializeToNode(item, item.GetType(), HistoryRecordingSupport.Json));
            }
            journal.Add(key, "turn.end", new JsonObject { ["completed"] = completed });
            if (arm == "record-after") await RecordAsync();
            var after = await HistoryRecordingSupport.StoreAsync(host, ct);
            var selected = HistoryRecordingSupport.Selected(tap.Searches, question.Question);
            var system = tap.CompletionBody is null ? null : JsonNode.Parse(tap.CompletionBody)!["messages"]!.AsArray()
                .First(n => n!["role"]!.GetValue<string>() == "system")!["content"]!.GetValue<string>();
            var observed = ProductPromptObservation.Observe(system, selected.Select(s => new PromptMemory(s.Id, s.Content)).ToArray());
            var gold = question.Evidence.Distinct(StringComparer.Ordinal)
                .Select(id => "ep_" + HistoryRecordingSupport.EventId(c, id)).ToArray();
            var row = new JsonObject
            {
                ["c"] = c, ["arm"] = arm, ["q"] = q, ["sampleId"] = conversation.SampleId,
                ["question"] = question.Question, ["category"] = question.Category,
                ["evidenceSourceIds"] = JsonSerializer.SerializeToNode(question.Evidence, HistoryRecordingSupport.Json),
                ["goldIds"] = JsonSerializer.SerializeToNode(gold, HistoryRecordingSupport.Json),
                ["unlocatedGoldIds"] = JsonSerializer.SerializeToNode(gold.Where(id => !source.ContainsKey(id)), HistoryRecordingSupport.Json),
                ["historySupplied"] = JsonSerializer.SerializeToNode(history, HistoryRecordingSupport.Json),
                ["storeBefore"] = beforeState, ["storeAfter"] = HistoryRecordingSupport.State(after, logical),
                ["questionWrites"] = questionWrites, ["completed"] = completed, ["events"] = events,
                ["moduleFailures"] = JsonSerializer.SerializeToNode(failures, HistoryRecordingSupport.Json),
                ["calls"] = new JsonArray(tap.Calls.Select(n => (JsonNode)n.DeepClone()).ToArray()),
                ["searches"] = new JsonArray(tap.Searches.Select(n => (JsonNode)n.DeepClone()).ToArray()),
                ["selected"] = JsonSerializer.SerializeToNode(selected, HistoryRecordingSupport.Json),
                ["completionCaptures"] = tap.Completions, ["completionBody"] = tap.CompletionBody,
                ["promptObservation"] = JsonSerializer.SerializeToNode(observed, HistoryRecordingSupport.Json),
                ["gatewayAttempts"] = gateway.Attempts,
            };
            await output.WriteLineAsync(row.ToJsonString().AsMemory(), ct); await output.FlushAsync(ct);
            journal.Add(key, "question.complete", new JsonObject { ["rowSha256"] = Hash(row.ToJsonString()) });
            rows++; captured += tap.Completions; if (!observed.Identifiable) unknown++;
            await File.WriteAllTextAsync(Path.Combine(folder, "progress.json"), new JsonObject
            {
                ["rows"] = rows, ["captures"] = captured, ["questionWrites"] = totalWrites, ["lastQuestion"] = q,
            }.ToJsonString(), ct);
        }
        var final = await HistoryRecordingSupport.StoreAsync(host, ct);
        await WriteGzipAsync(Path.Combine(folder, "final-store.json.gz"), final, ct);
        var counts = new Counts(source.Count, totalWrites, rows, captured, unknown, gateway.Attempts);
        await File.WriteAllTextAsync(Path.Combine(folder, "receipt.json"), JsonSerializer.Serialize(new
        {
            status = "TRAJECTORY_OBSERVATIONS_COMPLETE", c, arm, position, database, counts,
            codeCommit = Environment.GetEnvironmentVariable("AIJADE_GIT_COMMIT"), newModelCalls = 0,
            firstStore = HistoryRecordingSupport.State(original, source.ToDictionary(p => p.Key, p => "source:" + p.Value.Id, StringComparer.Ordinal)),
            finalStore = HistoryRecordingSupport.State(final, logical),
        }, Pretty), ct);
        journal.Add("trajectory", "trajectory.complete", JsonSerializer.SerializeToNode(counts, HistoryRecordingSupport.Json));
        Assert.Equal(0, gateway.Attempts);
        return counts;
    }

    private static async Task WriteGzipAsync<T>(string path, T value, CancellationToken ct)
    {
        await using var file = new FileStream(path, FileMode.CreateNew);
        await using var zip = new GZipStream(file, CompressionLevel.SmallestSize);
        await JsonSerializer.SerializeAsync(zip, value, HistoryRecordingSupport.Json, ct);
    }

    private static async Task<List<JsonNode>> ReadRowsAsync(string path, CancellationToken ct)
    {
        await using var file = File.OpenRead(path); await using var zip = new GZipStream(file, CompressionMode.Decompress);
        using var reader = new StreamReader(zip); var rows = new List<JsonNode>();
        while (await reader.ReadLineAsync(ct) is { } line) rows.Add(JsonNode.Parse(line)!);
        return rows;
    }
}
