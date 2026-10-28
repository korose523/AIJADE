using System.Text.Json;
using System.Text.Json.Nodes;

namespace Aijade.Client.Settings;

// User settings of the companion apps, stored as one JSON document in a platform key-value store (browser localStorage,
// MAUI preferences, a file). Unknown or malformed stored documents fall back to defaults instead of breaking the app.

public interface IKeyValueStore
{
    ValueTask<string?> GetAsync(string key);

    ValueTask SetAsync(string key, string value);

    ValueTask RemoveAsync(string key);
}

public sealed class InMemoryKeyValueStore : IKeyValueStore
{
    private readonly Dictionary<string, string> values = new(StringComparer.Ordinal);

    public ValueTask<string?> GetAsync(string key) => ValueTask.FromResult(values.TryGetValue(key, out var v) ? v : null);

    public ValueTask SetAsync(string key, string value)
    {
        values[key] = value;
        return ValueTask.CompletedTask;
    }

    public ValueTask RemoveAsync(string key)
    {
        values.Remove(key);
        return ValueTask.CompletedTask;
    }
}

public sealed record VoiceSettings
{
    public string? InputDeviceId { get; init; }

    /// <summary>Hands-free: speech is detected by voice-activity detection.</summary>
    public bool VadEnabled { get; init; } = true;

    /// <summary>Energy threshold of the detector, 0..1.</summary>
    public double VadThreshold { get; init; } = 0.02;

    /// <summary>Push-to-talk key (KeyboardEvent.code), used when hands-free is off.</summary>
    public string PushToTalkKey { get; init; } = "Space";

    /// <summary>Send the transcript as soon as speech ends.</summary>
    public bool AutoSend { get; init; } = true;

    /// <summary>
    /// Recognition backend: "auto" (the browser's own when it has one, else the server), "browser" (Web Speech) or
    /// "server" (each utterance is recorded and transcribed by the server's speech-recognition route).
    /// </summary>
    public string Recognition { get; init; } = "auto";

    public bool SpeakReplies { get; init; } = true;

    public string TtsVoice { get; init; } = "alloy";

    public bool LipSync { get; init; } = true;
}

public sealed record StageSettings
{
    /// <summary>The MMD model (PMX / PMD) URL; none by default — models are supplied by the user under their own licence.</summary>
    public string? ModelUrl { get; init; }

    public string? IdleMotionUrl { get; init; }

    public string Background { get; init; } = "#1e2230";

    /// <summary>A background picture behind the model: an http(s) URL, a path on the server, or a data: URL of an uploaded image.</summary>
    public string? BackgroundImage { get; init; }

    /// <summary>How the picture fills the stage: "cover" (crop to fill) or "contain" (show it whole).</summary>
    public string BackgroundFit { get; init; } = "cover";

    /// <summary>Saved scenes (background colour, picture, fit and zoom), applied with one click.</summary>
    public IReadOnlyList<StageScene> Scenes { get; init; } = [];

    public double Scale { get; init; } = 1;

    public bool BeatSync { get; init; }

    /// <summary>Hair and cloth physics for MMD models (Bullet in WebAssembly).</summary>
    public bool Physics { get; init; } = true;
}

/// <summary>A named stage arrangement.</summary>
public sealed record StageScene(string Name, string Background, string? BackgroundImage, string BackgroundFit, double Scale)
{
    public static StageScene From(string name, StageSettings s) => new(name, s.Background, s.BackgroundImage, s.BackgroundFit, s.Scale);

    public StageSettings ApplyTo(StageSettings s) => s with { Background = Background, BackgroundImage = BackgroundImage, BackgroundFit = BackgroundFit, Scale = Scale };
}

public sealed record ModuleSettings
{
    public bool Memory { get; init; } = true;

    public bool Learning { get; init; } = true;

    public bool Hearing { get; init; } = true;

    public bool Speech { get; init; } = true;

    public bool Vision { get; init; }

    /// <summary>
    /// When the chat has gone quiet, the companion may speak first, under the rule of the companion contract shared with MOSAIC
    /// (night hours, a request for quiet, goodbyes, unanswered lines, cooldown and an hourly budget hold her back). Off by default.
    /// </summary>
    public bool SpeakFirst { get; init; }

    /// <summary>
    /// MOSAIC's home as her stage (docs/STAGE-MOSAIC.md): while the owner's workbench runs a scene, each reply is said there
    /// and her body goes where the user's words send her (the companion contract's stage rules); her voice here stays silent.
    /// Needs a server with Stage:WorkbenchUrl and an admin account; without them the chat goes on as usual. Off by default.
    /// </summary>
    public bool MosaicStage { get; init; }

    /// <summary>Let the companion see what the browser extension reports you are reading or watching.</summary>
    public bool BrowserContext { get; init; }

    /// <summary>Let the companion see what the VS Code extension reports you are working on.</summary>
    public bool IdeContext { get; init; }

    /// <summary>Drawing: the companion may answer with a picture (costs flux when the server prices images).</summary>
    public bool Artistry { get; init; }

    public bool Mcp { get; init; }

    public bool Gaming { get; init; }

    public bool Discord { get; init; }

    public bool X { get; init; }
}

public sealed record VisionCaptureSettings
{
    /// <summary>Gateway model alias that can read images; empty = the chat model.</summary>
    public string Model { get; init; } = "";

    /// <summary>Seconds between looks while the screen or camera is shared.</summary>
    public int IntervalSeconds { get; init; } = 30;

    /// <summary>Frames are scaled down to this width before they leave the device.</summary>
    public int MaxWidth { get; init; } = 1024;
}

public sealed record AppSettings
{
    public const string StorageKey = "aijade.settings.v1";

    public string Locale { get; init; } = "en";

    /// <summary>system | light | dark</summary>
    public string Theme { get; init; } = "system";

    public string Model { get; init; } = "aijade-chat";

    public double? Temperature { get; init; }

    public string? ActiveCharacterId { get; init; }

    /// <summary>Record conversations to long-term memory.</summary>
    public bool RecordConversations { get; init; } = true;

    public VoiceSettings Voice { get; init; } = new();

    public StageSettings Stage { get; init; } = new();

    public ModuleSettings Modules { get; init; } = new();

    public VisionCaptureSettings VisionCapture { get; init; } = new();

    /// <summary>Consent to record research telemetry (persona trajectory, no message text) on this device. Off by default.</summary>
    public bool ResearchConsent { get; init; }

    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web) { WriteIndented = true };

    public string ToJson() => JsonSerializer.Serialize(this, Json);

    public static AppSettings FromJson(string? json)
    {
        if (string.IsNullOrWhiteSpace(json))
            return new AppSettings();
        try
        {
            return JsonSerializer.Deserialize<AppSettings>(json, Json) ?? new AppSettings();
        }
        catch (JsonException)
        {
            return new AppSettings();
        }
    }
}

/// <summary>Loads and saves settings, and notifies subscribers when they change.</summary>
public sealed class SettingsService(IKeyValueStore store)
{
    public AppSettings Current { get; private set; } = new();

    public event Action<AppSettings>? Changed;

    public async Task<AppSettings> LoadAsync()
    {
        Current = AppSettings.FromJson(await store.GetAsync(AppSettings.StorageKey).ConfigureAwait(false));
        return Current;
    }

    public async Task SaveAsync(AppSettings settings)
    {
        Current = settings;
        await store.SetAsync(AppSettings.StorageKey, settings.ToJson()).ConfigureAwait(false);
        Changed?.Invoke(settings);
    }

    public Task UpdateAsync(Func<AppSettings, AppSettings> change) => SaveAsync(change(Current));

    public async Task ResetAsync()
    {
        await store.RemoveAsync(AppSettings.StorageKey).ConfigureAwait(false);
        Current = new AppSettings();
        Changed?.Invoke(Current);
    }

    /// <summary>The settings as an exportable document (no secrets are kept in settings).</summary>
    public JsonObject Export() => new() { ["format"] = "aijade.export.v1", ["settings"] = JsonNode.Parse(Current.ToJson()) };

    public async Task ImportAsync(JsonObject document)
    {
        if (document["format"]?.GetValue<string>() != "aijade.export.v1" || document["settings"] is not JsonObject s)
            throw new FormatException("not an AIJADE export");
        await SaveAsync(AppSettings.FromJson(s.ToJsonString())).ConfigureAwait(false);
    }
}
