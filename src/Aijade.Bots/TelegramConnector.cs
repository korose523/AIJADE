using Aijade.Client.Api;
using Aijade.Integrations;

using Microsoft.Extensions.Logging;

using Telegram.Bot;
using Telegram.Bot.Polling;
using Telegram.Bot.Types;
using Telegram.Bot.Types.Enums;

namespace Aijade.Bots;

/// <summary>Telegram (long polling): private chats are always answered; groups when the bot is @mentioned or replied to.</summary>
public sealed class TelegramConnector(string token, AijadeApi api, ILogger<TelegramConnector> log) : IChannelConnector
{
    public const int MaxText = 4096;

    public string Platform => "telegram";

    /// <summary>A Telegram message as a channel message (null for non-text, bots, or the bot itself).</summary>
    public static ChannelMessage? ToChannelMessage(Message m, User me)
    {
        if (m.Text is not { Length: > 0 } text || m.From is not { IsBot: false } from)
            return null;
        var mention = $"@{me.Username}";
        var addresses = (me.Username is { Length: > 0 } && text.Contains(mention, StringComparison.OrdinalIgnoreCase)) || m.ReplyToMessage?.From?.Id == me.Id;
        var clean = me.Username is { Length: > 0 } ? text.Replace(mention, "", StringComparison.OrdinalIgnoreCase).Trim() : text.Trim();
        var name = string.Join(' ', new[] { from.FirstName, from.LastName }.Where(s => !string.IsNullOrWhiteSpace(s)));
        return new ChannelMessage("telegram", m.Chat.Id.ToString(System.Globalization.CultureInfo.InvariantCulture), from.Id.ToString(System.Globalization.CultureInfo.InvariantCulture),
            name.Length > 0 ? name : from.Username ?? "someone", clean, m.Chat.Type == ChatType.Private, addresses);
    }

    public async Task RunAsync(Func<ChannelMessage, CancellationToken, Task<ChannelReply?>> handle, CancellationToken ct)
    {
        var bot = new TelegramBotClient(token);
        var me = await bot.GetMe(ct).ConfigureAwait(false);
        log.LogInformation("Telegram connected as @{Username}", me.Username);
        await bot.ReceiveAsync(async (client, update, token) =>
        {
            if (update.Message is not { } message || ToChannelMessage(message, me) is not { } incoming)
                return;
            await client.SendChatAction(message.Chat.Id, ChatAction.Typing, cancellationToken: token).ConfigureAwait(false);
            if (await handle(incoming, token).ConfigureAwait(false) is not { } reply)
                return;
            var replyTo = new ReplyParameters { MessageId = message.MessageId };
            if (reply.Image is { } image)
            {
                var (bytes, _) = await api.ImageBytesAsync(image.Id, token).ConfigureAwait(false);
                using var stream = new MemoryStream(bytes);
                await client.SendPhoto(message.Chat.Id, InputFile.FromStream(stream, "aijade.png"), caption: image.Prompt.Length > 1000 ? image.Prompt[..1000] : image.Prompt,
                    replyParameters: replyTo, cancellationToken: token).ConfigureAwait(false);
            }
            foreach (var part in ChannelText.Split(reply.Text, MaxText))
                await client.SendMessage(message.Chat.Id, part, replyParameters: replyTo, cancellationToken: token).ConfigureAwait(false);
        }, (_, error, _) =>
        {
            log.LogWarning(error, "Telegram polling error");
            return Task.CompletedTask;
        }, new ReceiverOptions { AllowedUpdates = [UpdateType.Message], DropPendingUpdates = true }, ct).ConfigureAwait(false);
    }
}
