using System.Globalization;
using System.Text.Json.Nodes;

using Aijade.Server.Infrastructure;

using Npgsql;

namespace Aijade.Server.V9;

// The single write entry of the v9 event bus. Invariants:
//  1. Failure is visible: a database failure throws (the route turns it into a 5xx); success is never faked.
//  2. Idempotency rests on the unique key: look the key up first, then INSERT … ON CONFLICT DO NOTHING inside the
//     transaction; client retries are normal.
//  3. Fingerprints are never recomputed server-side: applied_params_hash is stored as received, only checked.
//  4. Pairing: an lpm.render_ready looks up the persona.render_requested of the same trace; a gap is written to the audit
//     log, so a render faithful to no known intent is visible instead of buried as normal data.

/// <summary>Why a render-trace contract was refused; distinct reasons so "missing pairing" and "identity drift" can be told apart in logs.</summary>
public enum RenderTraceFailure
{
    RenderRefNotFound,
    IntentRefMissing,
    AppliedParamsHashMismatch,
    AssetVersionHashMismatch,
    SelfReference,
    ProjectionRenderRefMismatch,
    ProjectionIntentRefMismatch,
}

public sealed class RenderTraceContractException(RenderTraceFailure reason, string detail)
    : Exception($"v10 render trace contract violated: {Core.Js.WireName.Of(reason)} ({detail})")
{
    public RenderTraceFailure Reason { get; } = reason;

    /// <summary>The client-facing message; the reason itself stays in the server log.</summary>
    public string PublicMessage => Reason is RenderTraceFailure.ProjectionRenderRefMismatch or RenderTraceFailure.ProjectionIntentRefMismatch
        ? "Render trace identity does not match the existing projection"
        : "Learning proposal render trace does not match the stored projection";
}

/// <summary>A validated envelope plus its validated payload.</summary>
public sealed record V9EventInput(
    string EventId, string TraceId, string CorrelationId, double Timestamp, string Producer, string OriginDevice, int PrivacyLevel,
    IReadOnlyList<string> EvidenceRefs, IReadOnlyList<string> CausalContextRefs, double RiskScore, string IdempotencyKey, string ReplayMode,
    string RiskLevel, string Topic, JsonObject Payload, int? Tick = null, string? InputHash = null, string? CoreStateNode = null)
{
    /// <summary>From an envelope that passed <see cref="V9Boundary.Envelope"/>, with the payload that passed its topic rule.</summary>
    public static V9EventInput FromEnvelope(JsonObject env, JsonObject payload)
    {
        static string S(JsonObject o, string k) => o[k]!.GetValue<string>();
        static double D(JsonObject o, string k) => double.Parse(o[k]!.ToJsonString(), CultureInfo.InvariantCulture);
        return new V9EventInput(S(env, "event_id"), S(env, "trace_id"), S(env, "correlation_id"), D(env, "timestamp"), S(env, "producer"),
            S(env, "origin_device"), (int)D(env, "privacy_level"), env["evidence_refs"]!.AsArray().Select(x => x!.GetValue<string>()).ToList(),
            env["causal_context_refs"]!.AsArray().Select(x => x!.GetValue<string>()).ToList(), D(env, "risk_score"), S(env, "idempotency_key"),
            S(env, "replay_mode"), S(env, "risk_level"), S(env, "topic"), payload,
            env.ContainsKey("tick") ? (int)D(env, "tick") : null, env["causality"]?["inputHash"]?.GetValue<string>(),
            env.ContainsKey("core_state_node") ? S(env, "core_state_node") : null);
    }
}

public sealed record V9EventRow(string Id, string EventId, string TraceId, string CorrelationId, string Topic, string IdempotencyKey);

public sealed record AppendEventResult(V9EventRow Row, bool Deduped, bool PairingMissing = false);

public sealed record RenderTraceReference(string RenderRef, string AppliedParamsHash, string AssetVersionHash, string? IntentRef = null);

public sealed record RenderTraceRecord(
    string Id, string SessionId, string TraceId, string CorrelationId, string EventId, string? PersonaSnapshotRef, string? IntentRef, string? RenderRef,
    string? AppliedParamsHash, string? AssetVersionHash, string? RenderReadyEventId, string? PersonaRenderRequestedEventId, string ProjectionStatus);

public sealed class V9EventService(NpgsqlDataSource db, ILogger<V9EventService> logger, TimeProvider? time = null)
{
    public const string PersonaRenderRequested = "aijade.persona.render_requested";
    public const string LpmRenderReady = "aijade.lpm.render_ready";
    private readonly TimeProvider clock = time ?? TimeProvider.System;

    /// <summary>paired = request (intent_ref) and receipt (render_ref) both present; partial = a pairing gap, visible on purpose.</summary>
    public static string ProjectionStatusOf(string? renderRef, string? intentRef) =>
        !string.IsNullOrEmpty(renderRef) && !string.IsNullOrEmpty(intentRef) ? "paired" : "partial";

    private const string TraceColumns =
        "id, session_id, trace_id, correlation_id, event_id, persona_snapshot_ref, intent_ref, render_ref, applied_params_hash, asset_version_hash, " +
        "render_ready_event_id, persona_render_requested_event_id, projection_status";

    private static RenderTraceRecord MapTrace(System.Data.Common.DbDataReader r) => new(
        r.GetString(0), r.GetString(1), r.GetString(2), r.GetString(3), r.GetString(4), Sql.NullableString(r, 5), Sql.NullableString(r, 6),
        Sql.NullableString(r, 7), Sql.NullableString(r, 8), Sql.NullableString(r, 9), Sql.NullableString(r, 10), Sql.NullableString(r, 11), r.GetString(12));

    private static async Task<V9EventRow?> ReadByKeyAsync(NpgsqlConnection conn, NpgsqlTransaction? tx, string key, CancellationToken ct) =>
        (await Sql.QueryAsync(conn, tx, "SELECT id, event_id, trace_id, correlation_id, topic, idempotency_key FROM events WHERE idempotency_key = $1 LIMIT 1",
            r => new V9EventRow(r.GetString(0), r.GetString(1), r.GetString(2), r.GetString(3), r.GetString(4), r.GetString(5)), ct, Sql.Text(key)))
        .FirstOrDefault();

    public async Task<RenderTraceRecord?> FindRenderTraceAsync(string renderRef, CancellationToken ct = default)
    {
        if (string.IsNullOrEmpty(renderRef))
            return null;
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        return (await Sql.QueryAsync(conn, null, $"SELECT {TraceColumns} FROM render_traces WHERE render_ref = $1 LIMIT 1", MapTrace, ct, Sql.Text(renderRef))).FirstOrDefault();
    }

    /// <summary>Whether render, intent and both content hashes belong to one projection.</summary>
    public async Task<bool> IsRenderTraceConsistentAsync(RenderTraceReference reference, CancellationToken ct = default)
    {
        var trace = await FindRenderTraceAsync(reference.RenderRef, ct).ConfigureAwait(false);
        return trace is { IntentRef: not null }
            && (reference.IntentRef is null || trace.IntentRef == reference.IntentRef)
            && trace.AppliedParamsHash == reference.AppliedParamsHash
            && trace.AssetVersionHash == reference.AssetVersionHash;
    }

    /// <summary>
    /// The latest real render identity with its full receipt triple, for observation dispatch; null when there is none —
    /// the caller must then skip the proposal rather than synthesise one. Deliberately not joined by session: observation
    /// sessions (extension install ids) and render sessions live in different namespaces; this projection is their only
    /// trustworthy link, and a proposal referencing it is re-checked at the boundary anyway.
    /// </summary>
    public async Task<RenderTraceReference?> FindLatestRenderIdentityAsync(CancellationToken ct = default)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        return (await Sql.QueryAsync(conn, null,
            "SELECT render_ref, applied_params_hash, asset_version_hash FROM render_traces " +
            "WHERE render_ref IS NOT NULL AND applied_params_hash IS NOT NULL AND asset_version_hash IS NOT NULL " +
            "ORDER BY updated_at DESC, created_at DESC LIMIT 1",
            r => new RenderTraceReference(r.GetString(0), r.GetString(1), r.GetString(2)), ct)).FirstOrDefault();
    }

    public async Task<AppendEventResult> AppendEventAsync(V9EventInput input, CancellationToken ct = default)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        if (await ReadByKeyAsync(conn, null, input.IdempotencyKey, ct).ConfigureAwait(false) is { } existing)
            return new AppendEventResult(existing, true);

        await using var tx = await conn.BeginTransactionAsync(ct).ConfigureAwait(false);
        if (await ReadByKeyAsync(conn, tx, input.IdempotencyKey, ct).ConfigureAwait(false) is { } txExisting)
            return new AppendEventResult(txExisting, true);

        await ValidateLearningReferenceAsync(conn, tx, input, ct).ConfigureAwait(false);
        var causality = input.InputHash is null ? null : new JsonObject { ["inputHash"] = input.InputHash };
        await Sql.ExecAsync(conn, tx,
            "INSERT INTO events (id, event_id, trace_id, correlation_id, \"timestamp\", producer, origin_device, privacy_level, evidence_refs, " +
            "causal_context_refs, risk_score, topic, payload, idempotency_key, replay_mode, risk_level, tick, causality, core_state_node) " +
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19) ON CONFLICT (idempotency_key) DO NOTHING", ct,
            Sql.Text(Ids.New()), Sql.Text(input.EventId), Sql.Text(input.TraceId), Sql.Text(input.CorrelationId), Sql.TimeMs(input.Timestamp),
            Sql.Text(input.Producer), Sql.Text(input.OriginDevice), Sql.P(input.PrivacyLevel), Sql.TextArray(input.EvidenceRefs),
            Sql.TextArray(input.CausalContextRefs), Sql.P((float)input.RiskScore), Sql.Text(input.Topic), Sql.Jsonb(input.Payload),
            Sql.Text(input.IdempotencyKey), Sql.Text(input.ReplayMode), Sql.Text(input.RiskLevel), Sql.P(input.Tick), Sql.Jsonb(causality),
            Sql.Text(input.CoreStateNode)).ConfigureAwait(false);
        var row = await ReadByKeyAsync(conn, tx, input.IdempotencyKey, ct).ConfigureAwait(false)
            ?? throw new InvalidOperationException("v9-events: failed to read back inserted event row after upsert");

        var pairingMissing = await CheckRenderReadyPairingAsync(conn, tx, input, ct).ConfigureAwait(false);
        await UpsertRenderTraceProjectionAsync(conn, tx, input, ct).ConfigureAwait(false);
        await tx.CommitAsync(ct).ConfigureAwait(false);
        return new AppendEventResult(row, false, pairingMissing);
    }

    private async Task<bool> CheckRenderReadyPairingAsync(NpgsqlConnection conn, NpgsqlTransaction tx, V9EventInput input, CancellationToken ct)
    {
        if (input.Topic != LpmRenderReady)
            return false;
        var found = await Sql.CountAsync(conn, tx, "SELECT count(*) FROM events WHERE topic = $1 AND trace_id = $2", ct,
            Sql.Text(PersonaRenderRequested), Sql.Text(input.TraceId)).ConfigureAwait(false);
        if (found > 0)
            return false;
        // A visible pairing gap, not a failure: the receipt is faithful to no known intent.
        await Sql.ExecAsync(conn, tx, "INSERT INTO audit_log_entries (id, tx_id, actor, action, before_hash, after_hash, at) VALUES ($1,$2,$3,$4,NULL,$5,$6)", ct,
            Sql.Text(Ids.New()), Sql.Text(input.EventId), Sql.Text("v9-render-pairing"), Sql.Text("render_ready_without_matching_request"), Sql.Text(input.TraceId),
            Sql.Time(clock.GetUtcNow())).ConfigureAwait(false);
        logger.LogWarning("lpm.render_ready received without a matching persona.render_requested (trace {TraceId}, key {Key})", input.TraceId, input.IdempotencyKey);
        return true;
    }

    private static string? Str(JsonObject p, string key) => p[key] is { } v ? (v is JsonValue jv && jv.TryGetValue<string>(out var s) ? s : v.ToJsonString()) : null;

    private async Task UpsertRenderTraceProjectionAsync(NpgsqlConnection conn, NpgsqlTransaction tx, V9EventInput input, CancellationToken ct)
    {
        if (input.Topic is not (PersonaRenderRequested or LpmRenderReady))
            return;
        var p = input.Payload;
        var sessionId = Str(p, "session_id") ?? "";
        var snapshot = Str(p, "persona_snapshot_ref");
        var intentRef = Str(p, "intent_ref");
        var renderRef = Str(p, "render_ref");
        var applied = Str(p, "applied_params_hash");
        var asset = Str(p, "asset_version_hash");
        var readyEventId = input.Topic == LpmRenderReady ? input.EventId : null;
        var requestedEventId = input.Topic == PersonaRenderRequested ? input.EventId : null;

        // §11.2 self-reference impersonation: an identity field that merely copies an envelope identifier points at no real
        // object, and would later pass as "two topics naming one identity". A cross-field rule, so it lives here.
        var envelopeIds = new HashSet<string>(StringComparer.Ordinal) { input.TraceId, input.EventId, input.CorrelationId };
        foreach (var (field, value) in new[] { ("intent_ref", intentRef), ("render_ref", renderRef) })
        {
            if (!string.IsNullOrEmpty(value) && envelopeIds.Contains(value))
                throw new RenderTraceContractException(RenderTraceFailure.SelfReference, $"{field}={value} equals an envelope identifier (trace={input.TraceId})");
        }

        var existing = (await Sql.QueryAsync(conn, tx, $"SELECT {TraceColumns} FROM render_traces WHERE trace_id = $1 LIMIT 1", MapTrace, ct,
            Sql.Text(input.TraceId)).ConfigureAwait(false)).FirstOrDefault();
        var now = clock.GetUtcNow();
        if (existing is not null)
        {
            // A trace is an append-only identity chain: never silently replace a render or an intent under one trace.
            if (input.Topic == LpmRenderReady && existing.RenderRef is { Length: > 0 } r0 && r0 != renderRef)
                throw new RenderTraceContractException(RenderTraceFailure.ProjectionRenderRefMismatch, $"trace={input.TraceId}");
            if (input.Topic == PersonaRenderRequested && existing.IntentRef is { Length: > 0 } i0 && i0 != intentRef)
                throw new RenderTraceContractException(RenderTraceFailure.ProjectionIntentRefMismatch, $"trace={input.TraceId}");
            var mergedRender = renderRef ?? existing.RenderRef;
            var mergedIntent = intentRef ?? existing.IntentRef;
            await Sql.ExecAsync(conn, tx,
                "UPDATE render_traces SET session_id=$2, correlation_id=$3, event_id=$4, persona_snapshot_ref=$5, intent_ref=$6, render_ref=$7, " +
                "applied_params_hash=$8, asset_version_hash=$9, render_ready_event_id=$10, persona_render_requested_event_id=$11, projection_status=$12, updated_at=$13 " +
                "WHERE id=$1", ct,
                Sql.Text(existing.Id), Sql.Text(sessionId), Sql.Text(input.CorrelationId), Sql.Text(input.EventId), Sql.Text(snapshot ?? existing.PersonaSnapshotRef),
                Sql.Text(mergedIntent), Sql.Text(mergedRender), Sql.Text(applied ?? existing.AppliedParamsHash), Sql.Text(asset ?? existing.AssetVersionHash),
                Sql.Text(readyEventId ?? existing.RenderReadyEventId), Sql.Text(requestedEventId ?? existing.PersonaRenderRequestedEventId),
                Sql.Text(ProjectionStatusOf(mergedRender, mergedIntent)), Sql.Time(now)).ConfigureAwait(false);
            return;
        }
        await Sql.ExecAsync(conn, tx,
            "INSERT INTO render_traces (id, session_id, trace_id, correlation_id, event_id, persona_snapshot_ref, intent_ref, render_ref, applied_params_hash, " +
            "asset_version_hash, render_ready_event_id, persona_render_requested_event_id, projection_status, created_at, updated_at) " +
            "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$14)", ct,
            Sql.Text(Ids.New()), Sql.Text(sessionId), Sql.Text(input.TraceId), Sql.Text(input.CorrelationId), Sql.Text(input.EventId), Sql.Text(snapshot),
            Sql.Text(intentRef), Sql.Text(renderRef), Sql.Text(applied), Sql.Text(asset), Sql.Text(readyEventId), Sql.Text(requestedEventId),
            Sql.Text(ProjectionStatusOf(renderRef, intentRef)), Sql.Time(now)).ConfigureAwait(false);
    }

    private static async Task ValidateLearningReferenceAsync(NpgsqlConnection conn, NpgsqlTransaction tx, V9EventInput input, CancellationToken ct)
    {
        if (!input.Topic.StartsWith("aijade.learning.proposed.", StringComparison.Ordinal))
            return;
        var p = input.Payload;
        var renderRef = Str(p, "render_ref") ?? "";
        if (renderRef == input.TraceId || renderRef == input.EventId || renderRef == input.IdempotencyKey)
        {
            throw new RenderTraceContractException(RenderTraceFailure.SelfReference,
                $"render_ref={renderRef} equals trace_id/event_id/idempotency_key (trace={input.TraceId})");
        }
        var trace = (await Sql.QueryAsync(conn, tx, $"SELECT {TraceColumns} FROM render_traces WHERE render_ref = $1 LIMIT 1", MapTrace, ct,
            Sql.Text(renderRef)).ConfigureAwait(false)).FirstOrDefault();
        // Three rules judged separately, each with its own reason (§6.4): a missing pairing and drifted identity are different failures.
        if (trace is null)
            throw new RenderTraceContractException(RenderTraceFailure.RenderRefNotFound, $"render_ref={renderRef}");
        if (string.IsNullOrEmpty(trace.IntentRef))
            throw new RenderTraceContractException(RenderTraceFailure.IntentRefMissing, $"render_ref={renderRef}");
        if (trace.AppliedParamsHash != Str(p, "applied_params_hash"))
        {
            throw new RenderTraceContractException(RenderTraceFailure.AppliedParamsHashMismatch,
                $"render_ref={renderRef} stored={trace.AppliedParamsHash} proposed={Str(p, "applied_params_hash")}");
        }
        if (trace.AssetVersionHash != Str(p, "asset_version_hash"))
        {
            throw new RenderTraceContractException(RenderTraceFailure.AssetVersionHashMismatch,
                $"render_ref={renderRef} stored={trace.AssetVersionHash} proposed={Str(p, "asset_version_hash")}");
        }
        // Known boundary: intent_ref can only be checked for presence — a learning proposal carries no second domain identity to compare.
    }
}
