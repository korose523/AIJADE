using Aijade.Client.Api;
using Aijade.Maui.Services;
using Aijade.UI.Services;

namespace Aijade.Maui;

public static class MauiProgram
{
    public static MauiApp CreateMauiApp()
    {
        var builder = MauiApp.CreateBuilder();
        builder.UseMauiApp<App>();
        builder.Services.AddMauiBlazorWebView();
#if DEBUG
        builder.Services.AddBlazorWebViewDeveloperTools();
#endif
        // The user chooses the server; requests go to a placeholder origin that the handler points at that choice.
        builder.Services.AddSingleton<IClientHost, MauiClientHost>();
        builder.Services.AddSingleton(sp => new HttpClient(new ServerAddressHandler(sp.GetRequiredService<IClientHost>()) { InnerHandler = new HttpClientHandler() })
        {
            BaseAddress = ServerAddressHandler.Placeholder,
            Timeout = TimeSpan.FromMinutes(5),
        });
        builder.Services.AddAijadeUi();
        // The session token lives in the platform's secure storage (Android Keystore), not in the web view.
        builder.Services.AddSingleton<ITokenStore, SecureTokenStore>();
        return builder.Build();
    }
}
