using System.Diagnostics;
using System.Net.Http.Json;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Chat;
using Aijade.Client.Companion;
using Aijade.Server.Product;

using Microsoft.Extensions.DependencyInjection;

namespace Aijade.Tests;

/// <summary>Opt-in synthetic product check with an existing local model; not a study or a model-quality benchmark.</summary>
public sealed class CompanionLiveTests
{
    private static readonly JsonSerializerOptions WebJson = new(JsonSerializerDefaults.Web);
    private static readonly JsonSerializerOptions PrettyJson = new() { WriteIndented = true };
    private sealed class RecordingGateway(HttpMessageHandler inner, Uri endpoint, HttpClient metadata) : DelegatingHandler(inner)
    {
        public List<JsonObject> Calls { get; } = [];
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            Assert.Equal(endpoint.Authority, request.RequestUri!.Authority);
            var body = JsonNode.Parse(await request.Content!.ReadAsStringAsync(ct))!.AsObject();
            body["max_tokens"] = 256; // explicit development budget; formal research settings are not altered
            request.Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json");
            var record = new JsonObject { ["request"] = body.DeepClone(), ["startedAt"] = DateTimeOffset.UtcNow };
            Calls.Add(record); var elapsed = Stopwatch.StartNew();
            var response = await base.SendAsync(request, ct);
            record["loadedState"] = await metadata.GetFromJsonAsync<JsonObject>("/api/ps", ct);
            var raw = await response.Content.ReadAsStringAsync(ct);
            record["wallSeconds"] = elapsed.Elapsed.TotalSeconds; record["status"] = (int)response.StatusCode;
            record["response"] = raw;
            var kind = response.Content.Headers.ContentType?.MediaType ?? "text/event-stream";
            response.Content = new StringContent(raw, Encoding.UTF8, kind);
            return response;
        }
    }

    [Fact]
    public async Task A_local_model_turn_can_be_saved_quoted_and_forgotten_through_the_product_runtime()
    {
        var model = Environment.GetEnvironmentVariable("AIJADE_COMPANION_LIVE_MODEL");
        if (string.IsNullOrWhiteSpace(model)) Assert.Skip("AIJADE_COMPANION_LIVE_MODEL is not set; live product check is opt-in");
        var endpoint = new Uri(Environment.GetEnvironmentVariable("AIJADE_COMPANION_LIVE_URL") ?? "http://127.0.0.1:11510");
        Assert.True(endpoint.IsLoopback && endpoint.Scheme == "http", "This check sends synthetic data only to a local operator-owned model service");
        var output = Environment.GetEnvironmentVariable("AIJADE_COMPANION_LIVE_RECEIPT");
        Assert.False(string.IsNullOrWhiteSpace(output), "A separate output receipt is required");
        Assert.False(File.Exists(output), "Refusing to overwrite an earlier live check");
        var ct = TestContext.Current.CancellationToken;
        using var metadata = new HttpClient { BaseAddress = endpoint };
        var tags = await metadata.GetFromJsonAsync<JsonObject>("/api/tags", ct);
        var identity = tags!["models"]!.AsArray().Single(m => m?["name"]?.GetValue<string>() == model)!.DeepClone();
        using var recorder = new RecordingGateway(new HttpClientHandler(), endpoint, metadata);
        var observations = new JsonArray();
        var report = new JsonObject { ["kind"] = "synthetic companion product smoke; not primary research", ["status"] = "FAILED", ["turns"] = observations,
            ["model"] = identity, ["contextConfigured"] = 4096, ["maxOutputTokens"] = 256,
            ["transportNote"] = "Actual local HTTP model responses are recorded then forwarded as SSE; streaming latency is not measured.",
            ["backendVersion"] = await metadata.GetFromJsonAsync<JsonObject>("/api/version", ct) };
        try
        {
            await using var host = await ServerTestHost.StartAsync(new Dictionary<string, string?> { ["Aijade:Profile"] = "companion" }, worker: false,
                services: s => s.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => recorder));
            host.Client.Timeout = TimeSpan.FromMinutes(5); // recorded SSE buffering must allow the configured gateway's cold-start deadline
            report["testClientTimeoutSeconds"] = 300;
            await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", new JsonObject { ["models"] = new JsonObject
            {
                ["aijade-chat"] = new JsonObject { ["upstream"] = new Uri(endpoint, "/v1").ToString(), ["model"] = model, ["keys"] = new JsonArray("local-development") },
            } }, ServerTestHost.AdminToken);
            var tokens = new MemoryTokenStore(); await tokens.SetAsync(ServerTestHost.Token);
            var api = new AijadeApi(host.Client, tokens); var sync = new CompanionSync(api); var state = await sync.CurrentAsync(ct);
            var notebook = new SyncedCompanionNotebook(sync, null, state); using var weather = new HttpClient();
            var companion = new CompanionExperience(notebook, () => notebook.Latest!.RuntimeProfile, new CompanionWeather(weather), "synthetic-owner");
            var runtime = CompanionRuntime.Create(api, [new("life", companion, companion)], new OrchestratorOptions { Temperature = 0 }, companion);
            var chat = await api.CreateChatAsync(null, "Synthetic live product check", ct);
            foreach (var input in new[] { "I am a little tired after reading. Please answer in one short English sentence.",
                "I feel better now. Let us read again tomorrow. Please answer in one short English sentence." })
            {
                var events = new List<OrchestratorEvent>();
                await foreach (var e in runtime.SendAsync(chat.Id, null, await api.MessagesAsync(chat.Id, ct: ct), input, "synthetic", ct)) events.Add(e);
                if (events.LastOrDefault() is TurnFailed failed)
                    observations.Add(new JsonObject { ["input"] = input, ["failureCode"] = failed.Code, ["failureMessage"] = failed.Message });
                var completed = Assert.IsType<TurnCompleted>(events[^1]); Assert.NotEmpty(completed.Reply.Content);
                observations.Add(new JsonObject { ["input"] = input, ["storedReply"] = completed.Reply.Content, ["messageId"] = completed.Reply.Id });
            }
            var calls = recorder.Calls.Count;
            var media = new List<OrchestratorEvent>();
            await foreach (var e in runtime.SendAsync(chat.Id, null, [], "/diary save", "synthetic", ct)) media.Add(e);
            Assert.IsType<MediaCompleted>(Assert.Single(media));
            var diary = await sync.ReadDiaryAsync(null, ct: ct); var entry = Assert.Single(diary.Entries);
            var originalReply = observations[^1]!["storedReply"]!.GetValue<string>();
            Assert.StartsWith(entry.Assistant.Text, originalReply, StringComparison.Ordinal);
            Assert.Equal(Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(Encoding.UTF8.GetBytes(originalReply))), entry.Assistant.Sha256);
            await foreach (var _ in runtime.SendAsync(chat.Id, null, [], "/diary", "synthetic", ct)) { }
            Assert.Equal(calls, recorder.Calls.Count); Assert.Equal(2, calls);
            await sync.RemoveDiaryEntryAsync(null, entry.Id, diary.Revision, ct);
            Assert.Empty((await sync.ReadDiaryAsync(null, diary.Day, ct)).Entries);
            Assert.Contains(await api.MessagesAsync(chat.Id, ct: ct), m => m.Id == entry.Assistant.MessageId);
            report["savedDiary"] = JsonSerializer.SerializeToNode(diary, WebJson);
            report["diaryCommandsAddedModelCalls"] = 0; report["originalChatRetainedAfterForgetting"] = true;
            report["status"] = "PASS";
        }
        finally
        {
            report["calls"] = new JsonArray([.. recorder.Calls.Select(x => (JsonNode)x.DeepClone())]);
            report["finishedAt"] = DateTimeOffset.UtcNow;
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output!))!);
            await File.WriteAllTextAsync(output!, report.ToJsonString(PrettyJson), CancellationToken.None);
        }
    }
}
