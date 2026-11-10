using System.Text.Json.Nodes;

using Aijade.Server;
using Aijade.Server.Infrastructure;
using Aijade.Server.Tools;

using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

namespace Aijade.Tests;

public sealed class ServerModulesTests
{
    [Fact]
    public void Profiles_preserve_full_compatibility_and_reject_misspelled_or_invalid_module_configuration()
    {
        var full = ServerModules.Read(new ConfigurationBuilder().Build());
        Assert.True(full is { Mcp: true, Tools: true, Stage: true, Billing: true });
        foreach (var pair in new[] { ("Aijade:Profile", "unknown"), ("Aijade:Modules:Toolz", "true"), ("Aijade:Modules:Tools", "perhaps") })
            Assert.Throws<InvalidOperationException>(() => ServerModules.Read(new ConfigurationBuilder()
                .AddInMemoryCollection(new Dictionary<string, string?> { [pair.Item1] = pair.Item2 }).Build()));
    }

    [Fact]
    public async Task An_idle_queue_waits_for_work_without_polling_and_wakeup_hints_do_not_consume_jobs()
    {
        var ct = TestContext.Current.CancellationToken;
        var queue = new InMemoryJobBroker();
        using var stop = CancellationTokenSource.CreateLinkedTokenSource(ct);
        var waiting = queue.WaitForWorkAsync(stop.Token); Assert.False(waiting.IsCompleted);
        await queue.EnqueueAsync(Queues.Memory, new JsonObject { ["id"] = "first" }, ct);
        await queue.EnqueueAsync(Queues.Memory, new JsonObject { ["id"] = "second" }, ct);
        await waiting.WaitAsync(TimeSpan.FromSeconds(3), ct);
        Assert.Equal(2, await queue.LengthAsync(Queues.Memory, ct));
        Assert.Equal("first", (await queue.TryDequeueAsync(Queues.Memory, ct))!["id"]!.GetValue<string>());
        Assert.Equal("second", (await queue.TryDequeueAsync(Queues.Memory, ct))!["id"]!.GetValue<string>());
        // Drain any coalesced hint; after that an idle wait must remain cancellable.
        using var idle = CancellationTokenSource.CreateLinkedTokenSource(ct);
        idle.Cancel();
        await Assert.ThrowsAnyAsync<OperationCanceledException>(() => queue.WaitForWorkAsync(idle.Token));
    }

    [Theory]
    [InlineData(false)]
    [InlineData(true)]
    public async Task The_companion_profile_mounts_only_selected_integrations_and_still_processes_memory_outbox(bool tools)
    {
        var ct = TestContext.Current.CancellationToken;
        await using var host = await ServerTestHost.StartAsync(new Dictionary<string, string?>
        {
            ["Aijade:Profile"] = "companion", ["Aijade:Modules:Tools"] = tools.ToString(), ["Aijade:ServeWeb"] = "false",
            ["Stage:WorkbenchUrl"] = "https://unused.example/", // A disabled integration is not started or probed.
        });
        var (status, manifest) = await host.SendAsync(HttpMethod.Get, "/api/v1/runtime");
        Assert.Equal(200, status); Assert.Equal("companion", manifest!["profile"]!.GetValue<string>());
        Assert.Equal("inline", manifest["queue"]!.GetValue<string>());
        Assert.Equal(tools, manifest["modules"]!["tools"]!.GetValue<bool>());
        Assert.Equal(tools, host.App.Services.GetService<ToolHub>() is not null);
        Assert.Equal(tools ? 200 : 404, (await host.SendAsync(HttpMethod.Get, "/api/v1/tools")).Status);
        Assert.Equal(404, (await host.SendAsync(HttpMethod.Get, "/api/v1/stripe/prices")).Status);
        Assert.Equal(401, (await host.SendAsync(HttpMethod.Get, "/api/v1/runtime", token: null)).Status);
        var saved = await host.SendAsync(HttpMethod.Post, "/api/v1/memory/persona-snapshots", new JsonObject
        {
            ["deviceId"] = "web", ["privacyLevel"] = 1, ["persona"] = new JsonObject(), ["version"] = 1,
        });
        Assert.Equal(201, saved.Status);
        var deadline = DateTimeOffset.UtcNow.AddSeconds(5);
        while (await host.CountAsync("SELECT count(*) FROM memory_sync_outbox WHERE status = 'processed'") == 0 && DateTimeOffset.UtcNow < deadline)
            await Task.Delay(20, ct);
        Assert.Equal(1, await host.CountAsync("SELECT count(*) FROM memory_sync_outbox WHERE status = 'processed'"));
    }
}
