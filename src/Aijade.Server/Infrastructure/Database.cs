using System.Data.Common;
using System.Reflection;
using System.Text.Json.Nodes;

using Npgsql;

using NpgsqlTypes;

namespace Aijade.Server.Infrastructure;

/// <summary>Applies the embedded SQL migrations in order, once each, under an advisory lock (safe with several instances).</summary>
public static class Migrator
{
    private const long LockKey = 0x41494A414445; // "AIJADE"

    public static IReadOnlyList<(string Id, string Sql)> Scripts()
    {
        var asm = typeof(Migrator).Assembly;
        const string prefix = "Aijade.Server.Migrations.";
        return asm.GetManifestResourceNames()
            .Where(n => n.StartsWith(prefix, StringComparison.Ordinal) && n.EndsWith(".sql", StringComparison.Ordinal))
            .Order(StringComparer.Ordinal)
            .Select(n =>
            {
                using var stream = asm.GetManifestResourceStream(n)!;
                using var reader = new StreamReader(stream);
                return (n[prefix.Length..^4], reader.ReadToEnd());
            })
            .ToList();
    }

    /// <returns>The ids applied by this call.</returns>
    public static async Task<IReadOnlyList<string>> MigrateAsync(NpgsqlDataSource db, CancellationToken cancellationToken = default)
    {
        await using var conn = await db.OpenConnectionAsync(cancellationToken).ConfigureAwait(false);
        await using (var lockCmd = new NpgsqlCommand($"SELECT pg_advisory_lock({LockKey})", conn))
            await lockCmd.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
        try
        {
            await using (var create = new NpgsqlCommand(
                "CREATE TABLE IF NOT EXISTS __aijade_migrations (id text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())", conn))
                await create.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
            var applied = new HashSet<string>(StringComparer.Ordinal);
            await using (var read = new NpgsqlCommand("SELECT id FROM __aijade_migrations", conn))
            await using (var r = await read.ExecuteReaderAsync(cancellationToken).ConfigureAwait(false))
            {
                while (await r.ReadAsync(cancellationToken).ConfigureAwait(false))
                    applied.Add(r.GetString(0));
            }
            var done = new List<string>();
            foreach (var (id, sql) in Scripts().Where(s => !applied.Contains(s.Id)))
            {
                await using var tx = await conn.BeginTransactionAsync(cancellationToken).ConfigureAwait(false);
                await using (var cmd = new NpgsqlCommand(sql, conn, tx))
                    await cmd.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
                await using (var mark = new NpgsqlCommand("INSERT INTO __aijade_migrations (id) VALUES ($1)", conn, tx))
                {
                    mark.Parameters.Add(new NpgsqlParameter { Value = id });
                    await mark.ExecuteNonQueryAsync(cancellationToken).ConfigureAwait(false);
                }
                await tx.CommitAsync(cancellationToken).ConfigureAwait(false);
                done.Add(id);
            }
            return done;
        }
        finally
        {
            await using var unlock = new NpgsqlCommand($"SELECT pg_advisory_unlock({LockKey})", conn);
            await unlock.ExecuteNonQueryAsync(CancellationToken.None).ConfigureAwait(false);
        }
    }
}

/// <summary>Small helpers for parameterised SQL over Npgsql.</summary>
public static class Sql
{
    public static NpgsqlParameter P(object? value) => new() { Value = value ?? DBNull.Value };

    public static NpgsqlParameter Text(string? value) => new() { Value = (object?)value ?? DBNull.Value, NpgsqlDbType = NpgsqlDbType.Text };

    public static NpgsqlParameter Jsonb(JsonNode? value) => new() { Value = value is null ? DBNull.Value : value.ToJsonString(), NpgsqlDbType = NpgsqlDbType.Jsonb };

    public static NpgsqlParameter TextArray(IEnumerable<string> values) => new() { Value = values.ToArray(), NpgsqlDbType = NpgsqlDbType.Array | NpgsqlDbType.Text };

    public static NpgsqlParameter Time(DateTimeOffset value) => new() { Value = value.UtcDateTime, NpgsqlDbType = NpgsqlDbType.TimestampTz };

    public static NpgsqlParameter TimeMs(double unixMs) => Time(DateTimeOffset.FromUnixTimeMilliseconds((long)unixMs));

    public static NpgsqlCommand Cmd(NpgsqlConnection conn, NpgsqlTransaction? tx, string sql, params NpgsqlParameter[] parameters)
    {
        var cmd = new NpgsqlCommand(sql, conn, tx);
        cmd.Parameters.AddRange(parameters);
        return cmd;
    }

    public static async Task<int> ExecAsync(NpgsqlConnection conn, NpgsqlTransaction? tx, string sql, CancellationToken ct, params NpgsqlParameter[] parameters)
    {
        await using var cmd = Cmd(conn, tx, sql, parameters);
        return await cmd.ExecuteNonQueryAsync(ct).ConfigureAwait(false);
    }

    public static async Task<List<T>> QueryAsync<T>(NpgsqlConnection conn, NpgsqlTransaction? tx, string sql, Func<DbDataReader, T> map, CancellationToken ct, params NpgsqlParameter[] parameters)
    {
        await using var cmd = Cmd(conn, tx, sql, parameters);
        await using var r = await cmd.ExecuteReaderAsync(ct).ConfigureAwait(false);
        var rows = new List<T>();
        while (await r.ReadAsync(ct).ConfigureAwait(false))
            rows.Add(map(r));
        return rows;
    }

    public static async Task<long> CountAsync(NpgsqlConnection conn, NpgsqlTransaction? tx, string sql, CancellationToken ct, params NpgsqlParameter[] parameters)
    {
        await using var cmd = Cmd(conn, tx, sql, parameters);
        return Convert.ToInt64(await cmd.ExecuteScalarAsync(ct).ConfigureAwait(false), System.Globalization.CultureInfo.InvariantCulture);
    }

    public static string? NullableString(DbDataReader r, int i) => r.IsDBNull(i) ? null : r.GetString(i);

    public static JsonNode? JsonOf(DbDataReader r, int i) => r.IsDBNull(i) ? null : JsonNode.Parse(r.GetString(i));

    public static double UnixMs(DbDataReader r, int i) => new DateTimeOffset(DateTime.SpecifyKind(r.GetDateTime(i), DateTimeKind.Utc)).ToUnixTimeMilliseconds();
}
