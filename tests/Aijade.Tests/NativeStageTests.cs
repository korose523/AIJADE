using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Companion;
using Aijade.Server.Product;
using Microsoft.Extensions.Configuration;

namespace Aijade.Tests;

public sealed class NativeStageTests
{
    private static Dictionary<string, string?> Enabled => new() { [StageEndpoints.NativeEnabledKey] = "true" };
    private static JsonObject Command(string text, string id, long? revision = null, string character = "default")
    {
        var body = new JsonObject { ["text"] = text, ["commandId"] = id, ["characterId"] = character };
        if (revision is not null) body["expectedRevision"] = revision.Value;
        return body;
    }

    [Fact]
    public async Task The_native_scene_is_private_durable_and_never_claims_a_render_or_audio_receipt()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(Enabled, worker: false);
        Assert.Equal(401, (await host.SendAsync(HttpMethod.Get, "/api/v1/stage", token: null)).Status);
        Assert.Equal(200, (await host.SendAsync(HttpMethod.Get, "/api/v1/stage")).Status);
        var (status, result) = await host.SendAsync(HttpMethod.Post, "/api/v1/stage/command", Command("说 你好; 去 沙发", "first", 0));
        Assert.Equal(200, status); Assert.Equal("sit", result!["posture"]!.GetValue<string>());
        Assert.Equal("state_applied", result["outcome"]!.GetValue<string>());
        Assert.False(result["renderObserved"]!.GetValue<bool>()); Assert.False(result["audioPlayed"]!.GetValue<bool>());
        Assert.Equal(1, result["revision"]!.GetValue<long>());
        var other = (await host.SendAsync(HttpMethod.Get, "/api/v1/stage", token: ServerTestHost.AdminToken)).Body!;
        Assert.Equal(0, other["revision"]!.GetValue<long>()); Assert.Equal("stand", other["posture"]!.GetValue<string>());
        var store = new NativeStageStore(host.Db);
        Assert.Equal("sit", (await store.ReadAsync(ServerTestHost.UserId, null, ct))["posture"]!.GetValue<string>());
        var tokens = new MemoryTokenStore(); await tokens.SetAsync(ServerTestHost.Token);
        var client = new CompanionStage(new AijadeApi(host.Client, tokens));
        Assert.Equal("virtual", (await client.StateAsync(ct))!.StateKind);
        Assert.Equal(StageOutcome.Unknown, (await client.FollowAsync(new(StageActionKind.Place, "沙发", "去沙发"), null, ct: ct)).Outcome);
    }

    [Fact]
    public async Task Commands_are_atomic_and_replays_do_not_overwrite_later_scene_state()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(Enabled, worker: false);
        Assert.Equal(200, (await host.SendAsync(HttpMethod.Post, "/api/v1/stage/command", Command("去 沙发", "a", 0))).Status);
        Assert.Equal(200, (await host.SendAsync(HttpMethod.Post, "/api/v1/stage/command", Command("去 床", "b", 1))).Status);
        var duplicate = await host.SendAsync(HttpMethod.Post, "/api/v1/stage/command", Command("去 沙发", "a", 0));
        Assert.Equal(200, duplicate.Status); Assert.True(duplicate.Body!["replayed"]!.GetValue<bool>());
        Assert.Equal(1, duplicate.Body["revision"]!.GetValue<long>()); // the ORIGINAL receipt, not an invented new execution
        Assert.Equal(409, (await host.SendAsync(HttpMethod.Post, "/api/v1/stage/command", Command("起来", "a"))).Status);
        Assert.Equal(409, (await host.SendAsync(HttpMethod.Post, "/api/v1/stage/command", Command("起来", "stale", 0))).Status);
        Assert.Equal(422, (await host.SendAsync(HttpMethod.Post, "/api/v1/stage/command", Command("去 厨房; 跳舞", "unsupported"))).Status);
        Assert.Equal(400, (await host.SendAsync(HttpMethod.Post, "/api/v1/stage/command", Command("表情 NaN 0 0 0", "nan"))).Status);
        var current = (await host.SendAsync(HttpMethod.Get, "/api/v1/stage")).Body!;
        Assert.Equal(2, current["revision"]!.GetValue<long>()); Assert.Equal("lie", current["posture"]!.GetValue<string>());
        Assert.Equal(2, await host.CountAsync("SELECT count(*) FROM config_kv WHERE key LIKE 'aijade.scene.%.command.%'"));
        var store = new NativeStageStore(host.Db);
        var changes = await Task.WhenAll(Enumerable.Range(0, 8).Select(async i =>
        {
            try { await store.ApplyAsync(ServerTestHost.UserId, null, "起来", "race-" + i, 2, ct); return true; }
            catch (Aijade.Server.Infrastructure.ApiException error) when (error.Status == 409) { return false; }
        }));
        Assert.Single(changes, success => success);
    }

    [Fact]
    public async Task Character_selection_has_its_own_scene_and_obsolete_external_configuration_is_refused()
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(Enabled, worker: false);
        var tokens = new MemoryTokenStore(); await tokens.SetAsync(ServerTestHost.Token);
        var api = new AijadeApi(host.Client, tokens); var sync = new CompanionSync(api);
        Assert.Equal(200, (await host.SendAsync(HttpMethod.Post, "/api/v1/stage/command", Command("去 床", "a"))).Status);
        var character = await api.CreateCharacterAsync(new { name = "Different companion" }, ct);
        await sync.SelectAsync(character.Id, ct);
        Assert.Equal(0, (await host.SendAsync(HttpMethod.Get, "/api/v1/stage")).Body!["revision"]!.GetValue<long>());
        var replay = await host.SendAsync(HttpMethod.Post, "/api/v1/stage/command", Command("去 床", "a"));
        Assert.Equal(200, replay.Status); Assert.True(replay.Body!["replayed"]!.GetValue<bool>());
        Assert.Equal(0, (await host.SendAsync(HttpMethod.Get, "/api/v1/stage")).Body!["revision"]!.GetValue<long>());
        var pinned = new CompanionStage(api); // explicit default, not the account's mutable current selection
        Assert.Equal("lie", (await pinned.StateAsync(ct))!.Posture);
        await pinned.SendAsync("起来", ct);
        Assert.Equal(0, (await host.SendAsync(HttpMethod.Get, "/api/v1/stage")).Body!["revision"]!.GetValue<long>());
        await sync.SelectAsync(null, ct);
        Assert.Equal("stand", (await host.SendAsync(HttpMethod.Get, "/api/v1/stage")).Body!["posture"]!.GetValue<string>());
        Assert.Throws<InvalidOperationException>(() => StageEndpoints.ValidateConfiguration(new ConfigurationBuilder().AddInMemoryCollection(new Dictionary<string, string?> { [StageEndpoints.ConfigKey] = "http://127.0.0.1:5002" }).Build()));
    }
}
