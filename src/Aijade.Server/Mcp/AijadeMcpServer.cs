using System.ComponentModel;
using System.Text;

using Aijade.Client.Api;
using Aijade.Client.Chat;

using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;
using Microsoft.Extensions.Configuration;
using Microsoft.Extensions.DependencyInjection;

using ModelContextProtocol.Server;

namespace Aijade.Server.Mcp;

// AIJADE as a Model Context Protocol server, at /mcp (Streamable HTTP, stateless). Any MCP client — Claude Code (see
// integrations/claude-code), an IDE extension, another agent — can talk with the companion and use the caller's
// long-term memory. Every tool acts as the calling account: the tools call this server's own HTTP API with the caller's
// bearer token, so the same authorization, billing and memory ownership apply as in the apps.

public static class McpEndpoints
{
    public const string SelfClient = "aijade-self";

    public static void AddAijadeMcp(this IServiceCollection services)
    {
        services.AddHttpContextAccessor();
        services.AddHttpClient(SelfClient, c => c.Timeout = TimeSpan.FromMinutes(5));
        services.AddMcpServer(o => o.ServerInfo = new() { Name = "aijade", Version = "0.1.0" })
            .WithHttpTransport(o => o.Stateless = true)
            .WithTools<AijadeMcpTools>();
    }

    public static void MapAijadeMcp(this WebApplication app) => app.MapMcp("/mcp").RequireAuthorization();
}

[McpServerToolType]
public sealed class AijadeMcpTools(IHttpContextAccessor http, IHttpClientFactory factory, IConfiguration config)
{
    /// <summary>The chat MCP conversations continue in, per account, unless a chat id is given.</summary>
    public const string ChatTitle = "MCP";

    private AijadeApi Api()
    {
        var context = http.HttpContext ?? throw new InvalidOperationException("no request");
        var client = factory.CreateClient(McpEndpoints.SelfClient);
        client.BaseAddress ??= config["Aijade:SelfUrl"] is { Length: > 0 } self ? new Uri(self) : new Uri($"{context.Request.Scheme}://{context.Request.Host}/");
        var tokens = new MemoryTokenStore();
        var header = context.Request.Headers.Authorization.ToString();
        tokens.SetAsync(header.StartsWith("Bearer ", StringComparison.OrdinalIgnoreCase) ? header[7..].Trim() : null).AsTask().GetAwaiter().GetResult();
        return new AijadeApi(client, tokens);
    }

    [McpServerTool(Name = "companion_chat"), Description(
        "Talk with the AIJADE companion (艾娅德 / Aijade-9, or the character the chat was created with). " +
        "Returns the companion's reply. Conversations continue in the account's \"MCP\" chat unless chatId names another chat.")]
    public async Task<string> CompanionChatAsync(
        [Description("What to say to the companion.")] string message,
        [Description("Optional id of an existing chat to continue.")] string? chatId = null,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(message))
            return "Nothing to say: the message is empty.";
        var api = Api();
        var chats = await api.ChatsAsync(cancellationToken).ConfigureAwait(false);
        var chat = chatId is { Length: > 0 }
            ? chats.FirstOrDefault(c => c.Id == chatId) ?? throw new ArgumentException($"no chat '{chatId}' in this account", nameof(chatId))
            : chats.FirstOrDefault(c => c.Title == ChatTitle) ?? await api.CreateChatAsync(null, ChatTitle, cancellationToken).ConfigureAwait(false);
        var character = chat.CharacterId is { } cid ? (await api.CharactersAsync(cancellationToken).ConfigureAwait(false)).FirstOrDefault(c => c.Id == cid) : null;
        var history = await api.MessagesAsync(chat.Id, ct: cancellationToken).ConfigureAwait(false);
        var orchestrator = new ChatOrchestrator(api, [new MemoryRecallProvider(api, () => true)], new OrchestratorOptions());
        await foreach (var e in orchestrator.SendAsync(chat.Id, character, history, message.Trim(), $"persona:{character?.Id ?? "default"}", cancellationToken).ConfigureAwait(false))
        {
            switch (e)
            {
                case TurnCompleted done:
                    return done.Reply.Content;
                case TurnFailed failed:
                    return $"The companion could not answer ({failed.Code}): {failed.Message}";
            }
        }
        return "The companion did not answer.";
    }

    [McpServerTool(Name = "memory_search", ReadOnly = true), Description("Search the account's long-term memory (what the user has told the companion). Returns matching items, newest first.")]
    public async Task<string> MemorySearchAsync(
        [Description("Words to look for; empty lists the most recent items.")] string query = "",
        [Description("At most this many items (1-50).")] int limit = 10,
        CancellationToken cancellationToken = default)
    {
        var items = await Api().MemoryItemsAsync(query, Math.Clamp(limit, 1, 50), ct: cancellationToken).ConfigureAwait(false);
        if (items.Count == 0)
            return "No memory matches.";
        var text = new StringBuilder();
        foreach (var item in items)
            text.Append(System.Globalization.CultureInfo.InvariantCulture, $"- [{item.CreatedAt:yyyy-MM-dd}] {item.Content}\n");
        return text.ToString();
    }

    [McpServerTool(Name = "memory_remember"), Description(
        "Tell the companion something to remember about the user. It goes through the same gated perception pipeline as chat, " +
        "so it is kept only if it passes the memory gates.")]
    public async Task<string> MemoryRememberAsync(
        [Description("The fact, in the user's words.")] string text,
        CancellationToken cancellationToken = default)
    {
        if (string.IsNullOrWhiteSpace(text))
            return "Nothing to remember: the text is empty.";
        var api = Api();
        var account = await api.SessionAsync(cancellationToken).ConfigureAwait(false) ?? throw new InvalidOperationException("not signed in");
        await new ConversationRecorder(api, $"mcp:{account.Id}", "mcp").RecordAsync(text.Trim(), cancellationToken).ConfigureAwait(false);
        return "Passed to memory.";
    }
}
