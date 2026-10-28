using Aijade.Memory.V9;
using Aijade.Server.Auth;
using Aijade.Server.Infrastructure;
using Aijade.Server.Memory;
using Aijade.Server.Mcp;
using Aijade.Server.Product;
using Aijade.Server.V9;

using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.DataProtection;

using Npgsql;

using StackExchange.Redis;

namespace Aijade.Server;

// Host composition. Configuration (environment variables or appsettings):
//   DATABASE_URL / ConnectionStrings:Postgres   PostgreSQL (required)
//   REDIS_URL                                   Redis; when set, jobs go to a worker process, else they run inline
//   Aijade:Role                                 api | worker | all (default all)
//   Aijade:MigrateOnStartup                     default true
//   Aijade:DispatchObservations                 dispatch video observations to the learning runtime (default true)
//   Aijade:ServeWeb                             serve the web app from this origin (default true)
//   Aijade:ModelsDir                            a local folder of the user's MMD models, served read-only at /models/
//   Aijade:ImagePollMs / ImageTimeoutSeconds    polling of asynchronous image backends (default 1000 ms / 180 s)
//   Aijade:SelfUrl                              this server's own base URL for the MCP tools' API calls (default: the request's)
//   Auth:StaticTokens:<token> = <userId>        development / e2e only

public static class AijadeServer
{
    /// <summary>A postgres:// URL or an Npgsql connection string, as an Npgsql connection string.</summary>
    public static string NormalizeConnectionString(string value)
    {
        if (!value.StartsWith("postgres://", StringComparison.Ordinal) && !value.StartsWith("postgresql://", StringComparison.Ordinal))
            return value;
        var uri = new Uri(value);
        var userInfo = uri.UserInfo.Split(':', 2);
        var b = new NpgsqlConnectionStringBuilder
        {
            Host = uri.Host,
            Port = uri.IsDefaultPort || uri.Port <= 0 ? 5432 : uri.Port,
            Database = uri.AbsolutePath.Trim('/'),
            Username = Uri.UnescapeDataString(userInfo[0]),
        };
        if (userInfo.Length > 1)
            b.Password = Uri.UnescapeDataString(userInfo[1]);
        return b.ConnectionString;
    }

    public static WebApplication Build(string[] args, Action<WebApplicationBuilder>? configure = null)
    {
        var builder = WebApplication.CreateBuilder(args);
        configure?.Invoke(builder);
        var config = builder.Configuration;
        var connection = config["DATABASE_URL"] ?? config.GetConnectionString("Postgres")
            ?? throw new InvalidOperationException("DATABASE_URL (or ConnectionStrings:Postgres) is required");
        var role = config["Aijade:Role"] ?? "all";

        builder.Services.AddSingleton(_ => new NpgsqlDataSourceBuilder(NormalizeConnectionString(connection)).Build());
        builder.Services.AddSingleton(TimeProvider.System);
        var redisUrl = config["REDIS_URL"];
        if (!string.IsNullOrEmpty(redisUrl))
        {
            builder.Services.AddSingleton<IConnectionMultiplexer>(_ => ConnectionMultiplexer.Connect(redisUrl.Replace("redis://", "", StringComparison.Ordinal)));
            builder.Services.AddSingleton<IJobBroker, RedisJobBroker>();
        }
        else
        {
            builder.Services.AddSingleton<IJobBroker, InMemoryJobBroker>();
        }
        builder.Services.AddSingleton<IV9RuntimeStore, V9RuntimeStore>();
        builder.Services.AddSingleton(sp => new V9CausalRuntime(sp.GetRequiredService<IV9RuntimeStore>()));
        builder.Services.AddSingleton<V9EventService>();
        builder.Services.AddSingleton(sp => new ServerRuntime(sp.GetRequiredService<V9CausalRuntime>(), sp.GetRequiredService<IJobBroker>(),
            sp.GetRequiredService<V9EventService>(), sp.GetRequiredService<ILogger<ServerRuntime>>(), !string.IsNullOrEmpty(redisUrl),
            !bool.TryParse(config["Aijade:DispatchObservations"], out var dispatch) || dispatch));
        builder.Services.AddSingleton<PromotionService>();
        builder.Services.AddSingleton<EvidenceDomainService>();
        builder.Services.AddSingleton<LongTermMemoryService>();
        builder.Services.AddSingleton<AccountService>();
        builder.Services.AddSingleton<FluxLedger>();
        builder.Services.AddSingleton<ProductEvents>();
        builder.Services.AddSingleton<ChatHub>();
        builder.Services.AddSingleton<GatewayRoutes>();
        builder.Services.AddSingleton<KeyRotator>();
        builder.Services.AddSingleton<ImageBackends>();
        builder.Services.AddSingleton<EmbeddingService>();
        builder.Services.AddAijadeMcp();
        builder.Services.AddHttpClient(Aijade.Server.Tools.ToolHub.HttpClientName, c => c.Timeout = TimeSpan.FromSeconds(60));
        builder.Services.AddSingleton<Aijade.Server.Tools.ToolsConfigStore>();
        builder.Services.AddSingleton<Aijade.Server.Tools.ToolHub>();
        builder.Services.AddHttpClient(GatewayEndpoints.HttpClientName, c => c.Timeout = TimeSpan.FromMinutes(5));
        builder.Services.AddHttpClient(BillingEndpoints.HttpClientName, c => c.Timeout = TimeSpan.FromSeconds(30));
        // The owner's MOSAIC stage: refuse at start a workbench address that is not on this machine (it has no authentication).
        StageEndpoints.Workbench(config[StageEndpoints.ConfigKey]);
        builder.Services.AddHttpClient(StageEndpoints.HttpClientName, c => c.Timeout = TimeSpan.FromSeconds(10));
        builder.Services.Configure<StripeOptions>(o =>
        {
            var s = config.GetSection("Stripe");
            o.SecretKey = s["SecretKey"];
            o.WebhookSecret = s["WebhookSecret"];
            o.SuccessUrl = s["SuccessUrl"] ?? o.SuccessUrl;
            o.CancelUrl = s["CancelUrl"] ?? o.CancelUrl;
            o.ApiBase = s["ApiBase"] ?? o.ApiBase;
            foreach (var p in s.GetSection("Prices").GetChildren())
            {
                if (long.TryParse(p.Value, out var flux))
                    o.Prices[p.Key] = flux;
            }
        });
        var dataProtection = builder.Services.AddDataProtection().SetApplicationName("aijade");
        if (config["DataProtection:KeysDir"] is { Length: > 0 } keysDir)
            dataProtection.PersistKeysToFileSystem(new DirectoryInfo(keysDir));
        builder.Services.Configure<AuthOptions>(o =>
        {
            foreach (var t in config.GetSection("Auth:StaticTokens").GetChildren())
            {
                if (!string.IsNullOrEmpty(t.Value))
                    o.StaticTokens[t.Key] = t.Value;
            }
            if (bool.TryParse(config["Auth:AllowSignUp"], out var allow))
                o.AllowSignUp = allow;
        });
        var auth = builder.Services.AddAuthentication(BearerAuthHandler.SchemeName)
            .AddScheme<AuthenticationSchemeOptions, BearerAuthHandler>(BearerAuthHandler.SchemeName, null);
        OidcSetup.Add(auth, config);
        builder.Services.AddAuthorization(o => o.AddPolicy(AdminEndpoints.Policy, p => p.RequireRole("admin")));
        if (role is "worker" or "all")
        {
            builder.Services.AddSingleton<V9Worker>();
            builder.Services.AddHostedService(sp => sp.GetRequiredService<V9Worker>());
        }

        var app = builder.Build();
        app.UseMiddleware<ApiErrorMiddleware>();
        app.UseWebSockets();
        app.UseAuthentication();
        app.UseAuthorization();
        app.MapGet("/healthz", () => Results.Json(new { ok = true }));
        // The web app (Blazor WebAssembly) is served from the same origin unless Aijade:ServeWeb is false.
        if (role is "api" or "all" && (!bool.TryParse(config["Aijade:ServeWeb"], out var serveWeb) || serveWeb))
        {
            app.UseBlazorFrameworkFiles();
            app.UseStaticFiles(new StaticFileOptions { ContentTypeProvider = MmdContentTypes() });
            // A local directory of the user's own (licensed) MMD models and motions, served read-only at /models/.
            // Models are never bundled with AIJADE: each comes with its author's terms.
            if (config["Aijade:ModelsDir"] is { Length: > 0 } modelsDir && Directory.Exists(modelsDir))
            {
                app.UseStaticFiles(new StaticFileOptions
                {
                    FileProvider = new Microsoft.Extensions.FileProviders.PhysicalFileProvider(Path.GetFullPath(modelsDir)),
                    RequestPath = "/models",
                    ContentTypeProvider = MmdContentTypes(),
                });
            }
            app.MapFallbackToFile("index.html");
        }
        if (role is "api" or "all")
        {
            AuthEndpoints.Map(app);
            OidcSetup.Map(app, config);
            V9Endpoints.Map(app);
            MemoryEndpoints.Map(app);
            MemoryLibrary.Map(app);
            LibraryEndpoints.Map(app);
            GatewayEndpoints.Map(app);
            ImageEndpoints.Map(app);
            LiveContextEndpoints.Map(app);
            StageEndpoints.Map(app);
            app.MapAijadeMcp();
            Aijade.Server.Tools.ToolEndpoints.Map(app);
            BillingEndpoints.Map(app);
            AdminEndpoints.Map(app);
        }
        return app;
    }

    /// <summary>Static-file content types including the MMD formats (models, motions, poses) and their texture formats.</summary>
    public static Microsoft.AspNetCore.StaticFiles.FileExtensionContentTypeProvider MmdContentTypes()
    {
        var p = new Microsoft.AspNetCore.StaticFiles.FileExtensionContentTypeProvider();
        foreach (var ext in new[] { ".pmx", ".pmd", ".vmd", ".vpd", ".bpmx", ".bvmd" })
            p.Mappings[ext] = "application/octet-stream";
        p.Mappings[".tga"] = "image/x-tga";
        p.Mappings[".dds"] = "image/vnd-ms.dds";
        p.Mappings[".spa"] = "image/bmp";
        p.Mappings[".sph"] = "image/bmp";
        return p;
    }

    /// <summary>Apply migrations (unless disabled) before serving.</summary>
    public static async Task PrepareAsync(WebApplication app)
    {
        var db = app.Services.GetRequiredService<NpgsqlDataSource>();
        if (!bool.TryParse(app.Configuration["Aijade:MigrateOnStartup"], out var migrate) || migrate)
            await Migrator.MigrateAsync(db).ConfigureAwait(false);
        // Development / e2e static tokens act as real users, so everything owned by a user works for them too.
        await using var conn = await db.OpenConnectionAsync().ConfigureAwait(false);
        foreach (var (_, userId) in app.Services.GetRequiredService<Microsoft.Extensions.Options.IOptions<AuthOptions>>().Value.StaticTokens)
        {
            await Sql.ExecAsync(conn, null, "INSERT INTO users (id, email, name) VALUES ($1, $2, $1) ON CONFLICT DO NOTHING", CancellationToken.None,
                Sql.Text(userId), Sql.Text($"{userId}@static.local")).ConfigureAwait(false);
        }
    }
}
