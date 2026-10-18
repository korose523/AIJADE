using System.Net;
using System.Net.WebSockets;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Server.Product;

using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;

namespace Aijade.Tests;

/// <summary>The product layer of the server: accounts, library, chat sync, flux, the gateway, Stripe and administration.</summary>
public class ProductServerTests
{
    private const string AdminToken = ServerTestHost.AdminToken;

    /// <summary>A fake OpenAI-compatible / Stripe upstream that records requests and answers per the configured script.</summary>
    private sealed class FakeUpstream(Func<HttpRequestMessage, string, HttpResponseMessage> respond) : HttpMessageHandler
    {
        public List<(string Path, string? Auth, string Body)> Requests { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var body = request.Content is null ? "" : await request.Content.ReadAsStringAsync(cancellationToken);
            lock (Requests)
                Requests.Add((request.RequestUri!.AbsolutePath, request.Headers.Authorization?.Parameter, body));
            return respond(request, body);
        }
    }

    private static HttpResponseMessage Json(HttpStatusCode code, string json) => new(code) { Content = new StringContent(json, Encoding.UTF8, "application/json") };

    [Fact]
    public async Task Accounts_sign_up_sign_in_session_and_sign_out()
    {
        await using var host = await ServerTestHost.StartAsync(worker: false);
        var (s1, up) = await host.SendAsync(HttpMethod.Post, "/api/v1/auth/sign-up/email", new JsonObject { ["email"] = "a@x.io", ["password"] = "correct horse", ["name"] = "A" }, token: null);
        Assert.Equal(201, s1);
        var token = up!["token"]!.GetValue<string>();
        Assert.Equal(409, (await host.SendAsync(HttpMethod.Post, "/api/v1/auth/sign-up/email", new JsonObject { ["email"] = "A@X.io", ["password"] = "correct horse" }, token: null)).Status);
        Assert.Equal(400, (await host.SendAsync(HttpMethod.Post, "/api/v1/auth/sign-up/email", new JsonObject { ["email"] = "b@x.io", ["password"] = "short" }, token: null)).Status);
        Assert.Equal(401, (await host.SendAsync(HttpMethod.Post, "/api/v1/auth/sign-in/email", new JsonObject { ["email"] = "a@x.io", ["password"] = "wrong password" }, token: null)).Status);
        var (s2, signIn) = await host.SendAsync(HttpMethod.Post, "/api/v1/auth/sign-in/email", new JsonObject { ["email"] = "a@x.io", ["password"] = "correct horse" }, token: null);
        Assert.Equal(200, s2);
        var (s3, session) = await host.SendAsync(HttpMethod.Get, "/api/v1/auth/session", token: signIn!["token"]!.GetValue<string>());
        Assert.Equal(200, s3);
        Assert.Equal("a@x.io", session!["user"]!["email"]!.GetValue<string>());
        // Only the hash of a token is stored.
        Assert.Equal(0, await host.CountAsync("SELECT count(*) FROM auth_sessions WHERE token_hash = $1", token));
        Assert.Equal(200, (await host.SendAsync(HttpMethod.Post, "/api/v1/auth/sign-out", token: token)).Status);
        Assert.Equal(401, (await host.SendAsync(HttpMethod.Get, "/api/v1/auth/session", token: token)).Status);
        Assert.Equal(401, (await host.SendAsync(HttpMethod.Get, "/api/v1/auth/session", token: null)).Status);
    }

    [Fact]
    public async Task Characters_chats_and_messages_are_owner_scoped_and_pushed_over_websocket()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(worker: false);
        var (sc, character) = await host.SendAsync(HttpMethod.Post, "/api/v1/characters", new JsonObject { ["name"] = "艾娅德", ["persona"] = "a maid", ["tags"] = new JsonArray("maid") });
        Assert.Equal(201, sc);
        var cid = character!["id"]!.GetValue<string>();
        Assert.Equal("maid", character["tags"]![0]!.GetValue<string>());
        Assert.Equal(404, (await host.SendAsync(HttpMethod.Get, $"/api/v1/characters/{cid}", token: AdminToken)).Status); // private to its owner
        Assert.Equal(200, (await host.SendAsync(HttpMethod.Patch, $"/api/v1/characters/{cid}", new JsonObject { ["visibility"] = "public" })).Status);
        Assert.Equal(200, (await host.SendAsync(HttpMethod.Get, $"/api/v1/characters/{cid}", token: AdminToken)).Status);

        var (_, chat) = await host.SendAsync(HttpMethod.Post, "/api/v1/chats", new JsonObject { ["characterId"] = cid, ["title"] = "first" });
        var chatId = chat!["id"]!.GetValue<string>();

        var ws = host.App.GetTestServer().CreateWebSocketClient();
        using var socket = await ws.ConnectAsync(new Uri(host.Client.BaseAddress!, $"/api/v1/ws/chats?access_token={ServerTestHost.Token}"), ct);
        var (sm, msg) = await host.SendAsync(HttpMethod.Post, $"/api/v1/chats/{chatId}/messages", new JsonObject { ["role"] = "user", ["content"] = "hello" });
        Assert.Equal(201, sm);
        var buffer = new byte[8192];
        var received = await socket.ReceiveAsync(buffer, ct);
        var pushed = JsonNode.Parse(Encoding.UTF8.GetString(buffer, 0, received.Count))!;
        Assert.Equal("message", pushed["type"]!.GetValue<string>());
        Assert.Equal(msg!["id"]!.GetValue<string>(), pushed["message"]!["id"]!.GetValue<string>());

        // A push over the socket is stored and echoed to every connection of the owner.
        await socket.SendAsync(Encoding.UTF8.GetBytes(new JsonObject { ["type"] = "push", ["chatId"] = chatId, ["role"] = "assistant", ["content"] = "hi there" }.ToJsonString()),
            WebSocketMessageType.Text, true, ct);
        received = await socket.ReceiveAsync(buffer, ct);
        Assert.Equal("hi there", JsonNode.Parse(Encoding.UTF8.GetString(buffer, 0, received.Count))!["message"]!["content"]!.GetValue<string>());
        await socket.CloseAsync(WebSocketCloseStatus.NormalClosure, "done", ct);

        var (_, list) = await host.SendAsync(HttpMethod.Get, $"/api/v1/chats/{chatId}/messages?after=0");
        Assert.Equal(["hello", "hi there"], list!["messages"]!.AsArray().Select(m => m!["content"]!.GetValue<string>()));
        Assert.Equal(404, (await host.SendAsync(HttpMethod.Get, $"/api/v1/chats/{chatId}/messages", token: AdminToken)).Status);
        Assert.Equal(400, (await host.SendAsync(HttpMethod.Post, $"/api/v1/chats/{chatId}/messages", new JsonObject { ["role"] = "robot", ["content"] = "x" })).Status);
        Assert.Equal(1, await host.CountAsync("SELECT count(*) FROM product_events WHERE action = 'message_pushed'"));
    }

    [Fact]
    public async Task Provider_secrets_are_encrypted_and_never_returned()
    {
        await using var host = await ServerTestHost.StartAsync(worker: false);
        var (s, created) = await host.SendAsync(HttpMethod.Post, "/api/v1/providers", new JsonObject { ["kind"] = "openai", ["name"] = "mine", ["apiKey"] = "sk-secret-123" });
        Assert.Equal(201, s);
        Assert.True(created!["hasSecret"]!.GetValue<bool>());
        Assert.DoesNotContain("sk-secret-123", created.ToJsonString(), StringComparison.Ordinal);
        Assert.Equal(0, await host.CountAsync("SELECT count(*) FROM provider_configs WHERE secret_protected LIKE '%sk-secret%'"));
        var (_, list) = await host.SendAsync(HttpMethod.Get, "/api/v1/providers");
        Assert.DoesNotContain("sk-secret-123", list!.ToJsonString(), StringComparison.Ordinal);
    }

    [Fact]
    public async Task Flux_ledger_is_idempotent_and_never_negative()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(worker: false);
        var ledger = host.App.Services.GetRequiredService<FluxLedger>();
        Assert.Equal(403, (await host.SendAsync(HttpMethod.Post, "/api/v1/admin/flux-grants", new JsonObject { ["userId"] = ServerTestHost.UserId, ["amount"] = 100 })).Status);
        var grant = new JsonObject { ["userId"] = ServerTestHost.UserId, ["amount"] = 100, ["idempotencyKey"] = "g1" };
        Assert.Equal(201, (await host.SendAsync(HttpMethod.Post, "/api/v1/admin/flux-grants", grant, AdminToken)).Status);
        Assert.Equal(201, (await host.SendAsync(HttpMethod.Post, "/api/v1/admin/flux-grants", grant, AdminToken)).Status);
        Assert.Equal(100, await ledger.BalanceAsync(ServerTestHost.UserId, ct));
        var ex = await Assert.ThrowsAsync<Aijade.Server.Infrastructure.ApiException>(() => ledger.ApplyAsync(ServerTestHost.UserId, -101, "usage", "too much", ct: ct));
        Assert.Equal(402, ex.Status);
        await Task.WhenAll(Enumerable.Range(0, 10).Select(i => ledger.ApplyAsync(ServerTestHost.UserId, -10, "usage", $"c{i}", ct: ct)));
        Assert.Equal(0, await ledger.BalanceAsync(ServerTestHost.UserId, ct));
        var (_, mine) = await host.SendAsync(HttpMethod.Get, "/api/v1/flux");
        Assert.Equal(0, mine!["balance"]!.GetValue<long>());
        Assert.Equal(11, mine["transactions"]!.AsArray().Count);
    }

    [Fact]
    public async Task Gateway_routes_rotates_keys_streams_and_meters_flux()
    {
        var ct = TestContext.Current.CancellationToken;
        var upstream = new FakeUpstream((req, body) =>
        {
            if (req.Headers.Authorization?.Parameter == "sk-bad")
                return Json(HttpStatusCode.Unauthorized, "{\"error\":\"bad key\"}");
            var json = JsonNode.Parse(body)!;
            if (req.RequestUri!.AbsolutePath.EndsWith("/audio/speech", StringComparison.Ordinal))
                return new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent([1, 2, 3]) { Headers = { ContentType = new("audio/mpeg") } } };
            if (json["stream"]?.GetValue<bool>() == true)
            {
                var sse = "data: {\"choices\":[{\"delta\":{\"content\":\"Hel\"}}],\"model\":\"up-model\"}\n\n" +
                          "data: {\"choices\":[{\"delta\":{\"content\":\"lo\"}}],\"model\":\"up-model\"}\n\n" +
                          "data: {\"choices\":[],\"usage\":{\"prompt_tokens\":1000,\"completion_tokens\":1000}}\n\n" +
                          "data: [DONE]\n\n";
                return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(sse, Encoding.UTF8, "text/event-stream") };
            }
            return Json(HttpStatusCode.OK, "{\"id\":\"c1\",\"model\":\"up-model\",\"choices\":[{\"message\":{\"role\":\"assistant\",\"content\":\"Hello\"}}],\"usage\":{\"prompt_tokens\":600,\"completion_tokens\":400}}");
        });
        await using var host = await ServerTestHost.StartAsync(worker: false,
            services: s => s.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => upstream));
        var routes = new JsonObject
        {
            ["models"] = new JsonObject { ["aijade-chat"] = new JsonObject { ["upstream"] = "https://llm.example/v1", ["model"] = "up-model", ["keys"] = new JsonArray("sk-bad", "sk-good"), ["fluxPer1k"] = 10 } },
            ["speech"] = new JsonObject { ["upstream"] = "https://tts.example/v1", ["model"] = "tts-1", ["keys"] = new JsonArray("sk-good"), ["fluxPer1k"] = 1000 },
        };
        Assert.Equal(200, (await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", routes, AdminToken)).Status);
        var (_, masked) = await host.SendAsync(HttpMethod.Get, "/api/v1/admin/gateway/routes", token: AdminToken);
        Assert.DoesNotContain("sk-good", masked!.ToJsonString(), StringComparison.Ordinal);
        Assert.Equal(0, await host.CountAsync("SELECT count(*) FROM config_kv WHERE value::text LIKE '%sk-good%'"));
        // Saving the masked document back (what the admin console does) keeps the real keys; the calls below prove it.
        Assert.Equal(200, (await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", masked, AdminToken)).Status);
        var broken = (JsonObject)masked.DeepClone();
        broken["speech"]!["keys"] = new JsonArray("…zzzz");
        Assert.Equal(400, (await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", broken, AdminToken)).Status);

        var request = new JsonObject { ["model"] = "aijade-chat", ["messages"] = new JsonArray(new JsonObject { ["role"] = "user", ["content"] = "hi" }) };
        Assert.Equal(402, (await host.SendAsync(HttpMethod.Post, "/api/v1/openai/v1/chat/completions", request)).Status); // no flux yet
        await host.SendAsync(HttpMethod.Post, "/api/v1/admin/flux-grants", new JsonObject { ["userId"] = ServerTestHost.UserId, ["amount"] = 100 }, AdminToken);

        var (s1, completion) = await host.SendAsync(HttpMethod.Post, "/api/v1/openai/v1/chat/completions", request);
        Assert.Equal(200, s1);
        Assert.Equal("aijade-chat", completion!["model"]!.GetValue<string>()); // the alias, never the upstream model
        Assert.Contains(upstream.Requests, r => r.Auth == "sk-bad");
        Assert.Contains(upstream.Requests, r => r.Auth == "sk-good" && r.Body.Contains("\"up-model\"", StringComparison.Ordinal));
        var ledger = host.App.Services.GetRequiredService<FluxLedger>();
        Assert.Equal(90, await ledger.BalanceAsync(ServerTestHost.UserId, ct)); // 1000 tokens × 10 / 1k

        request["stream"] = true;
        using (var req = new HttpRequestMessage(HttpMethod.Post, "/api/v1/openai/v1/chat/completions") { Content = new StringContent(request.ToJsonString(), Encoding.UTF8, "application/json") })
        {
            req.Headers.Authorization = new("Bearer", ServerTestHost.Token);
            using var res = await host.Client.SendAsync(req, ct);
            var text = await res.Content.ReadAsStringAsync(ct);
            Assert.Contains("\"content\":\"Hel\"", text, StringComparison.Ordinal);
            Assert.Contains("data: [DONE]", text, StringComparison.Ordinal);
            Assert.DoesNotContain("up-model", text, StringComparison.Ordinal);
        }
        Assert.Equal(70, await ledger.BalanceAsync(ServerTestHost.UserId, ct)); // 2000 tokens × 10 / 1k
        Assert.Equal(404, (await host.SendAsync(HttpMethod.Post, "/api/v1/openai/v1/chat/completions", new JsonObject { ["model"] = "nope", ["messages"] = new JsonArray(new JsonObject()) })).Status);
        var (_, models) = await host.SendAsync(HttpMethod.Get, "/api/v1/openai/v1/models");
        Assert.Equal("aijade-chat", models!["data"]![0]!["id"]!.GetValue<string>());

        using (var req = new HttpRequestMessage(HttpMethod.Post, "/api/v1/openai/v1/audio/speech") { Content = new StringContent("{\"input\":\"hello\",\"voice\":\"alloy\"}", Encoding.UTF8, "application/json") })
        {
            req.Headers.Authorization = new("Bearer", ServerTestHost.Token);
            using var res = await host.Client.SendAsync(req, ct);
            Assert.Equal(HttpStatusCode.OK, res.StatusCode);
            Assert.Equal([1, 2, 3], await res.Content.ReadAsByteArrayAsync(ct));
        }
        Assert.Equal(65, await ledger.BalanceAsync(ServerTestHost.UserId, ct)); // 5 chars × 1000 / 1k
        Assert.Equal(2, await host.CountAsync("SELECT count(*) FROM llm_request_logs WHERE status = 200"));
        Assert.Equal(2, await host.CountAsync("SELECT count(*) FROM product_events WHERE action = 'completion_succeeded'"));
    }

    [Fact]
    public async Task Stripe_checkout_and_signed_webhook_credit_flux_exactly_once()
    {
        var ct = TestContext.Current.CancellationToken;
        var stripe = new FakeUpstream((req, body) => Json(HttpStatusCode.OK, "{\"id\":\"cs_test_1\",\"url\":\"https://checkout.stripe.test/cs_test_1\"}"));
        const string secret = "whsec_test";
        await using var host = await ServerTestHost.StartAsync(new Dictionary<string, string?>
        {
            ["Stripe:SecretKey"] = "sk_test_x", ["Stripe:WebhookSecret"] = secret, ["Stripe:Prices:price_small"] = "500",
        }, worker: false, services: s => s.AddHttpClient(BillingEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => stripe));
        Assert.Equal(400, (await host.SendAsync(HttpMethod.Post, "/api/v1/stripe/checkout", new JsonObject { ["priceId"] = "price_unknown" })).Status);
        var (s, checkout) = await host.SendAsync(HttpMethod.Post, "/api/v1/stripe/checkout", new JsonObject { ["priceId"] = "price_small" });
        Assert.Equal(200, s);
        Assert.Equal("cs_test_1", checkout!["sessionId"]!.GetValue<string>());
        Assert.Contains("client_reference_id=test-user", stripe.Requests[0].Body, StringComparison.Ordinal);

        async Task<int> Deliver(string eventId, string? signature = null)
        {
            var payload = new JsonObject
            {
                ["id"] = eventId, ["type"] = "checkout.session.completed",
                ["data"] = new JsonObject { ["object"] = new JsonObject { ["id"] = "cs_test_1", ["payment_status"] = "paid" } },
            }.ToJsonString();
            var t = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
            using var req = new HttpRequestMessage(HttpMethod.Post, "/api/v1/stripe/webhook") { Content = new StringContent(payload, Encoding.UTF8, "application/json") };
            req.Headers.Add("Stripe-Signature", signature ?? $"t={t},v1={StripeSignature.Sign(payload, t, secret)}");
            using var res = await host.Client.SendAsync(req, ct);
            return (int)res.StatusCode;
        }
        Assert.Equal(400, await Deliver("evt_forged", "t=1,v1=deadbeef"));
        Assert.Equal(200, await Deliver("evt_1"));
        Assert.Equal(200, await Deliver("evt_1"));  // the same event redelivered
        Assert.Equal(200, await Deliver("evt_2"));  // a distinct event for the same session
        Assert.Equal(500, await host.App.Services.GetRequiredService<FluxLedger>().BalanceAsync(ServerTestHost.UserId, ct));
        Assert.Equal("completed", await host.ScalarAsync("SELECT status FROM stripe_checkouts WHERE session_id = 'cs_test_1'"));
        Assert.False(StripeSignature.Verify("x", $"t=1,v1={StripeSignature.Sign("x", 1, secret)}", secret, DateTimeOffset.FromUnixTimeSeconds(10_000)));
    }

    [Fact]
    public async Task Admin_requires_the_admin_role_and_manages_users_and_pipeline_health()
    {
        await using var host = await ServerTestHost.StartAsync(worker: false);
        Assert.Equal(403, (await host.SendAsync(HttpMethod.Get, "/api/v1/admin/users")).Status);
        Assert.Equal(401, (await host.SendAsync(HttpMethod.Get, "/api/v1/admin/users", token: null)).Status);
        var (s, users) = await host.SendAsync(HttpMethod.Get, "/api/v1/admin/users?q=test.local", token: AdminToken);
        Assert.Equal(200, s);
        Assert.Equal(2, users!["users"]!.AsArray().Count);
        var (_, signUp) = await host.SendAsync(HttpMethod.Post, "/api/v1/auth/sign-up/email", new JsonObject { ["email"] = "c@x.io", ["password"] = "correct horse" }, token: null);
        var victim = signUp!["user"]!["id"]!.GetValue<string>();
        Assert.Equal(200, (await host.SendAsync(HttpMethod.Patch, $"/api/v1/admin/users/{victim}", new JsonObject { ["banned"] = true, ["banReason"] = "spam" }, AdminToken)).Status);
        Assert.Equal(401, (await host.SendAsync(HttpMethod.Get, "/api/v1/auth/session", token: signUp["token"]!.GetValue<string>())).Status);
        Assert.Equal(403, (await host.SendAsync(HttpMethod.Post, "/api/v1/auth/sign-in/email", new JsonObject { ["email"] = "c@x.io", ["password"] = "correct horse" }, token: null)).Status);
        var (_, stats) = await host.SendAsync(HttpMethod.Get, "/api/v1/admin/v9/stats", token: AdminToken);
        Assert.Equal(0, stats!["events"]!.GetValue<long>());
        var (_, backfill) = await host.SendAsync(HttpMethod.Post, "/api/v1/admin/v9/render-trace-backfill?dryRun=true", token: AdminToken);
        Assert.Equal(0, backfill!["scannedEvents"]!.GetValue<int>());
        var (_, analytics) = await host.SendAsync(HttpMethod.Get, "/api/v1/admin/analytics/product-events", token: AdminToken);
        Assert.NotNull(analytics!["rows"]);
    }

    [Fact]
    public async Task Memory_items_are_owner_scoped_searchable_forgettable_and_portable()
    {
        await using var host = await ServerTestHost.StartAsync(worker: false);
        static JsonObject Perception(string id, string session, string content) => new()
        {
            ["event_id"] = id, ["session_id"] = session, ["trace_id"] = $"t-{id}", ["correlation_id"] = $"t-{id}", ["timestamp"] = 1_700_000_000_000,
            ["origin_device"] = "d", ["privacy_level"] = 1, ["risk_score"] = 0.1, ["source"] = "chat", ["content"] = content,
        };
        Assert.Equal(201, (await host.SendAsync(HttpMethod.Post, "/api/v1/v9/perception", Perception("m1", "mine", "I adopted a cat named Mochi."))).Status);
        Assert.Equal(201, (await host.SendAsync(HttpMethod.Post, "/api/v1/v9/perception", Perception("m2", "mine", "I work as a nurse."))).Status);
        Assert.Equal(403, (await host.SendAsync(HttpMethod.Post, "/api/v1/v9/perception", Perception("m3", "mine", "intrusion"), AdminToken)).Status);
        var (_, all) = await host.SendAsync(HttpMethod.Get, "/api/v1/memory/items");
        Assert.Equal(2, all!["items"]!.AsArray().Count);
        var (_, found) = await host.SendAsync(HttpMethod.Get, "/api/v1/memory/items?q=mochi");
        var item = Assert.Single(found!["items"]!.AsArray())!;
        Assert.Empty((await host.SendAsync(HttpMethod.Get, "/api/v1/memory/items", token: AdminToken)).Body!["items"]!.AsArray());
        var (_, export) = await host.SendAsync(HttpMethod.Get, "/api/v1/memory/items/export");
        Assert.Equal(404, (await host.SendAsync(HttpMethod.Delete, $"/api/v1/memory/items/{item["id"]}", token: AdminToken)).Status);
        Assert.Equal(200, (await host.SendAsync(HttpMethod.Delete, $"/api/v1/memory/items/{item["id"]}")).Status);
        Assert.Single((await host.SendAsync(HttpMethod.Get, "/api/v1/memory/items")).Body!["items"]!.AsArray());
        Assert.Equal(1, await host.CountAsync("SELECT count(*) FROM audit_log_entries WHERE action = 'memory_forgotten'"));
        var (si, imported) = await host.SendAsync(HttpMethod.Post, "/api/v1/memory/items/import", export);
        Assert.Equal(200, si);
        Assert.Equal(2, imported!["imported"]!.GetValue<int>());
        Assert.Equal(3, (await host.SendAsync(HttpMethod.Get, "/api/v1/memory/items")).Body!["items"]!.AsArray().Count);
        Assert.Equal(400, (await host.SendAsync(HttpMethod.Post, "/api/v1/memory/items/import", new JsonObject { ["format"] = "x" })).Status);
    }

    // A 1×1 PNG.
    private static readonly byte[] Png = Convert.FromBase64String("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==");

    private static HttpResponseMessage Image() => new(HttpStatusCode.OK) { Content = new ByteArrayContent(Png) { Headers = { ContentType = new("image/png") } } };

    [Fact]
    public async Task Images_are_drawn_by_each_backend_charged_stored_per_owner_and_validated()
    {
        var replicatePolls = 0;
        var comfyPolls = 0;
        string? geminiKey = null;
        var upstream = new FakeUpstream((req, body) => (req.RequestUri!.Host, req.RequestUri.AbsolutePath) switch
        {
            ("bad.example", "/v1/images/generations") => Json(HttpStatusCode.OK, $$"""{"data":[{"b64_json":"{{Convert.ToBase64String(Encoding.UTF8.GetBytes("not an image"))}}"}]}"""),
            ("img.example", "/v1/images/generations") => Json(HttpStatusCode.OK, $$"""{"data":[{"b64_json":"{{Convert.ToBase64String(Png)}}"}]}"""),
            ("replicate.example", "/v1/models/acme/painter/predictions") =>
                Json(HttpStatusCode.Created, """{"id":"p1","status":"starting","urls":{"get":"https://replicate.example/v1/predictions/p1"}}"""),
            ("replicate.example", "/v1/predictions/p1") => ++replicatePolls < 2
                ? Json(HttpStatusCode.OK, """{"id":"p1","status":"processing","urls":{"get":"https://replicate.example/v1/predictions/p1"}}""")
                : Json(HttpStatusCode.OK, """{"id":"p1","status":"succeeded","output":["https://cdn.example/out.png"]}"""),
            ("cdn.example", "/out.png") => Image(),
            ("comfy.local", "/prompt") => Json(HttpStatusCode.OK, """{"prompt_id":"q1"}"""),
            ("comfy.local", "/history/q1") => ++comfyPolls < 2
                ? Json(HttpStatusCode.OK, "{}")
                : Json(HttpStatusCode.OK, """{"q1":{"status":{"status_str":"success"},"outputs":{"9":{"images":[{"filename":"a b.png","subfolder":"","type":"output"}]}}}}"""),
            ("comfy.local", "/view") => Image(),
            ("gemini.example", "/v1beta/models/gemini-2.5-flash-image:generateContent") => Gemini(req),
            ("gemini.example", "/v1beta/models/refuser:generateContent") =>
                Json(HttpStatusCode.OK, """{"promptFeedback":{"blockReason":"SAFETY"}}"""),
            _ => new HttpResponseMessage(HttpStatusCode.NotFound),
        });
        await using var host = await ServerTestHost.StartAsync(new Dictionary<string, string?> { ["Aijade:ImagePollMs"] = "5" }, worker: false,
            services: s => s.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => upstream));
        var draw = new JsonObject { ["prompt"] = "a maid serving jasmine tea" };

        Assert.Equal(503, (await host.SendAsync(HttpMethod.Post, "/api/v1/images", draw)).Status); // not configured yet
        Assert.False((await host.SendAsync(HttpMethod.Get, "/api/v1/capabilities")).Body!["images"]!.GetValue<bool>());

        async Task Configure(JsonObject images) =>
            Assert.Equal(200, (await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", new JsonObject { ["images"] = images }, AdminToken)).Status);

        // openai: base64 in the response; costs flux.
        await Configure(new JsonObject { ["kind"] = "openai", ["upstream"] = "https://img.example/v1", ["model"] = "img-1", ["keys"] = new JsonArray("sk-img"), ["fluxPerImage"] = 5 });
        Assert.True((await host.SendAsync(HttpMethod.Get, "/api/v1/capabilities")).Body!["images"]!.GetValue<bool>());
        Assert.Equal(402, (await host.SendAsync(HttpMethod.Post, "/api/v1/images", draw)).Status);
        await host.SendAsync(HttpMethod.Post, "/api/v1/admin/flux-grants", new JsonObject { ["userId"] = ServerTestHost.UserId, ["amount"] = 10 }, AdminToken);
        var (s1, made) = await host.SendAsync(HttpMethod.Post, "/api/v1/images", draw);
        Assert.Equal(201, s1);
        Assert.Equal("image/png", made!["mime"]!.GetValue<string>());
        Assert.Contains(upstream.Requests, r => r.Path == "/v1/images/generations" && r.Auth == "sk-img" && r.Body.Contains("\"img-1\"", StringComparison.Ordinal));
        Assert.Equal(5, await host.App.Services.GetRequiredService<FluxLedger>().BalanceAsync(ServerTestHost.UserId, TestContext.Current.CancellationToken));
        using (var res = await host.Client.GetAsync(made["url"]!.GetValue<string>(), TestContext.Current.CancellationToken))
        {
            Assert.Equal(HttpStatusCode.OK, res.StatusCode);
            Assert.Equal(Png, await res.Content.ReadAsByteArrayAsync(TestContext.Current.CancellationToken));
            Assert.Equal("image/png", res.Content.Headers.ContentType!.MediaType);
        }
        // Another account cannot see it.
        Assert.Equal(404, (await host.SendAsync(HttpMethod.Get, made["url"]!.GetValue<string>(), token: AdminToken)).Status);

        // replicate: an asynchronous prediction is polled until it succeeds, then the output is downloaded.
        await Configure(new JsonObject { ["kind"] = "replicate", ["upstream"] = "https://replicate.example/v1", ["model"] = "acme/painter", ["keys"] = new JsonArray("r8-key"), ["input"] = new JsonObject { ["aspect_ratio"] = "1:1" } });
        Assert.Equal(201, (await host.SendAsync(HttpMethod.Post, "/api/v1/images", draw)).Status);
        Assert.Equal(2, replicatePolls);
        Assert.Contains(upstream.Requests, r => r.Path == "/v1/models/acme/painter/predictions" && r.Body.Contains("\"aspect_ratio\":\"1:1\"", StringComparison.Ordinal)
            && r.Body.Contains("a maid serving jasmine tea", StringComparison.Ordinal));

        // comfyui: no key; the workflow's {{prompt}} placeholders are filled; history is polled; /view serves the file.
        var workflow = new JsonObject { ["6"] = new JsonObject { ["class_type"] = "CLIPTextEncode", ["inputs"] = new JsonObject { ["text"] = "masterpiece, {{prompt}}" } } };
        await Configure(new JsonObject { ["kind"] = "comfyui", ["upstream"] = "http://comfy.local", ["model"] = "sdxl", ["keys"] = new JsonArray(), ["workflow"] = workflow });
        Assert.Equal(201, (await host.SendAsync(HttpMethod.Post, "/api/v1/images", draw)).Status);
        Assert.Contains(upstream.Requests, r => r.Path == "/prompt" && r.Auth is null && r.Body.Contains("masterpiece, a maid serving jasmine tea", StringComparison.Ordinal));
        Assert.Contains(upstream.Requests, r => r.Path == "/view");

        // gemini (Nano Banana): key in x-goog-api-key (not Bearer), the size as an aspect ratio, the image inline as base64.
        await Configure(new JsonObject { ["kind"] = "gemini", ["upstream"] = "https://gemini.example/v1beta", ["model"] = "gemini-2.5-flash-image", ["keys"] = new JsonArray("AIza-test") });
        var (sg, gem) = await host.SendAsync(HttpMethod.Post, "/api/v1/images", new JsonObject { ["prompt"] = "a maid serving jasmine tea", ["size"] = "1792x1024" });
        Assert.Equal(201, sg);
        Assert.Equal("image/png", gem!["mime"]!.GetValue<string>());
        Assert.Equal("AIza-test", geminiKey);
        Assert.Contains(upstream.Requests, r => r.Path.EndsWith(":generateContent", StringComparison.Ordinal) && r.Auth is null
            && r.Body.Contains("\"aspectRatio\":\"16:9\"", StringComparison.Ordinal) && r.Body.Contains("\"responseModalities\":[\"IMAGE\"]", StringComparison.Ordinal)
            && r.Body.Contains("a maid serving jasmine tea", StringComparison.Ordinal));
        // A refusal is reported with its reason and nothing is stored or charged.
        await Configure(new JsonObject { ["kind"] = "gemini", ["upstream"] = "https://gemini.example/v1beta", ["model"] = "refuser", ["keys"] = new JsonArray("AIza-test") });
        var (sr, refused) = await host.SendAsync(HttpMethod.Post, "/api/v1/images", draw);
        Assert.Equal(422, sr);
        Assert.Contains("SAFETY", refused!.ToJsonString(), StringComparison.Ordinal);

        var (_, list) = await host.SendAsync(HttpMethod.Get, "/api/v1/images");
        Assert.Equal(4, list!["images"]!.AsArray().Count);
        Assert.Equal(204, (await host.SendAsync(HttpMethod.Delete, made["url"]!.GetValue<string>())).Status);
        Assert.Equal(404, (await host.SendAsync(HttpMethod.Get, made["url"]!.GetValue<string>())).Status);

        // Bad input and bad configuration are refused.
        Assert.Equal(400, (await host.SendAsync(HttpMethod.Post, "/api/v1/images", new JsonObject { ["prompt"] = " " })).Status);
        Assert.Equal(400, (await host.SendAsync(HttpMethod.Post, "/api/v1/images", new JsonObject { ["prompt"] = "x", ["size"] = "huge" })).Status);
        Assert.Equal(400, (await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", new JsonObject { ["images"] = new JsonObject { ["kind"] = "dalle9", ["upstream"] = "https://x.example" } }, AdminToken)).Status);
        Assert.Equal(400, (await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", new JsonObject { ["images"] = new JsonObject { ["kind"] = "comfyui", ["upstream"] = "http://comfy.local" } }, AdminToken)).Status);
        // An upstream that answers with something other than an image is a 502, not a stored file.
        await Configure(new JsonObject { ["kind"] = "openai", ["upstream"] = "https://bad.example/v1", ["model"] = "img-1", ["keys"] = new JsonArray("sk-img") });
        Assert.Equal(502, (await host.SendAsync(HttpMethod.Post, "/api/v1/images", draw)).Status);
        Assert.Equal(3, (await host.SendAsync(HttpMethod.Get, "/api/v1/images")).Body!["images"]!.AsArray().Count);

        HttpResponseMessage Gemini(HttpRequestMessage req)
        {
            geminiKey = req.Headers.TryGetValues("x-goog-api-key", out var v) ? v.Single() : null;
            return Json(HttpStatusCode.OK, $$$"""{"candidates":[{"content":{"parts":[{"text":"Here you go."},{"inlineData":{"mimeType":"image/png","data":"{{{Convert.ToBase64String(Png)}}}"}}]},"finishReason":"STOP"}]}""");
        }
    }

    [Fact]
    public async Task Aliyun_native_speech_qwen_tts_downloads_the_audio_and_cosyvoice_speaks_the_duplex_protocol()
    {
        var ct = TestContext.Current.CancellationToken;
        var wav = "RIFF\0\0\0\0WAVEfmt "u8.ToArray();
        var upstream = new FakeUpstream((req, body) => (req.RequestUri!.Host, req.RequestUri.AbsolutePath) switch
        {
            ("dashscope.example", "/api/v1/services/aigc/multimodal-generation/generation") =>
                Json(HttpStatusCode.OK, """{"output":{"audio":{"url":"https://dashscope-result.example/tts/a.wav","expires_at":1},"finish_reason":"stop"},"request_id":"r1"}"""),
            ("dashscope-result.example", "/tts/a.wav") => new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent(wav) { Headers = { ContentType = new("audio/wav") } } },
            _ => new HttpResponseMessage(HttpStatusCode.NotFound),
        });

        // A CosyVoice stand-in that follows the published task protocol over a real WebSocket.
        var handshakes = new List<string>();
        var texts = new List<string>();
        var b = Microsoft.AspNetCore.Builder.WebApplication.CreateSlimBuilder();
        Microsoft.AspNetCore.Hosting.HostingAbstractionsWebHostBuilderExtensions.UseUrls(b.WebHost, "http://127.0.0.1:0");
        await using var cosy = b.Build();
        cosy.UseWebSockets();
        cosy.Map("/api-ws/v1/inference", async (Microsoft.AspNetCore.Http.HttpContext c) =>
        {
            var auth = c.Request.Headers.Authorization.ToString();
            lock (handshakes)
                handshakes.Add(auth);
            if (auth != "bearer good-key")
            {
                c.Response.StatusCode = 401;
                return;
            }
            using var ws = await c.WebSockets.AcceptWebSocketAsync();
            var buffer = new byte[8192];
            async Task<JsonNode> Receive() { var r = await ws.ReceiveAsync(buffer, ct); return JsonNode.Parse(Encoding.UTF8.GetString(buffer, 0, r.Count))!; }
            async Task Event(string name, string taskId, string extra = "") =>
                await ws.SendAsync(Encoding.UTF8.GetBytes("{\"header\":{\"task_id\":\"" + taskId + "\",\"event\":\"" + name + "\"" + extra + "},\"payload\":{}}"), System.Net.WebSockets.WebSocketMessageType.Text, true, ct);
            var run = await Receive();
            var taskId = run["header"]!["task_id"]!.GetValue<string>();
            Assert.Equal("run-task", run["header"]!["action"]!.GetValue<string>());
            if (run["payload"]!["model"]!.GetValue<string>() == "fail-model")
            {
                await Event("task-failed", taskId, ",\"error_code\":\"InvalidParameter\",\"error_message\":\"bad voice\"");
                return;
            }
            await Event("task-started", taskId);
            var cont = await Receive();
            lock (texts)
                texts.Add(cont["payload"]!["input"]!["text"]!.GetValue<string>());
            Assert.Equal("finish-task", (await Receive())["header"]!["action"]!.GetValue<string>());
            await ws.SendAsync(new byte[] { 0xFF, 0xFB, 1 }, System.Net.WebSockets.WebSocketMessageType.Binary, true, ct);
            await Event("result-generated", taskId);
            await ws.SendAsync(new byte[] { 2, 3 }, System.Net.WebSockets.WebSocketMessageType.Binary, true, ct);
            await Event("task-finished", taskId);
            try { await ws.ReceiveAsync(buffer, ct); } catch (System.Net.WebSockets.WebSocketException) { }
        });
        await cosy.StartAsync(ct);
        var wsUrl = cosy.Urls.First().Replace("http://", "ws://", StringComparison.Ordinal) + "/api-ws/v1/inference";

        await using var host = await ServerTestHost.StartAsync(worker: false, services: s => s.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => upstream));
        async Task<(int Status, byte[] Audio, string? Mime)> Speak(string text)
        {
            // The client sends its OpenAI-style default voice; the route's provider-specific voice must win.
            using var req = new HttpRequestMessage(HttpMethod.Post, "/api/v1/openai/v1/audio/speech") { Content = new StringContent(new JsonObject { ["input"] = text, ["voice"] = "alloy" }.ToJsonString(), Encoding.UTF8, "application/json") };
            using var res = await host.Client.SendAsync(req, ct);
            return ((int)res.StatusCode, await res.Content.ReadAsByteArrayAsync(ct), res.Content.Headers.ContentType?.MediaType);
        }
        async Task Configure(JsonObject speech) =>
            Assert.Equal(200, (await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", new JsonObject { ["speech"] = speech }, AdminToken)).Status);

        // Qwen-TTS: the native request carries model, text and voice; the signed URL in the answer is downloaded without the key.
        await Configure(new JsonObject { ["kind"] = "aliyun-qwen-tts", ["upstream"] = "https://dashscope.example/api/v1", ["model"] = "qwen-tts", ["voice"] = "Cherry", ["keys"] = new JsonArray("sk-ds") });
        var qwen = await Speak("你好，我是艾娅德。");
        Assert.Equal((200, "audio/wav"), (qwen.Status, qwen.Mime));
        Assert.Equal(wav, qwen.Audio);
        var call = upstream.Requests.Single(r => r.Path.EndsWith("/generation", StringComparison.Ordinal));
        Assert.Equal("sk-ds", call.Auth);
        Assert.Contains("\"voice\":\"Cherry\"", call.Body, StringComparison.Ordinal);
        Assert.Contains("\"model\":\"qwen-tts\"", call.Body, StringComparison.Ordinal);
        Assert.Null(upstream.Requests.Single(r => r.Path == "/tts/a.wav").Auth);

        // CosyVoice: a refused key alone is a 502; with a good key beside it every request succeeds whichever key the rotation
        // tries first. The audio frames are joined in order and the text is sent once per request.
        await Configure(new JsonObject { ["kind"] = "aliyun-cosyvoice", ["upstream"] = wsUrl, ["model"] = "cosyvoice-v2", ["voice"] = "longxiaochun_v2", ["keys"] = new JsonArray("bad-key") });
        Assert.Equal(502, (await Speak("晚上好。")).Status);
        Assert.Equal(["bearer bad-key"], handshakes);
        await Configure(new JsonObject { ["kind"] = "aliyun-cosyvoice", ["upstream"] = wsUrl, ["model"] = "cosyvoice-v2", ["voice"] = "longxiaochun_v2", ["keys"] = new JsonArray("bad-key", "good-key") });
        foreach (var _ in Enumerable.Range(0, 2))
        {
            var cosyVoice = await Speak("晚上好。");
            Assert.Equal((200, "audio/mpeg"), (cosyVoice.Status, cosyVoice.Mime));
            Assert.Equal(new byte[] { 0xFF, 0xFB, 1, 2, 3 }, cosyVoice.Audio);
        }
        Assert.Equal(["晚上好。", "晚上好。"], texts);

        // A failed task is a 502 with the provider's error code, not an empty audio file.
        await Configure(new JsonObject { ["kind"] = "aliyun-cosyvoice", ["upstream"] = wsUrl, ["model"] = "fail-model", ["keys"] = new JsonArray("good-key") });
        var failed = await Speak("hi");
        Assert.Equal(502, failed.Status);
        Assert.Contains("InvalidParameter", Encoding.UTF8.GetString(failed.Audio), StringComparison.Ordinal);
    }

    /// <summary>Toy embeddings: one dimension per topic, so "kitten" and "cat" are close and "pizza" is far.</summary>
    private static float[] Topic(string text)
    {
        var t = text.ToLowerInvariant();
        return [t.Contains("cat", StringComparison.Ordinal) || t.Contains("kitten", StringComparison.Ordinal) || t.Contains('猫', StringComparison.Ordinal) ? 1f : 0f,
                t.Contains("pizza", StringComparison.Ordinal) || t.Contains("food", StringComparison.Ordinal) ? 1f : 0f,
                0.05f];
    }

    [Fact]
    public async Task Memory_search_goes_by_meaning_with_embeddings_and_speech_routes_reach_their_providers()
    {
        var ct = TestContext.Current.CancellationToken;
        var embedCalls = 0;
        var upstream = new FakeUpstream((req, body) =>
        {
            switch (req.RequestUri!.AbsolutePath)
            {
                case "/v1/embeddings":
                    Interlocked.Increment(ref embedCalls);
                    var input = JsonNode.Parse(body)!["input"]!.AsArray().Select(i => i!.GetValue<string>()).ToList();
                    var data = new JsonArray([.. input.Select((x, i) => (JsonNode)new JsonObject { ["index"] = i, ["embedding"] = new JsonArray([.. Topic(x).Select(v => (JsonNode)v)]) })]);
                    return Json(HttpStatusCode.OK, new JsonObject { ["data"] = data, ["usage"] = new JsonObject { ["total_tokens"] = 10 } }.ToJsonString());
                case "/v1/audio/transcriptions":
                    return Json(HttpStatusCode.OK, """{"text":"hello from the recognizer"}""");
                case "/v1/text-to-speech/voice-9":
                    return new HttpResponseMessage(HttpStatusCode.OK) { Content = new ByteArrayContent([1, 2, 3]) { Headers = { ContentType = new("audio/mpeg") } } };
                default:
                    return new HttpResponseMessage(HttpStatusCode.NotFound);
            }
        });
        await using var host = await ServerTestHost.StartAsync(worker: false,
            services: s => s.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => upstream));
        static JsonObject Perception(string id, string text) => new()
        {
            ["event_id"] = id, ["session_id"] = "mem", ["trace_id"] = $"t-{id}", ["correlation_id"] = $"t-{id}", ["timestamp"] = 1_790_000_000_000,
            ["origin_device"] = "test", ["privacy_level"] = 1, ["risk_score"] = 0.1, ["source"] = "chat", ["content"] = text,
        };
        await host.SendAsync(HttpMethod.Post, "/api/v1/v9/perception", Perception("e1", "I adopted a cat named Mochi."));
        await host.SendAsync(HttpMethod.Post, "/api/v1/v9/perception", Perception("e2", "My favourite food is pizza."));

        // Without an embeddings route: text search ("kitten" appears nowhere).
        Assert.Empty((await host.SendAsync(HttpMethod.Get, "/api/v1/memory/items?q=kitten")).Body!["items"]!.AsArray());

        var routes = new JsonObject { ["embeddings"] = new JsonObject { ["upstream"] = "https://emb.example/v1", ["model"] = "toy-1", ["keys"] = new JsonArray("k") } };
        Assert.Equal(200, (await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", routes, AdminToken)).Status);
        var found = (await host.SendAsync(HttpMethod.Get, "/api/v1/memory/items?q=tell%20me%20about%20my%20kitten")).Body!["items"]!.AsArray();
        Assert.Equal("I adopted a cat named Mochi.", Assert.Single(found)!["content"]!.GetValue<string>());
        Assert.Equal(2, await host.CountAsync("SELECT count(*) FROM evidence_chunks WHERE embedding IS NOT NULL AND embedding_model = 'toy-1'"));
        var calls = embedCalls;
        await host.SendAsync(HttpMethod.Get, "/api/v1/memory/items?q=pizza%20night");
        Assert.Equal(calls + 1, embedCalls); // stored vectors are reused: only the query is embedded
        routes["embeddings"]!["model"] = "toy-2";
        await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", routes, AdminToken);
        await host.SendAsync(HttpMethod.Get, "/api/v1/memory/items?q=cats");
        Assert.Equal(2, await host.CountAsync("SELECT count(*) FROM evidence_chunks WHERE embedding_model = 'toy-2'")); // a new model re-embeds
        var (_, direct) = await host.SendAsync(HttpMethod.Post, "/api/v1/openai/v1/embeddings", new JsonObject { ["input"] = new JsonArray("cat", "pizza") });
        Assert.Equal(2, direct!["data"]!.AsArray().Count);

        // Speech recognition: the uploaded utterance is passed on as multipart with the route's model.
        routes["transcription"] = new JsonObject { ["upstream"] = "https://asr.example/v1", ["model"] = "whisper-x", ["keys"] = new JsonArray("asr-key") };
        routes["speech"] = new JsonObject { ["kind"] = "elevenlabs", ["upstream"] = "https://api.elevenlabs.io", ["model"] = "eleven_multilingual_v2", ["voice"] = "voice-9", ["keys"] = new JsonArray("xi-key") };
        await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", routes, AdminToken);
        using (var form = new MultipartFormDataContent())
        {
            form.Add(new ByteArrayContent([1, 2, 3, 4]) { Headers = { ContentType = new("audio/webm") } }, "file", "speech.webm");
            form.Add(new StringContent("en"), "language");
            using var req = new HttpRequestMessage(HttpMethod.Post, "/api/v1/openai/v1/audio/transcriptions") { Content = form };
            using var res = await host.Client.SendAsync(req, ct);
            Assert.Equal("hello from the recognizer", JsonNode.Parse(await res.Content.ReadAsStringAsync(ct))!["text"]!.GetValue<string>());
        }
        var asr = upstream.Requests.Single(r => r.Path == "/v1/audio/transcriptions");
        Assert.Equal("asr-key", asr.Auth);
        Assert.Contains("whisper-x", asr.Body, StringComparison.Ordinal);

        // ElevenLabs: key in xi-api-key (never as a bearer token), voice in the path.
        using (var res = await host.Client.PostAsync("/api/v1/openai/v1/audio/speech", new StringContent("""{"input":"hello"}""", Encoding.UTF8, "application/json"), ct))
            Assert.Equal([1, 2, 3], await res.Content.ReadAsByteArrayAsync(ct));
        var tts = upstream.Requests.Single(r => r.Path == "/v1/text-to-speech/voice-9");
        Assert.Null(tts.Auth);
        Assert.Contains("\"model_id\":\"eleven_multilingual_v2\"", tts.Body, StringComparison.Ordinal);
    }
}
