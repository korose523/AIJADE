using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Chat;
using Aijade.Server.Mcp;
using Aijade.Server.Product;
using Aijade.Server.Tools;

using Microsoft.AspNetCore.Hosting.Server;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;

namespace Aijade.Tests;

public class ToolTests
{
    private sealed class Fake(Func<HttpRequestMessage, string, HttpResponseMessage> respond) : HttpMessageHandler
    {
        public List<(string Url, string Body, string? Cookie)> Requests { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var body = request.Content is null ? "" : await request.Content.ReadAsStringAsync(cancellationToken);
            lock (Requests)
                Requests.Add((request.RequestUri!.ToString(), body, request.Headers.TryGetValues("Cookie", out var c) ? string.Join(";", c) : null));
            return respond(request, body);
        }
    }

    private static HttpResponseMessage Text(string s) => new(HttpStatusCode.OK) { Content = new StringContent(s, Encoding.UTF8, "application/json") };

    // Known-answer vectors from the author's plugin tests, computed independently with Python's hashlib / hmac.
    [Fact]
    public void Mi_cloud_signing_matches_the_independent_known_answer_vectors()
    {
        Assert.Equal("2AB96390C7DBE3439DE74D0C9B0B1767", MiCloud.PasswordHash("hunter2"));
        Assert.Equal("AQIDBAUGBwgBxzh1", MiCloud.Nonce(1_790_000_000_000, [1, 2, 3, 4, 5, 6, 7, 8]));
        Assert.Equal("3uR08cM90KTtW73Io8ug8qzAoCcWnaSxHAwYs2LlH8k=", MiCloud.SignedNonce("MDEyMzQ1Njc4OWFiY2RlZg==", "AQIDBAUGBwgBxzh1"));
        Assert.Equal("jvccLEpKzFPBigfzR8jc8/WHYn/gcYoPPde1AHRcWuI=",
            MiCloud.Signature("/home/device_list", "3uR08cM90KTtW73Io8ug8qzAoCcWnaSxHAwYs2LlH8k=", "AQIDBAUGBwgBxzh1", "{\"getVirtualModel\":false,\"getHuamiDevices\":0}"));
        Assert.Throws<MiCloudException>(() => new MiCloud(new MiCredentials("u", "p", "mars"), new HttpClient(), TimeProvider.System));
    }

    [Fact]
    public async Task Mi_home_logs_in_signs_calls_and_reports_failures_honestly()
    {
        var ct = TestContext.Current.CancellationToken;
        var rpcAnswer = """{"code":0,"result":["on",80,4000,16711680]}""";
        var fake = new Fake((req, body) => req.RequestUri!.AbsolutePath switch
        {
            "/pass/serviceLogin" => Text("&&&START&&&{\"_sign\":\"sign-1\"}"),
            "/pass/serviceLoginAuth2" => Text("&&&START&&&{\"code\":0,\"userId\":42,\"ssecurity\":\"MDEyMzQ1Njc4OWFiY2RlZg==\",\"location\":\"https://sts.api.io.mi.com/sts?x=1\"}"),
            "/sts" => new HttpResponseMessage(HttpStatusCode.OK) { Headers = { { "Set-Cookie", "serviceToken=svc-token; path=/" } } },
            "/app/home/device_list" => Text("""{"code":0,"result":{"list":[{"did":"1","name":"Desk Lamp","model":"yeelink.light.lamp4","isOnline":true},{"did":"2","name":"Desk Fan","model":"zhimi.fan.v3","isOnline":true},{"did":"3","name":"Plug","model":"chuangmi.plug.m1","isOnline":false}]}}"""),
            _ when req.RequestUri.AbsolutePath.StartsWith("/app/home/rpc/", StringComparison.Ordinal) => Text(rpcAnswer),
            _ => new HttpResponseMessage(HttpStatusCode.NotFound),
        });
        var cloud = new MiCloud(new MiCredentials("user@example.com", "hunter2", "cn"), new HttpClient(fake), TimeProvider.System);
        var tools = new XiaomiTools(new XiaomiClient(cloud));

        var list = await tools.CallAsync("list_devices", [], ct);
        Assert.Contains("Desk Lamp (did 1, yeelink.light.lamp4, light, online)", list.Content, StringComparison.Ordinal);
        Assert.Contains("hash=2AB96390C7DBE3439DE74D0C9B0B1767", fake.Requests[1].Body, StringComparison.Ordinal);
        var call = fake.Requests[3];
        Assert.Equal("https://api.io.mi.com/app/home/device_list", call.Url);
        Assert.Contains("serviceToken=svc-token", call.Cookie, StringComparison.Ordinal);
        var form = System.Web.HttpUtility.ParseQueryString(call.Body);
        Assert.Equal(MiCloud.Signature("/home/device_list", MiCloud.SignedNonce("MDEyMzQ1Njc4OWFiY2RlZg==", form["_nonce"]!), form["_nonce"]!, form["data"]!), form["signature"]);

        Assert.Equal("Desk Lamp brightness 40%.", (await tools.CallAsync("set_brightness", new JsonObject { ["name"] = "Desk Lamp", ["brightness"] = 40 }, ct)).Content);
        Assert.Contains("\"method\":\"set_bright\",\"params\":[40]", Uri.UnescapeDataString(fake.Requests[^1].Body), StringComparison.Ordinal);
        Assert.Contains("\"power\":\"on\"", (await tools.CallAsync("get_device_status", new JsonObject { ["did"] = "1" }, ct)).Content, StringComparison.Ordinal);
        var offline = await tools.CallAsync("toggle_device", new JsonObject { ["did"] = "3", ["on"] = true }, ct);
        Assert.True(offline.IsError);
        Assert.Contains("offline", offline.Content, StringComparison.Ordinal);
        Assert.Contains("several devices", Assert.Throws<ArgumentException>(() => XiaomiTools.Find(
            [new("1", "Desk Lamp", "", "light", true), new("2", "Desk Fan", "", "other", true)], new JsonObject { ["name"] = "Desk" })).Message, StringComparison.Ordinal);
        Assert.Equal("1", XiaomiTools.Find([new("1", "Desk Lamp", "", "light", true), new("2", "Desk Fan", "", "other", true)], new JsonObject { ["name"] = "Lamp" }).Did);

        // A device-side error is a failure, never a success.
        rpcAnswer = """{"code":0,"result":{"error":{"code":-5001,"message":"unsupported"}}}""";
        await Assert.ThrowsAsync<MiCloudException>(() => tools.CallAsync("toggle_device", new JsonObject { ["did"] = "1", ["on"] = true }, ct));

        // Accounts that need verification say so instead of pretending to log in.
        var verify = new Fake((req, _) => req.RequestUri!.AbsolutePath == "/pass/serviceLogin"
            ? Text("&&&START&&&{\"_sign\":\"s\"}") : Text("&&&START&&&{\"code\":0,\"notificationUrl\":\"https://account.xiaomi.com/verify\"}"));
        var blocked = await Assert.ThrowsAsync<MiCloudException>(() => new MiCloud(new MiCredentials("u", "p", "cn"), new HttpClient(verify), TimeProvider.System).LoginAsync(ct));
        Assert.Equal("verification-required", blocked.Code);
    }

    /// <summary>A minimal Source RCON server: password "secret", answers "/players online" and echoes other lines.</summary>
    private static async Task RconServerAsync(TcpListener listener, List<string> received, CancellationToken ct)
    {
        using var client = await listener.AcceptTcpClientAsync(ct);
        var s = client.GetStream();
        while (!ct.IsCancellationRequested)
        {
            (int Id, int Type, string Body) p;
            try
            {
                p = await RconClient.ReadPacketAsync(s, ct);
            }
            catch (EndOfStreamException)
            {
                return;
            }
            lock (received)
                received.Add(p.Body);
            if (p.Type == 3)
            {
                await s.WriteAsync(RconClient.Packet(p.Id, 0, ""), ct); // the empty response some servers send first
                await s.WriteAsync(RconClient.Packet(p.Body == "secret" ? p.Id : -1, 2, ""), ct);
            }
            else
            {
                await s.WriteAsync(RconClient.Packet(p.Id, 0, p.Body == "/players online" ? "Online players (1):\n  alice (online)" : ""), ct);
            }
        }
    }

    [Fact]
    public async Task Factorio_tools_speak_rcon_and_keep_raw_commands_behind_a_switch()
    {
        var ct = TestContext.Current.CancellationToken;
        var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        var port = ((IPEndPoint)listener.LocalEndpoint).Port;
        var received = new List<string>();
        var server = RconServerAsync(listener, received, ct);

        await using var tools = new FactorioTools("127.0.0.1", port, "secret", allowCommands: false);
        Assert.DoesNotContain(await tools.ListAsync(ct), t => t.Name == "command");
        Assert.Contains("alice", (await tools.CallAsync("players", [], ct)).Content, StringComparison.Ordinal);
        await tools.CallAsync("say", new JsonObject { ["message"] = "/c game.forces.player.kill_all_units()\nhello" }, ct);
        Assert.Contains("c game.forces.player.kill_all_units() hello", received, StringComparer.Ordinal); // never a command
        Assert.True((await tools.CallAsync("command", new JsonObject { ["command"] = "/evolution" }, ct)).IsError);

        var second = RconServerAsync(listener, [], ct);
        await using var wrong = new RconClient("127.0.0.1", port, "nope");
        await Assert.ThrowsAsync<UnauthorizedAccessException>(() => wrong.ExecuteAsync("/time", ct));
        listener.Stop();
    }

    private sealed class ToolLlm : HttpMessageHandler
    {
        public List<JsonNode> Bodies { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var body = JsonNode.Parse(await request.Content!.ReadAsStringAsync(cancellationToken))!;
            Bodies.Add(body);
            var last = body["messages"]!.AsArray()[^1]!;
            if (body["tools"] is JsonArray && last["role"]!.GetValue<string>() == "user")
            {
                return Text("""{"choices":[{"message":{"role":"assistant","content":null,"tool_calls":[{"id":"call_1","type":"function","function":{"name":"home__call_service","arguments":"{\"domain\":\"light\",\"service\":\"turn_on\",\"entity_id\":\"light.desk\"}"}}]}}]}""");
            }
            if (last["role"]!.GetValue<string>() == "tool")
                return Text("""{"choices":[{"message":{"role":"assistant","content":"[[emote:joy]]The desk light is on now."}}],"usage":{"prompt_tokens":20,"completion_tokens":8}}""");
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent("data: {\"choices\":[{\"delta\":{\"content\":\"No tools here.\"}}]}\n\ndata: [DONE]\n\n", Encoding.UTF8, "text/event-stream") };
        }
    }

    [Fact]
    public async Task The_tool_hub_serves_configured_providers_to_admins_and_the_companion_uses_them()
    {
        var ct = TestContext.Current.CancellationToken;
        var llm = new ToolLlm();
        var ha = new Fake((req, body) => req.RequestUri!.AbsolutePath switch
        {
            "/api/states" => Text("""[{"entity_id":"light.desk","state":"off","attributes":{"friendly_name":"Desk"}},{"entity_id":"lock.front","state":"locked","attributes":{}}]"""),
            "/api/services/light/turn_on" => Text("[]"),
            _ => new HttpResponseMessage(HttpStatusCode.NotFound),
        });
        await using var host = await ServerTestHost.StartAsync(worker: false, services: s =>
        {
            s.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => llm);
            s.AddHttpClient(McpEndpoints.SelfClient, c => c.BaseAddress = new Uri("http://localhost/"))
                .ConfigurePrimaryHttpMessageHandler(sp => ((TestServer)sp.GetRequiredService<IServer>()).CreateHandler());
            // Home Assistant is faked; the MCP provider reaches this very server's /mcp through the test server.
            s.AddHttpClient(ToolHub.HttpClientName).ConfigurePrimaryHttpMessageHandler(sp => new Router(ha, ((TestServer)sp.GetRequiredService<IServer>()).CreateHandler()));
        });
        await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", new JsonObject
        {
            ["models"] = new JsonObject { ["aijade-chat"] = new JsonObject { ["upstream"] = "https://llm.example/v1", ["model"] = "m", ["keys"] = new JsonArray("k") } },
        }, ServerTestHost.AdminToken);
        var config = new JsonObject
        {
            ["providers"] = new JsonObject
            {
                ["home"] = new JsonObject { ["kind"] = "homeassistant", ["url"] = "http://ha.local:8123/", ["token"] = "ha-long-lived-token", ["domains"] = new JsonArray("light") },
                ["self"] = new JsonObject { ["kind"] = "mcp-http", ["url"] = "http://localhost/mcp", ["headers"] = new JsonObject { ["Authorization"] = $"Bearer {ServerTestHost.AdminToken}" } },
            },
        };
        Assert.Equal(400, (await host.SendAsync(HttpMethod.Put, "/api/v1/admin/tools", new JsonObject { ["providers"] = new JsonObject { ["Bad Id"] = new JsonObject { ["kind"] = "homeassistant", ["url"] = "http://x/" } } }, ServerTestHost.AdminToken)).Status);
        Assert.Equal(200, (await host.SendAsync(HttpMethod.Put, "/api/v1/admin/tools", config, ServerTestHost.AdminToken)).Status);
        var (_, masked) = await host.SendAsync(HttpMethod.Get, "/api/v1/admin/tools", token: ServerTestHost.AdminToken);
        Assert.DoesNotContain("ha-long-lived-token", masked!.ToJsonString(), StringComparison.Ordinal);
        Assert.Equal("…oken", masked["providers"]!["home"]!["token"]!.GetValue<string>());
        Assert.Equal(200, (await host.SendAsync(HttpMethod.Put, "/api/v1/admin/tools", masked, ServerTestHost.AdminToken)).Status); // masked round trip keeps secrets
        Assert.Equal(0, await host.CountAsync("SELECT count(*) FROM config_kv WHERE value::text LIKE '%ha-long-lived-token%'"));

        var (_, listed) = await host.SendAsync(HttpMethod.Get, "/api/v1/tools", token: ServerTestHost.AdminToken);
        var names = listed!["tools"]!.AsArray().Select(t => t!["name"]!.GetValue<string>()).ToList();
        Assert.Contains("home__call_service", names);
        Assert.Contains("self__memory_search", names);
        var (_, lights) = await host.SendAsync(HttpMethod.Post, "/api/v1/tools/call", new JsonObject { ["name"] = "home__list_entities", ["arguments"] = new JsonObject() }, ServerTestHost.AdminToken);
        Assert.Equal("light.desk = off (Desk)", lights!["content"]!.GetValue<string>()); // the lock is outside the allowed domains
        var (_, viaMcp) = await host.SendAsync(HttpMethod.Post, "/api/v1/tools/call", new JsonObject { ["name"] = "self__memory_search", ["arguments"] = new JsonObject { ["query"] = "x" } }, ServerTestHost.AdminToken);
        Assert.Equal("No memory matches.", viaMcp!["content"]!.GetValue<string>());

        // Ordinary users get no tools unless the administrator allows it.
        Assert.Empty((await host.SendAsync(HttpMethod.Get, "/api/v1/tools")).Body!["tools"]!.AsArray());
        Assert.Equal(403, (await host.SendAsync(HttpMethod.Post, "/api/v1/tools/call", new JsonObject { ["name"] = "home__list_entities" })).Status);
        config["allowAllUsers"] = true;
        await host.SendAsync(HttpMethod.Put, "/api/v1/admin/tools", config, ServerTestHost.AdminToken);

        // The companion calls a tool, sees its result, then answers (with its expression marker handled as usual).
        var tokens = new MemoryTokenStore();
        await tokens.SetAsync(ServerTestHost.Token);
        var api = new AijadeApi(host.Client, tokens);
        var chat = await api.CreateChatAsync(null, "tools", ct);
        var events = new List<OrchestratorEvent>();
        await foreach (var e in new ChatOrchestrator(api, [], new OrchestratorOptions { Tools = () => true }).SendAsync(chat.Id, null, [], "Turn on my desk light", "snap", ct))
            events.Add(e);
        Assert.Equal("The desk light is on now.", Assert.IsType<TurnCompleted>(events[^1]).Reply.Content);
        Assert.Equal(["joy"], events.OfType<ExpressionCue>().Select(c => c.Name));
        Assert.Contains(ha.Requests, r => r.Url == "http://ha.local:8123/api/services/light/turn_on" && r.Body.Contains("\"entity_id\":\"light.desk\"", StringComparison.Ordinal));
        var toolMessage = llm.Bodies[^1]["messages"]!.AsArray()[^1]!;
        Assert.Equal(("tool", "call_1", "Called light.turn_on on light.desk."), (toolMessage["role"]!.GetValue<string>(), toolMessage["tool_call_id"]!.GetValue<string>(), toolMessage["content"]!.GetValue<string>()));

        // With the module off, no tools are offered and the reply streams as before.
        events.Clear();
        await foreach (var e in new ChatOrchestrator(api, [], new OrchestratorOptions()).SendAsync(chat.Id, null, [], "Hi", "snap", ct))
            events.Add(e);
        Assert.Equal("No tools here.", Assert.IsType<TurnCompleted>(events[^1]).Reply.Content);
        Assert.Null(llm.Bodies[^1]["tools"]);
    }

    /// <summary>Sends ha.local to the Home Assistant fake and everything else to the test server.</summary>
    private sealed class Router(HttpMessageHandler ha, HttpMessageHandler server) : DelegatingHandler(server)
    {
        private readonly HttpMessageInvoker haInvoker = new(ha);

        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) =>
            request.RequestUri!.Host == "ha.local" ? haInvoker.SendAsync(request, cancellationToken) : base.SendAsync(request, cancellationToken);

        protected override void Dispose(bool disposing)
        {
            if (disposing)
                haInvoker.Dispose();
            base.Dispose(disposing);
        }
    }
}
