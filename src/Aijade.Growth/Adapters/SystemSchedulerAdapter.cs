using System.Text.Json;

namespace Aijade.Growth.Adapters;

// The wall clock plus a token-bucket ledger persisted to disk, so quotas survive restarts. ConsumeBudget stays
// synchronous (the port contract); persistence is a small best-effort JSON write.

/// <param name="Capacity">Maximum tokens the bucket holds.</param>
/// <param name="RefillPerSec">Refill rate in tokens per second.</param>
public sealed record BudgetPolicy(double Capacity, double RefillPerSec);

public sealed class SystemSchedulerAdapter : ISchedulerPort
{
    private sealed class LedgerEntry
    {
        public double Balance { get; set; }

        public double LastRefill { get; set; }
    }

    private readonly Dictionary<string, BudgetPolicy> budgets;
    private readonly Dictionary<string, LedgerEntry> ledger = new(StringComparer.Ordinal);
    private readonly string? ledgerPath;
    private readonly TimeProvider time;
    private readonly Lock gate = new();

    /// <param name="budgets">Per-scope budgets; unlisted scopes are unlimited.</param>
    /// <param name="ledgerPath">Where the ledger is persisted (JSON); null keeps it in memory.</param>
    /// <param name="time">Clock override for tests.</param>
    public SystemSchedulerAdapter(IReadOnlyDictionary<string, BudgetPolicy>? budgets = null, string? ledgerPath = null, TimeProvider? time = null)
    {
        this.budgets = new Dictionary<string, BudgetPolicy>(budgets ?? new Dictionary<string, BudgetPolicy>(), StringComparer.Ordinal);
        this.ledgerPath = ledgerPath;
        this.time = time ?? TimeProvider.System;
        if (ledgerPath is not null && File.Exists(ledgerPath))
        {
            try
            {
                var data = JsonSerializer.Deserialize<Dictionary<string, LedgerEntry>>(File.ReadAllText(ledgerPath), GrowthJson.Options);
                foreach (var (k, v) in data ?? [])
                    ledger[k] = v;
            }
            catch (Exception e) when (e is IOException or JsonException)
            {
                // Corrupt ledger: start fresh.
            }
        }
    }

    public double Now() => time.GetUtcNow().ToUnixTimeMilliseconds();

    public bool ConsumeBudget(string scope, double amount)
    {
        if (!budgets.TryGetValue(scope, out var policy))
            return true;
        lock (gate)
        {
            var now = Now();
            if (!ledger.TryGetValue(scope, out var entry))
            {
                entry = new LedgerEntry { Balance = policy.Capacity, LastRefill = now };
                ledger[scope] = entry;
            }
            var elapsedSec = Math.Max(0, (now - entry.LastRefill) / 1000);
            entry.Balance = Math.Min(policy.Capacity, entry.Balance + (elapsedSec * policy.RefillPerSec));
            entry.LastRefill = now;
            var ok = entry.Balance >= amount;
            if (ok)
                entry.Balance -= amount;
            Persist();
            return ok;
        }
    }

    /// <summary>Current balances (ops / tests).</summary>
    public IReadOnlyDictionary<string, double> Snapshot()
    {
        lock (gate)
            return ledger.ToDictionary(kv => kv.Key, kv => kv.Value.Balance, StringComparer.Ordinal);
    }

    private void Persist()
    {
        if (ledgerPath is null)
            return;
        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(ledgerPath))!);
            File.WriteAllText(ledgerPath, JsonSerializer.Serialize(ledger, GrowthJson.Options));
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException)
        {
            // Best effort: budgeting still works in memory.
        }
    }
}
