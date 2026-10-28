using System.Net;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Bots;
using Aijade.Client.Api;
using Aijade.Client.Chat;
using Aijade.Client.Companion;
using Aijade.Integrations;
using Aijade.Server.Product;

using Microsoft.AspNetCore.Builder;
using Microsoft.Extensions.DependencyInjection;

namespace Aijade.Tests;

public class IntegrationTests
{
    private sealed class ChannelLlm : HttpMessageHandler
    {
        public List<JsonNode> Chats { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var body = JsonNode.Parse(await request.Content!.ReadAsStringAsync(cancellationToken))!;
            lock (Chats)
                Chats.Add(body);
            const string sse = "data: {\"choices\":[{\"delta\":{\"content\":\"[[emote:joy]]Hello there!\"}}]}\n\ndata: [DONE]\n\n";
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(sse, Encoding.UTF8, "text/event-stream") };
        }
    }

    private static string SystemPrompt(JsonNode chat) => chat["messages"]![0]!["content"]!.GetValue<string>();

    private static string LastUser(JsonNode chat) => chat["messages"]!.AsArray()[^1]!["content"]!.GetValue<string>();

    [Fact]
    public async Task The_bridge_answers_dms_and_mentions_keeps_one_chat_per_conversation_and_memory_per_person()
    {
        var ct = TestContext.Current.CancellationToken;
        var llm = new ChannelLlm();
        await using var host = await ServerTestHost.StartAsync(worker: false,
            services: s => s.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => llm));
        await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", new JsonObject
        {
            ["models"] = new JsonObject { ["aijade-chat"] = new JsonObject { ["upstream"] = "https://llm.example/v1", ["model"] = "m", ["keys"] = new JsonArray("k") } },
        }, ServerTestHost.AdminToken);
        var tokens = new MemoryTokenStore();
        await tokens.SetAsync(ServerTestHost.Token);
        var api = new AijadeApi(host.Client, tokens);
        var time = new ManualTime(1_000_000);
        var state = Path.Combine(Path.GetTempPath(), $"aijade-bridge-{Guid.NewGuid():N}.json");
        using var bridge = new CompanionBridge(api, new BridgeOptions { StateFile = state, Time = time });

        var aliceDm = new ChannelMessage("telegram", "100", "alice", "Alice", "My cat is called Mochi.", IsDirect: true, AddressesBot: false);
        var reply = await bridge.AnswerAsync(aliceDm, ct);
        Assert.Equal("Hello there!", reply!.Text);
        Assert.Equal(["joy"], reply.Expressions);
        Assert.Equal("My cat is called Mochi.", LastUser(llm.Chats[^1]));

        // A group room: chatter is ignored; a mention or the companion's name gets an answer, with the speaker named.
        var chatter = new ChannelMessage("discord", "room-1", "bob", "Bob", "anyone seen my keys?", false, false);
        Assert.Null(await bridge.AnswerAsync(chatter, ct));
        var mention = chatter with { Text = "what is my cat called?", AddressesBot = true };
        Assert.NotNull(await bridge.AnswerAsync(mention, ct));
        Assert.Equal("Bob: what is my cat called?", LastUser(llm.Chats[^1]));
        Assert.True(bridge.ShouldAnswer(chatter with { Text = "艾娅德, hello" }));
        // Rooms are rate-limited; a little later the companion speaks again.
        Assert.Null(await bridge.AnswerAsync(mention, ct));
        time.Advance(TimeSpan.FromSeconds(5));
        Assert.NotNull(await bridge.AnswerAsync(mention, ct));

        // Alice's memory reaches Alice's later turns, never Bob's.
        // Memories are recorded in the background after a turn; under a loaded test run that can take a few seconds.
        for (var i = 0; i < 150 && (await api.MemoryItemsAsync("Mochi", session: CompanionBridge.MemorySession(aliceDm), ct: ct)).Count == 0; i++)
            await Task.Delay(100, ct);
        Assert.NotEmpty(await api.MemoryItemsAsync("Mochi", session: CompanionBridge.MemorySession(aliceDm), ct: ct));
        var bobAsks = mention with { Text = "remind me, what is the cat called?" };
        time.Advance(TimeSpan.FromSeconds(5));
        await bridge.AnswerAsync(bobAsks, ct);
        Assert.DoesNotContain("Mochi", SystemPrompt(llm.Chats[^1]), StringComparison.Ordinal);
        // The bridge records Alice's question in the background while it recalls; on a loaded machine it is stored first and
        // matches itself. Store it up front so recall always has to see past that echo.
        await new ConversationRecorder(api, CompanionBridge.MemorySession(aliceDm), "test").RecordAsync("what is my cat called?", ct);
        await bridge.AnswerAsync(aliceDm with { Text = "what is my cat called?" }, ct);
        Assert.Contains("Mochi", SystemPrompt(llm.Chats[^1]), StringComparison.Ordinal);

        // One chat per conversation, kept across restarts through the state file.
        var chats = await api.ChatsAsync(ct);
        Assert.Equal(2, chats.Count);
        using var restarted = new CompanionBridge(api, new BridgeOptions { StateFile = state, Time = time });
        await restarted.AnswerAsync(aliceDm, ct);
        Assert.Equal(2, (await api.ChatsAsync(ct)).Count);
        Assert.Equal(3, (await api.MessagesAsync(chats.Single(c => c.Title.StartsWith("telegram", StringComparison.Ordinal)).Id, ct: ct)).Count(m => m.Role == "user"));
        File.Delete(state);
    }

    [Fact]
    public async Task On_a_text_channel_she_is_told_she_has_no_body_and_a_promised_movement_is_put_off()
    {
        var ct = TestContext.Current.CancellationToken;
        var llm = new ChannelLlm();
        await using var host = await ServerTestHost.StartAsync(worker: false,
            services: s => s.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => llm));
        await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", new JsonObject
        {
            ["models"] = new JsonObject { ["aijade-chat"] = new JsonObject { ["upstream"] = "https://llm.example/v1", ["model"] = "m", ["keys"] = new JsonArray("k") } },
        }, ServerTestHost.AdminToken);
        var tokens = new MemoryTokenStore();
        await tokens.SetAsync(ServerTestHost.Token);
        var api = new AijadeApi(host.Client, tokens);
        using var bridge = new CompanionBridge(api, new BridgeOptions { Memory = false, Time = new ManualTime(1_000_000) });

        static List<(string Role, string Content)> Sent(JsonNode chat) =>
            [.. chat["messages"]!.AsArray().Select(m => (m!["role"]!.GetValue<string>(), m["content"]!.GetValue<string>()))];

        // Telegram: the channel note and, for a request to dance, the movement note go just before the message; the reply
        // "Hello there!" does not put the dance off, so the sentence that does is added to what is sent.
        var dance = new ChannelMessage("telegram", "200", "carol", "Carol", "你能跳个舞给我看吗", IsDirect: true, AddressesBot: false);
        var reply = await bridge.AnswerAsync(dance, ct);
        Assert.Equal("Hello there!" + TextChannel.Later, reply!.Text);
        var sent = Sent(llm.Chats[^1]);
        Assert.Equal(("system", TextChannel.ChannelNote("Telegram text messages")), sent[^3]);
        Assert.Equal(("system", TextChannel.MovementNote("Telegram")), sent[^2]);
        Assert.Equal(("user", "你能跳个舞给我看吗"), sent[^1]);
        // The stored reply is the model's own; only the sent text carries the added sentence.
        var chat = (await api.ChatsAsync(ct)).Single();
        Assert.Equal("Hello there!", (await api.MessagesAsync(chat.Id, ct: ct))[^1].Content);

        // Minecraft: she has an avatar there, so no note.
        await bridge.AnswerAsync(new ChannelMessage("minecraft", "mc", "dave", "dave", "跳个舞", IsDirect: true, AddressesBot: true), ct);
        Assert.DoesNotContain(Sent(llm.Chats[^1]).Skip(1), m => m.Role == "system");

        // The rules can be switched off.
        using var plain = new CompanionBridge(api, new BridgeOptions { Memory = false, TextChannelRules = false, Time = new ManualTime(1_000_000) });
        var unchanged = await plain.AnswerAsync(dance with { ConversationId = "201" }, ct);
        Assert.Equal("Hello there!", unchanged!.Text);
        Assert.DoesNotContain(Sent(llm.Chats[^1]).Skip(1), m => m.Role == "system");
    }

    [Fact]
    public void Platform_messages_map_to_channel_messages()
    {
        var me = new Telegram.Bot.Types.User { Id = 42, IsBot = true, FirstName = "Aijade", Username = "aijade_bot" };
        var group = new Telegram.Bot.Types.Chat { Id = -100, Type = Telegram.Bot.Types.Enums.ChatType.Supergroup };
        var from = new Telegram.Bot.Types.User { Id = 7, FirstName = "Ann", LastName = "Lee" };
        var mentioned = TelegramConnector.ToChannelMessage(new Telegram.Bot.Types.Message { Chat = group, From = from, Text = "@aijade_bot hi there" }, me)!;
        Assert.Equal(("telegram", "-100", "7", "Ann Lee", "hi there", false, true), (mentioned.Platform, mentioned.ConversationId, mentioned.AuthorId, mentioned.AuthorName, mentioned.Text, mentioned.IsDirect, mentioned.AddressesBot));
        var reply = TelegramConnector.ToChannelMessage(new Telegram.Bot.Types.Message { Chat = group, From = from, Text = "ok", ReplyToMessage = new Telegram.Bot.Types.Message { From = me, Chat = group } }, me)!;
        Assert.True(reply.AddressesBot);
        var dm = TelegramConnector.ToChannelMessage(new Telegram.Bot.Types.Message { Chat = new Telegram.Bot.Types.Chat { Id = 7, Type = Telegram.Bot.Types.Enums.ChatType.Private }, From = from, Text = "hey" }, me)!;
        Assert.True(dm.IsDirect);
        Assert.Null(TelegramConnector.ToChannelMessage(new Telegram.Bot.Types.Message { Chat = group, From = new Telegram.Bot.Types.User { Id = 9, IsBot = true, FirstName = "x" }, Text = "spam" }, me));

        var d = DiscordConnector.ToChannelMessage("<@42> hello", 7, "Ann", false, false, 555, [42], null, 42)!;
        Assert.Equal(("discord", "555", "hello", true, false), (d.Platform, d.ConversationId, d.Text, d.AddressesBot, d.IsDirect));
        Assert.True(DiscordConnector.ToChannelMessage("thanks", 7, "Ann", false, false, 555, [], 42, 42)!.AddressesBot);
        Assert.Null(DiscordConnector.ToChannelMessage("echo", 42, "me", true, false, 555, [], null, 42));
        Assert.Null(DiscordConnector.ToChannelMessage("<@42>", 7, "Ann", false, false, 555, [42], null, 42));
    }

    [Fact]
    public void Long_replies_split_at_natural_breaks_within_the_platform_limit()
    {
        var text = string.Join(" ", Enumerable.Repeat("This is one sentence.", 300));
        var parts = ChannelText.Split(text, 2000);
        Assert.All(parts, p => Assert.InRange(p.Length, 1, 2000));
        Assert.All(parts, p => Assert.EndsWith(".", p, StringComparison.Ordinal));
        Assert.Equal(text.Replace(" ", "", StringComparison.Ordinal), string.Concat(parts).Replace(" ", "", StringComparison.Ordinal));
        Assert.Equal(["short"], ChannelText.Split("  short  ", 2000));
        Assert.Equal(3, ChannelText.Split(new string('x', 5000), 2000).Count);
    }

    [Fact]
    public void Satori_and_x_events_map_to_channel_messages()
    {
        var group = JsonNode.Parse("""
            {"type":"message-created","platform":"qq","self_id":"bot1","channel":{"id":"g42","type":0},"user":{"id":"u7","name":"Ann"},
             "member":{"nick":"Annie"},"message":{"id":"m1","content":"<at id=\"bot1\"/> what &amp; why?"}}
            """)!.AsObject();
        var (m, platform, self, channel) = SatoriConnector.ToChannelMessage(group)!.Value;
        Assert.Equal(("satori-qq", "g42", "u7", "Annie", "what & why?", false, true), (m.Platform, m.ConversationId, m.AuthorId, m.AuthorName, m.Text, m.IsDirect, m.AddressesBot));
        Assert.Equal(("qq", "bot1", "g42"), (platform, self, channel));
        group["channel"]!["type"] = 1;
        group["message"]!["content"] = "hi <at id=\"someone\"/>";
        var dm = SatoriConnector.ToChannelMessage(group)!.Value.Message;
        Assert.True(dm.IsDirect);
        Assert.Equal("hi @someone", dm.Text);
        group["user"]!["id"] = "bot1";
        Assert.Null(SatoriConnector.ToChannelMessage(group)); // its own message

        var page = JsonNode.Parse("""
            {"data":[{"id":"t2","text":"@aijade how are you &lt;3","author_id":"a1","conversation_id":"c1"},
                     {"id":"t1","text":"@aijade first","author_id":"a2","conversation_id":"t1"},
                     {"id":"t0","text":"@aijade me","author_id":"self"}],
             "includes":{"users":[{"id":"a1","name":"Ann","username":"ann"},{"id":"a2","name":"Bo","username":"bo"}]}}
            """);
        var mentions = XConnector.ToChannelMessages(page, "self", "aijade");
        Assert.Equal(["t1", "t2"], mentions.Select(x => x.TweetId)); // oldest first, own tweets skipped
        Assert.Equal(("x", "c1", "Ann", "how are you <3", true), (mentions[1].Message.Platform, mentions[1].Message.ConversationId, mentions[1].Message.AuthorName, mentions[1].Message.Text, mentions[1].Message.AddressesBot));
    }

    [Fact]
    public async Task A_satori_server_delivers_events_and_receives_replies()
    {
        var ct = TestContext.Current.CancellationToken;
        var sent = new List<(string? Auth, string? Platform, string Body)>();
        var identified = new TaskCompletionSource<string>();
        var b = Microsoft.AspNetCore.Builder.WebApplication.CreateSlimBuilder();
        Microsoft.AspNetCore.Hosting.HostingAbstractionsWebHostBuilderExtensions.UseUrls(b.WebHost, "http://127.0.0.1:0");
        await using var satori = b.Build();
        satori.UseWebSockets();
        satori.Map("/satori/v1/events", async (Microsoft.AspNetCore.Http.HttpContext c) =>
        {
            using var ws = await c.WebSockets.AcceptWebSocketAsync();
            var buffer = new byte[4096];
            var r = await ws.ReceiveAsync(buffer, ct);
            identified.TrySetResult(Encoding.UTF8.GetString(buffer, 0, r.Count));
            async Task Send(string json) => await ws.SendAsync(Encoding.UTF8.GetBytes(json), System.Net.WebSockets.WebSocketMessageType.Text, true, ct);
            await Send("""{"op":4,"body":{"logins":[]}}""");
            await Send("""{"op":0,"body":{"type":"message-created","platform":"kook","self_id":"bot","channel":{"id":"room","type":0},"user":{"id":"u1","name":"Kai"},"message":{"id":"1","content":"just chatting"}}}""");
            await Send("""{"op":0,"body":{"type":"message-created","platform":"kook","self_id":"bot","channel":{"id":"room","type":0},"user":{"id":"u1","name":"Kai"},"message":{"id":"2","content":"<at id=\"bot\"/> hello"}}}""");
            while (!ct.IsCancellationRequested && ws.State == System.Net.WebSockets.WebSocketState.Open)
                await Task.Delay(50, ct);
        });
        satori.MapPost("/satori/v1/message.create", async (Microsoft.AspNetCore.Http.HttpContext c) =>
        {
            using var reader = new StreamReader(c.Request.Body);
            var body = await reader.ReadToEndAsync(ct);
            lock (sent)
                sent.Add((c.Request.Headers.Authorization.ToString(), c.Request.Headers["Satori-Platform"].ToString(), body));
            return Microsoft.AspNetCore.Http.Results.Json(new JsonArray());
        });
        await satori.StartAsync(ct);
        var url = new Uri(satori.Urls.First() + "/satori/");
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        var seen = new List<ChannelMessage>();
        var run = new SatoriConnector(url, "satori-token", new HttpClient()).RunAsync((m, _) =>
        {
            lock (seen)
                seen.Add(m);
            return Task.FromResult<ChannelReply?>(m.AddressesBot ? new ChannelReply("Hi <Kai> & all", []) : null);
        }, cts.Token);
        Assert.Contains("\"token\":\"satori-token\"", await identified.Task.WaitAsync(TimeSpan.FromSeconds(10), ct), StringComparison.Ordinal);
        for (var i = 0; i < 100 && sent.Count == 0; i++)
            await Task.Delay(50, ct);
        var reply = Assert.Single(sent);
        Assert.Equal(("Bearer satori-token", "kook"), (reply.Auth, reply.Platform));
        Assert.Equal("Hi &lt;Kai&gt; &amp; all", JsonNode.Parse(reply.Body)!["content"]!.GetValue<string>()); // text, never markup
        Assert.Equal(2, seen.Count);
        await cts.CancelAsync();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => run);
    }

    [Fact]
    public void Bilibili_live_frames_decode_plain_zlib_and_brotli_batches_into_danmaku()
    {
        static byte[] Compress(byte[] raw, bool brotli)
        {
            using var output = new MemoryStream();
            using (Stream s = brotli ? new System.IO.Compression.BrotliStream(output, System.IO.Compression.CompressionLevel.Fastest)
                                     : new System.IO.Compression.ZLibStream(output, System.IO.Compression.CompressionLevel.Fastest))
                s.Write(raw);
            return output.ToArray();
        }
        static byte[] Wrap(byte[] body, short version)
        {
            var packet = new byte[16 + body.Length];
            System.Buffers.Binary.BinaryPrimitives.WriteInt32BigEndian(packet, packet.Length);
            System.Buffers.Binary.BinaryPrimitives.WriteInt16BigEndian(packet.AsSpan(4), 16);
            System.Buffers.Binary.BinaryPrimitives.WriteInt16BigEndian(packet.AsSpan(6), version);
            System.Buffers.Binary.BinaryPrimitives.WriteInt32BigEndian(packet.AsSpan(8), BilibiliLiveConnector.OpMessage);
            body.CopyTo(packet, 16);
            return packet;
        }
        var danmaku = BilibiliLiveConnector.Encode(BilibiliLiveConnector.OpMessage, """{"cmd":"DANMU_MSG","info":[[0],"主播晚上好",[123,"小明"]]}""", 0);
        var gift = BilibiliLiveConnector.Encode(BilibiliLiveConnector.OpMessage, """{"cmd":"SEND_GIFT","data":{}}""", 0);
        var batch = danmaku.Concat(gift).ToArray();
        foreach (var frame in new[] { batch, Wrap(Compress(batch, brotli: false), 2), Wrap(Compress(batch, brotli: true), 3) })
        {
            var packets = BilibiliLiveConnector.Decode(frame).ToList();
            Assert.Equal(2, packets.Count);
            var messages = packets.Select(p => BilibiliLiveConnector.ToChannelMessage(JsonNode.Parse(p.Body), 42)).OfType<ChannelMessage>().ToList();
            var m = Assert.Single(messages);
            Assert.Equal(("bilibili", "42", "123", "小明", "主播晚上好", true), (m.Platform, m.ConversationId, m.AuthorId, m.AuthorName, m.Text, m.AddressesBot));
        }
        var auth = BilibiliLiveConnector.Encode(BilibiliLiveConnector.OpAuth, "{\"roomid\":42}");
        Assert.Equal((BilibiliLiveConnector.OpAuth, "{\"roomid\":42}"), BilibiliLiveConnector.Decode(auth).Select(p => (p.Operation, Encoding.UTF8.GetString(p.Body))).Single());
        Assert.Empty(BilibiliLiveConnector.Decode(auth[..10])); // a truncated frame yields nothing, never garbage
    }
}
