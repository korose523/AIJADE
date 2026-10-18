using System.Text.Json.Nodes;

using Aijade.Growth;
using Aijade.Growth.Services;
using Aijade.Memory.Contracts;
using Aijade.Memory.Development;
using Aijade.Server.Infrastructure;

using Npgsql;

namespace Aijade.Server.Memory;

// Persona snapshots and performance intents are stored and queued for cross-device sync through an outbox; share
// notifications are queued for delivery. Deriving a persona from memory runs the real PerformanceDirector over the session's
// committed evidence and persists the validated kernel intent — never a hand-rolled look-alike, never a blank intent.

public sealed class NoEvidenceException() : Exception("no committed long-term memory found for session");

public sealed record PersonaSnapshotInput(string DeviceId, int PrivacyLevel, JsonObject Persona, int Version, string? Id = null);

public sealed record PerformanceIntentInput(string DeviceId, int PrivacyLevel, string PersonaSnapshotRef, JsonObject Intent, double TimeMarked, string? Id = null);

public sealed record DeriveInput(string UserId, string SessionId, string DeviceId, int PrivacyLevel, string AgentId, string UserScope, int? StepCount = null, int? Duration = null);

public sealed record ShareNotificationInput(string Id, string Channel, string ContentRef, double Score, int PrivacyLevel);

public sealed class LongTermMemoryService(NpgsqlDataSource db, IJobBroker queue, TimeProvider? time = null)
{
    private readonly TimeProvider clock = time ?? TimeProvider.System;

    private static void AssertPrivacy(int level)
    {
        if (level is < 0 or > 3)
            throw ApiException.BadRequest("privacyLevel must be an integer from 0 to 3", "INVALID_PRIVACY_LEVEL");
    }

    private static JsonObject Row(System.Data.Common.DbDataReader r)
    {
        var o = new JsonObject();
        for (var i = 0; i < r.FieldCount; i++)
        {
            var name = r.GetName(i);
            var key = System.Text.Json.JsonNamingPolicy.CamelCase.ConvertName(string.Concat(name.Split('_').Select((p, k) => k == 0 ? p : char.ToUpperInvariant(p[0]) + p[1..])));
            o[key] = r.IsDBNull(i) ? null
                : r.GetDataTypeName(i) == "jsonb" ? JsonNode.Parse(r.GetString(i))
                : r.GetFieldType(i) == typeof(DateTime) ? JsonValue.Create(new DateTimeOffset(DateTime.SpecifyKind(r.GetDateTime(i), DateTimeKind.Utc)))
                : JsonValue.Create(r.GetValue(i));
        }
        return o;
    }

    private static async Task<JsonObject> InsertReturningAsync(NpgsqlConnection conn, NpgsqlTransaction tx, string sql, CancellationToken ct, params NpgsqlParameter[] ps) =>
        (await Sql.QueryAsync(conn, tx, sql + " RETURNING *", Row, ct, ps).ConfigureAwait(false))[0];

    private async Task<JsonObject> SaveWithOutboxAsync(string userId, string deviceId, int privacy, string entityType, Func<NpgsqlConnection, NpgsqlTransaction, Task<JsonObject>> insert, CancellationToken ct)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        await using var tx = await conn.BeginTransactionAsync(ct).ConfigureAwait(false);
        var entity = await insert(conn, tx).ConfigureAwait(false);
        var outboxId = Ids.New();
        await Sql.ExecAsync(conn, tx, "INSERT INTO memory_sync_outbox (id, user_id, source_device_id, entity_type, entity_id, privacy_level, payload) VALUES ($1,$2,$3,$4,$5,$6,$7)", ct,
            Sql.Text(outboxId), Sql.Text(userId), Sql.Text(deviceId), Sql.Text(entityType), Sql.Text(entity["id"]!.GetValue<string>()), Sql.P(privacy), Sql.Jsonb(entity)).ConfigureAwait(false);
        await tx.CommitAsync(ct).ConfigureAwait(false);
        await queue.EnqueueAsync(Queues.Memory, new JsonObject { ["kind"] = "sync", ["outboxId"] = outboxId }, ct).ConfigureAwait(false);
        return entity;
    }

    public Task<JsonObject> SavePersonaSnapshotAsync(string userId, PersonaSnapshotInput input, CancellationToken ct = default)
    {
        AssertPrivacy(input.PrivacyLevel);
        return SaveWithOutboxAsync(userId, input.DeviceId, input.PrivacyLevel, "persona_snapshot", (conn, tx) => InsertReturningAsync(conn, tx,
            "INSERT INTO persona_snapshots (id, user_id, device_id, privacy_level, persona, version) VALUES ($1,$2,$3,$4,$5,$6)", ct,
            Sql.Text(input.Id ?? Ids.New()), Sql.Text(userId), Sql.Text(input.DeviceId), Sql.P(input.PrivacyLevel), Sql.Jsonb(input.Persona), Sql.P(input.Version)), ct);
    }

    public Task<JsonObject> SavePerformanceIntentAsync(string userId, PerformanceIntentInput input, CancellationToken ct = default)
    {
        AssertPrivacy(input.PrivacyLevel);
        if (string.IsNullOrEmpty(input.PersonaSnapshotRef))
            throw ApiException.BadRequest("personaSnapshotRef is required", "INVALID_PERFORMANCE_INTENT");
        return SaveWithOutboxAsync(userId, input.DeviceId, input.PrivacyLevel, "performance_intent", (conn, tx) => InsertReturningAsync(conn, tx,
            "INSERT INTO performance_intents (id, user_id, device_id, persona_snapshot_ref, privacy_level, intent, time_marked) VALUES ($1,$2,$3,$4,$5,$6,$7)", ct,
            Sql.Text(input.Id ?? Ids.New()), Sql.Text(userId), Sql.Text(input.DeviceId), Sql.Text(input.PersonaSnapshotRef), Sql.P(input.PrivacyLevel),
            Sql.Jsonb(input.Intent), Sql.TimeMs(input.TimeMarked)), ct);
    }

    /// <summary>
    /// The persona stack derived from evidence, deterministically: the dialogue act from the joined text ('?' → question,
    /// '!' → celebrate, else inform) and the distinct evidence sources as developmental interests. Character, expressive
    /// state, relationship and constitution stay unset — there is no verified basis for them, so the kernel's neutral
    /// baseline is used rather than a fabricated personality.
    /// </summary>
    public static PersonaInput DerivePersonaInput(IReadOnlyList<(string Content, string Source)> evidence)
    {
        var joined = string.Join(" ", evidence.Select(e => e.Content)).ToLowerInvariant();
        var act = joined.Contains('?', StringComparison.Ordinal) ? DialogueAct.Question : joined.Contains('!', StringComparison.Ordinal) ? DialogueAct.Celebrate : DialogueAct.Inform;
        return new PersonaInput(act, Developmental: new DevelopmentalSelf(Interests: evidence.Select(e => e.Source).Distinct(StringComparer.Ordinal).ToList()));
    }

    /// <returns>The persisted persona snapshot and performance-intent rows.</returns>
    public async Task<(JsonObject Snapshot, JsonObject Intent)> DeriveForSessionAsync(DeriveInput input, CancellationToken ct = default)
    {
        AssertPrivacy(input.PrivacyLevel);
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        var evidence = await Sql.QueryAsync(conn, null,
            "SELECT c.content, p.source FROM evidence_chunks c JOIN evidence_packs p ON p.id = c.pack_id WHERE p.session_id = $1 ORDER BY c.created_at DESC LIMIT 20",
            r => (r.GetString(0), r.GetString(1)), ct, Sql.Text(input.SessionId)).ConfigureAwait(false);
        if (evidence.Count == 0)
            throw new NoEvidenceException();

        var persona = DerivePersonaInput(evidence);
        var personaJson = System.Text.Json.JsonSerializer.SerializeToNode(persona, GrowthJson.Options)!;
        await using var tx = await conn.BeginTransactionAsync(ct).ConfigureAwait(false);
        var snapshot = await InsertReturningAsync(conn, tx, "INSERT INTO persona_snapshots (id, user_id, device_id, privacy_level, persona, version) VALUES ($1,$2,$3,$4,$5,1)", ct,
            Sql.Text(Ids.New()), Sql.Text(input.UserId), Sql.Text(input.DeviceId), Sql.P(input.PrivacyLevel), Sql.Jsonb(new JsonObject
            {
                ["source"] = "v9-persona-intent",
                ["sessionId"] = input.SessionId,
                ["evidenceCount"] = evidence.Count,
                ["evidenceSources"] = new JsonArray([.. evidence.Select(e => e.Item2).Distinct(StringComparer.Ordinal).Select(s => (JsonNode)s)]),
                ["persona"] = personaJson,
            })).ConfigureAwait(false);

        var ports = new GrowthPorts(new InMemoryStorage(), new InMemoryScheduler(time: clock));
        var result = await new PerformanceDirector(ports, input.AgentId, input.UserScope)
            .DirectAsync(new DirectInput(snapshot["id"]!.GetValue<string>(), persona, StepCount: input.StepCount, Duration: input.Duration), ct).ConfigureAwait(false);
        var intent = result.Steps[0].Intent;
        var check = ContractValidationV8.Validate(intent); // defence in depth: the director already validated it
        if (!check.Ok)
            throw new InvalidOperationException($"PerformanceIntent rejected: {check.Reason}");
        var intentJson = System.Text.Json.JsonSerializer.SerializeToNode(intent, GrowthJson.Options)!.AsObject();
        intentJson.Insert(1, "schema", "aijade.performance_intent@1");
        var intentRow = await InsertReturningAsync(conn, tx,
            "INSERT INTO performance_intents (id, user_id, device_id, persona_snapshot_ref, privacy_level, intent, time_marked) VALUES ($1,$2,$3,$4,$5,$6,$7)", ct,
            Sql.Text(Ids.New()), Sql.Text(input.UserId), Sql.Text(input.DeviceId), Sql.Text(snapshot["id"]!.GetValue<string>()), Sql.P(input.PrivacyLevel),
            Sql.Jsonb(intentJson), Sql.TimeMs(intent.TimeMarked)).ConfigureAwait(false);
        await tx.CommitAsync(ct).ConfigureAwait(false);
        return (snapshot, intentRow);
    }

    /// <summary>Rows another device may pull: from other devices, privacy level ≥ 2 (shareable across devices).</summary>
    public async Task<IReadOnlyList<JsonObject>> PullForDeviceAsync(string userId, string deviceId, CancellationToken ct = default)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        return await Sql.QueryAsync(conn, null,
            "SELECT * FROM memory_sync_outbox WHERE user_id = $1 AND source_device_id <> $2 AND privacy_level >= 2 ORDER BY created_at DESC", Row, ct,
            Sql.Text(userId), Sql.Text(deviceId)).ConfigureAwait(false);
    }

    public async Task ProcessSyncAsync(string outboxId, CancellationToken ct = default)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        await Sql.ExecAsync(conn, null, "UPDATE memory_sync_outbox SET status = 'processed', processed_at = $2 WHERE id = $1", ct, Sql.Text(outboxId), Sql.Time(clock.GetUtcNow())).ConfigureAwait(false);
    }

    public async Task<JsonObject> QueueShareNotificationAsync(string userId, ShareNotificationInput c, CancellationToken ct = default)
    {
        AssertPrivacy(c.PrivacyLevel);
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        await using var tx = await conn.BeginTransactionAsync(ct).ConfigureAwait(false);
        var n = await InsertReturningAsync(conn, tx,
            "INSERT INTO sharing_notifications (id, user_id, candidate_id, channel, content_ref, score, privacy_level) VALUES ($1,$2,$3,$4,$5,$6,$7)", ct,
            Sql.Text(Ids.New()), Sql.Text(userId), Sql.Text(c.Id), Sql.Text(c.Channel), Sql.Text(c.ContentRef), Sql.P((float)c.Score), Sql.P(c.PrivacyLevel)).ConfigureAwait(false);
        await tx.CommitAsync(ct).ConfigureAwait(false);
        await queue.EnqueueAsync(Queues.Memory, new JsonObject { ["kind"] = "share", ["notificationId"] = n["id"]!.GetValue<string>() }, ct).ConfigureAwait(false);
        return n;
    }

    public async Task ProcessShareAsync(string notificationId, CancellationToken ct = default)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        await Sql.ExecAsync(conn, null, "UPDATE sharing_notifications SET status = 'delivered', delivered_at = $2 WHERE id = $1", ct, Sql.Text(notificationId), Sql.Time(clock.GetUtcNow())).ConfigureAwait(false);
    }

    public async Task<IReadOnlyList<JsonObject>> ListNotificationsAsync(string userId, CancellationToken ct = default)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        return await Sql.QueryAsync(conn, null, "SELECT * FROM sharing_notifications WHERE user_id = $1 ORDER BY created_at DESC", Row, ct, Sql.Text(userId)).ConfigureAwait(false);
    }
}
