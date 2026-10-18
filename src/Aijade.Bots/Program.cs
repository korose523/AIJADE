using Aijade.Bots;
using Aijade.Client.Api;
using Aijade.Integrations;

using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

// Configuration (environment variables use __ for ':'):
//   Aijade:Server        the AIJADE server, e.g. https://aijade.example/
//   Aijade:Token         a bot account's token (a static token from the server's Auth:StaticTokens, or a session token)
//   Bridge:CharacterId   optional character the companion plays here; Bridge:Drawing / Bridge:Memory / Bridge:Tools true/false
//   Bridge:StateFile     where conversation → chat mappings are kept (default ./aijade-bots-state.json)
//   Renderer:MosaicPort  optional: drive the MOSAIC native MMD client (--behavior-live PORT) with each reply's PEF intent
//   Discord:Token, Telegram:Token   a connector runs for each one that is set
//   Satori:Url (+ Satori:Token)     a Satori server, e.g. http://localhost:5140/satori/ (QQ, OneBot, KOOK … through Koishi)
//   X:AccessToken                   an OAuth 2.0 user-context token of the bot's X account
//   Minecraft:Host (+ Port, Name)   an offline-mode Java server (26.3, protocol 777; enforce-secure-profile=false)
//   Bilibili:RoomId (+ Bilibili:Cookie)   a live room; with the owner's cookie viewers are identified and replies are sent
var builder = Host.CreateApplicationBuilder(args);
var config = builder.Configuration;
var server = ServerAddressHandler.ParseServer(config["Aijade:Server"]) ?? throw new InvalidOperationException("Aijade:Server must be an http(s) URL");
var token = config["Aijade:Token"] is { Length: > 0 } t ? t : throw new InvalidOperationException("Aijade:Token is required");

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
    StateFile = config["Bridge:StateFile"] is { Length: > 0 } f ? f : "aijade-bots-state.json",
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
builder.Services.AddHostedService<ConnectorHost>();
await builder.Build().RunAsync();
