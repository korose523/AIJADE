using Aijade.Server.Infrastructure;

using Npgsql;

namespace Aijade.Server.V9;

// The evidence layer as an explicit, queryable reference domain: the ids of a session's evidence packs and chunks, the
// beliefs, the session's memory versions and weave graph hashes; plus a pure check that a set of references all fall
// inside it. A dangling reference is never treated as anchored evidence.

public sealed record EvidenceDomainSnapshot(
    string SessionId, IReadOnlyList<string> EvidencePackIds, IReadOnlyList<string> EvidenceChunkIds, IReadOnlyList<string> BeliefIds,
    IReadOnlyList<string> MemoryVersionIds, IReadOnlyList<string> GraphHashes);

public sealed record EvidenceRefVerification(bool Ok, IReadOnlyList<string> Missing);

public sealed class EvidenceDomainService(NpgsqlDataSource db)
{
    /// <summary>Pure: every reference must be a known id of the domain; missing ones are listed (deduplicated, in order).</summary>
    public static EvidenceRefVerification Verify(IEnumerable<string> refs, EvidenceDomainSnapshot d)
    {
        var known = new HashSet<string>([.. d.EvidencePackIds, .. d.EvidenceChunkIds, .. d.BeliefIds, .. d.MemoryVersionIds, .. d.GraphHashes], StringComparer.Ordinal);
        var missing = refs.Distinct(StringComparer.Ordinal).Where(r => !known.Contains(r)).ToList();
        return new EvidenceRefVerification(missing.Count == 0, missing);
    }

    public async Task<EvidenceDomainSnapshot> GetAsync(string sessionId, CancellationToken ct = default)
    {
        await using var conn = await db.OpenConnectionAsync(ct).ConfigureAwait(false);
        var s = Sql.Text(sessionId);
        var packs = await Sql.QueryAsync(conn, null, "SELECT id FROM evidence_packs WHERE session_id = $1", r => r.GetString(0), ct, s).ConfigureAwait(false);
        var chunks = await Sql.QueryAsync(conn, null, "SELECT c.id FROM evidence_chunks c JOIN evidence_packs p ON p.id = c.pack_id WHERE p.session_id = $1",
            r => r.GetString(0), ct, Sql.Text(sessionId)).ConfigureAwait(false);
        // Beliefs carry no session column (scope / owner hold their reach): the companion's whole current belief domain.
        var beliefs = await Sql.QueryAsync(conn, null, "SELECT id FROM beliefs", r => r.GetString(0), ct).ConfigureAwait(false);
        var versions = await Sql.QueryAsync(conn, null, "SELECT v.id FROM memory_versions v JOIN memory_txs t ON t.id = v.memory_tx_id WHERE t.session_id = $1",
            r => r.GetString(0), ct, Sql.Text(sessionId)).ConfigureAwait(false);
        var hashes = await Sql.QueryAsync(conn, null, "SELECT w.graph_hash FROM evidence_weaves w JOIN memory_txs t ON t.id = w.tx_id WHERE t.session_id = $1",
            r => r.GetString(0), ct, Sql.Text(sessionId)).ConfigureAwait(false);
        return new EvidenceDomainSnapshot(sessionId, packs, chunks, beliefs, versions, hashes);
    }
}
