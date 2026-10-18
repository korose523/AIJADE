using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Chat;
using Aijade.Client.Settings;

using Microsoft.JSInterop;

namespace Aijade.UI.Services;

// Platform services backed by the browser (also used inside the MAUI web view): localStorage, the session token, the
// microphone with voice-activity detection and speech recognition, audio playback with a lip-sync level, and the stage.

public sealed class BrowserKeyValueStore(IJSRuntime js) : IKeyValueStore
{
    public ValueTask<string?> GetAsync(string key) => js.InvokeAsync<string?>("localStorage.getItem", key);

    public ValueTask SetAsync(string key, string value) => js.InvokeVoidAsync("localStorage.setItem", key, value);

    public ValueTask RemoveAsync(string key) => js.InvokeVoidAsync("localStorage.removeItem", key);
}

public sealed class BrowserTokenStore(IKeyValueStore store) : ITokenStore
{
    public const string Key = "aijade.session";

    public ValueTask<string?> GetAsync() => store.GetAsync(Key);

    public ValueTask SetAsync(string? token) => token is null ? store.RemoveAsync(Key) : store.SetAsync(Key, token);
}

/// <summary>Microphone input: device list, VAD or push-to-talk capture, recognition through the Web Speech API.</summary>
public sealed class VoiceInput(IJSRuntime js, AijadeApi api) : IAsyncDisposable
{
    private IJSObjectReference? module;
    private DotNetObjectReference<VoiceInput>? self;

    public event Action<string, bool>? Transcript;

    public event Action<double>? Level;

    public event Action<string>? Failed;

    public event Action<bool>? SpeakingChanged;

    private async ValueTask<IJSObjectReference> ModuleAsync() => module ??= await js.InvokeAsync<IJSObjectReference>("import", "./_content/Aijade.UI/voice.js");

    public async Task<IReadOnlyList<(string Id, string Label)>> DevicesAsync()
    {
        var list = await (await ModuleAsync()).InvokeAsync<JsonArray>("devices");
        return list.Select(d => (d!["id"]!.GetValue<string>(), d["label"]!.GetValue<string>())).ToList();
    }

    /// <summary>Start listening; a failure (no permission, no device, no recognition support) is reported, never thrown away.</summary>
    public async Task StartAsync(VoiceSettings settings, string locale)
    {
        self ??= DotNetObjectReference.Create(this);
        language = locale.Split('-')[0];
        await (await ModuleAsync()).InvokeVoidAsync("start", self, new
        {
            deviceId = settings.InputDeviceId, vad = settings.VadEnabled, threshold = settings.VadThreshold, pushToTalkKey = settings.PushToTalkKey, lang = locale,
            recognition = settings.Recognition,
        });
    }

    public async Task StopAsync()
    {
        if (module is not null)
            await module.InvokeVoidAsync("stop");
    }

    [JSInvokable] public void OnTranscript(string text, bool final) => Transcript?.Invoke(text, final);

    [JSInvokable] public void OnLevel(double level) => Level?.Invoke(level);

    [JSInvokable] public void OnError(string message) => Failed?.Invoke(message);

    private string? language;

    /// <summary>A recorded utterance (server recognition): transcribed by the server and reported as a final transcript.</summary>
    [JSInvokable]
    public async Task OnUtterance(byte[] audio, string mime, double seconds)
    {
        try
        {
            var text = await api.TranscribeAsync(audio, mime, language, seconds);
            if (text.Trim().Length > 0)
                Transcript?.Invoke(text.Trim(), true);
        }
        catch (AijadeApiException e)
        {
            Failed?.Invoke($"server recognition: {e.Message}");
        }
        catch (HttpRequestException e)
        {
            Failed?.Invoke($"server recognition: {e.Message}");
        }
    }

    [JSInvokable] public void OnSpeaking(bool speaking) => SpeakingChanged?.Invoke(speaking);

    public async ValueTask DisposeAsync()
    {
        if (module is not null)
        {
            try
            {
                await module.InvokeVoidAsync("stop");
                await module.DisposeAsync();
            }
            catch (JSDisconnectedException)
            {
            }
        }
        self?.Dispose();
    }
}

/// <summary>The stage: a renderer chosen at load (MMD when a model and the MMD backend are available, else the built-in avatar).</summary>
public sealed class StageHost(IJSRuntime js, IClientHost host) : IAsyncDisposable
{
    private IJSObjectReference? module;

    private async ValueTask<IJSObjectReference> ModuleAsync() => module ??= await js.InvokeAsync<IJSObjectReference>("import", "./_content/Aijade.UI/stage.js");

    /// <returns>The renderer actually used ("mmd" or "avatar") and its asset version hash, if any.</returns>
    public async Task<JsonObject> MountAsync(string canvasId, StageSettings settings) =>
        await (await ModuleAsync()).InvokeAsync<JsonObject>("mount", canvasId, new { modelUrl = host.Resolve(settings.ModelUrl), motionUrl = host.Resolve(settings.IdleMotionUrl), background = settings.Background, transparent = settings.BackgroundImage is { Length: > 0 }, scale = settings.Scale, beatSync = settings.BeatSync, physics = settings.Physics });

    /// <summary>The stage container's CSS: the background colour, and the picture (if any) behind the transparent canvas.</summary>
    public string BackgroundStyle(StageSettings settings)
    {
        var style = $"background-color:{CssColor(settings.Background)};";
        if (settings.BackgroundImage is { Length: > 0 } image)
        {
            var url = image.StartsWith("data:", StringComparison.Ordinal) ? image : host.Resolve(image) ?? image;
            var fit = settings.BackgroundFit == "contain" ? "contain" : "cover";
            style += $"background-image:url(\"{url.Replace("\\", "%5C", StringComparison.Ordinal).Replace("\"", "%22", StringComparison.Ordinal)}\");background-size:{fit};background-position:center;background-repeat:no-repeat;";
        }
        return style;
    }

    private static string CssColor(string color) =>
        System.Text.RegularExpressions.Regex.IsMatch(color, "^#[0-9a-fA-F]{3,8}$") ? color : "#1e2230";

    /// <summary>Shrink an uploaded picture to fit maxSide and return a JPEG data: URL.</summary>
    public async Task<string> FitImageAsync(byte[] bytes, string mime, int maxSide = 1600) =>
        await (await ModuleAsync()).InvokeAsync<string>("fitImage", bytes, mime, maxSide);

    /// <summary>Apply an expression vector; returns the parameter map the renderer actually applied (the receipt's content).</summary>
    public async Task<JsonObject> ApplyAsync(Aijade.Memory.Contracts.PerformanceIntent intent) =>
        await (await ModuleAsync()).InvokeAsync<JsonObject>("apply", new
        {
            expression = intent.Expression, face = intent.Face, gaze = intent.Gaze, gesture = intent.Gesture, posture = intent.Posture, duration = intent.Duration,
        });

    public async Task MouthAsync(double open) => await (await ModuleAsync()).InvokeVoidAsync("mouth", open);

    /// <summary>A beat from the music (strength 0–1): the stage nods with it.</summary>
    public async Task BeatAsync(double strength) => await (await ModuleAsync()).InvokeVoidAsync("beat", strength);

    public async ValueTask DisposeAsync()
    {
        if (module is not null)
        {
            try
            {
                await module.InvokeVoidAsync("unmount");
                await module.DisposeAsync();
            }
            catch (JSDisconnectedException)
            {
            }
        }
    }
}

/// <summary>Plays synthesized speech and reports the output level for lip sync.</summary>
public sealed class AudioOutput(IJSRuntime js)
{
    private IJSObjectReference? module;

    public async Task PlayAsync(byte[] audio, DotNetObjectReference<LipSyncSink>? sink)
    {
        module ??= await js.InvokeAsync<IJSObjectReference>("import", "./_content/Aijade.UI/audio.js");
        await module.InvokeVoidAsync("play", audio, sink);
    }
}

public sealed class LipSyncSink(Func<double, Task> onLevel)
{
    [JSInvokable] public Task OnMouth(double level) => onLevel(level);
}

/// <summary>Screen / camera frames and attached images for the vision module (see vision.js).</summary>
public sealed class VisionCapture(IJSRuntime js) : IAsyncDisposable
{
    private IJSObjectReference? module;
    private DotNetObjectReference<VisionCapture>? self;

    /// <summary>The user stopped sharing from the browser's own controls.</summary>
    public event Action? Ended;

    private async ValueTask<IJSObjectReference> ModuleAsync() => module ??= await js.InvokeAsync<IJSObjectReference>("import", "./_content/Aijade.UI/vision.js");

    /// <summary>Start sharing; null on success, otherwise why it could not start.</summary>
    public async Task<string?> StartAsync(VisionSource source)
    {
        self ??= DotNetObjectReference.Create(this);
        return await (await ModuleAsync()).InvokeAsync<string?>("start", self, source == VisionSource.Camera ? "camera" : "screen");
    }

    public async Task<string?> GrabAsync(int maxWidth) => module is null ? null : await module.InvokeAsync<string?>("grab", maxWidth);

    public async Task<string?> DownscaleAsync(byte[] bytes, string mime, int maxWidth) => await (await ModuleAsync()).InvokeAsync<string?>("downscale", bytes, mime, maxWidth);

    public async Task StopAsync()
    {
        if (module is not null)
            await module.InvokeVoidAsync("stop");
    }

    [JSInvokable] public void OnEnded() => Ended?.Invoke();

    public async ValueTask DisposeAsync()
    {
        if (module is not null)
        {
            try
            {
                await module.InvokeVoidAsync("stop");
                await module.DisposeAsync();
            }
            catch (JSDisconnectedException)
            {
            }
        }
        self?.Dispose();
    }
}
