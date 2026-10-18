using Aijade.Client.Api;
using Aijade.Integrations;

using Discord;
using Discord.WebSocket;

using Microsoft.Extensions.Logging;

namespace Aijade.Bots;

/// <summary>Discord (gateway): DMs are always answered; server channels when the bot is mentioned or replied to.</summary>
public sealed class DiscordConnector(string token, AijadeApi api, ILogger<DiscordConnector> log) : IChannelConnector
{
    public const int MaxText = 2000;

    public string Platform => "discord";

    /// <summary>The fields of a Discord message that matter, as a channel message (null for bots and empty text).</summary>
    public static ChannelMessage? ToChannelMessage(string content, ulong authorId, string authorName, bool authorIsBot, bool isDm, ulong channelId,
        IReadOnlyCollection<ulong> mentionedUserIds, ulong? repliedToAuthorId, ulong botId)
    {
        if (authorIsBot || authorId == botId)
            return null;
        var clean = content.Replace($"<@{botId}>", "", StringComparison.Ordinal).Replace($"<@!{botId}>", "", StringComparison.Ordinal).Trim();
        if (clean.Length == 0)
            return null;
        return new ChannelMessage("discord", channelId.ToString(System.Globalization.CultureInfo.InvariantCulture), authorId.ToString(System.Globalization.CultureInfo.InvariantCulture),
            authorName, clean, isDm, mentionedUserIds.Contains(botId) || repliedToAuthorId == botId);
    }

    public async Task RunAsync(Func<ChannelMessage, CancellationToken, Task<ChannelReply?>> handle, CancellationToken ct)
    {
        await using var client = new DiscordSocketClient(new DiscordSocketConfig
        {
            GatewayIntents = GatewayIntents.Guilds | GatewayIntents.GuildMessages | GatewayIntents.DirectMessages | GatewayIntents.MessageContent,
        });
        client.Log += m =>
        {
            log.LogInformation("Discord: {Message}", m.ToString());
            return Task.CompletedTask;
        };
        client.MessageReceived += message =>
        {
            // Answer off the gateway thread so a slow model never stalls the connection.
            _ = Task.Run(async () =>
            {
                try
                {
                    var replied = message.Reference?.MessageId is { IsSpecified: true } && message is SocketUserMessage { ReferencedMessage: { } r } ? r.Author.Id : (ulong?)null;
                    if (ToChannelMessage(message.Content, message.Author.Id, (message.Author as SocketGuildUser)?.DisplayName ?? message.Author.GlobalName ?? message.Author.Username,
                            message.Author.IsBot, message.Channel is IDMChannel, message.Channel.Id, message.MentionedUsers.Select(u => u.Id).ToList(), replied, client.CurrentUser.Id)
                        is not { } incoming)
                        return;
                    using var typing = message.Channel.EnterTypingState();
                    if (await handle(incoming, ct).ConfigureAwait(false) is not { } reply)
                        return;
                    var reference = new MessageReference(message.Id);
                    if (reply.Image is { } image)
                    {
                        var (bytes, _) = await api.ImageBytesAsync(image.Id, ct).ConfigureAwait(false);
                        using var stream = new MemoryStream(bytes);
                        await message.Channel.SendFileAsync(stream, "aijade.png", messageReference: reference).ConfigureAwait(false);
                    }
                    foreach (var part in ChannelText.Split(reply.Text, MaxText))
                        await message.Channel.SendMessageAsync(part, messageReference: reference, allowedMentions: AllowedMentions.None).ConfigureAwait(false);
                }
                catch (Exception e) when (e is not OperationCanceledException)
                {
                    log.LogWarning(e, "Discord reply failed");
                }
            }, ct);
            return Task.CompletedTask;
        };
        await client.LoginAsync(TokenType.Bot, token).ConfigureAwait(false);
        await client.StartAsync().ConfigureAwait(false);
        try
        {
            await Task.Delay(Timeout.Infinite, ct).ConfigureAwait(false);
        }
        catch (OperationCanceledException)
        {
        }
        await client.StopAsync().ConfigureAwait(false);
    }
}
