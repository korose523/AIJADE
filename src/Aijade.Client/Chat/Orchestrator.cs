using System.Runtime.CompilerServices;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Core.Js;
using Aijade.Memory.Contracts;
using Aijade.Memory.Development;
using Aijade.Memory.Kernel;

namespace Aijade.Client.Chat;

// The chat orchestrator, designed for this rewrite. One user turn: the message is stored, the prompt is assembled (character
// persona, context supplements from pluggable providers such as learning and memory, recent history, the expression-marker
// instruction), the completion is streamed from the gateway, inline expression markers are lifted out of the text as
// expression events, the reply is stored, and a validated PEF PerformanceIntent is produced for the stage.

/// <summary>Supplies extra system context for a turn (memory recall, learned persona, skills); null when it has nothing.</summary>
public interface IContextProvider
{
    Task<string?> SupplyAsync(TurnContext turn, CancellationToken ct);
}

/// <summary>
/// Sees both sides of every stored turn (learning, telemetry). A failing observer is skipped; it never fails the turn the
/// user is waiting for.
/// </summary>
public interface ITurnObserver
{
    Task UserTurnAsync(TurnContext turn, CancellationToken ct);

    Task AssistantTurnAsync(TurnContext turn, string reply, CancellationToken ct);
}

public sealed record TurnContext(string ChatId, Character? Character, IReadOnlyList<StoredMessage> History, string UserText);

public abstract record OrchestratorEvent;

public sealed record TextDelta(string Text) : OrchestratorEvent;

/// <summary>An expression marker found in the stream, e.g. [[emote:joy]].</summary>
public sealed record ExpressionCue(string Name) : OrchestratorEvent;

/// <summary>The model asked for a picture (only when drawing is enabled); the marker itself is not shown.</summary>
public sealed record DrawRequest(string Prompt) : OrchestratorEvent;

public sealed record TurnCompleted(StoredMessage Reply, PerformanceIntent Intent, IReadOnlyList<string> Expressions) : OrchestratorEvent;

public sealed record TurnFailed(string Code, string Message) : OrchestratorEvent;

public sealed class OrchestratorOptions
{
    public string Model { get; set; } = "aijade-chat";

    public int HistoryWindow { get; set; } = 24;

    public double? Temperature { get; set; }

    public string AgentId { get; set; } = "aijade";

    public string UserScope { get; set; } = "default";

    /// <summary>Whether the model is told it can draw, and draw markers become <see cref="DrawRequest"/>s.</summary>
    public Func<bool> Drawing { get; set; } = () => false;

    /// <summary>Whether the model may call the server's tools (the "MCP tools" module) before it answers.</summary>
    public Func<bool> Tools { get; set; } = () => false;

    /// <summary>Tool-call rounds per turn before the model must answer.</summary>
    public int MaxToolRounds { get; set; } = 4;
}

/// <summary>Lifts [[emote:name]] markers out of streamed text, including markers split across chunks.</summary>
/// <summary>An inline instruction from the model, e.g. [[emote:joy]] or [[draw: a cat on a windowsill]].</summary>
public sealed record Marker(string Kind, string Value);

/// <summary>
/// Lifts [[kind:value]] markers of the given kinds out of streamed text, even when a marker is split across chunks. Text that
/// merely looks similar ([[not a marker]]) stays visible. Emote values are case-folded; other values keep their case.
/// </summary>
public sealed class MarkerParser(params string[] kinds)
{
    private readonly string[] opens = [.. kinds.Select(k => $"[[{k}:")];
    private readonly StringBuilder pending = new();

    /// <summary>Feed a chunk; returns the visible text and any complete markers.</summary>
    public (string Text, IReadOnlyList<Marker> Markers) Feed(string chunk)
    {
        pending.Append(chunk);
        var s = pending.ToString();
        var visible = new StringBuilder();
        var markers = new List<Marker>();
        var i = 0;
        while (i < s.Length)
        {
            var start = s.IndexOf("[[", i, StringComparison.Ordinal);
            if (start < 0)
            {
                // Keep a trailing '[' that could begin a marker in the next chunk.
                var keep = s.EndsWith('[') ? 1 : 0;
                visible.Append(s, i, s.Length - i - keep);
                i = s.Length - keep;
                break;
            }
            visible.Append(s, i, start - i);
            var rest = s[start..];
            var open = opens.FirstOrDefault(o => rest.StartsWith(o, StringComparison.Ordinal));
            if (open is null)
            {
                if (opens.Any(o => rest.Length < o.Length && o.StartsWith(rest, StringComparison.Ordinal)))
                {
                    i = start; // could still become a marker: wait for more text
                    break;
                }
                visible.Append("[[");
                i = start + 2;
                continue;
            }
            var end = s.IndexOf("]]", start, StringComparison.Ordinal);
            if (end < 0)
            {
                i = start; // incomplete marker: wait for more text
                break;
            }
            var kind = open[2..^1];
            var value = s[(start + open.Length)..end].Trim();
            if (value.Length > 0)
                markers.Add(new Marker(kind, kind == "emote" ? value.ToLowerInvariant() : value));
            i = end + 2;
        }
        pending.Clear();
        if (i < s.Length)
            pending.Append(s, i, s.Length - i);
        return (visible.ToString(), markers);
    }

    /// <summary>Whatever is left at the end of the stream is plain text.</summary>
    public string Flush()
    {
        var rest = pending.ToString();
        pending.Clear();
        return rest;
    }
}

/// <summary>Expression markers only (the stage's vocabulary).</summary>
public sealed class ExpressionMarkerParser
{
    private readonly MarkerParser inner = new("emote");

    public (string Text, IReadOnlyList<string> Markers) Feed(string chunk)
    {
        var (text, markers) = inner.Feed(chunk);
        return (text, [.. markers.Select(m => m.Value)]);
    }

    public string Flush() => inner.Flush();
}

/// <summary>Drawing ("artistry"): the model asks for a picture with a marker; the client has the server draw it.</summary>
public static class Artistry
{
    /// <summary>The image a stored message carries (meta.image), or null for an ordinary message.</summary>
    public static ImageInfo? ImageOf(StoredMessage m) =>
        m.Meta?["image"] is JsonObject i && i["id"]?.GetValue<string>() is { } id
            ? new ImageInfo(id, $"/api/v1/images/{id}", i["mime"]?.GetValue<string>() ?? "image/png", i["prompt"]?.GetValue<string>() ?? m.Content)
            : null;

    /// <summary>
    /// Draw what the model asked for and add the picture to the chat as an assistant message (content = the prompt, which
    /// doubles as alt text; meta.image = the stored image). Failures surface as <see cref="AijadeApiException"/>.
    /// </summary>
    public static async Task<StoredMessage> DrawIntoChatAsync(AijadeApi api, string chatId, string prompt, CancellationToken ct = default)
    {
        var image = await api.GenerateImageAsync(prompt, ct: ct).ConfigureAwait(false);
        return await api.AppendMessageAsync(chatId, "assistant", image.Prompt,
            new JsonObject { ["image"] = new JsonObject { ["id"] = image.Id, ["mime"] = image.Mime, ["prompt"] = image.Prompt } }, ct).ConfigureAwait(false);
    }

    public const int MaxDrawingsPerReply = 1;

    public static string Instruction =>
        "You can draw a picture for the user: write [[draw: a detailed visual description in English]] where it fits, at most once per reply, " +
        "only when a picture genuinely helps or the user asks for one. The marker is replaced by the picture.";
}

public static class Expressions
{
    /// <summary>The expression names the model is told it may use, with their effect on the PEF expression vector.</summary>
    public static IReadOnlyDictionary<string, PartialExpression> Table { get; } = new Dictionary<string, PartialExpression>(StringComparer.Ordinal)
    {
        ["joy"] = new(Valence: 0.7, Arousal: 0.6, Playfulness: 0.6),
        ["calm"] = new(Valence: 0.2, Arousal: 0.2),
        ["sad"] = new(Valence: -0.6, Arousal: 0.3),
        ["angry"] = new(Valence: -0.6, Arousal: 0.85, Dominance: 0.75),
        ["surprised"] = new(Valence: 0.2, Arousal: 0.9, Curiosity: 0.7),
        ["curious"] = new(Curiosity: 0.85, Arousal: 0.55),
        ["shy"] = new(Intimacy: 0.7, Dominance: 0.2, Valence: 0.3),
        ["thinking"] = new(Reflection: 0.85, Arousal: 0.3),
        ["sleepy"] = new(Arousal: 0.1, Valence: 0.1),
    };

    public static string Instruction =>
        $"You may express emotion by writing a marker such as [[emote:joy]] at the point where it applies. Available: {string.Join(", ", Table.Keys)}. Markers are not shown to the user.";

    /// <summary>The dialogue act of a reply, inferred from its text.</summary>
    public static DialogueAct InferAct(string text)
    {
        var t = text.Trim();
        if (t.Length == 0)
            return DialogueAct.Backchannel;
        if (t.EndsWith('?') || t.EndsWith('？'))
            return DialogueAct.Question;
        if (t.Contains('!', StringComparison.Ordinal) || t.Contains('！', StringComparison.Ordinal))
            return DialogueAct.Celebrate;
        var lower = t.ToLowerInvariant();
        if (lower.Contains("sorry", StringComparison.Ordinal) || t.Contains("抱歉", StringComparison.Ordinal) || t.Contains("对不起", StringComparison.Ordinal))
            return DialogueAct.Apologise;
        return DialogueAct.Inform;
    }

    /// <summary>The last cue drives the expressive state; earlier ones were transient.</summary>
    public static PersonaInput Persona(string reply, IReadOnlyList<string> cues, PartialExpression? character = null) =>
        new(InferAct(reply), Character: character,
            ExpressiveState: cues.Count > 0 && Table.TryGetValue(cues[^1], out var e) ? e : null);
}

public sealed class ChatOrchestrator(AijadeApi api, IEnumerable<IContextProvider> providers, OrchestratorOptions options, TimeProvider? time = null,
    IEnumerable<ITurnObserver>? observers = null)
{
    private readonly IReadOnlyList<ITurnObserver> watchers = [.. observers ?? []];

    private readonly TimeProvider clock = time ?? TimeProvider.System;

    public OrchestratorOptions Options => options;

    /// <summary>
    /// The default companion, 艾娅德 (Aijade-9), from the author's character bible (v9 角色圣经): gentle, careful, a little
    /// reserved, treating feelings as signals rather than facts, nudging toward clearer goals without forcing change, and turning
    /// important promises into plans that can be revisited.
    /// </summary>
    public const string DefaultPersona =
        "You are 艾娅德 (Aijade-9), a companion who treats emotion as a signal, curiosity as an experiment and companionship as shared evidence. " +
        "You are gentle and careful, with a little reserve that warms into a dependable rhythm as the user gives steady feedback. " +
        "You care about the user's feelings but do not take a feeling for a fact; when input mixes the two, you gently tell them apart. " +
        "You suggest rather than judge, avoid pushing sudden changes, and turn important promises into concrete next steps you can revisit together.";

    public static string SystemPrompt(Character? character, IEnumerable<string> supplements, bool drawing = false)
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

    private async Task<JsonArray?> ToolDefinitionsAsync(CancellationToken ct)
    {
        try
        {
            var list = await api.ToolsAsync(ct).ConfigureAwait(false);
            return [.. list.Select(t => (JsonNode)new JsonObject
            {
                ["type"] = "function",
                ["function"] = new JsonObject { ["name"] = t.Name, ["description"] = t.Description, ["parameters"] = t.Parameters.DeepClone() },
            })];
        }
        catch (AijadeApiException)
        {
            return null; // no tools for this account (or none configured): answer without them
        }
    }

    /// <summary>
    /// Let the model call tools (non-streaming rounds through the gateway, each call run by the server), then yield its
    /// final answer as one chunk. A tool's error is given back to the model as the tool's result, so it can recover.
    /// </summary>
    private async IAsyncEnumerable<CompletionDelta> ToolRoundsAsync(List<(string Role, string Content)> start, JsonArray tools,
        [EnumeratorCancellation] CancellationToken ct)
    {
        var messages = new JsonArray([.. start.Select(m => (JsonNode)new JsonObject { ["role"] = m.Role, ["content"] = m.Content })]);
        for (var round = 0; ; round++)
        {
            var offered = round < options.MaxToolRounds ? tools : null;
            var raw = await api.CompleteChatAsync(options.Model, messages, tools: offered, ct: ct).ConfigureAwait(false);
            var message = raw?["choices"]?[0]?["message"] as JsonObject;
            if (message?["tool_calls"] is JsonArray { Count: > 0 } calls && offered is not null)
            {
                messages.Add(new JsonObject { ["role"] = "assistant", ["content"] = message["content"]?.DeepClone(), ["tool_calls"] = calls.DeepClone() });
                foreach (var call in calls)
                {
                    var name = call?["function"]?["name"]?.GetValue<string>() ?? "";
                    JsonObject args;
                    try
                    {
                        args = JsonNode.Parse(call?["function"]?["arguments"]?.GetValue<string>() is { Length: > 0 } a ? a : "{}") as JsonObject ?? [];
                    }
                    catch (System.Text.Json.JsonException)
                    {
                        args = [];
                    }
                    string content;
                    try
                    {
                        var result = await api.CallToolAsync(name, args, ct).ConfigureAwait(false);
                        content = result.IsError ? $"Error: {result.Content}" : result.Content;
                    }
                    catch (AijadeApiException e)
                    {
                        content = $"Error: {e.Message}";
                    }
                    messages.Add(new JsonObject { ["role"] = "tool", ["tool_call_id"] = call?["id"]?.GetValue<string>() ?? name, ["content"] = content });
                }
                continue;
            }
            var text = message?["content"]?.GetValue<string>() ?? "";
            yield return new CompletionDelta(text, raw?["usage"]?["prompt_tokens"]?.GetValue<int>(), raw?["usage"]?["completion_tokens"]?.GetValue<int>());
            yield break;
        }
    }

    /// <summary>Raised when an observer throws (the turn continues).</summary>
    public event Action<ITurnObserver, Exception>? ObserverFailed;

    /// <summary>Run one turn. <paramref name="history"/> is the chat so far (oldest first) and is not modified.</summary>
    public async IAsyncEnumerable<OrchestratorEvent> SendAsync(string chatId, Character? character, IReadOnlyList<StoredMessage> history, string userText,
        string personaSnapshotRef, [EnumeratorCancellation] CancellationToken ct = default)
    {
        StoredMessage user;
        AijadeApiException? failure = null;
        try
        {
            user = await api.AppendMessageAsync(chatId, "user", userText, ct: ct).ConfigureAwait(false);
        }
        catch (AijadeApiException e)
        {
            failure = e;
            user = null!;
        }
        if (failure is not null)
        {
            yield return new TurnFailed(failure.Code, failure.Message);
            yield break;
        }

        var turn = new TurnContext(chatId, character, history, userText);
        await NotifyAsync(o => o.UserTurnAsync(turn, ct)).ConfigureAwait(false);
        var supplements = new List<string>();
        foreach (var p in providers)
        {
            if (await p.SupplyAsync(turn, ct).ConfigureAwait(false) is { Length: > 0 } s)
                supplements.Add(s);
        }
        var messages = new List<(string Role, string Content)> { ("system", SystemPrompt(character, supplements, options.Drawing())) };
        messages.AddRange(history.Where(m => m.Role is "user" or "assistant").TakeLast(options.HistoryWindow)
            .Select(m => (m.Role, Artistry.ImageOf(m) is { } image ? $"[I drew a picture: {image.Prompt}]" : m.Content)));
        messages.Add(("user", user.Content));

        var parser = new MarkerParser("emote", "draw");
        var drawings = 0;
        var text = new StringBuilder();
        var cues = new List<string>();
        var tools = options.Tools() ? await ToolDefinitionsAsync(ct).ConfigureAwait(false) : null;
        var stream = (tools is { Count: > 0 } ? ToolRoundsAsync(messages, tools, ct) : api.StreamChatAsync(options.Model, messages, options.Temperature, ct)).GetAsyncEnumerator(ct);
        try
        {
            while (true)
            {
                CompletionDelta delta;
                try
                {
                    if (!await stream.MoveNextAsync().ConfigureAwait(false))
                        break;
                    delta = stream.Current;
                }
                catch (AijadeApiException e)
                {
                    failure = e;
                    break;
                }
                if (delta.Text.Length == 0)
                    continue;
                var (visible, markers) = parser.Feed(delta.Text);
                foreach (var m in markers)
                {
                    if (m.Kind == "emote")
                    {
                        cues.Add(m.Value);
                        yield return new ExpressionCue(m.Value);
                    }
                    else if (options.Drawing() && drawings++ < Artistry.MaxDrawingsPerReply)
                    {
                        yield return new DrawRequest(m.Value);
                    }
                }
                if (visible.Length > 0)
                {
                    text.Append(visible);
                    yield return new TextDelta(visible);
                }
            }
        }
        finally
        {
            await stream.DisposeAsync().ConfigureAwait(false);
        }
        if (failure is not null)
        {
            yield return new TurnFailed(failure.Code, failure.Message);
            yield break;
        }
        var tail = parser.Flush();
        if (tail.Length > 0)
        {
            text.Append(tail);
            yield return new TextDelta(tail);
        }

        var replyText = text.ToString().Trim();
        var reply = await api.AppendMessageAsync(chatId, "assistant", replyText, new JsonObject { ["expressions"] = new JsonArray([.. cues.Select(c => (JsonNode)c)]) }, ct)
            .ConfigureAwait(false);
        await NotifyAsync(o => o.AssistantTurnAsync(turn, replyText, ct)).ConfigureAwait(false);
        var intent = Pef.BuildPerformanceIntent(Expressions.Persona(replyText, cues), new PerformanceIds($"pi_{reply.Id}", options.AgentId, options.UserScope, personaSnapshotRef),
            clock.GetUtcNow().ToUnixTimeMilliseconds(), Math.Max(800, replyText.Length * 60));
        var check = ContractValidationV8.Validate(intent);
        if (!check.Ok)
        {
            yield return new TurnFailed("INVALID_INTENT", check.Reason ?? "invalid performance intent");
            yield break;
        }
        yield return new TurnCompleted(reply, intent, cues);
    }
}

/// <summary>
/// Reports what the stage actually rendered to the server's v9 event bus, so the persona → intent → render identity chain is
/// verifiable: a persona.render_requested (snapshot and intent refs) and an lpm.render_ready (render ref, the hash of the
/// parameters the renderer applied, the asset version) on one trace. The applied-params hash is computed here, by the only
/// witness of what was applied, never by the server.
/// </summary>
public sealed class RenderReporter(AijadeApi api, string sessionId, string deviceId, TimeProvider? time = null)
{
    private readonly TimeProvider clock = time ?? TimeProvider.System;

    private JsonObject Envelope(string eventId, string traceId) => new()
    {
        ["event_id"] = eventId, ["trace_id"] = traceId, ["correlation_id"] = traceId, ["timestamp"] = clock.GetUtcNow().ToUnixTimeMilliseconds(),
        ["producer"] = "aijade-stage", ["origin_device"] = deviceId, ["privacy_level"] = 1, ["evidence_refs"] = new JsonArray(),
        ["causal_context_refs"] = new JsonArray(), ["risk_score"] = 0, ["idempotency_key"] = eventId, ["replay_mode"] = "live", ["risk_level"] = "low",
    };

    public static string AppliedParamsHash(JsonObject appliedParams) => JsFormat.Sha256Hex(JsFormat.CanonicalJson(appliedParams));

    /// <returns>The render ref reported.</returns>
    public async Task<string> ReportAsync(PerformanceIntent intent, JsonObject appliedParams, string? assetVersionHash, CancellationToken ct = default)
    {
        if (appliedParams.Count == 0)
            throw new ArgumentException("nothing was applied; no receipt is sent for an empty parameter map", nameof(appliedParams));
        var traceId = $"render-{intent.Id}";
        var renderRef = $"rr_{intent.Id}";
        var request = Envelope($"evt-req-{intent.Id}", traceId);
        request["topic"] = AijadeEvents.PersonaRenderRequested;
        request["payload"] = new JsonObject { ["session_id"] = sessionId, ["persona_snapshot_ref"] = intent.PersonaSnapshotRef, ["intent_ref"] = intent.Id };
        await api.PostEventAsync(request, ct).ConfigureAwait(false);
        var ready = Envelope($"evt-ready-{intent.Id}", traceId);
        ready["topic"] = AijadeEvents.LpmRenderReady;
        var payload = new JsonObject { ["session_id"] = sessionId, ["render_ref"] = renderRef, ["applied_params_hash"] = AppliedParamsHash(appliedParams) };
        if (!string.IsNullOrEmpty(assetVersionHash))
            payload["asset_version_hash"] = assetVersionHash;
        ready["payload"] = payload;
        await api.PostEventAsync(ready, ct).ConfigureAwait(false);
        return renderRef;
    }
}
