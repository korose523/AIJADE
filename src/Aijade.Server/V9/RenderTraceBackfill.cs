using System.Text.Json.Nodes;

using Aijade.Server.Infrastructure;

using Npgsql;

namespace Aijade.Server.V9;

// Offline backfill of the render_traces projection (v10 §6.3 / §12.1): historical persona.render_requested and
// lpm.render_ready events are paired by trace and replayed into projection rows. Planning is a pure function; landing is
// idempotent (existing traces skipped, inserts ON CONFLICT DO NOTHING). A trace without a receipt yields no row — a gap is
// left rather than an identity invented.

public sealed record BackfillEvent(string EventId, string TraceId, string CorrelationId, string Topic, JsonObject Payload, double Timestamp);

public sealed record BackfillRow(
    string Id, string SessionId, string TraceId, string CorrelationId, string EventId, string? PersonaSnapshotRef, string? IntentRef, string? RenderRef,
    string? AppliedParamsHash, string? AssetVersionHash, string? RenderReadyEventId, string? PersonaRenderRequestedEventId, string ProjectionStatus);

public sealed record BackfillGap(string TraceId, string Reason);

public sealed record BackfillPlan(IReadOnlyList<BackfillRow> Rows, IReadOnlyList<BackfillGap> Incomplete, IReadOnlyList<BackfillGap> Conflicts);

public sealed record BackfillReport(
    int ScannedEvents, int PlannedRows, int Inserted, int SkippedExisting, int SkippedConflict, IReadOnlyList<BackfillGap> Incomplete, IReadOnlyList<BackfillGap> Conflicts);

public static class RenderTraceBackfill
{
    private static string? Read(JsonObject p, string key) => p[key] is JsonValue v && v.TryGetValue<string>(out var s) && s.Length > 0 ? s : null;

    /// <summary>Pure and deterministic: ids derive from the trace (rt_{trace}); rows are sorted by trace id.</summary>
    public static BackfillPlan Plan(IEnumerable<BackfillEvent> events)
    {
        var rows = new List<BackfillRow>();
        var incomplete = new List<BackfillGap>();
        var conflicts = new List<BackfillGap>();
        foreach (var bucket in events.GroupBy(e => e.TraceId, StringComparer.Ordinal))
        {
            var ordered = bucket.OrderBy(e => e.Timestamp).ToList();
            var request = ordered.FirstOrDefault(e => e.Topic == V9EventService.PersonaRenderRequested);
            var ready = ordered.FirstOrDefault(e => e.Topic == V9EventService.LpmRenderReady);
            if (ready is null)
            {
                incomplete.Add(new(bucket.Key, "missing_lpm_render_ready"));
                continue;
            }
            var readySession = Read(ready.Payload, "session_id");
            var requestSession = request is null ? null : Read(request.Payload, "session_id");
            if (request is not null && requestSession is not null && readySession is not null && requestSession != readySession)
            {
                conflicts.Add(new(bucket.Key, "session_id_mismatch_between_request_and_ready"));
                continue;
            }
            var sessionId = readySession ?? requestSession;
            if (sessionId is null)
            {
                incomplete.Add(new(bucket.Key, "missing_session_id"));
                continue;
            }
            var renderRef = Read(ready.Payload, "render_ref");
            var intentRef = request is null ? null : Read(request.Payload, "intent_ref");
            rows.Add(new BackfillRow($"rt_{bucket.Key}", sessionId, bucket.Key, (request ?? ready).CorrelationId, ready.EventId,
                request is null ? null : Read(request.Payload, "persona_snapshot_ref"), intentRef, renderRef, Read(ready.Payload, "applied_params_hash"),
                Read(ready.Payload, "asset_version_hash"), ready.EventId, request?.EventId, V9EventService.ProjectionStatusOf(renderRef, intentRef)));
        }
        rows.Sort((a, b) => string.CompareOrdinal(a.TraceId, b.TraceId));
        return new BackfillPlan(rows, incomplete, conflicts);
    }

    public static async Task<BackfillReport> RunAsync(NpgsqlDataSource db, bool dryRun = false, CancellationToken ct = default)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        var events = await Sql.QueryAsync(conn, null,
            "SELECT event_id, trace_id, correlation_id, topic, payload::text, \"timestamp\" FROM events WHERE topic = ANY($1) ORDER BY \"timestamp\"",
            r => new BackfillEvent(r.GetString(0), r.GetString(1), r.GetString(2), r.GetString(3), r.IsDBNull(4) ? [] : JsonNode.Parse(r.GetString(4)) as JsonObject ?? [],
                Sql.UnixMs(r, 5)), ct, Sql.TextArray([V9EventService.PersonaRenderRequested, V9EventService.LpmRenderReady])).ConfigureAwait(false);
        var plan = Plan(events);
        int inserted = 0, skippedExisting = 0, skippedConflict = 0;
        if (!dryRun)
        {
            foreach (var row in plan.Rows)
            {
                if (await Sql.CountAsync(conn, null, "SELECT count(*) FROM render_traces WHERE trace_id = $1", ct, Sql.Text(row.TraceId)).ConfigureAwait(false) > 0)
                {
                    skippedExisting++;
                    continue;
                }
                var written = await Sql.ExecAsync(conn, null,
                    "INSERT INTO render_traces (id, session_id, trace_id, correlation_id, event_id, persona_snapshot_ref, intent_ref, render_ref, applied_params_hash, " +
                    "asset_version_hash, render_ready_event_id, persona_render_requested_event_id, projection_status) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13) " +
                    "ON CONFLICT DO NOTHING", ct,
                    Sql.Text(row.Id), Sql.Text(row.SessionId), Sql.Text(row.TraceId), Sql.Text(row.CorrelationId), Sql.Text(row.EventId), Sql.Text(row.PersonaSnapshotRef),
                    Sql.Text(row.IntentRef), Sql.Text(row.RenderRef), Sql.Text(row.AppliedParamsHash), Sql.Text(row.AssetVersionHash), Sql.Text(row.RenderReadyEventId),
                    Sql.Text(row.PersonaRenderRequestedEventId), Sql.Text(row.ProjectionStatus)).ConfigureAwait(false);
                if (written > 0)
                    inserted++;
                else
                    skippedConflict++;
            }
        }
        return new BackfillReport(events.Count, plan.Rows.Count, inserted, skippedExisting, skippedConflict, plan.Incomplete, plan.Conflicts);
    }
}
