using System.Collections.Concurrent;
using System.Net;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Bots;
using Aijade.Client.Api;
using Aijade.Client.Companion;
using Aijade.Integrations;

using Microsoft.Extensions.Configuration;
using Microsoft.Playwright;

using static Microsoft.Playwright.Assertions;

namespace Aijade.E2E;

public sealed partial class CompanionExperienceWebTests
{
    private static async Task PersistProfileAsync(IPage page, string button)
    {
        var response = await page.RunAndWaitForResponseAsync(() => page.GetByRole(AriaRole.Button, new() { Name = button, Exact = true }).ClickAsync(),
            r => r.Request.Method == "PUT" && r.Url.EndsWith("/profile", StringComparison.Ordinal));
        Assert.Equal(200, response.Status);
        await Expect(page.GetByRole(AriaRole.Status)).ToHaveTextAsync("Saved to your collection");
    }

    [Fact]
    public async Task Web_and_signed_QQ_events_share_live_roles_location_relationship_and_collections()
    {
        host.RequireEnabled();
        var ct = TestContext.Current.CancellationToken;
        var (page, _) = await host.SignUpAsync("Sync owner");
        using var ownerHttp = new HttpClient { BaseAddress = host.BaseUrl };
        var ownerTokens = new MemoryTokenStore();
        await ownerTokens.SetAsync(await page.EvaluateAsync<string>("localStorage.getItem('aijade.session')"));
        var ownerApi = new AijadeApi(ownerHttp, ownerTokens); var sync = new CompanionSync(ownerApi);
        using var relayHttp = new HttpClient { BaseAddress = host.BaseUrl };
        var relayTokens = new MemoryTokenStore(); await relayTokens.SetAsync(E2EHost.AdminToken);
        var relayApi = new AijadeApi(relayHttp, relayTokens);
        await using var qq = new LocalQqHarness(relayApi, ct);
        try
        {
            // Create and select a private persona through the actual character editor.
            await page.GetByRole(AriaRole.Link, new() { Name = "Characters" }).ClickAsync();
            await page.GetByLabel("Name", new() { Exact = true }).FillAsync("Sync star");
            await page.GetByLabel("Persona", new() { Exact = true }).FillAsync("SYNC-PERSONA-ONE: I enjoy telescopes.");
            await page.GetByRole(AriaRole.Button, new() { Name = "Save", Exact = true }).ClickAsync();
            var card = page.Locator(".card").Filter(new() { Has = page.GetByRole(AriaRole.Heading, new() { Name = "Sync star", Exact = true }) });
            await card.GetByRole(AriaRole.Button, new() { Name = "Talk to this character" }).ClickAsync();
            await page.GetByPlaceholder("Say something…").WaitForAsync();
            await page.GetByRole(AriaRole.Link, new() { Name = "Companion life" }).ClickAsync();
            await page.GetByLabel("Home", new() { Exact = true }).FillAsync("SYNC-HOME-ONE");
            await page.GetByLabel("Interests (comma separated)").FillAsync("SYNC-TELESCOPE");
            await PersistProfileAsync(page, "Save");
            await page.GetByLabel("City label").FillAsync("SYNC-CITY-ONE");
            await page.GetByLabel("Time zone (blank uses the shared server clock)").FillAsync("Asia/Seoul");
            await PersistProfileAsync(page, "Save location and time zone");
            await page.GetByPlaceholder("Name / song title").FillAsync("Web smile");
            await page.Locator("input[type=file]").SetInputFilesAsync(new FilePayload { Name = "smile.png", MimeType = "image/png", Buffer = Convert.FromBase64String(FakeUpstream.PngBase64) });
            await Expect(page.Locator(".companion-asset")).ToHaveCountAsync(1);
            await page.GetByRole(AriaRole.Button, new() { Name = "Generate QQ pairing code" }).ClickAsync();
            var command = await page.Locator("code").InnerTextAsync();
            await qq.SendAsync(command, ct);
            await LocalQqHarness.WaitAsync(() => qq.Texts.Any(t => t.Contains("同步绑定完成", StringComparison.Ordinal)), ct);
            Assert.Empty(await relayApi.ChatsAsync(ct)); // binding secrets never enter a conversation
            await Expect(page.GetByRole(AriaRole.Button, new() { Name = "Unlink QQ" })).ToBeVisibleAsync();

            var before = qq.Texts.Count;
            await qq.SendAsync("谢谢你，今天过得怎么样？", ct);
            await LocalQqHarness.WaitAsync(() => qq.Texts.Count > before && qq.Images > 0, ct);
            var prompt = host.Llm.ChatRequests[^1]["messages"]![0]!["content"]!.GetValue<string>();
            Assert.Contains("SYNC-PERSONA-ONE", prompt, StringComparison.Ordinal);
            Assert.Contains("SYNC-TELESCOPE", prompt, StringComparison.Ordinal);
            Assert.Contains("SYNC-CITY-ONE", prompt, StringComparison.Ordinal); Assert.Contains("Asia/Seoul", prompt, StringComparison.Ordinal);
            var shared = await sync.CurrentAsync(ct); var firstRole = shared.CharacterId;
            Assert.Equal("SYNC-CITY-ONE", shared.Profile.City); Assert.Equal("Asia/Seoul", shared.EffectiveTimeZone);
            Assert.Equal(1, shared.Notebook.Relationship.Interactions);
            await Expect(page.GetByText("Relationship：", new() { Exact = false })).ToContainTextAsync("31.0/100");

            // The running QQ connector imports into the same collection; the open Web page sees it without reloading.
            await qq.SendAsync("/sticker joy QQ smile", ct, picture: true);
            await Expect(page.Locator(".companion-asset")).ToHaveCountAsync(2);
            var qqItem = page.Locator(".companion-asset").Filter(new() { HasText = "QQ smile" });
            await qqItem.GetByRole(AriaRole.Button, new() { Name = "Remove" }).ClickAsync();
            await Expect(page.Locator(".companion-asset")).ToHaveCountAsync(1);
            Assert.Single((await sync.CurrentAsync(ct)).Notebook.Assets);

            // Edit both the character card and shared location while the same bridge and connector keep running.
            await page.GetByRole(AriaRole.Link, new() { Name = "Characters" }).ClickAsync();
            await card.GetByRole(AriaRole.Button, new() { Name = "✎", Exact = true }).ClickAsync();
            await page.GetByLabel("Persona", new() { Exact = true }).FillAsync("SYNC-PERSONA-TWO: I now prefer painting.");
            await page.GetByRole(AriaRole.Button, new() { Name = "Save", Exact = true }).ClickAsync();
            await Expect(page.GetByLabel("Persona", new() { Exact = true })).ToHaveValueAsync("");
            await page.GetByRole(AriaRole.Link, new() { Name = "Companion life" }).ClickAsync();
            await page.GetByLabel("City label").FillAsync("SYNC-CITY-TWO");
            await page.GetByLabel("Time zone (blank uses the shared server clock)").FillAsync("Asia/Tokyo");
            await PersistProfileAsync(page, "Save location and time zone");
            before = qq.Texts.Count;
            await qq.SendAsync("我们继续刚才的话题", ct);
            await LocalQqHarness.WaitAsync(() => qq.Texts.Count > before, ct);
            prompt = host.Llm.ChatRequests[^1]["messages"]![0]!["content"]!.GetValue<string>();
            Assert.Contains("SYNC-PERSONA-TWO", prompt, StringComparison.Ordinal); Assert.DoesNotContain("SYNC-PERSONA-ONE", prompt, StringComparison.Ordinal);
            Assert.Contains("SYNC-CITY-TWO", prompt, StringComparison.Ordinal); Assert.Contains("Asia/Tokyo", prompt, StringComparison.Ordinal);
            var resolved = await qq.Configuration.ForAsync(LocalQqHarness.Contact, ct);
            Assert.Equal("SYNC-CITY-TWO", resolved!.Experience.Profile.City); Assert.Equal("Asia/Tokyo", resolved.Experience.Profile.TimeZone);

            // A Web turn contributes to the same relationship, and the response persists across reloads.
            await page.GetByRole(AriaRole.Link, new() { Name = "Chat" }).ClickAsync();
            await page.GetByPlaceholder("Say something…").FillAsync("谢谢你，网页也来聊聊");
            await page.GetByRole(AriaRole.Button, new() { Name = "Send", Exact = true }).ClickAsync();
            await Expect(page.Locator(".bubble.assistant").Last).ToHaveTextAsync(FakeUpstream.Reply);
            await page.ReloadAsync();
            await Expect(page.Locator(".bubble.assistant").Last).ToHaveTextAsync(FakeUpstream.Reply);
            Assert.Equal(3, (await sync.CurrentAsync(ct)).Notebook.Relationship.Interactions);

            var second = await ownerApi.CreateCharacterAsync(new { name = "Separate role", persona = "SYNC-SEPARATE-ROLE" }, ct);
            await sync.SelectAsync(second.Id, ct);
            before = qq.Texts.Count;
            await qq.SendAsync("你好，新角色", ct);
            await LocalQqHarness.WaitAsync(() => qq.Texts.Count > before, ct);
            Assert.Contains("SYNC-SEPARATE-ROLE", host.Llm.ChatRequests[^1].ToJsonString(), StringComparison.Ordinal);
            var newState = await sync.CurrentAsync(ct); Assert.Equal(1, newState.Notebook.Relationship.Interactions); Assert.Empty(newState.Notebook.Assets);
            // An already-open Web chat also moves to a clean conversation before the next turn after a remote switch.
            await page.GetByPlaceholder("Say something…").FillAsync("Web new role hello");
            await page.GetByRole(AriaRole.Button, new() { Name = "Send", Exact = true }).ClickAsync();
            await Expect(page.Locator(".bubble.user")).ToHaveTextAsync("Web new role hello");
            await Expect(page.Locator(".bubble.assistant").Last).ToHaveTextAsync(FakeUpstream.Reply);
            Assert.Contains("SYNC-SEPARATE-ROLE", host.Llm.ChatRequests[^1]["messages"]![0]!["content"]!.GetValue<string>(), StringComparison.Ordinal);
            Assert.DoesNotContain("谢谢你，网页也来聊聊", host.Llm.ChatRequests[^1].ToJsonString(), StringComparison.Ordinal);
            Assert.Equal(2, (await sync.CurrentAsync(ct)).Notebook.Relationship.Interactions);
            Assert.Equal(3, (await sync.ReadAsync(firstRole, ct: ct)).Notebook.Relationship.Interactions);

            await page.GetByRole(AriaRole.Link, new() { Name = "Companion life" }).ClickAsync();
            await Expect(page.GetByRole(AriaRole.Button, new() { Name = "Unlink QQ" })).ToBeEnabledAsync();
            if (Environment.GetEnvironmentVariable("AIJADE_SYNC_SCREENSHOT") is { Length: > 0 } screenshot)
                await page.ScreenshotAsync(new() { Path = screenshot, FullPage = true });
            await page.GetByRole(AriaRole.Button, new() { Name = "Unlink QQ" }).ClickAsync();
            await Expect(page.GetByRole(AriaRole.Button, new() { Name = "Unlink QQ" })).ToHaveCountAsync(0);
            Assert.Null(await new CompanionSync(relayApi).ResolveAsync(LocalQqHarness.Owner, ct));
            resolved = await qq.Configuration.ForAsync(LocalQqHarness.Contact, ct);
            Assert.NotEqual(newState.OwnerId, resolved!.Identity.Split(':')[0]);
            Assert.Empty((await resolved.Experience.Notebook.ReadAsync(ct: ct)).Assets);
        }
        finally { await page.Context.CloseAsync(); }
    }
}

/// <summary>Actual signed OneBot HTTP ingress and production bridge; only NapCat delivery and its CDN are fixtures.</summary>
internal sealed class LocalQqHarness : IAsyncDisposable
{
    public const string Owner = "123456789";
    private const string Secret = "local-test-event-secret";
    public static ChannelMessage Contact => new("qq", Owner, Owner, "Sync owner", "", true, true);
    private readonly CancellationTokenSource stop;
    private readonly HttpClient events;
    private readonly HttpClient napcat;
    private readonly CompanionBridge bridge;
    private readonly Task running;
    private readonly string directory = Path.Combine(Path.GetTempPath(), "aijade-sync-e2e-" + Guid.NewGuid().ToString("N"));
    private readonly NapCatFixture delivery = new();
    public string ReplyMode { get => delivery.Mode; set => delivery.Mode = value; }
    public CompanionConfiguration Configuration { get; }
    public IReadOnlyList<string> Texts => [.. delivery.Calls.SelectMany(c => c["message"]!.AsArray()).Where(s => s!["type"]!.GetValue<string>() == "text").Select(s => s!["data"]!["text"]!.GetValue<string>())];
    public int Images => delivery.Calls.SelectMany(c => c["message"]!.AsArray()).Count(s => s!["type"]!.GetValue<string>() == "image");

    public LocalQqHarness(AijadeApi api, CancellationToken ct)
    {
        stop = CancellationTokenSource.CreateLinkedTokenSource(ct);
        Configuration = new(new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?> { ["Bridge:StateFile"] = Path.Combine(directory, "bridge.json") }).Build(), api);
        bridge = new(api, new BridgeOptions { Memory = false, Drawing = true, StateFile = Path.Combine(directory, "bridge.json"), ResolveCompanion = Configuration.ForAsync, PairCompanion = Configuration.PairAsync });
        var listener = new TcpListener(IPAddress.Loopback, 0); listener.Start(); var port = ((IPEndPoint)listener.LocalEndpoint).Port; listener.Stop();
        events = new() { BaseAddress = new Uri($"http://127.0.0.1:{port}/") }; napcat = new(delivery);
        var connector = new OneBotConnector(port, new Uri("http://127.0.0.1:3000"), "local-test-napcat-token", Secret, Owner, napcat,
            companionSource: async token => (await Configuration.ForAsync(Contact, token))!.Experience);
        running = connector.RunAsync(bridge.AnswerAsync, stop.Token);
    }
    public async Task SendAsync(string text, CancellationToken ct, bool picture = false)
    {
        var segments = new JsonArray(new JsonObject { ["type"] = "text", ["data"] = new JsonObject { ["text"] = text } });
        if (picture) segments.Add(new JsonObject { ["type"] = "image", ["data"] = new JsonObject { ["file"] = "fixture", ["url"] = "https://gchat.qpic.cn/fixture.png" } });
        var body = Encoding.UTF8.GetBytes(new JsonObject { ["post_type"] = "message", ["message_type"] = "private", ["user_id"] = long.Parse(Owner, System.Globalization.CultureInfo.InvariantCulture), ["self_id"] = 42, ["message"] = segments }.ToJsonString());
        using var request = new HttpRequestMessage(HttpMethod.Post, "") { Content = new ByteArrayContent(body) };
        request.Content.Headers.ContentType = new("application/json");
#pragma warning disable CA5350 // OneBot 11 specifies HMAC-SHA1.
        request.Headers.Add("X-Signature", "sha1=" + Convert.ToHexStringLower(HMACSHA1.HashData(Encoding.UTF8.GetBytes(Secret), body)));
#pragma warning restore CA5350
        using var response = await events.SendAsync(request, ct); Assert.Equal(HttpStatusCode.NoContent, response.StatusCode);
    }
    public static async Task WaitAsync(Func<bool> ready, CancellationToken ct)
    {
        var until = DateTimeOffset.UtcNow.AddSeconds(30);
        while (!ready() && DateTimeOffset.UtcNow < until) await Task.Delay(50, ct);
        Assert.True(ready(), "The local OneBot round trip did not complete");
    }
    public async ValueTask DisposeAsync()
    {
        await stop.CancelAsync(); await running; bridge.Dispose(); events.Dispose(); napcat.Dispose(); stop.Dispose();
        if (Directory.Exists(directory)) Directory.Delete(directory, recursive: true);
    }
    private sealed class NapCatFixture : HttpMessageHandler
    {
        public ConcurrentQueue<JsonObject> Calls { get; } = new();
        public string Mode { get; set; } = "ok";
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            if (request.Method == HttpMethod.Get)
                return new(HttpStatusCode.OK) { Content = new ByteArrayContent(Convert.FromBase64String(FakeUpstream.PngBase64)) { Headers = { ContentType = new("image/png") } } };
            var body = (JsonObject)JsonNode.Parse(await request.Content!.ReadAsStringAsync(cancellationToken))!;
            Assert.Equal("local-test-napcat-token", request.Headers.Authorization?.Parameter); Calls.Enqueue(body);
            var response = Mode switch
            {
                "failed" => "{\"status\":\"failed\",\"retcode\":100,\"data\":null}",
                "missing-id" => "{\"status\":\"ok\",\"retcode\":0,\"data\":{}}",
                _ => "{\"status\":\"ok\",\"retcode\":0,\"data\":{\"message_id\":7}}",
            };
            return new(HttpStatusCode.OK) { Content = new StringContent(response, Encoding.UTF8, "application/json") };
        }
    }
}
