using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Chat;
using Aijade.Core.Js;
using Aijade.Learning.Continuous;
using Aijade.Learning.Forge;
using Aijade.Providers.Llm;

namespace Aijade.Client.Agent;

// The bridge that fuses skill
// auto-creation and continuous learning into the chat pipeline through the orchestrator's extension points only (a
// context provider and turn observers), never by changing the orchestrator itself. Computer control, the third capability,
// plugs into the same options.

/// <summary>The learning loop's model: the server gateway, so it is billed and routed like chat.</summary>
public sealed class GatewayChatClient(AijadeApi api, Func<string> model) : IChatClient
{
    public string Model => model();

    public async Task<ChatCompletion> CompleteAsync(IReadOnlyList<ChatMessage> messages, ChatRequestOptions? options = null, CancellationToken cancellationToken = default)
    {
        var raw = await api.CompleteChatAsync(Model, [.. messages.Select(m => (WireName.Of(m.Role), m.Content))], options?.Temperature, options?.MaxTokens, cancellationToken)
            .ConfigureAwait(false);
        return ChatParsing.ParseCompletion(raw, Model);
    }

    public async Task<JsonNode?> JsonCompleteAsync(IReadOnlyList<ChatMessage> messages, ChatRequestOptions? options = null, CancellationToken cancellationToken = default) =>
        ChatParsing.ParseJsonContent((await CompleteAsync(messages, options, cancellationToken).ConfigureAwait(false)).Text);
}

public sealed class AgentCapabilitiesOptions
{
    /// <summary>Checked on every turn; when false the bridge neither learns nor adds context (the "Learning" module switch).</summary>
    public Func<bool> Enabled { get; init; } = () => true;

    /// <summary>Turn a teachable moment into a registered skill after a reply. Default true.</summary>
    public bool AutoCreateSkills { get; init; } = true;

    /// <summary>Every persona change, for research telemetry (the longitudinal trajectory).</summary>
    public Action<PersonaUpdateEvent>? OnPersonaUpdate { get; init; }

    public TimeProvider Time { get; init; } = TimeProvider.System;
}

/// <summary>
/// One per app session (learning state spans chats): supplies the persona and discourse context plus the skill index to each
/// turn, feeds both sides of the conversation to continuous learning, drifts the persona by the time between turns, and
/// after each reply compacts discourse memory and tries to forge a skill from the recent exchange. Background work never
/// blocks or fails a turn; <see cref="Background"/> exposes it for tests and for a clean shutdown.
/// </summary>
public sealed class AgentCapabilities : IContextProvider, ITurnObserver
{
    private readonly AgentCapabilitiesOptions options;
    private readonly object gate = new();
    private Task background = Task.CompletedTask;
    private bool creating;
    private long lastTurn;

    public AgentCapabilities(IChatClient llm, AgentCapabilitiesOptions? options = null, SkillForge? forge = null, ContinuousLearning? learning = null)
    {
        this.options = options ?? new AgentCapabilitiesOptions();
        var now = () => (double)this.options.Time.GetUtcNow().ToUnixTimeMilliseconds();
        SkillForge = forge ?? new SkillForge(llm, now: now);
        Learning = learning ?? new ContinuousLearning(llm, forge: SkillForge, onPersonaUpdate: this.options.OnPersonaUpdate, now: now);
        lastTurn = this.options.Time.GetUtcNow().ToUnixTimeMilliseconds();
    }

    public SkillForge SkillForge { get; }

    public ContinuousLearning Learning { get; }

    /// <summary>The compaction / skill-creation work started by the latest turns.</summary>
    public Task Background
    {
        get
        {
            lock (gate)
                return background;
        }
    }

    /// <summary>Last background failure (model unreachable, malformed skill JSON …); informational only.</summary>
    public string? LastBackgroundError { get; private set; }

    public string SkillIndex()
    {
        var skills = SkillForge.Registry.List();
        return skills.Count == 0
            ? ""
            : $"You have these reusable skills (invoke via the skill tools):\n{string.Join("\n", skills.Select(s => $"- {s.Frontmatter.Name}: {s.Frontmatter.Description}"))}";
    }

    public Task<string?> SupplyAsync(TurnContext turn, CancellationToken ct)
    {
        if (!options.Enabled())
            return Task.FromResult<string?>(null);
        var text = string.Join("\n\n", new[] { Learning.ContextSupplement(), SkillIndex() }.Where(p => JsText.Trim(p).Length > 0));
        return Task.FromResult<string?>(text.Length == 0 ? null : text);
    }

    public async Task UserTurnAsync(TurnContext turn, CancellationToken ct)
    {
        if (options.Enabled())
            await Learning.IngestTurnAsync(ChatRole.User, turn.UserText, ct: ct).ConfigureAwait(false);
    }

    public async Task AssistantTurnAsync(TurnContext turn, string reply, CancellationToken ct)
    {
        if (!options.Enabled())
            return;
        await Learning.IngestTurnAsync(ChatRole.Assistant, reply, ct: ct).ConfigureAwait(false);
        // Persona drift between turns keeps the mood from freezing.
        var now = options.Time.GetUtcNow().ToUnixTimeMilliseconds();
        var dt = now - Interlocked.Exchange(ref lastTurn, now);
        Learning.Tick(dt);
        lock (gate)
            background = Task.WhenAll(background, Guarded(() => Learning.CompactAsync(CancellationToken.None)), options.AutoCreateSkills ? Guarded(MaybeCreateSkillAsync) : Task.CompletedTask);
    }

    private async Task Guarded(Func<Task> work)
    {
        try
        {
            await work().ConfigureAwait(false);
        }
#pragma warning disable CA1031 // background learning must never surface into the chat turn; the failure is kept for inspection
        catch (Exception e)
#pragma warning restore CA1031
        {
            LastBackgroundError = e.Message;
        }
    }

    private async Task MaybeCreateSkillAsync()
    {
        lock (gate)
        {
            if (creating)
                return;
            creating = true;
        }
        try
        {
            var history = Learning.Discourse.RecentMessages();
            if (history.Count < 2)
                return;
            if (await SkillForge.DetectTeachableMomentAsync(history).ConfigureAwait(false) is not { } draft)
                return;
            SkillForge.Register(await SkillForge.GenerateSkillAsync(draft).ConfigureAwait(false));
        }
        finally
        {
            lock (gate)
                creating = false;
        }
    }
}
