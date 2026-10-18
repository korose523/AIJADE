using System.Globalization;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Core.Js;

namespace Aijade.Growth;

// The growth services never touch the outside world directly: they depend only on these small ports. Concrete adapters
// (in-memory for tests, file / HMAC / wall-clock / LLM adapters for real runs) are injected, keeping the services pure,
// deterministic and testable against stubs.

/// <summary>A raw hit returned by a search adapter (untrusted external content).</summary>
/// <param name="Locator">URL, DOI, local path or tool result ref.</param>
/// <param name="SourceType">Coarse source type (official_doc | paper | news | code | social | tool | …).</param>
/// <param name="Content">The fetched body, used to derive a content hash.</param>
/// <param name="FetchedAt">Epoch ms when the hit was fetched.</param>
public sealed record RawHit(string Locator, string SourceType, string Content, double FetchedAt);

/// <summary>External search / retrieval. Returns untrusted content to be quarantined.</summary>
public interface ISearchPort
{
    Task<IReadOnlyList<RawHit>> SearchAsync(string query, IReadOnlyList<string> sourceTypes, CancellationToken cancellationToken = default);
}

/// <summary>Generic persistence partitioned by kind. The product layer never assumes a concrete store.</summary>
public interface IStoragePort
{
    Task PutAsync<T>(string kind, string id, T value, CancellationToken cancellationToken = default);

    /// <summary>The value stored under kind / id, or default when absent.</summary>
    Task<T?> GetAsync<T>(string kind, string id, CancellationToken cancellationToken = default);

    Task<IReadOnlyList<T>> ListAsync<T>(string kind, CancellationToken cancellationToken = default);

    Task<IReadOnlyList<T>> QueryAsync<T>(string kind, Func<T, bool> predicate, CancellationToken cancellationToken = default);
}

/// <summary>Detached signatures over a JSON payload (evolution proposals, releases).</summary>
public interface ISigningPort
{
    string Sign(JsonNode payload);

    bool Verify(JsonNode payload, string signature);
}

/// <summary>Time and budget control.</summary>
public interface ISchedulerPort
{
    /// <summary>Current epoch-ms clock.</summary>
    double Now();

    /// <summary>Draw <paramref name="amount"/> from the named budget; false when insufficient.</summary>
    bool ConsumeBudget(string scope, double amount);
}

/// <summary>LLM surface for planning / synthesis (a stub in tests).</summary>
public interface ILlmPort
{
    Task<string> CompleteAsync(string prompt, CancellationToken cancellationToken = default);
}

/// <summary>Produces readable unique ids.</summary>
public interface IIdGenerator
{
    string NewId(string prefix);
}

/// <summary>
/// The id scheme <c>{prefix}_{now base36}_{counter base36}_{random base36}</c>. The clock and random source are
/// injectable, so a run with a frozen clock and fixed random value reproduces the same ids exactly.
/// </summary>
public sealed class GrowthIds(Func<double>? clockMs = null, Func<double>? random = null) : IIdGenerator
{
    private readonly Func<double> clockMs = clockMs ?? (() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
    private readonly Func<double> random = random ?? Random.Shared.NextDouble;
    private long counter;

    /// <summary>A process-wide generator on the wall clock.</summary>
    public static GrowthIds Shared { get; } = new();

    public string NewId(string prefix)
    {
        var n = Interlocked.Increment(ref counter);
        var t = (long)clockMs();
        var r = (long)Math.Floor(random() * 0xFFFFFF);
        return $"{prefix}_{GrowthUtil.Base36(t)}_{GrowthUtil.Base36(n)}_{GrowthUtil.Base36(r)}";
    }
}

/// <summary>The bundle of ports a service may need. Services use only the subset they need.</summary>
/// <param name="Storage">Persistence.</param>
/// <param name="Scheduler">Clock and budgets.</param>
/// <param name="Search">External search (acquirer, loop).</param>
/// <param name="Signing">Signatures (evolution, release).</param>
/// <param name="Llm">Optional LLM; when present the acquirer distils a brief.</param>
/// <param name="Ids">Id generator; defaults to <see cref="GrowthIds.Shared"/>.</param>
/// <param name="TimeZone">Zone for local dates and quiet hours; defaults to the machine's local zone.</param>
public sealed record GrowthPorts(
    IStoragePort Storage, ISchedulerPort Scheduler, ISearchPort? Search = null, ISigningPort? Signing = null, ILlmPort? Llm = null,
    IIdGenerator? Ids = null, TimeZoneInfo? TimeZone = null)
{
    internal IIdGenerator IdGen => Ids ?? GrowthIds.Shared;

    internal TimeZoneInfo Zone => TimeZone ?? TimeZoneInfo.Local;

    internal ISearchPort RequireSearch => Search ?? throw new InvalidOperationException("this service needs a search port");

    internal ISigningPort RequireSigning => Signing ?? throw new InvalidOperationException("this service needs a signing port");
}

public static class GrowthUtil
{
    /// <summary>Non-negative integer in base 36, as <c>Number.prototype.toString(36)</c>.</summary>
    public static string Base36(long value)
    {
        if (value == 0)
            return "0";
        const string digits = "0123456789abcdefghijklmnopqrstuvwxyz";
        var sb = new StringBuilder();
        var neg = value < 0;
        var v = Math.Abs(value);
        while (v > 0)
        {
            sb.Insert(0, digits[(int)(v % 36)]);
            v /= 36;
        }
        return neg ? "-" + sb : sb.ToString();
    }

    /// <summary>The local date of an epoch-ms instant as YYYY-MM-DD.</summary>
    public static string TodayIso(double nowMs, TimeZoneInfo? zone = null)
    {
        var local = TimeZoneInfo.ConvertTime(DateTimeOffset.FromUnixTimeMilliseconds((long)nowMs), zone ?? TimeZoneInfo.Local);
        return local.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);
    }

    /// <summary>Local hour of an epoch-ms instant.</summary>
    public static int LocalHour(double nowMs, TimeZoneInfo? zone = null) =>
        TimeZoneInfo.ConvertTime(DateTimeOffset.FromUnixTimeMilliseconds((long)nowMs), zone ?? TimeZoneInfo.Local).Hour;

    /// <summary>FNV-1a 32-bit over UTF-16 code units (hex).</summary>
    public static string Fnv1a(string input) => JsFormat.Fnv1a(input);

    /// <summary>Short content hash used to de-duplicate reposts.</summary>
    public static string ContentHashOf(string content) => $"h_{Fnv1a(content)}";
}
