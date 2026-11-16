using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Memory.Pgc;

namespace Aijade.Memory.V9;

// The database rows of the v9 write pipeline, as the kernel consumes them; the physical DDL lives with the server. Beliefs
// and evidence entries reuse the belief-graph types rather than a parallel definition.

public sealed record SessionRow(string Id, string SessionRef, double CreatedAt, double UpdatedAt, JsonObject? Meta = null);

public sealed record AssetRow(string Id, string Kind, string OwnerSessionId, JsonObject Payload, double CreatedAt);

/// <summary>An event as stored; the idempotency key is unique, which is what makes MemoryTx deduplication hold.</summary>
public sealed record EventRow(
    string Id, string EventId, string TraceId, string CorrelationId, double Timestamp, string Producer, string Topic, JsonNode? Payload,
    string IdempotencyKey, string ReplayMode, string RiskLevel);

public sealed record EvidencePackRow(string Id, string SessionId, string Source, double CreatedAt, string? Note = null);

public sealed record EvidenceChunkRow(string Id, string PackId, int Idx, string Content, double CreatedAt);

/// <summary>Session and trace make the four-dimensional state recoverable across turns; the v6 state is needed for the next transition.</summary>
public sealed record PgcStateRow(string Id, string SessionId, string TraceId, string PolicyVersion, PgcStateComponents Components, PgcState4 V6State, double CreatedAt);

/// <summary>
/// One write-plan entry as stored. The full snapshot that produced the decision is kept (not only its id): v10 §4.3 replay
/// needs the same endogenous state the w_max_at_f bound used, and an id alone can never be verified.
/// </summary>
public sealed record PgcWritePlanEntryRow(
    string MemoryWriteId, PgcDecision Decision, double FinalIntensity, IReadOnlyList<PgcReasonCode> ReasonCodes, IReadOnlyList<string> ExpectedTests,
    string PgcStateId, PgcStateSnapshot PgcStateSnapshot);

public sealed record PgcWritePlanRow(
    string Id, string PgcStateId, string SessionId, string TraceId, string PolicyVersion, IReadOnlyList<PgcWritePlanEntryRow> WritePlan,
    ContradictionReport ContradictionReport, double CreatedAt);

public enum TxAtomicity
{
    PerWrite,
    Bundle,
}

public enum TxStatus
{
    Committed,
    Rejected,
    Partial,
}

public sealed record MemoryTxRow(string Id, string SessionId, string TraceId, TxAtomicity Atomicity, int MaxWrites, TxStatus Status, double CreatedAt);

/// <summary>A memory version: only produced by a committed transaction, and always with its evidence pack and evidence chain.</summary>
public sealed record MemoryVersionRow(
    string Id, string MemoryTxId, string MemoryItemId, string MemoryWriteId, MemoryKind MemoryKind, string ContentHashSha256,
    string EvidencePackId, IReadOnlyList<string> EvidenceIds, string PgcStateId, double Intensity, double Durability, double CreatedAt,
    IReadOnlyList<string>? SourceClaimIds = null, string? RiskLevel = null);

public sealed record WeaveSpec(bool IncludePgcSnapshot, bool IncludeClaimIds, string? IncludeEvolutionSpecId = null);

public sealed record WeaveLink(string LinkId, string MemoryVersionId, IReadOnlyList<string> EvidenceIds, string PgcStateId, string? HypothesisId = null);

public sealed record EvidenceWeaveRow(string Id, string TxId, string GraphHash, WeaveSpec Spec, IReadOnlyList<WeaveLink> Links, double CreatedAt);

public sealed record EvolutionSpecRow(string Id, string Name, JsonObject Spec, double CreatedAt);

public sealed record EvalReportRow(string Id, string Name, JsonObject Metric, JsonObject Result, double CreatedAt);

public sealed record AuditLogEntryRow(string Id, string TxId, string Actor, string Action, double At, string? BeforeHash = null, string? AfterHash = null);

/// <summary>Deterministic hashes shared by the v9 kernel; replay checks need byte-identical results across runs.</summary>
public static class V9Hash
{
    /// <summary>sha256 of the canonical JSON (keys sorted); used as memory_versions.content_hash_sha256.</summary>
    public static string ContentHash(JsonNode? payload) => JsFormat.ContentHash(payload);

    /// <summary>
    /// sha256 of canonical { spec, links } with the links sorted by their canonical JSON (UTF-16 order), so link order
    /// never changes the hash; used as evidence_weaves.graph_hash.
    /// </summary>
    public static string GraphHash(IEnumerable<JsonNode?> links, JsonNode? spec)
    {
        var sorted = links.OrderBy(JsFormat.CanonicalJson, StringComparer.Ordinal).Select(l => l?.DeepClone()).ToArray();
        return JsFormat.Sha256Hex(JsFormat.CanonicalJson(new JsonObject { ["spec"] = spec?.DeepClone(), ["links"] = new JsonArray(sorted) }));
    }
}
