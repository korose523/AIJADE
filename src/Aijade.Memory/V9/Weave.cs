using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Memory.Kernel;

namespace Aijade.Memory.V9;

// EvidenceWeave, the third stage of the v9 write pipeline and the anchor of replay checks: the committed versions of one
// transaction are woven into a causal graph (version → evidence, version → PGC state, version → hypothesis). graph_hash must
// be deterministic — same input, same hash; different input, different hash — or replay comparison means nothing.

public sealed record WeaveResult(string WeaveId, string TxId, IReadOnlyList<WeaveLink> Links, string GraphHash, WeaveSpec Spec);

public static class EvidenceWeave
{
    /// <summary>Build the weave of a committed transaction. Pure apart from reading the engine's state; deterministic.</summary>
    public static WeaveResult Build(MemoryTxEngine engine, string txId, WeaveSpec spec)
    {
        var links = engine.GetVersionsForTx(txId).Select(v => new WeaveLink(
            JsFormat.Sha256Hex($"{txId}:{v.Id}")[..16], v.Id, [.. v.EvidenceIds], v.PgcStateId,
            spec.IncludeClaimIds && v.SourceClaimIds is { Count: > 0 } claims ? claims[0] : null)).ToList();
        var graphHash = GraphHash(links, spec);
        return new WeaveResult(JsFormat.Sha256Hex($"{txId}:{graphHash}")[..16], txId, links, graphHash, spec);
    }

    /// <summary>
    /// sha256 of the canonical { spec, links }. hypothesisId and include_evolution_spec_id are <c>undefined</c> when absent,
    /// and the canonical form writes the bare text
    /// <c>undefined</c> into the hashed string (e.g. <c>"hypothesisId":undefined</c>); that text is reproduced so existing
    /// graph hashes stay valid. Links are sorted by their canonical text.
    /// </summary>
    public static string GraphHash(IEnumerable<WeaveLink> links, WeaveSpec spec)
    {
        static string Opt(string? s) => s is null ? "undefined" : JsFormat.JsonString(s);
        var canonicalLinks = links.Select(l =>
            $"{{\"evidenceIds\":[{string.Join(",", l.EvidenceIds.Select(JsFormat.JsonString))}],\"hypothesisId\":{Opt(l.HypothesisId)},"
            + $"\"linkId\":{JsFormat.JsonString(l.LinkId)},\"memoryVersionId\":{JsFormat.JsonString(l.MemoryVersionId)},\"pgcStateId\":{JsFormat.JsonString(l.PgcStateId)}}}")
            .OrderBy(s => s, StringComparer.Ordinal);
        var canonicalSpec = $"{{\"include_claim_ids\":{(spec.IncludeClaimIds ? "true" : "false")},\"include_evolution_spec_id\":{Opt(spec.IncludeEvolutionSpecId)},"
            + $"\"include_pgc_snapshot\":{(spec.IncludePgcSnapshot ? "true" : "false")}}}";
        return JsFormat.Sha256Hex($"{{\"links\":[{string.Join(",", canonicalLinks)}],\"spec\":{canonicalSpec}}}");
    }

    public static EvidenceWeaveRow ToRow(WeaveResult r, double createdAt) => new(r.WeaveId, r.TxId, r.GraphHash, r.Spec, r.Links, createdAt);

    /// <summary>Wrap a weave as aijade.evidence.weave_candidate_ready (candidate_memory_write_ids carries the version ids).</summary>
    public static JsonObject BuildCandidateReadyEvent(WeaveResult r, JsonObject envelope) =>
        AijadeEvents.Build(AijadeEvents.EvidenceWeaveCandidateReady, envelope, new JsonObject
        {
            ["tx_id"] = r.TxId,
            ["weave_id"] = r.WeaveId,
            ["graph_hash"] = r.GraphHash,
            ["candidate_memory_write_ids"] = new JsonArray(r.Links.Select(l => (JsonNode?)l.MemoryVersionId).ToArray()),
        });
}
