using System.Globalization;

using Aijade.Core.Js;
using Aijade.Memory.Contracts;

namespace Aijade.Growth.Pilot;

// §5.3 memory-write policies as storage decorators. The B0–B5 / A1 difference is not a metric-side constant: each strategy
// is a real IStoragePort wrapper deciding, on every write, what enters long-term memory — from the written value's own
// attributes (truth, role, importance, predicted future value, session, contradiction link) plus the mechanism parameters
// under test (dual-graph separation, CDI). The configuration only picks which policy is installed. Statement ground truth
// travels in the SourceRecord locator, the one field the acquirer copies verbatim.

/// <param name="StmtId">Benchmark statement id (the golden-set key).</param>
/// <param name="SessionIndex">Session (sliding-window eviction).</param>
/// <param name="IsTrue">False for poison / false facts.</param>
/// <param name="Role">Statement role; null when the locator carried none.</param>
/// <param name="IsDistractor">Low-value / high-frequency distractor.</param>
/// <param name="IsContradictionLate">Late member of a contradiction pair.</param>
/// <param name="Contradicts">The earlier member, for a late member.</param>
/// <param name="Topic">Grouping key: the early id for a pair, else the statement id.</param>
/// <param name="FutureValue">Predicted future utility (HAC gate input).</param>
/// <param name="Importance">Importance (threshold / budget gate input).</param>
public sealed record MemoryMeta(
    string StmtId, int SessionIndex, bool IsTrue, string? Role, bool IsDistractor, bool IsContradictionLate, string? Contradicts, string? Topic,
    double FutureValue, double Importance);

/// <param name="Strategy">Memory-write strategy.</param>
/// <param name="DualGraphSeparation">DGM: experience / belief dual graph (false-fact filter and contradiction retention).</param>
/// <param name="CdiEnabled">CDI: identity constraint blocking destabilising writes.</param>
/// <param name="WindowSessions">Sliding-window size in sessions.</param>
/// <param name="Budget">Fixed-budget slot ceiling.</param>
/// <param name="Reflect">Reflection summariser (the B4 policy).</param>
public sealed record PolicyParams(
    MemoryWriteStrategy Strategy, bool DualGraphSeparation, bool CdiEnabled, int WindowSessions, int Budget, Func<string, Task<string>>? Reflect = null);

public static class MemoryPolicies
{
    /// <summary>The only kind the policy gates and evicts.</summary>
    public const string MemoryKind = "source_record";

    /// <summary>Persona-core roles whose retention defines Core Stability.</summary>
    public static IReadOnlySet<string> CorePersonaRoles { get; } = new HashSet<string>(StringComparer.Ordinal) { "preference_early", "preference_late", "relationship_boundary" };

    /// <summary>Identity-destabilising roles (high-emotion, low-fact), blocked by CDI.</summary>
    public static IReadOnlySet<string> DestabilizingRoles { get; } = new HashSet<string>(StringComparer.Ordinal) { "emotion_high_lowfact" };

    public static string EncodeLocator(MemoryMeta m)
    {
        var blob = string.Join("&",
            $"s={m.SessionIndex}", $"t={(m.IsTrue ? 1 : 0)}", $"r={m.Role}", $"d={(m.IsDistractor ? 1 : 0)}", $"c={(m.IsContradictionLate ? 1 : 0)}",
            $"ct={m.Contradicts ?? ""}", $"tp={m.Topic}", $"fv={JsFormat.Number(m.FutureValue)}", $"imp={JsFormat.Number(m.Importance)}");
        return $"stmt:{m.StmtId}|meta:{blob}";
    }

    /// <summary><c>Number(s) || 0</c>: JavaScript numeric conversion, with NaN and absence becoming 0.</summary>
    private static double NumberOrZero(string? s)
    {
        if (s is null)
            return 0;
        var t = JsText.Trim(s);
        if (t.Length == 0)
            return 0;
        if (t.StartsWith("0x", StringComparison.OrdinalIgnoreCase))
            return long.TryParse(t[2..], NumberStyles.AllowHexSpecifier, CultureInfo.InvariantCulture, out var hex) ? hex : 0;
        if (t is "Infinity" or "+Infinity")
            return double.PositiveInfinity;
        if (t == "-Infinity")
            return double.NegativeInfinity;
        if (t.Any(c => !(char.IsAsciiDigit(c) || c is '.' or 'e' or 'E' or '+' or '-')))
            return 0;
        return double.TryParse(t, NumberStyles.Float, CultureInfo.InvariantCulture, out var v) && !double.IsNaN(v) ? v : 0;
    }

    public static MemoryMeta? DecodeLocator(string locator)
    {
        const string sep = "|meta:";
        var i = locator.IndexOf(sep, StringComparison.Ordinal);
        if (i < 0)
            return null;
        var head = locator[..i];
        var stmtId = head.StartsWith("stmt:", StringComparison.Ordinal) ? head[5..] : head;
        var kv = new Dictionary<string, string>(StringComparer.Ordinal);
        foreach (var part in locator[(i + sep.Length)..].Split('&'))
        {
            var eq = part.IndexOf('=', StringComparison.Ordinal);
            if (eq >= 0)
                kv[part[..eq]] = part[(eq + 1)..];
        }
        if (stmtId.Length == 0)
            return null;
        return new MemoryMeta(stmtId, (int)NumberOrZero(kv.GetValueOrDefault("s")), kv.GetValueOrDefault("t") == "1", kv.GetValueOrDefault("r"),
            kv.GetValueOrDefault("d") == "1", kv.GetValueOrDefault("c") == "1", kv.GetValueOrDefault("ct") is { Length: > 0 } ct ? ct : null,
            kv.GetValueOrDefault("tp"), NumberOrZero(kv.GetValueOrDefault("fv")), NumberOrZero(kv.GetValueOrDefault("imp")));
    }

    /// <summary>Policy parameters of a Table-3 configuration (window 10 sessions).</summary>
    public static PolicyParams ParamsFrom(MechanismConfig config, int budget, Func<string, Task<string>>? reflect = null) =>
        new(config.MemoryWrite, config.DualGraphSeparation, config.IdentityConstraint, 10, budget, reflect);

    /// <summary>A reflection summariser over an LLM port: <c>reflect: {content}</c>.</summary>
    public static Func<string, Task<string>> MakeReflection(ILlmPort llm) => content => llm.CompleteAsync($"reflect: {content}");
}

/// <summary>
/// A storage decorator implementing one memory-write strategy. Kinds other than <see cref="MemoryPolicies.MemoryKind"/> pass
/// straight through so the growth loop runs normally; source records are admitted, evicted and contradiction-resolved by
/// the strategy, and the genuinely committed set is exposed by <see cref="Committed"/>.
/// </summary>
/// <remarks>
/// Reproduced as written: a contradiction overwrite without DGM drops the early member from the committed set but not
/// from the record map, and records are keyed by statement id while <c>GetAsync</c> is asked for record ids.
/// </remarks>
public sealed class PolicyStorage(IStoragePort inner, PolicyParams p) : IStoragePort
{
    private readonly OrderedDictionary<string, MemoryMeta> mem = new(StringComparer.Ordinal);
    private readonly List<string> order = [];
    private readonly OrderedDictionary<string, object?> records = new(StringComparer.Ordinal);
    private readonly Lock gate = new();
    private int maxSession = -1;

    /// <summary>The genuinely persisted memory (statement id → meta), in commit order. Read by the metrics.</summary>
    public IReadOnlyList<MemoryMeta> Committed
    {
        get
        {
            lock (gate)
                return [.. mem.Values];
        }
    }

    private async Task<bool> AdmitTrueAsync(MemoryMeta meta)
    {
        switch (p.Strategy)
        {
            case MemoryWriteStrategy.None:
                return false;
            case MemoryWriteStrategy.SlidingWindow:
            case MemoryWriteStrategy.VectorAllwrite:
                return true;
            case MemoryWriteStrategy.ImportanceThreshold:
                return meta.Importance >= 0.5;
            case MemoryWriteStrategy.LlmReflection:
                if (meta.Importance >= 0.5)
                    return true;
                if (p.Reflect is { } reflect)
                {
                    var output = await reflect((meta.Role ?? "undefined") + meta.StmtId).ConfigureAwait(false);
                    return uint.Parse(GrowthUtil.Fnv1a(output), NumberStyles.AllowHexSpecifier, CultureInfo.InvariantCulture) % 1000 < 300;
                }
                return false;
            case MemoryWriteStrategy.FixedBudget:
                return meta.Importance >= 0.4;
            case MemoryWriteStrategy.HacGated:
                // HAC endogenous gate: predicted future utility, with a high-confidence importance fallback. False facts are
                // left to the dual graph (see PutAsync).
                return meta.FutureValue >= 0.4 || meta.Importance >= 0.7;
            default:
                return false;
        }
    }

    public async Task PutAsync<T>(string kind, string id, T value, CancellationToken cancellationToken = default)
    {
        if (kind != MemoryPolicies.MemoryKind || value is not SourceRecord record || MemoryPolicies.DecodeLocator(record.Locator) is not { } meta)
        {
            await inner.PutAsync(kind, id, value, cancellationToken).ConfigureAwait(false);
            return;
        }
        // DGM: the dual graph is the only false-fact filter; with it, poisoning is rejected at write time.
        if (!meta.IsTrue && p.DualGraphSeparation)
            return;
        // Contradictions: with DGM both sides are retained; without it the early member is silently overwritten.
        if (meta.IsContradictionLate && meta.Contradicts is { } early && !p.DualGraphSeparation)
        {
            lock (gate)
                mem.Remove(early);
        }
        // CDI: identity-destabilising writes are blocked outright.
        if (p.CdiEnabled && meta.Role is { } role && MemoryPolicies.DestabilizingRoles.Contains(role))
            return;
        // False facts that passed the dual-graph check (DGM off) are admitted by every baseline.
        if (!meta.IsTrue || await AdmitTrueAsync(meta).ConfigureAwait(false))
            Commit(meta, value);
    }

    private void Commit(MemoryMeta meta, object? value)
    {
        lock (gate)
        {
            if (!mem.ContainsKey(meta.StmtId))
                order.Add(meta.StmtId);
            mem[meta.StmtId] = meta;
            records[meta.StmtId] = value;
            if (meta.SessionIndex > maxSession)
                maxSession = meta.SessionIndex;
            Enforce();
        }
    }

    /// <summary>Strategy-specific eviction after every commit; the other strategies have no hard slot cap.</summary>
    private void Enforce()
    {
        if (p.Strategy == MemoryWriteStrategy.SlidingWindow)
        {
            var cut = maxSession - (p.WindowSessions - 1);
            foreach (var id in mem.Keys.ToList())
            {
                if (mem[id].SessionIndex < cut)
                {
                    mem.Remove(id);
                    records.Remove(id);
                }
            }
        }
        else if (p.Strategy == MemoryWriteStrategy.FixedBudget)
        {
            while (mem.Count > p.Budget && EvictionCandidate() is { } victim)
            {
                mem.Remove(victim);
                records.Remove(victim);
            }
        }
    }

    /// <summary>Lowest importance, then earliest inserted.</summary>
    private string? EvictionCandidate()
    {
        string? worst = null;
        var worstScore = double.PositiveInfinity;
        var worstOrder = double.PositiveInfinity;
        foreach (var (id, m) in mem)
        {
            var oi = order.IndexOf(id);
            if (m.Importance < worstScore || (m.Importance == worstScore && oi < worstOrder))
            {
                worst = id;
                worstScore = m.Importance;
                worstOrder = oi;
            }
        }
        return worst;
    }

    public Task<T?> GetAsync<T>(string kind, string id, CancellationToken cancellationToken = default)
    {
        if (kind != MemoryPolicies.MemoryKind)
            return inner.GetAsync<T>(kind, id, cancellationToken);
        lock (gate)
            return Task.FromResult(records.TryGetValue(id, out var v) ? (T?)v : default);
    }

    public Task<IReadOnlyList<T>> ListAsync<T>(string kind, CancellationToken cancellationToken = default)
    {
        if (kind != MemoryPolicies.MemoryKind)
            return inner.ListAsync<T>(kind, cancellationToken);
        lock (gate)
            return Task.FromResult<IReadOnlyList<T>>(records.Values.Cast<T>().ToList());
    }

    public async Task<IReadOnlyList<T>> QueryAsync<T>(string kind, Func<T, bool> predicate, CancellationToken cancellationToken = default)
    {
        if (kind != MemoryPolicies.MemoryKind)
            return await inner.QueryAsync(kind, predicate, cancellationToken).ConfigureAwait(false);
        return (await ListAsync<T>(kind, cancellationToken).ConfigureAwait(false)).Where(predicate).ToList();
    }
}
