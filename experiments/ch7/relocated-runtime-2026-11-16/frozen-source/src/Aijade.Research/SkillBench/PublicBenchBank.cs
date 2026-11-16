using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace Aijade.Research.SkillBench;

public sealed record PublicBenchEntry(
    string TaskId, string SourceTaskId, string TaskFile, string TaskSha256,
    string ReferenceFile, string ReferenceSha256, int CaseCount);

/// <summary>A materialized public benchmark whose files are bound by a manifest.</summary>
public sealed class PublicBenchBank
{
    public const string Schema = "aijade.p2a.execution-bank.v1";

    private sealed record FileIdentity(string File, string Sha256);
    private sealed record Manifest(string Schema, string AuthorReview, FileIdentity Runtime, List<PublicBenchEntry> Tasks);
    private sealed record TaskFile(string TaskId, string Statement, string Contract, List<BenchCase> Cases);

    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web);
    private static readonly UTF8Encoding Utf8 = new(false, true);
    private readonly string _directory;
    private readonly Dictionary<string, PublicBenchEntry> _byId;
    private readonly Lazy<string> _runtime;

    public string ManifestSha256 { get; }
    public string AuthorReview { get; }
    public IReadOnlyList<PublicBenchEntry> Entries { get; }

    private PublicBenchBank(string directory, string sha256, Manifest manifest)
    {
        _directory = directory;
        ManifestSha256 = sha256;
        AuthorReview = manifest.AuthorReview;
        Entries = manifest.Tasks.AsReadOnly();
        _byId = manifest.Tasks.ToDictionary(entry => entry.TaskId, StringComparer.Ordinal);
        _runtime = new Lazy<string>(() => ReadChecked(manifest.Runtime.File, manifest.Runtime.Sha256));
    }

    public static string FileSha256(string path) =>
        Convert.ToHexStringLower(SHA256.HashData(File.ReadAllBytes(path)));

    public static PublicBenchBank Load(string path, string? expectedSha256 = null)
    {
        var bytes = File.ReadAllBytes(path);
        var sha256 = Convert.ToHexStringLower(SHA256.HashData(bytes));
        if (expectedSha256 is not null && sha256 != expectedSha256)
            throw new InvalidDataException("The public-bank manifest has changed.");
        var manifest = JsonSerializer.Deserialize<Manifest>(bytes, Json)
            ?? throw new InvalidDataException("The public-bank manifest is empty.");
        if (manifest.Schema != Schema || manifest.Tasks is not { Count: > 0 }
            || manifest.Runtime is null || string.IsNullOrWhiteSpace(manifest.AuthorReview))
            throw new InvalidDataException("The public-bank schema or required fields are invalid.");
        if (manifest.Tasks.Any(entry => entry is null || string.IsNullOrWhiteSpace(entry.TaskId)
                || string.IsNullOrWhiteSpace(entry.SourceTaskId) || entry.CaseCount <= 0)
            || manifest.Tasks.Select(entry => entry.TaskId).Distinct(StringComparer.Ordinal).Count() != manifest.Tasks.Count
            || manifest.Tasks.Select(entry => entry.SourceTaskId).Distinct(StringComparer.Ordinal).Count() != manifest.Tasks.Count)
            throw new InvalidDataException("The public-bank tasks are empty or have duplicate identities.");
        return new PublicBenchBank(Path.GetDirectoryName(Path.GetFullPath(path))!, sha256, manifest);
    }

    public BenchTask ReadTask(string taskId)
    {
        var entry = Entry(taskId);
        var source = ReadChecked(entry.TaskFile, entry.TaskSha256);
        var task = JsonSerializer.Deserialize<TaskFile>(source, Json)
            ?? throw new InvalidDataException("The public task is empty.");
        if (task.TaskId != taskId || string.IsNullOrWhiteSpace(task.Statement)
            || string.IsNullOrWhiteSpace(task.Contract) || task.Cases is null || task.Cases.Count != entry.CaseCount
            || task.Cases.Any(test => test is null || test.Args is null || test.Expected is null))
            throw new InvalidDataException($"The public task does not match its manifest: {taskId}");
        return new BenchTask(taskId, task.Statement, BenchCategory.Logic, BenchTier.Medium, task.Cases, 2000)
        {
            PublicContract = task.Contract,
        };
    }

    public string ReadReference(string taskId)
    {
        var entry = Entry(taskId);
        return _runtime.Value + "\n" + ReadChecked(entry.ReferenceFile, entry.ReferenceSha256);
    }

    private PublicBenchEntry Entry(string id) => _byId.TryGetValue(id, out var entry)
        ? entry : throw new ArgumentException($"Unknown public task: {id}", nameof(id));

    private string ReadChecked(string relativePath, string expectedSha256)
    {
        if (string.IsNullOrWhiteSpace(relativePath) || Path.IsPathRooted(relativePath))
            throw new InvalidDataException("A public-bank file path must be relative.");
        var path = Path.GetFullPath(Path.Combine(_directory, relativePath));
        var prefix = Path.EndsInDirectorySeparator(_directory) ? _directory : _directory + Path.DirectorySeparatorChar;
        if (!path.StartsWith(prefix, StringComparison.Ordinal))
            throw new InvalidDataException("A public-bank file path leaves its directory.");
        var bytes = File.ReadAllBytes(path);
        if (Convert.ToHexStringLower(SHA256.HashData(bytes)) != expectedSha256)
            throw new InvalidDataException($"A public-bank file has changed: {relativePath}");
        return Utf8.GetString(bytes);
    }
}
