using Aijade.Server.Mcp;
using Aijade.Server.Product;
using Aijade.Server.Tools;
using Aijade.Server.Infrastructure;
using Aijade.Server.V9;

namespace Aijade.Server;

/// <summary>
/// The host's optional integrations. The companion profile keeps chat, sync, media, memory and the event pipeline;
/// full preserves the existing deployment. Profiles compose existing code and do not install or execute plugins.
/// </summary>
public sealed record ServerModules(string Profile, bool Mcp, bool Tools, bool Stage, bool Billing)
{
    public static ServerModules Read(IConfiguration config)
    {
        var profile = (config["Aijade:Profile"] ?? "full").ToLowerInvariant();
        if (profile is not ("full" or "companion"))
            throw new InvalidOperationException("Aijade:Profile must be full or companion");
        var keys = new HashSet<string>(["Mcp", "Tools", "Stage", "Billing"], StringComparer.OrdinalIgnoreCase);
        foreach (var row in config.GetSection("Aijade:Modules").GetChildren())
        {
            if (!keys.Contains(row.Key) || !bool.TryParse(row.Value, out _))
                throw new InvalidOperationException($"Aijade:Modules:{row.Key} must name a supported module and contain true or false");
        }
        bool Enabled(string name) => bool.TryParse(config[$"Aijade:Modules:{name}"], out var enabled) ? enabled : profile == "full";
        return new(profile, Enabled("Mcp"), Enabled("Tools"), Enabled("Stage"), Enabled("Billing"));
    }

    public void Register(IServiceCollection services, IConfiguration config)
    {
        services.AddSingleton(this);
        if (Mcp)
            services.AddAijadeMcp();
        if (Tools)
        {
            services.AddHttpClient(ToolHub.HttpClientName, c => c.Timeout = TimeSpan.FromSeconds(60));
            services.AddSingleton<ToolsConfigStore>();
            services.AddSingleton<ToolHub>();
        }
        if (Stage)
        {
            StageEndpoints.Workbench(config[StageEndpoints.ConfigKey]);
            services.AddHttpClient(StageEndpoints.HttpClientName, c => c.Timeout = TimeSpan.FromSeconds(10));
        }
        if (Billing)
        {
            services.AddHttpClient(BillingEndpoints.HttpClientName, c => c.Timeout = TimeSpan.FromSeconds(30));
            services.Configure<StripeOptions>(o =>
            {
                var stripe = config.GetSection("Stripe");
                o.SecretKey = stripe["SecretKey"];
                o.WebhookSecret = stripe["WebhookSecret"];
                o.SuccessUrl = stripe["SuccessUrl"] ?? o.SuccessUrl;
                o.CancelUrl = stripe["CancelUrl"] ?? o.CancelUrl;
                o.ApiBase = stripe["ApiBase"] ?? o.ApiBase;
                foreach (var price in stripe.GetSection("Prices").GetChildren())
                {
                    if (long.TryParse(price.Value, out var flux))
                        o.Prices[price.Key] = flux;
                }
            });
        }
    }

    public void Map(WebApplication app, string role, bool redis)
    {
        app.MapGet("/api/v1/runtime", () => Results.Json(new
        {
            profile = Profile, role, queue = redis ? "redis" : "inline",
            modules = new { mcp = Mcp, tools = Tools, stage = Stage, billing = Billing },
        })).RequireAuthorization();
        if (Mcp)
            app.MapAijadeMcp();
        if (Tools)
            ToolEndpoints.Map(app);
        if (Stage)
            StageEndpoints.Map(app);
        if (Billing)
            BillingEndpoints.Map(app);
    }
}

/// <summary>
/// Single-process product scheduling: drain the existing, unchanged v9 processor, then sleep until enqueue wakes it.
/// Redis and the full research-compatible profile retain the original worker and its timing.
/// </summary>
internal sealed class CompanionWorker(V9Worker processor, IJobBroker broker, ILogger<CompanionWorker> log) : BackgroundService
{
    protected override async Task ExecuteAsync(CancellationToken stoppingToken)
    {
        try
        {
            while (!stoppingToken.IsCancellationRequested)
            {
                try
                {
                    if (!await processor.DrainOnceAsync(stoppingToken).ConfigureAwait(false))
                    {
                        if (broker is IJobWakeup wakeup)
                            await wakeup.WaitForWorkAsync(stoppingToken).ConfigureAwait(false);
                        else
                            await Task.Delay(1000, stoppingToken).ConfigureAwait(false);
                    }
                }
                catch (Exception e) when (!stoppingToken.IsCancellationRequested && e is not OperationCanceledException)
                {
                    log.LogError(e, "Companion job processing failed; queued work remains available");
                    await Task.Delay(1000, stoppingToken).ConfigureAwait(false);
                }
            }
        }
        catch (OperationCanceledException) when (stoppingToken.IsCancellationRequested) { }
    }
}
