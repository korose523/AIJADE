using System.Text.Json.Nodes;

using Aijade.Server.Infrastructure;

using Npgsql;

namespace Aijade.Server.V9;

/// <summary>The four configurations of experiments/plans/2026-11-05-p1-a-alternative-designs.md; only that study sets another than Paper.</summary>
public enum V9AlternativeDesign
{
    Paper,
    LiberalAcceptance,
    ConsumerContracts,
    AfterTheFactLineage,
}

/// <summary>
/// The alternatives of P1-A at the event endpoint, set by the configuration key <c>Aijade:P1aConfiguration</c>, which no deployment
/// sets. Each replaces only the mechanism it names: liberal acceptance tolerates unknown keys and fills missing fields, consumer
/// contracts validate no schema at run time (what a consumer cannot read fails there), after-the-fact lineage refuses nothing
/// at writing and leaves it to <see cref="AuditAsync"/>.
/// </summary>
public static class V9Alternative
{
    public const string ConfigKey = "Aijade:P1aConfiguration";

    public static V9AlternativeDesign Of(IConfiguration config) => config[ConfigKey] switch
    {
        "liberal" => V9AlternativeDesign.LiberalAcceptance,
        "contracts" => V9AlternativeDesign.ConsumerContracts,
        "lineage" => V9AlternativeDesign.AfterTheFactLineage,
        _ => V9AlternativeDesign.Paper,
    };

    public static async Task<IResult> PostEventAsync(V9AlternativeDesign design, JsonNode? body, V9EventService events, ServerRuntime runtime, CancellationToken ct)
    {
        if (body is not JsonObject env)
            throw ApiException.BadRequest("not a JSON object", "INVALID_V9_EVENT");
        if (design != V9AlternativeDesign.ConsumerContracts)
            Fill(env);
        if (design == V9AlternativeDesign.LiberalAcceptance)
            CheckTolerant(env);

        V9EventInput input;
        try
        {
            input = V9EventInput.FromEnvelope(env, env["payload"]!.AsObject());
        }
        catch (Exception e) when (e is NullReferenceException or InvalidOperationException or FormatException or KeyNotFoundException)
        {
            // the first consumer of the record cannot read it
            throw ApiException.BadRequest("a consumer could not read the event", "CONSUMER_UNREADABLE");
        }
        AppendEventResult appended;
        try
        {
            appended = await events.AppendEventAsync(input, design != V9AlternativeDesign.AfterTheFactLineage, ct).ConfigureAwait(false);
        }
        catch (RenderTraceContractException e)
        {
            throw ApiException.BadRequest(e.PublicMessage, "INVALID_RENDER_TRACE_REFERENCE");
        }
        if (!appended.Deduped && input.Topic.StartsWith("aijade.video.observation.", StringComparison.Ordinal))
            await runtime.DispatchVideoObservationAsync(input, ct).ConfigureAwait(false);
        return Results.Json(new JsonObject { ["ok"] = true, ["deduped"] = appended.Deduped, ["eventId"] = appended.Row.EventId }, statusCode: appended.Deduped ? 200 : 201);
    }

    private static void Fill(JsonObject env)
    {
        V9Boundary.Envelope.FillMissing(env);
        var topic = env["topic"]?.GetValue<string>() ?? "";
        if (V9Boundary.RequiresV10(topic))
        {
            if (!env.ContainsKey("tick"))
                env["tick"] = 0;
            if (env["causality"] is not JsonObject)
                env["causality"] = new JsonObject { ["inputHash"] = "unknown" };
        }
        if (env["payload"] is JsonObject payload && V9Boundary.Payloads.TryGetValue(topic, out var rule) && rule is R.StrictRule strict)
            strict.FillMissing(payload);
    }

    /// <summary>The boundary's rules with unknown keys tolerated; a field that is present and wrong is still refused.</summary>
    private static void CheckTolerant(JsonObject env)
    {
        R.StrictRule.TolerateUnknownKeys = true;
        try
        {
            var issues = V9Boundary.Envelope.Validate(env);
            if (issues.Count > 0)
                throw ApiException.BadRequest("Invalid v9 event envelope", "INVALID_V9_EVENT", issues);
            var topic = env["topic"]!.GetValue<string>();
            issues = V9Boundary.Payloads[topic].Validate(env["payload"]);
            if (issues.Count > 0)
                throw ApiException.BadRequest($"Invalid payload for topic '{topic}'", "INVALID_V9_PAYLOAD", issues);
        }
        finally
        {
            R.StrictRule.TolerateUnknownKeys = false;
        }
    }

    /// <summary>What the audit job lists from the stored data: references that name nothing stored, and identities left unpaired.</summary>
    public static async Task<IReadOnlyList<string>> AuditAsync(NpgsqlDataSource db, CancellationToken ct = default)
    {
        const string Sql0 = """
            SELECT 'proposal without a stored render: ' || e.event_id FROM events e
             WHERE e.topic LIKE 'aijade.learning.proposed.%'
               AND NOT EXISTS (SELECT 1 FROM render_traces t WHERE t.render_ref = e.payload->>'render_ref')
            UNION ALL
            SELECT 'reference to no stored event: ' || e.event_id || ' -> ' || r FROM events e, unnest(e.evidence_refs || e.causal_context_refs) r
             WHERE NOT EXISTS (SELECT 1 FROM events x WHERE x.event_id = r)
            UNION ALL
            SELECT 'write id of no stored event: ' || e.event_id || ' -> ' || r FROM events e, jsonb_array_elements_text(e.payload->'candidate_memory_write_ids') r
             WHERE e.topic = 'aijade.evidence.weave_candidate_ready' AND NOT EXISTS (SELECT 1 FROM events x WHERE x.event_id = r)
            UNION ALL
            SELECT 'unpaired identity: ' || t.trace_id FROM render_traces t WHERE t.projection_status <> 'paired'
            """;
        var found = new List<string>();
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        await using var cmd = new NpgsqlCommand(Sql0, conn);
        await using var reader = await cmd.ExecuteReaderAsync(ct).ConfigureAwait(false);
        while (await reader.ReadAsync(ct).ConfigureAwait(false))
            found.Add(reader.GetString(0));
        return found;
    }
}
