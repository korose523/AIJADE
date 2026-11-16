using System.Text.Json;
using System.Text.RegularExpressions;

namespace Aijade.Growth.Adapters;

// Durable storage as one JSON file per record under <root>/<kind>/<id>.json, so interest threads, quests, claim maps,
// artefacts and journals survive restarts. The default real store when no database is configured.

public sealed partial class FileStorageAdapter(string rootDir) : IStoragePort
{
    [GeneratedRegex("[^A-Za-z0-9_.-]", RegexOptions.CultureInvariant)]
    private static partial Regex Unsafe();

    /// <summary>Keep kind / id inside one directory segment (no path traversal).</summary>
    public static string Safe(string segment)
    {
        var s = Unsafe().Replace(segment, "_");
        return s.Length > 128 ? s[..128] : s;
    }

    private string Dir(string kind) => Path.Combine(rootDir, Safe(kind));

    private string FilePath(string kind, string id) => Path.Combine(Dir(kind), $"{Safe(id)}.json");

    public async Task PutAsync<T>(string kind, string id, T value, CancellationToken cancellationToken = default)
    {
        Directory.CreateDirectory(Dir(kind));
        await File.WriteAllTextAsync(FilePath(kind, id), JsonSerializer.Serialize(value, GrowthJson.Options), cancellationToken).ConfigureAwait(false);
    }

    public async Task<T?> GetAsync<T>(string kind, string id, CancellationToken cancellationToken = default)
    {
        try
        {
            return JsonSerializer.Deserialize<T>(await File.ReadAllTextAsync(FilePath(kind, id), cancellationToken).ConfigureAwait(false), GrowthJson.Options);
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException or JsonException)
        {
            return default;
        }
    }

    public async Task<IReadOnlyList<T>> ListAsync<T>(string kind, CancellationToken cancellationToken = default)
    {
        var dir = Dir(kind);
        if (!Directory.Exists(dir))
            return [];
        var output = new List<T>();
        foreach (var file in Directory.EnumerateFiles(dir, "*.json").Order(StringComparer.Ordinal))
        {
            try
            {
                if (JsonSerializer.Deserialize<T>(await File.ReadAllTextAsync(file, cancellationToken).ConfigureAwait(false), GrowthJson.Options) is { } v)
                    output.Add(v);
            }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException or JsonException)
            {
                // Skip unreadable / corrupt entries.
            }
        }
        return output;
    }

    public async Task<IReadOnlyList<T>> QueryAsync<T>(string kind, Func<T, bool> predicate, CancellationToken cancellationToken = default) =>
        (await ListAsync<T>(kind, cancellationToken).ConfigureAwait(false)).Where(predicate).ToList();

    /// <summary>Ops / test helper: wipe one kind.</summary>
    public void ClearKind(string kind)
    {
        if (Directory.Exists(Dir(kind)))
            Directory.Delete(Dir(kind), recursive: true);
    }
}
