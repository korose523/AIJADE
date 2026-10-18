using Aijade.Client.Api;
using Aijade.Client.I18n;
using Aijade.Client.Settings;

using Microsoft.Extensions.DependencyInjection;

namespace Aijade.UI.Services;

public static class ServiceRegistration
{
    /// <summary>
    /// Everything the shared UI needs; the host supplies the HttpClient (base address = the AIJADE server). Services that
    /// reach JavaScript are scoped: in a BlazorWebView (the native apps) the JS runtime belongs to the web view's scope, and
    /// a singleton would capture one that is attached to nothing. In WebAssembly there is one scope, so this is the same as
    /// a singleton there.
    /// </summary>
    public static IServiceCollection AddAijadeUi(this IServiceCollection services)
    {
        services.AddScoped<IKeyValueStore, BrowserKeyValueStore>();
        services.AddScoped<ITokenStore, BrowserTokenStore>();
        services.AddScoped<AijadeApi>();
        services.AddScoped<SettingsService>();
        services.AddScoped<Strings>();
        services.AddScoped<AppState>();
        services.AddScoped<BrowserTelemetryStorage>();
        services.AddScoped<AgentCapabilitiesHost>();
        services.AddScoped<VoiceInput>();
        services.AddScoped<VisionCapture>();
        services.AddScoped<VisionSession>();
        services.AddScoped<BeatSyncSession>();
        services.AddScoped<AudioOutput>();
        services.AddTransient<StageHost>();
        return services;
    }
}
