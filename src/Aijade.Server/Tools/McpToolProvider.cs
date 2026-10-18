using System.Text.Json;
using System.Text.Json.Nodes;

using ModelContextProtocol;
using ModelContextProtocol.Client;
using ModelContextProtocol.Protocol;

namespace Aijade.Server.Tools;

/// <summary>
/// Tools of an external MCP server, reached over Streamable HTTP or by starting it as a local process (stdio). The
/// connection opens on first use and is reopened after a failure.
/// </summary>
public sealed class McpToolProvider : IToolProvider
{
    private readonly Func<IClientTransport> transport;
    private readonly SemaphoreSlim gate = new(1, 1);
    private McpClient? client;

    private McpToolProvider(Func<IClientTransport> transport) => this.transport = transport;

    public static McpToolProvider Http(string id, Uri url, IReadOnlyDictionary<string, string> headers, HttpClient http) =>
        new(() => new HttpClientTransport(new HttpClientTransportOptions { Name = id, Endpoint = url, AdditionalHeaders = headers.ToDictionary() }, http));

    /// <summary>A local MCP server process. The command is administrator configuration; it runs as the server's own user.</summary>
    public static McpToolProvider Stdio(string id, string command, IReadOnlyList<string> args, IDictionary<string, string?> env, string? cwd) =>
        new(() => new StdioClientTransport(new StdioClientTransportOptions
        {
            Name = id, Command = command, Arguments = [.. args], EnvironmentVariables = env, WorkingDirectory = cwd,
        }));

    private async Task<McpClient> ClientAsync(CancellationToken ct)
    {
        await gate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            return client ??= await McpClient.CreateAsync(transport(), cancellationToken: ct).ConfigureAwait(false);
        }
        finally
        {
            gate.Release();
        }
    }

    private async Task ResetAsync()
    {
        await gate.WaitAsync().ConfigureAwait(false);
        try
        {
            if (client is not null)
                await client.DisposeAsync().ConfigureAwait(false);
            client = null;
        }
        finally
        {
            gate.Release();
        }
    }

    public async Task<IReadOnlyList<ToolSpec>> ListAsync(CancellationToken ct)
    {
        try
        {
            var tools = await (await ClientAsync(ct).ConfigureAwait(false)).ListToolsAsync(cancellationToken: ct).ConfigureAwait(false);
            return [.. tools.Select(t => new ToolSpec(t.Name, t.Description ?? t.Title ?? t.Name,
                JsonNode.Parse(t.ProtocolTool.InputSchema.GetRawText()) as JsonObject ?? new JsonObject { ["type"] = "object" }))];
        }
        catch (Exception e) when (e is not OperationCanceledException)
        {
            await ResetAsync().ConfigureAwait(false);
            throw;
        }
    }

    public async Task<ToolCallOutcome> CallAsync(string tool, JsonObject arguments, CancellationToken ct)
    {
        CallToolResult result;
        try
        {
            var args = arguments.ToDictionary(kv => kv.Key, kv => (object?)(kv.Value is null ? null : JsonSerializer.Deserialize<JsonElement>(kv.Value.ToJsonString())));
            result = await (await ClientAsync(ct).ConfigureAwait(false)).CallToolAsync(tool, args, cancellationToken: ct).ConfigureAwait(false);
        }
        catch (Exception e) when (e is not OperationCanceledException and not McpProtocolException)
        {
            await ResetAsync().ConfigureAwait(false);
            throw;
        }
        var text = string.Join("\n", result.Content.Select(c => c switch
        {
            TextContentBlock t => t.Text,
            ImageContentBlock => "[image]",
            _ => $"[{c.Type}]",
        }));
        if (text.Length == 0 && result.StructuredContent is { } structured)
            text = structured.ToString();
        return new ToolCallOutcome(text, result.IsError == true);
    }

    public async ValueTask DisposeAsync()
    {
        await ResetAsync().ConfigureAwait(false);
        gate.Dispose();
    }
}
