using System.Globalization;
using System.Text.Json;
using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Memory.Kernel;
using Aijade.Memory.Pgc;
using Aijade.Memory.V9;
using Aijade.Server.Auth;
using Aijade.Server.Infrastructure;
using Aijade.Server.Memory;

using Npgsql;

namespace Aijade.Server.V9;


public static class V9Endpoints
{
    private static readonly HashSet<string> VideoObservationTopics = new(StringComparer.Ordinal)
    {
        "aijade.video.observation.webpage_text",
        "aijade.video.observation.video_transcript",
    };

    /// <summary>The commit-reason chain of the PGC gate, in its fixed order.</summary>
    public static IReadOnlyList<string> CommitReasonChain { get; } =
        ["w_max_below_theta", "contradiction_high", "evidence_insufficient", "fatigue_deferred", "w_below_theta", "committed"];

    private const double FloatEpsilon = 1e-12;

    public static async Task<JsonNode?> ReadJsonAsync(HttpRequest request, string code, CancellationToken ct)
    {
        try
        {
            return await JsonNode.ParseAsync(request.Body, cancellationToken: ct).ConfigureAwait(false);
        }
        catch (JsonException)
        {
            throw ApiException.BadRequest("Invalid JSON body", code);
        }
    }

    public static void Map(IEndpointRouteBuilder app)
    {
        if (V9Boundary.TopicsWithoutPayloadRule.Count > 0)
            throw new InvalidOperationException($"v9 topic(s) missing a payload schema: {string.Join(", ", V9Boundary.TopicsWithoutPayloadRule)}");

        var v9 = app.MapGroup("/api/v1/v9").RequireAuthorization();
        v9.MapPost("/events", PostEventAsync);
        v9.MapPost("/perception", PostPerceptionAsync);
        v9.MapPost("/persona/derive", DerivePersonaAsync);
        v9.MapPost("/replay", ReplayAsync);
        v9.MapGet("/evidence-domain/{sessionId}", async (string sessionId, EvidenceDomainService domain, CancellationToken ct) =>
            Results.Json(await domain.GetAsync(sessionId, ct).ConfigureAwait(false), JsonSerializerOptions.Web));
    }

    /// <summary>
    /// POST /api/v1/v9/events: envelope → (v10 fields for video / learning topics) → topic payload → append. A failed
    /// observation dispatch after the event is stored is logged and dead-lettered, never turned into an error response:
    /// the stored event is a fact, and a sink failure must not leak upstream.
    /// </summary>
    private static async Task<IResult> PostEventAsync(HttpRequest request, V9EventService events, ServerRuntime runtime, ILoggerFactory logs, CancellationToken ct)
    {
        var body = await ReadJsonAsync(request, "INVALID_V9_EVENT", ct).ConfigureAwait(false);
        var envIssues = V9Boundary.Envelope.Validate(body);
        if (envIssues.Count > 0)
            throw ApiException.BadRequest("Invalid v9 event envelope", "INVALID_V9_EVENT", envIssues);
        var env = body!.AsObject();
        var topic = env["topic"]!.GetValue<string>();
        if (V9Boundary.RequiresV10(topic))
        {
            var v10 = new JsonObject();
            if (env.ContainsKey("tick"))
                v10["tick"] = env["tick"]!.DeepClone();
            if (env.ContainsKey("causality"))
                v10["causality"] = env["causality"]!.DeepClone();
            var v10Issues = V9Boundary.V10Fields.Validate(v10);
            if (v10Issues.Count > 0)
                throw ApiException.BadRequest("v10 video/learning events require tick and causality.inputHash", "INVALID_V10_EVENT", v10Issues);
        }
        var payload = env["payload"]!.AsObject();
        var payloadIssues = V9Boundary.Payloads[topic].Validate(payload);
        if (payloadIssues.Count > 0)
            throw ApiException.BadRequest($"Invalid payload for topic '{topic}'", "INVALID_V9_PAYLOAD", payloadIssues);

        var input = V9EventInput.FromEnvelope(env, payload);
        AppendEventResult appended;
        try
        {
            appended = await events.AppendEventAsync(input, ct).ConfigureAwait(false);
        }
        catch (RenderTraceContractException e)
        {
            logs.CreateLogger("v9-events").LogWarning("render trace contract rejected at the boundary: {Reason} (trace {TraceId}, topic {Topic})",
                WireName.Of(e.Reason), input.TraceId, topic);
            throw ApiException.BadRequest(e.PublicMessage, "INVALID_RENDER_TRACE_REFERENCE");
        }

        if (!appended.Deduped && VideoObservationTopics.Contains(topic))
            await runtime.DispatchVideoObservationAsync(input, ct).ConfigureAwait(false);

        return Results.Json(new JsonObject
        {
            ["ok"] = true,
            ["deduped"] = appended.Deduped,
            ["eventId"] = appended.Row.EventId,
            ["pairingMissing"] = appended.PairingMissing,
        }, statusCode: appended.Deduped ? 200 : 201);
    }

    private static double D(JsonNode? n) => double.Parse(n!.ToJsonString(), CultureInfo.InvariantCulture);

    private static async Task<IResult> PostPerceptionAsync(HttpRequest request, HttpContext context, ServerRuntime runtime, NpgsqlDataSource db, CancellationToken ct)
    {
        var body = await ReadJsonAsync(request, "INVALID_V9_PERCEPTION", ct).ConfigureAwait(false);
        var issues = V9Boundary.Perception.Validate(body);
        if (issues.Count > 0)
            throw ApiException.BadRequest("Invalid v9 perception input", "INVALID_V9_PERCEPTION", issues);
        var o = body!.AsObject();
        // A memory session belongs to the account that first wrote into it.
        if (!await Memory.MemoryLibrary.ClaimSessionAsync(db, o["session_id"]!.GetValue<string>(), context.User.UserId(), ct).ConfigureAwait(false))
            throw ApiException.Forbidden("this memory session belongs to another account");
        Dictionary<StimulusFeature, double>? stimulus = null;
        if (o["stimulus_features"] is JsonObject sf)
        {
            stimulus = [];
            foreach (var (k, v) in sf)
            {
                if (Enum.TryParse<StimulusFeature>(k, true, out var f) || TryWire(k, out f))
                    stimulus[f] = D(v);
            }
        }
        var input = new V9PerceptionInput(o["event_id"]!.GetValue<string>(), o["session_id"]!.GetValue<string>(), o["trace_id"]!.GetValue<string>(),
            o["correlation_id"]!.GetValue<string>(), D(o["timestamp"]), o["origin_device"]!.GetValue<string>(), (int)D(o["privacy_level"]), D(o["risk_score"]),
            o["source"]!.GetValue<string>(), o["content"]!.GetValue<string>(), stimulus, o["risk_level"]?.GetValue<string>());
        if (runtime.QueueIsDurable)
        {
            await runtime.Queue.EnqueueAsync(Queues.Perception, new JsonObject { ["jobId"] = Ids.New(), ["input"] = JsonSerializer.SerializeToNode(input, JsonSerializerOptions.Web) }, ct).ConfigureAwait(false);
            return Results.Json(new JsonObject { ["ok"] = true, ["queued"] = true }, statusCode: 202);
        }
        var processed = await runtime.Runtime.ProcessPerceptionAsync(input, ct).ConfigureAwait(false);
        return Results.Json(new JsonObject
        {
            ["ok"] = true,
            ["txId"] = processed.Tx.TxId,
            ["status"] = WireName.Of(processed.Tx.Status),
            ["committedCount"] = processed.Tx.Committed.Count,
            ["rejectedCount"] = processed.Tx.Rejected.Count,
            ["throttledCount"] = processed.Tx.Throttled.Count,
        }, statusCode: 201);
    }

    private static bool TryWire(string k, out StimulusFeature f)
    {
        try
        {
            f = WireName.Parse<StimulusFeature>(k);
            return true;
        }
        catch (ArgumentException)
        {
            f = default;
            return false;
        }
    }

    /// <summary>POST /api/v1/v9/persona/derive: 400 malformed, 422 NO_EVIDENCE when the session has nothing to derive from — never 200 with an empty intent.</summary>
    private static async Task<IResult> DerivePersonaAsync(HttpRequest request, HttpContext context, LongTermMemoryService memory, CancellationToken ct)
    {
        var body = await ReadJsonAsync(request, "INVALID_V9_PERSONA", ct).ConfigureAwait(false);
        var issues = V9Boundary.PersonaDerive.Validate(body);
        if (issues.Count > 0)
            throw ApiException.BadRequest("Invalid v9 persona derive request", "INVALID_V9_PERSONA", issues);
        var o = body!.AsObject();
        try
        {
            var (snapshot, intent) = await memory.DeriveForSessionAsync(new DeriveInput(context.User.UserId(), o["session_id"]!.GetValue<string>(),
                o["device_id"]!.GetValue<string>(), (int)D(o["privacy_level"]), o["agent_id"]!.GetValue<string>(), o["user_scope"]!.GetValue<string>(),
                o["step_count"] is { } sc ? (int)D(sc) : null, o["duration"] is { } du ? (int)D(du) : null), ct).ConfigureAwait(false);
            return Results.Json(new JsonObject
            {
                ["persona_snapshot_ref"] = snapshot["id"]!.DeepClone(),
                ["intent_ref"] = intent["id"]!.DeepClone(),
                ["intent"] = intent["intent"]!.DeepClone(),
            });
        }
        catch (NoEvidenceException)
        {
            throw new ApiException(422, "NO_EVIDENCE", "no committed long-term memory found for session");
        }
    }

    private static bool IsReplayableV6(JsonNode? v6) =>
        v6 is JsonObject o
        && o["tau"] is JsonValue t && t.GetValueKind() == JsonValueKind.String
        && o["s"]?["f"] is JsonValue f && f.GetValueKind() == JsonValueKind.Number
        && o["w_max_global"] is JsonValue g && g.GetValueKind() == JsonValueKind.Number && double.IsFinite(D(g))
        && o["w_max_at_f"] is JsonValue af && af.GetValueKind() == JsonValueKind.Number && double.IsFinite(D(af))
        && o["commit_reason"] is JsonValue c && c.GetValueKind() == JsonValueKind.String;

    /// <summary>
    /// POST /api/v1/v9/replay (v10 §4.3 / §11.3): for one input snapshot (tick + inputHash), recompute — with the current
    /// code — the endogenous facts that were recorded and compare. Not a tautology: the core state node is re-derived from
    /// the database fact of a persisted memory version, and w_max_* from the persisted tau and s.f through the current bounds
    /// function. A row without the needed snapshot is reported as insufficient, never as consistent.
    /// </summary>
    private static async Task<IResult> ReplayAsync(HttpRequest request, NpgsqlDataSource db, CancellationToken ct)
    {
        var body = await ReadJsonAsync(request, "INVALID_V9_REPLAY", ct).ConfigureAwait(false);
        var issues = V9Boundary.Replay.Validate(body);
        if (issues.Count > 0)
            throw ApiException.BadRequest("Invalid v9 replay request", "INVALID_V9_REPLAY", issues);
        var tick = (int)D(body!["tick"]);
        var inputHash = body["inputHash"]!.GetValue<string>();

        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        var events = await Sql.QueryAsync(conn, null,
            "SELECT event_id, trace_id, topic, core_state_node FROM events WHERE tick = $1 AND causality ->> 'inputHash' = $2",
            r => (EventId: r.GetString(0), TraceId: r.GetString(1), Topic: r.GetString(2), Node: Sql.NullableString(r, 3)), ct, Sql.P(tick), Sql.Text(inputHash)).ConfigureAwait(false);
        if (events.Count == 0)
        {
            return Results.Json(new JsonObject
            {
                ["ok"] = false, ["reason"] = "no_events_for_snapshot", ["tick"] = tick, ["inputHash"] = inputHash, ["checked"] = 0,
                ["mismatches"] = new JsonArray(), ["insufficient"] = new JsonArray(),
            }, statusCode: 404);
        }
        var traceIds = events.Select(e => e.TraceId).Distinct(StringComparer.Ordinal).ToArray();
        var withVersion = (await Sql.QueryAsync(conn, null,
            "SELECT t.trace_id FROM memory_versions v JOIN memory_txs t ON t.id = v.memory_tx_id WHERE t.trace_id = ANY($1)",
            r => r.GetString(0), ct, Sql.TextArray(traceIds)).ConfigureAwait(false)).ToHashSet(StringComparer.Ordinal);

        // Decision-level snapshots (write plan entries) first; the state-level pgc_states row only as a fallback.
        var v6Sources = new List<(string TraceId, JsonNode V6)>();
        var tracesWithV6 = new HashSet<string>(StringComparer.Ordinal);
        foreach (var (traceId, plan) in await Sql.QueryAsync(conn, null, "SELECT trace_id, write_plan::text FROM pgc_write_plans WHERE trace_id = ANY($1)",
            r => (r.GetString(0), JsonNode.Parse(r.GetString(1))), ct, Sql.TextArray(traceIds)).ConfigureAwait(false))
        {
            if (plan is not JsonArray entries)
                continue;
            foreach (var entry in entries)
            {
                var v6 = entry?["pgcStateSnapshot"]?["v6"];
                if (!IsReplayableV6(v6))
                    continue;
                v6Sources.Add((traceId, v6!));
                tracesWithV6.Add(traceId);
            }
        }
        foreach (var (traceId, v6) in await Sql.QueryAsync(conn, null, "SELECT trace_id, v6_state::text FROM pgc_states WHERE trace_id = ANY($1)",
            r => (r.GetString(0), JsonNode.Parse(r.GetString(1))), ct, Sql.TextArray(traceIds)).ConfigureAwait(false))
        {
            if (tracesWithV6.Contains(traceId) || !IsReplayableV6(v6))
                continue;
            v6Sources.Add((traceId, v6!));
            tracesWithV6.Add(traceId);
        }

        var mismatches = new JsonArray();
        var insufficient = new JsonArray();
        var nodes = new JsonArray();
        foreach (var e in events)
        {
            var hasVersion = withVersion.Contains(e.TraceId);
            if (e.Node is null)
            {
                insufficient.Add(new JsonObject { ["kind"] = "missing_core_state_node", ["eventId"] = e.EventId, ["traceId"] = e.TraceId, ["missing"] = new JsonArray("core_state_node") });
                continue;
            }
            nodes.Add(e.Node);
            var recomputed = CoreStateNodes.Derive(e.Topic, hasVersion).ToString();
            if (recomputed != e.Node)
                mismatches.Add(Mismatch("core_state_node_mismatch", e.EventId, e.TraceId, e.Topic, e.Node, recomputed));
            if (e.Node == "S8" && !hasVersion)
                mismatches.Add(Mismatch("s8_without_memory_version", e.EventId, e.TraceId, e.Topic, "S8", "S6"));
            if (e.Node == "S6" && hasVersion)
                mismatches.Add(Mismatch("s6_with_memory_version", e.EventId, e.TraceId, e.Topic, "S6", "S8"));
        }
        foreach (var traceId in traceIds.Where(t => !tracesWithV6.Contains(t)))
        {
            insufficient.Add(new JsonObject
            {
                ["kind"] = "missing_v6_snapshot", ["traceId"] = traceId,
                ["missing"] = new JsonArray("pgc_write_plans.write_plan[].pgcStateSnapshot.v6", "pgc_states.v6_state.tau", "pgc_states.v6_state.s.f"),
            });
        }
        var reasons = new JsonArray();
        foreach (var (traceId, v6) in v6Sources)
        {
            var reason = v6["commit_reason"]!.GetValue<string>();
            reasons.Add(reason);
            if (!CommitReasonChain.Contains(reason))
                mismatches.Add(new JsonObject { ["kind"] = "commit_reason_outside_fixed_chain", ["traceId"] = traceId, ["recorded"] = reason });
            var (wMaxGlobal, wMaxAtF) = PgcGate.ComputeV6WMaxBounds(WireName.Parse<Tau>(v6["tau"]!.GetValue<string>()), PgcGate.ParamsCase4, D(v6["s"]!["f"]));
            if (Math.Abs(wMaxGlobal - D(v6["w_max_global"])) > FloatEpsilon)
                mismatches.Add(new JsonObject { ["kind"] = "w_max_global_drift", ["traceId"] = traceId, ["recorded"] = D(v6["w_max_global"]), ["recomputed"] = wMaxGlobal });
            if (wMaxAtF is { } atF && Math.Abs(atF - D(v6["w_max_at_f"])) > FloatEpsilon)
                mismatches.Add(new JsonObject { ["kind"] = "w_max_at_f_drift", ["traceId"] = traceId, ["recorded"] = D(v6["w_max_at_f"]), ["recomputed"] = atF });
        }
        var result = new JsonObject
        {
            ["tick"] = tick, ["inputHash"] = inputHash, ["checked"] = events.Count, ["coreStateNodes"] = nodes, ["commitReasons"] = reasons,
            ["mismatches"] = mismatches, ["insufficient"] = insufficient,
        };
        if (mismatches.Count > 0)
            return Results.Json(Prefix(false, "mismatch", result));
        if (insufficient.Count > 0)
            return Results.Json(Prefix(false, "insufficient_input_snapshot", result));
        return Results.Json(Prefix(true, null, result));
    }

    private static JsonObject Mismatch(string kind, string eventId, string traceId, string topic, string recorded, string recomputed) => new()
    {
        ["kind"] = kind, ["eventId"] = eventId, ["traceId"] = traceId, ["topic"] = topic, ["recorded"] = recorded, ["recomputed"] = recomputed,
    };

    private static JsonObject Prefix(bool ok, string? reason, JsonObject rest)
    {
        var o = new JsonObject { ["ok"] = ok };
        if (reason is not null)
            o["reason"] = reason;
        foreach (var (k, v) in rest.ToList())
        {
            rest.Remove(k);
            o[k] = v;
        }
        return o;
    }
}
