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
    public async Task Optional_modules_fail_independently_and_switches_take_effect_without_losing_the_other_context()
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
        Assert.Equal("a quiet home\n\nthe owner prefers tea", await modules.SupplyAsync(turn, ct));
        await modules.AssistantTurnAsync(turn, "hello", ct);
        Assert.Equal(2, good.Observations); Assert.Equal(1, switched.Observations);
        Assert.Equal(["offline", "offline"], faults);
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
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Calls++;
            const string sse = "data: {\"choices\":[{\"delta\":{\"content\":\"[[emote:joy]]Here I am.\"}}]}\n\ndata: [DONE]\n\n";
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(sse, Encoding.UTF8, "text/event-stream") });
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
