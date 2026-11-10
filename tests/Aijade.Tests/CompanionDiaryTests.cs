using System.Net;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Chat;
using Aijade.Client.Companion;
using Aijade.Integrations;
using Aijade.Server.Product;

using Microsoft.Extensions.DependencyInjection;

namespace Aijade.Tests;

public sealed class CompanionDiaryTests
{
    private static async Task<AijadeApi> ApiAsync(ServerTestHost host, string token = ServerTestHost.Token)
    {
        var tokens = new MemoryTokenStore(); await tokens.SetAsync(token);
        return new(host.Client, tokens);
    }
    private static async Task<CompanionLink> LinkAsync(CompanionSync owner, CompanionSync relay, CancellationToken ct)
    {
        var code = (await owner.PairingCodeAsync(ct))!["code"]!.GetValue<string>();
        return await relay.PairAsync(code, "123456789", ct);
    }

    [Fact]
    public async Task Explicit_excerpts_share_one_revision_across_Web_and_QQ_without_sharing_private_chat_history()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(new Dictionary<string, string?> { ["Aijade:Profile"] = "companion" }, worker: false);
        var ownerApi = await ApiAsync(host); var relayApi = await ApiAsync(host, ServerTestHost.AdminToken);
        var owner = new CompanionSync(ownerApi); var relay = new CompanionSync(relayApi);
        var profile = await owner.CurrentAsync(ct);
        await owner.SaveProfileAsync(null, profile.Profile with { TimeZone = "Pacific/Honolulu" }, profile.ProfileRevision, ct);
        var link = await LinkAsync(owner, relay, ct); var linked = new CompanionSync(relayApi, link.Id);
        var chat = await ownerApi.CreateChatAsync(null, "diary source", ct);
        var user = await ownerApi.AppendMessageAsync(chat.Id, "user", "I finished reading a book.", ct: ct);
        var reply = await ownerApi.AppendMessageAsync(chat.Id, "assistant", "In my fictional day I read by the window.", ct: ct);
        var saves = await Task.WhenAll(owner.SaveExchangeAsync(null, user.Id, reply.Id, ct), owner.SaveExchangeAsync(null, user.Id, reply.Id, ct));
        Assert.All(saves, d => Assert.Equal(1, d.Revision));
        var diary = await linked.ReadDiaryAsync(null, saves[0].Day, ct);
        var entry = Assert.Single(diary.Entries);
        Assert.Equal(user.Content, entry.User.Text); Assert.Equal(reply.Content, entry.Assistant.Text);
        Assert.Equal(DateOnly.FromDateTime(TimeZoneInfo.ConvertTime(user.CreatedAt, TimeZoneInfo.FindSystemTimeZoneById("Pacific/Honolulu")).DateTime), entry.Day);
        Assert.Equal(user.Id, entry.User.MessageId); Assert.Equal(chat.Id, entry.ChatId);
        Assert.Equal(Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(user.Content))), entry.User.Sha256);
        var ordinaryState = (await host.SendAsync(HttpMethod.Get, "/api/v1/companion")).Body!.ToJsonString();
        Assert.DoesNotContain(user.Content, ordinaryState, StringComparison.Ordinal); // diary payload is lazy, not injected in every ordinary turn
        await Assert.ThrowsAsync<AijadeApiException>(() => relayApi.MessagesAsync(chat.Id, ct: ct));

        // The relay can explicitly save its own completed exchange into this grant, never read the owner's full chat.
        var botChat = await relayApi.CreateChatAsync(null, "QQ source", ct);
        var botUser = await relayApi.AppendMessageAsync(botChat.Id, "user", "QQ diary source", ct: ct);
        var botReply = await relayApi.AppendMessageAsync(botChat.Id, "assistant", "QQ reply", ct: ct);
        await Assert.ThrowsAsync<AijadeApiException>(() => owner.SaveExchangeAsync(null, botUser.Id, botReply.Id, ct));
        var botSaved = await linked.SaveExchangeAsync(null, botUser.Id, botReply.Id, ct);
        Assert.Equal(2, botSaved.Revision);
        var stale = await Assert.ThrowsAsync<AijadeApiException>(() => owner.RemoveDiaryEntryAsync(null, entry.Id, diary.Revision, ct));
        Assert.Equal(409, stale.Status);
        await owner.RemoveDiaryEntryAsync(null, entry.Id, botSaved.Revision, ct);
        Assert.DoesNotContain((await linked.ReadDiaryAsync(null, entry.Day, ct)).Entries, e => e.Id == entry.Id);
        Assert.Equal(2, (await ownerApi.MessagesAsync(chat.Id, ct: ct)).Count); // forgetting an excerpt leaves the original intact
        await owner.UnlinkAsync(link.Id, ct);
        Assert.Equal(404, (await Assert.ThrowsAsync<AijadeApiException>(() => linked.ReadDiaryAsync(null, entry.Day, ct))).Status);
    }

    [Fact]
    public async Task Source_validation_rejects_other_roles_interleaved_turns_commands_and_unsolicited_replies()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(worker: false);
        var api = await ApiAsync(host); var sync = new CompanionSync(api); var chat = await api.CreateChatAsync(null, "source rules", ct);
        var first = await api.AppendMessageAsync(chat.Id, "user", "First request", ct: ct);
        var second = await api.AppendMessageAsync(chat.Id, "user", "Second request", ct: ct);
        var reply = await api.AppendMessageAsync(chat.Id, "assistant", "Second reply", ct: ct);
        Assert.Equal(400, (await Assert.ThrowsAsync<AijadeApiException>(() => sync.SaveExchangeAsync(null, first.Id, reply.Id, ct))).Status);
        var role = await api.CreateCharacterAsync(new { name = "Other role", persona = "different" }, ct);
        Assert.Equal(400, (await Assert.ThrowsAsync<AijadeApiException>(() => sync.SaveExchangeAsync(role.Id, second.Id, reply.Id, ct))).Status);
        var command = await api.AppendMessageAsync(chat.Id, "user", "/life", ct: ct);
        var life = await api.AppendMessageAsync(chat.Id, "assistant", "fictional life", ct: ct);
        Assert.Equal(400, (await Assert.ThrowsAsync<AijadeApiException>(() => sync.SaveExchangeAsync(null, command.Id, life.Id, ct))).Status);
        var user = await api.AppendMessageAsync(chat.Id, "user", "Quiet now", ct: ct);
        var proactive = await api.AppendMessageAsync(chat.Id, "assistant", "unprompted", new JsonObject { ["initiative"] = new JsonObject() }, ct);
        Assert.Equal(400, (await Assert.ThrowsAsync<AijadeApiException>(() => sync.SaveExchangeAsync(null, user.Id, proactive.Id, ct))).Status);
        var other = await api.CreateChatAsync(null, "other chat", ct);
        var otherReply = await api.AppendMessageAsync(other.Id, "assistant", "unrelated reply", ct: ct);
        Assert.Equal(404, (await Assert.ThrowsAsync<AijadeApiException>(() => sync.SaveExchangeAsync(null, user.Id, otherReply.Id, ct))).Status);
        Assert.Equal(400, (await host.SendAsync(HttpMethod.Get, "/api/v1/companion/characters/default/diary?day=not-a-date")).Status);
        Assert.Equal(400, (await host.SendAsync(HttpMethod.Post, "/api/v1/companion/characters/default/diary", new JsonObject { ["userMessageId"] = 42, ["assistantMessageId"] = reply.Id })).Status);
        Assert.Equal(0, (await sync.ReadDiaryAsync(null, ct: ct)).Revision);
    }

    [Fact]
    public async Task Excerpts_keep_complete_source_digests_and_their_original_local_day_after_timezone_changes()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(worker: false);
        var api = await ApiAsync(host); var sync = new CompanionSync(api); var chat = await api.CreateChatAsync(null, "unicode", ct);
        var original = new string('a', 999) + "😀 trailing text";
        var user = await api.AppendMessageAsync(chat.Id, "user", original, ct: ct);
        var reply = await api.AppendMessageAsync(chat.Id, "assistant", "A short answer", ct: ct);
        var before = await sync.SaveExchangeAsync(null, user.Id, reply.Id, ct);
        var entry = Assert.Single(before.Entries);
        Assert.True(entry.User.Truncated); Assert.Equal(999, entry.User.Text.Length);
        Assert.Equal(Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(original))), entry.User.Sha256);
        var culture = System.Globalization.CultureInfo.CurrentCulture;
        try
        {
            System.Globalization.CultureInfo.CurrentCulture = new System.Globalization.CultureInfo("ar-SA");
            Assert.Equal(entry.Id, Assert.Single((await sync.ReadDiaryAsync(null, before.Day, ct)).Entries).Id);
        }
        finally { System.Globalization.CultureInfo.CurrentCulture = culture; }
        var profile = await sync.CurrentAsync(ct);
        await sync.SaveProfileAsync(null, profile.Profile with { TimeZone = "Pacific/Kiritimati" }, profile.ProfileRevision, ct);
        var repeated = await sync.SaveExchangeAsync(null, user.Id, reply.Id, ct);
        Assert.Equal(before.Revision, repeated.Revision); Assert.Equal(entry, Assert.Single(repeated.Entries));
        Assert.Equal(original, (await api.MessagesAsync(chat.Id, ct: ct))[0].Content);
        await api.DeleteChatAsync(chat.Id, ct);
        Assert.Equal(entry.Id, Assert.Single((await sync.ReadDiaryAsync(null, entry.Day, ct)).Entries).Id);
    }

    private sealed class Llm : HttpMessageHandler
    {
        public int Calls { get; private set; }
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Calls++;
            return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent("data: {\"choices\":[{\"delta\":{\"content\":\"Here I am.\"}}]}\n\ndata: [DONE]\n\n", Encoding.UTF8, "text/event-stream") });
        }
    }

    [Fact]
    public async Task Shared_diary_commands_use_the_existing_Web_and_bot_entry_point_with_no_extra_model_calls()
    {
        var ct = TestContext.Current.CancellationToken; var llm = new Llm();
        await using var host = await ServerTestHost.StartAsync(worker: false,
            services: s => s.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => llm));
        await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", JsonNode.Parse("""
            {"models":{"aijade-chat":{"upstream":"https://llm.example/v1","model":"test","keys":["test"]}}}
            """), ServerTestHost.AdminToken);
        var api = await ApiAsync(host); var sync = new CompanionSync(api); var state = await sync.CurrentAsync(ct);
        var notebook = new SyncedCompanionNotebook(sync, null, state); using var weather = new HttpClient();
        var companion = new CompanionExperience(notebook, () => notebook.Latest!.RuntimeProfile, new CompanionWeather(weather), "owner");
        var runtime = CompanionRuntime.Create(api, [new("life", companion, companion)], new OrchestratorOptions(), companion);
        var chat = await api.CreateChatAsync(null, "diary runtime", ct);
        await foreach (var _ in runtime.SendAsync(chat.Id, null, [], "Read my new book with me", "snapshot", ct)) { }
        for (var i = 0; i < 2; i++)
        {
            var events = new List<OrchestratorEvent>();
            await foreach (var e in runtime.SendAsync(chat.Id, null, [], "/diary save", "snapshot", ct)) events.Add(e);
            Assert.Contains("共同日记", Assert.IsType<MediaCompleted>(Assert.Single(events)).Reply.Content, StringComparison.Ordinal);
        }
        var diary = await sync.ReadDiaryAsync(null, ct: ct); Assert.Single(diary.Entries); Assert.Equal(1, diary.Revision);
        using var bridge = new CompanionBridge(api, new BridgeOptions { Memory = false, Companion = _ => companion });
        var result = await bridge.AnswerAsync(new("qq", "owner", "owner", "Owner", $"/diary {diary.Day:yyyy-MM-dd}", true, true), ct);
        Assert.Contains("Read my new book", result!.Text, StringComparison.Ordinal);
        Assert.Equal(1, llm.Calls);
        Assert.Equal(1, (await sync.CurrentAsync(ct)).Notebook.Relationship.Interactions);
    }
}
