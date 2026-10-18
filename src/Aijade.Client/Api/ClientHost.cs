namespace Aijade.Client.Api;

/// <summary>
/// Where the AIJADE server is, as the host app sees it. The web app is served by its server (fixed, same origin); the
/// native apps (MAUI) let the user choose a server, so their requests go to a placeholder origin that
/// <see cref="ServerAddressHandler"/> rewrites to the current choice.
/// </summary>
public interface IClientHost
{
    /// <summary>Whether the user picks the server (native apps) or it is fixed (web app).</summary>
    bool ServerConfigurable { get; }

    /// <summary>The server's origin, e.g. https://aijade.example/ (null until a native app has been told).</summary>
    Uri? Server { get; }

    Task SetServerAsync(Uri server);

    /// <summary>A URL the user typed or stored relative to the server (e.g. "/models/x.pmx"), made absolute for this host.</summary>
    string? Resolve(string? url) =>
        url is null || Server is null || Uri.TryCreate(url, UriKind.Absolute, out _) ? url : new Uri(Server, url).ToString();
}

/// <summary>The web app: same origin as its server, nothing to configure, relative URLs already right.</summary>
public sealed class SameOriginHost(Uri origin) : IClientHost
{
    public bool ServerConfigurable => false;

    public Uri? Server => origin;

    public Task SetServerAsync(Uri server) => throw new NotSupportedException("the web app always talks to the server it was loaded from");

    public string? Resolve(string? url) => url;
}

/// <summary>Sends requests addressed to <see cref="Placeholder"/> to the host's current server instead.</summary>
public sealed class ServerAddressHandler(IClientHost host) : DelegatingHandler
{
    public static Uri Placeholder { get; } = new("https://aijade.server.invalid/");

    /// <summary>Accept only http(s) URLs with a host, normalized to their origin plus a trailing slash.</summary>
    public static Uri? ParseServer(string? text)
    {
        if (!Uri.TryCreate(text?.Trim(), UriKind.Absolute, out var uri) || uri.Scheme is not ("http" or "https") || uri.Host.Length == 0)
            return null;
        return new Uri(uri.GetLeftPart(UriPartial.Path).TrimEnd('/') + "/");
    }

    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        if (request.RequestUri is { } uri && uri.Host == Placeholder.Host)
        {
            var server = host.Server ?? throw new HttpRequestException("No AIJADE server has been set yet.");
            request.RequestUri = new Uri(server, uri.PathAndQuery.TrimStart('/'));
        }
        return base.SendAsync(request, cancellationToken);
    }
}
