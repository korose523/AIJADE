using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.ComputerUse;

using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

using ModelContextProtocol.Protocol;

// An MCP server on stdio offering one tool, computer_use. Configure it as an mcp-stdio tool provider on the AIJADE
// server (command: path to this executable), or in any MCP client. AIJADE_COMPUTER_USE_ALLOW lists the desktop-changing
// actions that may run ("all", or e.g. "click,type,key"); without it only capture, wait and list_apps work.
var builder = Host.CreateApplicationBuilder(args);
builder.Logging.AddConsole(o => o.LogToStandardErrorThreshold = LogLevel.Trace); // stdout belongs to the protocol

IDesktop desktop = OperatingSystem.IsMacOS() ? new MacDesktop()
    : OperatingSystem.IsWindows() ? new WindowsDesktop()
    : throw new PlatformNotSupportedException("computer use is implemented for macOS and Windows");
var tool = new ComputerUseTool(desktop, ComputerUsePolicy.FromEnvironment(Environment.GetEnvironmentVariable("AIJADE_COMPUTER_USE_ALLOW")));

builder.Services.AddMcpServer(o => o.ServerInfo = new() { Name = "aijade-computer-use", Version = "0.1.0" })
    .WithStdioServerTransport()
    .WithListToolsHandler((_, _) => ValueTask.FromResult(new ListToolsResult
    {
        Tools = [new Tool { Name = "computer_use", Description = ComputerUseTool.Description, InputSchema = JsonSerializer.Deserialize<JsonElement>(ComputerUseTool.Schema().ToJsonString()) }],
    }))
    .WithCallToolHandler(async (request, ct) =>
    {
        if (request.Params?.Name != "computer_use")
            return new CallToolResult { IsError = true, Content = [new TextContentBlock { Text = $"unknown tool '{request.Params?.Name}'" }] };
        var args = request.Params.Arguments is { } a ? JsonNode.Parse(JsonSerializer.Serialize(a)) as JsonObject ?? [] : [];
        var result = await tool.RunAsync(args, ct);
        List<ContentBlock> content = [new TextContentBlock { Text = result.Summary }];
        if (result.Png is { } png)
            content.Add(ImageContentBlock.FromBytes(png, "image/png"));
        return new CallToolResult { IsError = !result.Ok, Content = content };
    });
await builder.Build().RunAsync();
