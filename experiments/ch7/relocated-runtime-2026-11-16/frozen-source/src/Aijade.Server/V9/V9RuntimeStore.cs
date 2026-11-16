using System.Globalization;
using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Memory.Dynamics;
using Aijade.Memory.Pgc;
using Aijade.Memory.V9;
using Aijade.Server.Infrastructure;

using Npgsql;

namespace Aijade.Server.V9;

// The durable adapter of the kernel runtime: one artifact is persisted in one database transaction, so a failure rolls
// back every stage of the causal chain. Observation context and the v10 provenance columns come from the kernel's
// envelopes as they are — never synthesised here (a synthesised device name or a banded risk score is a forged field).

public sealed class V9RuntimeStore(NpgsqlDataSource db) : IV9RuntimeStore
{
    private static double Num(JsonNode? n) => double.Parse(n!.ToJsonString(), CultureInfo.InvariantCulture);

    /// <summary>The stored JSON of a write-plan entry: camelCase row keys around the snake_case PGC snapshot (which replay reads).</summary>
    public static JsonObject WritePlanEntryJson(PgcWritePlanEntryRow e) => new()
    {
        ["memoryWriteId"] = e.MemoryWriteId,
        ["decision"] = WireName.Of(e.Decision),
        ["finalIntensity"] = e.FinalIntensity,
        ["reasonCodes"] = new JsonArray([.. e.ReasonCodes.Select(c => (JsonNode)WireName.Of(c))]),
        ["expectedTests"] = new JsonArray([.. e.ExpectedTests.Select(t => (JsonNode)t)]),
        ["pgcStateId"] = e.PgcStateId,
        ["pgcStateSnapshot"] = PgcJson.Snapshot(e.PgcStateSnapshot),
    };

    public static JsonObject ContradictionJson(ContradictionReport r)
    {
        var o = new JsonObject();
        if (r.ConflictingEvidenceIds is { } ids)
            o["conflicting_evidence_ids"] = new JsonArray([.. ids.Select(i => (JsonNode)i)]);
        o["severity"] = r.Severity;
        return o;
    }

    public static PgcStateComponents ParseComponents(JsonNode n)
    {
        var p = n["plasticity"]!;
        return new PgcStateComponents(
            new PlasticityGate(Num(p["consolidationGain"]), Num(p["decayMultiplier"]), Num(p["retrievalNoise"]), Num(p["moodCongruenceWeight"]),
                Num(p["socialBonus"]), Num(p["explorationTemperature"])),
            Num(n["evidence_strength"]), Num(n["contradiction_severity"]), Num(n["evidence_uncertainty"]), Num(n["persona_shift_risk"]));
    }

    public static PgcState4 ParseState(JsonNode n) => new(Num(n["a"]), Num(n["c"]), Num(n["d"]), Num(n["f"]));

    public async Task<PgcStateRow?> ReadLatestPgcStateAsync(string sessionId, CancellationToken cancellationToken = default)
    {
        await using var conn = await db.OpenConnectionAsync(cancellationToken).ConfigureAwait(false);
        return (await Sql.QueryAsync(conn, null,
            "SELECT id, session_id, trace_id, policy_version, components::text, v6_state::text, created_at FROM pgc_states WHERE session_id = $1 ORDER BY created_at DESC LIMIT 1",
            r => new PgcStateRow(r.GetString(0), r.GetString(1), r.GetString(2), r.GetString(3), ParseComponents(JsonNode.Parse(r.GetString(4))!),
                ParseState(JsonNode.Parse(r.GetString(5))!), Sql.UnixMs(r, 6)), cancellationToken, Sql.Text(sessionId)).ConfigureAwait(false)).FirstOrDefault();
    }

    public async Task PersistAsync(V9RuntimeArtifact artifact, CancellationToken cancellationToken = default)
    {
        var ct = cancellationToken;
        var a = artifact;
        if (a.MemoryTx.Status != TxStatus.Committed && a.MemoryVersions.Count > 0)
            throw new InvalidOperationException("v9 runtime invariant violated: non-committed transaction has versions");
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        if (await Sql.CountAsync(conn, null, "SELECT count(*) FROM memory_txs WHERE id = $1", ct, Sql.Text(a.MemoryTx.Id)).ConfigureAwait(false) > 0)
            return;

        await using var tx = await conn.BeginTransactionAsync(ct).ConfigureAwait(false);
        await Sql.ExecAsync(conn, tx, "INSERT INTO evidence_packs (id, session_id, source, created_at, note) VALUES ($1,$2,$3,$4,$5)", ct,
            Sql.Text(a.EvidencePack.Id), Sql.Text(a.EvidencePack.SessionId), Sql.Text(a.EvidencePack.Source), Sql.TimeMs(a.EvidencePack.CreatedAt),
            Sql.Text(a.EvidencePack.Note)).ConfigureAwait(false);
        await Sql.ExecAsync(conn, tx, "INSERT INTO evidence_chunks (id, pack_id, idx, content, created_at) VALUES ($1,$2,$3,$4,$5)", ct,
            Sql.Text(a.EvidenceChunk.Id), Sql.Text(a.EvidenceChunk.PackId), Sql.Text(a.EvidenceChunk.Idx.ToString(CultureInfo.InvariantCulture)),
            Sql.Text(a.EvidenceChunk.Content), Sql.TimeMs(a.EvidenceChunk.CreatedAt)).ConfigureAwait(false);
        await Sql.ExecAsync(conn, tx, "INSERT INTO pgc_states (id, session_id, trace_id, policy_version, components, v6_state, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7)", ct,
            Sql.Text(a.PgcState.Id), Sql.Text(a.PgcState.SessionId), Sql.Text(a.PgcState.TraceId), Sql.Text(a.PgcState.PolicyVersion),
            Sql.Jsonb(PgcJson.Components(a.PgcState.Components)), Sql.Jsonb(PgcJson.State(a.PgcState.V6State)), Sql.TimeMs(a.PgcState.CreatedAt)).ConfigureAwait(false);
        var plan = a.PgcWritePlan;
        await Sql.ExecAsync(conn, tx,
            "INSERT INTO pgc_write_plans (id, pgc_state_id, session_id, trace_id, policy_version, write_plan, contradiction_report, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8)", ct,
            Sql.Text(plan.Id), Sql.Text(plan.PgcStateId), Sql.Text(plan.SessionId), Sql.Text(plan.TraceId), Sql.Text(plan.PolicyVersion),
            Sql.Jsonb(new JsonArray([.. plan.WritePlan.Select(e => (JsonNode)WritePlanEntryJson(e))])), Sql.Jsonb(ContradictionJson(plan.ContradictionReport)),
            Sql.TimeMs(plan.CreatedAt)).ConfigureAwait(false);
        await Sql.ExecAsync(conn, tx, "INSERT INTO memory_txs (id, session_id, trace_id, atomicity, max_writes, status, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7)", ct,
            Sql.Text(a.MemoryTx.Id), Sql.Text(a.MemoryTx.SessionId), Sql.Text(a.MemoryTx.TraceId), Sql.Text(WireName.Of(a.MemoryTx.Atomicity)),
            Sql.Text(a.MemoryTx.MaxWrites.ToString(CultureInfo.InvariantCulture)), Sql.Text(WireName.Of(a.MemoryTx.Status)), Sql.TimeMs(a.MemoryTx.CreatedAt)).ConfigureAwait(false);
        foreach (var v in a.MemoryVersions)
        {
            await Sql.ExecAsync(conn, tx,
                "INSERT INTO memory_versions (id, memory_tx_id, memory_item_id, memory_write_id, memory_kind, content_hash_sha256, evidence_pack_id, evidence_ids, " +
                "pgc_state_id, intensity, durability, risk_level, created_at) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13)", ct,
                Sql.Text(v.Id), Sql.Text(v.MemoryTxId), Sql.Text(v.MemoryItemId), Sql.Text(v.MemoryWriteId), Sql.Text(WireName.Of(v.MemoryKind)),
                Sql.Text(v.ContentHashSha256), Sql.Text(v.EvidencePackId), Sql.TextArray(v.EvidenceIds), Sql.Text(v.PgcStateId),
                Sql.Text(JsFormat.Number(v.Intensity)), Sql.Text(JsFormat.Number(v.Durability)), Sql.Text(v.RiskLevel), Sql.TimeMs(v.CreatedAt)).ConfigureAwait(false);
        }
        var w = a.EvidenceWeave;
        var spec = new JsonObject { ["include_pgc_snapshot"] = w.Spec.IncludePgcSnapshot, ["include_claim_ids"] = w.Spec.IncludeClaimIds };
        if (w.Spec.IncludeEvolutionSpecId is { } evo)
            spec["include_evolution_spec_id"] = evo;
        var links = new JsonArray([.. w.Links.Select(l =>
        {
            var o = new JsonObject
            {
                ["linkId"] = l.LinkId,
                ["memoryVersionId"] = l.MemoryVersionId,
                ["evidenceIds"] = new JsonArray([.. l.EvidenceIds.Select(e => (JsonNode)e)]),
                ["pgcStateId"] = l.PgcStateId,
            };
            if (l.HypothesisId is { } h)
                o["hypothesisId"] = h;
            return (JsonNode)o;
        })]);
        await Sql.ExecAsync(conn, tx, "INSERT INTO evidence_weaves (id, tx_id, graph_hash, spec, links, created_at) VALUES ($1,$2,$3,$4,$5,$6)", ct,
            Sql.Text(w.Id), Sql.Text(w.TxId), Sql.Text(w.GraphHash), Sql.Jsonb(spec), Sql.Jsonb(links), Sql.TimeMs(w.CreatedAt)).ConfigureAwait(false);

        var used = new HashSet<string>(StringComparer.Ordinal);
        for (var index = 0; index < a.Events.Count; index++)
        {
            var e = a.Events[index];
            var baseId = e["event_id"]!.GetValue<string>();
            var id = baseId;
            for (var suffix = 1; used.Contains(id); suffix++)
                id = $"{baseId}:{index}:{suffix}";
            used.Add(id);
            await Sql.ExecAsync(conn, tx,
                "INSERT INTO events (id, event_id, trace_id, correlation_id, \"timestamp\", producer, origin_device, privacy_level, evidence_refs, causal_context_refs, " +
                "risk_score, topic, payload, idempotency_key, replay_mode, risk_level, tick, causality, core_state_node) " +
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)", ct,
                Sql.Text(id), Sql.Text(id), Sql.Text(e["trace_id"]!.GetValue<string>()), Sql.Text(e["correlation_id"]!.GetValue<string>()),
                Sql.TimeMs(Num(e["timestamp"])), Sql.Text(e["producer"]!.GetValue<string>()), Sql.Text(e["origin_device"]!.GetValue<string>()),
                Sql.P((int)Num(e["privacy_level"])), Sql.TextArray(e["evidence_refs"]!.AsArray().Select(x => x!.GetValue<string>())),
                Sql.TextArray(e["causal_context_refs"]!.AsArray().Select(x => x!.GetValue<string>())), Sql.P((float)Num(e["risk_score"])),
                Sql.Text(e["topic"]!.GetValue<string>()), Sql.Jsonb(e["payload"]), Sql.Text(e["idempotency_key"]!.GetValue<string>()),
                Sql.Text(e["replay_mode"]!.GetValue<string>()), Sql.Text(e["risk_level"]!.GetValue<string>()),
                Sql.P(e["tick"] is { } t ? (int)Num(t) : null), Sql.Jsonb(e["causality"]), Sql.Text(e["core_state_node"]?.GetValue<string>())).ConfigureAwait(false);
        }
        await tx.CommitAsync(ct).ConfigureAwait(false);
    }
}
