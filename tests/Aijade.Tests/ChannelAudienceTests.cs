using System.Net;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Bots;
using Aijade.Client.Api;
using Aijade.Client.Chat;
using Aijade.Client.Companion;
using Aijade.Integrations;
using Aijade.Server.Product;

using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace Aijade.Tests;

/// <summary>Audience boundaries are checked through real chat, memory and durable notebook storage.</summary>
public sealed class ChannelAudienceTests
{
    [Fact]
    public async Task A_group_cannot_recall_private_or_other_room_memory_or_reuse_a_private_chat_with_the_same_id()
    {
        var ct = TestContext.Current.CancellationToken;
        var model = new Model();
        await using var host = await StartAsync(model);
        var api = await ApiAsync(host);
        var stateFile = Path.Combine(Path.GetTempPath(), "aijade-audience-" + Guid.NewGuid().ToString("N") + ".json");
        var direct = new ChannelMessage("qq", "9001", "alice", "Alice", "cat", true, true);
        // Existing private state must remain readable, but its numeric id can also be a legitimate QQ group id.
        var legacyChat = await api.CreateChatAsync(null, "Legacy private chat", ct);
        await api.AppendMessageAsync(legacyChat.Id, "user", "My private cat is Mochi.", ct: ct);
        await File.WriteAllTextAsync(stateFile, JsonSerializer.Serialize(new Dictionary<string, string> { ["qq:9001"] = legacyChat.Id }), ct);
        await new ConversationRecorder(api, "bot:qq:alice", "test").RecordAsync("My private cat is Mochi.", ct);
        try
        {
            using var bridge = new CompanionBridge(api, new BridgeOptions { StateFile = stateFile, MinInterval = TimeSpan.Zero });
            var group = direct with { IsDirect = false };
            Assert.NotNull(await bridge.AnswerAsync(group, ct));
            Assert.DoesNotContain("Mochi", model.Chats[^1].ToJsonString(), StringComparison.Ordinal);
            Assert.Equal(2, (await api.ChatsAsync(ct)).Count);

            Assert.NotNull(await bridge.AnswerAsync(direct, ct));
            Assert.Contains("Mochi", Prompt(model.Chats[^1]), StringComparison.Ordinal);
            Assert.Equal(2, (await api.ChatsAsync(ct)).Count); // old private mapping is reused

            await new ConversationRecorder(api, CompanionBridge.MemorySession(group), "test").RecordAsync("Our group cat is Nori.", ct);
            Assert.NotNull(await bridge.AnswerAsync(group, ct));
            Assert.Contains("Nori", Prompt(model.Chats[^1]), StringComparison.Ordinal);
            Assert.DoesNotContain("Mochi", Prompt(model.Chats[^1]), StringComparison.Ordinal);

            Assert.NotNull(await bridge.AnswerAsync(group with { ConversationId = "another-room" }, ct));
            Assert.DoesNotContain("Nori", Prompt(model.Chats[^1]), StringComparison.Ordinal);
            Assert.DoesNotContain("Mochi", Prompt(model.Chats[^1]), StringComparison.Ordinal);
            Assert.NotNull(await bridge.AnswerAsync(group with { AuthorId = "bob", AuthorName = "Bob" }, ct));
            Assert.DoesNotContain("Nori", Prompt(model.Chats[^1]), StringComparison.Ordinal);

            using var restarted = new CompanionBridge(api, new BridgeOptions { StateFile = stateFile, MinInterval = TimeSpan.Zero });
            var count = (await api.ChatsAsync(ct)).Count;
            Assert.NotNull(await restarted.AnswerAsync(group, ct));
            Assert.Contains("Nori", Prompt(model.Chats[^1]), StringComparison.Ordinal);
            Assert.DoesNotContain("Mochi", model.Chats[^1].ToJsonString(), StringComparison.Ordinal);
            Assert.Equal(count, (await api.ChatsAsync(ct)).Count);
        }
        finally { File.Delete(stateFile); }
    }

    [Theory]
    [InlineData("room-a", "alice", "room-b", "alice")]
    [InlineData("room-a", "alice", "room-a", "bob")]
    [InlineData("room:a", "b", "room", "a:b")]
    public async Task Group_notebooks_keep_private_collections_and_relationships_separate_across_restarts(string room, string author, string otherRoom, string otherAuthor)
    {
        var ct = TestContext.Current.CancellationToken;
        using var http = new HttpClient { BaseAddress = new Uri("https://not-called.example/") };
        var api = new AijadeApi(http, new MemoryTokenStore());
        var directory = Path.Combine(Path.GetTempPath(), "aijade-notebook-audience-" + Guid.NewGuid().ToString("N"));
        var state = Path.Combine(directory, "bridge.json");
        var config = new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?> { ["Bridge:StateFile"] = state }).Build();
        var message = new ChannelMessage("qq", room, author, "Alice", "hello", true, true);
        const string image = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jWQ0AAAAASUVORK5CYII=";
        try
        {
            var settings = new CompanionConfiguration(config, api);
            var privateBook = settings.For(message).Notebook;
            await privateBook.AddAsync(new("private", "sticker", "Private collection", image), ct);
            var group = message with { IsDirect = false };
            var groupBook = settings.For(group).Notebook;
            Assert.Empty((await groupBook.ReadAsync(ct: ct)).Assets);
            await groupBook.AddAsync(new("group", "sticker", "Group collection", image), ct);
            await groupBook.ObserveAsync(new("group-chat", null, [], "谢谢你") { UserMessageId = "group-message" }, DateTimeOffset.UtcNow, ct);
            var other = settings.For(group with { ConversationId = otherRoom, AuthorId = otherAuthor }).Notebook;
            Assert.Empty((await other.ReadAsync(ct: ct)).Assets);
            Assert.Equal(0, (await privateBook.ReadAsync(ct: ct)).Relationship.Interactions);
            Assert.Equal(0, (await other.ReadAsync(ct: ct)).Relationship.Interactions);
            Assert.Single((await privateBook.ReadAsync(ct: ct)).Assets, a => a.Id == "private");

            var restarted = new CompanionConfiguration(config, api);
            var restored = await restarted.For(group).Notebook.ReadAsync(ct: ct);
            Assert.Equal("group", Assert.Single(restored.Assets).Id);
            Assert.Equal(1, restored.Relationship.Interactions);
            Assert.Equal("private", Assert.Single((await restarted.For(message).Notebook.ReadAsync(ct: ct)).Assets).Id);
            Assert.Null(await restarted.ForAsync(group, ct)); // group messages do not borrow a private pairing grant
        }
        finally { if (Directory.Exists(directory)) Directory.Delete(directory, recursive: true); }
    }

    [Fact]
    public async Task Concurrent_group_events_share_a_rate_limit_while_another_room_can_answer()
    {
        var ct = TestContext.Current.CancellationToken;
        var model = new Model { HoldFirst = true };
        await using var host = await StartAsync(model);
        var time = new Clock();
        using var bridge = new CompanionBridge(await ApiAsync(host), new BridgeOptions { Memory = false, Time = time });
        var group = new ChannelMessage("qq", "group-a", "alice", "Alice", "hello", false, true);
        var first = bridge.AnswerAsync(group, ct);
        try
        {
            await model.Entered.Task.WaitAsync(TimeSpan.FromSeconds(10), ct);
            // The first model call outlasts the interval. Multiple new events can now pass the outer check and queue.
            time.Advance(TimeSpan.FromSeconds(4));
            var queued = bridge.AnswerAsync(group with { AuthorId = "bob", AuthorName = "Bob" }, ct);
            var alsoQueued = bridge.AnswerAsync(group with { AuthorId = "carol", AuthorName = "Carol" }, ct);
            Assert.NotNull(await bridge.AnswerAsync(group with { ConversationId = "group-b" }, ct));
            model.Release.TrySetResult();
            Assert.NotNull(await first);
            Assert.Single(await Task.WhenAll(queued, alsoQueued), reply => reply is not null);
            Assert.Equal(3, model.Chats.Count);
            time.Advance(TimeSpan.FromSeconds(4));
            Assert.NotNull(await bridge.AnswerAsync(group, ct));
            Assert.Equal(4, model.Chats.Count);
        }
        finally { model.Release.TrySetResult(); await first; }
    }

    private static async Task<ServerTestHost> StartAsync(Model model)
    {
        var host = await ServerTestHost.StartAsync(worker: false,
            services: s => s.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => model));
        await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", new JsonObject
        {
            ["models"] = new JsonObject { ["aijade-chat"] = new JsonObject { ["upstream"] = "https://llm.example/v1", ["model"] = "m", ["keys"] = new JsonArray("k") } },
        }, ServerTestHost.AdminToken);
        return host;
    }

    private static async Task<AijadeApi> ApiAsync(ServerTestHost host)
    {
        var tokens = new MemoryTokenStore(); await tokens.SetAsync(ServerTestHost.Token);
        return new(host.Client, tokens);
    }

    private static string Prompt(JsonNode chat) => chat["messages"]![0]!["content"]!.GetValue<string>();

    private sealed class Clock : TimeProvider
    {
        private DateTimeOffset now = DateTimeOffset.FromUnixTimeSeconds(1_000_000);
        public override DateTimeOffset GetUtcNow() => now;
        public void Advance(TimeSpan by) => now += by;
    }

    private sealed class Model : HttpMessageHandler
    {
        public List<JsonNode> Chats { get; } = [];
        public bool HoldFirst { get; init; }
        public TaskCompletionSource Entered { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);
        public TaskCompletionSource Release { get; } = new(TaskCreationOptions.RunContinuationsAsynchronously);

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var body = JsonNode.Parse(await request.Content!.ReadAsStringAsync(cancellationToken))!;
            bool hold;
            lock (Chats) { Chats.Add(body); hold = HoldFirst && Chats.Count == 1; }
            if (hold) { Entered.TrySetResult(); await Release.Task.WaitAsync(cancellationToken); }
            const string sse = "data: {\"choices\":[{\"delta\":{\"content\":\"Hello there!\"}}]}\n\ndata: [DONE]\n\n";
            return new(HttpStatusCode.OK) { Content = new StringContent(sse, Encoding.UTF8, "text/event-stream") };
        }
    }
}
