using Aijade.Bots;
using Aijade.Client.Api;
using Aijade.Client.Chat;
using Aijade.Integrations;

using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

// Configuration (environment variables use __ for ':'):
//   Aijade:Server        the AIJADE server, e.g. https://aijade.example/
//   Aijade:Token         a bot account's token (a static token from the server's Auth:StaticTokens, or a session token)
//   Bridge:CharacterId   optional character the companion plays here; Bridge:Drawing / Bridge:Memory / Bridge:Tools true/false
//   Bridge:Model, Bridge:MaxToolRounds (default 4), Bridge:MaxToolCalls (default 12)  bounded per-turn tool worker
//   Bridge:ToolTimeoutSeconds (default 30), Bridge:PromptBudget:{Module,Supplement,History,ToolResult}Characters
//   Bridge:StateFile     where conversation → chat mappings are kept (default ./aijade-bots-state.json)
//   Bridge:Reminders     false to keep no reminders; otherwise she keeps those asked for in private conversations on the
//                        platforms that can start a message (QQ, Telegram) and says them when due (ADR-003)
//   Renderer:MosaicPort  optional: drive the MOSAIC native MMD client (--behavior-live PORT) with each reply's PEF intent
//   Discord:Token, Telegram:Token   a connector runs for each one that is set
//   Satori:Url (+ Satori:Token)     a Satori server, e.g. http://localhost:5140/satori/ (QQ, OneBot, KOOK … through Koishi)
//   OneBot:NapCat (+ Port, TokenFile, SecretFile, Owner, Voice)   QQ through NapCat's OneBot 11 HTTP server, e.g.
//                                   http://127.0.0.1:3000; NapCat's HTTP client posts events to 127.0.0.1:Port (default 8795); only
//                                   the owner's private messages are answered (ADR-003, as MOSAIC's tools/companion_qq.py);
//                                   Voice=true transcribes voice messages through the server's speech recognition
//   X:AccessToken                   an OAuth 2.0 user-context token of the bot's X account
//   Minecraft:Host (+ Port, Name)   an offline-mode Java server (26.3, protocol 777; enforce-secure-profile=false)
//   Bilibili:RoomId (+ Bilibili:Cookie)   a live room; with the owner's cookie viewers are identified and replies are sent
var builder = Host.CreateApplicationBuilder(args);
var config = builder.Configuration;
var server = ServerAddressHandler.ParseServer(config["Aijade:Server"]) ?? throw new InvalidOperationException("Aijade:Server must be an http(s) URL");
var token = config["Aijade:Token"] is { Length: > 0 } t ? t : throw new InvalidOperationException("Aijade:Token is required");
builder.Services.AddSingleton<CompanionConfiguration>();

builder.Services.AddSingleton(_ =>
{
    var tokens = new MemoryTokenStore();
    tokens.SetAsync(token).AsTask().GetAwaiter().GetResult();
    return new AijadeApi(new HttpClient { BaseAddress = server, Timeout = TimeSpan.FromMinutes(5) }, tokens);
});
if (int.TryParse(config["Renderer:MosaicPort"], out var mosaicPort))
    builder.Services.AddSingleton(_ => new Aijade.Integrations.Renderer.MosaicRendererLink(mosaicPort));
builder.Services.AddSingleton(sp => new CompanionBridge(sp.GetRequiredService<AijadeApi>(), new BridgeOptions
{
    CharacterId = config["Bridge:CharacterId"] is { Length: > 0 } c ? c : null,
    Drawing = bool.TryParse(config["Bridge:Drawing"], out var draw) && draw,
    Tools = bool.TryParse(config["Bridge:Tools"], out var tools) && tools,
    Memory = !bool.TryParse(config["Bridge:Memory"], out var memory) || memory,
    Orchestrator = new OrchestratorOptions
    {
        Model = config["Bridge:Model"] ?? "aijade-chat",
        MaxToolRounds = int.TryParse(config["Bridge:MaxToolRounds"], out var rounds) ? rounds : 4,
        MaxToolCalls = int.TryParse(config["Bridge:MaxToolCalls"], out var calls) ? calls : 12,
        ToolTimeoutSeconds = int.TryParse(config["Bridge:ToolTimeoutSeconds"], out var seconds) ? seconds : 30,
        PromptBudget = new PromptBudget
        {
            ModuleCharacters = int.TryParse(config["Bridge:PromptBudget:ModuleCharacters"], out var moduleChars) ? moduleChars : 4_000,
            SupplementCharacters = int.TryParse(config["Bridge:PromptBudget:SupplementCharacters"], out var supplementChars) ? supplementChars : 12_000,
            HistoryCharacters = int.TryParse(config["Bridge:PromptBudget:HistoryCharacters"], out var historyChars) ? historyChars : 24_000,
            ToolResultCharacters = int.TryParse(config["Bridge:PromptBudget:ToolResultCharacters"], out var toolChars) ? toolChars : 8_000,
        },
    },
    StateFile = config["Bridge:StateFile"] is { Length: > 0 } f ? f : "aijade-bots-state.json",
    Companion = sp.GetRequiredService<CompanionConfiguration>().For,
    ResolveCompanion = sp.GetRequiredService<CompanionConfiguration>().ForAsync,
    PairCompanion = sp.GetRequiredService<CompanionConfiguration>().PairAsync,
    SpeakFirst = bool.TryParse(config["Bridge:SpeakFirst"], out var first) && first,
    TimeZone = sp.GetRequiredService<CompanionConfiguration>().Profile.Zone,
    ReminderPlatforms = bool.TryParse(config["Bridge:Reminders"], out var remind) && !remind
        ? []
        : sp.GetServices<IChannelConnector>().OfType<IProactiveConnector>().Select(c => c.Platform).ToArray(),
    OnPerformance = sp.GetService<Aijade.Integrations.Renderer.MosaicRendererLink>() is { } renderer
        ? (intent, message) => renderer.SendAsync(intent, message.Key)
        : null,
}));
if (config["Discord:Token"] is { Length: > 0 } discord)
    builder.Services.AddSingleton<IChannelConnector>(sp => new DiscordConnector(discord, sp.GetRequiredService<AijadeApi>(), sp.GetRequiredService<ILogger<DiscordConnector>>()));
if (config["Telegram:Token"] is { Length: > 0 } telegram)
    builder.Services.AddSingleton<IChannelConnector>(sp => new TelegramConnector(telegram, sp.GetRequiredService<AijadeApi>(), sp.GetRequiredService<ILogger<TelegramConnector>>()));
foreach (var connector in Connectors.Extra(config))
    builder.Services.AddSingleton(connector);
if (config["OneBot:NapCat"] is { Length: > 0 })
    builder.Services.AddSingleton<IChannelConnector>(sp => Connectors.OneBot(config, sp.GetRequiredService<AijadeApi>(), sp.GetRequiredService<CompanionConfiguration>())!);
builder.Services.AddHostedService<ConnectorHost>();
await builder.Build().RunAsync();
