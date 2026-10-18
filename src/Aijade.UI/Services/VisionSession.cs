using Aijade.Client.Api;
using Aijade.Client.Chat;
using Aijade.Client.Settings;

namespace Aijade.UI.Services;

/// <summary>
/// The vision module for this app session: while the user shares the screen or camera, look every few seconds (as set in
/// Settings) and keep the description as chat context; describe attached images for the next turn. Sharing survives page
/// changes and stops when the user signs out or switches the module off.
/// </summary>
public sealed class VisionSession : IAsyncDisposable
{
    private readonly VisionCapture capture;
    private readonly SettingsService settings;
    private readonly VisionInterpreter interpreter;
    private CancellationTokenSource? loop;

    public VisionSession(VisionCapture capture, SettingsService settings, AijadeApi api, AppState state)
    {
        this.capture = capture;
        this.settings = settings;
        interpreter = new VisionInterpreter(api, () => settings.Current.VisionCapture.Model is { Length: > 0 } m ? m : settings.Current.Model);
        Context = new VisionContext(() => settings.Current.Modules.Vision);
        capture.Ended += () => _ = StopAsync();
        state.Changed += () =>
        {
            if (state.Account is null)
                Context.Clear();
            if (state.Account is null || !settings.Current.Modules.Vision)
                _ = StopAsync();
        };
    }

    public VisionContext Context { get; }

    /// <summary>What is being shared, or null.</summary>
    public VisionSource? Sharing { get; private set; }

    public string? LastError { get; private set; }

    public bool Looking { get; private set; }

    public event Action? Changed;

    public async Task StartAsync(VisionSource source)
    {
        await StopAsync();
        LastError = await capture.StartAsync(source);
        if (LastError is null)
        {
            Sharing = source;
            loop = new CancellationTokenSource();
            _ = RunAsync(loop.Token);
        }
        Changed?.Invoke();
    }

    private async Task RunAsync(CancellationToken ct)
    {
        try
        {
            while (!ct.IsCancellationRequested)
            {
                await LookAsync(ct);
                await Task.Delay(TimeSpan.FromSeconds(Math.Clamp(settings.Current.VisionCapture.IntervalSeconds, 5, 600)), ct);
            }
        }
        catch (OperationCanceledException)
        {
        }
    }

    /// <summary>Take one look now (also what the loop does each interval).</summary>
    public async Task LookAsync(CancellationToken ct = default)
    {
        if (Sharing is not { } source)
            return;
        var frame = await capture.GrabAsync(settings.Current.VisionCapture.MaxWidth);
        if (frame is null)
            return; // no frame yet: the next tick tries again
        Looking = true;
        Changed?.Invoke();
        try
        {
            Context.Observe(source, await interpreter.DescribeAsync(frame, source, ct));
            LastError = null;
        }
        catch (AijadeApiException e)
        {
            LastError = e.Message;
        }
        catch (HttpRequestException e)
        {
            LastError = e.Message;
        }
        finally
        {
            Looking = false;
            Changed?.Invoke();
        }
    }

    /// <summary>Describe an image the user attaches; its description goes with their next message. Null when it failed.</summary>
    public async Task<string?> AttachAsync(byte[] bytes, string mime, CancellationToken ct = default)
    {
        var dataUrl = await capture.DownscaleAsync(bytes, mime, settings.Current.VisionCapture.MaxWidth);
        if (dataUrl is null)
        {
            LastError = "not an image this browser can read";
            Changed?.Invoke();
            return null;
        }
        Looking = true;
        Changed?.Invoke();
        try
        {
            var text = await interpreter.DescribeAsync(dataUrl, VisionSource.Attachment, ct);
            Context.Observe(VisionSource.Attachment, text);
            LastError = null;
            return text;
        }
        catch (Exception e) when (e is AijadeApiException or HttpRequestException)
        {
            LastError = e.Message;
            return null;
        }
        finally
        {
            Looking = false;
            Changed?.Invoke();
        }
    }

    public async Task StopAsync()
    {
        loop?.Cancel();
        loop?.Dispose();
        loop = null;
        var was = Sharing;
        Sharing = null;
        Context.ClearLive();
        await capture.StopAsync();
        if (was is not null)
            Changed?.Invoke();
    }

    public async ValueTask DisposeAsync() => await StopAsync();
}
