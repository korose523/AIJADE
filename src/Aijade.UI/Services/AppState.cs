using Aijade.Client.Api;
using Aijade.Client.I18n;
using Aijade.Client.Settings;

namespace Aijade.UI.Services;

/// <summary>Application state shared by the pages: settings, locale, the signed-in account and device identity.</summary>
public sealed class AppState(SettingsService settings, Strings strings, AijadeApi api, IKeyValueStore store)
{
    public SettingsService Settings => settings;

    public Strings Text => strings;

    public AijadeApi Api => api;

    public AccountInfo? Account { get; private set; }

    public bool Ready { get; private set; }

    /// <summary>A stable id of this installation (memory session and render origin).</summary>
    public string DeviceId { get; private set; } = "";

    public event Action? Changed;

    public async Task InitializeAsync(string? browserLanguage)
    {
        var firstRun = await store.GetAsync(AppSettings.StorageKey) is null;
        var s = await settings.LoadAsync();
        if (firstRun && browserLanguage is not null)
        {
            // First start: follow the browser language, and remember it so the settings page shows what is in use.
            s = s with { Locale = Strings.Resolve(browserLanguage) };
            await settings.SaveAsync(s);
        }
        strings.SetLocale(s.Locale);
        DeviceId = await store.GetAsync("aijade.device") ?? await NewDeviceAsync();
        try
        {
            Account = await api.SessionAsync();
        }
        catch (HttpRequestException)
        {
            Account = null;
        }
        Ready = true;
        settings.Changed += s2 =>
        {
            strings.SetLocale(s2.Locale);
            Changed?.Invoke();
        };
        Changed?.Invoke();
    }

    private async Task<string> NewDeviceAsync()
    {
        var id = $"web-{Guid.NewGuid():N}";
        await store.SetAsync("aijade.device", id);
        return id;
    }

    public void SetAccount(AccountInfo? account)
    {
        Account = account;
        capabilities = null;
        Changed?.Invoke();
    }

    private ServerCapabilities? capabilities;

    /// <summary>What the server offers beyond chat (cached per sign-in); nothing when it cannot be asked.</summary>
    public async Task<ServerCapabilities> CapabilitiesAsync()
    {
        if (capabilities is not null)
            return capabilities;
        try
        {
            return capabilities = await api.CapabilitiesAsync();
        }
        catch (Exception e) when (e is AijadeApiException or HttpRequestException)
        {
            return new ServerCapabilities([], false, false);
        }
    }

    /// <summary>The memory session of this account on this installation.</summary>
    public string MemorySessionId => Account is null ? "" : $"{Account.Id}:{DeviceId}";
}
