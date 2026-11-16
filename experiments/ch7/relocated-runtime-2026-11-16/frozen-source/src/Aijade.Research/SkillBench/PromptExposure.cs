using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;

using Aijade.Research.RqC;

namespace Aijade.Research.SkillBench;

public sealed record InputOnlyCase(int Index, string Args, string Sha256);
public sealed record InputOnlyTask(string TaskId, string Instruction, int CaseCount, string InputSha256, IReadOnlyList<InputOnlyCase> Cases);
public sealed record ExposureScenario(string Id, int ContextTokens, int GenerationReplyTokens, int VerificationReplyTokens,
    int MaxVisibleCases, int MaxInputTokens);
public sealed record ExposureTask(string TaskId, int CaseCount, string InputSha256, IReadOnlyList<int> SelectedCaseIndices);

/// <summary>A presentation-only selection. It never replaces the execution task's tests.</summary>
public sealed class PromptExposure
{
    public const string Schema = "aijade.p2a.prompt-exposure.v1";
    public const string WholeTaskSchema = "aijade.p2a.prompt-exposure.v2";
    private sealed record Payload(string Schema, string BankManifestSha256, ExposureScenario Scenario,
        Dictionary<string, string> ModelManifestSha256ByName, List<ExposureTask> Tasks, string? VerifierInstructionVersion = null);

    private static readonly JsonSerializerOptions Json = new(JsonSerializerDefaults.Web)
    {
        UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow,
    };
    private readonly Dictionary<string, ExposureTask> _tasks;

    public string Sha256 { get; }
    public string BankManifestSha256 { get; }
    public ExposureScenario Scenario { get; }
    public IReadOnlyDictionary<string, string> ModelManifestSha256ByName { get; }
    public string VerifierInstructionVersion { get; }

    private PromptExposure(string sha256, Payload data)
    {
        Sha256 = sha256;
        BankManifestSha256 = data.BankManifestSha256;
        Scenario = data.Scenario;
        VerifierInstructionVersion = data.VerifierInstructionVersion ?? VerifierInstructions.Legacy;
        ModelManifestSha256ByName = data.ModelManifestSha256ByName.AsReadOnly();
        _tasks = data.Tasks.ToDictionary(row => row.TaskId,
            row => row with { SelectedCaseIndices = Array.AsReadOnly(row.SelectedCaseIndices.ToArray()) }, StringComparer.Ordinal);
    }

    public static string Hash(string text) => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(text)));

    public static InputOnlyTask Describe(BenchTask task)
    {
        ArgumentNullException.ThrowIfNull(task);
        var cases = task.Tests.Select((test, i) => new InputOnlyCase(i, test.Args, Hash(test.Args))).ToArray();
        var identity = Hash(Hash(task.ModelInstruction) + "\n" + string.Join("\n", cases.Select(test => test.Sha256)) + "\n");
        return new InputOnlyTask(task.Id, task.ModelInstruction, cases.Length, identity, cases);
    }

    public static PromptExposure Load(string path, PublicBenchBank bank, string? expectedSha256 = null)
    {
        ArgumentNullException.ThrowIfNull(bank);
        return Load(path, bank.ManifestSha256, bank.Entries.Select(entry => bank.ReadTask(entry.TaskId)).ToArray(), expectedSha256);
    }

    /// <summary>The caller supplies a complete independently frozen task bank; the original calling rules are retained.</summary>
    public static PromptExposure Load(string path, string bankManifestSha256, IReadOnlyList<BenchTask> tasks, string? expectedSha256 = null)
    {
        ArgumentNullException.ThrowIfNull(tasks);
        var sha256 = PublicBenchBank.FileSha256(path);
        if (expectedSha256 is not null && sha256 != expectedSha256)
            throw new InvalidDataException("The prompt-exposure file has changed.");
        var data = JsonSerializer.Deserialize<Payload>(File.ReadAllBytes(path), Json)
            ?? throw new InvalidDataException("The prompt exposure is empty.");
        var versionValid = data.Schema == Schema && data.VerifierInstructionVersion is null
            || data.Schema == WholeTaskSchema && data.VerifierInstructionVersion == VerifierInstructions.WholeTask;
        if (!versionValid || !IsHash(bankManifestSha256) || data.BankManifestSha256 != bankManifestSha256 || data.Scenario is null
            || tasks.Count == 0 || tasks.Select(task => task.Id).Distinct(StringComparer.Ordinal).Count() != tasks.Count
            || data.Tasks is null || data.Tasks.Count != tasks.Count || data.ModelManifestSha256ByName is not { Count: 2 }
            || data.ModelManifestSha256ByName.Any(pair => string.IsNullOrWhiteSpace(pair.Key) || !IsHash(pair.Value)))
            throw new InvalidDataException("The exposure schema, bank, task population or model identities do not match.");
        var expected = data.Scenario.Id switch
        {
            "compact4k" => new ExposureScenario("compact4k", 4096, 2048, 256, 3, 512),
            "compact8k" => new ExposureScenario("compact8k", 8192, 4096, 256, 3, 512),
            _ => throw new InvalidDataException("Unknown exposure scenario."),
        };
        if (data.Scenario != expected || data.Tasks.Any(row => row is null || string.IsNullOrWhiteSpace(row.TaskId)
            || row.SelectedCaseIndices is null || !IsHash(row.InputSha256))
            || data.Tasks.Select(row => row.TaskId).Distinct(StringComparer.Ordinal).Count() != data.Tasks.Count)
            throw new InvalidDataException("The exposure scenario or task identities are invalid.");
        var result = new PromptExposure(sha256, data);
        foreach (var task in tasks)
            result.ForTask(task);
        return result;
    }

    public IReadOnlyList<int> ForTask(BenchTask task)
    {
        if (!_tasks.TryGetValue(task.Id, out var row) || row.CaseCount != task.Tests.Count
            || row.InputSha256 != Describe(task).InputSha256 || row.SelectedCaseIndices.Count > Scenario.MaxVisibleCases)
            throw new InvalidDataException($"The exposure task/input identity does not match: {task.Id}");
        ValidateIndices(task, row.SelectedCaseIndices);
        return row.SelectedCaseIndices;
    }

    public static void ValidateIndices(BenchTask task, IReadOnlyList<int> indices)
    {
        ArgumentNullException.ThrowIfNull(task);
        ArgumentNullException.ThrowIfNull(indices);
        if (indices.Any(index => index < 0 || index >= task.Tests.Count)
            || !indices.SequenceEqual(indices.Distinct().Order()))
            throw new InvalidDataException("Visible case indices must be ordered, unique and inside the original task.");
    }

    internal static bool IsHash(string? text) => text is { Length: 64 } && text.All(c => c is >= '0' and <= '9' or >= 'a' and <= 'f');
}
