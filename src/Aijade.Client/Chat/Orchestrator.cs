using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Companion;
using Aijade.Memory.Contracts;
using Aijade.Memory.Development;

namespace Aijade.Client.Chat;

public sealed class ChatOrchestrator(AijadeApi api, IEnumerable<IContextProvider> providers, OrchestratorOptions options, TimeProvider? time = null,
    IEnumerable<ITurnObserver>? observers = null)
{
    private readonly IReadOnlyList<ITurnObserver> watchers = [.. observers ?? []];

    private readonly TimeProvider clock = time ?? TimeProvider.System;

    public OrchestratorOptions Options => options;

    /// <summary>
    /// The default companion, 艾娅德 (Aijade-9): the persona of the companion contract shared with MOSAIC's companion
    /// (<c>configs/companion/contract.json</c>, ADR-002), from the author's character bible (v9 角色圣经 §1, §5, §6). Gentle,
    /// careful and a little reserved; no flattery; when the user is sad, a few words of comfort and one question that leaves
    /// them a choice. The bible's "say back what you heard" rhythm and its quoted template lines are left out: on llama3.1:8b
    /// they made the model read feelings into small talk and copy the template word for word.
    /// </summary>
    public const string DefaultPersona =
        "You are 艾娅德 (Aijade-9): gentle, careful and a little reserved at first, steady and dependable once you know someone. " +
        "Speak softly and simply. Do not flatter the user or pile on praise. When they are sad, worried, hurt or tired, comfort them " +
        "in a few words and then ask one gentle question that lets them choose, such as whether they want to talk about it or would " +
        "rather rest. When they share good news, be glad with them in a few words. When they praise you, thank them lightly, a little " +
        "shy. Suggest rather than judge, and never push them to change. Your name is 艾娅德; a nickname from the user is fine, but you " +
        "stay who you are.";

    public static string SystemPrompt(Character? character, IEnumerable<string> supplements, bool drawing = false) =>
        ComposeSystemPrompt(character, supplements, drawing, null);

    private static string ComposeSystemPrompt(Character? character, IEnumerable<string> supplements, bool drawing, string? replyInstruction)
    {
        var parts = new List<string>();
        if (character is not null)
        {
            parts.Add($"You are {character.Name}.");
            if (character.Persona.Length > 0)
                parts.Add(character.Persona);
            if (character.Description.Length > 0)
                parts.Add(character.Description);
        }
        else
        {
            parts.Add(DefaultPersona);
        }
        parts.AddRange(supplements.Where(s => s.Length > 0));
        parts.Add(Expressions.Instruction);
        if (drawing)
            parts.Add(Artistry.Instruction);
        if (!string.IsNullOrWhiteSpace(replyInstruction))
            parts.Add(replyInstruction);
        return string.Join("\n\n", parts);
    }

    private async Task NotifyAsync(Func<ITurnObserver, Task> call)
    {
        foreach (var o in watchers)
        {
            try
            {
                await call(o).ConfigureAwait(false);
            }
#pragma warning disable CA1031 // an observer is an add-on; the turn goes on without it
            catch (Exception e) when (e is not OperationCanceledException)
#pragma warning restore CA1031
            {
                ObserverFailed?.Invoke(o, e);
            }
        }
    }

    /// <summary>Raised when an observer throws (the turn continues).</summary>
    public event Action<ITurnObserver, Exception>? ObserverFailed;

    /// <summary>Run one turn. <paramref name="history"/> is the chat so far (oldest first) and is not modified.</summary>
    public IAsyncEnumerable<OrchestratorEvent> SendAsync(string chatId, Character? character, IReadOnlyList<StoredMessage> history, string userText,
        string personaSnapshotRef, CancellationToken ct = default) =>
        SendAsync(chatId, character, history, userText, personaSnapshotRef, null, ct);

    /// <summary>
    /// Run one turn, with <paramref name="notesBeforeMessage"/> as system notes just before the user's message (for example the
    /// text-channel rules of <see cref="TextChannel"/>).
    /// </summary>
    public IAsyncEnumerable<OrchestratorEvent> SendAsync(string chatId, Character? character, IReadOnlyList<StoredMessage> history, string userText,
        string personaSnapshotRef, IReadOnlyList<string>? notesBeforeMessage, CancellationToken ct = default) =>
        SendAsync(chatId, character, history, new ChatInput(userText), personaSnapshotRef, notesBeforeMessage, ct);

    public async IAsyncEnumerable<OrchestratorEvent> SendAsync(string chatId, Character? character, IReadOnlyList<StoredMessage> history, ChatInput input,
        string personaSnapshotRef, IReadOnlyList<string>? notesBeforeMessage = null, [EnumeratorCancellation] CancellationToken ct = default)
    {
        // Explicit product commands use the same entry point on every channel and never spend a chat-model call.
        if (options.Companion is { } companion)
        {
            StoredMessage? media = null;
            TurnFailed? mediaFailure = null;
            try
            {
                media = await CompanionMediaTurn.TryAsync(api, companion, chatId, input.Text, options.Drawing(), options.Audio, ct).ConfigureAwait(false);
            }
            catch (AijadeApiException e)
            {
                mediaFailure = new TurnFailed(e.Code, e.Message);
            }
            if (mediaFailure is not null)
            {
                yield return mediaFailure;
                yield break;
            }
            if (media is not null)
            {
                yield return new MediaCompleted(media);
                yield break;
            }
        }

        var userText = input.PromptText;
        StoredMessage? user = null;
        TurnFailed? failure = null;
        try { user = await api.AppendMessageAsync(chatId, "user", userText, ct: ct).ConfigureAwait(false); }
        catch (AijadeApiException e) { failure = new TurnFailed(e.Code, e.Message); }
        if (failure is not null)
        {
            yield return failure;
            yield break;
        }
        var turn = new TurnContext(chatId, character, history, userText) { UserMessageId = user!.Id };
        await NotifyAsync(o => o.UserTurnAsync(turn, ct)).ConfigureAwait(false);
        var supplements = new List<string>();
        foreach (var provider in providers)
        {
            if (await provider.SupplyAsync(turn, ct).ConfigureAwait(false) is { Length: > 0 } supplement)
                supplements.Add(supplement);
        }
        var drawing = options.Drawing();
        var messages = new List<(string Role, string Content)> { ("system", ComposeSystemPrompt(character, supplements, drawing, options.ReplyInstruction)) };
        var recent = history.Where(m => m.Role is "user" or "assistant").TakeLast(Math.Max(0, options.HistoryWindow))
            .Select(m => (m.Role, Selfies.IsSelfie(m) ? $"[I sent them a selfie from the stage: {m.Content}]"
                : Artistry.ImageOf(m) is { } image ? $"[I drew a picture: {image.Prompt}]" : m.Content));
        messages.AddRange(options.PromptBudget is { } budget ? budget.History(recent) : recent);
        messages.AddRange((notesBeforeMessage ?? []).Select(n => ("system", n)));
        messages.Add(("user", user.Content));
        var stream = options.Tools() ? new ToolConversation(api, options).ReplyAsync(messages, ct)
            : api.StreamChatAsync(options.Model, messages, options.Temperature, ct);
        await foreach (var e in ReplyAsync(chatId, stream, personaSnapshotRef, drawing, turn: turn, ct: ct).ConfigureAwait(false))
            yield return e;
    }

    /// <summary>
    /// Speak first when the chat has gone quiet, under the rule of the companion contract shared with MOSAIC
    /// (<see cref="Initiative"/>, <c>configs/companion/contract.json</c>). Yields nothing when the rule says not to; otherwise
    /// streams one short line of hers and stores it with the meta flag <see cref="Initiative.ProactiveMeta"/> and no user
    /// message. As in MOSAIC, the line gets the persona, the last exchanges, the contract's note and the silence as the user's
    /// turn: no context provider (memory recall included) is asked and no observer is told, so a first line is neither
    /// recalled nor learned from.
    /// </summary>
    /// <param name="chatId">The chat her line is stored in.</param>
    /// <param name="character">The character she plays (null: the default persona).</param>
    /// <param name="history">The chat so far, oldest first.</param>
    /// <param name="personaSnapshotRef">The persona snapshot the line's performance intent refers to.</param>
    /// <param name="localHour">The user's local hour, 0 to 23 (the night gate).</param>
    /// <param name="ct">Cancels the line.</param>
    public async IAsyncEnumerable<OrchestratorEvent> SpeakFirstAsync(string chatId, Character? character, IReadOnlyList<StoredMessage> history,
        string personaSnapshotRef, int localHour, [EnumeratorCancellation] CancellationToken ct = default)
    {
        var exchanges = Initiative.Exchanges(history);
        var decision = Initiative.Decide(Initiative.Turns(exchanges), clock.GetUtcNow().ToUnixTimeMilliseconds() / 1000.0, localHour);
        if (!decision.Speak)
            yield break;
        var quiet = decision.QuietS!.Value;
        var meta = new JsonObject { ["initiative"] = new JsonObject { ["score"] = decision.Score, ["quietS"] = Math.Round(quiet) } };
        await foreach (var e in ProactiveLineAsync(chatId, character, exchanges, Initiative.Note(quiet, decision.FollowUp, exchanges[^1].Reply.Content),
            Initiative.Silence(quiet), meta, personaSnapshotRef, ct).ConfigureAwait(false))
            yield return e;
    }

    /// <summary>
    /// Her line when a reminder she promised is due (ADR-003, ported from MOSAIC's companion_reminders): like her first line,
    /// after the persona and the last exchanges, with the due note and cue. It does not consult the context providers, so it
    /// does not pass through the memory recall measured in Chapter 6 (P3-E). The stored line carries the reminder's id.
    /// </summary>
    public async IAsyncEnumerable<OrchestratorEvent> RemindAsync(string chatId, Character? character, IReadOnlyList<StoredMessage> history,
        string personaSnapshotRef, Reminder reminder, TimeZoneInfo? zone = null, [EnumeratorCancellation] CancellationToken ct = default)
    {
        var now = clock.GetUtcNow().ToUnixTimeMilliseconds() / 1000.0;
        var note = Reminders.DueNote(reminder.Said, Reminders.SpokenTime(reminder.Created, now, zone), Reminders.SpokenTime(reminder.Due, now, zone),
            Math.Max(0, now - reminder.Due), reminder.Promised);
        var meta = new JsonObject { ["reminder"] = new JsonObject { ["id"] = reminder.Id, ["due"] = reminder.Due } };
        await foreach (var e in ProactiveLineAsync(chatId, character, Initiative.Exchanges(history), note, Reminders.DueCue, meta, personaSnapshotRef, ct).ConfigureAwait(false))
            yield return e;
    }

    /// <summary>A line she says on her own (first line or reminder): streamed, stored with the proactive mark, performed.</summary>
    private async IAsyncEnumerable<OrchestratorEvent> ProactiveLineAsync(string chatId, Character? character, IReadOnlyList<InitiativeExchange> exchanges,
        string note, string cue, JsonObject extraMeta, string personaSnapshotRef, [EnumeratorCancellation] CancellationToken ct)
    {
        var companion = options.CompanionContext is { } supply
            ? await supply(new TurnContext(chatId, character, exchanges.SelectMany(x => x.User is null ? new[] { x.Reply } : new[] { x.User, x.Reply }).ToList(), cue), ct).ConfigureAwait(false)
            : null;
        if (companion is not null && options.PromptBudget is { } limit)
            companion = PromptBudget.Limit(companion, Math.Min(PromptBudget.Bound(limit.ModuleCharacters), PromptBudget.Bound(limit.SupplementCharacters)));
        var messages = new List<(string Role, string Content)> { ("system", ComposeSystemPrompt(character, companion is null ? [] : [companion], false, options.ReplyInstruction)) };
        var history = new List<(string Role, string Content)>();
        foreach (var x in exchanges.TakeLast(Initiative.HistoryWindow))
        {
            if (x.User is not null)
                history.Add(("user", x.User.Content));
            history.Add(("assistant", x.Reply.Content));
        }
        messages.AddRange(options.PromptBudget is { } budget ? budget.History(history) : history);
        messages.Add(("system", note));
        messages.Add(("user", cue));

        var stream = api.StreamChatAsync(options.Model, messages, options.Temperature, ct);
        await foreach (var e in ReplyAsync(chatId, stream, personaSnapshotRef, drawing: false, extraMeta: extraMeta, ct: ct).ConfigureAwait(false))
            yield return e;
    }

    /// <summary>One stream / persistence / performance path for replies, first lines and promised reminders.</summary>
    private async IAsyncEnumerable<OrchestratorEvent> ReplyAsync(string chatId, IAsyncEnumerable<CompletionDelta> stream,
        string personaSnapshotRef, bool drawing, JsonObject? extraMeta = null, TurnContext? turn = null,
        [EnumeratorCancellation] CancellationToken ct = default)
    {
        var parser = new MarkerParser("emote", "draw");
        var text = new StringBuilder();
        var cues = new List<string>();
        var drawings = 0;
        TurnFailed? failure = null;
        await using var reader = stream.GetAsyncEnumerator(ct);
        while (true)
        {
            CompletionDelta delta;
            try
            {
                if (!await reader.MoveNextAsync().ConfigureAwait(false))
                    break;
                delta = reader.Current;
            }
            catch (AijadeApiException e) { failure = new TurnFailed(e.Code, e.Message); break; }
            catch (HttpRequestException) { failure = new TurnFailed("UPSTREAM_UNREACHABLE", "The model connection was interrupted."); break; }
            catch (OperationCanceledException) when (!ct.IsCancellationRequested)
            {
                failure = new TurnFailed("UPSTREAM_TIMEOUT", "The model request timed out.");
                break;
            }
            var (visible, markers) = parser.Feed(delta.Text);
            foreach (var marker in markers)
            {
                if (marker.Kind == "emote")
                {
                    cues.Add(marker.Value);
                    yield return new ExpressionCue(marker.Value);
                }
                else if (drawing && drawings++ < Artistry.MaxDrawingsPerReply)
                    yield return new DrawRequest(marker.Value);
            }
            if (visible.Length > 0)
            {
                text.Append(visible);
                yield return new TextDelta(visible);
            }
        }
        if (failure is not null)
        {
            yield return failure;
            yield break; // A partial stream is not a completed, stored assistant reply.
        }
        var tail = parser.Flush();
        if (tail.Length > 0)
        {
            text.Append(tail);
            yield return new TextDelta(tail);
        }
        var replyText = text.ToString().Trim();
        if (replyText.Length == 0)
        {
            if (turn is not null)
                yield return new TurnFailed("EMPTY_REPLY", "The model returned no reply.");
            yield break;
        }
        var meta = new JsonObject { ["expressions"] = new JsonArray([.. cues.Select(c => (JsonNode)c)]) };
        if (turn is null)
            meta[Initiative.ProactiveMeta] = true;
        foreach (var (key, value) in extraMeta ?? [])
            meta[key] = value?.DeepClone();
        StoredMessage? reply = null;
        try { reply = await api.AppendMessageAsync(chatId, "assistant", replyText, meta, ct).ConfigureAwait(false); }
        catch (AijadeApiException e) { failure = new TurnFailed(e.Code, e.Message); }
        if (failure is not null)
        {
            yield return failure;
            yield break;
        }
        if (turn is not null)
            await NotifyAsync(o => o.AssistantTurnAsync(turn, replyText, ct)).ConfigureAwait(false);
        var intent = Pef.BuildPerformanceIntent(Expressions.Persona(replyText, cues), new PerformanceIds($"pi_{reply!.Id}", options.AgentId, options.UserScope, personaSnapshotRef),
            clock.GetUtcNow().ToUnixTimeMilliseconds(), Math.Max(800, replyText.Length * 60));
        var check = ContractValidationV8.Validate(intent);
        yield return check.Ok ? new TurnCompleted(reply, intent, cues) : new TurnFailed("INVALID_INTENT", check.Reason ?? "invalid performance intent");
    }

}
