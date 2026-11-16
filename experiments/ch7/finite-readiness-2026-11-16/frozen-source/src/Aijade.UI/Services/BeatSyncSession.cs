using Aijade.Client.Chat;
using Aijade.Client.Settings;

using Microsoft.JSInterop;

namespace Aijade.UI.Services;

/// <summary>
/// Beat sync for the stage: listens to the music the user chooses (microphone or a shared tab), runs the beat detector
/// and raises <see cref="Beat"/> for the stage to move with. The tempo and confidence are shown for troubleshooting.
/// Stops when the user signs out or switches beat sync off.
/// </summary>
public sealed class BeatSyncSession : IAsyncDisposable
{
    private readonly IJSRuntime js;
    private readonly BeatDetector detector = new();
    private IJSObjectReference? module;
    private DotNetObjectReference<BeatSyncSession>? self;
    private double lastNotify;

    public BeatSyncSession(IJSRuntime js, SettingsService settings, AppState state)
    {
        this.js = js;
        state.Changed += () =>
        {
            if (state.Account is null || !settings.Current.Stage.BeatSync)
                _ = StopAsync();
        };
    }

    public bool Listening { get; private set; }

    public string? LastError { get; private set; }

    public double? Bpm => detector.Bpm;

    public double Confidence => detector.Confidence;

    public int BeatCount => detector.BeatCount;

    public event Action<Beat>? Beat;

    /// <summary>Status changed (start / stop / error, and tempo updates at most twice a second).</summary>
    public event Action? Changed;

    private async ValueTask<IJSObjectReference> ModuleAsync() => module ??= await js.InvokeAsync<IJSObjectReference>("import", "./_content/Aijade.UI/beat.js");

    /// <summary>Start listening to "mic" or "tab".</summary>
    public async Task StartAsync(string source)
    {
        await StopAsync();
        detector.Reset();
        self ??= DotNetObjectReference.Create(this);
        LastError = await (await ModuleAsync()).InvokeAsync<string?>("start", self, source);
        Listening = LastError is null;
        Changed?.Invoke();
    }

    public async Task StopAsync()
    {
        if (module is not null && Listening)
            await module.InvokeVoidAsync("stop");
        if (Listening)
        {
            Listening = false;
            Changed?.Invoke();
        }
    }

    [JSInvokable]
    public void OnEnergy(double atMs, double energy)
    {
        if (detector.Feed(atMs, energy) is { } beat)
            Beat?.Invoke(beat);
        if (atMs - lastNotify > 500)
        {
            lastNotify = atMs;
            Changed?.Invoke();
        }
    }

    [JSInvokable]
    public void OnEnded()
    {
        Listening = false;
        Changed?.Invoke();
    }

    public async ValueTask DisposeAsync()
    {
        await StopAsync();
        if (module is not null)
        {
            try
            {
                await module.DisposeAsync();
            }
            catch (JSDisconnectedException)
            {
            }
        }
        self?.Dispose();
    }
}
