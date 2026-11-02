using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Bots;
using Aijade.Client.Api;
using Aijade.Client.Chat;
using Aijade.Client.Companion;
using Aijade.Integrations;
using Aijade.Server.Product;

using Microsoft.Extensions.DependencyInjection;

namespace Aijade.Tests;

/// <summary>
/// Reminders she promised (ADR-003, migration batch 1): the port of MOSAIC's companion_reminders, case by case against the
/// vectors its own module made (configs/companion/reminder-vectors.json), the book that keeps them, and her due line.
/// </summary>
public class RemindersTests
{
    private static readonly string Root = RqcReanalysisTests.RepoRoot();

    private static JsonElement Vectors()
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(Root, "configs", "companion", "reminder-vectors.json")));
        return doc.RootElement.Clone();
    }

    [Fact]
    public void Every_case_is_read_as_MOSAICs_module_reads_it()
    {
        var v = Vectors();
        var zone = TimeZoneInfo.FindSystemTimeZoneById(v.GetProperty("timeZone").GetString()!);
        var now = v.GetProperty("now").GetProperty("epoch").GetDouble();
        var constants = v.GetProperty("constants");
        Assert.Equal(constants.GetProperty("ask").EnumerateArray().Select(x => x.GetString()), Reminders.Ask);
        Assert.Equal(constants.GetProperty("askWithTime").EnumerateArray().Select(x => x.GetString()), Reminders.AskWithTime);
        Assert.Equal(constants.GetProperty("query").EnumerateArray().Select(x => x.GetString()), Reminders.Query);
        Assert.Equal(constants.GetProperty("cancel").EnumerateArray().Select(x => x.GetString()), Reminders.Cancel);
        Assert.Equal((constants.GetProperty("minAheadS").GetDouble(), constants.GetProperty("maxAheadS").GetDouble(), constants.GetProperty("lateS").GetDouble()),
            (Reminders.MinAheadS, Reminders.MaxAheadS, Reminders.LateS));
        Assert.Equal(Reminders.DueCue, constants.GetProperty("dueCue").GetString());
        foreach (var c in v.GetProperty("cases").EnumerateArray())
        {
            var text = c.GetProperty("text").GetString()!;
            var found = Reminders.Request(text, now, zone);
            var expected = c.GetProperty("request");
            if (expected.ValueKind == JsonValueKind.Null)
            {
                Assert.True(found is null, $"{text}: expected nothing, got {found}");
                continue;
            }
            Assert.True(found is not null, $"{text}: expected {expected}");
            Assert.Equal(expected.GetProperty("kind").GetString(), found.Kind.ToString().ToLowerInvariant());
            if (found.Kind != ReminderKind.Set)
                continue;
            Assert.True(expected.GetProperty("dueOffsetS").GetInt64() == (long)Math.Round(found.Due - now), $"{text}: due offset {found.Due - now}");
            Assert.Equal(expected.GetProperty("whenWords").GetString(), found.WhenWords);
            Assert.Equal(expected.GetProperty("spokenTime").GetString(), Reminders.SpokenTime(found.Due, now, zone));
        }
        foreach (var s in v.GetProperty("spokenTimes").EnumerateArray())
            Assert.Equal(s.GetProperty("text").GetString(), Reminders.SpokenTime(now + s.GetProperty("dueOffsetS").GetDouble(), now, zone));
        foreach (var n in v.GetProperty("notes").EnumerateArray())
        {
            var kind = Enum.Parse<ReminderKind>(n.GetProperty("kind").GetString()!, ignoreCase: true);
            Assert.Equal(n.GetProperty("text").GetString(), Reminders.Note(new ReminderRequest(kind), n.GetProperty("when").GetString(), n.GetProperty("cancelled").GetInt32()));
        }
        foreach (var d in v.GetProperty("dueLines").EnumerateArray())
            Assert.Equal(d.GetProperty("text").GetString(), Reminders.DueNote(d.GetProperty("said").GetString()!, d.GetProperty("askedAt").GetString()!,
                d.GetProperty("dueAt").GetString()!, d.GetProperty("lateS").GetDouble(), d.GetProperty("promised").GetString()!));
    }

    [Fact]
    public void The_book_sets_cancels_claims_and_lets_go_as_MOSAIC_does()
    {
        var zone = TimeZoneInfo.FindSystemTimeZoneById("Asia/Seoul");
        var now = Vectors().GetProperty("now").GetProperty("epoch").GetDouble();
        var book = new ReminderBook();
        var (notes, set) = book.Read("chat-1", "十分钟后提醒我喝水", now, zone);
        Assert.StartsWith("The app has scheduled a reminder: at 今天 10:10", Assert.Single(notes), StringComparison.Ordinal);
        Assert.NotNull(set);
        book.Promise(set.Id, "好的，十分钟后提醒你喝水。");
        Assert.Empty(book.Read("chat-1", "今天天气不错", now, zone).Notes);
        Assert.Contains("今天 10:10: \"十分钟后提醒我喝水\"", Assert.Single(book.Read("chat-1", "你要提醒我什么来着", now, zone).Notes), StringComparison.Ordinal);
        Assert.Contains("no pending reminder", Assert.Single(book.Read("chat-2", "有什么提醒", now, zone).Notes), StringComparison.Ordinal);
        Assert.StartsWith("They ask you to remind them, but without a time", Assert.Single(book.Read("chat-1", "一会儿提醒我", now, zone).Notes), StringComparison.Ordinal);

        Assert.Null(book.ClaimDue(now + 599));
        Assert.Null(book.ClaimDue(now + 600, c => c == "chat-2")); // due, but not in the conversations asked about
        var due = book.ClaimDue(now + 600)!;
        Assert.Equal((set.Id, "claimed", "好的，十分钟后提醒你喝水。"), (due.Id, due.Status, due.Promised));
        Assert.Null(book.ClaimDue(now + 601)); // only one caller says it
        book.Release(due.Id);
        Assert.Equal(set.Id, book.ClaimDue(now + 602)!.Id); // a failed line is due again
        Assert.Null(book.ClaimDue(now + 603));
        Assert.Equal(set.Id, book.ClaimDue(now + 602 + Reminders.ClaimS + 1)!.Id); // a stale claim is let go
        book.Done(set.Id);
        Assert.Null(book.ClaimDue(now + 3600));
        Assert.Equal("done", book.All.Single(r => r.Id == set.Id).Status);

        var (_, late) = book.Read("chat-1", "半小时后叫我", now, zone);
        Assert.Null(book.ClaimDue(now + 1800 + Reminders.LateS + 1)); // the app was not running then: missed, not said late
        Assert.Equal("missed", book.All.Single(r => r.Id == late!.Id).Status);

        book.Read("chat-1", "下午3点半提醒我开会", now, zone);
        book.Read("chat-1", "明天早上八点叫醒我", now, zone);
        book.Read("chat-2", "九点提醒我", now, zone);
        Assert.Equal("The app has cancelled their pending reminders (2). Tell them in a few words that you will not remind them.",
            Assert.Single(book.Read("chat-1", "取消提醒", now, zone).Notes));
        Assert.Single(book.Pending("chat-2")); // another conversation's reminder stays
        Assert.Equal("There was no pending reminder to cancel. Tell them so in a few words.", Assert.Single(book.Read("chat-1", "不用提醒了", now, zone).Notes));
    }

    [Fact]
    public async Task Her_due_line_is_stored_alone_with_the_reminder_and_says_why_she_speaks()
    {
        var ct = TestContext.Current.CancellationToken;
        var llm = new FakeLlm();
        await using var host = await ServerTestHost.StartAsync(worker: false,
            services: s => s.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => llm));
        await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", new JsonObject
        {
            ["models"] = new JsonObject { ["aijade-chat"] = new JsonObject { ["upstream"] = "https://llm.example/v1", ["model"] = "m", ["keys"] = new JsonArray("k"), ["fluxPer1k"] = 0 } },
        }, ServerTestHost.AdminToken);
        var tokens = new MemoryTokenStore();
        await tokens.SetAsync(ServerTestHost.Token);
        var api = new AijadeApi(host.Client, tokens);
        var chat = await api.CreateChatAsync(null, "reminder", ct);
        var now = DateTimeOffset.UtcNow;
        var history = new List<StoredMessage>
        {
            new("u", 1, "user", "十分钟后提醒我喝水", now.AddSeconds(-600)),
            new("a", 2, "assistant", "好的，十分钟后提醒你喝水。", now.AddSeconds(-595)),
        };
        var epoch = now.ToUnixTimeMilliseconds() / 1000.0;
        var reminder = new Reminder("r1", chat.Id, epoch - 600, epoch, "十分钟后提醒我喝水", "claimed", epoch, "好的，十分钟后提醒你喝水。");

        var events = new List<OrchestratorEvent>();
        await foreach (var e in new ChatOrchestrator(api, [], new OrchestratorOptions()).RemindAsync(chat.Id, null, history, "snap-1", reminder, ct: ct))
            events.Add(e);

        Assert.IsType<TurnCompleted>(events[^1]);
        var stored = Assert.Single(await api.MessagesAsync(chat.Id, ct: ct));
        Assert.Equal(("assistant", "该喝水啦，这是你要的提醒。"), (stored.Role, stored.Content));
        Assert.True(Initiative.IsProactive(stored));
        var sent = JsonNode.Parse(llm.LastBody!)!["messages"]!.AsArray().Select(m => (m!["role"]!.GetValue<string>(), m["content"]!.GetValue<string>())).ToList();
        Assert.Equal(5, sent.Count); // persona, the exchange, the due note, the cue
        Assert.StartsWith("The time has come for a reminder they asked you for.", sent[3].Item2, StringComparison.Ordinal);
        Assert.Contains("\"十分钟后提醒我喝水\"", sent[3].Item2, StringComparison.Ordinal);
        Assert.Contains("Back then you answered \"好的，十分钟后提醒你喝水。\"", sent[3].Item2, StringComparison.Ordinal);
        Assert.Equal(("user", Reminders.DueCue), sent[4]);
    }

    [Fact]
    public async Task On_a_channel_she_keeps_a_reminder_asked_in_private_and_says_it_through_the_connector_when_due()
    {
        var ct = TestContext.Current.CancellationToken;
        var llm = new FakeLlm();
        await using var host = await ServerTestHost.StartAsync(worker: false,
            services: s => s.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => llm));
        await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", new JsonObject
        {
            ["models"] = new JsonObject { ["aijade-chat"] = new JsonObject { ["upstream"] = "https://llm.example/v1", ["model"] = "m", ["keys"] = new JsonArray("k"), ["fluxPer1k"] = 0 } },
        }, ServerTestHost.AdminToken);
        var tokens = new MemoryTokenStore();
        await tokens.SetAsync(ServerTestHost.Token);
        var api = new AijadeApi(host.Client, tokens);
        var time = new ManualTime(1_000_000);
        var state = Path.Combine(Path.GetTempPath(), $"aijade-reminders-{Guid.NewGuid():N}.json");
        BridgeOptions Options() => new() { StateFile = state, Time = time, Memory = false, ReminderPlatforms = ["qq"], TimeZone = TimeZoneInfo.FindSystemTimeZoneById("Asia/Seoul") };
        var qq = new RecordingConnector("qq");
        var reach = new Dictionary<string, IProactiveConnector> { ["qq"] = qq };
        bool NoteSent() => JsonNode.Parse(llm.LastBody!)!["messages"]!.AsArray().Any(m => m!["content"]!.GetValue<string>().StartsWith("The app has scheduled a reminder", StringComparison.Ordinal));
        var owner = new ChannelMessage("qq", "123456789", "123456789", "主人", "十分钟后提醒我喝水", IsDirect: true, AddressesBot: true);

        using (var bridge = new CompanionBridge(api, Options()))
        {
            Assert.NotNull(await bridge.AnswerAsync(owner, ct));
            Assert.True(NoteSent());
            // Where no connector can start a message, and in rooms, she sets none: she could not keep the promise.
            Assert.NotNull(await bridge.AnswerAsync(owner with { Platform = "discord" }, ct));
            Assert.False(NoteSent());
            Assert.NotNull(await bridge.AnswerAsync(owner with { ConversationId = "group-1", IsDirect = false }, ct));
            Assert.False(NoteSent());

            Assert.Equal(0, await ConnectorHost.RemindOnceAsync(bridge, reach, ct));
            time.Advance(TimeSpan.FromSeconds(600));
            Assert.Equal(1, await ConnectorHost.RemindOnceAsync(bridge, reach, ct));
            Assert.Equal([("123456789", "该喝水啦，这是你要的提醒。")], qq.Sent);
            Assert.Equal(0, await ConnectorHost.RemindOnceAsync(bridge, reach, ct)); // said once
            var chat = (await api.ChatsAsync(ct)).Single(c => c.Title == "qq · 主人");
            var line = (await api.MessagesAsync(chat.Id, ct: ct))[^1];
            Assert.True(Initiative.IsProactive(line));
            Assert.Contains("\"十分钟后提醒我喝水\"", JsonNode.Parse(llm.LastBody!)!["messages"]!.AsArray()[^2]!["content"]!.GetValue<string>(), StringComparison.Ordinal);

            Assert.NotNull(await bridge.AnswerAsync(owner with { Text = "二十分钟后提醒我开会" }, ct));
        }
        // Kept across a restart; a reminder whose line was made counts as said even if sending it failed (as in MOSAIC's bridge).
        using (var restarted = new CompanionBridge(api, Options()))
        {
            time.Advance(TimeSpan.FromSeconds(1200));
            await Assert.ThrowsAsync<HttpRequestException>(() => ConnectorHost.RemindOnceAsync(restarted, new Dictionary<string, IProactiveConnector> { ["qq"] = new RecordingConnector("qq", fail: true) }, ct));
            Assert.Equal(0, await ConnectorHost.RemindOnceAsync(restarted, reach, ct));
            Assert.Single(qq.Sent);

            // A conversation whose chat was deleted keeps its reminder: the next check says it in a new chat.
            Assert.NotNull(await restarted.AnswerAsync(owner with { Text = "五分钟后提醒我出门" }, ct));
            var old = (await api.ChatsAsync(ct)).Single(c => c.Title == "qq · 主人");
            await api.DeleteChatAsync(old.Id, ct);
            time.Advance(TimeSpan.FromSeconds(300));
            Assert.Equal(0, await ConnectorHost.RemindOnceAsync(restarted, reach, ct));
            Assert.Equal(1, await ConnectorHost.RemindOnceAsync(restarted, reach, ct));
            Assert.Equal(2, qq.Sent.Count);
            var renewed = (await api.ChatsAsync(ct)).Single(c => c.Title == "qq · 123456789");
            Assert.Equal("assistant", Assert.Single(await api.MessagesAsync(renewed.Id, ct: ct)).Role);
        }
        File.Delete(state);
        File.Delete(state + ".reminders.json");
    }

    private sealed class RecordingConnector(string platform, bool fail = false) : IProactiveConnector
    {
        public List<(string Conversation, string Text)> Sent { get; } = [];

        public string Platform => platform;

        public Task SendAsync(string conversationId, string text, CancellationToken ct)
        {
            if (fail)
                throw new HttpRequestException("unreachable");
            Sent.Add((conversationId, text));
            return Task.CompletedTask;
        }
    }

    private sealed class FakeLlm : HttpMessageHandler
    {
        public string? LastBody { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            LastBody = await request.Content!.ReadAsStringAsync(cancellationToken);
            const string sse = "data: {\"choices\":[{\"delta\":{\"content\":\"该喝水啦，这是你要的提醒。\"}}]}\n\n" +
                               "data: {\"choices\":[],\"usage\":{\"prompt_tokens\":10,\"completion_tokens\":5}}\n\ndata: [DONE]\n\n";
            return new HttpResponseMessage(System.Net.HttpStatusCode.OK) { Content = new StringContent(sse, System.Text.Encoding.UTF8, "text/event-stream") };
        }
    }
}
