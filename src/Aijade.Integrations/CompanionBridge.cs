using System.Collections.Concurrent;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Chat;
using Aijade.Client.Companion;
using Aijade.Memory.Contracts;

namespace Aijade.Integrations;

/// <summary>A message seen on an external channel.</summary>
/// <param name="Platform">"discord", "telegram", "satori", "x", "bilibili" …</param>
/// <param name="ConversationId">The platform's id for the room / chat / thread the reply goes back to.</param>
/// <param name="AuthorId">The platform's id for the person (memory is kept per person).</param>
/// <param name="AuthorName">How the person is shown to the model in group rooms.</param>
/// <param name="Text">The message, with the bot's own mention removed.</param>
/// <param name="IsDirect">A private message to the bot (always answered).</param>
/// <param name="AddressesBot">The bot was mentioned or replied to (answered in group rooms).</param>
public sealed record ChannelMessage(string Platform, string ConversationId, string AuthorId, string AuthorName, string Text, bool IsDirect, bool AddressesBot)
{
    /// <summary>One AIJADE chat per platform conversation.</summary>
    public string Key => $"{Platform}:{ConversationId}";
}

/// <summary>What the companion says back: text, and optionally one picture it drew.</summary>
public sealed record ChannelReply(string Text, IReadOnlyList<string> Expressions, ImageInfo? Image = null);

public sealed class BridgeOptions
{
    /// <summary>Name(s) that address the companion in group rooms besides a mention (e.g. "艾娅德", "Aijade").</summary>
    public IReadOnlyList<string> Names { get; init; } = ["艾娅德", "Aijade"];

    /// <summary>At most one reply per conversation within this time (flood protection for busy rooms).</summary>
    public TimeSpan MinInterval { get; init; } = TimeSpan.FromSeconds(3);

    /// <summary>The character the companion plays on external channels (null = the default Aijade-9 persona).</summary>
    public string? CharacterId { get; init; }

    /// <summary>Recall and record long-term memory, per person (see <see cref="CompanionBridge.MemorySession"/>).</summary>
    public bool Memory { get; init; } = true;

    /// <summary>
    /// Let the companion use the server's tools here. Off by default: anyone in a public room could otherwise have it
    /// switch the owner's lights; the bot account must also be allowed tools on the server.
    /// </summary>
    public bool Tools { get; init; }

    /// <summary>
    /// On channels where she has no body (Discord, Telegram, X, platforms relayed by Satori), apply the companion contract's
    /// text-channel rules (<see cref="TextChannel"/>): she is told she cannot move there, and a reply that would promise a
    /// movement is put off until the user is at the screen.
    /// </summary>
    public bool TextChannelRules { get; init; } = true;

    /// <summary>Let the companion draw on channels that can show images (needs the server's image route).</summary>
    public bool Drawing { get; init; }

    /// <summary>Where the conversation → chat mapping is kept between restarts (null = memory only).</summary>
    public string? StateFile { get; init; }

    /// <summary>
    /// The platforms whose connector can start a message (<see cref="IProactiveConnector"/>). In private conversations there
    /// she keeps reminders, as MOSAIC's QQ bridge does (ADR-003): set and cancelled by fixed words, said when due. Elsewhere
    /// she could not keep the promise, so none is set. They are kept beside the state file (StateFile + ".reminders.json").
    /// </summary>
    public IReadOnlyCollection<string> ReminderPlatforms { get; init; } = [];

    /// <summary>The time zone clock words such as "明天早上八点" are read in (null = this machine's).</summary>
    public TimeZoneInfo? TimeZone { get; init; }

    public OrchestratorOptions Orchestrator { get; init; } = new();

    /// <summary>Called with each completed turn's PerformanceIntent (e.g. to drive an external renderer); errors are logged by the caller's sink, never thrown into the chat.</summary>
    public Func<PerformanceIntent, ChannelMessage, Task>? OnPerformance { get; init; }

    public TimeProvider Time { get; init; } = TimeProvider.System;
}

/// <summary>
/// Answers channel messages as the companion: decides whether a message is for it, keeps one AIJADE chat per platform
/// conversation (so history and memory carry over), runs the shared chat orchestrator through the server API, and
/// returns the reply for the connector to post. Rooms are rate-limited; one conversation is answered at a time.
/// </summary>
public sealed class CompanionBridge(AijadeApi api, BridgeOptions? options = null, IEnumerable<IContextProvider>? context = null, IEnumerable<ITurnObserver>? observers = null)
    : IDisposable
{
    private readonly BridgeOptions options = Configure(options ?? new BridgeOptions());

    private static BridgeOptions Configure(BridgeOptions o)
    {
        o.Orchestrator.Drawing = () => o.Drawing;
        o.Orchestrator.Tools = () => o.Tools;
        return o;
    }

    /// <summary>The memory session of one person on one platform: recall and recording never cross people.</summary>
    public static string MemorySession(ChannelMessage m) => $"bot:{m.Platform}:{m.AuthorId}";
    private readonly ConcurrentDictionary<string, SemaphoreSlim> locks = new(StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, DateTimeOffset> lastReply = new(StringComparer.Ordinal);
    private readonly SemaphoreSlim stateGate = new(1, 1);
    private Dictionary<string, string>? chats;
    private ReminderBook? reminders;
    private Character? character;
    private bool characterLoaded;

    /// <summary>Whether this message is for the companion: private messages, mentions, or its name in the text.</summary>
    public bool ShouldAnswer(ChannelMessage m) =>
        m.Text.Trim().Length > 0 && (m.IsDirect || m.AddressesBot || options.Names.Any(n => m.Text.Contains(n, StringComparison.OrdinalIgnoreCase)));

    /// <summary>Answer the message, or null when it is not for the companion, is rate-limited, or the turn failed.</summary>
    public async Task<ChannelReply?> AnswerAsync(ChannelMessage message, CancellationToken ct = default)
    {
        if (!ShouldAnswer(message))
            return null;
        var now = options.Time.GetUtcNow();
        if (!message.IsDirect && lastReply.TryGetValue(message.Key, out var last) && now - last < options.MinInterval)
            return null;
        var gate = locks.GetOrAdd(message.Key, _ => new SemaphoreSlim(1, 1));
        await gate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            lastReply[message.Key] = now;
            var who = await CharacterAsync(ct).ConfigureAwait(false);
            var chatId = await ChatForAsync(message.Key, message.IsDirect ? $"{message.Platform} · {message.AuthorName}" : $"{message.Platform} · {message.ConversationId}", who, ct).ConfigureAwait(false);
            var history = await api.MessagesAsync(chatId, ct: ct).ConfigureAwait(false);
            // Group rooms have many speakers: the model sees who said it.
            var text = message.IsDirect ? message.Text : $"{message.AuthorName}: {message.Text}";
            var session = MemorySession(message);
            IContextProvider[] providers = options.Memory ? [new MemoryRecallProvider(api, () => true, session: session), .. context ?? []] : [.. context ?? []];
            var orchestrator = new ChatOrchestrator(api, providers, options.Orchestrator, options.Time, observers);
            if (options.Memory)
                _ = RecordAsync(session, message.Text);
            TurnCompleted? done = null;
            string? draw = null;
            var bodiless = options.TextChannelRules ? TextChannel.BodilessChannel(message.Platform) : null;
            var (reminderNotes, promised) = message.IsDirect && options.ReminderPlatforms.Contains(message.Platform) ? await ReadRemindersAsync(message, ct).ConfigureAwait(false) : ([], null);
            var notes = (bodiless is null ? [] : TextChannel.Notes(bodiless, message.Text)).Concat(reminderNotes).ToList();
            await foreach (var e in orchestrator.SendAsync(chatId, who, history, text, $"persona:{who?.Id ?? "default"}", notes.Count > 0 ? notes : null, ct).ConfigureAwait(false))
            {
                switch (e)
                {
                    case TurnCompleted c:
                        done = c;
                        break;
                    case DrawRequest d:
                        draw ??= d.Prompt;
                        break;
                    case TurnFailed:
                        return null;
                }
            }
            if (done is null)
                return null;
            if (promised is not null)
                await UpdateRemindersAsync(book => book.Promise(promised.Id, done.Reply.Content), ct).ConfigureAwait(false);
            if (options.OnPerformance is { } perform)
            {
                try
                {
                    await perform(done.Intent, message).ConfigureAwait(false);
                }
                catch (Exception e) when (e is not OperationCanceledException)
                {
                    // the renderer is a display: a failure to reach it never costs the reply
                }
            }
            ImageInfo? image = null;
            if (draw is not null)
            {
                try
                {
                    image = Artistry.ImageOf(await Artistry.DrawIntoChatAsync(api, chatId, draw, ct).ConfigureAwait(false));
                }
                catch (AijadeApiException)
                {
                    // The text reply stands without the picture (image route unconfigured, out of flux …).
                }
            }
            var replyText = bodiless is null ? done.Reply.Content : TextChannel.PutOff(message.Text, done.Reply.Content);
            return new ChannelReply(replyText, done.Expressions, image);
        }
        finally
        {
            gate.Release();
        }
    }

    private double Now() => options.Time.GetUtcNow().ToUnixTimeMilliseconds() / 1000.0;

    private async Task<(IReadOnlyList<string> Notes, Reminder? Set)> ReadRemindersAsync(ChannelMessage message, CancellationToken ct)
    {
        await stateGate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            reminders ??= LoadReminders();
            var read = reminders.Read(message.Key, message.Text, Now(), options.TimeZone);
            if (read.Set is not null || read.Notes.Count > 0)
                SaveReminders();
            return read;
        }
        finally
        {
            stateGate.Release();
        }
    }

    private async Task UpdateRemindersAsync(Action<ReminderBook> change, CancellationToken ct)
    {
        await stateGate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            reminders ??= LoadReminders();
            change(reminders);
            SaveReminders();
        }
        finally
        {
            stateGate.Release();
        }
    }

    /// <summary>
    /// The next reminder due in a conversation the caller can reach (its key, "platform:conversation", passes
    /// <paramref name="reachable"/>), with her line for it, which is stored in that conversation's chat. As in MOSAIC's bridge,
    /// the reminder counts as said once her line is made, and the caller sends it; a line that could not be made releases the
    /// reminder, due again at the next check. Null when none is due or her line could not be made.
    /// </summary>
    public async Task<(Reminder Reminder, string Line)?> DueReminderAsync(Func<string, bool> reachable, CancellationToken ct = default)
    {
        Reminder? due;
        await stateGate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            reminders ??= LoadReminders();
            var before = reminders.All.ToArray();
            due = reminders.ClaimDue(Now(), reachable);
            if (!reminders.All.SequenceEqual(before))
                SaveReminders();
        }
        finally
        {
            stateGate.Release();
        }
        if (due is null)
            return null;
        string? line = null;
        var gate = locks.GetOrAdd(due.Conversation, _ => new SemaphoreSlim(1, 1));
        await gate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            var who = await CharacterAsync(ct).ConfigureAwait(false);
            // A conversation started over since keeps its reminder: her line opens its new chat.
            var split = due.Conversation.IndexOf(':', StringComparison.Ordinal);
            var chatId = await ChatForAsync(due.Conversation, $"{due.Conversation[..split]} · {due.Conversation[(split + 1)..]}", who, ct).ConfigureAwait(false);
            var history = await api.MessagesAsync(chatId, ct: ct).ConfigureAwait(false);
            await foreach (var e in new ChatOrchestrator(api, [], options.Orchestrator, options.Time, observers)
                .RemindAsync(chatId, who, history, $"persona:{who?.Id ?? "default"}", due, options.TimeZone, ct).ConfigureAwait(false))
            {
                if (e is TurnCompleted c)
                    line = c.Reply.Content;
            }
        }
        catch (AijadeApiException e) when (e.Status == 404)
        {
            await ForgetAsync(due.Conversation, ct).ConfigureAwait(false); // its chat was deleted: the next check opens a new one
        }
        catch (Exception e) when (e is AijadeApiException or HttpRequestException || (e is OperationCanceledException && !ct.IsCancellationRequested))
        {
            // the server cannot be reached now, or did not answer in time (an HttpClient timeout): released below
        }
        finally
        {
            gate.Release();
        }
        await UpdateRemindersAsync(book =>
        {
            if (line is null)
                book.Release(due.Id);
            else
                book.Done(due.Id);
        }, ct).ConfigureAwait(false);
        return line is null ? null : (due, line);
    }

    private string? RemindersFile => options.StateFile is { } file ? file + ".reminders.json" : null;

    private static readonly JsonSerializerOptions ReminderJson = new(JsonSerializerDefaults.Web);

    private ReminderBook LoadReminders()
    {
        if (RemindersFile is not { } file || !File.Exists(file))
            return new ReminderBook();
        try
        {
            return new ReminderBook(JsonSerializer.Deserialize<List<Reminder>>(File.ReadAllText(file), ReminderJson) ?? []);
        }
        catch (JsonException)
        {
            return new ReminderBook();
        }
    }

    private void SaveReminders()
    {
        if (RemindersFile is not { } file || reminders is null)
            return;
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(file))!);
        File.WriteAllText(file + ".tmp", JsonSerializer.Serialize(reminders.Kept(Now()), ReminderJson));
        File.Move(file + ".tmp", file, overwrite: true);
    }

    /// <summary>The speaker's own words go through the perception pipeline into their memory session (best effort).</summary>
    private async Task RecordAsync(string session, string text)
    {
        try
        {
            await new ConversationRecorder(api, session, "aijade-bots").RecordAsync(text).ConfigureAwait(false);
        }
        catch (Exception e) when (e is AijadeApiException or HttpRequestException)
        {
            // Memory is an add-on; the reply does not wait for it or fail with it.
        }
    }

    private async Task<Character?> CharacterAsync(CancellationToken ct)
    {
        if (!characterLoaded)
        {
            character = options.CharacterId is { } id ? (await api.CharactersAsync(ct).ConfigureAwait(false)).FirstOrDefault(c => c.Id == id) : null;
            characterLoaded = true;
        }
        return character;
    }

    private async Task<string> ChatForAsync(string key, string title, Character? who, CancellationToken ct)
    {
        await stateGate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            chats ??= Load();
            if (chats.TryGetValue(key, out var id))
                return id;
            var chat = await api.CreateChatAsync(who?.Id, title.Length > 60 ? title[..60] : title, ct).ConfigureAwait(false);
            chats[key] = chat.Id;
            Save();
            return chat.Id;
        }
        finally
        {
            stateGate.Release();
        }
    }

    public void Dispose()
    {
        stateGate.Dispose();
        foreach (var gate in locks.Values)
            gate.Dispose();
    }

    /// <summary>Forget a conversation's chat (e.g. the user asked to start over); the next message opens a new one.</summary>
    public Task ResetAsync(ChannelMessage m, CancellationToken ct = default) => ForgetAsync(m.Key, ct);

    private async Task ForgetAsync(string key, CancellationToken ct)
    {
        await stateGate.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            chats ??= Load();
            if (chats.Remove(key))
                Save();
        }
        finally
        {
            stateGate.Release();
        }
    }

    private Dictionary<string, string> Load()
    {
        if (options.StateFile is not { } file || !File.Exists(file))
            return new(StringComparer.Ordinal);
        try
        {
            return JsonSerializer.Deserialize<Dictionary<string, string>>(File.ReadAllText(file)) is { } d ? new(d, StringComparer.Ordinal) : new(StringComparer.Ordinal);
        }
        catch (JsonException)
        {
            return new(StringComparer.Ordinal);
        }
    }

    private void Save()
    {
        if (options.StateFile is not { } file)
            return;
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(file))!);
        var tmp = file + ".tmp";
        File.WriteAllText(tmp, JsonSerializer.Serialize(chats));
        File.Move(tmp, file, overwrite: true);
    }
}

/// <summary>
/// A connector that can also start a message in a conversation, so that she can say a reminder she promised (ADR-003). The
/// conversation is the one of <see cref="ChannelMessage.ConversationId"/> on this connector's platform.
/// </summary>
public interface IProactiveConnector
{
    string Platform { get; }

    Task SendAsync(string conversationId, string text, CancellationToken ct);
}

/// <summary>A platform connection: it reports incoming messages and posts what the handler answers.</summary>
public interface IChannelConnector
{
    string Platform { get; }

    /// <summary>Run until cancelled; <paramref name="handle"/> answers a message (null = say nothing).</summary>
    Task RunAsync(Func<ChannelMessage, CancellationToken, Task<ChannelReply?>> handle, CancellationToken ct);
}

public static class ChannelText
{
    /// <summary>Split a reply into chunks a platform accepts, preferring paragraph, then sentence, then word breaks.</summary>
    public static IReadOnlyList<string> Split(string text, int max)
    {
        var parts = new List<string>();
        var rest = text.Trim();
        while (rest.Length > max)
        {
            var window = rest[..max];
            var cut = new[] { window.LastIndexOf("\n\n", StringComparison.Ordinal), window.LastIndexOfAny(['。', '！', '？', '.', '!', '?', '\n']), window.LastIndexOf(' ') }
                .FirstOrDefault(i => i >= max / 2, -1);
            var at = cut < 0 ? max : cut + 1;
            parts.Add(rest[..at].Trim());
            rest = rest[at..].Trim();
        }
        if (rest.Length > 0)
            parts.Add(rest);
        return parts;
    }
}
