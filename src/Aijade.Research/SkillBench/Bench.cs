using System.Reflection;
using System.Text.Json;

using Aijade.Core.Random;

namespace Aijade.Research.SkillBench;

// The 44 deterministic RQ-C tasks over 7
// categories, the reference solutions and the deliberately wrong candidates. The data is fixed:
// test arguments and expected values are kept as JavaScript literal source (JSON cannot express undefined, ±Infinity,
// NaN or -0), and the reference solutions are exact source strings.

#pragma warning disable CA1720 // The member names are the category wire names.
public enum BenchCategory
{
    String,
    Array,
    Object,
    Math,
    Date,
    Parsing,
    Logic,
}
#pragma warning restore CA1720

public enum BenchTier
{
    Easy,
    Medium,
    Hard,
}

/// <summary>One deterministic case: arguments and expected value as JavaScript literal source.</summary>
public sealed record BenchCase(string Args, string Expected);

public sealed record BenchTask(string Id, string Instruction, BenchCategory Category, BenchTier Tier, IReadOnlyList<BenchCase> Tests, int? TimeoutMs = null);

public static class Bench
{
    private sealed record Raw(List<RawTask> Tasks, Dictionary<string, string> References, List<string> Wrong);

    private sealed record RawTask(string Id, string Instruction, string Category, string Tier, int? TimeoutMs, List<BenchCase> Tests);

    private static readonly JsonSerializerOptions WebJson = new(JsonSerializerDefaults.Web);

    private static readonly Lazy<Raw> Data = new(() =>
    {
        using var s = typeof(Bench).Assembly.GetManifestResourceStream("Aijade.Research.SkillBench.bench-data.json")
            ?? throw new InvalidOperationException("bench-data.json resource missing");
        return JsonSerializer.Deserialize<Raw>(s, WebJson)!;
    });

    /// <summary>The 44 tasks, in benchmark order.</summary>
    public static IReadOnlyList<BenchTask> Tasks { get; } = Data.Value.Tasks
        .Select(t => new BenchTask(t.Id, t.Instruction, Enum.Parse<BenchCategory>(t.Category, true), Enum.Parse<BenchTier>(t.Tier, true), t.Tests, t.TimeoutMs)).ToList();

    /// <summary>The correct implementation of each task, as source defining <c>solve</c>.</summary>
    public static IReadOnlyDictionary<string, string> ReferenceSolutions => Data.Value.References;

    /// <summary>Runnable but deliberately wrong candidates; none passes any task.</summary>
    public static IReadOnlyList<string> WrongCandidates => Data.Value.Wrong;

    /// <summary>A seeded partial Fisher–Yates shuffle: the same (n, seed) always gives the same subset, in order.</summary>
    public static IReadOnlyList<BenchTask> SampleTasks(int n, uint seed)
    {
        var pool = Tasks.ToArray();
        var count = Math.Max(0, Math.Min(n, pool.Length));
        var rng = new Mulberry32(seed);
        for (var i = 0; i < count; i++)
        {
            var j = i + (int)Math.Floor(rng.Next() * (pool.Length - i));
            (pool[i], pool[j]) = (pool[j], pool[i]);
        }
        return pool[..count];
    }

    /// <summary>The first ```js / ```javascript fenced block (trailing whitespace trimmed), else the whole text.</summary>
    public static string? ExtractCodeBlock(string? markdown)
    {
        if (markdown is null)
            return null;
        var m = Fenced.Match(markdown);
        return m.Success ? m.Groups[1].Value.TrimEnd() : markdown;
    }

    private static readonly System.Text.RegularExpressions.Regex Fenced = new(@"```\s*(?:js|javascript)[ \t]*\r?\n([\s\S]*?)```",
        System.Text.RegularExpressions.RegexOptions.IgnoreCase | System.Text.RegularExpressions.RegexOptions.CultureInvariant);
}
