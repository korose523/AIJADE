using Aijade.Client.Api;

namespace Aijade.Maui.Services;

/// <summary>The server the user chose, kept in the app's preferences.</summary>
public sealed class MauiClientHost : IClientHost
{
    private const string Key = "aijade.server";

    public bool ServerConfigurable => true;

    public Uri? Server { get; private set; } = Preferences.Default.Get<string?>(Key, null) is { } saved ? ServerAddressHandler.ParseServer(saved) : null;

    public Task SetServerAsync(Uri server)
    {
        Server = server;
        Preferences.Default.Set(Key, server.ToString());
        return Task.CompletedTask;
    }

    public string? Resolve(string? url) =>
        url is null || Server is null || Uri.TryCreate(url, UriKind.Absolute, out _) ? url : new Uri(Server, url).ToString();
}

/// <summary>The session token in SecureStorage (Android Keystore / Windows DPAPI).</summary>
public sealed class SecureTokenStore : ITokenStore
{
    private const string Key = "aijade.session";

    public async ValueTask<string?> GetAsync()
    {
        try
        {
            return await SecureStorage.Default.GetAsync(Key);
        }
        catch (Exception e) when (e is not OperationCanceledException)
        {
            // A keystore that cannot be read (e.g. after a backup restore to another device) means "signed out".
            SecureStorage.Default.Remove(Key);
            return null;
        }
    }

    public async ValueTask SetAsync(string? token)
    {
        if (token is null)
            SecureStorage.Default.Remove(Key);
        else
            await SecureStorage.Default.SetAsync(Key, token);
    }
}
