using System.Security.Cryptography;
using System.Text;

namespace Aijade.Tests;

internal sealed record PromptMemory(string Id, string Content);

/// <summary>
/// A test-side observation of the frozen memory provider's canonical block in a captured model request. This confirms
/// complete text visibility, not use by a model or independent truth of the source. Ambiguous sources remain unassigned.
/// </summary>
internal sealed record ProductPromptObservation(string State, bool Identifiable, bool Truncated,
    IReadOnlyList<string> FullItemIds, string? SystemSha256)
{
    public const string Header = "Things you remember about the user (use only when relevant):\n";
    public const string Marker = "\n[Truncated by the product character budget.]";

    public static ProductPromptObservation Observe(string? system, IReadOnlyList<PromptMemory> planned)
    {
        var hash = system is null ? null : Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(system)));
        ProductPromptObservation Result(string state, bool identifiable, bool truncated = false, IEnumerable<string>? ids = null) =>
            new(state, identifiable, truncated, ids?.ToArray() ?? [], hash);
        if (system is null)
            return Result("not-captured", false);
        var start = system.IndexOf(Header, StringComparison.Ordinal);
        if (start < 0)
            return Result("absent", true);
        if (system.IndexOf(Header, start + Header.Length, StringComparison.Ordinal) >= 0 || planned.Count == 0)
            return Result("unexplained-block", false);
        if (planned.Select(p => p.Id).Distinct(StringComparer.Ordinal).Count() != planned.Count ||
            planned.Select(p => p.Content).Distinct(StringComparer.Ordinal).Count() != planned.Count ||
            planned.Any(p => p.Content.Contains(Header, StringComparison.Ordinal) || p.Content.Contains(Marker, StringComparison.Ordinal)))
            return Result("ambiguous-source", false);

        var expected = Header + string.Join("\n", planned.Select(p => "- " + p.Content));
        var actual = system[start..];
        if (actual.StartsWith(expected, StringComparison.Ordinal) &&
            (actual.Length == expected.Length || actual[expected.Length] == '\n'))
            return Result("complete", true, ids: planned.Select(p => p.Id));
        var cut = actual.IndexOf(Marker, StringComparison.Ordinal);
        if (cut < 0 || cut >= expected.Length || !expected.StartsWith(actual[..cut], StringComparison.Ordinal))
            return Result("unexplained-block", false);

        var full = new List<string>();
        var end = Header.Length;
        for (var i = 0; i < planned.Count; i++)
        {
            end += (i == 0 ? 0 : 1) + 2 + planned[i].Content.Length;
            if (end <= cut)
                full.Add(planned[i].Id);
        }
        return Result("truncated", true, truncated: true, ids: full);
    }
}
