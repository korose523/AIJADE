using Aijade.Integrations;

using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace Aijade.Bots;

/// <summary>Runs every configured connector, restarting one that fails (with backoff) without touching the others.</summary>
public sealed class ConnectorHost(IEnumerable<IChannelConnector> connectors, CompanionBridge bridge, ILogger<ConnectorHost> log) : BackgroundService
{
    protected override Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var all = connectors.ToList();
        if (all.Count == 0)
            log.LogWarning("No connector is configured (set Discord:Token, Telegram:Token, …)");
        return Task.WhenAll(all.Select(c => RunAsync(c, stoppingToken)));
    }

    private async Task RunAsync(IChannelConnector connector, CancellationToken ct)
    {
        var delay = TimeSpan.FromSeconds(5);
        while (!ct.IsCancellationRequested)
        {
            try
            {
                log.LogInformation("Starting {Platform}", connector.Platform);
                await connector.RunAsync(bridge.AnswerAsync, ct).ConfigureAwait(false);
                delay = TimeSpan.FromSeconds(5);
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested)
            {
                return;
            }
            catch (Exception e)
            {
                log.LogError(e, "{Platform} stopped; restarting in {Delay}", connector.Platform, delay);
            }
            try
            {
                await Task.Delay(delay, ct).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                return;
            }
            delay = TimeSpan.FromSeconds(Math.Min(300, delay.TotalSeconds * 2));
        }
    }
}

/// <summary>Connectors without a platform SDK, configured the same way (added as they are implemented).</summary>
public static class Connectors
{
    public static IEnumerable<IChannelConnector> Extra(IConfiguration config)
    {
        if (config["Satori:Url"] is { Length: > 0 } satori)
            yield return new SatoriConnector(new Uri(satori.TrimEnd('/') + "/"), config["Satori:Token"], new HttpClient { Timeout = TimeSpan.FromSeconds(30) });
        if (config["Minecraft:Host"] is { Length: > 0 } mc)
            yield return new Aijade.Integrations.Minecraft.MinecraftConnector(mc, int.TryParse(config["Minecraft:Port"], out var p) ? p : 25565, config["Minecraft:Name"] is { Length: > 0 } n ? n : "Aijade");
        if (long.TryParse(config["Bilibili:RoomId"], out var room))
            yield return new BilibiliLiveConnector(room, config["Bilibili:Cookie"], new HttpClient { Timeout = TimeSpan.FromSeconds(30) });
        if (config["X:AccessToken"] is { Length: > 0 } x)
            yield return new XConnector(x, new HttpClient { Timeout = TimeSpan.FromSeconds(30) });
    }
}
