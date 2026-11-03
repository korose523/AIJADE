using Aijade.Client.Api;
using Aijade.Integrations;

using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace Aijade.Bots;

/// <summary>
/// Runs every configured connector, restarting one that fails (with backoff) without touching the others, and says the
/// reminders she promised when they fall due, through the connectors that can start a message.
/// </summary>
public sealed class ConnectorHost(IEnumerable<IChannelConnector> connectors, CompanionBridge bridge, ILogger<ConnectorHost> log) : BackgroundService
{
    /// <summary>How often due reminders are looked for (REMIND_EVERY_S of MOSAIC's QQ bridge).</summary>
    public static readonly TimeSpan RemindEvery = TimeSpan.FromSeconds(15);

    protected override Task ExecuteAsync(CancellationToken stoppingToken)
    {
        var all = connectors.ToList();
        if (all.Count == 0)
            log.LogWarning("No connector is configured (set Discord:Token, Telegram:Token, …)");
        var proactive = all.OfType<IProactiveConnector>().ToDictionary(c => c.Platform, StringComparer.Ordinal);
        return Task.WhenAll(all.Select(c => RunAsync(c, stoppingToken)).Append(RemindLoopAsync(bridge, proactive, log, RemindEvery, stoppingToken)));
    }

    /// <summary>
    /// Says each due reminder in its conversation, looking every <paramref name="every"/>. As in MOSAIC's bridge, a line that
    /// was made but could not be sent is logged, not made again; a line that could not be made is tried again at the next
    /// check. Only stopping ends the loop: a failed check, a timeout included, is logged and the next one comes.
    /// </summary>
    public static async Task RemindLoopAsync(CompanionBridge bridge, IReadOnlyDictionary<string, IProactiveConnector> proactive, ILogger log, TimeSpan every, CancellationToken ct)
    {
        if (proactive.Count == 0)
            return;
        using var timer = new PeriodicTimer(every);
        try
        {
            while (await timer.WaitForNextTickAsync(ct).ConfigureAwait(false))
            {
                try
                {
                    await RemindOnceAsync(bridge, proactive, ct).ConfigureAwait(false);
                }
                catch (Exception e) when (!ct.IsCancellationRequested) // an HttpClient timeout is a TaskCanceledException too
                {
                    log.LogWarning(e, "A due reminder could not be said; the checks go on");
                }
            }
        }
        catch (OperationCanceledException) when (ct.IsCancellationRequested)
        {
        }
    }

    /// <summary>Says the reminders due now (several when the host was stopped meanwhile); how many were said.</summary>
    public static async Task<int> RemindOnceAsync(CompanionBridge bridge, IReadOnlyDictionary<string, IProactiveConnector> proactive, CancellationToken ct)
    {
        var said = 0;
        while (await bridge.DueReminderAsync(key => proactive.ContainsKey(key[..key.IndexOf(':', StringComparison.Ordinal)]), ct).ConfigureAwait(false) is { } due)
        {
            var split = due.Reminder.Conversation.IndexOf(':', StringComparison.Ordinal);
            await proactive[due.Reminder.Conversation[..split]].SendAsync(due.Reminder.Conversation[(split + 1)..], due.Line, ct).ConfigureAwait(false);
            said++;
        }
        return said;
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

    /// <summary>
    /// QQ through NapCat (OneBot:NapCat set), or null. With OneBot:Voice=true her owner's voice messages are transcribed by the
    /// server's speech recognition (the gateway's transcription route; MOSAIC's bridge does it with --asr).
    /// </summary>
    public static OneBotConnector? OneBot(IConfiguration config, AijadeApi api) =>
        config["OneBot:NapCat"] is not { Length: > 0 } napcat ? null
            : new OneBotConnector(int.TryParse(config["OneBot:Port"], out var port) ? port : 8795, new Uri(napcat),
                KeyFile(config["OneBot:TokenFile"], "OneBot:TokenFile"), KeyFile(config["OneBot:SecretFile"], "OneBot:SecretFile"),
                config["OneBot:Owner"] is { Length: > 0 } owner ? owner : throw new InvalidOperationException("OneBot:Owner (the owner's QQ number) is required"),
                new HttpClient { Timeout = TimeSpan.FromSeconds(30) },
                bool.TryParse(config["OneBot:Voice"], out var voice) && voice ? (wav, ct) => api.TranscribeAsync(wav, "audio/wav", "zh-CN", 0, ct) : null);

    /// <summary>A key read from a file, as MOSAIC's bridge reads them: never from the command line or the environment.</summary>
    private static string KeyFile(string? path, string setting) =>
        path is { Length: > 0 } && File.Exists(path) ? File.ReadAllText(path).Trim() : throw new InvalidOperationException($"{setting} must name a file that holds the key");
}
