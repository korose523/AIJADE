using Aijade.Client.Api;
using Aijade.Client.Companion;
using Aijade.Memory.Contracts;

namespace Aijade.Client.Chat;

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

public sealed record TurnContext(string ChatId, Character? Character, IReadOnlyList<StoredMessage> History, string UserText)
{
    public string? UserMessageId { get; init; }
}

/// <summary>Raw channel input stays separate from the speaker label used in group-room prompts.</summary>
public sealed record ChatInput(string Text, string? Speaker = null)
{
    public string PromptText => Speaker is null ? Text : $"{Speaker}: {Text}";
}

public abstract record OrchestratorEvent;

public sealed record TextDelta(string Text) : OrchestratorEvent;

/// <summary>An expression marker found in the stream, e.g. [[emote:joy]].</summary>
public sealed record ExpressionCue(string Name) : OrchestratorEvent;

/// <summary>The model asked for a picture (only when drawing is enabled); the marker itself is not shown.</summary>
public sealed record DrawRequest(string Prompt) : OrchestratorEvent;

public sealed record TurnCompleted(StoredMessage Reply, PerformanceIntent Intent, IReadOnlyList<string> Expressions) : OrchestratorEvent;

public sealed record TurnFailed(string Code, string Message) : OrchestratorEvent;

/// <summary>An explicit photo, song, life, relationship or diary command completed without a chat-model request.</summary>
public sealed record MediaCompleted(StoredMessage Reply) : OrchestratorEvent;

public sealed record OrchestratorOptions
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

    /// <summary>Total external tool calls per turn, across all rounds. Zero allows conversation only.</summary>
    public int MaxToolCalls { get; set; } = 12;

    /// <summary>Deadline for one tool call, clamped to 1..300 seconds. Timeout does not prove that an effect was undone.</summary>
    public int ToolTimeoutSeconds { get; set; } = 30;

    /// <summary>Null preserves the archived direct caller's prompt construction; the product factory supplies defaults.</summary>
    public PromptBudget? PromptBudget { get; set; }

    /// <summary>Additional product output rules; null retains the archived direct caller's system prompt.</summary>
    public string? ReplyInstruction { get; set; }

    /// <summary>Optional fictional life context for product-only first lines; it does not call research memory providers.</summary>
    public Func<TurnContext, CancellationToken, Task<string?>>? CompanionContext { get; set; }

    /// <summary>The product command handler; omitted by archived research drivers.</summary>
    public CompanionExperience? Companion { get; set; }

    public bool Audio { get; set; } = true;
}
