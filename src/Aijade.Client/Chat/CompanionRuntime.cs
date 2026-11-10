using Aijade.Client.Api;
using Aijade.Client.Companion;

namespace Aijade.Client.Chat;

/// <summary>One optional capability, registered once for both prompt context and turn observation.</summary>
public sealed record ChatModule(string Id, IContextProvider? Context = null, ITurnObserver? Observer = null,
    Func<bool>? Enabled = null, bool Required = false);

/// <summary>
/// The composition root shared by the browser, native apps, bots and MCP. Hosts choose capabilities; the runtime owns
/// their order, failure isolation and the media / conversation entry point. It starts no loops or model requests.
/// </summary>
public static class CompanionRuntime
{
    public static ChatOrchestrator Create(AijadeApi api, IEnumerable<ChatModule> modules, OrchestratorOptions options,
        CompanionExperience? companion = null, bool audio = true, TimeProvider? time = null,
        Action<string, Exception>? moduleFailed = null)
    {
        var pipeline = new ChatModuleSet(modules, moduleFailed);
        var configured = options with
        {
            Companion = companion,
            Audio = audio,
            CompanionContext = companion is null ? options.CompanionContext : companion.SupplyAsync,
        };
        return new ChatOrchestrator(api, [pipeline], configured, time, [pipeline]);
    }
}

/// <summary>Ordered, named capabilities; a failed optional module cannot take down the companion.</summary>
public sealed class ChatModuleSet : IContextProvider, ITurnObserver
{
    private readonly IReadOnlyList<ChatModule> modules;
    private readonly Action<string, Exception> failed;

    public ChatModuleSet(IEnumerable<ChatModule> modules, Action<string, Exception>? failed = null)
    {
        this.modules = [.. modules];
        if (this.modules.Any(m => string.IsNullOrWhiteSpace(m.Id) || (m.Context is null && m.Observer is null)))
            throw new ArgumentException("Every chat module needs an id and a context provider or observer", nameof(modules));
        if (this.modules.Select(m => m.Id).Distinct(StringComparer.Ordinal).Count() != this.modules.Count)
            throw new ArgumentException("Chat module ids must be unique", nameof(modules));
        this.failed = failed ?? ((id, e) => Console.Error.WriteLine($"Chat module {id} failed: {e.GetType().Name}"));
    }

    public IReadOnlyList<string> Ids => [.. modules.Select(m => m.Id)];

    public async Task<string?> SupplyAsync(TurnContext turn, CancellationToken ct)
    {
        var context = new List<string>();
        foreach (var module in modules)
        {
            await InvokeAsync(module, async () =>
            {
                if (module.Context is { } provider && await provider.SupplyAsync(turn, ct).ConfigureAwait(false) is { Length: > 0 } text)
                    context.Add(text);
            }, ct).ConfigureAwait(false);
        }
        return context.Count == 0 ? null : string.Join("\n\n", context);
    }

    public Task UserTurnAsync(TurnContext turn, CancellationToken ct) =>
        ObserveAsync(o => o.UserTurnAsync(turn, ct), ct);

    public Task AssistantTurnAsync(TurnContext turn, string reply, CancellationToken ct) =>
        ObserveAsync(o => o.AssistantTurnAsync(turn, reply, ct), ct);

    private async Task ObserveAsync(Func<ITurnObserver, Task> call, CancellationToken ct)
    {
        foreach (var module in modules)
            await InvokeAsync(module, () => module.Observer is { } observer ? call(observer) : Task.CompletedTask, ct).ConfigureAwait(false);
    }

    private async Task InvokeAsync(ChatModule module, Func<Task> call, CancellationToken ct)
    {
        ct.ThrowIfCancellationRequested();
        try
        {
            if (module.Enabled?.Invoke() != false)
                await call().ConfigureAwait(false);
        }
#pragma warning disable CA1031 // Only optional capabilities degrade; caller cancellation and required context propagate.
        catch (Exception e) when (!module.Required && !ct.IsCancellationRequested)
#pragma warning restore CA1031
        {
            failed(module.Id, e);
        }
    }
}
