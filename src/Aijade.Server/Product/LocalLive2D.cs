using System.Net;

namespace Aijade.Server.Product;

/// <summary>Read-only delivery of a locally installed Live2D package to the loopback browser.</summary>
internal static class LocalLive2D
{
    public static void Map(WebApplication app, string directory)
    {
        if (!Path.IsPathFullyQualified(directory))
            throw new InvalidOperationException("Live2D:Root must be an absolute local directory.");
        var root = Path.TrimEndingDirectorySeparator(Path.GetFullPath(directory));
        if (!Directory.Exists(root) || new DirectoryInfo(root).LinkTarget is not null)
            throw new InvalidOperationException("Live2D:Root must identify an existing directory without a symbolic link.");
        app.MapGet("/_aijade/live2d/{**file}", (HttpContext context, string? file) => Read(context, root, file));
    }

    private static IResult Read(HttpContext context, string root, string? file)
    {
        var remote = context.Connection.RemoteIpAddress;
        if (remote is null || !IsLoopback(remote) || !IsLoopbackHost(context.Request.Host.Host))
            return Results.NotFound();
        var fetchSite = context.Request.Headers["Sec-Fetch-Site"].ToString();
        if (fetchSite.Length != 0 && fetchSite is not ("same-origin" or "none"))
            return Results.NotFound();
        if (context.Request.Headers.ContainsKey("Forwarded") || context.Request.Headers.ContainsKey("X-Forwarded-For"))
            return Results.NotFound();
        if (file is null || ContentType(file) is not { } type)
            return Results.NotFound();

        var path = root;
        var parts = file.Split('/');
        foreach (var part in parts)
        {
            if (part.Length == 0 || part is "." or ".." || part.Contains('\\') || part.Contains(':'))
                return Results.NotFound();
            path = Path.Combine(path, part);
            if (new FileInfo(path).LinkTarget is not null)
                return Results.NotFound();
        }
        if (!File.Exists(path))
            return Results.NotFound();
        context.Response.Headers.CacheControl = file == "active.json" ? "no-store" : "private, max-age=0";
        context.Response.Headers["Cross-Origin-Resource-Policy"] = "same-origin";
        return Results.File(path, type, lastModified: File.GetLastWriteTimeUtc(path));
    }

    private static bool IsLoopback(IPAddress address) =>
        IPAddress.IsLoopback(address.IsIPv4MappedToIPv6 ? address.MapToIPv4() : address);

    private static bool IsLoopbackHost(string host) =>
        host.Equals("localhost", StringComparison.OrdinalIgnoreCase) ||
        IPAddress.TryParse(host.Trim('[', ']'), out var address) && IsLoopback(address);

    private static string? ContentType(string file)
    {
        if (file == "active.json")
            return "application/json";
        if (file is "runtime/live2dcubismcore.min.js" or "runtime/live2d-backend.js")
            return "text/javascript";
        var extension = Path.GetExtension(file).ToLowerInvariant();
        if (file.StartsWith("runtime/shaders/", StringComparison.Ordinal) && extension is ".vert" or ".frag")
            return "text/plain";
        if (!file.StartsWith("model/", StringComparison.Ordinal))
            return null;
        return extension switch
        {
            ".json" => "application/json",
            ".moc3" => "application/octet-stream",
            ".png" => "image/png",
            ".jpg" or ".jpeg" => "image/jpeg",
            ".webp" => "image/webp",
            _ => null,
        };
    }
}
