using System.Net;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Server.Mcp;
using Aijade.Server.Product;

using Microsoft.AspNetCore.Hosting.Server;
using Microsoft.AspNetCore.TestHost;
using Microsoft.Extensions.DependencyInjection;

using ModelContextProtocol.Client;
using ModelContextProtocol.Protocol;

namespace Aijade.Tests;

public class McpServerTests
{
    private sealed class Llm : HttpMessageHandler
    {
        public string? LastBody { get; private set; }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            LastBody = await request.Content!.ReadAsStringAsync(cancellationToken);
            const string sse = "data: {\"choices\":[{\"delta\":{\"content\":\"[[emote:calm]]Of course, I am here.\"}}]}\n\ndata: [DONE]\n\n";
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(sse, Encoding.UTF8, "text/event-stream") };
        }
    }

    private static string Text(CallToolResult r) => string.Concat(r.Content.OfType<TextContentBlock>().Select(c => c.Text));

    [Fact]
    public async Task Mcp_clients_can_talk_with_the_companion_and_use_the_callers_memory()
    {
        var ct = TestContext.Current.CancellationToken;
        var llm = new Llm();
        await using var host = await ServerTestHost.StartAsync(worker: false, services: s =>
        {
            s.AddHttpClient(GatewayEndpoints.HttpClientName).ConfigurePrimaryHttpMessageHandler(() => llm);
            // The tools call this server's own API; in tests that is the in-memory test server.
            s.AddHttpClient(McpEndpoints.SelfClient, c => c.BaseAddress = new Uri("http://localhost/"))
                .ConfigurePrimaryHttpMessageHandler(sp => ((TestServer)sp.GetRequiredService<IServer>()).CreateHandler());
        });
        await host.SendAsync(HttpMethod.Put, "/api/v1/admin/gateway/routes", new JsonObject
        {
            ["models"] = new JsonObject { ["aijade-chat"] = new JsonObject { ["upstream"] = "https://llm.example/v1", ["model"] = "m", ["keys"] = new JsonArray("k") } },
        }, ServerTestHost.AdminToken);

        async Task<McpClient> Connect(string? token)
        {
            var http = new HttpClient(host.App.GetTestServer().CreateHandler()) { BaseAddress = host.Client.BaseAddress };
            var options = new HttpClientTransportOptions { Endpoint = new Uri(host.Client.BaseAddress!, "mcp") };
            if (token is not null)
                options.AdditionalHeaders = new Dictionary<string, string> { ["Authorization"] = $"Bearer {token}" };
            return await McpClient.CreateAsync(new HttpClientTransport(options, http, ownsHttpClient: true), cancellationToken: ct);
        }

        await Assert.ThrowsAnyAsync<Exception>(() => Connect(null)); // no token, no MCP

        await using var client = await Connect(ServerTestHost.Token);
        var tools = await client.ListToolsAsync(cancellationToken: ct);
        Assert.Equal(["companion_chat", "memory_remember", "memory_search"], tools.Select(t => t.Name).Order(StringComparer.Ordinal));

        var said = await client.CallToolAsync("companion_chat", new Dictionary<string, object?> { ["message"] = "Are you there?" }, cancellationToken: ct);
        Assert.Equal("Of course, I am here.", Text(said));
        Assert.StartsWith("You are 艾娅德", JsonNode.Parse(llm.LastBody!)!["messages"]![0]!["content"]!.GetValue<string>(), StringComparison.Ordinal);
        var mcpChat = Assert.Single(await host.SendAsync(HttpMethod.Get, "/api/v1/chats") is var (_, body) ? body!["chats"]!.AsArray() : []);
        Assert.Equal(AijadeMcpTools.ChatTitle, mcpChat!["title"]!.GetValue<string>());
        await client.CallToolAsync("companion_chat", new Dictionary<string, object?> { ["message"] = "Still there?" }, cancellationToken: ct);
        Assert.Single((await host.SendAsync(HttpMethod.Get, "/api/v1/chats")).Body!["chats"]!.AsArray()); // same chat continues

        Assert.Equal("Passed to memory.", Text(await client.CallToolAsync("memory_remember", new Dictionary<string, object?> { ["text"] = "I keep bees on my balcony." }, cancellationToken: ct)));
        Assert.Contains("I keep bees on my balcony.", Text(await client.CallToolAsync("memory_search", new Dictionary<string, object?> { ["query"] = "bees" }, cancellationToken: ct)), StringComparison.Ordinal);
        // Another account sees none of it.
        await using var admin = await Connect(ServerTestHost.AdminToken);
        Assert.Equal("No memory matches.", Text(await admin.CallToolAsync("memory_search", new Dictionary<string, object?> { ["query"] = "bees" }, cancellationToken: ct)));
    }
}
