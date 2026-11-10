using System.Net;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Chat;
using Aijade.Client.Companion;
using Aijade.Integrations;
using Aijade.Server.Product;

using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;

namespace Aijade.Tests;

public sealed class CompanionRuntimeTests
{
    private sealed class Clock : TimeProvider
    {
        public DateTimeOffset Now { get; set; } = DateTimeOffset.UtcNow;
        public override DateTimeOffset GetUtcNow() => Now;
    }
    private sealed class Module(string text, bool fail = false) : IContextProvider, ITurnObserver
    {
        public int Observations { get; private set; }
        public Task<string?> SupplyAsync(TurnContext turn, CancellationToken ct) =>
            fail ? throw new InvalidOperationException("optional service is offline") : Task.FromResult<string?>(text);
        public Task UserTurnAsync(TurnContext turn, CancellationToken ct) { Observations++; return Task.CompletedTask; }
        public Task AssistantTurnAsync(TurnContext turn, string reply, CancellationToken ct) { Observations++; return Task.CompletedTask; }
    }

    [Fact]
    public async Task Optional_modules_fail_independently_and_a_switch_applies_to_the_next_complete_turn()
    {
        var ct = TestContext.Current.CancellationToken;
        var enabled = false;
        var good = new Module("a quiet home"); var bad = new Module("", fail: true); var switched = new Module("the owner prefers tea");
        var faults = new List<string>();
        var modules = new ChatModuleSet([new("life", good, good), new("offline", bad), new("preference", switched, switched, () => enabled)],
            (id, _) => faults.Add(id));
        var turn = new TurnContext("chat", null, [], "hello");
        Assert.Equal("a quiet home", await modules.SupplyAsync(turn, ct));
        await modules.UserTurnAsync(turn, ct);
        Assert.Equal(1, good.Observations); Assert.Equal(0, switched.Observations);
        enabled = true;
        Assert.Equal("a quiet home", await modules.SupplyAsync(turn, ct));
        await modules.AssistantTurnAsync(turn, "hello", ct);
        Assert.Equal(2, good.Observations); Assert.Equal(0, switched.Observations);
        Assert.Equal(["offline", "offline"], faults);
        var next = new TurnContext("chat", null, [], "another message");
        await modules.UserTurnAsync(next, ct);
        enabled = false;
        Assert.Equal("a quiet home\n\nthe owner prefers tea", await modules.SupplyAsync(next, ct));
        await modules.AssistantTurnAsync(next, "still here", ct);
        Assert.Equal(2, switched.Observations); // the same selected module sees both halves despite a mid-turn switch
        Assert.Equal("a quiet home", await modules.SupplyAsync(new TurnContext("chat", null, [], "third"), ct));
    }

    [Fact]
    public async Task Required_context_and_caller_cancellation_are_never_silently_skipped()
    {
        var turn = new TurnContext("chat", null, [], "hello");
        var modules = new ChatModuleSet([new("identity", new Module("", fail: true), Required: true)]);
        await Assert.ThrowsAsync<InvalidOperationException>(() => modules.SupplyAsync(turn, TestContext.Current.CancellationToken));
        using var cancelled = new CancellationTokenSource(); cancelled.Cancel();
        var optional = new ChatModuleSet([new("life", new Module("home"))]);
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => optional.SupplyAsync(turn, cancelled.Token));
        Assert.Throws<ArgumentException>(() => new ChatModuleSet([new("same", new Module("a")), new("same", new Module("b"))]));
    }

    private sealed class Llm : HttpMessageHandler
    {
        public int Calls { get; private set; }
        public List<JsonNode> Bodies { get; } = [];
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Calls++;
            Bodies.Add(JsonNode.Parse(await request.Content!.ReadAsStringAsync(cancellationToken))!);
            const string sse = "data: {\"choices\":[{\"delta\":{\"content\":\"[[emote:joy]]Here I am.\"}}]}\n\ndata: [DONE]\n\n";
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(sse, Encoding.UTF8, "text/event-stream") };
        }
    }

    private static async Task<AijadeApi> ApiAsync(HttpClient client)
    {
        var tokens = new MemoryTokenStore(); await tokens.SetAsync(ServerTestHost.Token);
        return new AijadeApi(client, tokens);
    }

    private static Task<(int Status, JsonNode? Body)> ConfigureAsync(ServerTestHost host) =>
        host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", JsonNode.Parse("""
            {"models":{"aijade-chat":{"upstream":"https://llm.example/v1","model":"test","keys":["test"],"fluxPer1k":0}}}
            """), ServerTestHost.AdminToken);

    [Fact]
    public async Task Product_prompt_bounds_optional_context_and_old_history_without_clipping_identity_input_or_stored_evidence()
    {
        var ct = TestContext.Current.CancellationToken; var llm = new Llm();
        await using var host = await ServerTestHost.StartAsync(worker: false,
            services: s => s.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => llm));
        await ConfigureAsync(host);
        var api = await ApiAsync(host.Client); var chat = await api.CreateChatAsync(null, "bounded", ct);
        var life = "LIFE " + string.Concat(Enumerable.Repeat("😀", 200));
        var memory = "MEMORY " + new string('m', 300);
        var modules = new ChatModule[] { new("life", new Module(life)), new("memory", new Module(memory)), new("external", new Module("EXTERNAL " + new string('x', 300))) };
        var budget = new PromptBudget { ModuleCharacters = 90, SupplementCharacters = 200, HistoryCharacters = 30 };
        var original = new string('u', 500);
        var history = new StoredMessage[]
        {
            new("1", 1, "user", "old user message", DateTimeOffset.UtcNow),
            new("2", 2, "assistant", "OLD OVERFLOW " + new string('o', 1000), DateTimeOffset.UtcNow),
            new("3", 3, "user", "recent", DateTimeOffset.UtcNow),
            new("4", 4, "assistant", "short answer", DateTimeOffset.UtcNow),
        };
        await foreach (var _ in CompanionRuntime.Create(api, modules, new OrchestratorOptions { PromptBudget = budget })
            .SendAsync(chat.Id, null, history, original, "snapshot", ct)) { }
        var sent = llm.Bodies[^1]["messages"]!.AsArray();
        var system = sent[0]!["content"]!.GetValue<string>();
        Assert.Contains(ChatOrchestrator.DefaultPersona, system, StringComparison.Ordinal);
        Assert.Contains("LIFE ", system, StringComparison.Ordinal); Assert.Contains("MEMORY ", system, StringComparison.Ordinal);
        Assert.DoesNotContain("EXTERNAL", system, StringComparison.Ordinal);
        Assert.DoesNotContain("\ufffd", system, StringComparison.Ordinal);
        Assert.True(system.Length <= ChatOrchestrator.SystemPrompt(null, []).Length + 202);
        Assert.Equal(["recent", "short answer", original], sent.Skip(1).Select(m => m!["content"]!.GetValue<string>()));
        Assert.Equal(original, (await api.MessagesAsync(chat.Id, ct: ct))[0].Content);

        // The archived direct constructor has no implicit product budget. Source hashes alone cannot prove prompt parity.
        var legacy = new ChatOrchestrator(api, [new Module(life)], new OrchestratorOptions());
        await foreach (var _ in legacy.SendAsync(chat.Id, null, history, original, "snapshot", ct)) { }
        var archived = llm.Bodies[^1]["messages"]!.AsArray();
        Assert.Contains(life, archived[0]!["content"]!.GetValue<string>(), StringComparison.Ordinal);
        Assert.Contains(archived, m => m?["content"]?.GetValue<string>() == history[1].Content);
    }

    [Fact]
    public async Task Product_commands_and_normal_chat_use_one_runtime_with_one_stored_exchange_and_no_extra_model_call()
    {
        var ct = TestContext.Current.CancellationToken; var llm = new Llm();
        await using var host = await ServerTestHost.StartAsync(new Dictionary<string, string?> { ["Aijade:Profile"] = "companion" }, worker: false,
            services: s => s.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => llm));
        await ConfigureAsync(host);
        var api = await ApiAsync(host.Client); var sync = new CompanionSync(api); var state = await sync.CurrentAsync(ct);
        var notebook = new SyncedCompanionNotebook(sync, null, state);
        using var weather = new HttpClient();
        var companion = new CompanionExperience(notebook, () => notebook.Latest!.RuntimeProfile, new CompanionWeather(weather), "owner:default");
        var runtime = CompanionRuntime.Create(api, [new("life", companion, companion)], new OrchestratorOptions(), companion);
        var chat = await api.CreateChatAsync(null, "shared runtime", ct);
        var events = new List<OrchestratorEvent>();
        await foreach (var e in runtime.SendAsync(chat.Id, null, [], new ChatInput("/relationship", "Owner"), "snapshot", ct: ct))
            events.Add(e);
        Assert.IsType<MediaCompleted>(Assert.Single(events)); Assert.Equal(0, llm.Calls);
        var history = await api.MessagesAsync(chat.Id, ct: ct);
        Assert.Equal(["user", "assistant"], history.Select(m => m.Role)); Assert.Equal("/relationship", history[0].Content);
        events.Clear();
        await foreach (var e in runtime.SendAsync(chat.Id, null, history, "谢谢你", "snapshot", ct)) events.Add(e);
        Assert.Equal("Here I am.", Assert.IsType<TurnCompleted>(events[^1]).Reply.Content);
        Assert.Equal(1, llm.Calls); Assert.Equal(4, (await api.MessagesAsync(chat.Id, ct: ct)).Count);
        Assert.Equal(1, (await sync.CurrentAsync(ct)).Notebook.Relationship.Interactions);
    }

    private sealed class RejectAssistant(HttpMessageHandler inner) : DelegatingHandler(inner)
    {
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            if (request.Method == HttpMethod.Post && request.RequestUri!.AbsolutePath.EndsWith("/messages", StringComparison.Ordinal) &&
                request.Content is { } body && JsonNode.Parse(await body.ReadAsStringAsync(cancellationToken))?["role"]?.GetValue<string>() == "assistant")
                return new HttpResponseMessage(HttpStatusCode.ServiceUnavailable) { Content = new StringContent("""{"error":"WRITE_FAILED","message":"storage unavailable"}""", Encoding.UTF8, "application/json") };
            return await base.SendAsync(request, cancellationToken);
        }
    }

    [Fact]
    public async Task Reminder_words_in_a_song_title_do_not_create_a_promised_reminder_on_QQ()
    {
        var ct = TestContext.Current.CancellationToken; var clock = new Clock();
        await using var host = await ServerTestHost.StartAsync(worker: false);
        var api = await ApiAsync(host.Client); var sync = new CompanionSync(api); var state = await sync.CurrentAsync(ct);
        var notebook = new SyncedCompanionNotebook(sync, null, state);
        using var weather = new HttpClient();
        var companion = new CompanionExperience(notebook, () => notebook.Latest!.RuntimeProfile, new CompanionWeather(weather), "owner", clock);
        using var bridge = new CompanionBridge(api, new BridgeOptions { Memory = false, ReminderPlatforms = ["qq"], Companion = _ => companion, Time = clock });
        var reply = await bridge.AnswerAsync(new("qq", "owner", "owner", "Owner", "/sing 十分钟后提醒我喝水", true, true), ct);
        Assert.Contains("还没有练好", reply!.Text, StringComparison.Ordinal);
        clock.Now = clock.Now.AddMinutes(11);
        Assert.Null(await bridge.DueReminderAsync(_ => true, ct));
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task A_streamed_reply_is_not_completed_when_storage_fails_in_either_chat_mode(bool proactive)
    {
        var ct = TestContext.Current.CancellationToken; var llm = new Llm();
        await using var host = await ServerTestHost.StartAsync(worker: false,
            services: s => s.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => llm));
        await ConfigureAsync(host);
        using var http = new HttpClient(new RejectAssistant(host.App.GetTestServer().CreateHandler())) { BaseAddress = host.Client.BaseAddress };
        var api = await ApiAsync(http); var chat = await api.CreateChatAsync(null, "failure", ct);
        var runtime = CompanionRuntime.Create(api, [], new OrchestratorOptions());
        var now = DateTimeOffset.UtcNow;
        StoredMessage[] history = [new("u", 1, "user", "今天面试，有点紧张", now.AddSeconds(-425)), new("a", 2, "assistant", "祝你面试顺利！", now.AddSeconds(-420))];
        var stream = proactive ? runtime.SpeakFirstAsync(chat.Id, null, history, "snapshot", 14, ct)
            : runtime.SendAsync(chat.Id, null, [], "hello", "snapshot", ct);
        var events = new List<OrchestratorEvent>();
        await foreach (var e in stream) events.Add(e);
        Assert.Equal("WRITE_FAILED", Assert.IsType<TurnFailed>(events[^1]).Code);
        Assert.DoesNotContain(events, e => e is TurnCompleted);
        Assert.DoesNotContain(await api.MessagesAsync(chat.Id, ct: ct), m => m.Role == "assistant");
        Assert.Equal(1, llm.Calls);
    }
}
