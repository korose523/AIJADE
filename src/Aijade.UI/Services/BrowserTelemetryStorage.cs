using System.Text.Json;

using Aijade.Research.Telemetry;

using Microsoft.JSInterop;

namespace Aijade.UI.Services;

/// <summary>Research telemetry kept in this browser's IndexedDB (telemetry-db.js), serialized exactly like the file store.</summary>
public sealed class BrowserTelemetryStorage(IJSRuntime js) : ITelemetryStorage
{
    private IJSObjectReference? module;

    private async ValueTask<IJSObjectReference> ModuleAsync() => module ??= await js.InvokeAsync<IJSObjectReference>("import", "./_content/Aijade.UI/telemetry-db.js");

    public async Task SaveSessionAsync(SessionMeta session, CancellationToken cancellationToken = default) =>
        await (await ModuleAsync()).InvokeVoidAsync("putSession", cancellationToken, session.SessionId, JsonSerializer.Serialize(session, TelemetryJson.Options));

    public async Task AppendTurnAsync(TurnRecord record, CancellationToken cancellationToken = default) =>
        await (await ModuleAsync()).InvokeVoidAsync("addTurn", cancellationToken, record.SessionId, JsonSerializer.Serialize(record, TelemetryJson.Options));

    public async Task<IReadOnlyList<TurnRecord>> ReadTurnsAsync(string sessionId, CancellationToken cancellationToken = default) =>
        [.. (await (await ModuleAsync()).InvokeAsync<string[]>("turns", cancellationToken, sessionId))
            .Select(j => JsonSerializer.Deserialize<TurnRecord>(j, TelemetryJson.Options)!).OrderBy(t => t.TurnIndex)];

    public async Task<IReadOnlyList<SessionMeta>> ReadSessionsAsync(CancellationToken cancellationToken = default) =>
        [.. (await (await ModuleAsync()).InvokeAsync<string[]>("sessions", cancellationToken))
            .Select(j => JsonSerializer.Deserialize<SessionMeta>(j, TelemetryJson.Options)!).OrderBy(s => s.StartedAt)];

    public async Task ClearAsync(CancellationToken cancellationToken = default) => await (await ModuleAsync()).InvokeVoidAsync("clear", cancellationToken);

    /// <summary>Everything recorded here as JSON lines: sessions.jsonl and turns.jsonl, as the file store would have written them.</summary>
    public async Task<(string Sessions, string Turns)> ExportAsync(CancellationToken cancellationToken = default)
    {
        var m = await ModuleAsync();
        var sessions = await m.InvokeAsync<string[]>("sessions", cancellationToken);
        var turns = await m.InvokeAsync<string[]>("allTurns", cancellationToken);
        return (string.Join("\n", sessions) + (sessions.Length > 0 ? "\n" : ""), string.Join("\n", turns) + (turns.Length > 0 ? "\n" : ""));
    }
}
