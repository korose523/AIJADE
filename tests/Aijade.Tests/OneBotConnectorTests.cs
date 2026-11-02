using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Client.Companion;
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

    /// <summary>NapCat's HTTP server: records each action and answers ok.</summary>
    private sealed class FakeNapCat : HttpMessageHandler
    {
        public List<(string Action, string? Auth, JsonObject Body)> Calls { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var body = (JsonObject)JsonNode.Parse(await request.Content!.ReadAsStringAsync(cancellationToken))!;
            lock (Calls)
                Calls.Add((request.RequestUri!.AbsolutePath.TrimStart('/'), request.Headers.Authorization?.Parameter, body));
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent("{\"status\":\"ok\",\"retcode\":0,\"data\":{\"message_id\":7}}", Encoding.UTF8, "application/json") };
        }
    }

    private static int FreePort()
    {
        using var probe = new TcpListener(IPAddress.Loopback, 0);
        probe.Start();
        return ((IPEndPoint)probe.LocalEndpoint).Port;
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
