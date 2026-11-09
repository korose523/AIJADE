using System.Text.Json.Nodes;

using Aijade.Bots;
using Aijade.Client.Api;
using Aijade.Client.Companion;
using Aijade.Integrations;
using Aijade.Server.Product;

using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace Aijade.Tests;

public sealed class CompanionSyncTests
{
    private const string Image = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jWQ0AAAAASUVORK5CYII=";
    private static async Task<AijadeApi> ApiAsync(ServerTestHost host, string token)
    {
        var tokens = new MemoryTokenStore(); await tokens.SetAsync(token);
        return new(host.Client, tokens);
    }
    private static async Task<CompanionLink> LinkAsync(CompanionSync owner, CompanionSync relay)
    {
        var code = await owner.PairingCodeAsync(TestContext.Current.CancellationToken);
        return await relay.PairAsync(code!["code"]!.GetValue<string>(), "123456789", TestContext.Current.CancellationToken);
    }

    [Fact]
    public async Task Profiles_and_private_characters_are_shared_by_explicit_pairing_and_refresh_on_the_next_read()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(worker: false);
        var api = await ApiAsync(host, ServerTestHost.Token); var relayApi = await ApiAsync(host, ServerTestHost.AdminToken);
        var owner = new CompanionSync(api); var relay = new CompanionSync(relayApi);
        var character = await api.CreateCharacterAsync(new { name = "Shared companion", persona = "First persona", visibility = "private" }, ct);
        await owner.SelectAsync(character.Id, ct);
        var current = await owner.CurrentAsync(ct);
        await owner.SaveProfileAsync(character.Id, current.Profile with { City = "First city", TimeZone = "Asia/Seoul" }, current.ProfileRevision, ct);
        var link = await LinkAsync(owner, relay); var paired = new CompanionSync(relayApi, link.Id);
        var read = await paired.CurrentAsync(ct);
        Assert.Equal(ServerTestHost.UserId, read.OwnerId); Assert.Equal("First persona", read.Character!.Persona); Assert.Equal("First city", read.Profile.City);
        await api.UpdateCharacterAsync(character.Id, new { persona = "Updated persona" }, ct);
        await owner.SaveProfileAsync(character.Id, read.Profile with { City = "Second city", TimeZone = "Asia/Tokyo" }, read.ProfileRevision, ct);
        read = await paired.CurrentAsync(ct);
        Assert.Equal("Updated persona", read.Character!.Persona); Assert.Equal("Second city", read.Profile.City); Assert.Equal("Asia/Tokyo", read.Profile.TimeZone);
        var otherAccount = await relay.CurrentAsync(ct);
        Assert.Null(otherAccount.CharacterId); Assert.NotEqual("Second city", otherAccount.Profile.City);
        await Assert.ThrowsAsync<AijadeApiException>(() => new CompanionSync(api, link.Id).CurrentAsync(ct)); // owner access does not impersonate the relay grant
    }

    [Fact]
    public async Task Stale_profile_saves_cannot_overwrite_a_newer_profile_or_erase_collections()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(worker: false);
        var sync = new CompanionSync(await ApiAsync(host, ServerTestHost.Token));
        var initial = await sync.CurrentAsync(ct);
        var first = await sync.SaveProfileAsync(null, initial.Profile with { Home = "New home" }, initial.ProfileRevision, ct);
        await sync.AddAsync(null, new("sticker", "sticker", "Smile", Image, Emotion: "joy"), ct);
        var conflict = await Assert.ThrowsAsync<AijadeApiException>(() => sync.SaveProfileAsync(null, initial.Profile with { Home = "Stale home" }, initial.ProfileRevision, ct));
        Assert.Equal(409, conflict.Status);
        var state = await sync.CurrentAsync(ct);
        Assert.Equal("New home", state.Profile.Home); Assert.Single(state.Notebook.Assets);
        Assert.Equal("", state.Notebook.Assets[0].Data); // context polling does not download all binary media
        Assert.Equal(Image, (await sync.AssetAsync(null, "sticker", ct))!.Data);
        Assert.Equal(first.ProfileRevision, state.ProfileRevision);
    }

    [Fact]
    public async Task Concurrent_clients_keep_all_items_and_one_user_message_changes_the_relationship_once()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(worker: false);
        var api = await ApiAsync(host, ServerTestHost.Token); var sync = new CompanionSync(api);
        await Task.WhenAll(Enumerable.Range(0, 8).Select(i => sync.AddAsync(null, new("item-" + i, "sticker", "Smile", Image, Emotion: "joy"), ct)));
        Assert.Equal(8, (await sync.CurrentAsync(ct)).Notebook.Assets.Count);
        var chat = await api.CreateChatAsync(null, "Web", ct); var message = await api.AppendMessageAsync(chat.Id, "user", "谢谢你", ct: ct);
        await Task.WhenAll(Enumerable.Range(0, 8).Select(_ => sync.ObserveAsync(null, message.Id, ct)));
        var state = await sync.CurrentAsync(ct);
        Assert.Equal(1, state.Notebook.Relationship.Interactions); Assert.Equal(31, state.Notebook.Relationship.Affection);
        Assert.Equal(8, state.Notebook.Assets.Count);
        var otherApi = await ApiAsync(host, ServerTestHost.AdminToken);
        await Assert.ThrowsAsync<AijadeApiException>(() => new CompanionSync(otherApi).ObserveAsync(null, message.Id, ct));
    }

    [Fact]
    public async Task Both_clients_share_relations_and_media_while_other_characters_remain_separate()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(worker: false);
        var api = await ApiAsync(host, ServerTestHost.Token); var relayApi = await ApiAsync(host, ServerTestHost.AdminToken);
        var sync = new CompanionSync(api); var relay = new CompanionSync(relayApi);
        var link = await LinkAsync(sync, relay); var paired = new CompanionSync(relayApi, link.Id);
        var chat = await relayApi.CreateChatAsync(null, "QQ", ct); var message = await relayApi.AppendMessageAsync(chat.Id, "user", "谢谢你", ct: ct);
        await paired.ObserveAsync(null, message.Id, ct);
        await paired.AddAsync(null, new("scarf", "outfit", "围巾", Image, "red scarf", "winter"), ct);
        Assert.Equal(1, (await sync.CurrentAsync(ct)).Notebook.Relationship.Interactions);
        Assert.Equal("围巾", Assert.Single((await sync.CurrentAsync(ct)).Notebook.Assets).Name);
        await sync.RemoveAsync(null, "scarf", ct);
        Assert.Empty((await paired.CurrentAsync(ct)).Notebook.Assets);
        var role = await api.CreateCharacterAsync(new { name = "Another role" }, ct); await sync.SelectAsync(role.Id, ct);
        Assert.Equal(role.Id, (await paired.CurrentAsync(ct)).CharacterId);
        Assert.Equal(0, (await paired.CurrentAsync(ct)).Notebook.Relationship.Interactions);
        await sync.SelectAsync(null, ct); Assert.Equal(1, (await paired.CurrentAsync(ct)).Notebook.Relationship.Interactions);
    }

    [Fact]
    public async Task Pair_codes_are_one_use_hashed_and_revocation_blocks_old_scopes()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(worker: false);
        var owner = new CompanionSync(await ApiAsync(host, ServerTestHost.Token)); var api = await ApiAsync(host, ServerTestHost.AdminToken); var relay = new CompanionSync(api);
        var issued = await owner.PairingCodeAsync(ct); var code = issued!["code"]!.GetValue<string>();
        await using (var cmd = host.Db.CreateCommand("SELECT value::text FROM config_kv WHERE key LIKE 'companion.pair.%'"))
            Assert.DoesNotContain(code, (string)(await cmd.ExecuteScalarAsync(ct))!, StringComparison.Ordinal);
        var link = await relay.PairAsync(code, "123456789", ct);
        Assert.Equal(409, (await Assert.ThrowsAsync<AijadeApiException>(() => relay.PairAsync(code, "123456789", ct))).Status);
        Assert.Single(await owner.LinksAsync(ct));
        await owner.UnlinkAsync(link.Id, ct);
        Assert.Null(await relay.ResolveAsync("123456789", ct));
        Assert.Equal(404, (await Assert.ThrowsAsync<AijadeApiException>(() => new CompanionSync(api, link.Id).CurrentAsync(ct))).Status);
    }

    [Fact]
    public async Task Reimport_is_idempotent_and_cannot_resurrect_a_deleted_collection_or_overwrite_new_settings()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(worker: false);
        var sync = new CompanionSync(await ApiAsync(host, ServerTestHost.Token));
        var legacy = new CompanionNotebookData { Assets = [new("old", "sticker", "Old item", Image)] };
        var migrated = await sync.ImportAsync(null, "legacy-device", new CompanionProfile { Home = "Old home" }, legacy, ct: ct);
        await sync.SaveProfileAsync(null, migrated.Profile with { Home = "Current home" }, migrated.ProfileRevision, ct);
        await sync.RemoveAsync(null, "old", ct);
        await sync.ImportAsync(null, "legacy-device", new CompanionProfile { Home = "Old home" }, legacy, ct: ct);
        var read = await sync.CurrentAsync(ct); Assert.Equal("Current home", read.Profile.Home); Assert.Empty(read.Notebook.Assets);
    }

    [Fact]
    public async Task The_bot_resolver_reads_current_selection_instead_of_the_cached_character_or_location()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(worker: false);
        var api = await ApiAsync(host, ServerTestHost.Token); var relayApi = await ApiAsync(host, ServerTestHost.AdminToken);
        var sync = new CompanionSync(api); var relay = new CompanionSync(relayApi); await LinkAsync(sync, relay);
        var options = new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?> { ["Bridge:StateFile"] = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString("N")) }).Build();
        var resolver = new CompanionConfiguration(options, relayApi);
        var message = new ChannelMessage("qq", "123456789", "123456789", "Owner", "hello", true, true);
        var first = await resolver.ForAsync(message, ct); Assert.Null(first!.Character);
        var role = await api.CreateCharacterAsync(new { name = "New role", persona = "Always mention my telescope" }, ct); await sync.SelectAsync(role.Id, ct);
        var state = await sync.CurrentAsync(ct); await sync.SaveProfileAsync(role.Id, state.Profile with { City = "Tokyo", TimeZone = "Asia/Tokyo" }, state.ProfileRevision, ct);
        var next = await resolver.ForAsync(message, ct); Assert.Equal(role.Id, next!.Character!.Id); Assert.Equal("Tokyo", next.Experience.Profile.City);
        Assert.NotEqual(first.Identity, next.Identity);
    }

    [Fact]
    public async Task Blank_zones_use_the_same_server_clock_for_both_clients()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(worker: false, services: s => s.AddSingleton<TimeProvider>(new SharedClock()));
        var owner = new CompanionSync(await ApiAsync(host, ServerTestHost.Token));
        var relayApi = await ApiAsync(host, ServerTestHost.AdminToken); var relay = new CompanionSync(relayApi);
        var link = await LinkAsync(owner, relay);
        var web = await owner.CurrentAsync(ct); var qq = await new CompanionSync(relayApi, link.Id).CurrentAsync(ct);
        Assert.Equal("", web.Profile.TimeZone); Assert.Equal("Asia/Seoul", web.EffectiveTimeZone);
        Assert.Equal(web.RuntimeProfile.Zone, qq.RuntimeProfile.Zone);
    }

    [Fact]
    public async Task Expired_codes_fail_and_rebinding_revokes_the_previous_grant()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(worker: false);
        var owner = new CompanionSync(await ApiAsync(host, ServerTestHost.Token));
        var relayApi = await ApiAsync(host, ServerTestHost.AdminToken); var relay = new CompanionSync(relayApi);
        var issued = await owner.PairingCodeAsync(ct);
        await using (var cmd = host.Db.CreateCommand("UPDATE config_kv SET value=jsonb_set(value,'{expires}',to_jsonb('2000-01-01T00:00:00Z'::text)) WHERE key LIKE 'companion.pair.%'"))
            await cmd.ExecuteNonQueryAsync(ct);
        Assert.Equal(409, (await Assert.ThrowsAsync<AijadeApiException>(() => relay.PairAsync(issued!["code"]!.GetValue<string>(), "123456789", ct))).Status);
        var first = await LinkAsync(owner, relay); var second = await LinkAsync(owner, relay);
        Assert.NotEqual(first.Id, second.Id); Assert.Single(await owner.LinksAsync(ct));
        Assert.Equal(404, (await Assert.ThrowsAsync<AijadeApiException>(() => new CompanionSync(relayApi, first.Id).CurrentAsync(ct))).Status);
        Assert.Equal(second.Id, (await relay.ResolveAsync("123456789", ct))!.Id);
    }

    private sealed class SharedClock : TimeProvider
    {
        public override TimeZoneInfo LocalTimeZone => TimeZoneInfo.FindSystemTimeZoneById("ROK");
    }
}
