using System.Globalization;
using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Companion;
using Aijade.Integrations;

using Microsoft.Extensions.DependencyInjection;

namespace Aijade.Tests;

public sealed class CompanionDeliveryTests
{
    private const string Subject = "123456789";
    private static string Digest(string text) => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(text)));
    private static async Task<AijadeApi> ApiAsync(ServerTestHost host, string token = ServerTestHost.Token)
    {
        var tokens = new MemoryTokenStore(); await tokens.SetAsync(token); return new(host.Client, tokens);
    }
    private static async Task<StoredMessage> SourceAsync(AijadeApi api, string? character, CancellationToken ct)
    {
        var chat = await api.CreateChatAsync(character, "synthetic delivery source", ct);
        return await api.AppendMessageAsync(chat.Id, "assistant", "A stored reply, not proof of platform delivery. 原文。", ct: ct);
    }
    private sealed class Clock : TimeProvider
    {
        public DateTimeOffset Now { get; set; } = DateTimeOffset.Parse("2026-11-10T00:00:00Z", CultureInfo.InvariantCulture);
        public override DateTimeOffset GetUtcNow() => Now;
        public override TimeZoneInfo LocalTimeZone => TimeZoneInfo.Utc;
    }

    [Fact]
    public async Task Owned_sources_role_scope_grants_and_destination_are_checked_and_duplicate_begins_are_serialized()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(worker: false);
        var api = await ApiAsync(host); var relayApi = await ApiAsync(host, ServerTestHost.AdminToken);
        var owner = new CompanionSync(api); var relay = new CompanionSync(relayApi);
        var code = (await owner.PairingCodeAsync(ct))!["code"]!.GetValue<string>();
        var link = await relay.PairAsync(code, Subject, ct); var linked = new CompanionSync(relayApi, link.Id);
        var source = await SourceAsync(api, null, ct);
        var attempts = await Task.WhenAll(Enumerable.Range(0, 8).Select(_ => owner.BeginDeliveryAsync(null, source.Id, Subject, ct)));
        Assert.Single(attempts, a => a.Created);
        Assert.All(attempts, a => Assert.Equal(attempts[0].Attempt.Id, a.Attempt.Id));
        var log = await linked.DeliveriesAsync(null, ct); var saved = Assert.Single(log.Entries);
        Assert.Equal(Digest(source.Content), saved.SourceSha256); Assert.Equal(source.Id, saved.MessageId);
        var state = (await host.SendAsync(HttpMethod.Get, "/api/v1/companion")).Body!.ToJsonString();
        Assert.DoesNotContain("deliveries", state, StringComparison.Ordinal);
        await Assert.ThrowsAsync<AijadeApiException>(() => linked.BeginDeliveryAsync(null, source.Id, Subject, ct)); // no owner's private source access
        var botSource = await SourceAsync(relayApi, null, ct);
        await Assert.ThrowsAsync<AijadeApiException>(() => linked.BeginDeliveryAsync(null, botSource.Id, "987654321", ct));
        var bot = await linked.BeginDeliveryAsync(null, botSource.Id, Subject, ct);
        await Assert.ThrowsAsync<AijadeApiException>(() => owner.StartDeliveryPartAsync(null, bot.Attempt.Id, 0, "text", Digest("p"), ct)); // owner reads, relay reports
        var character = await api.CreateCharacterAsync(new { name = "Separate", persona = "separate" }, ct);
        Assert.Empty((await owner.DeliveriesAsync(character.Id, ct)).Entries);
        await Assert.ThrowsAsync<AijadeApiException>(() => owner.BeginDeliveryAsync(character.Id, source.Id, Subject, ct));
        await owner.UnlinkAsync(link.Id, ct);
        Assert.Equal(404, (await Assert.ThrowsAsync<AijadeApiException>(() => linked.FinishDeliveryAsync(null, bot.Attempt.Id, "failed", ct))).Status);
        Assert.Equal(2, (await owner.DeliveriesAsync(null, ct)).Entries.Count);
    }

    [Fact]
    public async Task Ordered_observations_are_idempotent_immutable_and_cannot_turn_unknown_or_rejected_into_acknowledged()
    {
        var ct = TestContext.Current.CancellationToken; var clock = new Clock();
        await using var host = await ServerTestHost.StartAsync(worker: false, services: s => s.AddSingleton<TimeProvider>(clock));
        var api = await ApiAsync(host); var sync = new CompanionSync(api); var source = await SourceAsync(api, null, ct);
        var attempt = (await sync.BeginDeliveryAsync(null, source.Id, Subject, ct)).Attempt.Id;
        Assert.True((await sync.StartDeliveryPartAsync(null, attempt, 0, "text", Digest("part one"), ct)).Created);
        Assert.False((await sync.StartDeliveryPartAsync(null, attempt, 0, "text", Digest("part one"), ct)).Created);
        await Assert.ThrowsAsync<AijadeApiException>(() => sync.StartDeliveryPartAsync(null, attempt, 0, "text", Digest("changed"), ct));
        await Assert.ThrowsAsync<AijadeApiException>(() => sync.StartDeliveryPartAsync(null, attempt, 2, "text", Digest("gap"), ct));
        await Assert.ThrowsAsync<AijadeApiException>(() => sync.CompleteDeliveryPartAsync(null, attempt, 0, new("acknowledged", HttpStatus: 200, Retcode: 0), ct));
        await Assert.ThrowsAsync<AijadeApiException>(() => sync.CompleteDeliveryPartAsync(null, attempt, 0, new("rejected", HttpStatus: 200, Retcode: 1), ct));
        var ack = new DeliveryReceipt("acknowledged", "-7", 200, 0);
        await sync.CompleteDeliveryPartAsync(null, attempt, 0, ack, ct); await sync.CompleteDeliveryPartAsync(null, attempt, 0, ack, ct);
        await Assert.ThrowsAsync<AijadeApiException>(() => sync.CompleteDeliveryPartAsync(null, attempt, 0, ack with { PlatformMessageId = "8" }, ct));
        await sync.StartDeliveryPartAsync(null, attempt, 1, "image", Digest("image bytes"), ct);
        await sync.CompleteDeliveryPartAsync(null, attempt, 1, new("rejected", HttpStatus: 200, Retcode: 100), ct);
        await Assert.ThrowsAsync<AijadeApiException>(() => sync.StartDeliveryPartAsync(null, attempt, 2, "record", Digest("no further side effect"), ct));
        await sync.FinishDeliveryAsync(null, attempt, "failed", ct);
        var failed = Assert.Single((await sync.DeliveriesAsync(null, ct)).Entries); Assert.Equal("rejected", failed.State);
        Assert.Equal(["acknowledged", "rejected"], failed.Parts!.Select(p => p.Outcome));
        Assert.False((await sync.BeginDeliveryAsync(null, source.Id, Subject, ct)).Created);

        var abandonedSource = await SourceAsync(api, null, ct);
        var abandoned = (await sync.BeginDeliveryAsync(null, abandonedSource.Id, Subject, ct)).Attempt.Id;
        await sync.StartDeliveryPartAsync(null, abandoned, 0, "text", Digest("unconfirmed"), ct);
        clock.Now = clock.Now.AddMinutes(11);
        var unknown = (await sync.DeliveriesAsync(null, ct)).Entries.Single(e => e.Id == abandoned);
        Assert.Equal("unknown", unknown.State); Assert.Equal("expired", unknown.FinishReason);
        Assert.Equal("unknown", Assert.Single(unknown.Parts!).Outcome);
        await Assert.ThrowsAsync<AijadeApiException>(() => sync.CompleteDeliveryPartAsync(null, abandoned, 0, ack, ct));
        Assert.False((await sync.BeginDeliveryAsync(null, abandonedSource.Id, Subject, ct)).Created);
    }

    private sealed class NapCat(string mode, CancellationTokenSource? cancel = null) : HttpMessageHandler
    {
        public List<string> Bodies { get; } = [];
        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Bodies.Add(await request.Content!.ReadAsStringAsync(cancellationToken));
            Assert.Equal("send_private_msg", request.RequestUri!.AbsolutePath.Trim('/'));
            if (mode == "transport") throw new HttpRequestException("synthetic lost response");
            if (mode == "cancel") { cancel!.Cancel(); throw new OperationCanceledException(cancel.Token); }
            var kind = mode == "second-rejected" && Bodies.Count > 1 ? "failed" : mode;
            var body = kind switch
            {
                "missing-code" => """{"status":"ok","data":{"message_id":7}}""",
                "missing-id" => """{"status":"ok","retcode":0,"data":{}}""",
                "async" => """{"status":"async","retcode":1,"data":null}""",
                "failed" => """{"status":"failed","retcode":100,"data":null}""",
                "bad-json" => "not JSON",
                "wrong-type" => """{"status":"ok","retcode":"0","data":{"message_id":7}}""",
                "contradictory" => """{"status":"ok","retcode":100,"data":{"message_id":7}}""",
                "oversized" => new string(' ', 70_000),
                "string-id" => """{"status":"ok","retcode":0,"data":{"message_id":"-7"}}""",
                _ => """{"status":"ok","retcode":0,"data":{"message_id":7}}""",
            };
            return new(kind == "http500" ? HttpStatusCode.InternalServerError : HttpStatusCode.OK)
                { Content = new StringContent(body, Encoding.UTF8, "application/json") };
        }
    }

    [Theory]
    [InlineData("ok", "acknowledged")]
    [InlineData("string-id", "acknowledged")]
    [InlineData("missing-code", "unknown")]
    [InlineData("missing-id", "unknown")]
    [InlineData("async", "unknown")]
    [InlineData("failed", "rejected")]
    [InlineData("bad-json", "unknown")]
    [InlineData("wrong-type", "unknown")]
    [InlineData("contradictory", "unknown")]
    [InlineData("oversized", "unknown")]
    [InlineData("http500", "unknown")]
    [InlineData("transport", "unknown")]
    [InlineData("cancel", "unknown")]
    public async Task Actual_outbound_parts_require_a_complete_ack_and_unknown_results_never_trigger_another_send(string mode, string expected)
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(worker: false);
        var api = await ApiAsync(host); var sync = new CompanionSync(api); var source = await SourceAsync(api, null, ct);
        using var cancel = CancellationTokenSource.CreateLinkedTokenSource(ct);
        var napcat = new NapCat(mode, cancel); using var http = new HttpClient(napcat);
        var connector = new OneBotConnector(1, new Uri("http://127.0.0.1:3000"), "synthetic-token-12345", "synthetic-secret-12345", Subject, http);
        var reply = new ChannelReply(source.Content, []) { Delivery = new(new SyncedCompanionNotebook(sync, null), source.Id) };
        if (expected == "acknowledged") await connector.SendReplyAsync(reply, 0, cancel.Token);
        else await Assert.ThrowsAnyAsync<Exception>(() => connector.SendReplyAsync(reply, 0, cancel.Token));
        var saved = Assert.Single((await sync.DeliveriesAsync(null, ct)).Entries); var part = Assert.Single(saved.Parts!);
        Assert.Equal(expected, saved.State); Assert.Equal(expected, part.Outcome);
        Assert.Equal(Digest(napcat.Bodies[0]), part.PayloadSha256); Assert.Equal(Digest(source.Content), saved.SourceSha256);
        Assert.Equal(expected == "acknowledged" ? 1 : 0, connector.Health()["answered"]!.GetValue<int>());
        await connector.SendReplyAsync(reply, 0, ct); // the same retained attempt is not dispatched again
        Assert.Single(napcat.Bodies);
    }

    [Fact]
    public async Task A_partial_reply_keeps_the_first_ack_stops_after_rejection_and_records_unsent_interruption()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(worker: false);
        var api = await ApiAsync(host); var sync = new CompanionSync(api); var source = await SourceAsync(api, null, ct);
        var napcat = new NapCat("second-rejected"); using var http = new HttpClient(napcat);
        var connector = new OneBotConnector(1, new Uri("http://127.0.0.1:3000"), "synthetic-token-12345", "synthetic-secret-12345", Subject, http);
        var notebook = new SyncedCompanionNotebook(sync, null);
        var reply = new ChannelReply(source.Content, []) { Delivery = new(notebook, source.Id),
            Attachments = [new("image", "data:image/png;base64,aGVsbG8="), new("record", "data:audio/wav;base64,aGVsbG8=")] };
        await Assert.ThrowsAsync<OneBotSendException>(() => connector.SendReplyAsync(reply, 0, ct));
        var attempt = Assert.Single((await sync.DeliveriesAsync(null, ct)).Entries);
        Assert.Equal("rejected", attempt.State); Assert.Equal(["acknowledged", "rejected"], attempt.Parts!.Select(p => p.Outcome));
        Assert.Equal(2, napcat.Bodies.Count); Assert.DoesNotContain(napcat.Bodies, b => b.Contains("\"record\"", StringComparison.Ordinal));
        var other = await SourceAsync(api, null, ct);
        await connector.SendReplyAsync(new(other.Content, []) { Delivery = new(notebook, other.Id) }, 1, ct);
        var interrupted = (await sync.DeliveriesAsync(null, ct)).Entries.Single(e => e.MessageId == other.Id);
        Assert.Equal("interrupted", interrupted.State); Assert.Empty(interrupted.Parts!); Assert.Equal(2, napcat.Bodies.Count);
    }

    [Fact]
    public async Task Recent_history_is_bounded_but_unfinished_attempts_are_not_evicted_to_make_room()
    {
        var ct = TestContext.Current.CancellationToken; var clock = new Clock();
        await using var host = await ServerTestHost.StartAsync(worker: false, services: s => s.AddSingleton<TimeProvider>(clock));
        var api = await ApiAsync(host); var sync = new CompanionSync(api);
        var chat = await api.CreateChatAsync(null, "synthetic capacity", ct);
        for (var i = 0; i < 128; i++)
        {
            var source = await api.AppendMessageAsync(chat.Id, "assistant", "capacity " + i, ct: ct);
            await sync.BeginDeliveryAsync(null, source.Id, Subject, ct);
        }
        var next = await api.AppendMessageAsync(chat.Id, "assistant", "next", ct: ct);
        Assert.Equal(409, (await Assert.ThrowsAsync<AijadeApiException>(() => sync.BeginDeliveryAsync(null, next.Id, Subject, ct))).Status);
        clock.Now = clock.Now.AddMinutes(11);
        await sync.BeginDeliveryAsync(null, next.Id, Subject, ct);
        var log = await sync.DeliveriesAsync(null, ct); Assert.Equal(128, log.Entries.Count); Assert.Equal(1, log.Pruned);
        Assert.Equal(129, (await api.MessagesAsync(chat.Id, ct: ct)).Count);
    }

    private sealed class LostObservation(ICompanionDelivery inner) : ICompanionDelivery
    {
        public Task<DeliveryStart> BeginDeliveryAsync(string messageId, string destination, CancellationToken ct = default) => inner.BeginDeliveryAsync(messageId, destination, ct);
        public Task<DeliveryPartStart> StartDeliveryPartAsync(string attempt, int index, string kind, string payloadSha256, CancellationToken ct = default) => inner.StartDeliveryPartAsync(attempt, index, kind, payloadSha256, ct);
        public Task CompleteDeliveryPartAsync(string attempt, int index, DeliveryReceipt receipt, CancellationToken ct = default) => throw new HttpRequestException("Synthetic lost receipt write");
        public Task FinishDeliveryAsync(string attempt, string reason, CancellationToken ct = default) => inner.FinishDeliveryAsync(attempt, reason, ct);
    }

    [Fact]
    public async Task Unavailable_recording_prevents_dispatch_or_stops_after_the_last_observed_part_without_retrying_it()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(worker: false);
        var api = await ApiAsync(host); var sync = new CompanionSync(api); var notebook = new SyncedCompanionNotebook(sync, null);
        var napcat = new NapCat("ok"); using var http = new HttpClient(napcat);
        var connector = new OneBotConnector(1, new Uri("http://127.0.0.1:3000"), "synthetic-token-12345", "synthetic-secret-12345", Subject, http);
        await Assert.ThrowsAsync<AijadeApiException>(() => connector.SendReplyAsync(new("not dispatched", []) { Delivery = new(notebook, "missing-source") }, 0, ct));
        Assert.Empty(napcat.Bodies); Assert.Equal(1, connector.Health()["deliveryRecordFailures"]!.GetValue<int>());
        var source = await SourceAsync(api, null, ct);
        var reply = new ChannelReply(source.Content, []) { Delivery = new(new LostObservation(notebook), source.Id), Attachments = [new("image", "data:image/png;base64,aGVsbG8=")] };
        await Assert.ThrowsAsync<HttpRequestException>(() => connector.SendReplyAsync(reply, 0, ct));
        Assert.Single(napcat.Bodies); Assert.Equal(1, connector.Health()["answered"]!.GetValue<int>());
        var attempt = Assert.Single((await sync.DeliveriesAsync(null, ct)).Entries);
        Assert.Equal("unknown", attempt.State); Assert.Equal("unknown", Assert.Single(attempt.Parts!).Outcome);
        await connector.SendReplyAsync(reply, 0, ct); Assert.Single(napcat.Bodies);
    }
}
