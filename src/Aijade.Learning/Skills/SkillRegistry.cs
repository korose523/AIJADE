using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;

namespace Aijade.Learning.Skills;


/// <summary>Narrow persistence port (upsert / get / all), so a SQL store can replace JSONL without touching callers.</summary>
public interface ISkillStore
{
    Task UpsertAsync(SkillRecord record, CancellationToken cancellationToken = default);

    Task<SkillRecord?> GetAsync(string skillId, CancellationToken cancellationToken = default);

    Task<IReadOnlyList<SkillRecord>> AllAsync(CancellationToken cancellationToken = default);

    /// <summary>Replace the whole store (tests and pilot-run resets).</summary>
    Task ReplaceAllAsync(IEnumerable<SkillRecord> records, CancellationToken cancellationToken = default);

    Task ClearAsync(CancellationToken cancellationToken = default);
}

/// <summary>Insertion-ordered in-memory store; records are immutable, so no defensive copies are needed.</summary>
public sealed class MemorySkillStore(IEnumerable<SkillRecord>? initial = null) : ISkillStore
{
    private readonly OrderedDictionary<string, SkillRecord> _map = new((initial ?? []).Select(r => KeyValuePair.Create(r.SkillId, r)), StringComparer.Ordinal);
    private readonly Lock _gate = new();

    public Task UpsertAsync(SkillRecord record, CancellationToken cancellationToken = default)
    {
        lock (_gate)
            _map[record.SkillId] = record;
        return Task.CompletedTask;
    }

    public Task<SkillRecord?> GetAsync(string skillId, CancellationToken cancellationToken = default)
    {
        lock (_gate)
            return Task.FromResult(_map.GetValueOrDefault(skillId));
    }

    public Task<IReadOnlyList<SkillRecord>> AllAsync(CancellationToken cancellationToken = default)
    {
        lock (_gate)
            return Task.FromResult<IReadOnlyList<SkillRecord>>([.. _map.Values]);
    }

    public Task ReplaceAllAsync(IEnumerable<SkillRecord> records, CancellationToken cancellationToken = default)
    {
        lock (_gate)
        {
            _map.Clear();
            foreach (var r in records)
                _map[r.SkillId] = r;
        }
        return Task.CompletedTask;
    }

    public Task ClearAsync(CancellationToken cancellationToken = default)
    {
        lock (_gate)
            _map.Clear();
        return Task.CompletedTask;
    }
}

/// <summary>
/// One JSON record per line, the last revision per id kept (the file is rewritten on upsert); writes are serialized.
/// The field names and kebab-case enum values are the stored file format.
/// </summary>
public sealed class JsonlSkillStore(string file) : ISkillStore, IDisposable
{
    public static JsonSerializerOptions JsonOptions { get; } = new(JsonSerializerDefaults.Web)
    {
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        Converters = { new JsonStringEnumConverter(JsonNamingPolicy.KebabCaseLower) },
    };

    private readonly SemaphoreSlim _writeLock = new(1, 1);

    public void Dispose() => _writeLock.Dispose();

    private async Task<List<SkillRecord>> ReadAllAsync(CancellationToken ct)
    {
        if (!File.Exists(file))
            return [];
        var lines = await File.ReadAllLinesAsync(file, ct).ConfigureAwait(false);
        return lines.Where(l => l.Trim().Length > 0).Select(l => JsonSerializer.Deserialize<SkillRecord>(l, JsonOptions)!).ToList();
    }

    private async Task WriteAllAsync(IEnumerable<SkillRecord> records, CancellationToken ct)
    {
        if (Path.GetDirectoryName(Path.GetFullPath(file)) is { } dir)
            Directory.CreateDirectory(dir);
        await File.WriteAllTextAsync(file, string.Concat(records.Select(r => JsonSerializer.Serialize(r, JsonOptions) + "\n")), ct).ConfigureAwait(false);
    }

    private async Task Serialized(Func<Task> task, CancellationToken ct)
    {
        await _writeLock.WaitAsync(ct).ConfigureAwait(false);
        try
        {
            await task().ConfigureAwait(false);
        }
        finally
        {
            _writeLock.Release();
        }
    }

    public Task UpsertAsync(SkillRecord record, CancellationToken cancellationToken = default) => Serialized(async () =>
    {
        var all = await ReadAllAsync(cancellationToken).ConfigureAwait(false);
        var idx = all.FindIndex(r => r.SkillId == record.SkillId);
        if (idx >= 0)
            all[idx] = record;
        else
            all.Add(record);
        await WriteAllAsync(all, cancellationToken).ConfigureAwait(false);
    }, cancellationToken);

    public async Task<SkillRecord?> GetAsync(string skillId, CancellationToken cancellationToken = default) =>
        (await ReadAllAsync(cancellationToken).ConfigureAwait(false)).Find(r => r.SkillId == skillId);

    public async Task<IReadOnlyList<SkillRecord>> AllAsync(CancellationToken cancellationToken = default) => await ReadAllAsync(cancellationToken).ConfigureAwait(false);

    public Task ReplaceAllAsync(IEnumerable<SkillRecord> records, CancellationToken cancellationToken = default) =>
        Serialized(() => WriteAllAsync(records.ToList(), cancellationToken), cancellationToken);

    public Task ClearAsync(CancellationToken cancellationToken = default) => Serialized(() => WriteAllAsync([], cancellationToken), cancellationToken);
}

public sealed record CreateSkillOptions(
    string Name, SkillDomain Domain, string? Body = null, SkillTrigger? Trigger = null, SelfVerification? SelfVerification = null,
    EnvFeedback? EnvFeedback = null, JsonObject? Metadata = null, string? SkillId = null);

public sealed class SkillNotFoundException(string skillId) : Exception($"Skill {skillId} not found");

/// <summary>Thrown when an execution verdict would be recorded for a domain with no environmental oracle.</summary>
public sealed class NoOracleException(string message) : Exception(message);

/// <summary>A skill registry with a lifecycle (active → retired / rejected), usage counters and ground-truth executions.</summary>
public sealed class SkillRegistry(ISkillStore? store = null, Func<double>? now = null)
{
    private readonly ISkillStore _store = store ?? new MemorySkillStore();
    private readonly Func<double> _now = now ?? (() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());

    public ISkillStore Store => _store;

    private async Task<SkillRecord> MutateAsync(string skillId, Func<SkillRecord, SkillRecord> fn, CancellationToken ct)
    {
        var existing = await _store.GetAsync(skillId, ct).ConfigureAwait(false) ?? throw new SkillNotFoundException(skillId);
        var updated = fn(existing);
        await _store.UpsertAsync(updated, ct).ConfigureAwait(false);
        return updated;
    }

    public async Task<SkillRecord> CreateAsync(CreateSkillOptions o, CancellationToken cancellationToken = default)
    {
        var record = new SkillRecord(o.SkillId ?? Guid.NewGuid().ToString(), o.Name, _now(), o.Domain)
        {
            Trigger = o.Trigger,
            SelfVerification = o.SelfVerification,
            EnvFeedback = o.EnvFeedback,
            Body = o.Body,
            Metadata = o.Metadata,
        };
        await _store.UpsertAsync(record, cancellationToken).ConfigureAwait(false);
        return record;
    }

    public Task<SkillRecord?> GetAsync(string skillId, CancellationToken cancellationToken = default) => _store.GetAsync(skillId, cancellationToken);

    public Task<IReadOnlyList<SkillRecord>> AllAsync(CancellationToken cancellationToken = default) => _store.AllAsync(cancellationToken);

    /// <summary>Record the LLM's self-assessment; a self-fail rejects an active skill (it is not silently kept).</summary>
    public Task<SkillRecord> SetSelfVerificationAsync(string skillId, SkillVerdict verdict, double? score = null, string? rationale = null, string? model = null,
        CancellationToken cancellationToken = default) => MutateAsync(skillId, r =>
    {
        var next = r with { SelfVerification = new SelfVerification(verdict, true, score, string.IsNullOrEmpty(rationale) ? null : rationale, string.IsNullOrEmpty(model) ? null : model) };
        return verdict == SkillVerdict.Fail && r.Status == SkillLifecycle.Active
            ? next with { Status = SkillLifecycle.Rejected, RetirementReason = RetirementReason.SelfRejected, RetiredAt = _now() }
            : next;
    }, cancellationToken);

    /// <summary>
    /// Record an invocation and the environment's verdict (the ground-truth half of RQ-C). Three calls with no success
    /// retire an active skill unless environment feedback is explicitly off (absent counts as on here).
    /// </summary>
    public Task<SkillRecord> RecordExecutionAsync(string skillId, ExecutionOutcome outcome, CancellationToken cancellationToken = default) => MutateAsync(skillId, r =>
    {
        var calls = r.CallCount + 1;
        var successes = r.SuccessCount + (outcome.Ok ? 1 : 0);
        var ts = _now();
        var next = r with
        {
            CallCount = calls,
            SuccessCount = successes,
            FailureCount = r.FailureCount + (outcome.Ok ? 0 : 1),
            LastUsedAt = ts,
            Execution = new SkillExecution(outcome.Ok, ts, calls, string.IsNullOrEmpty(outcome.Detail) ? null : outcome.Detail, outcome.DurationMs),
        };
        return calls >= 3 && successes == 0 && r.Status == SkillLifecycle.Active && (r.EnvFeedback?.Enabled ?? true)
            ? next with { Status = SkillLifecycle.Retired, RetirementReason = RetirementReason.LowPrecision, RetiredAt = ts }
            : next;
    }, cancellationToken);

    public Task<SkillRecord> RetireAsync(string skillId, RetirementReason reason, CancellationToken cancellationToken = default) => MutateAsync(skillId, r => r with
    {
        Status = reason == RetirementReason.SelfRejected ? SkillLifecycle.Rejected : SkillLifecycle.Retired,
        RetirementReason = reason,
        RetiredAt = _now(),
    }, cancellationToken);

    public Task<SkillRecord> SetEnvFeedbackAsync(string skillId, bool enabled, CancellationToken cancellationToken = default) =>
        MutateAsync(skillId, r => r with { EnvFeedback = new EnvFeedback(enabled, r.EnvFeedback?.AppliedAt is { } at && at != 0 ? at : null) }, cancellationToken);

    public async Task<SkillLibraryMetrics> MetricsAsync(CancellationToken cancellationToken = default) => SkillMetrics.Compute(await _store.AllAsync(cancellationToken).ConfigureAwait(false));

#pragma warning disable CS0618 // The deprecated table is kept for backward compatibility.
    public async Task<IReadOnlyList<TwoByTwoCell>> TwoByTwoAsync(CancellationToken cancellationToken = default) => SkillMetrics.TwoByTwo(await _store.AllAsync(cancellationToken).ConfigureAwait(false));
#pragma warning restore CS0618

    /// <summary>Retire every active skill below the precision threshold once it has at least <paramref name="minCalls"/> calls.</summary>
    public async Task<IReadOnlyList<SkillRecord>> PruneLowPrecisionAsync(double threshold, int minCalls = 3, CancellationToken cancellationToken = default)
    {
        var doomed = (await _store.AllAsync(cancellationToken).ConfigureAwait(false))
            .Where(r => r.Status == SkillLifecycle.Active && r.CallCount >= minCalls && (double)r.SuccessCount / r.CallCount < threshold).ToList();
        var ts = _now();
        foreach (var r in doomed)
            await _store.UpsertAsync(r with { Status = SkillLifecycle.Retired, RetirementReason = RetirementReason.LowPrecision, RetiredAt = ts }, cancellationToken).ConfigureAwait(false);
        return doomed;
    }

    /// <summary>Recording a verdict for a domain without an oracle would fabricate ground truth for the 2×2 control cell.</summary>
    public static void AssertOracleAvailable(SkillRecord record)
    {
        if (!SkillMetrics.HasEnvironmentalOracle(record.Domain))
        {
            throw new NoOracleException($"Skill {record.SkillId} is in domain \"{Core.Js.WireName.Of(record.Domain)}\", which has no "
                + "environmental oracle. Do not record an execution verdict for it — that would fabricate ground truth for the 2×2 control cell.");
        }
    }
}
