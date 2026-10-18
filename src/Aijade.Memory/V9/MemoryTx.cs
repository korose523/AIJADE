using System.Text.Json.Nodes;

using Aijade.Core.Js;
using Aijade.Memory.Dynamics;
using Aijade.Memory.Kernel;
using Aijade.Memory.Model;
using Aijade.Memory.Pgc;

namespace Aijade.Memory.V9;

// MemoryTx, the second gate of the v9 write pipeline. Hard constraints, enforced by the types and again at runtime:
// 1. memory versions come only from committed transactions — only the evidence-checked commit set creates one;
// 2. every version carries an evidence pack id and a non-empty evidence chain (a commit without them is rejected with
//    no_evidence, and AssertEvidenceChain throws if anything bypasses that);
// 3. the transaction id is the idempotency key: resubmitting returns the first result and creates nothing new.

public sealed record MemoryPayloadAttributes(
    IReadOnlyList<string> Tags, IReadOnlyList<string> SourceClaimIds, string? RiskLevel = null, ContentSalience? Salience = null);

public sealed record NormalizedPayload(MemoryKind MemoryKind, JsonNode? ContentObject, MemoryPayloadAttributes Attributes, string? EmbeddingInputText = null)
{
    /// <summary>The payload as hashed (snake_case keys; the hash sorts keys, so only names and values matter).</summary>
    public JsonObject ToJson()
    {
        var attributes = new JsonObject
        {
            ["tags"] = new JsonArray(Attributes.Tags.Select(t => (JsonNode?)t).ToArray()),
            ["source_claim_ids"] = new JsonArray(Attributes.SourceClaimIds.Select(t => (JsonNode?)t).ToArray()),
        };
        if (Attributes.RiskLevel is not null)
            attributes["risk_level"] = Attributes.RiskLevel;
        if (Attributes.Salience is { } s)
            attributes["salience"] = new JsonObject { ["salience"] = s.Salience, ["socialSalience"] = s.SocialSalience, ["novelty"] = s.Novelty };
        var o = new JsonObject { ["memory_kind"] = WireName.Of(MemoryKind), ["content_object"] = ContentObject?.DeepClone() };
        if (EmbeddingInputText is not null)
            o["embedding_input_text"] = EmbeddingInputText;
        o["attributes"] = attributes;
        return o;
    }
}

public sealed record Provenance(string Source, string Actor);

public sealed record MemoryPayload(string MemoryWriteId, NormalizedPayload NormalizedPayload, string EvidencePackId, IReadOnlyList<string> EvidenceIds, Provenance Provenance);

public sealed record TxPolicy(TxAtomicity Atomicity, int MaxWrites);

/// <summary>
/// How the event was observed (device, privacy level, continuous risk score). Only the runtime knows these; the engine must
/// not invent them. Evidence and causal refs default to values derived from the transaction itself; tick and causality are
/// propagated from the input event, never minted here.
/// </summary>
public sealed record MemoryTxEnvelopeContext(
    string OriginDevice, int PrivacyLevel, double RiskScore, IReadOnlyList<string>? CausalContextRefs = null, IReadOnlyList<string>? EvidenceRefs = null,
    int? Tick = null, string? CausalityInputHash = null);

public sealed record MemoryTxInput(
    string SessionId, string TraceId, IReadOnlyList<PgcWritePlanEntry> PgcWritePlan, IReadOnlyList<MemoryPayload> MemoryPayloads, TxPolicy TxPolicy,
    string? TxId = null, string? CapabilityToken = null, MemoryTxEnvelopeContext? EnvelopeContext = null);

/// <summary>
/// The gating audit of every write attempt. memory_version_id is explicitly null when nothing was stored, so "not stored"
/// is an assertable fact; without a v6 state the v6 diagnostics are null.
/// </summary>
public sealed record MemoryWriteGatingAudit(
    string MemoryWriteId, int? TauCaseId, Tau? Tau, double ThetaCommitThreshold, double? WMaxGlobal, double? WMaxAtF, double? W,
    bool? CommitPossible, CommitReason? CommitReason, string? MemoryVersionId, string? ContentHash);

public sealed record CommittedMemory(string MemoryItemId, string MemoryVersionId, string MemoryWriteId, MemoryWriteGatingAudit Gating);

public sealed record ThrottledMemory(string MemoryWriteId, PgcDecision Decision, MemoryWriteGatingAudit Gating);

public sealed record RejectedMemory(string MemoryWriteId, string Reason, MemoryWriteGatingAudit Gating);

public sealed record TxResult(
    string TxId, TxStatus Status, IReadOnlyList<CommittedMemory> Committed, IReadOnlyList<ThrottledMemory> Throttled, IReadOnlyList<RejectedMemory> Rejected,
    IReadOnlyList<AuditLogEntryRow> AuditLog, IReadOnlyList<JsonObject> Events);

public sealed class MemoryTxEngine(GatingCoefficients? gating = null, MemoryWriteGate? gate = null, TimeProvider? time = null)
{
    /// <summary>The engine's own signature when no observation context is given — deliberately not a device name.</summary>
    public const string UncontextedOrigin = "kernel:memory-tx";

    private readonly GatingCoefficients _gating = gating ?? GatingCoefficients.None;
    private readonly TimeProvider _time = time ?? TimeProvider.System;
    private readonly Dictionary<string, MemoryVersionRow> _versions = new(StringComparer.Ordinal);
    private readonly Dictionary<string, (MemoryKind Kind, string CurrentVersionId)> _items = new(StringComparer.Ordinal);
    private readonly Dictionary<string, List<string>> _txVersions = new(StringComparer.Ordinal);
    private readonly List<AuditLogEntryRow> _audit = [];
    private readonly Dictionary<string, TxResult> _results = new(StringComparer.Ordinal);

    public MemoryVersionRow? GetVersion(string id) => _versions.GetValueOrDefault(id);

    public IReadOnlyList<MemoryVersionRow> GetVersionsForTx(string txId) =>
        (_txVersions.GetValueOrDefault(txId) ?? []).Select(id => _versions[id]).ToList();

    public IReadOnlyList<AuditLogEntryRow> AuditLog => _audit;

    private static string MakeId(params string[] parts) => string.Join("_", parts);

    /// <summary>Second line of defence: creating a version without its evidence chain throws.</summary>
    private static void AssertEvidenceChain(string packId, IReadOnlyList<string> evidenceIds)
    {
        if (string.IsNullOrEmpty(packId))
            throw new InvalidOperationException("[memory-tx] evidence_pack_id 缺失：违反「每条 memory_version 必须带证据包」约束");
        if (evidenceIds.Count == 0)
            throw new InvalidOperationException("[memory-tx] evidence_ids 为空：违反「每条 memory_version 必须带证据链」约束");
    }

    private static MemoryWriteGatingAudit Audit(string writeId, PgcWritePlanEntry? entry, string? versionId, string? hash)
    {
        var theta = PgcGate.DefaultV6Policy.CommitMinW;
        if (entry?.PgcStateSnapshot.V6 is not { } v6)
            return new MemoryWriteGatingAudit(writeId, null, null, theta, null, null, null, null, null, versionId, hash);
        return new MemoryWriteGatingAudit(writeId, PgcGate.V6TauCaseId, v6.Tau, theta, v6.WMaxGlobal, v6.WMaxAtF, v6.W, v6.CommitPossible, v6.CommitReason, versionId, hash);
    }

    /// <summary>Commit a controlled write transaction. Idempotent: the same transaction id returns its first result.</summary>
    public TxResult Commit(MemoryTxInput input)
    {
        // With a capability gate configured, a commit without a token is refused here too (the runtime verifies the token itself).
        if (gate is not null && string.IsNullOrEmpty(input.CapabilityToken))
            throw new MemoryWriteDeniedException("memory write denied: missing capability token");

        var txId = input.TxId ?? MakeId("tx", input.SessionId, input.TraceId);
        if (_results.TryGetValue(txId, out var cached))
            return cached;

        var plan = new Dictionary<string, PgcWritePlanEntry>(StringComparer.Ordinal);
        foreach (var p in input.PgcWritePlan)
            plan[p.MemoryWriteId] = p;
        var now = (double)_time.GetUtcNow().ToUnixTimeMilliseconds();
        var committed = new List<CommittedMemory>();
        var throttled = new List<ThrottledMemory>();
        var rejected = new List<RejectedMemory>();
        PgcWritePlanEntry? EntryOf(string id) => plan.GetValueOrDefault(id);

        foreach (var p in input.MemoryPayloads)
        {
            var entry = EntryOf(p.MemoryWriteId);
            switch (entry?.Decision)
            {
                case PgcDecision.Commit:
                    break;
                case PgcDecision.Throttle or PgcDecision.Defer:
                    throttled.Add(new ThrottledMemory(p.MemoryWriteId, entry.Decision, Audit(p.MemoryWriteId, entry, null, null)));
                    break;
                default:
                    rejected.Add(new RejectedMemory(p.MemoryWriteId, entry is null ? "no_write_plan" : "pgc_rejected", Audit(p.MemoryWriteId, entry, null, null)));
                    break;
            }
        }

        var valid = new List<MemoryPayload>();
        foreach (var p in input.MemoryPayloads.Where(p => EntryOf(p.MemoryWriteId)?.Decision == PgcDecision.Commit))
        {
            if (string.IsNullOrEmpty(p.EvidencePackId) || p.EvidenceIds.Count == 0)
                rejected.Add(new RejectedMemory(p.MemoryWriteId, "no_evidence", Audit(p.MemoryWriteId, EntryOf(p.MemoryWriteId), null, null)));
            else
                valid.Add(p);
        }

        var final = valid;
        if (valid.Count > input.TxPolicy.MaxWrites)
        {
            foreach (var e in valid.Skip(input.TxPolicy.MaxWrites))
                rejected.Add(new RejectedMemory(e.MemoryWriteId, "tx_max_writes_exceeded", Audit(e.MemoryWriteId, EntryOf(e.MemoryWriteId), null, null)));
            final = valid.Take(input.TxPolicy.MaxWrites).ToList();
        }

        // Bundle atomicity: any failed commit candidate rolls back the whole bundle.
        if (input.TxPolicy.Atomicity == TxAtomicity.Bundle && rejected.Count > 0)
        {
            foreach (var p in final)
                rejected.Add(new RejectedMemory(p.MemoryWriteId, "bundle_rolled_back", Audit(p.MemoryWriteId, EntryOf(p.MemoryWriteId), null, null)));
            final = [];
        }

        foreach (var p in final)
        {
            var entry = plan[p.MemoryWriteId];
            AssertEvidenceChain(p.EvidencePackId, p.EvidenceIds);
            var itemId = MakeId("mi", p.MemoryWriteId);
            var versionId = MakeId("mv", txId, p.MemoryWriteId);
            var hash = V9Hash.ContentHash(p.NormalizedPayload.ToJson());
            var attrs = p.NormalizedPayload.Attributes;
            var durability = attrs.Salience is { } sal ? Gating.Durability(sal, _gating) : 1;
            var version = new MemoryVersionRow(versionId, txId, itemId, p.MemoryWriteId, p.NormalizedPayload.MemoryKind, hash, p.EvidencePackId,
                [.. p.EvidenceIds], entry.PgcStateSnapshot.PgcStateId, entry.FinalIntensity, durability, now, attrs.SourceClaimIds, attrs.RiskLevel);
            _versions[versionId] = version;
            _items[itemId] = (version.MemoryKind, versionId);
            if (!_txVersions.TryGetValue(txId, out var list))
                _txVersions[txId] = list = [];
            list.Add(versionId);
            _audit.Add(new AuditLogEntryRow(MakeId("aud", txId, p.MemoryWriteId), txId, p.Provenance.Actor, "memory_version.commit", now, AfterHash: hash));
            committed.Add(new CommittedMemory(itemId, versionId, p.MemoryWriteId, Audit(p.MemoryWriteId, entry, versionId, hash)));
        }

        var status = committed.Count > 0 && rejected.Count == 0 ? TxStatus.Committed
            : committed.Count == 0 && rejected.Count > 0 ? TxStatus.Rejected
            : TxStatus.Partial;

        var ctx = input.EnvelopeContext;
        var derivedEvidenceRefs = input.MemoryPayloads.SelectMany(p => p.EvidenceIds.Prepend(p.EvidencePackId)).Where(s => !string.IsNullOrEmpty(s)).Distinct(StringComparer.Ordinal);
        var envelope = new JsonObject
        {
            ["event_id"] = MakeId("evt", txId, "committed"),
            ["trace_id"] = input.TraceId,
            ["correlation_id"] = input.TraceId,
            ["timestamp"] = now,
            ["producer"] = "memory-tx",
            ["origin_device"] = ctx?.OriginDevice ?? UncontextedOrigin,
            ["privacy_level"] = ctx?.PrivacyLevel ?? 0,
            ["evidence_refs"] = Strings(ctx?.EvidenceRefs ?? derivedEvidenceRefs),
            ["causal_context_refs"] = Strings(ctx?.CausalContextRefs ?? [input.TraceId]),
            ["risk_score"] = ctx?.RiskScore ?? 0,
            ["idempotency_key"] = txId,
            ["replay_mode"] = "live",
            ["risk_level"] = committed.Any(c => _versions[c.MemoryVersionId].RiskLevel == "high") ? "high" : "low",
        };
        if (ctx?.Tick is { } tick)
            envelope["tick"] = tick;
        if (ctx?.CausalityInputHash is { } inputHash)
            envelope["causality"] = new JsonObject { ["inputHash"] = inputHash };
        var evt = AijadeEvents.Build(AijadeEvents.MemoryTxCommitted, envelope, new JsonObject
        {
            ["tx_id"] = txId,
            ["trace_id"] = input.TraceId,
            ["committed_count"] = committed.Count,
            ["rejected_count"] = rejected.Count,
            ["throttled_count"] = throttled.Count,
        });

        var result = new TxResult(txId, status, committed, throttled, rejected, _audit.Where(a => a.TxId == txId).ToList(), [evt]);
        _results[txId] = result;
        return result;
    }

    private static JsonArray Strings(IEnumerable<string> s) => new(s.Select(x => (JsonNode?)x).ToArray());

    /// <summary>The memory_txs row of a result (pure read of the current state).</summary>
    public MemoryTxRow ToMemoryTxRow(MemoryTxInput input, TxResult result) => new(
        result.TxId, input.SessionId, input.TraceId, input.TxPolicy.Atomicity, input.TxPolicy.MaxWrites, result.Status,
        result.Committed.Count > 0 && _versions.TryGetValue(result.Committed[0].MemoryVersionId, out var v) ? v.CreatedAt : _time.GetUtcNow().ToUnixTimeMilliseconds());
}
