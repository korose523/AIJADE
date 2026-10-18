using System.Text.Json.Nodes;

using Aijade.Server.Infrastructure;

using Npgsql;

namespace Aijade.Server.Product;

// The flux credit ledger: an append-only transaction log with a cached balance per user, updated in one transaction
// under a row lock. An idempotency key makes a charge or credit happen at most once (webhook retries, client retries).
// A charge that would take the balance below zero is refused with 402.

public sealed record FluxTransaction(string Id, long Amount, long BalanceAfter, string Kind, string Reason, DateTimeOffset CreatedAt);

public sealed class FluxLedger(NpgsqlDataSource db)
{
    public async Task<long> BalanceAsync(string userId, CancellationToken ct = default)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        var rows = await Sql.QueryAsync(conn, null, "SELECT balance FROM flux_accounts WHERE user_id = $1", r => r.GetInt64(0), ct, Sql.Text(userId)).ConfigureAwait(false);
        return rows.Count > 0 ? rows[0] : 0;
    }

    /// <summary>Apply a signed amount (credit &gt; 0, charge &lt; 0). Returns the transaction, or the earlier one with the same key.</summary>
    public async Task<FluxTransaction> ApplyAsync(string userId, long amount, string kind, string reason, string? idempotencyKey = null, JsonObject? meta = null, CancellationToken ct = default)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        await using var tx = await conn.BeginTransactionAsync(ct).ConfigureAwait(false);
        if (idempotencyKey is not null)
        {
            var prior = await Sql.QueryAsync(conn, tx, "SELECT id, amount, balance_after, kind, reason, created_at FROM flux_transactions WHERE idempotency_key = $1", Map, ct, Sql.Text(idempotencyKey)).ConfigureAwait(false);
            if (prior.Count > 0)
                return prior[0];
        }
        await Sql.ExecAsync(conn, tx, "INSERT INTO flux_accounts (user_id) VALUES ($1) ON CONFLICT DO NOTHING", ct, Sql.Text(userId)).ConfigureAwait(false);
        var balance = (await Sql.QueryAsync(conn, tx, "SELECT balance FROM flux_accounts WHERE user_id = $1 FOR UPDATE", r => r.GetInt64(0), ct, Sql.Text(userId)).ConfigureAwait(false))[0];
        var after = balance + amount;
        if (after < 0)
            throw new ApiException(402, "INSUFFICIENT_FLUX", $"Insufficient flux: balance {balance}, required {-amount}");
        var id = Ids.New();
        var now = DateTimeOffset.UtcNow;
        await Sql.ExecAsync(conn, tx, "UPDATE flux_accounts SET balance = $2, updated_at = $3 WHERE user_id = $1", ct, Sql.Text(userId), Sql.P(after), Sql.Time(now)).ConfigureAwait(false);
        await Sql.ExecAsync(conn, tx, "INSERT INTO flux_transactions (id, user_id, amount, balance_after, kind, reason, idempotency_key, meta, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)", ct,
            Sql.Text(id), Sql.Text(userId), Sql.P(amount), Sql.P(after), Sql.Text(kind), Sql.Text(reason), Sql.Text(idempotencyKey), Sql.Jsonb(meta), Sql.Time(now)).ConfigureAwait(false);
        await tx.CommitAsync(ct).ConfigureAwait(false);
        return new FluxTransaction(id, amount, after, kind, reason, now);
    }

    private static FluxTransaction Map(System.Data.Common.DbDataReader r) =>
        new(r.GetString(0), r.GetInt64(1), r.GetInt64(2), r.GetString(3), r.GetString(4), new DateTimeOffset(DateTime.SpecifyKind(r.GetDateTime(5), DateTimeKind.Utc)));

    public async Task<IReadOnlyList<FluxTransaction>> HistoryAsync(string userId, int limit = 50, CancellationToken ct = default)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        return await Sql.QueryAsync(conn, null, "SELECT id, amount, balance_after, kind, reason, created_at FROM flux_transactions WHERE user_id = $1 ORDER BY created_at DESC LIMIT $2",
            Map, ct, Sql.Text(userId), Sql.P(Math.Clamp(limit, 1, 500))).ConfigureAwait(false);
    }
}

/// <summary>First-party product analytics: bounded feature / action / status values; the user id stays in the database.</summary>
public sealed class ProductEvents(NpgsqlDataSource db, ILogger<ProductEvents> logger)
{
    /// <summary>Best effort: a failure is logged and swallowed, never propagated to the caller.</summary>
    public async Task TrackAsync(string userId, string feature, string action, string status, string? source = null, string? model = null, string? provider = null,
        string? reason = null, JsonObject? metadata = null, CancellationToken ct = default)
    {
        try
        {
            await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
            await Sql.ExecAsync(conn, null, "INSERT INTO product_events (id, user_id, feature, action, status, source, model, provider, reason, metadata) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)", ct,
                Sql.Text(Ids.New()), Sql.Text(userId), Sql.Text(feature), Sql.Text(action), Sql.Text(status), Sql.Text(source), Sql.Text(model), Sql.Text(provider), Sql.Text(reason),
                Sql.Jsonb(metadata)).ConfigureAwait(false);
        }
        catch (Exception e) when (e is NpgsqlException or InvalidOperationException)
        {
            logger.LogWarning(e, "failed to write product event {Feature}/{Action}/{Status}; swallowed to protect the caller", feature, action, status);
        }
    }

    public async Task<JsonArray> AggregateAsync(DateTimeOffset from, DateTimeOffset? to, CancellationToken ct = default)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        var rows = await Sql.QueryAsync(conn, null,
            "SELECT feature, action, status, count(*), count(DISTINCT user_id) FROM product_events WHERE created_at >= $1 AND ($2::timestamptz IS NULL OR created_at < $2) " +
            "GROUP BY feature, action, status ORDER BY feature, action, status",
            r => (JsonNode)new JsonObject { ["feature"] = r.GetString(0), ["action"] = r.GetString(1), ["status"] = r.GetString(2), ["eventCount"] = r.GetInt64(3), ["distinctUsers"] = r.GetInt64(4) },
            ct, Sql.Time(from), to is { } t ? Sql.Time(t) : new NpgsqlParameter { Value = DBNull.Value, NpgsqlDbType = NpgsqlTypes.NpgsqlDbType.TimestampTz }).ConfigureAwait(false);
        return new JsonArray([.. rows]);
    }
}
