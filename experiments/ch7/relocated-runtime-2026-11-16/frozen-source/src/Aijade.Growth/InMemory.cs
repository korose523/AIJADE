using System.Collections.Concurrent;
using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

using Aijade.Core.Js;

namespace Aijade.Growth;

// Deterministic default adapters for tests and local runs; no external services.

/// <summary>An in-process key/value store partitioned by kind; insertion order is kept per kind.</summary>
public sealed class InMemoryStorage : IStoragePort
{
    private readonly Dictionary<string, OrderedDictionary<string, object?>> buckets = new(StringComparer.Ordinal);
    private readonly Lock gate = new();

    private OrderedDictionary<string, object?> Bucket(string kind)
    {
        if (!buckets.TryGetValue(kind, out var b))
        {
            b = new OrderedDictionary<string, object?>(StringComparer.Ordinal);
            buckets[kind] = b;
        }
        return b;
    }

    public Task PutAsync<T>(string kind, string id, T value, CancellationToken cancellationToken = default)
    {
        lock (gate)
            Bucket(kind)[id] = value;
        return Task.CompletedTask;
    }

    public Task<T?> GetAsync<T>(string kind, string id, CancellationToken cancellationToken = default)
    {
        lock (gate)
            return Task.FromResult(Bucket(kind).TryGetValue(id, out var v) ? (T?)v : default);
    }

    public Task<IReadOnlyList<T>> ListAsync<T>(string kind, CancellationToken cancellationToken = default) =>
        Task.FromResult(All<T>(kind));

    public Task<IReadOnlyList<T>> QueryAsync<T>(string kind, Func<T, bool> predicate, CancellationToken cancellationToken = default) =>
        Task.FromResult<IReadOnlyList<T>>(All<T>(kind).Where(predicate).ToList());

    /// <summary>Test helper: the whole bucket (not part of the port contract).</summary>
    public IReadOnlyList<T> All<T>(string kind)
    {
        lock (gate)
            return Bucket(kind).Values.Cast<T>().ToList();
    }
}

/// <summary>Search over a seed list: case-insensitive substring match on content or locator, optionally filtered by type.</summary>
public sealed class InMemorySearch(IEnumerable<RawHit>? seed = null) : ISearchPort
{
    private readonly List<RawHit> index = [.. seed ?? []];

    public Task<IReadOnlyList<RawHit>> SearchAsync(string query, IReadOnlyList<string> sourceTypes, CancellationToken cancellationToken = default)
    {
        var q = JsText.Lower(JsText.Trim(query));
        var types = sourceTypes.ToHashSet(StringComparer.Ordinal);
        IReadOnlyList<RawHit> hits = index.Where(hit =>
        {
            var typeOk = types.Count == 0 || types.Contains(hit.SourceType);
            var textOk = q.Length == 0 || JsText.Lower(hit.Content).Contains(q, StringComparison.Ordinal)
                || JsText.Lower(hit.Locator).Contains(q, StringComparison.Ordinal);
            return typeOk && textOk;
        }).ToList();
        return Task.FromResult(hits);
    }
}

/// <summary>
/// HMAC-style stand-in: <c>sig_{fnv1a(JSON.stringify(payload) + ":" + secret)}</c>. Enough to exercise the signing and
/// release contracts; <see cref="Adapters.CryptoSigningAdapter"/> is the real scheme.
/// </summary>
public sealed class InMemorySigning(string secret = "aijade-growth-inmemory-secret") : ISigningPort
{
    public string Sign(JsonNode payload) => $"sig_{GrowthUtil.Fnv1a($"{JsFormat.Stringify(payload)}:{secret}")}";

    public bool Verify(JsonNode payload, string signature) => Sign(payload) == signature;
}

/// <summary>A clock plus named budgets; an unregistered scope is unlimited so tests without budgets never stall.</summary>
public sealed class InMemoryScheduler(IReadOnlyDictionary<string, double>? budgets = null, TimeProvider? time = null) : ISchedulerPort
{
    private readonly ConcurrentDictionary<string, double> budgets = new(budgets ?? new Dictionary<string, double>(), StringComparer.Ordinal);
    private readonly ConcurrentDictionary<string, bool> unlimited = new(StringComparer.Ordinal);
    private readonly TimeProvider time = time ?? TimeProvider.System;
    private readonly Lock gate = new();

    public void MarkUnlimited(string scope) => unlimited[scope] = true;

    public double Now() => time.GetUtcNow().ToUnixTimeMilliseconds();

    public bool ConsumeBudget(string scope, double amount)
    {
        lock (gate)
        {
            if (unlimited.ContainsKey(scope) || !budgets.TryGetValue(scope, out var remaining))
                return true;
            if (remaining < amount)
                return false;
            budgets[scope] = remaining - amount;
            return true;
        }
    }
}

/// <summary>A scheduler pinned to a fixed clock, with an all-or-nothing budget policy.</summary>
public sealed class FixedScheduler(double now = 1_700_000_000_000, bool allowBudget = true) : ISchedulerPort
{
    public double Time { get; set; } = now;

    public double Now() => Time;

    public bool ConsumeBudget(string scope, double amount) => allowBudget;
}

/// <summary>Deterministic stub LLM: a stable acknowledgement, or a test-supplied handler.</summary>
public sealed partial class StubLlm : ILlmPort
{
    public Func<string, string>? Handler { get; set; }

    [GeneratedRegex("[" + JsText.SpaceChars + "]+", RegexOptions.CultureInvariant)]
    private static partial Regex Whitespace();

    public Task<string> CompleteAsync(string prompt, CancellationToken cancellationToken = default)
    {
        if (Handler is { } h)
            return Task.FromResult(h(prompt));
        var preview = JsText.Trim(Whitespace().Replace(prompt.Length > 64 ? prompt[..64] : prompt, " "));
        return Task.FromResult($"[stub-completion] acknowledged: {preview}");
    }
}

public static class DefaultPorts
{
    /// <summary>A ready-to-inject in-memory bundle for tests and local runs.</summary>
    public static GrowthPorts Create(IEnumerable<RawHit>? searchSeed = null, IReadOnlyDictionary<string, double>? budgets = null, ILlmPort? llm = null) =>
        new(new InMemoryStorage(), new InMemoryScheduler(budgets), new InMemorySearch(searchSeed), new InMemorySigning(), llm ?? new StubLlm());
}
