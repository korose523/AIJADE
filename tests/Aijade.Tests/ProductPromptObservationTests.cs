using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Chat;

using Microsoft.AspNetCore.TestHost;

namespace Aijade.Tests;

public sealed class ProductPromptObservationTests
{
    private sealed class FixedContext(string text) : IContextProvider
    {
        public Task<string?> SupplyAsync(TurnContext turn, CancellationToken ct) => Task.FromResult<string?>(text);
    }

    private sealed class Tap(HttpMessageHandler inner, bool failMemory, CancellationTokenSource? cancel) : DelegatingHandler(inner)
    {
        public string? SystemMessage { get; private set; }
        public int Searches { get; private set; }
        public List<PromptMemory> Returned { get; } = [];
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken ct)
        {
            var path = request.RequestUri!.AbsolutePath;
            if (path.EndsWith("/openai/v1/chat/completions", StringComparison.Ordinal))
            {
                var body = JsonNode.Parse(await request.Content!.ReadAsStringAsync(ct))!;
                SystemMessage = body["messages"]!.AsArray().First(m => m!["role"]!.GetValue<string>() == "system")!["content"]!.GetValue<string>();
                if (cancel is not null)
                {
                    await cancel.CancelAsync();
                    ct.ThrowIfCancellationRequested();
                }
                return new HttpResponseMessage(HttpStatusCode.OK)
                {
                    Content = new StringContent("data: {\"choices\":[{\"delta\":{\"content\":\"ok\"}}]}\n\ndata: [DONE]\n\n", Encoding.UTF8, "text/event-stream"),
                };
            }
            if (!path.TrimEnd('/').EndsWith("/api/v1/memory/items", StringComparison.Ordinal))
                return await base.SendAsync(request, ct);
            Searches++;
            if (failMemory)
                return new HttpResponseMessage(HttpStatusCode.ServiceUnavailable)
                {
                    Content = new StringContent("""{"error":"MEMORY_UNAVAILABLE","message":"qualification fixture"}""", Encoding.UTF8, "application/json"),
                };
            var response = await base.SendAsync(request, ct);
            var text = await response.Content.ReadAsStringAsync(ct);
            foreach (var item in JsonNode.Parse(text)!["items"]!.AsArray())
                Returned.Add(new(item!["id"]!.GetValue<string>(), item["content"]!.GetValue<string>()));
            response.Content = new StringContent(text, Encoding.UTF8, "application/json");
            return response;
        }
    }

    [Theory]
    [InlineData("shared-short", 80, 5, 1, "complete")]
    [InlineData("shared-long", 1500, 2, 1, "truncated")]
    [InlineData("legacy-long", 1500, 5, 1, "complete")]
    [InlineData("disabled", 80, 0, 0, "absent")]
    [InlineData("memory-failure", 80, 0, 1, "absent")]
    [InlineData("budget-exhausted", 80, 0, 0, "absent")]
    [InlineData("cancelled", 80, 5, 1, "complete")]
    public async Task Actual_requests_distinguish_full_partial_and_omitted_memory(string scenario, int bodyLength, int visible, int searches, string state)
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(worker: false);
        // Real perception writes and real memory queries; no corpus, model, embedding route or external recipient.
        var contents = Enumerable.Range(0, 6).Select(i => $"quartz fixture-{i} " + new string((char)('a' + i), bodyLength)).ToArray();
        for (var i = 0; i < contents.Length; i++)
        {
            var (status, _) = await host.PostAsync("/api/v1/v9/perception", new JsonObject
            {
                ["event_id"] = $"qualification-{i}", ["session_id"] = "qualification", ["trace_id"] = $"trace-{i}", ["correlation_id"] = $"trace-{i}",
                ["timestamp"] = new DateTimeOffset(2026, 1, 1, 0, 0, 0, TimeSpan.Zero).AddDays(i).ToUnixTimeMilliseconds(),
                ["origin_device"] = "synthetic-qualification", ["privacy_level"] = 1, ["risk_score"] = 0.1, ["source"] = "chat", ["content"] = contents[i],
            });
            Assert.InRange(status, 200, 299);
        }
        using var cancellation = CancellationTokenSource.CreateLinkedTokenSource(ct);
        using var tap = new Tap(host.App.GetTestServer().CreateHandler(), scenario == "memory-failure", scenario == "cancelled" ? cancellation : null);
        using var http = new HttpClient(tap) { BaseAddress = host.Client.BaseAddress };
        var tokens = new MemoryTokenStore(); await tokens.SetAsync(ServerTestHost.Token);
        var api = new AijadeApi(http, tokens);
        var chat = await api.CreateChatAsync(null, "synthetic prompt qualification", ct);
        var memory = new MemoryRecallProvider(api, () => true);
        var modules = new List<ChatModule>();
        if (scenario == "budget-exhausted")
        {
            modules.Add(new("first", new FixedContext(new string('x', 4_000))));
            modules.Add(new("second", new FixedContext(new string('y', 4_000))));
            modules.Add(new("third", new FixedContext(new string('z', 4_000))));
        }
        modules.Add(new("memory", memory, Enabled: () => scenario != "disabled"));
        var runtime = scenario == "legacy-long"
            ? new ChatOrchestrator(api, [memory], new OrchestratorOptions())
            : CompanionRuntime.Create(api, modules, new OrchestratorOptions());
        var events = new List<OrchestratorEvent>();
        async Task RunAsync()
        {
            await foreach (var e in runtime.SendAsync(chat.Id, null, [], "quartz", "synthetic-qualification", cancellation.Token)) events.Add(e);
        }
        if (scenario == "cancelled")
            await Assert.ThrowsAnyAsync<OperationCanceledException>(RunAsync);
        else
            await RunAsync();

        Assert.Equal(searches, tap.Searches);
        var planned = tap.Returned.Take(5).ToArray(); // the real endpoint returns newest first in this text-only fixture
        if (searches > 0 && scenario != "memory-failure")
        {
            Assert.Equal(6, tap.Returned.Count);
            Assert.Equal(contents.Reverse().Take(5), planned.Select(p => p.Content));
        }
        var observation = ProductPromptObservation.Observe(tap.SystemMessage, planned);
        Assert.True(observation.Identifiable);
        Assert.Equal(state, observation.State);
        Assert.Equal(visible, observation.FullItemIds.Count);
        Assert.Equal(planned.Take(visible).Select(p => p.Id), observation.FullItemIds);
        if (scenario == "shared-long")
        {
            Assert.Contains(ProductPromptObservation.Marker, tap.SystemMessage!, StringComparison.Ordinal);
            Assert.Contains("quartz fixture-3", tap.SystemMessage!, StringComparison.Ordinal); // third item is only partial
            Assert.DoesNotContain(contents[3], tap.SystemMessage!, StringComparison.Ordinal);
        }
        var stored = await api.MessagesAsync(chat.Id, ct: ct);
        Assert.Equal(scenario == "cancelled" ? 1 : 2, stored.Count);
        Assert.Equal("user", stored[0].Role);
        if (scenario != "cancelled")
            Assert.Equal("assistant", stored[1].Role);
        Assert.Equal(scenario == "cancelled" ? 0 : 1, events.Count(e => e is TurnCompleted));
        Assert.DoesNotContain(events, e => e is TurnFailed);
        if (Environment.GetEnvironmentVariable("AIJADE_PROMPT_QUALIFICATION_DIR") is { Length: > 0 } dir)
        {
            Directory.CreateDirectory(dir);
            var report = new
            {
                schema = "aijade.synthetic-prompt-qualification.v1", scenario, bodyLength, searches = tap.Searches,
                entry = scenario == "legacy-long" ? "legacy-direct" : "shared-runtime",
                defaultBudget = scenario == "legacy-long" ? null : new PromptBudget(),
                planned, observation, rawSystem = tap.SystemMessage, storedRoles = stored.Select(m => m.Role).ToArray(),
                completedTurns = events.Count(e => e is TurnCompleted), cancelled = scenario == "cancelled",
                testAssemblySha256 = Hash(typeof(ProductPromptObservationTests).Assembly.Location),
                clientAssemblySha256 = Hash(typeof(CompanionRuntime).Assembly.Location),
                generatedAt = DateTimeOffset.UtcNow,
            };
            await using var output = new FileStream(Path.Combine(dir, scenario + ".json"), FileMode.CreateNew);
            await JsonSerializer.SerializeAsync(output, report, cancellationToken: ct);
        }
    }

    [Fact]
    public void Missing_capture_ambiguous_sources_and_unexplained_blocks_are_not_reported_as_observed_zero()
    {
        PromptMemory[] plan = [new("a", "alpha"), new("b", "beta")];
        var block = ProductPromptObservation.Header + "- alpha\n- beta";
        Assert.False(ProductPromptObservation.Observe(null, plan).Identifiable);
        Assert.False(ProductPromptObservation.Observe(block, []).Identifiable);
        Assert.False(ProductPromptObservation.Observe(block + "\n" + block, plan).Identifiable);
        Assert.False(ProductPromptObservation.Observe(block, [new("a", "alpha"), new("b", "alpha")]).Identifiable);
        Assert.False(ProductPromptObservation.Observe(block, [new("a", "alpha"), new("a", "beta")]).Identifiable);
        Assert.False(ProductPromptObservation.Observe(block, [new("a", ProductPromptObservation.Marker)]).Identifiable);
        Assert.False(ProductPromptObservation.Observe(block, [new("a", ProductPromptObservation.Header)]).Identifiable);
        Assert.False(ProductPromptObservation.Observe(block + "unexpected", plan).Identifiable);
        Assert.False(ProductPromptObservation.Observe(ProductPromptObservation.Header + "- changed" + ProductPromptObservation.Marker, plan).Identifiable);
        var truncated = ProductPromptObservation.Observe(ProductPromptObservation.Header + "- alpha\n- be" + ProductPromptObservation.Marker, plan);
        Assert.True(truncated.Identifiable); Assert.Equal("a", Assert.Single(truncated.FullItemIds));
        Assert.True(ProductPromptObservation.Observe("no memory block", plan).Identifiable);
    }

    private static string Hash(string path) => Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(path)));
}
