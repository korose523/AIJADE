using System.Globalization;
using System.Net;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Bots;
using Aijade.Client.Api;
using Aijade.Client.Companion;
using Aijade.Integrations;
using Aijade.Server.Product;

using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace Aijade.Tests;

/// <summary>Production scheduling, source storage and QQ dispatch; only the model and NapCat are local fixtures.</summary>
public sealed class ProactiveDeliveryTests
{
    private const string Subject = "123456789";
    private static readonly ChannelMessage Contact = new("qq", Subject, Subject, "Owner", "今天有点紧张，陪我聊聊", true, true);

    [Fact]
    public async Task First_lines_retain_their_stored_identity_and_share_the_ordinary_reply_delivery_path()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var f = await Fixture.StartAsync(ct);
        var reply = Assert.IsType<ChannelReply>(await f.Bridge.AnswerAsync(Contact, ct));
        await f.Reach["qq"].SendReplyAsync(Subject, reply, ct);
        f.Time.Advance(TimeSpan.FromSeconds(600));
        Assert.Equal(1, await ConnectorHost.SpeakFirstOnceAsync(f.Bridge, f.Reach, ct));
        var entries = (await f.Sync.DeliveriesAsync(null, ct)).Entries;
        Assert.Equal(2, entries.Count);
        var initiative = Assert.Single(entries, e => e.Kind == "initiative");
        Assert.Null(initiative.TriggerId); Assert.Equal("acknowledged", initiative.State);
        Assert.Equal("reply", Assert.Single(entries, e => e.Id != initiative.Id).Kind);
        var chat = Assert.Single(await f.Relay.ChatsAsync(ct));
        var stored = (await f.Relay.MessagesAsync(chat.Id, ct: ct)).Single(m => m.Id == initiative.MessageId);
        Assert.NotNull(stored.Meta?["initiative"]);
        var calls = f.Model.Calls; var sends = f.NapCat.Calls;
        Assert.Equal(0, await ConnectorHost.SpeakFirstOnceAsync(f.Bridge, f.Reach, ct));
        Assert.Equal(calls, f.Model.Calls); Assert.Equal(sends, f.NapCat.Calls);
    }

    [Theory]
    [InlineData("ok", "acknowledged")]
    [InlineData("failed", "rejected")]
    [InlineData("missing-id", "unknown")]
    public async Task Due_reminders_record_acceptance_and_recover_a_stored_line_without_regenerating_or_resending(string mode, string state)
    {
        var ct = TestContext.Current.CancellationToken;
        await using var f = await Fixture.StartAsync(ct);
        var reply = Assert.IsType<ChannelReply>(await f.Bridge.AnswerAsync(Contact with { Text = "十分钟后提醒我喝水" }, ct));
        await f.Reach["qq"].SendReplyAsync(Subject, reply, ct);
        // Restore this file after dispatch to model a stop between storing the line and consuming its local promise.
        var pending = await File.ReadAllBytesAsync(f.StateFile + ".reminders.json", ct);
        f.Time.Advance(TimeSpan.FromSeconds(600)); f.NapCat.Mode = mode;
        if (mode == "ok") Assert.Equal(1, await ConnectorHost.RemindOnceAsync(f.Bridge, f.Reach, ct));
        else await Assert.ThrowsAsync<OneBotSendException>(() => ConnectorHost.RemindOnceAsync(f.Bridge, f.Reach, ct));
        var entry = Assert.Single((await f.Sync.DeliveriesAsync(null, ct)).Entries, e => e.Kind == "reminder");
        Assert.Equal(state, entry.State); Assert.False(string.IsNullOrWhiteSpace(entry.TriggerId));
        var chat = Assert.Single(await f.Relay.ChatsAsync(ct));
        var source = (await f.Relay.MessagesAsync(chat.Id, ct: ct)).Single(m => m.Id == entry.MessageId);
        Assert.Equal(entry.TriggerId, source.Meta!["reminder"]!["id"]!.GetValue<string>());
        Assert.Equal(0, await ConnectorHost.RemindOnceAsync(f.Bridge, f.Reach, ct));
        var calls = f.Model.Calls; var sends = f.NapCat.Calls;
        f.Bridge.Dispose();
        await File.WriteAllBytesAsync(f.StateFile + ".reminders.json", pending, ct);
        f.Bridge = f.NewBridge();
        Assert.Equal(1, await ConnectorHost.RemindOnceAsync(f.Bridge, f.Reach, ct)); // handed to the connector; retained attempt suppresses the send
        Assert.Equal(0, await ConnectorHost.RemindOnceAsync(f.Bridge, f.Reach, ct));
        Assert.Equal(calls, f.Model.Calls); Assert.Equal(sends, f.NapCat.Calls);
        Assert.Equal(entry.Id, Assert.Single((await f.Sync.DeliveriesAsync(null, ct)).Entries, e => e.Kind == "reminder").Id);
        Assert.Single(await f.Relay.MessagesAsync(chat.Id, ct: ct), m => m.Meta?["reminder"]?["id"]?.GetValue<string>() == entry.TriggerId);
    }

    [Fact]
    public async Task A_reminder_that_cannot_be_generated_is_released_without_creating_a_delivery_attempt()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var f = await Fixture.StartAsync(ct);
        var reply = Assert.IsType<ChannelReply>(await f.Bridge.AnswerAsync(Contact with { Text = "十分钟后提醒我喝水" }, ct));
        await f.Reach["qq"].SendReplyAsync(Subject, reply, ct);
        f.Time.Advance(TimeSpan.FromSeconds(600)); f.Model.Fail = true;
        Assert.Equal(0, await ConnectorHost.RemindOnceAsync(f.Bridge, f.Reach, ct));
        Assert.Single((await f.Sync.DeliveriesAsync(null, ct)).Entries);
        f.Model.Fail = false;
        Assert.Equal(1, await ConnectorHost.RemindOnceAsync(f.Bridge, f.Reach, ct));
        Assert.Equal("acknowledged", Assert.Single((await f.Sync.DeliveriesAsync(null, ct)).Entries, e => e.Kind == "reminder").State);
        Assert.Equal(0, await ConnectorHost.RemindOnceAsync(f.Bridge, f.Reach, ct));
    }

    private sealed class Clock : TimeProvider
    {
        private DateTimeOffset now = DateTimeOffset.UtcNow;
        public override DateTimeOffset GetUtcNow() => now;
        public void Advance(TimeSpan span) => now += span;
    }

    private sealed class Model : HttpMessageHandler
    {
        public int Calls { get; private set; }
        public bool Fail { get; set; }
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Calls++;
            return Task.FromResult(Fail ? new HttpResponseMessage(HttpStatusCode.ServiceUnavailable) { Content = new StringContent("synthetic generation failure") }
                : new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent("data: {\"choices\":[{\"delta\":{\"content\":\"这是测试用的陪伴消息。\"}}]}\n\ndata: [DONE]\n\n", Encoding.UTF8, "text/event-stream") });
        }
    }

    private sealed class NapCat : HttpMessageHandler
    {
        public string Mode { get; set; } = "ok";
        public int Calls { get; private set; }
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Calls++;
            var json = Mode switch
            {
                "failed" => """{"status":"failed","retcode":100,"data":null}""",
                "missing-id" => """{"status":"ok","retcode":0,"data":{}}""",
                _ => """{"status":"ok","retcode":0,"data":{"message_id":7}}""",
            };
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(json, Encoding.UTF8, "application/json") });
        }
    }

    private sealed class Fixture(ServerTestHost host, AijadeApi relay, CompanionSync sync, Model model) : IAsyncDisposable
    {
        public readonly Clock Time = new();
        public readonly NapCat NapCat = new();
        public string StateFile { get; } = Path.Combine(Path.GetTempPath(), "aijade-proactive-" + Guid.NewGuid().ToString("N"), "bridge.json");
        public AijadeApi Relay => relay;
        public CompanionSync Sync => sync;
        public Model Model => model;
        public CompanionBridge Bridge { get; set; } = null!;
        public Dictionary<string, IProactiveConnector> Reach { get; private set; } = null!;
        private CompanionConfiguration configuration = null!;
        private HttpClient napcatHttp = null!;

        public CompanionBridge NewBridge() => new(relay, new BridgeOptions
        {
            Memory = false, SpeakFirst = true, Time = Time, StateFile = StateFile, ReminderPlatforms = ["qq"],
            ResolveCompanion = configuration.ForAsync, PairCompanion = configuration.PairAsync,
        });

        public static async Task<Fixture> StartAsync(CancellationToken ct)
        {
            var model = new Model();
            var host = await ServerTestHost.StartAsync(worker: false,
                services: s => s.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => model));
            await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", new JsonObject
            {
                ["models"] = new JsonObject { ["aijade-chat"] = new JsonObject { ["upstream"] = "https://llm.example/v1", ["model"] = "m", ["keys"] = new JsonArray("k"), ["fluxPer1k"] = 0 } },
            }, ServerTestHost.AdminToken);
            var ownerTokens = new MemoryTokenStore(); await ownerTokens.SetAsync(ServerTestHost.Token);
            var relayTokens = new MemoryTokenStore(); await relayTokens.SetAsync(ServerTestHost.AdminToken);
            var sync = new CompanionSync(new AijadeApi(host.Client, ownerTokens)); var relay = new AijadeApi(host.Client, relayTokens);
            var code = (await sync.PairingCodeAsync(ct))!["code"]!.GetValue<string>();
            await new CompanionSync(relay).PairAsync(code, Subject, ct);
            var f = new Fixture(host, relay, sync, model);
            var offset = 12 - f.Time.GetUtcNow().Hour;
            var zone = offset == 0 ? "Etc/UTC" : "Etc/GMT" + (offset > 0 ? "-" : "+") + Math.Abs(offset).ToString(CultureInfo.InvariantCulture);
            var state = await sync.CurrentAsync(ct);
            await sync.SaveProfileAsync(null, state.Profile with { TimeZone = zone, NaturalPacing = false, Weather = false }, state.ProfileRevision, ct);
            f.configuration = new(new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?> { ["Bridge:StateFile"] = f.StateFile }).Build(), relay);
            f.Bridge = f.NewBridge(); f.napcatHttp = new(f.NapCat);
            f.Reach = new Dictionary<string, IProactiveConnector> { ["qq"] = new OneBotConnector(1, new Uri("http://127.0.0.1:3000"), "synthetic-token-12345", "synthetic-secret-12345", Subject, f.napcatHttp) };
            return f;
        }

        public async ValueTask DisposeAsync()
        {
            Bridge.Dispose(); napcatHttp.Dispose(); await host.DisposeAsync();
            var directory = Path.GetDirectoryName(StateFile)!;
            if (Directory.Exists(directory)) Directory.Delete(directory, recursive: true);
        }
    }
}
