using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Client.Companion;
using Aijade.Client.Settings;
using Aijade.Integrations;

namespace Aijade.Tests;

/// <summary>
/// QQ through OneBot 11 and NapCat (ADR-003, migration batch 1), as MOSAIC's tools/companion_qq.py (r601): signed event posts,
/// only the owner's private text messages answered, replies sent with send_private_msg and a bearer token.
/// </summary>
public class OneBotConnectorTests
{
    private const string Secret = "event-secret-0123456789";
    private const string Token = "napcat-token-0123456789";
    private const string Owner = "123456789";

#pragma warning disable CA5350 // the protocol's algorithm
    private static string Sign(byte[] body) => "sha1=" + Convert.ToHexStringLower(HMACSHA1.HashData(Encoding.UTF8.GetBytes(Secret), body));
#pragma warning restore CA5350

    private static JsonObject Private(string userId, JsonNode message) => new()
    {
        ["post_type"] = "message", ["message_type"] = "private", ["sub_type"] = "friend", ["user_id"] = long.Parse(userId, System.Globalization.CultureInfo.InvariantCulture),
        ["self_id"] = 42, ["message"] = message, ["sender"] = new JsonObject { ["nickname"] = "主人" },
    };

    private static JsonArray Segments(params (string Type, string Text)[] parts) =>
        new([.. parts.Select(p => (JsonNode)new JsonObject { ["type"] = p.Type, ["data"] = p.Type == "text" ? new JsonObject { ["text"] = p.Text } : new JsonObject { ["file"] = p.Text } })]);

    /// <summary>NapCat's HTTP server: records each action and answers ok; get_record gives a voice message as base64 WAV.</summary>
    private sealed class FakeNapCat : HttpMessageHandler
    {
        public static readonly byte[] Voice = [.. "RIFF"u8, 36, 0, 0, 0, .. "WAVEfmt "u8, 16, 0, 0, 0, 1, 0, 1, 0, 0x80, 0x3E, 0, 0, 0, 0x7D, 0, 0, 2, 0, 16, 0, .. "data"u8, 0, 0, 0, 0];

        public List<(string Action, string? Auth, JsonObject Body)> Calls { get; } = [];
        public int ImageReads { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            if (request.Method == HttpMethod.Get)
            {
                ImageReads++;
                Assert.Null(request.Headers.Authorization);
                return new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(Convert.FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jWQ0AAAAASUVORK5CYII=")) { Headers = { ContentType = new("image/png") } } };
            }
            var body = (JsonObject)JsonNode.Parse(await request.Content!.ReadAsStringAsync(cancellationToken))!;
            var action = request.RequestUri!.AbsolutePath.TrimStart('/');
            lock (Calls)
                Calls.Add((action, request.Headers.Authorization?.Parameter, body));
            var data = action == "get_record" ? new JsonObject { ["file"] = "voice.wav", ["base64"] = Convert.ToBase64String(Voice) } : new JsonObject { ["message_id"] = 7 };
            var answer = new JsonObject { ["status"] = "ok", ["retcode"] = 0, ["data"] = data };
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(answer.ToJsonString(), Encoding.UTF8, "application/json") };
        }
    }

    /// <summary>A started connector on a free loopback port, a way to post signed events to it, and what its handler received.</summary>
    private static (Task Run, Func<JsonObject, Task<HttpStatusCode>> Post, List<ChannelMessage> Received, HttpClient Client) Start(OneBotConnector connector, int port, CancellationToken ct)
    {
        var received = new List<ChannelMessage>();
        var run = connector.RunAsync((m, _) =>
        {
            lock (received)
                received.Add(m);
            return Task.FromResult<ChannelReply?>(new ChannelReply("在呢，" + m.Text, []));
        }, ct);
        var client = new HttpClient { BaseAddress = new Uri($"http://127.0.0.1:{port}/") };
        async Task<HttpStatusCode> PostAsync(JsonObject evt)
        {
            var body = Encoding.UTF8.GetBytes(evt.ToJsonString());
            for (var attempt = 0; ; attempt++)
            {
                try
                {
                    using var content = new ByteArrayContent(body);
                    content.Headers.ContentType = new("application/json");
                    using var req = new HttpRequestMessage(HttpMethod.Post, "") { Content = content };
                    req.Headers.Add("X-Signature", Sign(body));
                    using var res = await client.SendAsync(req, ct);
                    return res.StatusCode;
                }
                catch (HttpRequestException) when (attempt < 50)
                {
                    await Task.Delay(100, ct); // the listener is still starting
                }
            }
        }
        return (run, PostAsync, received, client);
    }

    [Fact]
    public void A_message_is_read_as_MOSAICs_bridge_reads_it()
    {
        var m = OneBotConnector.ReadOwnerMessage(Private(Owner, Segments(("text", "听听"), ("record", "a.amr"), ("image", "p.jpg"), ("text", "这个"), ("face", "1"))), Owner)!;
        Assert.Equal(("听听这个", 2, "主人"), (m.Text, m.Other, m.Name));
        Assert.Equal(["a.amr"], m.Voices);
        Assert.Equal(("你好", 0), (OneBotConnector.ReadOwnerMessage(Private(Owner, "  你好 "), Owner)!.Text, OneBotConnector.ReadOwnerMessage(Private(Owner, "你好"), Owner)!.Voices.Count));
        Assert.Null(OneBotConnector.ReadOwnerMessage(Private("987654321", "你好"), Owner));
    }

    [Fact]
    public async Task Voice_messages_are_heard_and_a_message_without_words_gets_MOSAICs_fixed_line()
    {
        var ct = TestContext.Current.CancellationToken;
        var napcat = new FakeNapCat();
        var transcribed = new List<byte[]>();
        var port = FreePort();
        var connector = new OneBotConnector(port, new Uri("http://127.0.0.1:3000"), Token, Secret, Owner, new HttpClient(napcat), (wav, _) =>
        {
            lock (transcribed)
                transcribed.Add(wav);
            return Task.FromResult("我回来了");
        });
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        var (run, post, received, client) = Start(connector, port, cts.Token);
        using (client)
        {
            async Task WaitSentAsync(int count)
            {
                for (var i = 0; i < 100 && napcat.Calls.Count(c => c.Action == "send_private_msg") < count; i++)
                    await Task.Delay(50, ct);
            }
            string Last() => napcat.Calls.Last(c => c.Action == "send_private_msg").Body["message"]![0]!["data"]!["text"]!.GetValue<string>();

            // A voice message alone: fetched as WAV, transcribed, answered.
            Assert.Equal(HttpStatusCode.NoContent, await post(Private(Owner, Segments(("record", "v1.amr")))));
            await WaitSentAsync(1);
            var fetch = napcat.Calls.Single(c => c.Action == "get_record");
            Assert.Equal(("v1.amr", "wav", Token), (fetch.Body["file"]!.GetValue<string>(), fetch.Body["out_format"]!.GetValue<string>(), fetch.Auth));
            Assert.Equal(FakeNapCat.Voice, Assert.Single(transcribed));
            Assert.Equal(["我回来了"], received.Select(m => m.Text));
            Assert.Equal("在呢，我回来了", Last());

            // Words and a voice message: the words first, then what was heard.
            Assert.Equal(HttpStatusCode.NoContent, await post(Private(Owner, Segments(("text", "你听"), ("record", "v2.amr")))));
            await WaitSentAsync(2);
            Assert.Equal("你听 我回来了", received[^1].Text);

            // A picture alone: MOSAIC's fixed line, without the model.
            Assert.Equal(HttpStatusCode.NoContent, await post(Private(Owner, Segments(("image", "p.jpg")))));
            await WaitSentAsync(3);
            Assert.Equal(OneBotConnector.OnlyTextReply, Last());
            Assert.Equal(2, received.Count);
            var health = JsonNode.Parse(await client.GetStringAsync("health", ct))!;
            Assert.Equal((3, 3, 2), (health["messages"]!.GetValue<int>(), health["answered"]!.GetValue<int>(), health["voicesHeard"]!.GetValue<int>()));
        }
        await cts.CancelAsync();
        await run;

        // Without a transcriber a voice message has no words either.
        var quiet = new FakeNapCat();
        var port2 = FreePort();
        using var cts2 = CancellationTokenSource.CreateLinkedTokenSource(ct);
        var (run2, post2, received2, client2) = Start(new OneBotConnector(port2, new Uri("http://127.0.0.1:3000"), Token, Secret, Owner, new HttpClient(quiet)), port2, cts2.Token);
        using (client2)
        {
            Assert.Equal(HttpStatusCode.NoContent, await post2(Private(Owner, Segments(("record", "v3.amr")))));
            for (var i = 0; i < 100 && quiet.Calls.Count == 0; i++)
                await Task.Delay(50, ct);
            Assert.Equal(OneBotConnector.OnlyTextReply, Assert.Single(quiet.Calls).Body["message"]![0]!["data"]!["text"]!.GetValue<string>());
            Assert.Empty(received2);
        }
        await cts2.CancelAsync();
        await run2;
    }

    [Fact]
    public async Task A_step_that_times_out_costs_only_its_own_message()
    {
        var ct = TestContext.Current.CancellationToken;
        var napcat = new FakeNapCat();
        var port = FreePort();
        var calls = 0;
        // The first recognition times out the way HttpClient reports a timeout: a TaskCanceledException nobody asked for.
        var connector = new OneBotConnector(port, new Uri("http://127.0.0.1:3000"), Token, Secret, Owner, new HttpClient(napcat), (_, _) =>
            Interlocked.Increment(ref calls) == 1
                ? throw new TaskCanceledException("The request was canceled due to the configured HttpClient.Timeout of 300 seconds elapsing.", new TimeoutException())
                : Task.FromResult("我回来了"));
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        var (run, post, received, client) = Start(connector, port, cts.Token);
        using (client)
        {
            Assert.Equal(HttpStatusCode.NoContent, await post(Private(Owner, Segments(("record", "v1.amr")))));
            Assert.Equal(HttpStatusCode.NoContent, await post(Private(Owner, Segments(("record", "v2.amr")))));
            for (var i = 0; i < 100 && !napcat.Calls.Any(c => c.Action == "send_private_msg"); i++)
                await Task.Delay(50, ct);
            Assert.Equal(["我回来了"], received.Select(m => m.Text));
            Assert.Equal("在呢，我回来了", napcat.Calls.Single(c => c.Action == "send_private_msg").Body["message"]![0]!["data"]!["text"]!.GetValue<string>());
        }
        await cts.CancelAsync();
        await run;
    }

    private static int FreePort()
    {
        using var probe = new TcpListener(IPAddress.Loopback, 0);
        probe.Start();
        return ((IPEndPoint)probe.LocalEndpoint).Port;
    }

    [Fact]
    public async Task A_phone_QQ_image_can_be_collected_as_a_sticker_or_outfit_without_leaking_the_NapCat_token()
    {
        var ct = TestContext.Current.CancellationToken;
        using var notebook = new CompanionNotebook(new InMemoryKeyValueStore(), "qq:owner");
        var transport = new FakeNapCat();
        using var http = new HttpClient(transport);
        var companion = new CompanionExperience(notebook, () => new(), new(http), "qq:owner");
        var port = FreePort();
        var connector = new OneBotConnector(port, new("http://127.0.0.1:3000"), Token, Secret, Owner, http, companion: companion);
        using var cancel = CancellationTokenSource.CreateLinkedTokenSource(ct);
        var (run, post, received, client) = Start(connector, port, cancel.Token);
        using (client)
        {
            static JsonObject Image(string command, string url) => Private(Owner, new JsonArray(
                new JsonObject { ["type"] = "text", ["data"] = new JsonObject { ["text"] = command } },
                new JsonObject { ["type"] = "image", ["data"] = new JsonObject { ["url"] = url, ["file"] = "phone.png" } }));
            Assert.Equal(HttpStatusCode.NoContent, await post(Image("/sticker joy 笑脸", "https://gchat.qpic.cn/phone.png")));
            for (var i = 0; i < 100 && (await notebook.ReadAsync(ct: TestContext.Current.CancellationToken)).Assets.Count < 1; i++) await Task.Delay(25, ct);
            Assert.Equal("joy", Assert.Single((await notebook.ReadAsync(ct: TestContext.Current.CancellationToken)).Assets).Emotion);
            Assert.Equal(HttpStatusCode.NoContent, await post(Image("/outfit winter 红围巾", "https://multimedia.nt.qq.com.cn/scarf.png")));
            for (var i = 0; i < 100 && (await notebook.ReadAsync(ct: TestContext.Current.CancellationToken)).Assets.Count < 2; i++) await Task.Delay(25, ct);
            Assert.Equal("winter", (await notebook.ReadAsync(ct: TestContext.Current.CancellationToken)).Assets.Single(a => a.Kind == "outfit").Season);
            Assert.Equal(HttpStatusCode.NoContent, await post(Image("/sticker joy bad", "http://127.0.0.1/private")));
            for (var i = 0; i < 100 && transport.Calls.Count(c => c.Action == "send_private_msg") < 3; i++) await Task.Delay(25, ct);
            Assert.Equal(2, transport.ImageReads);
            Assert.Equal(2, (await notebook.ReadAsync(ct: TestContext.Current.CancellationToken)).Assets.Count);
            Assert.Empty(received); // collection commands do not ask a language model to pretend it saved an image
        }
        await cancel.CancelAsync(); await run;
    }

    [Fact]
    public void The_signature_is_the_hmac_sha1_of_the_body_under_the_secret()
    {
        var body = Encoding.UTF8.GetBytes("{\"post_type\":\"message\"}");
        Assert.True(OneBotConnector.HasValidSignature(body, Sign(body), Secret));
        Assert.True(OneBotConnector.HasValidSignature(body, " " + Sign(body).ToUpperInvariant().Replace("SHA1=", "sha1=", StringComparison.Ordinal) + " ", Secret));
        Assert.False(OneBotConnector.HasValidSignature(body, Sign(Encoding.UTF8.GetBytes("{}")), Secret));
        Assert.False(OneBotConnector.HasValidSignature(body, null, Secret));
        Assert.False(OneBotConnector.HasValidSignature(body, Sign(body), "another-secret-0123456789"));
    }

    [Fact]
    public void Only_a_private_text_message_from_the_owner_is_a_channel_message()
    {
        var m = OneBotConnector.ToChannelMessage(Private(Owner, Segments(("text", "你好 "), ("image", "a.png"), ("text", "艾娅德"))), Owner)!;
        Assert.Equal(("qq", Owner, "你好 艾娅德", true, true, "主人"), (m.Platform, m.ConversationId, m.Text, m.IsDirect, m.AddressesBot, m.AuthorName));
        Assert.Equal("早上好", OneBotConnector.ToChannelMessage(Private(Owner, JsonValue.Create("  早上好 ")), Owner)!.Text); // the "string" post format
        Assert.Null(OneBotConnector.ToChannelMessage(Private("987654321", Segments(("text", "hi"))), Owner));
        Assert.Null(OneBotConnector.ToChannelMessage(Private(Owner, Segments(("record", "v.amr"))), Owner)); // a voice message alone
        var group = Private(Owner, Segments(("text", "hi")));
        group["message_type"] = "group";
        Assert.Null(OneBotConnector.ToChannelMessage(group, Owner));
        Assert.Null(OneBotConnector.ToChannelMessage(new JsonObject { ["post_type"] = "notice", ["user_id"] = 123456789 }, Owner));
        Assert.Equal("QQ", TextChannel.BodilessChannel("qq")); // the bodiless-channel notes of contract 1.2.0 apply on QQ
    }

    [Fact]
    public void Short_keys_and_a_missing_owner_are_refused()
    {
        using var http = new HttpClient();
        Assert.Throws<ArgumentException>(() => new OneBotConnector(1, new Uri("http://127.0.0.1:3000"), "short", Secret, Owner, http));
        Assert.Throws<ArgumentException>(() => new OneBotConnector(1, new Uri("http://127.0.0.1:3000"), Token, "short", Owner, http));
        Assert.Throws<ArgumentException>(() => new OneBotConnector(1, new Uri("http://127.0.0.1:3000"), Token, Secret, "", http));
        Assert.Throws<ArgumentException>(() => new OneBotConnector(1, new Uri("https://127.0.0.1:3000"), Token, Secret, Owner, http));
    }

    [Fact]
    public async Task She_can_start_a_message_to_the_owner_and_to_nobody_else()
    {
        var ct = TestContext.Current.CancellationToken;
        var napcat = new FakeNapCat();
        var connector = new OneBotConnector(FreePort(), new Uri("http://127.0.0.1:3000"), Token, Secret, Owner, new HttpClient(napcat));
        await Assert.ThrowsAsync<InvalidOperationException>(() => connector.SendAsync("987654321", "到点啦", ct));
        Assert.Empty(napcat.Calls);
        await connector.SendAsync(Owner, new string('提', OneBotConnector.MaxText + 1), ct); // a long line goes out in parts
        Assert.Equal([OneBotConnector.MaxText, 1], napcat.Calls.Select(c => c.Body["message"]![0]!["data"]!["text"]!.GetValue<string>().Length));
        Assert.All(napcat.Calls, c => Assert.Equal(("send_private_msg", 123456789L), (c.Action, c.Body["user_id"]!.GetValue<long>())));
    }

    [Fact]
    public async Task Signed_owner_messages_are_answered_through_napcat_and_the_rest_is_refused_or_ignored()
    {
        var ct = TestContext.Current.CancellationToken;
        var port = FreePort();
        var napcat = new FakeNapCat();
        var connector = new OneBotConnector(port, new Uri("http://127.0.0.1:3000"), Token, Secret, Owner, new HttpClient(napcat));
        var received = new List<ChannelMessage>();
        var answered = new TaskCompletionSource();
        using var cts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        var run = connector.RunAsync((m, _) =>
        {
            lock (received)
                received.Add(m);
            return Task.FromResult<ChannelReply?>(new ChannelReply("在呢，" + m.Text, []));
        }, cts.Token);
        using var client = new HttpClient { BaseAddress = new Uri($"http://127.0.0.1:{port}/") };
        async Task<HttpStatusCode> PostAsync(JsonObject evt, string? signature = null)
        {
            var body = Encoding.UTF8.GetBytes(evt.ToJsonString());
            using var content = new ByteArrayContent(body);
            content.Headers.ContentType = new("application/json");
            using var req = new HttpRequestMessage(HttpMethod.Post, "") { Content = content };
            req.Headers.Add("X-Signature", signature ?? Sign(body));
            for (var attempt = 0; ; attempt++)
            {
                try
                {
                    using var res = await client.SendAsync(req.Clone(body), ct);
                    return res.StatusCode;
                }
                catch (HttpRequestException) when (attempt < 50)
                {
                    await Task.Delay(100, ct); // the listener is still starting
                }
            }
        }

        Assert.Equal(HttpStatusCode.Forbidden, await PostAsync(Private(Owner, Segments(("text", "unsigned"))), "sha1=00"));
        Assert.Equal(HttpStatusCode.NoContent, await PostAsync(Private("987654321", Segments(("text", "a stranger")))));
        Assert.Equal(HttpStatusCode.NoContent, await PostAsync(Private(Owner, Segments(("text", "你好")))));
        for (var i = 0; i < 100 && napcat.Calls.Count == 0; i++)
            await Task.Delay(50, ct);

        Assert.Equal(["你好"], received.Select(m => m.Text));
        var (action, auth, body) = Assert.Single(napcat.Calls);
        Assert.Equal("send_private_msg", action);
        Assert.Equal(Token, auth);
        Assert.Equal(123456789L, body["user_id"]!.GetValue<long>());
        Assert.Equal("text", body["message"]![0]!["type"]!.GetValue<string>());
        Assert.Equal("在呢，你好", body["message"]![0]!["data"]!["text"]!.GetValue<string>());
        var health = JsonNode.Parse(await client.GetStringAsync("health", ct))!;
        Assert.Equal((1, 1, 1), (health["messages"]!.GetValue<int>(), health["answered"]!.GetValue<int>(), health["ignored"]!.GetValue<int>()));
        Assert.DoesNotContain("你好", health.ToJsonString(), StringComparison.Ordinal);
        await cts.CancelAsync();
        await run;
    }
}

internal static class OneBotTestRequests
{
    /// <summary>A fresh copy of a request (an HttpRequestMessage is sent once).</summary>
    public static HttpRequestMessage Clone(this HttpRequestMessage request, byte[] body)
    {
        var copy = new HttpRequestMessage(request.Method, request.RequestUri) { Content = new ByteArrayContent(body) };
        copy.Content.Headers.ContentType = new("application/json");
        foreach (var header in request.Headers)
            copy.Headers.TryAddWithoutValidation(header.Key, header.Value);
        return copy;
    }
}
